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
| `/health` | GET | Server health |
| `/smc_snapshot` | GET | Full SMC snapshot (nested JSON) — `?symbol=AAPL&timeframe=15m` |
| `/smc_tv` | GET | Pipe-encoded for Pine — `?symbol=AAPL&tf=15m` |

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

The Python API includes a lightweight SMC zone detector that computes from FMP intraday candles:

- **BOS**: Swing-high/low breaks (close beyond recent pivot)
- **Order Blocks**: Last candle before an impulsive move (1.5x body ratio, 60%+ body/range)
- **FVG**: 3-candle fair value gaps (unfilled imbalances)
- **Liquidity Sweeps**: Wick beyond recent S/R with close back inside

## TradingView Pine Script

Use `SMC_TV_Bridge.pine` in the repo root. Set `Backend URL` to your Node endpoint.
Note: `request.get()` requires TradingView Premium or higher.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `8080` | Node listen port |
| `PYTHON_BASE` | `http://localhost:8000` | Python backend URL |
| `SMC_USE_MOCK` | `0` | Set to `1` for built-in mock data |
| `PYTHON_ENCODED` | `0` | Set to `1` to use Python's `/smc_tv` directly (skip Node encoding) |
| `FMP_API_KEY` | — | FMP API key (required for real data) |
