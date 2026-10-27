package executor

import (
	"strings"
	"testing"
)

func TestNormalizeWindowsStatus(t *testing.T) {
	running := "SERVICE_NAME: W3SVC\n        STATE              : 4  RUNNING\n"
	if got := normalizeWindowsStatus(running); !strings.Contains(got, "ActiveState=active") {
		t.Errorf("running normalized to %q", got)
	}

	stopped := "SERVICE_NAME: W3SVC\n        STATE              : 1  STOPPED\n"
	out := normalizeWindowsStatus(stopped)
	if !strings.Contains(out, "ActiveState=inactive") || !strings.Contains(out, "RunState=STOPPED") {
		t.Errorf("stopped normalized to %q", out)
	}
}
