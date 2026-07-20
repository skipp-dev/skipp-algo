package main

import (
	"bufio"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"math"
	"net/http"
	"net/url"
	"os"
	"regexp"
	"sort"
	"strings"
	"time"
)

const (
	candidateSchema       = "skipp-live-news-candidates/1"
	maxCandidateLineBytes = 2 << 20
	maxCandidateFileBytes = 64 << 20
)

var candidateTickerPattern = regexp.MustCompile(`^[A-Z][A-Z0-9.-]{0,14}$`)

type candidateConfig struct {
	feedPath string
	maxAge   time.Duration
	limit    int
	now      func() time.Time
}

type terminalFeedRow struct {
	Ticker              string   `json:"ticker"`
	Headline            string   `json:"headline"`
	Snippet             string   `json:"snippet"`
	URL                 string   `json:"url"`
	Source              string   `json:"source"`
	PublishedTS         float64  `json:"published_ts"`
	UpdatedTS           float64  `json:"updated_ts"`
	Provider            string   `json:"provider"`
	Category            string   `json:"category"`
	Relevance           *float64 `json:"relevance"`
	Materiality         string   `json:"materiality"`
	StoryKey            string   `json:"story_key"`
	StoryExpiresAt      float64  `json:"story_expires_at"`
	AttentionState      string   `json:"attention_state"`
	AttentionScore      *float64 `json:"attention_score"`
	AttentionConfidence *float64 `json:"attention_confidence"`
	AttentionActive     *bool    `json:"attention_active"`
}

type newsCandidate struct {
	CandidateID         string  `json:"candidate_id"`
	Ticker              string  `json:"ticker"`
	Headline            string  `json:"headline"`
	Summary             string  `json:"summary"`
	Publisher           string  `json:"publisher"`
	Provider            string  `json:"provider"`
	PublishedAt         int64   `json:"published_at"`
	UpdatedAt           int64   `json:"updated_at"`
	ExpiresAt           int64   `json:"expires_at"`
	Category            string  `json:"category"`
	Materiality         string  `json:"materiality"`
	Relevance           float64 `json:"relevance"`
	AttentionState      string  `json:"attention_state"`
	AttentionScore      float64 `json:"attention_score"`
	AttentionConfidence float64 `json:"attention_confidence"`
	SourceURL           string  `json:"source_url"`
}

type candidateEnvelope struct {
	Schema      string            `json:"schema"`
	GeneratedAt int64             `json:"generated_at"`
	Scope       string            `json:"scope"`
	Source      map[string]string `json:"source"`
	Candidates  []newsCandidate   `json:"candidates"`
	Diagnostics map[string]int    `json:"diagnostics"`
}

func (p *accessProxy) newsCandidates(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet && r.Method != http.MethodHead {
		w.Header().Set("Allow", "GET, HEAD")
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	now := p.candidates.now().UTC()
	envelope, err := readNewsCandidates(p.candidates, now)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			http.Error(w, "candidate feed unavailable", http.StatusServiceUnavailable)
			return
		}
		http.Error(w, "candidate feed unreadable", http.StatusServiceUnavailable)
		return
	}
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	if r.Method == http.MethodHead {
		w.WriteHeader(http.StatusOK)
		return
	}
	if err := json.NewEncoder(w).Encode(envelope); err != nil {
		return
	}
}

func readNewsCandidates(cfg candidateConfig, now time.Time) (candidateEnvelope, error) {
	file, err := os.Open(cfg.feedPath)
	if err != nil {
		return candidateEnvelope{}, err
	}
	defer file.Close()
	info, err := file.Stat()
	if err != nil || info.Size() > maxCandidateFileBytes {
		return candidateEnvelope{}, errors.New("candidate feed exceeds size limit")
	}
	reader := io.LimitReader(file, maxCandidateFileBytes+1)
	scanner := bufio.NewScanner(reader)
	scanner.Buffer(make([]byte, 64*1024), maxCandidateLineBytes)
	bestByTicker := make(map[string]newsCandidate)
	diagnostics := map[string]int{"rows_read": 0, "rows_rejected": 0, "rows_stale": 0, "symbols_emitted": 0}
	for scanner.Scan() {
		diagnostics["rows_read"]++
		var row terminalFeedRow
		if err := json.Unmarshal(scanner.Bytes(), &row); err != nil {
			diagnostics["rows_rejected"]++
			continue
		}
		candidate, status := candidateFromRow(row, now, cfg.maxAge)
		if status == "stale" {
			diagnostics["rows_stale"]++
			continue
		}
		if status != "ok" {
			diagnostics["rows_rejected"]++
			continue
		}
		previous, found := bestByTicker[candidate.Ticker]
		if !found || betterCandidate(candidate, previous) {
			bestByTicker[candidate.Ticker] = candidate
		}
	}
	if err := scanner.Err(); err != nil {
		return candidateEnvelope{}, err
	}
	candidates := make([]newsCandidate, 0, len(bestByTicker))
	for _, candidate := range bestByTicker {
		candidates = append(candidates, candidate)
	}
	sort.Slice(candidates, func(i, j int) bool {
		if attentionRank(candidates[i].AttentionState) != attentionRank(candidates[j].AttentionState) {
			return attentionRank(candidates[i].AttentionState) > attentionRank(candidates[j].AttentionState)
		}
		if candidates[i].AttentionScore != candidates[j].AttentionScore {
			return candidates[i].AttentionScore > candidates[j].AttentionScore
		}
		if candidates[i].PublishedAt != candidates[j].PublishedAt {
			return candidates[i].PublishedAt > candidates[j].PublishedAt
		}
		return candidates[i].Ticker < candidates[j].Ticker
	})
	if len(candidates) > cfg.limit {
		candidates = candidates[:cfg.limit]
	}
	diagnostics["symbols_emitted"] = len(candidates)
	return candidateEnvelope{
		Schema:      candidateSchema,
		GeneratedAt: now.Unix(),
		Scope:       "terminal_live_feed_retained_active_candidates",
		Source: map[string]string{
			"producer":         "skipp-terminal-live-feed",
			"producer_version": "1",
		},
		Candidates:  candidates,
		Diagnostics: diagnostics,
	}, nil
}

