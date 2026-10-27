//go:build windows

package collectors

// PlatformHost returns the host-metrics collector for the current OS.
func PlatformHost() Collector {
	return &WindowsHost{}
}
