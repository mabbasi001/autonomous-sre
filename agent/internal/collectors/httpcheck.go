package collectors

import (
	"net/http"
	"time"
)

type HTTPCheck struct {
	Name    string
	URL     string
	Timeout time.Duration
}

// HTTPChecker probes explicitly configured endpoints only.
type HTTPChecker struct {
	Checks []HTTPCheck
}

func (c *HTTPChecker) Collect() []Record {
	var records []Record
	for _, check := range c.Checks {
		timeout := check.Timeout
		if timeout == 0 {
			timeout = 5 * time.Second
		}
		client := &http.Client{Timeout: timeout}

		payload := map[string]any{"name": check.Name, "url": check.URL}
		start := time.Now()
		resp, err := client.Get(check.URL)
		payload["latency_ms"] = time.Since(start).Milliseconds()
		if err != nil {
			payload["ok"] = false
			payload["status_code"] = 0
			payload["error"] = err.Error()
		} else {
			payload["ok"] = resp.StatusCode >= 200 && resp.StatusCode < 400
			payload["status_code"] = resp.StatusCode
			if resp.TLS != nil && len(resp.TLS.PeerCertificates) > 0 {
				payload["tls_not_after"] = resp.TLS.PeerCertificates[0].NotAfter.UTC().Format(time.RFC3339)
			}
			resp.Body.Close()
		}
		records = append(records, event("http.check", payload))
	}
	return records
}
