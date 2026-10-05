package main

import (
	"fmt"
	"sync"
	"testing"
	"time"
)

func contactTestStore(t *testing.T) *MessageStore {
	t.Helper()
	t.Chdir(t.TempDir())
	store, err := NewMessageStore()
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { store.Close() })
	return store
}

func TestNewContactLimitPersistsAndExpires(t *testing.T) {
	store := contactTestStore(t)
	now := time.Date(2026, 10, 4, 12, 0, 0, 0, time.UTC)
	for i := 0; i < newContactLimit; i++ {
		// Six batches over six hours fill the daily allowance without exceeding
		// the hourly allowance; the most recent batch is at now.
		attempt := now.Add(-time.Duration((newContactLimit-1-i)/newContactHourlyLimit) * time.Hour)
		if err := store.reserveNewContact(fmt.Sprintf("%d@s.whatsapp.net", i), "", false, attempt); err != nil {
			t.Fatal(err)
		}
	}
	store.Close()
	reopened, err := NewMessageStore()
	if err != nil {
		t.Fatal(err)
	}
	defer reopened.Close()
	if err := reopened.reserveNewContact("new@s.whatsapp.net", "", false, now); err == nil {
		t.Fatal("daily allowance must be enforced after restart")
	}
	if err := reopened.reserveNewContact("new@s.whatsapp.net", "", false, now.Add(time.Hour)); err == nil {
		t.Fatal("daily limit must still apply when the hourly allowance is available")
	}
	if err := reopened.reserveNewContact("0@s.whatsapp.net", "", false, now.Add(25*time.Hour)); err == nil {
		t.Fatal("an unanswered contact stays blocked even after 24 hours")
	}
	if err := reopened.reserveNewContact("new@s.whatsapp.net", "", false, now.Add(24*time.Hour)); err != nil {
		t.Fatalf("rolling window must expire after 24 hours: %v", err)
	}
}

func TestHourlyContactLimitPersistsAndExpires(t *testing.T) {
	store := contactTestStore(t)
	now := time.Date(2026, 10, 5, 12, 0, 0, 0, time.UTC)
	for i := 0; i < newContactHourlyLimit; i++ {
		if err := store.reserveNewContact(fmt.Sprintf("hourly%d@s.whatsapp.net", i), "", false, now); err != nil {
			t.Fatal(err)
		}
	}
	store.Close()
	reopened, err := NewMessageStore()
	if err != nil {
		t.Fatal(err)
	}
	defer reopened.Close()
	if err := reopened.reserveNewContact("later@s.whatsapp.net", "", false, now.Add(time.Hour-time.Second)); err == nil {
		t.Fatal("hourly limit must survive restart and block until the rolling window expires")
	}
	var count int
	if err := reopened.db.QueryRow(`SELECT COUNT(*) FROM outbound_contact_attempts`).Scan(&count); err != nil {
		t.Fatal(err)
	}
	if count != newContactHourlyLimit {
		t.Fatal("a rate-limit rejection must not reserve a new recipient")
	}
	if err := reopened.reserveNewContact("later@s.whatsapp.net", "", false, now.Add(time.Hour)); err != nil {
		t.Fatalf("hourly allowance must become available at the window boundary: %v", err)
	}
	if err := reopened.reserveNewContact("hourly0@s.whatsapp.net", "", false, now.Add(time.Hour)); err == nil {
		t.Fatal("hourly expiry must not permit an unanswered recipient to be contacted again")
	}
}

func TestNewContactAliasesAndReply(t *testing.T) {
	store := contactTestStore(t)
	now := time.Now()
	if err := store.reserveNewContact("123@s.whatsapp.net", "456@lid", false, now); err != nil {
		t.Fatal(err)
	}
	if err := store.reserveNewContact("456@lid", "123@s.whatsapp.net", false, now); err == nil {
		t.Fatal("changing the address must not permit a duplicate first contact")
	}
	if err := store.StoreChat("456@lid", "Supplier", now); err != nil {
		t.Fatal(err)
	}
	if _, err := store.db.Exec(`INSERT INTO messages (id, chat_jid, is_from_me, content) VALUES ('reply', '456@lid', 0, 'Budget')`); err != nil {
		t.Fatal(err)
	}
	if err := store.reserveNewContact("123@s.whatsapp.net", "456@lid", false, now); err != nil {
		t.Fatalf("an incoming reply must allow conversation: %v", err)
	}
}

func TestSavedContactsAndUnansweredHistory(t *testing.T) {
	store := contactTestStore(t)
	now := time.Now()
	if err := store.reserveNewContact("saved@s.whatsapp.net", "", true, now); err != nil {
		t.Fatal(err)
	}
	var count int
	store.db.QueryRow(`SELECT COUNT(*) FROM outbound_contact_attempts`).Scan(&count)
	if count != 0 {
		t.Fatal("saved contacts must not consume the new-contact allowance")
	}
	if err := store.StoreChat("unanswered@lid", "", now); err != nil {
		t.Fatal(err)
	}
	if _, err := store.db.Exec(`INSERT INTO messages (id, chat_jid, is_from_me, content) VALUES ('old', 'unanswered@lid', 1, 'Hello')`); err != nil {
		t.Fatal(err)
	}
	if err := store.reserveNewContact("unanswered@s.whatsapp.net", "unanswered@lid", false, now); err == nil {
		t.Fatal("old unanswered outreach must not be repeated")
	}
}

func TestConcurrentFirstContactsStayWithinLimit(t *testing.T) {
	store := contactTestStore(t)
	gate := messageSendGate{}
	var wg sync.WaitGroup
	results := make(chan error, 12)
	for i := 0; i < 12; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			results <- gate.send(func() error {
				return store.reserveNewContact(fmt.Sprintf("%d@s.whatsapp.net", i), "", false, time.Now())
			})
		}(i)
	}
	wg.Wait()
	close(results)
	allowed := 0
	for err := range results {
		if err == nil {
			allowed++
		}
	}
	if allowed != newContactHourlyLimit {
		t.Fatalf("concurrent attempts allowed %d; want %d", allowed, newContactHourlyLimit)
	}
}
