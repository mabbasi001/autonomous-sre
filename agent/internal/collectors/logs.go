package collectors

import (
	"os/exec"
	"strconv"
	"strings"
	"time"
)

type LogUnit struct {
	Unit     string
	MaxLines int
}

// Logs collects bounded journal excerpts from configured units, keeping a
// per-unit cursor so lines are not re-read every cycle.
type Logs struct {
	Units []LogUnit
	Run   func(name string, args ...string) ([]byte, error)

	since map[string]time.Time
}

func (l *Logs) run(name string, args ...string) ([]byte, error) {
	if l.Run != nil {
		return l.Run(name, args...)
	}
	return exec.Command(name, args...).Output()
}

func (l *Logs) Collect() []Record {
	if l.since == nil {
		l.since = map[string]time.Time{}
	}
	var records []Record
	now := time.Now()
	for _, unit := range l.Units {
		maxLines := unit.MaxLines
		if maxLines == 0 || maxLines > 200 {
			maxLines = 50
		}
		args := []string{"-u", unit.Unit, "-o", "cat", "-n", strconv.Itoa(maxLines), "--no-pager"}
		if since, ok := l.since[unit.Unit]; ok {
			args = append(args, "--since", since.Format("2006-01-02 15:04:05"))
		}
		l.since[unit.Unit] = now

		out, err := l.run("journalctl", args...)
		if err != nil {
			continue
		}
		var lines []string
		for _, line := range strings.Split(strings.TrimSpace(string(out)), "\n") {
			if line != "" {
				lines = append(lines, line)
			}
		}
		if len(lines) > 0 {
			records = append(records, logExcerpt(unit.Unit, lines))
		}
	}
	return records
}
