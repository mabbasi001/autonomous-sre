package enrollment

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"testing"
)

func TestEnrollExchangesToken(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/agents/enroll" {
			t.Errorf("path = %s", r.URL.Path)
		}
		var req map[string]string
		json.NewDecoder(r.Body).Decode(&req)
		if req["token"] != "tok-123" || req["environment"] != "development" || req["hostname"] == "" {
			t.Errorf("unexpected request: %v", req)
		}
		w.WriteHeader(http.StatusCreated)
		json.NewEncoder(w).Encode(Credentials{AgentID: "a-1", Secret: "s-1"})
	}))
	defer server.Close()

	creds, err := Enroll(server.URL, "tok-123", "vm-01", "development")
	if err != nil {
		t.Fatal(err)
	}
	if creds.AgentID != "a-1" || creds.Secret != "s-1" {
		t.Errorf("creds = %+v", creds)
	}
}

func TestEnrollRejectedToken(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusUnauthorized)
	}))
	defer server.Close()

	if _, err := Enroll(server.URL, "bad", "vm-01", "development"); err == nil {
		t.Error("expected error for rejected enrollment")
	}
}

func TestSaveLoadRoundTrip(t *testing.T) {
	dir := t.TempDir()
	want := Credentials{AgentID: "a-1", Secret: "s-1"}
	if err := Save(dir, want); err != nil {
		t.Fatal(err)
	}

	info, err := os.Stat(credentialsPath(dir))
	if err != nil {
		t.Fatal(err)
	}
	if perm := info.Mode().Perm(); perm != 0o600 {
		t.Errorf("credentials file mode = %o, want 600", perm)
	}

	got, err := Load(dir)
	if err != nil {
		t.Fatal(err)
	}
	if got != want {
		t.Errorf("Load() = %+v, want %+v", got, want)
	}
}
