package main

import (
	"crypto/hmac"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base64"
	"errors"
	"fmt"
	"html/template"
	"io"
	"log"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"
)

const (
	accessTokenEnv = "TERMINAL_ACCESS_TOKEN"
	sessionCookie  = "__Host-skipp_terminal_session"
	maxTokenBytes  = 512
	minTokenBytes  = 32
)

var loginPage = template.Must(template.New("login").Parse(`<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Skipp Terminal access</title><style>
body{font:16px system-ui,sans-serif;max-width:30rem;margin:10vh auto;padding:1.5rem;background:#0b1020;color:#eef2ff}
main{background:#151c32;border:1px solid #2b3659;border-radius:12px;padding:1.5rem}label,input,button{display:block;width:100%;box-sizing:border-box}
input,button{margin-top:.6rem;padding:.8rem;border-radius:7px;border:1px solid #52618c}input{background:#090e1c;color:#fff}button{background:#526df5;color:#fff;font-weight:700;cursor:pointer}.error{color:#ffb4b4}
</style></head><body><main><h1>Skipp Terminal</h1><p>Enter the access token supplied by the operator.</p>
{{if .Error}}<p class="error">Invalid access token.</p>{{end}}
<form method="post" action="/_access/session"><label for="token">Access token</label><input id="token" name="token" type="password" autocomplete="current-password" required maxlength="512"><button type="submit">Continue</button></form>
</main></body></html>`))

type config struct {
	listenAddr string
	upstream   *url.URL
	token      string
}

type accessProxy struct {
	tokenDigest  [sha256.Size]byte
	sessionKey   [sha256.Size]byte
	upstream     *url.URL
	reverseProxy *httputil.ReverseProxy
	probeClient  *http.Client
}

func loadConfig() (config, error) {
	token := os.Getenv(accessTokenEnv)
	if len(token) < minTokenBytes || len(token) > maxTokenBytes {
		return config{}, fmt.Errorf("%s must contain %d-%d bytes", accessTokenEnv, minTokenBytes, maxTokenBytes)
	}
	if strings.TrimSpace(token) != token || strings.IndexFunc(token, func(r rune) bool { return r < 0x21 || r == 0x7f }) >= 0 {
		return config{}, fmt.Errorf("%s contains disallowed whitespace or control characters", accessTokenEnv)
	}

	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}
	listenAddr := os.Getenv("TERMINAL_PROXY_ADDR")
	if listenAddr == "" {
		listenAddr = ":" + port
	}
	upstreamRaw := os.Getenv("TERMINAL_PROXY_UPSTREAM")
	if upstreamRaw == "" {
		upstreamRaw = "http://127.0.0.1:8501"
	}
	upstream, err := url.Parse(upstreamRaw)
	if err != nil || upstream.Scheme != "http" || upstream.Host == "" || upstream.User != nil {
		return config{}, errors.New("TERMINAL_PROXY_UPSTREAM must be a plain internal http URL without credentials")
	}
	return config{listenAddr: listenAddr, upstream: upstream, token: token}, nil
}

func newAccessProxy(cfg config) *accessProxy {
	tokenDigest := sha256.Sum256([]byte(cfg.token))
	mac := hmac.New(sha256.New, []byte(cfg.token))
	_, _ = mac.Write([]byte("skipp-terminal-session-v1"))
	var sessionKey [sha256.Size]byte
	copy(sessionKey[:], mac.Sum(nil))

	reverseProxy := httputil.NewSingleHostReverseProxy(cfg.upstream)
	originalDirector := reverseProxy.Director
	reverseProxy.Director = func(req *http.Request) {
		originalDirector(req)
		req.Header.Del("Authorization")
		stripSessionCookie(req)
	}
	reverseProxy.ErrorHandler = func(w http.ResponseWriter, _ *http.Request, _ error) {
		applySecurityHeaders(w.Header())
		http.Error(w, "upstream unavailable", http.StatusBadGateway)
	}

	return &accessProxy{
		tokenDigest:  tokenDigest,
		sessionKey:   sessionKey,
		upstream:     cfg.upstream,
		reverseProxy: reverseProxy,
		probeClient:  &http.Client{Timeout: 2 * time.Second},
	}
}

func (p *accessProxy) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	applySecurityHeaders(w.Header())
	if r.URL.Path == "/health" {
		p.health(w, r)
		return
	}
	if r.URL.Path == "/_access/session" && r.Method == http.MethodPost {
		p.createSession(w, r)
		return
	}
	if !p.authorized(r) {
		p.unauthorized(w, r, false)
		return
	}
	if r.URL.Path == "/_access/logout" && r.Method == http.MethodPost {
		p.clearSession(w)
		return
	}
	if r.URL.Path == "/ready" {
		p.ready(w, r)
		return
	}
	p.reverseProxy.ServeHTTP(w, r)
}

