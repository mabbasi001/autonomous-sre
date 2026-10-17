package collectors

import (
	"strings"
	"testing"
)

func TestSystemdCollectsOnlyConfiguredUnits(t *testing.T) {
	var queried []string
	fake := func(name string, args ...string) ([]byte, error) {
		queried = append(queried, args[1])
		return []byte("ActiveState=inactive\nSubState=dead\nNRestarts=2\n"), nil
	}

	s := &Systemd{Units: []string{"nginx"}, Run: fake}
	records := s.Collect()

	if strings.Join(queried, ",") != "nginx" {
		t.Errorf("queried units = %v, want only nginx", queried)
	}
	if len(records) != 1 {
		t.Fatalf("records = %d, want 1", len(records))
	}
	payload := records[0].Data["payload"].(map[string]any)
	if payload["active_state"] != "inactive" || payload["restarts"] != 2 {
		t.Errorf("payload = %v", payload)
	}
	if records[0].Path != EventsPath {
		t.Errorf("path = %s", records[0].Path)
	}
}

func TestSystemdNoUnitsNoRecords(t *testing.T) {
	called := false
	s := &Systemd{Run: func(string, ...string) ([]byte, error) { called = true; return nil, nil }}
	if records := s.Collect(); len(records) != 0 || called {
		t.Error("unconfigured collector must not query or emit anything")
	}
}
