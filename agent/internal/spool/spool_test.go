package spool

import (
	"fmt"
	"testing"
)

func TestFIFOOrderAndAck(t *testing.T) {
	s, err := Open(t.TempDir(), 1<<20)
	if err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 5; i++ {
		if err := s.Append([]byte(fmt.Sprintf("item-%d", i))); err != nil {
			t.Fatal(err)
		}
	}

	items, ack, err := s.NextBatch(3)
	if err != nil {
		t.Fatal(err)
	}
	if len(items) != 3 || string(items[0]) != "item-0" || string(items[2]) != "item-2" {
		t.Fatalf("unexpected batch: %q", items)
	}
	if err := ack(); err != nil {
		t.Fatal(err)
	}

	items, _, _ = s.NextBatch(10)
	if len(items) != 2 || string(items[0]) != "item-3" {
		t.Fatalf("unexpected remainder: %q", items)
	}
}

func TestUnackedItemsStay(t *testing.T) {
	s, _ := Open(t.TempDir(), 1<<20)
	s.Append([]byte("one"))

	s.NextBatch(1) // read without ack
	items, _, _ := s.NextBatch(1)
	if len(items) != 1 || string(items[0]) != "one" {
		t.Fatalf("unacked item lost: %q", items)
	}
}

func TestSizeCapDropsOldest(t *testing.T) {
	s, _ := Open(t.TempDir(), 100)
	for i := 0; i < 10; i++ {
		s.Append([]byte(fmt.Sprintf("payload-%02d-aaaaaaaaaaaaaaaaaaaa", i))) // 31 bytes each
	}
	if s.Dropped() == 0 {
		t.Fatal("expected drops under size cap")
	}
	items, _, _ := s.NextBatch(100)
	if string(items[0]) == "payload-00-aaaaaaaaaaaaaaaaaaaa" {
		t.Fatal("oldest item should have been dropped")
	}
	if len(items) == 0 || string(items[len(items)-1]) != "payload-09-aaaaaaaaaaaaaaaaaaaa" {
		t.Fatalf("newest item missing: %q", items)
	}
}

func TestSurvivesReopen(t *testing.T) {
	dir := t.TempDir()
	s, _ := Open(dir, 1<<20)
	s.Append([]byte("persisted"))

	reopened, err := Open(dir, 1<<20)
	if err != nil {
		t.Fatal(err)
	}
	items, _, _ := reopened.NextBatch(10)
	if len(items) != 1 || string(items[0]) != "persisted" {
		t.Fatalf("lost item across reopen: %q", items)
	}
	reopened.Append([]byte("after"))
	items, _, _ = reopened.NextBatch(10)
	if len(items) != 2 || string(items[1]) != "after" {
		t.Fatalf("sequence broken across reopen: %q", items)
	}
}
