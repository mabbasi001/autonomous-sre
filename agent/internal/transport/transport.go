// Package transport signs and sends requests to the control plane.
package transport

import (
	"bytes"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"strconv"
	"strings"
	"time"
)

// Sign computes the request signature the control plane verifies:
// HMAC-SHA256 over "method\npath\ntimestamp\nsha256(body)".
func Sign(secret, method, path, timestamp string, body []byte) string {
	bodyHash := sha256.Sum256(body)
	payload := strings.Join([]string{method, path, timestamp, hex.EncodeToString(bodyHash[:])}, "\n")
	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write([]byte(payload))
	return hex.EncodeToString(mac.Sum(nil))
}

type Client struct {
	BaseURL string
	AgentID string
	Secret  string
	HTTP    *http.Client
}

func (c *Client) Post(path string, payload any) (*http.Response, error) {
	body, err := json.Marshal(payload)
	if err != nil {
		return nil, err
	}
	req, err := http.NewRequest(http.MethodPost, c.BaseURL+path, bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	ts := strconv.FormatInt(time.Now().Unix(), 10)
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Agent-Id", c.AgentID)
	req.Header.Set("X-Timestamp", ts)
	req.Header.Set("X-Signature", Sign(c.Secret, http.MethodPost, path, ts, body))

	httpClient := c.HTTP
	if httpClient == nil {
		httpClient = &http.Client{Timeout: 30 * time.Second}
	}
	return httpClient.Do(req)
}
