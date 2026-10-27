// Package config loads the agent's local configuration. Deliberately
// dependency-free so the agent stays a single static binary.
package config

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
	"strings"
)

// Config is the agent's local configuration.
type Config struct {
	// ControlPlaneURL is the outbound HTTPS endpoint of the platform API.
	ControlPlaneURL string
	// Environment this agent belongs to (development/staging/production).
	Environment string
	// StateDir holds the agent's credentials and local state.
	StateDir string
}

// Defaults returns a Config with safe defaults.
func Defaults() Config {
	return Config{
		ControlPlaneURL: "https://localhost:8000",
		Environment:     "development",
		StateDir:        "/var/lib/autonomous-sre",
	}
}

// Remote is the centrally managed collection config fetched from the
// control plane. Collection is allowlist-only: anything not listed here
// is not collected.
type Remote struct {
	CollectIntervalSeconds int               `json:"collect_interval_seconds"`
	Services               []string          `json:"services"`
	HTTPChecks             []HTTPCheckConfig `json:"http_checks"`
	LogUnits               []LogUnitConfig   `json:"log_units"`
	IISAppPools            []string          `json:"iis_app_pools"`
}

type HTTPCheckConfig struct {
	Name           string `json:"name"`
	URL            string `json:"url"`
	TimeoutSeconds int    `json:"timeout_seconds"`
}

type LogUnitConfig struct {
	Unit     string `json:"unit"`
	MaxLines int    `json:"max_lines"`
}

func ParseRemote(data []byte) (Remote, error) {
	remote := Remote{CollectIntervalSeconds: 60}
	err := json.Unmarshal(data, &remote)
	if remote.CollectIntervalSeconds <= 0 {
		remote.CollectIntervalSeconds = 60
	}
	return remote, err
}

// Load reads a config file of simple "key: value" lines. A missing file
// returns defaults so the agent can start before being configured.
func Load(path string) (Config, error) {
	cfg := Defaults()

	f, err := os.Open(path)
	if os.IsNotExist(err) {
		return cfg, nil
	}
	if err != nil {
		return cfg, err
	}
	defer f.Close()

	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		key, value, found := strings.Cut(line, ":")
		if !found {
			return cfg, fmt.Errorf("invalid config line: %q", line)
		}
		key = strings.TrimSpace(key)
		value = strings.TrimSpace(value)
		switch key {
		case "control_plane_url":
			cfg.ControlPlaneURL = value
		case "environment":
			cfg.Environment = value
		case "state_dir":
			cfg.StateDir = value
		default:
			// unknown keys are errors: config typos must not pass silently
			return cfg, fmt.Errorf("unknown config key: %q", key)
		}
	}
	return cfg, scanner.Err()
}
