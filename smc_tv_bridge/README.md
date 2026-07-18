# SMC TV Bridge

Thin Node.js HTTP layer that sits between TradingView and the Python SMC/Realtime stack.
Node encodes the full SMC snapshot into a compact pipe-delimited format that Pine Script can parse easily.

## Architecture

```
TradingView Pine  ──→  Node :8080 /smc_tv  ──→  Python :8000 /smc_snapshot
                                                  ├─ FMP candles → BOS/OB/FVG/Sweep detector
                                                  ├─ VolumeRegimeDetector → regime
                                                  ├─ TechnicalScorer → tech score
                                                  └─ Newsstack → news score
```

## Quick Start (Mock Mode — no FMP key needed)

```bash
cd smc_tv_bridge
npm install
npm run start:mock        # Node mock on :8080
```

Or mock via Python:

```bash
SMC_USE_MOCK=1 uvicorn smc_tv_bridge.smc_api:app --port 8000 &
npm start                 # Node on :8080, proxying to Python :8000
```

## Production (with FMP key)

```bash
# Start Python API (real SMC zone detection from FMP candles)
FMP_API_KEY=xxx uvicorn smc_tv_bridge.smc_api:app --host 0.0.0.0 --port 8000 &

# Option A: Node encodes (fetches /smc_snapshot, encodes in Node)
PYTHON_BASE=http://localhost:8000 npm start

# Option B: Python encodes (Node passes through /smc_tv directly)
PYTHON_BASE=http://localhost:8000 PYTHON_ENCODED=1 npm start
```

## Endpoints

### Python API (:8000)

| Path | Method | Description |
|------|--------|-------------|
| `/health` | GET | Server health (`fmp_available` is the mock-mode flag, not an FMP probe) |
| `/smc_snapshot` | GET | Full SMC snapshot (nested JSON) — `?symbol=AAPL&timeframe=15m` |
| `/smc_tv` | GET | Pipe-encoded for Pine — `?symbol=AAPL&tf=15m` |
| `/smc_live` | GET | Flat `smc-live-overlay/1` payload — `?symbol=AAPL&tf=15m` |

### Node Bridge (:8080)

| Path | Method | Description |
|------|--------|-------------|
| `/health` | GET | Bridge health + config |
| `/smc_tv` | GET | TV-friendly response — `?symbol=AAPL&tf=15m` |

## Response Format (`/smc_tv`)

```json
{
  "bos":    "time|price|dir;...",
  "ob":     "low|high|dir|valid;...",
  "fvg":    "low|high|dir|valid;...",
  "sweeps": "time|price|side;...",
  "regime": "NORMAL",
  "tech":   0.72,
  "news":   0.35
}
```

## SMC Zone Detection

The Python API delegates structure detection to the canonical repo producer
(`scripts/explicit_structure_from_bars.build_full_structure_from_bars`) on FMP
intraday candles — the same BOS / Order Block / FVG / Liquidity Sweep detectors
used everywhere else in the repo (two-candle displacement OBs, 3-candle FVGs,
sweep wick-beyond-with-close-back rules). There is no bridge-local heuristic.

## TradingView Pine Script

`SMC_Regime_and_News.pine` in the repo root is now a retired compatibility
notice. Its former fetch design was not supported by Pine; Pine exposes no
arbitrary HTTP client. No TradingView delivery path is planned for this REST
bridge. The tombstone deliberately contains no endpoint, token input, fetch code, or data
visualization; nothing hits the Node bridge from TradingView.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `8080` | Node listen port |
| `PYTHON_BASE` | `http://localhost:8000` | Python backend URL |
| `SMC_USE_MOCK` | `0` | Set to `1` for built-in mock data |
| `PYTHON_ENCODED` | `0` | Set to `1` to use Python's `/smc_tv` directly (skip Node encoding) |
| `FMP_API_KEY` | — | FMP API key (required for real data) |
