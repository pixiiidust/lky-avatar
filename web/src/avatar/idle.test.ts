import { describe, expect, it } from "vitest";
import { BlinkScheduler, DEFAULT_BLINK, DEFAULT_IDLE, IdleMotion } from "./idle.ts";

describe("BlinkScheduler", () => {
  it("keeps eyes open until the first scheduled blink", () => {
    const blink = new BlinkScheduler(() => 0.5); // interval = midpoint
    const interval =
      DEFAULT_BLINK.minIntervalMs +
      0.5 * (DEFAULT_BLINK.maxIntervalMs - DEFAULT_BLINK.minIntervalMs);
    let elapsed = 0;
    while (elapsed + 16 < interval) {
      expect(blink.update(16)).toBe(1);
      elapsed += 16;
    }
  });

  it("runs a full close→hold→reopen cycle and returns to open", () => {
    const blink = new BlinkScheduler(() => 0, {
      minIntervalMs: 100,
      maxIntervalMs: 100,
      closeMs: 60,
      closedMs: 40,
      openMs: 60,
    });
    blink.update(100); // reach the blink start
    const closing = blink.update(30); // 30ms into 60ms close
    expect(closing).toBeCloseTo(0.5, 5);
    const closed = blink.update(30); // fully closed
    expect(closed).toBeLessThanOrEqual(0.001);
    blink.update(40); // hold closed
    const reopening = blink.update(30); // 30ms into 60ms reopen
    expect(reopening).toBeCloseTo(0.5, 5);
    expect(blink.update(40)).toBe(1); // done, back to open
  });

  it("blinks repeatedly (autonomous)", () => {
    const blink = new BlinkScheduler(() => 0, {
      minIntervalMs: 200,
      maxIntervalMs: 200,
      closeMs: 50,
      closedMs: 30,
      openMs: 50,
    });
    let closures = 0;
    let wasClosed = false;
    for (let t = 0; t < 5000; t += 10) {
      const v = blink.update(10);
      const isClosed = v < 0.01;
      if (isClosed && !wasClosed) closures++;
      wasClosed = isClosed;
    }
    expect(closures).toBeGreaterThanOrEqual(10);
  });
});

describe("IdleMotion", () => {
  const stillBlink = () =>
    new BlinkScheduler(() => 1, {
      ...DEFAULT_BLINK,
      minIntervalMs: 1e9,
      maxIntervalMs: 1e9,
    });

  it("breathes on a cycle (values span [0,1] over a period)", () => {
    const idle = new IdleMotion(stillBlink());
    let min = Infinity;
    let max = -Infinity;
    for (let t = 0; t < DEFAULT_IDLE.breathPeriodMs * 2; t += 16) {
      const f = idle.update(16, "neutral");
      min = Math.min(min, f.breath);
      max = Math.max(max, f.breath);
      expect(f.breath).toBeGreaterThanOrEqual(0);
      expect(f.breath).toBeLessThanOrEqual(1);
    }
    expect(min).toBeLessThan(0.1);
    expect(max).toBeGreaterThan(0.9);
  });

  it("sways the head subtly and within bounds in neutral", () => {
    const idle = new IdleMotion(stillBlink());
    let moved = false;
    let prev: number | null = null;
    for (let t = 0; t < 20000; t += 16) {
      const f = idle.update(16, "neutral");
      expect(Math.abs(f.angleX)).toBeLessThanOrEqual(DEFAULT_IDLE.swayAngleDeg + 0.01);
      if (prev !== null && Math.abs(f.angleX - prev) > 1e-4) moved = true;
      prev = f.angleX;
    }
    expect(moved).toBe(true);
  });

  it("animated pose sways more than attentive pose", () => {
    const amp = (pose: "animated" | "attentive"): number => {
      const idle = new IdleMotion(stillBlink());
      let max = 0;
      for (let t = 0; t < 30000; t += 16) {
        const f = idle.update(16, pose);
        if (t > 5000) max = Math.max(max, Math.abs(f.angleX)); // after easing
      }
      return max;
    };
    expect(amp("animated")).toBeGreaterThan(amp("attentive"));
  });

  it("eases toward pose offsets (reflective tilts the head up and aside)", () => {
    const idle = new IdleMotion(
      stillBlink(),
      { ...DEFAULT_IDLE, swayAngleDeg: 0, bodySwayDeg: 0 }, // isolate offsets
    );
    let f = idle.update(16, "reflective");
    for (let t = 0; t < 5000; t += 16) f = idle.update(16, "reflective");
    expect(f.angleX).toBeCloseTo(5, 1);
    expect(f.angleY).toBeCloseTo(5, 1);
  });

  it("resetExpression() snaps head angles to neutral immediately", () => {
    const idle = new IdleMotion(stillBlink());
    for (let t = 0; t < 5000; t += 16) idle.update(16, "reflective");
    idle.resetExpression();
    const f = idle.update(16, "attentive");
    // First frame after a reset: everything at (or a hair from) zero.
    expect(Math.abs(f.angleX)).toBeLessThan(0.35);
    expect(Math.abs(f.angleY)).toBeLessThan(0.35);
    expect(Math.abs(f.angleZ)).toBeLessThan(0.35);
    expect(Math.abs(f.bodyAngleX)).toBeLessThan(0.35);
  });

  it("recovers full sway after a reset (settle ramps back to 1)", () => {
    const idle = new IdleMotion(stillBlink());
    idle.resetExpression();
    let max = 0;
    for (let t = 0; t < 30000; t += 16) {
      const f = idle.update(16, "neutral");
      if (t > DEFAULT_IDLE.settleMs * 3) max = Math.max(max, Math.abs(f.angleX));
    }
    expect(max).toBeGreaterThan(DEFAULT_IDLE.swayAngleDeg * 0.5);
  });
});
