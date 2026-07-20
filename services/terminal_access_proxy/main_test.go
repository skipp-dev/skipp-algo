package main

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"strings"
	"testing"
	"time"
)

const testToken = "test-only-terminal-access-token-0123456789"

func testProxy(t *testing.T, upstream http.Handler) (*accessProxy, *httptest.Server) {
	t.Helper()
	server := httptest.NewServer(upstream)
	t.Cleanup(server.Close)
	upstreamURL, err := url.Parse(server.URL)
	if err != nil {
		t.Fatal(err)
	}
	return newAccessProxy(config{upstream: upstreamURL, token: testToken}), server
}

func performRequest(t *testing.T, handler http.Handler, method, path, token string) *httptest.ResponseRecorder {
	t.Helper()
	req := httptest.NewRequest(method, path, nil)
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
	recorder := httptest.NewRecorder()
	handler.ServeHTTP(recorder, req)
	return recorder
}

func TestHealthIsTheOnlyPublicSuccess(t *testing.T) {
	proxy, _ := testProxy(t, http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(http.StatusOK) }))
	if got := performRequest(t, proxy, http.MethodGet, "/health", "").Code; got != http.StatusOK {
		t.Fatalf("health status = %d", got)
	}
	for _, path := range []string{"/", "/ready", "/metrics", "/_stcore/health", "/ai", "/api/v1/news-candidates"} {
		if got := performRequest(t, proxy, http.MethodGet, path, "").Code; got != http.StatusUnauthorized {
			t.Errorf("%s without auth status = %d", path, got)
		}
	}
}

func TestNewsCandidatesExportsDynamicActiveSymbols(t *testing.T) {
	now := time.Unix(1_750_000_000, 0).UTC()
	feed := t.TempDir() + "/terminal.jsonl"
	active := true
	rows := []map[string]any{
		{
			"ticker": "TSLA", "headline": "Tesla expands energy storage production", "snippet": "New production line.",
			"url": "https://example.test/tsla", "source": "Example Wire", "provider": "fmp_stock_latest",
			"published_ts": now.Unix() - 30, "updated_ts": now.Unix() - 20, "category": "company_news",
			"relevance": 0.81, "materiality": "HIGH", "story_key": "story-tsla", "story_expires_at": now.Unix() + 1800,
			"attention_state": "ALERT", "attention_score": 0.92, "attention_confidence": 0.88, "attention_active": active,
		},
		{
			"ticker": "TSLA", "headline": "Older lower-ranked story", "snippet": "Old.",
			"url": "https://example.test/old", "source": "Example Wire", "provider": "benzinga_rest",
			"published_ts": now.Unix() - 60, "updated_ts": now.Unix() - 60, "category": "company_news",
			"relevance": 0.6, "materiality": "MEDIUM", "story_key": "story-old", "story_expires_at": now.Unix() + 1200,
			"attention_state": "MONITOR", "attention_score": 0.7, "attention_confidence": 0.7, "attention_active": active,
		},
		{
			"ticker": "AAPL", "headline": "Inactive background item", "snippet": "Background.",
			"url": "https://example.test/aapl", "source": "Example Wire", "provider": "fmp_stock_latest",
			"published_ts": now.Unix() - 20, "updated_ts": now.Unix() - 20, "category": "company_news",
			"relevance": 0.3, "materiality": "LOW", "story_key": "story-aapl", "story_expires_at": now.Unix() + 1200,
			"attention_state": "BACKGROUND", "attention_score": 0.3, "attention_confidence": 0.4, "attention_active": false,
		},
		{
			"ticker": "NVDA", "headline": "Expired active item", "snippet": "Old.",
			"url": "https://example.test/nvda", "source": "Example Wire", "provider": "benzinga_rest",
			"published_ts": now.Add(-5 * time.Hour).Unix(), "updated_ts": now.Add(-5 * time.Hour).Unix(), "category": "company_news",
			"relevance": 0.9, "materiality": "HIGH", "story_key": "story-nvda", "story_expires_at": now.Unix() + 1200,
			"attention_state": "ALERT", "attention_score": 0.95, "attention_confidence": 0.9, "attention_active": active,
		},
	}
	file, err := os.Create(feed)
	if err != nil {
		t.Fatal(err)
	}
	for _, row := range rows {
		if err := json.NewEncoder(file).Encode(row); err != nil {
			t.Fatal(err)
		}
	}
	if err := file.Close(); err != nil {
		t.Fatal(err)
	}
	proxy, _ := testProxy(t, http.NotFoundHandler())
	proxy.candidates = candidateConfig{feedPath: feed, maxAge: 4 * time.Hour, limit: 100, now: func() time.Time { return now }}
	recorder := performRequest(t, proxy, http.MethodGet, "/api/v1/news-candidates", testToken)
	if recorder.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %q", recorder.Code, recorder.Body.String())
	}
	var envelope candidateEnvelope
	if err := json.Unmarshal(recorder.Body.Bytes(), &envelope); err != nil {
		t.Fatal(err)
	}
	if envelope.Schema != candidateSchema || len(envelope.Candidates) != 1 {
		t.Fatalf("unexpected envelope: %#v", envelope)
	}
	if got := envelope.Candidates[0]; got.Ticker != "TSLA" || got.AttentionState != "ALERT" || got.AttentionScore != 0.92 {
		t.Fatalf("unexpected candidate: %#v", got)
	}
	if envelope.Diagnostics["rows_stale"] != 1 || envelope.Diagnostics["rows_rejected"] != 1 {
		t.Fatalf("unexpected diagnostics: %#v", envelope.Diagnostics)
	}
	if got := recorder.Header().Get("Cache-Control"); got != "no-store" {
		t.Fatalf("Cache-Control = %q", got)
	}
}

