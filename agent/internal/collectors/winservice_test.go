package collectors

import "testing"

const scRunning = `SERVICE_NAME: W3SVC
        TYPE               : 20  WIN32_SHARE_PROCESS
        STATE              : 4  RUNNING
        WIN32_EXIT_CODE    : 0  (0x0)
`

const scStopped = `SERVICE_NAME: W3SVC
        TYPE               : 20  WIN32_SHARE_PROCESS
        STATE              : 1  STOPPED
`

func TestWindowsServiceNormalizesState(t *testing.T) {
	cases := map[string]string{scRunning: "active", scStopped: "inactive"}
	for output, want := range cases {
		var queried []string
		s := &WindowsService{
			Units: []string{"W3SVC"},
			Run: func(name string, args ...string) ([]byte, error) {
				queried = append(queried, args...)
				return []byte(output), nil
			},
		}
		records := s.Collect()
		if len(records) != 1 || records[0].Path != EventsPath {
			t.Fatalf("records = %v", records)
		}
		payload := records[0].Data["payload"].(map[string]any)
		if payload["active_state"] != want {
			t.Errorf("active_state = %v, want %v", payload["active_state"], want)
		}
		if payload["unit"] != "W3SVC" {
			t.Errorf("unit = %v", payload["unit"])
		}
	}
}

func TestWindowsServiceOnlyConfiguredUnits(t *testing.T) {
	var queried []string
	s := &WindowsService{
		Units: []string{"W3SVC"},
		Run: func(name string, args ...string) ([]byte, error) {
			queried = append(queried, args[1])
			return []byte(scRunning), nil
		},
	}
	s.Collect()
	if len(queried) != 1 || queried[0] != "W3SVC" {
		t.Errorf("queried = %v, want only W3SVC", queried)
	}
}

func TestWindowsServiceErrorReported(t *testing.T) {
	s := &WindowsService{
		Units: []string{"Missing"},
		Run:   func(string, ...string) ([]byte, error) { return nil, errFake },
	}
	payload := s.Collect()[0].Data["payload"].(map[string]any)
	if payload["active_state"] != "unknown" {
		t.Errorf("payload = %v", payload)
	}
}