func candidateFromRow(row terminalFeedRow, now time.Time, maxAge time.Duration) (newsCandidate, string) {
	ticker := strings.ToUpper(strings.TrimSpace(row.Ticker))
	headline := strings.Join(strings.Fields(row.Headline), " ")
	publisher := strings.Join(strings.Fields(row.Source), " ")
	attentionState := strings.ToUpper(strings.TrimSpace(row.AttentionState))
	publishedAt := int64(row.PublishedTS)
	if ticker == "" || !candidateTickerPattern.MatchString(ticker) || headline == "" || publisher == "" || publishedAt <= 0 {
		return newsCandidate{}, "rejected"
	}
	if row.AttentionActive == nil || !*row.AttentionActive || attentionRank(attentionState) == 0 {
		return newsCandidate{}, "rejected"
	}
	if publishedAt > now.Add(5*time.Minute).Unix() || publishedAt < now.Add(-maxAge).Unix() {
		return newsCandidate{}, "stale"
	}
	sourceURL := strings.TrimSpace(row.URL)
	parsedURL, err := url.Parse(sourceURL)
	if err != nil || (parsedURL.Scheme != "https" && parsedURL.Scheme != "http") || parsedURL.Host == "" || parsedURL.User != nil {
		return newsCandidate{}, "rejected"
	}
	attentionScore, ok := boundedPointer(row.AttentionScore)
	if !ok {
		return newsCandidate{}, "rejected"
	}
	attentionConfidence, ok := boundedPointer(row.AttentionConfidence)
	if !ok {
		return newsCandidate{}, "rejected"
	}
	relevance, ok := boundedPointer(row.Relevance)
	if !ok {
		return newsCandidate{}, "rejected"
	}
	updatedAt := int64(row.UpdatedTS)
	if updatedAt < publishedAt {
		updatedAt = publishedAt
	}
	expiresAt := int64(row.StoryExpiresAt)
	maximumExpiry := now.Add(maxAge).Unix()
	if expiresAt <= now.Unix() || expiresAt > maximumExpiry {
		expiresAt = maximumExpiry
	}
	storyIdentity := strings.TrimSpace(row.StoryKey)
	if storyIdentity == "" {
		storyIdentity = sourceURL + "|" + strconvFormatInt(publishedAt)
	}
	digest := sha256.Sum256([]byte(storyIdentity + "|" + ticker))
	return newsCandidate{
		CandidateID:         "news:" + hex.EncodeToString(digest[:12]),
		Ticker:              ticker,
		Headline:            truncateUTF8(headline, 500),
		Summary:             truncateUTF8(strings.Join(strings.Fields(row.Snippet), " "), 8000),
		Publisher:           truncateUTF8(publisher, 128),
		Provider:            defaultText(strings.TrimSpace(row.Provider), "unknown", 64),
		PublishedAt:         publishedAt,
		UpdatedAt:           updatedAt,
		ExpiresAt:           expiresAt,
		Category:            defaultText(strings.TrimSpace(row.Category), "company_news", 64),
		Materiality:         normalizeMateriality(row.Materiality),
		Relevance:           relevance,
		AttentionState:      attentionState,
		AttentionScore:      attentionScore,
		AttentionConfidence: attentionConfidence,
		SourceURL:           truncateUTF8(sourceURL, 2048),
	}, "ok"
}

func betterCandidate(left, right newsCandidate) bool {
	if attentionRank(left.AttentionState) != attentionRank(right.AttentionState) {
		return attentionRank(left.AttentionState) > attentionRank(right.AttentionState)
	}
	if left.AttentionScore != right.AttentionScore {
		return left.AttentionScore > right.AttentionScore
	}
	if left.PublishedAt != right.PublishedAt {
		return left.PublishedAt > right.PublishedAt
	}
	return left.CandidateID < right.CandidateID
}

func attentionRank(value string) int {
	switch value {
	case "ALERT":
		return 3
	case "FOCUS":
		return 2
	case "MONITOR":
		return 1
	default:
		return 0
	}
}

func boundedPointer(value *float64) (float64, bool) {
	if value == nil || math.IsNaN(*value) || math.IsInf(*value, 0) || *value < 0 || *value > 1 {
		return 0, false
	}
	return *value, true
}

func normalizeMateriality(value string) string {
	value = strings.ToUpper(strings.TrimSpace(value))
	switch value {
	case "HIGH", "MEDIUM", "LOW":
		return value
	default:
		return "UNKNOWN"
	}
}

func defaultText(value, fallback string, maximum int) string {
	if value == "" {
		value = fallback
	}
	return truncateUTF8(value, maximum)
}

func truncateUTF8(value string, maximum int) string {
	runes := []rune(value)
	if len(runes) > maximum {
		return string(runes[:maximum])
	}
	return value
}

func strconvFormatInt(value int64) string {
	// Kept local so candidate identity cannot depend on locale or float formatting.
	return time.Unix(value, 0).UTC().Format(time.RFC3339)
}
