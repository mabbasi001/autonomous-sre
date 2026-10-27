package executor

import "strings"

// normalizeWindowsStatus turns `sc query` output into the normalized
// "ActiveState=active|inactive" form the server-side verification parses,
// so verification stays platform-agnostic. Pure string processing, tested
// on any OS.
func normalizeWindowsStatus(output string) string {
	state := ""
	for _, line := range strings.Split(output, "\n") {
		line = strings.TrimSpace(line)
		if !strings.HasPrefix(line, "STATE") {
			continue
		}
		if _, value, found := strings.Cut(line, ":"); found {
			fields := strings.Fields(value)
			if len(fields) >= 2 {
				state = fields[1]
			}
		}
	}
	active := "inactive"
	if strings.EqualFold(state, "RUNNING") {
		active = "active"
	}
	return "ActiveState=" + active + "\nRunState=" + state
}
