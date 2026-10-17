package collectors

import (
	"os/exec"
	"strconv"
	"strings"
)

// Systemd reports state for explicitly configured units only.
type Systemd struct {
	Units []string
	Run   func(name string, args ...string) ([]byte, error)
}

func (s *Systemd) run(name string, args ...string) ([]byte, error) {
	if s.Run != nil {
		return s.Run(name, args...)
	}
	return exec.Command(name, args...).Output()
}

func (s *Systemd) Collect() []Record {
	var records []Record
	for _, unit := range s.Units {
		out, err := s.run("systemctl", "show", unit, "--property=ActiveState,SubState,NRestarts")
		if err != nil {
			records = append(records, event("systemd.service", map[string]any{
				"unit": unit, "active_state": "unknown", "error": err.Error(),
			}))
			continue
		}
		props := map[string]string{}
		for _, line := range strings.Split(strings.TrimSpace(string(out)), "\n") {
			if key, value, found := strings.Cut(line, "="); found {
				props[key] = value
			}
		}
		restarts, _ := strconv.Atoi(props["NRestarts"])
		records = append(records, event("systemd.service", map[string]any{
			"unit":         unit,
			"active_state": props["ActiveState"],
			"sub_state":    props["SubState"],
			"restarts":     restarts,
		}))
	}
	return records
}
