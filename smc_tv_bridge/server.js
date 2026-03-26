import express from 'express';
import morgan from 'morgan';
import fetch from 'node-fetch';
import rateLimit from 'express-rate-limit';

const app = express();
const PORT = parseInt(process.env.PORT || '8080', 10);
const PYTHON_BASE = process.env.PYTHON_BASE || 'http://localhost:8000';
const USE_MOCK = process.env.SMC_USE_MOCK === '1';
// When PYTHON_ENCODED=1, Python's /smc_tv already returns pipe-encoded data
// (no Node-side encoding needed). Otherwise Node fetches /smc_snapshot and encodes.
const PYTHON_ENCODED = process.env.PYTHON_ENCODED === '1';

// ── Logging ────────────────────────────────────────────
app.use(morgan('combined'));

// ── Rate-limit (60 req/min per IP) ─────────────────────
const limiter = rateLimit({
  windowMs: 60_000,
  max: 60,
  standardHeaders: true,
  legacyHeaders: false,
});
app.use('/smc_tv', limiter);

// ── Mock data (when no Python backend is running) ──────
function mockSnapshot(symbol, tf) {
  const now = Math.floor(Date.now() / 1000);
  return {
    bos: [
      { time: now - 3600, price: 100, dir: 'UP' },
      { time: now - 1800, price: 98, dir: 'DOWN' },
    ],
    orderblocks: [
      { low: 95, high: 97, dir: 'BULL', valid: true },
      { low: 102, high: 104, dir: 'BEAR', valid: true },
    ],
    fvg: [
      { low: 97, high: 99, dir: 'BULL', valid: true },
    ],
    sweeps: [
      { time: now - 900, price: 96.5, side: 'BUY' },
      { time: now - 600, price: 103.2, side: 'SELL' },
    ],
    regime: { volume_regime: 'NORMAL', thin_fraction: 0.0 },
    technicalscore: 0.72,
    newsscore: 0.35,
  };
}

// ── Encoders (pipe-delimited, semicolon-separated) ─────
function encodeLevels(levels = []) {
  return levels
    .map((l) => `${Math.floor(l.time)}|${l.price}|${l.dir}`)
    .join(';');
}

function encodeZones(zones = []) {
  return zones
    .map((z) => `${z.low}|${z.high}|${z.dir}|${z.valid ? 1 : 0}`)
    .join(';');
}

function encodeSweeps(sweeps = []) {
  return sweeps
    .map((s) => `${Math.floor(s.time)}|${s.price}|${s.side}`)
    .join(';');
}

// ── Health endpoint ────────────────────────────────────
app.get('/health', (_req, res) => {
  res.json({ ok: true, python_base: PYTHON_BASE, mock: USE_MOCK, python_encoded: PYTHON_ENCODED });
});

// ── Main endpoint for TradingView ──────────────────────
app.get('/smc_tv', async (req, res) => {
  try {
    const symbol = (req.query.symbol || '').toString().toUpperCase();
    const tf = (req.query.tf || '15m').toString();

    if (!symbol) {
      return res.status(400).json({ error: 'symbol required' });
    }

    let snap;

    if (USE_MOCK) {
      snap = mockSnapshot(symbol, tf);
    } else if (PYTHON_ENCODED) {
      // Python /smc_tv already returns pipe-encoded response — pass through
      const url = new URL('/smc_tv', PYTHON_BASE);
      url.searchParams.set('symbol', symbol);
      url.searchParams.set('tf', tf);

      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 4000);
      try {
        const r = await fetch(url.toString(), { signal: controller.signal });
        if (!r.ok) {
          console.error('python backend status', r.status);
          return res.status(502).json({ error: `python backend ${r.status}` });
        }
        const out = await r.json();
        res.set('Access-Control-Allow-Origin', '*');
        return res.json(out);
      } finally {
        clearTimeout(timeout);
      }
    } else {
      const url = new URL('/smc_snapshot', PYTHON_BASE);
      url.searchParams.set('symbol', symbol);
      url.searchParams.set('timeframe', tf);

      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 4000);
      try {
        const r = await fetch(url.toString(), { signal: controller.signal });
        if (!r.ok) {
          console.error('python backend status', r.status);
          return res.status(502).json({ error: `python backend ${r.status}` });
        }
        snap = await r.json();
      } finally {
        clearTimeout(timeout);
      }
    }

    const out = {
      bos: encodeLevels(snap.bos || snap.BOS || []),
      ob: encodeZones(snap.orderblocks || []),
      fvg: encodeZones(snap.fvg || []),
      sweeps: encodeSweeps(snap.liquidity_sweeps || snap.sweeps || []),
      regime: snap.regime?.volume_regime || 'NORMAL',
      tech: typeof snap.technicalscore === 'number' ? snap.technicalscore : 0.5,
      news: typeof snap.newsscore === 'number' ? snap.newsscore : 0.0,
    };

    res.set('Access-Control-Allow-Origin', '*');
    res.json(out);
  } catch (e) {
    console.error('smc_tv error', e);
    res.status(500).json({ error: 'internal' });
  }
});

app.listen(PORT, () => {
  console.log(`SMC TV bridge listening on ${PORT}, mock=${USE_MOCK}`);
});
