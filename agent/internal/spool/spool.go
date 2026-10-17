// Package spool is a disk-backed FIFO buffer so collected records survive
// control-plane outages and agent restarts.
package spool

import (
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"
)

type Spool struct {
	dir      string
	maxBytes int64

	mu      sync.Mutex
	seq     uint64
	size    int64
	dropped uint64
}

func Open(dir string, maxBytes int64) (*Spool, error) {
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return nil, err
	}
	s := &Spool{dir: dir, maxBytes: maxBytes}
	for _, name := range s.fileNames() {
		info, err := os.Stat(filepath.Join(dir, name))
		if err == nil {
			s.size += info.Size()
		}
		if n, err := strconv.ParseUint(strings.TrimSuffix(name, ".json"), 10, 64); err == nil && n >= s.seq {
			s.seq = n + 1
		}
	}
	return s, nil
}

func (s *Spool) fileNames() []string {
	entries, err := os.ReadDir(s.dir)
	if err != nil {
		return nil
	}
	var names []string
	for _, entry := range entries {
		if strings.HasSuffix(entry.Name(), ".json") {
			names = append(names, entry.Name())
		}
	}
	sort.Strings(names)
	return names
}

func (s *Spool) Append(data []byte) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	name := fmt.Sprintf("%016d.json", s.seq)
	if err := os.WriteFile(filepath.Join(s.dir, name), data, 0o600); err != nil {
		return err
	}
	s.seq++
	s.size += int64(len(data))

	// over cap: drop oldest first
	for s.size > s.maxBytes {
		names := s.fileNames()
		if len(names) <= 1 {
			break
		}
		oldest := filepath.Join(s.dir, names[0])
		info, err := os.Stat(oldest)
		if err != nil {
			break
		}
		if err := os.Remove(oldest); err != nil {
			break
		}
		s.size -= info.Size()
		s.dropped++
	}
	return nil
}

// NextBatch returns up to max oldest items and an ack that removes them
// once they have been delivered.
func (s *Spool) NextBatch(max int) ([][]byte, func() error, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	names := s.fileNames()
	if len(names) > max {
		names = names[:max]
	}
	var items [][]byte
	var paths []string
	for _, name := range names {
		path := filepath.Join(s.dir, name)
		data, err := os.ReadFile(path)
		if err != nil {
			continue
		}
		items = append(items, data)
		paths = append(paths, path)
	}

	ack := func() error {
		s.mu.Lock()
		defer s.mu.Unlock()
		for _, path := range paths {
			if info, err := os.Stat(path); err == nil {
				s.size -= info.Size()
			}
			if err := os.Remove(path); err != nil {
				return err
			}
		}
		return nil
	}
	return items, ack, nil
}

func (s *Spool) Len() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return len(s.fileNames())
}

func (s *Spool) Dropped() uint64 {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.dropped
}
