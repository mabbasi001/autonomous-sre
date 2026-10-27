//go:build !windows

package executor

import "strconv"

func restartCommand(unit string) (string, []string) {
	return "sudo", []string{"-n", "systemctl", "restart", unit}
}

func statusCommand(unit string) (string, []string) {
	return "systemctl", []string{
		"show", "--no-pager", "--property=ActiveState,SubState,NRestarts", unit,
	}
}

// systemctl already emits "ActiveState=active"; no normalization needed.
func normalizeStatus(output string) string { return output }

func logsCommand(unit string, maxLines int) (string, []string) {
	return "journalctl", []string{"-u", unit, "-n", strconv.Itoa(maxLines), "--no-pager", "-o", "cat"}
}

func recycleCommand(pool string) (string, []string, bool) {
	return "", nil, false
}
