// Package runner drives the collect → spool → drain cycle. Everything
// goes through the spool so delivery order and crash-safety come from one
// code path, whether the control plane is reachable or not.
package runner

import (
	"encoding/json"
	"log"
	"math/rand"
	"net/http"
	"time"

	"github.com/mabbasi001/autonomous-sre/agent/internal/collectors"
	"github.com/mabbasi001/autonomous-sre/agent/internal/spool"
	"github.com/mabbasi001/autonomous-sre/agent/internal/transport"
)

var batchFields = map[string]string{
	collectors.MetricsPath: "metrics",
	collectors.LogsPath:    "logs",
	collectors.EventsPath:  "events",
}

const (
	drainBatchSize = 100
	minBackoff     = time.Second
	maxBackoff     = 5 * time.Minute
)

type Runner struct {
	Client     *transport.Client
	Spool      *spool.Spool
	Collectors []collectors.Collector

	backoff      time.Duration
	backoffUntil time.Time
}

func (r *Runner) Cycle() {
	for _, collector := range r.Collectors {
		for _, record := range collector.Collect() {
			data, err := json.Marshal(record)
			if err != nil {
				continue
			}
			if err := r.Spool.Append(data); err != nil {
				log.Printf("spool append failed: %v", err)
			}
		}
	}
	r.Drain()
}

func (r *Runner) Drain() {
	if time.Now().Before(r.backoffUntil) {
		return
	}
	for {
		items, ack, err := r.Spool.NextBatch(drainBatchSize)
		if err != nil || len(items) == 0 {
			return
		}
		if !r.send(items) {
			r.backoff = min(max(2*r.backoff, minBackoff), maxBackoff)
			jitter := 0.5 + rand.Float64()
			r.backoffUntil = time.Now().Add(time.Duration(float64(r.backoff) * jitter))
			return // no ack: retry after backoff, server dedupes by event_id
		}
		r.backoff = 0
		if err := ack(); err != nil {
			log.Printf("spool ack failed: %v", err)
			return
		}
	}
}

// send groups items by endpoint, preserving order within each stream.
func (r *Runner) send(items [][]byte) bool {
	grouped := map[string][]map[string]any{}
	var order []string
	for _, raw := range items {
		var record collectors.Record
		if err := json.Unmarshal(raw, &record); err != nil {
			continue // malformed spool entry: skip rather than wedge the queue
		}
		if _, seen := grouped[record.Path]; !seen {
			order = append(order, record.Path)
		}
		grouped[record.Path] = append(grouped[record.Path], record.Data)
	}

	for _, path := range order {
		field, known := batchFields[path]
		if !known {
			continue
		}
		resp, err := r.Client.Post(path, map[string]any{field: grouped[path]})
		if err != nil {
			log.Printf("send %s failed: %v", path, err)
			return false
		}
		resp.Body.Close()
		if resp.StatusCode != http.StatusOK {
			log.Printf("send %s rejected: %s", path, resp.Status)
			return false
		}
	}
	return true
}
