// Package enrollment exchanges a one-time token for agent credentials
// and persists them locally.
package enrollment

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"time"
)

type Credentials struct {
	AgentID string `json:"agent_id"`
	Secret  string `json:"secret"`
}

func Enroll(baseURL, token, hostname, environment string) (Credentials, error) {
	var creds Credentials
	body, err := json.Marshal(map[string]string{
		"token":       token,
		"hostname":    hostname,
		"environment": environment,
	})
	if err != nil {
		return creds, err
	}

	client := &http.Client{Timeout: 30 * time.Second}
	resp, err := client.Post(baseURL+"/v1/agents/enroll", "application/json", bytes.NewReader(body))
	if err != nil {
		return creds, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusCreated {
		return creds, fmt.Errorf("enrollment rejected: %s", resp.Status)
	}
	if err := json.NewDecoder(resp.Body).Decode(&creds); err != nil {
		return creds, err
	}
	return creds, nil
}

func credentialsPath(dir string) string {
	return filepath.Join(dir, "credentials.json")
}

func Save(dir string, creds Credentials) error {
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return err
	}
	data, err := json.Marshal(creds)
	if err != nil {
		return err
	}
	return os.WriteFile(credentialsPath(dir), data, 0o600)
}

func Load(dir string) (Credentials, error) {
	var creds Credentials
	data, err := os.ReadFile(credentialsPath(dir))
	if err != nil {
		return creds, err
	}
	err = json.Unmarshal(data, &creds)
	return creds, err
}
