//go:build windows

package collectors

import "unsafe"

var (
	globalMemoryStatusEx = kernel32.NewProc("GlobalMemoryStatusEx")
	getSystemTimes       = kernel32.NewProc("GetSystemTimes")
	getTickCount64       = kernel32.NewProc("GetTickCount64")
)

type memoryStatusEx struct {
	length               uint32
	memoryLoad           uint32
	totalPhys            uint64
	availPhys            uint64
	totalPageFile        uint64
	availPageFile        uint64
	totalVirtual         uint64
	availVirtual         uint64
	availExtendedVirtual uint64
}

type fileTime struct {
	low  uint32
	high uint32
}

func (f fileTime) uint64() uint64 {
	return uint64(f.high)<<32 | uint64(f.low)
}

// WindowsHost reads host metrics via kernel32 rather than /proc.
type WindowsHost struct {
	prevIdle  uint64
	prevTotal uint64
}

func (h *WindowsHost) Collect() []Record {
	var records []Record

	var mem memoryStatusEx
	mem.length = uint32(unsafe.Sizeof(mem))
	if ret, _, _ := globalMemoryStatusEx.Call(uintptr(unsafe.Pointer(&mem))); ret != 0 {
		records = append(records,
			metric("host.mem_used_percent", float64(mem.memoryLoad), nil),
			metric("host.mem_total_bytes", float64(mem.totalPhys), nil),
		)
	}

	if cpu, ok := h.cpuPercent(); ok {
		records = append(records, metric("host.cpu_used_percent", cpu, nil))
	}

	if ret, _, _ := getTickCount64.Call(); ret != 0 {
		records = append(records, metric("host.uptime_seconds", float64(ret)/1000, nil))
	}

	if used, err := diskUsedPercent("C:\\"); err == nil {
		records = append(records,
			metric("host.disk_used_percent", used, map[string]string{"mount": "C:"}))
	}
	return records
}

func (h *WindowsHost) cpuPercent() (float64, bool) {
	var idle, kernel, user fileTime
	ret, _, _ := getSystemTimes.Call(
		uintptr(unsafe.Pointer(&idle)),
		uintptr(unsafe.Pointer(&kernel)),
		uintptr(unsafe.Pointer(&user)),
	)
	if ret == 0 {
		return 0, false
	}
	// on Windows kernel time already includes idle time
	total := kernel.uint64() + user.uint64()
	idleTime := idle.uint64()

	prevIdle, prevTotal := h.prevIdle, h.prevTotal
	h.prevIdle, h.prevTotal = idleTime, total
	if prevTotal == 0 || total == prevTotal {
		return 0, false
	}
	busy := (total - prevTotal) - (idleTime - prevIdle)
	return float64(busy) / float64(total-prevTotal) * 100, true
}
