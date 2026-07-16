import type { Page, WebSocket } from "playwright";

export type TradingViewStudyError = {
  at: string;
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

  hasUnknownParentError(): boolean {
    return this.errors.some((error) => /unknown parent id/i.test(error.message));
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
    const message = strings.find((value) => /unknown parent id/i.test(value));
    if (!message) return;
    const studyId = strings.find((value) => /^[A-Za-z0-9]{4,16}$/.test(value)) ?? null;
    this.errors.push({ at: new Date().toISOString(), studyId, message, payload });
  }
}
