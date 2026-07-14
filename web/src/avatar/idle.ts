/**
 * Procedural idle animation: breathing, autonomous blinking, subtle head
 * sway, and coarse pose offsets. Pure logic (no DOM, no pixi) so it is
 * unit-testable and identical for the placeholder model and the final
 * custom rig (#12) — both are driven through the same standard Cubism
 * parameter IDs (docs/style-feasibility-rig.md §3).
 */

import type { AvatarPose } from "./stateMachine.ts";

/** Values for the standard Cubism parameters the renderer writes each frame. */
export interface IdleFrame {
  /** ParamAngleX/Y/Z head rotation, degrees (typical range ±30). */
  angleX: number;
  angleY: number;
  angleZ: number;
  /** ParamBodyAngleX, degrees (typical range ±10). */
  bodyAngleX: number;
  /** ParamBreath in [0, 1]. */
  breath: number;
  /** ParamEyeLOpen / ParamEyeROpen in [0, 1]; 1 = open. */
  eyeOpen: number;
}

export interface BlinkOptions {
  /** Gap between blinks is uniform in [min, max] ms. */
  minIntervalMs: number;
  maxIntervalMs: number;
  /** Lid closing / staying closed / reopening durations, ms. */
  closeMs: number;
  closedMs: number;
  openMs: number;
}

export const DEFAULT_BLINK: BlinkOptions = Object.freeze({
  minIntervalMs: 1800,
  maxIntervalMs: 5500,
  closeMs: 70,
  closedMs: 50,
  openMs: 120,
});

/**
 * Autonomous blink scheduler. `update(dt)` returns eye openness in [0, 1].
 * The RNG is injectable for deterministic tests.
 */
export class BlinkScheduler {
  private untilNextBlinkMs: number;
  /** -1 when idle; otherwise elapsed ms within the current blink. */
  private blinkElapsedMs = -1;

  constructor(
    private readonly rng: () => number = Math.random,
    private readonly options: BlinkOptions = DEFAULT_BLINK,
  ) {
    this.untilNextBlinkMs = this.nextInterval();
  }

  private nextInterval(): number {
    const { minIntervalMs, maxIntervalMs } = this.options;
    return minIntervalMs + this.rng() * (maxIntervalMs - minIntervalMs);
  }

  update(dtMs: number): number {
    const { closeMs, closedMs, openMs } = this.options;
    if (this.blinkElapsedMs < 0) {
      this.untilNextBlinkMs -= dtMs;
      if (this.untilNextBlinkMs > 0) return 1;
      this.blinkElapsedMs = 0;
    } else {
      this.blinkElapsedMs += dtMs;
    }

    const t = this.blinkElapsedMs;
    if (t < closeMs) return 1 - t / closeMs;
    if (t < closeMs + closedMs) return 0;
    const reopen = (t - closeMs - closedMs) / openMs;
    if (reopen < 1) return reopen;

    // Blink finished — schedule the next one.
    this.blinkElapsedMs = -1;
    this.untilNextBlinkMs = this.nextInterval();
    return 1;
  }
}

interface PoseOffsets {
  angleX: number;
  angleY: number;
  angleZ: number;
  bodyAngleX: number;
  /** Multiplier on sway amplitude. */
  swayScale: number;
}

/** Subtle, opinionated pose targets; renderer-agnostic degrees. */
const POSE_OFFSETS: Record<AvatarPose, PoseOffsets> = {
  neutral: { angleX: 0, angleY: 0, angleZ: 0, bodyAngleX: 0, swayScale: 1 },
  // Attentive: slight forward tilt toward the visitor, steadier head.
  attentive: { angleX: 0, angleY: -4, angleZ: 1.5, bodyAngleX: 1, swayScale: 0.6 },
  // Reflective: gaze drifts up and aside, as if considering.
  reflective: { angleX: 5, angleY: 5, angleZ: -3, bodyAngleX: -1, swayScale: 0.8 },
  // Animated: livelier sway while speaking.
  animated: { angleX: 0, angleY: 0, angleZ: 0, bodyAngleX: 0, swayScale: 1.7 },
};

export interface IdleMotionOptions {
  /** Base sway amplitudes, degrees. */
  swayAngleDeg: number;
  bodySwayDeg: number;
  /** Breathing cycle duration, ms. */
  breathPeriodMs: number;
  /** Sway base period, ms (three incommensurate sines derive from it). */
  swayPeriodMs: number;
  /** Time constant (ms) for easing toward a new pose's offsets. */
  poseEaseMs: number;
  /** Ramp-back duration (ms) after an expression reset. */
  settleMs: number;
}

export const DEFAULT_IDLE: IdleMotionOptions = Object.freeze({
  swayAngleDeg: 3,
  bodySwayDeg: 1.2,
  breathPeriodMs: 3800,
  swayPeriodMs: 5200,
  poseEaseMs: 450,
  settleMs: 900,
});

/**
 * Breathing + head sway + pose easing. `update(dt, pose)` advances time and
 * returns the frame's parameter values (excluding the mouth, which belongs
 * to lip sync). `resetExpression()` snaps everything to neutral immediately
 * (spec: interruption/error reset the expression) and eases motion back in.
 */
export class IdleMotion {
  private timeMs = 0;
  /** 0 right after a reset, ramping back to 1 over settleMs. */
  private settle = 1;
  private readonly current: PoseOffsets = { ...POSE_OFFSETS.neutral };

  constructor(
    private readonly blink: BlinkScheduler = new BlinkScheduler(),
    private readonly options: IdleMotionOptions = DEFAULT_IDLE,
  ) {}

  /** Immediate neutral: zero offsets and sway this very frame. */
  resetExpression(): void {
    this.settle = 0;
    Object.assign(this.current, POSE_OFFSETS.neutral);
  }

  update(dtMs: number, pose: AvatarPose): IdleFrame {
    const o = this.options;
    this.timeMs += dtMs;
    this.settle = Math.min(1, this.settle + (o.settleMs <= 0 ? 1 : dtMs / o.settleMs));

    // Ease current pose offsets toward the target pose.
    const target = POSE_OFFSETS[pose];
    const alpha = o.poseEaseMs <= 0 ? 1 : 1 - Math.exp(-dtMs / o.poseEaseMs);
    this.current.angleX += (target.angleX - this.current.angleX) * alpha;
    this.current.angleY += (target.angleY - this.current.angleY) * alpha;
    this.current.angleZ += (target.angleZ - this.current.angleZ) * alpha;
    this.current.bodyAngleX += (target.bodyAngleX - this.current.bodyAngleX) * alpha;
    this.current.swayScale += (target.swayScale - this.current.swayScale) * alpha;

    const t = this.timeMs;
    const two = Math.PI * 2;
    const sway = o.swayAngleDeg * this.current.swayScale * this.settle;
    const breathPhase = (1 - Math.cos((two * t) / o.breathPeriodMs)) / 2; // 0..1

    return {
      angleX: this.current.angleX * this.settle + sway * Math.sin((two * t) / o.swayPeriodMs),
      angleY:
        this.current.angleY * this.settle +
        sway * 0.6 * Math.sin((two * t) / (o.swayPeriodMs * 0.73)),
      angleZ:
        this.current.angleZ * this.settle +
        sway * 0.4 * Math.sin((two * t) / (o.swayPeriodMs * 1.31)),
      bodyAngleX:
        this.current.bodyAngleX * this.settle +
        o.bodySwayDeg *
          this.current.swayScale *
          this.settle *
          Math.sin((two * t) / (o.swayPeriodMs * 1.11)),
      breath: breathPhase,
      eyeOpen: this.blink.update(dtMs),
    };
  }
}
