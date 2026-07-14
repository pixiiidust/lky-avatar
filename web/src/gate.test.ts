import { describe, expect, it } from "vitest";
import { gateNoticeFor } from "./gate.ts";

const busyBody = {
  detail: {
    reason: "busy",
    message: "LKY is in session with another visitor — please try again in a few minutes.",
    retry_after_seconds: 120,
  },
};

const rateLimitedBody = {
  detail: {
    reason: "rate_limited",
    message: "Too many interview requests from your connection — please wait a moment and try again.",
    retry_after_seconds: 10,
  },
};

describe("gateNoticeFor", () => {
  it("renders the occupied studio as the IN SESSION slate with retry guidance", () => {
    const notice = gateNoticeFor(409, busyBody);
    expect(notice).toEqual({
      kind: "busy",
      caption: "In session",
      message: busyBody.detail.message,
    });
    expect(notice!.message).toMatch(/try again/);
  });

  it("renders the rate limit in the studio's voice, not as a raw error", () => {
    const notice = gateNoticeFor(429, rateLimitedBody);
    expect(notice).toEqual({
      kind: "rate-limited",
      caption: "Hold the line",
      message: rateLimitedBody.detail.message,
    });
  });

  it("falls back to designed wording when the body is malformed", () => {
    expect(gateNoticeFor(409, { detail: { reason: "busy" } })!.message).toMatch(
      /try again in a few minutes/,
    );
    expect(gateNoticeFor(429, "not json at all")!.message).toMatch(/wait a moment/);
    expect(gateNoticeFor(429, null)!.caption).toBe("Hold the line");
  });

  it("leaves every other failure to the generic connection-error path", () => {
    expect(gateNoticeFor(503, { detail: "credentials missing" })).toBeNull();
    expect(gateNoticeFor(500, {})).toBeNull();
    // A 409 that is not the designed busy body is not the gate's state.
    expect(gateNoticeFor(409, { detail: { reason: "conflict" } })).toBeNull();
  });
});
