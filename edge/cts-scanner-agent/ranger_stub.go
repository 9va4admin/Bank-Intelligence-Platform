//go:build !windows || !cgo

package main

// StubTransport is used when the real Ranger COM SDK is not available
// (non-Windows builds, CI, and development environments).
// It returns a configurable sequence of ScannedItems from memory —
// useful for integration testing without physical hardware.

import (
	"errors"
	"sync"
)

type StubTransport struct {
	mu      sync.Mutex
	items   []*ScannedItem // items to return from ReadItem in order
	pos     int
	started bool
	closed  bool
	done    chan struct{}
}

// NewStubTransport creates a stub with a fixed sequence of items to return.
// When all items are exhausted, ReadItem blocks until EndJob is called.
func NewStubTransport(items []*ScannedItem) *StubTransport {
	return &StubTransport{items: items, done: make(chan struct{})}
}

func (s *StubTransport) Open() error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.closed {
		return errors.New("stub: already closed")
	}
	return nil
}

func (s *StubTransport) StartJob(endorsementText string, enableImprinter bool) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.closed {
		return errors.New("stub: closed")
	}
	s.started = true
	return nil
}

func (s *StubTransport) ReadItem() (*ScannedItem, error) {
	s.mu.Lock()
	if !s.started {
		s.mu.Unlock()
		return nil, errors.New("stub: job not started")
	}
	if s.pos < len(s.items) {
		item := s.items[s.pos]
		s.pos++
		s.mu.Unlock()
		return item, nil
	}
	s.mu.Unlock()

	// Block until EndJob is called.
	<-s.done
	return nil, nil
}

// PrintItem is a no-op on the stub — the caller sets ImprinterStamped on the item.
func (s *StubTransport) PrintItem(_ string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.closed {
		return errors.New("stub: closed")
	}
	return nil
}

func (s *StubTransport) EndJob() error {
	s.mu.Lock()
	defer s.mu.Unlock()
	select {
	case <-s.done:
	default:
		close(s.done)
	}
	s.started = false
	return nil
}

func (s *StubTransport) Close() error {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.closed = true
	select {
	case <-s.done:
	default:
		close(s.done)
	}
	return nil
}

// newTransport is the factory used by main.go.
// On non-Windows or non-CGO builds, returns a stub with no items.
// To inject test items, callers use NewStubTransport directly.
func newTransport(_ *Config) Transport {
	return NewStubTransport(nil)
}
