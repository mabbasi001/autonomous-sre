package collectors

import "testing"

func metricsByName(records []Record) map[string]map[string]any {
	out := map[string]map[string]any{}
	for _, record := range records {
		if record.Path == MetricsPath {
			out[record.Data["name"].(string)] = record.Data
		}
	}
	return out
}

func TestHostReadsProcFiles(t *testing.T) {
	host := &Host{ProcRoot: "testdata/proc", DiskPath: "."}
	got := metricsByName(host.Collect())

	if v := got["host.mem_used_percent"]["value"].(float64); v != 75.0 {
		t.Errorf("mem_used_percent = %v, want 75", v)
	}
	if v := got["host.load1"]["value"].(float64); v != 1.25 {
		t.Errorf("load1 = %v", v)
	}
	if v := got["host.uptime_seconds"]["value"].(float64); v != 54321.0 {
		t.Errorf("uptime = %v", v)
	}
	if _, present := got["host.cpu_used_percent"]; present {
		t.Error("cpu percent should be absent on first sample (no delta)")
	}
	if _, present := got["host.disk_used_percent"]; !present {
		t.Error("disk_used_percent missing")
	}
	for _, data := range got {
		if data["event_id"] == "" || data["occurred_at"] == "" {
			t.Error("records must carry event_id and occurred_at")
		}
	}
}

func TestHostMissingProcIsQuiet(t *testing.T) {
	host := &Host{ProcRoot: "testdata/nonexistent", DiskPath: "."}
	got := metricsByName(host.Collect())
	if _, present := got["host.mem_used_percent"]; present {
		t.Error("should not report memory without proc files")
	}
}
