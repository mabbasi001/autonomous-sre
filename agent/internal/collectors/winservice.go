package collectors

import (
	"os/exec"
	"strings"
)

// WindowsService reports state for explicitly configured Windows services
// via the Service Control Manager. The parsing is OS-independent (tested
// with a fake runner); only the sc.exe call is Windows-specific at runtime.
type WindowsService struct {
	Units []string
	Run   func(name string, args ...string) ([]byte, error)
}

func (s *WindowsService) run(name string, args ...string) ([]byte, error) {
	if s.Run != nil {
		return s.Run(name, args...)
	}
	return exec.Command(name, args...).Output()
}

// scStateToActive maps SCM run states to the normalized active/inactive the
// detection rules and verification share with the systemd collector.
func scStateToActive(state string) string {
	switch strings.ToUpper(state) {
	case "RUNNING":
		return "active"
	case "STOPPED", "STOP_PENDING", "PAUSED":
		return "inactive"
	default:
		return strings.ToLower(state)
	}
}

func parseScState(output string) string {
	for _, line := range strings.Split(output, "\n") {
		line = strings.TrimSpace(line)
		if !strings.HasPrefix(line, "STATE") {
			continue
		}
		_, value, found := strings.Cut(line, ":")
		if !found {
			continue
		}
		fields := strings.Fields(value) // e.g. "4  RUNNING"
		if len(fields) >= 2 {
			return fields[1]
		}
	}
	return ""
}

func (s *WindowsService) Collect() []Record {
	var records []Record
	for _, unit := range s.Units {
		out, err := s.run("sc", "query", unit)
		if err != nil {
			records = append(records, event("windows.service", map[string]any{
				"unit": unit, "active_state": "unknown", "error": err.Error(),
			}))
			continue
		}
		state := parseScState(string(out))
		records = append(records, event("windows.service", map[string]any{
			"unit":         unit,
			"active_state": scStateToActive(state),
			"run_state":    state,
		}))
	}
	return records
}
