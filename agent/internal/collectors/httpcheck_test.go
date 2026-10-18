package collectors

import (
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func TestHTTPCheckReportsStatusAndLatency(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))
	defer server.Close()

	checker := &HTTPChecker{Checks: []HTTPCheck{{Name: "web", URL: server.URL}}}
	records := checker.Collect()
	if len(records) != 1 {
		t.Fatalf("records = %d", len(records))
	}
	payload := records[0].Data["payload"].(map[string]any)
	if payload["ok"] != true || payload["status_code"] != 200 {
		t.Errorf("payload = %v", payload)
	}
	if _, hasLatency := payload["latency_ms"]; !hasLatency {
		t.Error("latency_ms missing")
	}
}

func TestHTTPCheckUnreachableEndpoint(t *testing.T) {
	checker := &HTTPChecker{Checks: []HTTPCheck{{
		Name:    "down",
		URL:     "http://127.0.0.1:1",
		Timeout: time.Second,
	}}}
	payload := checker.Collect()[0].Data["payload"].(map[string]any)
	if payload["ok"] != false || payload["status_code"] != 0 {
		t.Errorf("payload = %v", payload)
	}
	if payload["error"] == "" {
		t.Error("error detail missing")
	}
}
