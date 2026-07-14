/**
 * Session-gate slates (issue #13). The token server can now refuse to start
 * an interview: 409 while the studio already holds a live visitor
 * (single-session enforcement) and 429 when one connection asks too often
 * (per-IP rate limit). Both must render inside the studio identity — a
 * slate card with retry guidance in the broadcast vocabulary — never as a
 * raw error.
 *
 * Pure module: maps (HTTP status, parsed body) to a slate view; no DOM, no
 * fetch. Tested in gate.test.ts; main.ts wires it to fetchToken failures.
 */

export interface GateNotice {
  kind: "busy" | "rate-limited";
  /** Slate caption (CSS sets it in letterspaced caps). */
  caption: string;
  /** One sentence of ink, including retry guidance. */
  message: string;
}

/** Structured refusal body minted by services/token_server (issue #13). */
interface GateDetail {
  reason?: unknown;
  message?: unknown;
  retry_after_seconds?: unknown;
}

const BUSY_FALLBACK =
  "LKY is in session with another visitor — please try again in a few minutes.";
const RATE_LIMITED_FALLBACK =
  "Too many interview requests from your connection — " +
  "please wait a moment and try again.";

function detailOf(body: unknown): GateDetail {
  if (typeof body !== "object" || body === null) return {};
  const detail = (body as { detail?: unknown }).detail;
  if (typeof detail !== "object" || detail === null) return {};
  return detail as GateDetail;
}

function messageOf(detail: GateDetail, fallback: string): string {
  return typeof detail.message === "string" && detail.message.length > 0
    ? detail.message
    : fallback;
}

/**
 * The designed notice for a refused token request, or null when the failure
 * is not one of the gate's designed states (the caller then falls back to
 * the generic connection-error path).
 */
export function gateNoticeFor(status: number, body: unknown): GateNotice | null {
  const detail = detailOf(body);
  if (status === 409 && detail.reason === "busy") {
    return {
      kind: "busy",
      caption: "In session",
      message: messageOf(detail, BUSY_FALLBACK),
    };
  }
  if (status === 429) {
    return {
      kind: "rate-limited",
      caption: "Hold the line",
      message: messageOf(detail, RATE_LIMITED_FALLBACK),
    };
  }
  return null;
}
