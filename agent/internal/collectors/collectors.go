// Package collectors gathers host and workload signals as records ready
// to ship to the control plane.
package collectors

import (
	"crypto/rand"
	"fmt"
	"time"
)

const (
	MetricsPath = "/v1/telemetry/metrics"
	LogsPath    = "/v1/telemetry/logs"
	EventsPath  = "/v1/events"
)

// Record is one collected datum plus the ingestion endpoint it belongs to.
type Record struct {
	Path string         `json:"path"`
	Data map[string]any `json:"data"`
}

type Collector interface {
	Collect() []Record
}

func newEventID() string {
	b := make([]byte, 16)
	rand.Read(b)
	b[6] = (b[6] & 0x0f) | 0x40
	b[8] = (b[8] & 0x3f) | 0x80
	return fmt.Sprintf("%x-%x-%x-%x-%x", b[0:4], b[4:6], b[6:8], b[8:10], b[10:16])
}

func stamp(data map[string]any) map[string]any {
	data["event_id"] = newEventID()
	data["occurred_at"] = time.Now().UTC().Format(time.RFC3339)
	return data
}

func metric(name string, value float64, labels map[string]string) Record {
	if labels == nil {
		labels = map[string]string{}
	}
	return Record{
		Path: MetricsPath,
		Data: stamp(map[string]any{"name": name, "value": value, "labels": labels}),
	}
}

func event(eventType string, payload map[string]any) Record {
	return Record{
		Path: EventsPath,
		Data: stamp(map[string]any{"type": eventType, "payload": payload}),
	}
}

func logExcerpt(unit string, lines []string) Record {
	return Record{
		Path: LogsPath,
		Data: stamp(map[string]any{"unit": unit, "lines": lines}),
	}
}
