//go:build windows

package executor

import (
	"os"
	"path/filepath"
	"strconv"
)

func appcmdPath() string {
	root := os.Getenv("SystemRoot")
	if root == "" {
		root = `C:\Windows`
	}
	return filepath.Join(root, "System32", "inetsrv", "appcmd.exe")
}

func restartCommand(unit string) (string, []string) {
	return "powershell", []string{
		"-NoProfile", "-NonInteractive", "-Command",
		"Restart-Service -Name '" + unit + "' -Force",
	}
}

func statusCommand(unit string) (string, []string) {
	return "sc", []string{"query", unit}
}

// normalizeStatus rewrites sc.exe output into the "ActiveState=active"
// shape the control-plane verification shares with the systemd path.
func normalizeStatus(output string) string {
	return normalizeWindowsStatus(output)
}

func logsCommand(unit string, maxLines int) (string, []string) {
	return "wevtutil", []string{"qe", "System", "/c:" + strconv.Itoa(maxLines), "/rd:true", "/f:text"}
}

func recycleCommand(pool string) (string, []string, bool) {
	return appcmdPath(), []string{"recycle", "apppool", "/apppool.name:" + pool}, true
}
