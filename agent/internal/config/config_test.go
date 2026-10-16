package config

import (
	"os"
	"path/filepath"
	"testing"
)

func TestLoadMissingFileReturnsDefaults(t *testing.T) {
	cfg, err := Load("/nonexistent/agent.yaml")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if cfg.Environment != "development" {
		t.Errorf("expected default environment, got %q", cfg.Environment)
	}
}

func TestLoadParsesValues(t *testing.T) {
	path := filepath.Join(t.TempDir(), "agent.yaml")
	content := "# comment\ncontrol_plane_url: https://sre.internal:8443\nenvironment: staging\n"
	if err := os.WriteFile(path, []byte(content), 0o600); err != nil {
		t.Fatal(err)
	}

	cfg, err := Load(path)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if cfg.ControlPlaneURL != "https://sre.internal:8443" {
		t.Errorf("control_plane_url = %q", cfg.ControlPlaneURL)
	}
	if cfg.Environment != "staging" {
		t.Errorf("environment = %q", cfg.Environment)
	}
}

func TestLoadRejectsUnknownKeys(t *testing.T) {
	path := filepath.Join(t.TempDir(), "agent.yaml")
	if err := os.WriteFile(path, []byte("tpyo_key: oops\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := Load(path); err == nil {
		t.Error("expected error for unknown key, got nil")
	}
}
