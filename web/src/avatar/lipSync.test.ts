import { describe, expect, it } from "vitest";
import { computeRms, DEFAULT_ENVELOPE, LipSyncEnvelope } from "./lipSync.ts";

describe("computeRms", () => {
  it("is 0 for an empty buffer", () => {
    expect(computeRms(new Float32Array(0))).toBe(0);
  });

  it("is 0 for silence", () => {
    expect(computeRms(new Float32Array(512))).toBe(0);
  });

  it("is the amplitude for a square wave", () => {
    const buf = new Float32Array(100).fill(0.5);
    for (let i = 0; i < buf.length; i += 2) buf[i] = -0.5;
    expect(computeRms(buf)).toBeCloseTo(0.5, 6);
  });

  it("is amplitude/√2 for a sine wave", () => {
    const buf = new Float32Array(4800);
    for (let i = 0; i < buf.length; i++) {
      buf[i] = 0.8 * Math.sin((2 * Math.PI * i * 10) / buf.length);
    }
    expect(computeRms(buf)).toBeCloseTo(0.8 / Math.SQRT2, 3);
  });
});

describe("LipSyncEnvelope", () => {
  it("stays exactly at 0 through sustained silence (spec: silence ⇒ zero mouth)", () => {
    const env = new LipSyncEnvelope();
    for (let i = 0; i < 100; i++) {
      expect(env.update(0, 16.7)).toBe(0);
    }
  });

  it("treats sub-gate noise as silence", () => {
    const env = new LipSyncEnvelope();
    for (let i = 0; i < 100; i++) {
      expect(env.update(DEFAULT_ENVELOPE.noiseGate * 0.9, 16.7)).toBe(0);
    }
  });

  it("opens toward the target during loud audio (attack)", () => {
    const env = new LipSyncEnvelope();
    const first = env.update(0.3, 16.7);
    expect(first).toBeGreaterThan(0);
    let last = first;
    for (let i = 0; i < 20; i++) {
      const v = env.update(0.3, 16.7);
      expect(v).toBeGreaterThanOrEqual(last);
      last = v;
    }
    expect(last).toBeGreaterThan(0.5);
  });

  it("attack is faster than release", () => {
    const env = new LipSyncEnvelope();
    const rise = env.update(0.5, DEFAULT_ENVELOPE.attackMs); // one attack tau
    const afterRise = env.value;
    env.update(0, DEFAULT_ENVELOPE.attackMs); // same dt, falling
    const drop = afterRise - env.value;
    expect(rise).toBeGreaterThan(drop);
  });

  it("decays to a true 0 (snaps closed) after audio ends", () => {
    const env = new LipSyncEnvelope();
    for (let i = 0; i < 30; i++) env.update(0.5, 16.7);
    expect(env.value).toBeGreaterThan(0.5);
    let frames = 0;
    while (env.value > 0 && frames < 200) {
      env.update(0, 16.7);
      frames++;
    }
    expect(env.value).toBe(0);
    expect(frames).toBeLessThan(60); // fully closed well under a second
  });

  it("clamps to [0, 1] even for extreme RMS", () => {
    const env = new LipSyncEnvelope();
    for (let i = 0; i < 200; i++) {
      const v = env.update(10, 16.7);
      expect(v).toBeGreaterThanOrEqual(0);
      expect(v).toBeLessThanOrEqual(1);
    }
    expect(env.value).toBeCloseTo(1, 2);
  });

  it("reset() hard-zeroes immediately (interruption contract)", () => {
    const env = new LipSyncEnvelope();
    for (let i = 0; i < 30; i++) env.update(0.5, 16.7);
    expect(env.value).toBeGreaterThan(0);
    env.reset();
    expect(env.value).toBe(0);
  });

  it("is frame-rate independent (one 100ms step ≈ ten 10ms steps)", () => {
    const a = new LipSyncEnvelope();
    const b = new LipSyncEnvelope();
    a.update(0.4, 100);
    for (let i = 0; i < 10; i++) b.update(0.4, 10);
    expect(a.value).toBeCloseTo(b.value, 2);
  });
});