func (p *accessProxy) health(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet && r.Method != http.MethodHead {
		w.Header().Set("Allow", "GET, HEAD")
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("Content-Type", "text/plain; charset=utf-8")
	w.WriteHeader(http.StatusOK)
	if r.Method != http.MethodHead {
		_, _ = io.WriteString(w, "ok\n")
	}
}

func (p *accessProxy) ready(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet && r.Method != http.MethodHead {
		w.Header().Set("Allow", "GET, HEAD")
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	probeURL := *p.upstream
	probeURL.Path = "/_stcore/health"
	probeURL.RawQuery = ""
	probeURL.Fragment = ""
	req, err := http.NewRequestWithContext(r.Context(), http.MethodGet, probeURL.String(), nil)
	if err != nil {
		http.Error(w, "not ready", http.StatusServiceUnavailable)
		return
	}
	resp, err := p.probeClient.Do(req)
	if err != nil {
		http.Error(w, "not ready", http.StatusServiceUnavailable)
		return
	}
	defer resp.Body.Close()
	_, _ = io.Copy(io.Discard, io.LimitReader(resp.Body, 4096))
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		http.Error(w, "not ready", http.StatusServiceUnavailable)
		return
	}
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("Content-Type", "text/plain; charset=utf-8")
	w.WriteHeader(http.StatusOK)
	if r.Method != http.MethodHead {
		_, _ = io.WriteString(w, "ready\n")
	}
}

func (p *accessProxy) authorized(r *http.Request) bool {
	if auth := r.Header.Get("Authorization"); auth != "" {
		const prefix = "Bearer "
		if !strings.HasPrefix(auth, prefix) || len(auth) == len(prefix) || strings.ContainsAny(auth[len(prefix):], " \t\r\n") {
			return false
		}
		return p.matchesToken(auth[len(prefix):])
	}
	cookie, err := r.Cookie(sessionCookie)
	return err == nil && p.validSession(cookie.Value, time.Now())
}

func (p *accessProxy) matchesToken(candidate string) bool {
	digest := sha256.Sum256([]byte(candidate))
	return subtle.ConstantTimeCompare(digest[:], p.tokenDigest[:]) == 1
}

func (p *accessProxy) newSession(now time.Time) string {
	expires := strconv.FormatInt(now.Add(8*time.Hour).Unix(), 10)
	mac := hmac.New(sha256.New, p.sessionKey[:])
	_, _ = mac.Write([]byte(expires))
	return expires + "." + base64.RawURLEncoding.EncodeToString(mac.Sum(nil))
}

func (p *accessProxy) validSession(value string, now time.Time) bool {
	expiresRaw, signature, found := strings.Cut(value, ".")
	if !found || expiresRaw == "" || signature == "" {
		return false
	}
	expires, err := strconv.ParseInt(expiresRaw, 10, 64)
	if err != nil || expires <= now.Unix() || expires > now.Add(8*time.Hour+time.Minute).Unix() {
		return false
	}
	mac := hmac.New(sha256.New, p.sessionKey[:])
	_, _ = mac.Write([]byte(expiresRaw))
	expected := base64.RawURLEncoding.EncodeToString(mac.Sum(nil))
	return subtle.ConstantTimeCompare([]byte(signature), []byte(expected)) == 1
}

func (p *accessProxy) createSession(w http.ResponseWriter, r *http.Request) {
	r.Body = http.MaxBytesReader(w, r.Body, 4096)
	if err := r.ParseForm(); err != nil || !p.matchesToken(r.Form.Get("token")) {
		p.unauthorized(w, r, true)
		return
	}
	http.SetCookie(w, &http.Cookie{
		Name:     sessionCookie,
		Value:    p.newSession(time.Now()),
		Path:     "/",
		MaxAge:   int((8 * time.Hour).Seconds()),
		HttpOnly: true,
		Secure:   true,
		SameSite: http.SameSiteStrictMode,
	})
	w.Header().Set("Cache-Control", "no-store")
	http.Redirect(w, r, "/", http.StatusSeeOther)
}

func (p *accessProxy) clearSession(w http.ResponseWriter) {
	http.SetCookie(w, &http.Cookie{
		Name:     sessionCookie,
		Value:    "",
		Path:     "/",
		MaxAge:   -1,
		HttpOnly: true,
		Secure:   true,
		SameSite: http.SameSiteStrictMode,
	})
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(http.StatusNoContent)
}

func (p *accessProxy) unauthorized(w http.ResponseWriter, r *http.Request, invalid bool) {
	w.Header().Set("WWW-Authenticate", `Bearer realm="skipp-terminal-ai"`)
	w.Header().Set("Cache-Control", "no-store")
	if (r.Method == http.MethodGet || r.URL.Path == "/_access/session") && strings.Contains(r.Header.Get("Accept"), "text/html") {
		w.Header().Set("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		w.WriteHeader(http.StatusUnauthorized)
		_ = loginPage.Execute(w, struct{ Error bool }{Error: invalid})
		return
	}
	http.Error(w, "unauthorized", http.StatusUnauthorized)
}

func stripSessionCookie(req *http.Request) {
	cookies := req.Cookies()
	req.Header.Del("Cookie")
	for _, cookie := range cookies {
		if cookie.Name != sessionCookie {
			req.AddCookie(cookie)
		}
	}
}

func applySecurityHeaders(headers http.Header) {
	headers.Set("X-Content-Type-Options", "nosniff")
	headers.Set("Referrer-Policy", "no-referrer")
	headers.Set("X-Frame-Options", "DENY")
	headers.Set("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
}

func main() {
	cfg, err := loadConfig()
	if err != nil {
		log.Printf("terminal access proxy configuration rejected: %v", err)
		os.Exit(1)
	}
	server := &http.Server{
		Addr:              cfg.listenAddr,
		Handler:           newAccessProxy(cfg),
		ReadHeaderTimeout: 5 * time.Second,
		IdleTimeout:       90 * time.Second,
		MaxHeaderBytes:    16 << 10,
		ErrorLog:          log.New(io.Discard, "", 0),
	}
	log.Printf("terminal access proxy listening (public liveness: /health; all other paths protected)")
	if err := server.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
		log.Printf("terminal access proxy stopped unexpectedly")
		os.Exit(1)
	}
}
