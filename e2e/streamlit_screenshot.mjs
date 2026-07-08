// Playwright screenshot driver for the Streamlit terminal (streamlit_terminal.py).
// Streamlit first paints a loading skeleton, then streams the real widget tree
// over a websocket — Chrome's one-shot --screenshot fires before that finishes,
// so it needs a real browser that WAITS for the rendered DOM. This does.
//
// Usage:  node e2e/streamlit_screenshot.mjs [url] [out.png]
//   defaults: http://127.0.0.1:8501  ,  e2e/terminal.png
import { chromium } from 'playwright';

const url = process.argv[2] || 'http://127.0.0.1:8501';
const out = process.argv[3] || 'e2e/terminal.png';

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1600, height: 1200 } });
await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 90000 });

// Wait until the sidebar has streamed in, the skeletons are gone, and there is
// real text — i.e. the app tree rendered, not the loading placeholder.
await page.waitForFunction(() => {
  const sidebar = document.querySelector('[data-testid="stSidebar"]');
  const skeletons = document.querySelectorAll('[data-testid="stSkeleton"]').length;
  const text = (document.body.innerText || '').trim();
  return sidebar && skeletons === 0 && text.length > 500;
}, { timeout: 60000 });

await page.waitForTimeout(2000); // let tables/expanders settle
await page.screenshot({ path: out, fullPage: true });
await browser.close();
console.log('wrote', out);
