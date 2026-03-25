#!/usr/bin/env -S node --enable-source-maps

import { closeTradingViewSession, ensurePineEditor, gotoChart, newTradingViewSession, openExistingScript } from "../automation/tradingview/lib/tv_shared.js";

type ProbeResult = {
  scriptName: string;
  url: string;
  textMatches: ElementSnapshot[];
  legendContainers: ElementSnapshot[];
  settingsButtons: ElementSnapshot[];
  moreButtons: ElementSnapshot[];
};

type ElementSnapshot = {
  index: number;
  tag: string;
  text: string;
  title: string | null;
  ariaLabel: string | null;
  dataName: string | null;
  dataQaId: string | null;
  className: string;
  rect: {
    x: number;
    y: number;
    width: number;
    height: number;
  };
  centerHitTag: string | null;
  centerHitClass: string | null;
  centerHitQa: string | null;
  centerHitText: string | null;
};

const targetScript = process.argv[2] || "SMC Dashboard";

const session = await newTradingViewSession();

try {
  const { page } = session;
  await gotoChart(page);
  await ensurePineEditor(page);
  await openExistingScript(page, targetScript).catch(() => false);
  await ensurePineEditor(page);

  const probeSource = `
    const scriptName = ${JSON.stringify(targetScript)};
    const normalize = (value) => (value || "").replace(/\\s+/g, " ").trim();
    const matchesScript = (value) => normalize(value).toLowerCase().includes(normalize(scriptName).toLowerCase());
    const describeElement = (element, index) => {
      if (!(element instanceof HTMLElement)) {
        return null;
      }
      const rect = element.getBoundingClientRect();
      const centerX = rect.left + rect.width / 2;
      const centerY = rect.top + rect.height / 2;
      const hit = document.elementFromPoint(centerX, centerY);
      return {
        index,
        tag: element.tagName,
        text: normalize(element.innerText),
        title: element.getAttribute("title"),
        ariaLabel: element.getAttribute("aria-label"),
        dataName: element.getAttribute("data-name"),
        dataQaId: element.getAttribute("data-qa-id"),
        className: String(element.className || ""),
        rect: {
          x: Math.round(rect.x),
          y: Math.round(rect.y),
          width: Math.round(rect.width),
          height: Math.round(rect.height),
        },
        centerHitTag: hit instanceof HTMLElement ? hit.tagName : null,
        centerHitClass: hit instanceof HTMLElement ? String(hit.className || "") : null,
        centerHitQa: hit instanceof HTMLElement ? hit.getAttribute("data-qa-id") : null,
        centerHitText: hit instanceof HTMLElement ? normalize(hit.innerText).slice(0, 120) : null,
      };
    };
    const allElements = Array.from(document.querySelectorAll("div,button,span,section"));
    const textMatches = allElements
      .filter((element) => matchesScript(element.textContent) || matchesScript(element.getAttribute("title")) || matchesScript(element.getAttribute("aria-label")))
      .map((element, index) => describeElement(element, index))
      .filter((value) => value !== null)
      .slice(0, 25);
    const legendContainers = allElements
      .filter((element) => {
        const dataName = element.getAttribute("data-name") || "";
        const className = String(element.className || "");
        return (dataName.toLowerCase().includes("legend") || className.toLowerCase().includes("legend")) && matchesScript(element.textContent);
      })
      .map((element, index) => describeElement(element, index))
      .filter((value) => value !== null)
      .slice(0, 15);
    const settingsButtons = Array.from(document.querySelectorAll('button[aria-label="Settings"], button[title="Settings"], [role="button"][aria-label="Settings"]'))
      .map((element, index) => describeElement(element, index))
      .filter((value) => value !== null)
      .slice(0, 20);
    const moreButtons = Array.from(document.querySelectorAll('button[aria-label="More"], button[title="More"], [role="button"][aria-label="More"]'))
      .map((element, index) => describeElement(element, index))
      .filter((value) => value !== null)
      .slice(0, 20);
    return {
      scriptName,
      url: location.href,
      textMatches,
      legendContainers,
      settingsButtons,
      moreButtons,
    };
  `;

  const result = await page.evaluate((source) => {
    const run = new Function(source);
    return run();
  }, probeSource) as ProbeResult;

  console.log(JSON.stringify(result, null, 2));
} finally {
  await closeTradingViewSession(session);
}