func TestNewsCandidatesFailsClosedWhenFeedIsMissing(t *testing.T) {
	proxy, _ := testProxy(t, http.NotFoundHandler())
	proxy.candidates.feedPath = t.TempDir() + "/missing.jsonl"
	if got := performRequest(t, proxy, http.MethodGet, "/api/v1/news-candidates", testToken).Code; got != http.StatusServiceUnavailable {
		t.Fatalf("missing feed status = %d", got)
	}
}

func TestWrongAndMalformedBearerAreRejected(t *testing.T) {
	proxy, _ := testProxy(t, http.NotFoundHandler())
	for _, auth := range []string{"Bearer wrong-token-that-is-long-enough-000000", "bearer " + testToken, "Bearer " + testToken + " extra"} {
		req := httptest.NewRequest(http.MethodGet, "/", nil)
		req.Header.Set("Authorization", auth)
		recorder := httptest.NewRecorder()
		proxy.ServeHTTP(recorder, req)
		if recorder.Code != http.StatusUnauthorized {
			t.Errorf("authorization %q status = %d", auth, recorder.Code)
		}
	}
}

func TestCorrectBearerProxiesAndStripsCredential(t *testing.T) {
	proxy, _ := testProxy(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if got := r.Header.Get("Authorization"); got != "" {
			t.Errorf("upstream received Authorization %q", got)
		}
		if _, err := r.Cookie(sessionCookie); err == nil {
			t.Error("upstream received access session cookie")
		}
		if cookie, err := r.Cookie("streamlit"); err != nil || cookie.Value != "preserve-me" {
			t.Errorf("application cookie not preserved: %#v, %v", cookie, err)
		}
		w.WriteHeader(http.StatusNoContent)
	}))
	req := httptest.NewRequest(http.MethodGet, "/terminal", nil)
	req.Header.Set("Authorization", "Bearer "+testToken)
	req.AddCookie(&http.Cookie{Name: sessionCookie, Value: "not-forwarded"})
	req.AddCookie(&http.Cookie{Name: "streamlit", Value: "preserve-me"})
	recorder := httptest.NewRecorder()
	proxy.ServeHTTP(recorder, req)
	if recorder.Code != http.StatusNoContent {
		t.Fatalf("status = %d", recorder.Code)
	}
}

