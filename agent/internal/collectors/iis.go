package collectors

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"unicode/utf16"
)

// decodeOutput handles appcmd, which emits UTF-16LE (with a BOM) when its
// output is redirected rather than written to a console.
func decodeOutput(b []byte) string {
	if len(b) >= 2 && b[0] == 0xFF && b[1] == 0xFE {
		b = b[2:]
		u16 := make([]uint16, len(b)/2)
		for i := range u16 {
			u16[i] = uint16(b[2*i]) | uint16(b[2*i+1])<<8
		}
		return string(utf16.Decode(u16))
	}
	return string(b)
}

// appcmdPath resolves appcmd.exe, which lives in inetsrv and is not on the
// default PATH (including a service account's).
func appcmdPath() string {
	root := os.Getenv("SystemRoot")
	if root == "" {
		root = `C:\Windows`
	}
	return filepath.Join(root, "System32", "inetsrv", "appcmd.exe")
}

// IIS reports application-pool state for explicitly configured pools via
// appcmd. Parsing is OS-independent (tested with a fake runner).
type IIS struct {
	AppPools []string
	Run      func(name string, args ...string) ([]byte, error)
}

func (c *IIS) run(name string, args ...string) ([]byte, error) {
	if c.Run != nil {
		return c.Run(name, args...)
	}
	return exec.Command(name, args...).Output()
}

func iisStateToActive(state string) string {
	switch strings.ToLower(state) {
	case "started":
		return "active"
	case "stopped":
		return "inactive"
	default:
		return strings.ToLower(state)
	}
}

// parseAppPoolState pulls the run state for a named pool out of
// `appcmd list apppool` output:
//
//	APPPOOL "DefaultAppPool" (MgdVersion:v4.0,MgdMode:Integrated,state:Started)
func parseAppPoolState(output, pool string) string {
	needle := `"` + pool + `"`
	for _, line := range strings.Split(output, "\n") {
		if !strings.Contains(line, needle) {
			continue
		}
		_, rest, found := strings.Cut(line, "state:")
		if !found {
			return ""
		}
		return strings.TrimRight(strings.TrimSpace(rest), ")")
	}
	return ""
}

func (c *IIS) Collect() []Record {
	if len(c.AppPools) == 0 {
		return nil
	}
	out, err := c.run(appcmdPath(), "list", "apppool")
	if err != nil {
		var records []Record
		for _, pool := range c.AppPools {
			records = append(records, event("iis.app_pool", map[string]any{
				"pool": pool, "active_state": "unknown", "error": err.Error(),
			}))
		}
		return records
	}

	decoded := decodeOutput(out)
	var records []Record
	for _, pool := range c.AppPools {
		state := parseAppPoolState(decoded, pool)
		records = append(records, event("iis.app_pool", map[string]any{
			"pool":         pool,
			"active_state": iisStateToActive(state),
			"mgmt_state":   state,
		}))
	}
	return records
}
