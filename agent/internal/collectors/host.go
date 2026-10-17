package collectors

import (
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

// Host reads memory, load, uptime and cpu from proc and disk usage from
// statfs. ProcRoot is overridable for tests.
type Host struct {
	ProcRoot string
	DiskPath string

	prevTotal uint64
	prevIdle  uint64
}

func (h *Host) root() string {
	if h.ProcRoot == "" {
		return "/proc"
	}
	return h.ProcRoot
}

func (h *Host) Collect() []Record {
	var records []Record

	if total, available, ok := h.meminfo(); ok && total > 0 {
		usedPercent := (1 - float64(available)/float64(total)) * 100
		records = append(records,
			metric("host.mem_used_percent", usedPercent, nil),
			metric("host.mem_total_bytes", float64(total), nil),
		)
	}
	if load1, ok := h.firstFloat("loadavg"); ok {
		records = append(records, metric("host.load1", load1, nil))
	}
	if uptime, ok := h.firstFloat("uptime"); ok {
		records = append(records, metric("host.uptime_seconds", uptime, nil))
	}
	if cpu, ok := h.cpuPercent(); ok {
		records = append(records, metric("host.cpu_used_percent", cpu, nil))
	}

	diskPath := h.DiskPath
	if diskPath == "" {
		diskPath = "/"
	}
	if used, err := diskUsedPercent(diskPath); err == nil {
		records = append(records, metric("host.disk_used_percent", used, map[string]string{"mount": diskPath}))
	}
	return records
}

func (h *Host) meminfo() (total, available uint64, ok bool) {
	data, err := os.ReadFile(filepath.Join(h.root(), "meminfo"))
	if err != nil {
		return 0, 0, false
	}
	for _, line := range strings.Split(string(data), "\n") {
		fields := strings.Fields(line)
		if len(fields) < 2 {
			continue
		}
		kb, err := strconv.ParseUint(fields[1], 10, 64)
		if err != nil {
			continue
		}
		switch fields[0] {
		case "MemTotal:":
			total = kb * 1024
		case "MemAvailable:":
			available = kb * 1024
		}
	}
	return total, available, total > 0
}

func (h *Host) firstFloat(file string) (float64, bool) {
	data, err := os.ReadFile(filepath.Join(h.root(), file))
	if err != nil {
		return 0, false
	}
	fields := strings.Fields(string(data))
	if len(fields) == 0 {
		return 0, false
	}
	value, err := strconv.ParseFloat(fields[0], 64)
	return value, err == nil
}

func (h *Host) cpuPercent() (float64, bool) {
	data, err := os.ReadFile(filepath.Join(h.root(), "stat"))
	if err != nil {
		return 0, false
	}
	line, _, _ := strings.Cut(string(data), "\n")
	fields := strings.Fields(line)
	if len(fields) < 8 || fields[0] != "cpu" {
		return 0, false
	}
	var total, idle uint64
	for i, raw := range fields[1:] {
		v, err := strconv.ParseUint(raw, 10, 64)
		if err != nil {
			return 0, false
		}
		total += v
		if i == 3 || i == 4 { // idle + iowait
			idle += v
		}
	}
	prevTotal, prevIdle := h.prevTotal, h.prevIdle
	h.prevTotal, h.prevIdle = total, idle
	if prevTotal == 0 || total == prevTotal {
		return 0, false // first sample has no delta
	}
	return (1 - float64(idle-prevIdle)/float64(total-prevTotal)) * 100, true
}
