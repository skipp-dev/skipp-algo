import type { Page, WebSocket } from "playwright";

/**
 * A captured TradingView `study_error`. NOTE: the monitor only ever records the
 * `unknown parent id` variant (a dead `input.source` parent) — see
 * {@link TradingViewRuntimeErrorMonitor}. Every value here is that one error kind.
 */
export type TradingViewStudyError = {
  at: string;
  /** Best-effort study id: the first 4–16-char alphanumeric token in the error
   *  payload. TradingView does not label it, so this is a heuristic, not authoritative. */
  studyId: string | null;
  message: string;
  payload: unknown;
};

export function decodeTradingViewMessages(frame: string): unknown[] {
  const messages: unknown[] = [];
  const marker = "~m~";
  let cursor = 0;
  while (cursor < frame.length) {
    const markerIndex = frame.indexOf(marker, cursor);
    if (markerIndex < 0) break;
    const lengthStart = markerIndex + marker.length;
    const lengthEnd = frame.indexOf(marker, lengthStart);
    if (lengthEnd < 0) break;
    const length = Number(frame.slice(lengthStart, lengthEnd));
    if (!Number.isInteger(length) || length < 0) {
      cursor = lengthStart;
      continue;
    }
    const payloadStart = lengthEnd + marker.length;
    const payload = frame.slice(payloadStart, payloadStart + length);
    cursor = payloadStart + length;
    try {
      messages.push(JSON.parse(payload));
    } catch {
      // TradingView also frames non-JSON protocol messages. They are irrelevant here.
    }
  }
  return messages;
}

function collectStrings(value: unknown, out: string[] = []): string[] {
  if (typeof value === "string") out.push(value);
  else if (Array.isArray(value)) value.forEach((item) => collectStrings(item, out));
  else if (value && typeof value === "object") Object.values(value).forEach((item) => collectStrings(item, out));
  return out;
}

/**
 * Watches the chart WebSocket for TradingView `study_error` frames and records
 * ONLY those reporting `unknown parent id` (a consumer whose stored
 * `input.source` parent study id is dead). Every other study/runtime error is
 * intentionally ignored — the consumer-binding flow needs just the dead-parent
 * signal. `snapshot()` therefore returns exclusively unknown-parent errors, not
 * a general runtime-error log; widen {@link record} if broader capture is ever
 * needed.
 */
export class TradingViewRuntimeErrorMonitor {
  private readonly errors: TradingViewStudyError[] = [];
  private readonly sockets = new WeakSet<WebSocket>();

  attach(page: Page): void {
    page.on("websocket", (socket) => this.attachSocket(socket));
  }

  snapshot(): TradingViewStudyError[] {
    return this.errors.map((error) => ({ ...error }));
  }

  clear(): void {
    this.errors.length = 0;
  }

  private attachSocket(socket: WebSocket): void {
    if (this.sockets.has(socket)) return;
    this.sockets.add(socket);
    socket.on("framereceived", ({ payload }) => {
      const frame = typeof payload === "string" ? payload : payload.toString("utf8");
      for (const message of decodeTradingViewMessages(frame)) this.record(message);
    });
  }

  private record(payload: unknown): void {
    if (!payload || typeof payload !== "object") return;
    const record = payload as { m?: unknown; p?: unknown };
    if (record.m !== "study_error") return;
    const strings = collectStrings(record.p);
    // Scope guard: keep ONLY the dead-parent variant; drop all other study_errors.
    const message = strings.find((value) => /unknown parent id/i.test(value));
    if (!message) return;
    const studyId = strings.find((value) => /^[A-Za-z0-9]{4,16}$/.test(value)) ?? null;
    this.errors.push({ at: new Date().toISOString(), studyId, message, payload });
  }
}
