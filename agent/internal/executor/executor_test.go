package executor

import (
	"context"
	"strings"
	"testing"
	"time"
)

func fakeRun(calls *[][]string) func(context.Context, string, ...string) ([]byte, int, error) {
	return func(ctx context.Context, name string, args ...string) ([]byte, int, error) {
		*calls = append(*calls, append([]string{name}, args...))
		return []byte("ok"), 0, nil
	}
}

func newTestExecutor(t *testing.T, services ...string) (*Executor, *[][]string) {
	t.Helper()
	var calls [][]string
	e, err := New(t.TempDir(), services)
	if err != nil {
		t.Fatal(err)
	}
	e.Run = fakeRun(&calls)
	return e, &calls
}

func restart(id, unit string) Command {
	return Command{ID: id, Action: "service.restart", Params: map[string]any{"unit": unit}}
}

func TestAllowlistedRestartExecutes(t *testing.T) {
	e, calls := newTestExecutor(t, "nginx")
	result := e.Handle(restart("c1", "nginx"))
	if result.Status != "succeeded" {
		t.Fatalf("status = %s (%s)", result.Status, result.Error)
	}
	want := "sudo -n systemctl restart nginx"
	if got := strings.Join((*calls)[0], " "); got != want {
		t.Errorf("ran %q, want %q", got, want)
	}
}

func TestNonAllowlistedUnitRejected(t *testing.T) {
	e, calls := newTestExecutor(t, "nginx")
	result := e.Handle(restart("c1", "redis"))
	if result.Status != "rejected" || !strings.Contains(result.Error, "allowlist") {
		t.Fatalf("result = %+v", result)
	}
	if len(*calls) != 0 {
		t.Error("nothing may run for a non-allowlisted unit")
	}
}

func TestUnknownActionRejected(t *testing.T) {
	e, calls := newTestExecutor(t, "nginx")
	result := e.Handle(Command{ID: "c1", Action: "vm.delete"})
	if result.Status != "rejected" {
		t.Fatalf("result = %+v", result)
	}
	if len(*calls) != 0 {
		t.Error("unknown actions must never execute")
	}
}

func TestDuplicateDeliveryExecutesOnce(t *testing.T) {
	e, calls := newTestExecutor(t, "nginx")
	first := e.Handle(restart("c1", "nginx"))
	second := e.Handle(restart("c1", "nginx"))
	if first.Status != "succeeded" || second.Status != "duplicate" {
		t.Fatalf("first=%s second=%s", first.Status, second.Status)
	}
	if len(*calls) != 1 {
		t.Errorf("executed %d times, want 1", len(*calls))
	}
}

func TestDuplicateSuppressedAcrossRestart(t *testing.T) {
	dir := t.TempDir()
	var calls [][]string
	e, _ := New(dir, []string{"nginx"})
	e.Run = fakeRun(&calls)
	e.Handle(restart("c1", "nginx"))

	reopened, err := New(dir, []string{"nginx"})
	if err != nil {
		t.Fatal(err)
	}
	reopened.Run = fakeRun(&calls)
	result := reopened.Handle(restart("c1", "nginx"))
	if result.Status != "duplicate" {
		t.Fatalf("status after restart = %s", result.Status)
	}
	if len(calls) != 1 {
		t.Errorf("executed %d times, want 1", len(calls))
	}
}

func TestExpiredCommandRejected(t *testing.T) {
	e, calls := newTestExecutor(t, "nginx")
	cmd := restart("c1", "nginx")
	cmd.ExpiresAt = time.Now().Add(-time.Second)
	result := e.Handle(cmd)
	if result.Status != "rejected" || !strings.Contains(result.Error, "expired") {
		t.Fatalf("result = %+v", result)
	}
	if len(*calls) != 0 {
		t.Error("expired commands must never execute")
	}
}

func TestTimeoutKillsRunaway(t *testing.T) {
	e, _ := newTestExecutor(t, "nginx")
	e.Timeout = 50 * time.Millisecond
	e.Run = func(ctx context.Context, name string, args ...string) ([]byte, int, error) {
		<-ctx.Done()
		return nil, -1, ctx.Err()
	}
	result := e.Handle(restart("c1", "nginx"))
	if result.Status != "timeout" {
		t.Fatalf("status = %s", result.Status)
	}
}

func TestDefaultRunnerEnforcesContextDeadline(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 100*time.Millisecond)
	defer cancel()
	start := time.Now()
	_, _, err := runCommand(ctx, "/bin/sleep", "5")
	if err == nil {
		t.Fatal("expected error from killed process")
	}
	if elapsed := time.Since(start); elapsed > 2*time.Second {
		t.Fatalf("process not killed by deadline (took %s)", elapsed)
	}
}

func TestOutputBounded(t *testing.T) {
	e, _ := newTestExecutor(t, "nginx")
	e.Run = func(ctx context.Context, name string, args ...string) ([]byte, int, error) {
		return []byte(strings.Repeat("x", 10000)), 0, nil
	}
	result := e.Handle(restart("c1", "nginx"))
	if len(result.Output) != maxOutputBytes {
		t.Errorf("output length = %d, want %d", len(result.Output), maxOutputBytes)
	}
}
