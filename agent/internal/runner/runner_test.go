package runner

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"
	"time"

	"github.com/mabbasi001/autonomous-sre/agent/internal/collectors"
	"github.com/mabbasi001/autonomous-sre/agent/internal/spool"
	"github.com/mabbasi001/autonomous-sre/agent/internal/transport"
)

type stubCollector struct{ records []collectors.Record }

func (s stubCollector) Collect() []collectors.Record { return s.records }

type fakeServer struct {
	mu        sync.Mutex
	available bool
	received  []string
}

func (f *fakeServer) handler(w http.ResponseWriter, r *http.Request) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if !f.available {
		w.WriteHeader(http.StatusServiceUnavailable)
		return
	}
	var body map[string][]map[string]any
	json.NewDecoder(r.Body).Decode(&body)
	for _, items := range body {
		for _, item := range items {
			if name, ok := item["name"].(string); ok {
				f.received = append(f.received, name)
			}
		}
	}
	w.WriteHeader(http.StatusOK)
	w.Write([]byte(`{"accepted": 1, "duplicates": 0}`))
}

func metricRecord(name string) collectors.Record {
	return collectors.Record{
		Path: collectors.MetricsPath,
		Data: map[string]any{
			"event_id":    name + "-0000-4000-8000-000000000000",
			"name":        name,
			"value":       1.0,
			"labels":      map[string]string{},
			"occurred_at": "2026-11-01T00:00:00Z",
		},
	}
}

func TestOutageSpoolsThenDrainsInOrder(t *testing.T) {
	server := &fakeServer{}
	ts := httptest.NewServer(http.HandlerFunc(server.handler))
	defer ts.Close()

	queue, err := spool.Open(t.TempDir(), 1<<20)
	if err != nil {
		t.Fatal(err)
	}
	run := &Runner{
		Client: &transport.Client{BaseURL: ts.URL, AgentID: "a", Secret: "s"},
		Spool:  queue,
		Collectors: []collectors.Collector{
			stubCollector{[]collectors.Record{metricRecord("m1"), metricRecord("m2")}},
		},
	}

	// control plane down: records must spool, nothing delivered
	run.Cycle()
	if queue.Len() != 2 {
		t.Fatalf("spool len = %d, want 2", queue.Len())
	}
	if len(server.received) != 0 {
		t.Fatal("nothing should have been delivered while down")
	}
	if run.backoffUntil.IsZero() {
		t.Fatal("failed drain must arm backoff")
	}

	// a second cycle during the outage keeps accumulating
	run.Cycle()
	if queue.Len() != 4 {
		t.Fatalf("spool len = %d, want 4", queue.Len())
	}

	// control plane back: everything drains in original order
	server.mu.Lock()
	server.available = true
	server.mu.Unlock()
	run.backoffUntil = time.Time{}

	run.Drain()
	if queue.Len() != 0 {
		t.Fatalf("spool len = %d after drain, want 0", queue.Len())
	}
	want := []string{"m1", "m2", "m1", "m2"}
	if len(server.received) != len(want) {
		t.Fatalf("received %v", server.received)
	}
	for i, name := range want {
		if server.received[i] != name {
			t.Fatalf("order broken: received %v, want %v", server.received, want)
		}
	}
}

func TestDrainRoutesToCorrectEndpoints(t *testing.T) {
	var paths []string
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		paths = append(paths, r.URL.Path)
		w.Write([]byte(`{}`))
	}))
	defer ts.Close()

	queue, _ := spool.Open(t.TempDir(), 1<<20)
	for _, record := range []collectors.Record{
		{Path: collectors.MetricsPath, Data: map[string]any{"name": "m"}},
		{Path: collectors.EventsPath, Data: map[string]any{"type": "t"}},
		{Path: collectors.LogsPath, Data: map[string]any{"unit": "u"}},
	} {
		data, _ := json.Marshal(record)
		queue.Append(data)
	}

	run := &Runner{Client: &transport.Client{BaseURL: ts.URL}, Spool: queue}
	run.Drain()

	if len(paths) != 3 {
		t.Fatalf("paths = %v", paths)
	}
	seen := map[string]bool{}
	for _, p := range paths {
		seen[p] = true
	}
	for _, p := range []string{collectors.MetricsPath, collectors.EventsPath, collectors.LogsPath} {
		if !seen[p] {
			t.Errorf("endpoint %s never called: %v", p, paths)
		}
	}
}
