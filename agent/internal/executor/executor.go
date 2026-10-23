// Package executor runs typed catalogue actions delivered by the control
// plane. Commands execute at most once: the command ID is persisted to
// disk before execution, so a redelivery - even across an agent restart
// or a crash mid-execution - is suppressed rather than re-run.
package executor

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"sync"
	"time"
)

const (
	defaultTimeout = 30 * time.Second
	maxOutputBytes = 4096
	maxExecutedIDs = 1000
)

type Command struct {
	ID        string         `json:"id"`
	Action    string         `json:"action"`
	Params    map[string]any `json:"params"`
	ExpiresAt time.Time      `json:"expires_at"`
}

type Result struct {
	Status     string `json:"status"`
	ExitStatus *int   `json:"exit_status,omitempty"`
	Output     string `json:"output,omitempty"`
	Error      string `json:"error,omitempty"`
	DurationMS int64  `json:"duration_ms"`
}

type Executor struct {
	Timeout time.Duration
	Run     func(ctx context.Context, name string, args ...string) ([]byte, int, error)

	mu       sync.Mutex
	stateDir string
	allowed  map[string]bool
	executed map[string]bool
	order    []string
}

func New(stateDir string, allowedServices []string) (*Executor, error) {
	e := &Executor{
		Timeout:  defaultTimeout,
		stateDir: stateDir,
		executed: map[string]bool{},
	}
	e.SetAllowedServices(allowedServices)

	data, err := os.ReadFile(e.executedPath())
	if err == nil {
		var ids []string
		if err := json.Unmarshal(data, &ids); err != nil {
			return nil, fmt.Errorf("corrupt executed-commands file: %w", err)
		}
		for _, id := range ids {
			e.executed[id] = true
		}
		e.order = ids
	} else if !os.IsNotExist(err) {
		return nil, err
	}
	return e, nil
}

func (e *Executor) executedPath() string {
	return filepath.Join(e.stateDir, "executed.json")
}

func (e *Executor) SetAllowedServices(services []string) {
	allowed := make(map[string]bool, len(services))
	for _, service := range services {
		allowed[service] = true
	}
	e.mu.Lock()
	e.allowed = allowed
	e.mu.Unlock()
}

func (e *Executor) serviceAllowed(unit string) bool {
	e.mu.Lock()
	defer e.mu.Unlock()
	return e.allowed[unit]
}

// markExecuted persists the ID before anything runs, so a crash between
// here and completion can never lead to a second execution.
func (e *Executor) markExecuted(id string) error {
	e.mu.Lock()
	defer e.mu.Unlock()
	if e.executed[id] {
		return nil
	}
	e.executed[id] = true
	e.order = append(e.order, id)
	if len(e.order) > maxExecutedIDs {
		for _, old := range e.order[:len(e.order)-maxExecutedIDs] {
			delete(e.executed, old)
		}
		e.order = e.order[len(e.order)-maxExecutedIDs:]
	}
	data, err := json.Marshal(e.order)
	if err != nil {
		return err
	}
	return os.WriteFile(e.executedPath(), data, 0o600)
}

func (e *Executor) alreadyExecuted(id string) bool {
	e.mu.Lock()
	defer e.mu.Unlock()
	return e.executed[id]
}

func (e *Executor) Handle(cmd Command) Result {
	if !cmd.ExpiresAt.IsZero() && time.Now().After(cmd.ExpiresAt) {
		return Result{Status: "rejected", Error: "command expired"}
	}
	if e.alreadyExecuted(cmd.ID) {
		return Result{Status: "duplicate", Error: "command already handled; outcome unknown to this delivery"}
	}
	if err := e.markExecuted(cmd.ID); err != nil {
		return Result{Status: "failed", Error: "cannot persist execution record: " + err.Error()}
	}

	start := time.Now()
	result := e.dispatch(cmd)
	result.DurationMS = time.Since(start).Milliseconds()
	return result
}

func (e *Executor) dispatch(cmd Command) Result {
	switch cmd.Action {
	case "service.restart":
		return e.serviceCommand(cmd, "sudo", "-n", "systemctl", "restart")
	case "service.status":
		return e.serviceCommand(cmd, "systemctl", "show", "--no-pager")
	case "logs.collect_excerpt":
		return e.collectLogs(cmd)
	case "http.check":
		return e.httpCheck(cmd)
	default:
		return Result{Status: "rejected", Error: "unknown action: " + cmd.Action}
	}
}

func (e *Executor) serviceCommand(cmd Command, name string, args ...string) Result {
	unit, ok := cmd.Params["unit"].(string)
	if !ok || unit == "" {
		return Result{Status: "rejected", Error: "missing unit parameter"}
	}
	if !e.serviceAllowed(unit) {
		return Result{Status: "rejected", Error: "unit not in local allowlist: " + unit}
	}
	return e.run(name, append(args, unit)...)
}

func (e *Executor) collectLogs(cmd Command) Result {
	unit, ok := cmd.Params["unit"].(string)
	if !ok || !e.serviceAllowed(unit) {
		return Result{Status: "rejected", Error: "unit not in local allowlist"}
	}
	maxLines := 50
	if n, ok := cmd.Params["max_lines"].(float64); ok && n > 0 && n <= 200 {
		maxLines = int(n)
	}
	return e.run("journalctl", "-u", unit, "-n", strconv.Itoa(maxLines), "--no-pager", "-o", "cat")
}

func (e *Executor) httpCheck(cmd Command) Result {
	url, ok := cmd.Params["url"].(string)
	if !ok || url == "" {
		return Result{Status: "rejected", Error: "missing url parameter"}
	}
	client := &http.Client{Timeout: e.timeout()}
	resp, err := client.Get(url)
	if err != nil {
		return Result{Status: "failed", Error: err.Error()}
	}
	defer resp.Body.Close()
	io.Copy(io.Discard, io.LimitReader(resp.Body, 1<<16))
	status := resp.StatusCode
	result := Result{Output: fmt.Sprintf("status_code=%d", status), ExitStatus: &status}
	if status >= 200 && status < 400 {
		result.Status = "succeeded"
	} else {
		result.Status = "failed"
	}
	return result
}

func (e *Executor) timeout() time.Duration {
	if e.Timeout > 0 {
		return e.Timeout
	}
	return defaultTimeout
}

func (e *Executor) run(name string, args ...string) Result {
	ctx, cancel := context.WithTimeout(context.Background(), e.timeout())
	defer cancel()

	runner := e.Run
	if runner == nil {
		runner = runCommand
	}
	output, exitCode, err := runner(ctx, name, args...)
	if len(output) > maxOutputBytes {
		output = output[:maxOutputBytes]
	}

	result := Result{Output: string(output), ExitStatus: &exitCode}
	switch {
	case ctx.Err() == context.DeadlineExceeded:
		result.Status = "timeout"
		result.Error = "execution timed out"
	case err != nil:
		result.Status = "failed"
		result.Error = err.Error()
	default:
		result.Status = "succeeded"
	}
	return result
}

func runCommand(ctx context.Context, name string, args ...string) ([]byte, int, error) {
	cmd := exec.CommandContext(ctx, name, args...)
	output, err := cmd.CombinedOutput()
	exitCode := -1
	if cmd.ProcessState != nil {
		exitCode = cmd.ProcessState.ExitCode()
	}
	return output, exitCode, err
}
