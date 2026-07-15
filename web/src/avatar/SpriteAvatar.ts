/**
 * Sprite avatar: the elderly-statesman portrait as an animated placeholder.
 *
 * Live2D's free sample catalog has no elderly man (checked 2026-07-15), so
 * this view animates the operator's portrait expression set directly:
 *
 *  - conversation state -> expression frame (reflective while thinking,
 *    empathetic while listening, stern on error, surprised on interruption),
 *  - RMS lip sync -> mouth-open frame swaps ("muppet mouth") while speaking,
 *  - a blink timer flashes the eyes-closed frame every few seconds,
 *  - a slow CSS breathing loop keeps the figure alive (disabled under
 *    prefers-reduced-motion).
 *
 * Same `AvatarView` contract as the Live2D renderer, so the state machine,
 * lip-sync driver, and main.ts are untouched — and the final #12 rig remains
 * a drop-in replacement for this file's view.
 *
 * All frames are same-pose edit variants of one portrait, so hard cuts
 * between them read as expression changes, not scene changes.
 */

import { RmsLipSync } from "./lipSync.ts";
import { intentOf, INITIAL_SNAPSHOT, type AvatarIntent, type AvatarState } from "./stateMachine.ts";

export const SPRITE_BASE_URL = "/avatar/portrait";

/** Frames shipped in web/public/avatar/portrait/. */
const FRAMES = [
  "default",
  "empathetic",
  "eyes-closed",
  "faintly-stern",
  "mouth-open",
  "pleased-smile",
  "reflective",
  "subtly-amused",
  "surprised",
] as const;
type FrameName = (typeof FRAMES)[number];

/** Base expression per conversation state (mouth/blink frames overlay it). */
const STATE_FRAME: Record<AvatarState, FrameName> = {
  idle: "default",
  listening: "empathetic",
  thinking: "reflective",
  speaking: "default",
  interrupted: "surprised",
  error: "faintly-stern",
};

/** Mouth-gate hysteresis on the (already smoothed) lip-sync envelope. */
const MOUTH_OPEN_AT = 0.3;
const MOUTH_CLOSE_AT = 0.18;

const BLINK_MIN_GAP_MS = 2500;
const BLINK_MAX_GAP_MS = 6500;
const BLINK_HOLD_MS = 130;

export interface SpriteAvatarOptions {
  baseUrl?: string;
  lipSync?: RmsLipSync;
}

export class SpriteAvatarView {
  readonly mode = "sprite" as const;

  private intent: AvatarIntent = intentOf(INITIAL_SNAPSHOT);
  private readonly wrapper: HTMLDivElement;
  private readonly imgs = new Map<FrameName, HTMLImageElement>();
  private shown: FrameName | null = null;

  private mouthOpen = false;
  private blinkUntil = 0;
  private nextBlinkAt = 0;
  private raf = 0;
  private lastTs = 0;
  private fpsEma = 0;

  constructor(
    private readonly container: HTMLElement,
    private readonly lipSync: RmsLipSync,
    baseUrl: string = SPRITE_BASE_URL,
  ) {
    this.wrapper = document.createElement("div");
    this.wrapper.className = "avatar-sprite";
    for (const name of FRAMES) {
      const img = document.createElement("img");
      img.src = `${baseUrl}/${name}.png`;
      img.alt = "";
      img.decoding = "async";
      img.draggable = false;
      img.style.visibility = "hidden";
      this.imgs.set(name, img);
      this.wrapper.append(img);
    }
    // The portrait is decorative chrome; the transcript carries the content.
    this.wrapper.setAttribute("aria-hidden", "true");
    container.append(this.wrapper);
    container.dataset.avatarMode = "sprite";

    this.show("default");
    this.scheduleBlink(performance.now());
    this.raf = requestAnimationFrame(this.onFrame);
  }

  get fps(): number {
    return this.fpsEma;
  }

  applyIntent(intent: AvatarIntent): void {
    this.intent = intent;
    if (intent.expressionReset) {
      // Spec: interruption/error reset expression immediately; cancel any
      // in-flight blink so the reset is visible this frame.
      this.blinkUntil = 0;
    }
    if (!intent.mouthEnabled) {
      // Spec: mouth closes the instant playback stops / interruption lands.
      this.lipSync.reset();
      this.mouthOpen = false;
    }
  }

  private onFrame = (ts: number): void => {
    const dtMs = this.lastTs > 0 ? ts - this.lastTs : 16.7;
    this.lastTs = ts;
    const instantFps = dtMs > 0 ? 1000 / dtMs : 0;
    this.fpsEma = this.fpsEma === 0 ? instantFps : this.fpsEma * 0.95 + instantFps * 0.05;

    // Mouth: hysteresis over the smoothed envelope, only while enabled.
    if (this.intent.mouthEnabled) {
      const level = this.lipSync.sample(dtMs);
      this.mouthOpen = this.mouthOpen ? level > MOUTH_CLOSE_AT : level > MOUTH_OPEN_AT;
    } else {
      this.mouthOpen = false;
    }

    // Blink: skip while the mouth frame is up (one face at a time).
    if (ts >= this.nextBlinkAt && !this.mouthOpen) {
      this.blinkUntil = ts + BLINK_HOLD_MS;
      this.scheduleBlink(ts);
    }
    const blinking = ts < this.blinkUntil;

    const base = STATE_FRAME[this.intent.state];
    const frame: FrameName = this.mouthOpen ? "mouth-open" : blinking ? "eyes-closed" : base;
    this.show(frame);

    this.raf = requestAnimationFrame(this.onFrame);
  };

  private scheduleBlink(now: number): void {
    this.nextBlinkAt =
      now + BLINK_MIN_GAP_MS + Math.random() * (BLINK_MAX_GAP_MS - BLINK_MIN_GAP_MS);
  }

  private show(name: FrameName): void {
    if (this.shown === name) return;
    if (this.shown) this.imgs.get(this.shown)!.style.visibility = "hidden";
    this.imgs.get(name)!.style.visibility = "visible";
    this.shown = name;
  }

  destroy(): void {
    cancelAnimationFrame(this.raf);
    this.wrapper.remove();
    delete this.container.dataset.avatarMode;
  }
}
