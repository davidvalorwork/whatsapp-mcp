package main

import (
	"errors"
	"sync"
	"testing"
	"time"
)

func TestOutboundMessageInterval(t *testing.T) {
	if outboundMessageInterval != 5*time.Second {
		t.Fatalf("outbound interval must be five seconds: %v", outboundMessageInterval)
	}
}

func TestMessageSendGateSerializesConcurrentAttempts(t *testing.T) {
	const count = 4
	gate := messageSendGate{interval: 20 * time.Millisecond}
	wantErr := errors.New("simulated send failure")
	var wg sync.WaitGroup
	var starts, finishes []time.Time
	results := make(chan error, count)
	ready := make(chan struct{})
	for i := 0; i < count; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			<-ready
			results <- gate.send(func() error {
				// These slices are protected by the gate during the callback.
				starts = append(starts, time.Now())
				time.Sleep(5 * time.Millisecond)
				finishes = append(finishes, time.Now())
				return wantErr
			})
		}()
	}
	close(ready)
	wg.Wait()
	close(results)
	for err := range results {
		if !errors.Is(err, wantErr) {
			t.Fatalf("send error must be preserved: %v", err)
		}
	}
	if len(starts) != count || len(finishes) != count {
		t.Fatalf("every callback must run once: starts=%d finishes=%d", len(starts), len(finishes))
	}
	for i := 1; i < count; i++ {
		if gap := starts[i].Sub(finishes[i-1]); gap < gate.interval {
			t.Fatalf("attempt %d started too early after a failed send: %v", i, gap)
		}
	}
}

func TestMediaFilenameUsesMessageID(t *testing.T) {
	timestamp := time.Date(2026, 9, 20, 10, 34, 18, 0, time.UTC)
	first := mediaFilename("image", "", "MESSAGE_A", timestamp)
	second := mediaFilename("image", "", "MESSAGE_B", timestamp)

	if first == second {
		t.Fatalf("different messages must not share a local filename: %q", first)
	}
	if first != "image_20260920_103418_MESSAGE_A.jpg" {
		t.Fatalf("unexpected deterministic filename: %q", first)
	}
}

func TestRESTServerOnlyListensOnLoopback(t *testing.T) {
	if got := restServerAddress(8080); got != "127.0.0.1:8080" {
		t.Fatalf("REST API must stay local: %q", got)
	}
}