func TestReadyRequiresAuthAndProbesStreamlit(t *testing.T) {
	proxy, _ := testProxy(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/_stcore/health" {
			t.Errorf("probe path = %q", r.URL.Path)
		}
		_, _ = io.WriteString(w, "ok")
	}))
	if got := performRequest(t, proxy, http.MethodGet, "/ready", "wrong-token-that-is-long-enough-000000").Code; got != http.StatusUnauthorized {
		t.Fatalf("wrong token status = %d", got)
	}
	if got := performRequest(t, proxy, http.MethodGet, "/ready", testToken).Code; got != http.StatusOK {
		t.Fatalf("correct token status = %d", got)
	}
}

func TestFormLoginCreatesSecureSessionWithoutReflectingToken(t *testing.T) {
	proxy, _ := testProxy(t, http.NotFoundHandler())
	form := url.Values{"token": {testToken}}.Encode()
	req := httptest.NewRequest(http.MethodPost, "/_access/session", strings.NewReader(form))
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	recorder := httptest.NewRecorder()
	proxy.ServeHTTP(recorder, req)
	if recorder.Code != http.StatusSeeOther {
		t.Fatalf("status = %d, body = %q", recorder.Code, recorder.Body.String())
	}
	setCookie := recorder.Header().Get("Set-Cookie")
	for _, want := range []string{sessionCookie + "=", "HttpOnly", "Secure", "SameSite=Strict"} {
		if !strings.Contains(setCookie, want) {
			t.Errorf("Set-Cookie missing %q: %q", want, setCookie)
		}
	}
	if strings.Contains(setCookie, testToken) || strings.Contains(recorder.Body.String(), testToken) {
		t.Error("response exposed access token")
	}

	result := recorder.Result()
	cookies := result.Cookies()
	if len(cookies) != 1 {
		t.Fatalf("cookies = %#v", cookies)
	}
	upstreamProxy, _ := testProxy(t, http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(http.StatusOK) }))
	// Session values are deterministic for the configured token, so the cookie is valid on another proxy replica.
	followup := httptest.NewRequest(http.MethodGet, "/", nil)
	followup.AddCookie(cookies[0])
	followupRecorder := httptest.NewRecorder()
	upstreamProxy.ServeHTTP(followupRecorder, followup)
	if followupRecorder.Code != http.StatusOK {
		t.Fatalf("cookie-authenticated status = %d", followupRecorder.Code)
	}
}

func TestInvalidFormReturns401WithoutReflectingSecret(t *testing.T) {
	proxy, _ := testProxy(t, http.NotFoundHandler())
	secret := "do-not-reflect-this-candidate-value"
	form := url.Values{"token": {secret}}.Encode()
	req := httptest.NewRequest(http.MethodPost, "/_access/session", strings.NewReader(form))
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	req.Header.Set("Accept", "text/html")
	recorder := httptest.NewRecorder()
	proxy.ServeHTTP(recorder, req)
	if recorder.Code != http.StatusUnauthorized {
		t.Fatalf("status = %d", recorder.Code)
	}
	if strings.Contains(recorder.Body.String(), secret) {
		t.Error("response reflected rejected token")
	}
}

func TestLoadConfigFailsClosed(t *testing.T) {
	t.Setenv(accessTokenEnv, "")
	if _, err := loadConfig(); err == nil {
		t.Fatal("missing token accepted")
	}
	t.Setenv(accessTokenEnv, "too-short")
	if _, err := loadConfig(); err == nil {
		t.Fatal("short token accepted")
	}
	t.Setenv(accessTokenEnv, testToken+"\n")
	if _, err := loadConfig(); err == nil {
		t.Fatal("token with control character accepted")
	}
}

func TestExpiredOrTamperedSessionIsRejected(t *testing.T) {
	proxy, _ := testProxy(t, http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(http.StatusOK) }))
	expired := proxy.newSession(time.Now().Add(-9 * time.Hour))
	for _, value := range []string{expired, expired + "tampered", "malformed"} {
		req := httptest.NewRequest(http.MethodGet, "/", nil)
		req.AddCookie(&http.Cookie{Name: sessionCookie, Value: value})
		recorder := httptest.NewRecorder()
		proxy.ServeHTTP(recorder, req)
		if recorder.Code != http.StatusUnauthorized {
			t.Errorf("session %q status = %d", value, recorder.Code)
		}
	}
}
