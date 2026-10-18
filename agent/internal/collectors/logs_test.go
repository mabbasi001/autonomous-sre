package collectors

import (
	"slices"
	"testing"
)

func TestLogsCollectConfiguredUnitsWithCursor(t *testing.T) {
	var calls [][]string
	fake := func(name string, args ...string) ([]byte, error) {
		calls = append(calls, args)
		return []byte("line one\nline two\n"), nil
	}

	logs := &Logs{Units: []LogUnit{{Unit: "nginx", MaxLines: 10}}, Run: fake}

	records := logs.Collect()
	if len(records) != 1 {
		t.Fatalf("records = %d", len(records))
	}
	data := records[0].Data
	if data["unit"] != "nginx" {
		t.Errorf("unit = %v", data["unit"])
	}
	lines := data["lines"].([]string)
	if len(lines) != 2 || lines[0] != "line one" {
		t.Errorf("lines = %v", lines)
	}
	if slices.Contains(calls[0], "--since") {
		t.Error("first collection must not pass --since")
	}

	logs.Collect()
	if !slices.Contains(calls[1], "--since") {
		t.Error("second collection must pass --since cursor")
	}
}

func TestLogsEmptyOutputEmitsNothing(t *testing.T) {
	logs := &Logs{
		Units: []LogUnit{{Unit: "nginx"}},
		Run:   func(string, ...string) ([]byte, error) { return []byte("\n"), nil },
	}
	if records := logs.Collect(); len(records) != 0 {
		t.Errorf("records = %v, want none for empty journal", records)
	}
}
