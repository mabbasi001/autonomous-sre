package executor

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/mabbasi001/autonomous-sre/agent/internal/transport"
)

func TestPollAcksExecutesAndReports(t *testing.T) {
	var acked, reported bool
	var reportedResult Result

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.Method == http.MethodGet && r.URL.Path == "/v1/agents/commands":
			json.NewEncoder(w).Encode(map[string]any{
				"commands": []map[string]any{{
					"id":         "cmd-1",
					"action":     "service.restart",
					"params":     map[string]any{"unit": "nginx"},
					"expires_at": time.Now().Add(time.Minute).Format(time.RFC3339),
				}},
			})
		case strings.HasSuffix(r.URL.Path, "/ack"):
			acked = true
			w.Write([]byte(`{"status":"delivered"}`))
		case strings.HasSuffix(r.URL.Path, "/result"):
			reported = true
			json.NewDecoder(r.Body).Decode(&reportedResult)
			w.Write([]byte(`{"status":"succeeded"}`))
		default:
			t.Errorf("unexpected request: %s %s", r.Method, r.URL.Path)
		}
	}))
	defer server.Close()

	var calls [][]string
	e, _ := New(t.TempDir(), []string{"nginx"})
	e.Run = fakeRun(&calls)
	client := &transport.Client{BaseURL: server.URL, AgentID: "a", Secret: "s"}

	if err := Poll(client, e); err != nil {
		t.Fatal(err)
	}
	if !acked || !reported {
		t.Fatalf("acked=%v reported=%v", acked, reported)
	}
	if reportedResult.Status != "succeeded" {
		t.Errorf("reported status = %s", reportedResult.Status)
	}
	if len(calls) != 1 {
		t.Errorf("executed %d times", len(calls))
	}
}

func TestPollRespectsRejectedAck(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.URL.Path == "/v1/agents/commands":
			json.NewEncoder(w).Encode(map[string]any{
				"commands": []map[string]any{{
					"id":     "cmd-1",
					"action": "service.restart",
					"params": map[string]any{"unit": "nginx"},
				}},
			})
		case strings.HasSuffix(r.URL.Path, "/ack"):
			w.WriteHeader(http.StatusConflict)
		case strings.HasSuffix(r.URL.Path, "/result"):
			t.Error("result must not be sent when ack is rejected")
		}
	}))
	defer server.Close()

	var calls [][]string
	e, _ := New(t.TempDir(), []string{"nginx"})
	e.Run = fakeRun(&calls)

	if err := Poll(&transport.Client{BaseURL: server.URL}, e); err != nil {
		t.Fatal(err)
	}
	if len(calls) != 0 {
		t.Error("nothing may execute without a successful ack")
	}
}
