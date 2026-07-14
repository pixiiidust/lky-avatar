/**
 * Live2D renderer: applies `AvatarIntent`s from the state machine to a
 * Cubism 4 model via pixi-live2d-display, with procedural idle animation
 * (breathing / blinking / head sway) and RMS lip sync.
 *
 * All animation drives the standard Cubism parameter IDs
 * (`ParamMouthOpenY`, `ParamEyeLOpen`, `ParamEyeROpen`, `ParamAngle*`,
 * `ParamBodyAngleX`, `ParamBreath` — see docs/style-feasibility-rig.md §3),
 * so the final custom model (#12) is a drop-in swap: point `modelUrl` at the
 * new `.model3.json` and everything else is unchanged.
 *
 * If WebGL, the Cubism core, or the model fails to load, `createAvatarView`
 * degrades to a static-image fallback (spec story 21) instead of throwing.
 */

import { Application, UPDATE_PRIORITY } from "pixi.js";
// Type-only imports are erased at runtime. The plugin module MUST NOT be
// statically imported: its cubism4 entry throws at evaluation time when the
// (CDN-loaded, proprietary) Cubism core script isn't present yet, which
// would take the whole app down instead of degrading to the fallback. The
// value import happens dynamically in `Live2DAvatar.create` after
// `loadCubismCore()` resolves.
import type {
  Cubism4InternalModel,
  Live2DModel,
} from "pixi-live2d-display-lipsyncpatch/cubism4";
import { loadCubismCore } from "./cubismCore.ts";
import { RmsLipSync } from "./lipSync.ts";
import { IdleMotion } from "./idle.ts";
import { intentOf, INITIAL_SNAPSHOT, type AvatarIntent } from "./stateMachine.ts";

/** Default placeholder model location (see scripts/fetch_placeholder_model.py). */
export const DEFAULT_MODEL_URL = "/models/hiyori/Hiyori.model3.json";
export const DEFAULT_FALLBACK_IMAGE_URL = "/avatar-fallback.svg";

/** What main.ts (and the demo) talk to, regardless of rendering mode. */
export interface AvatarView {
  readonly mode: "live2d" | "fallback";
  /** Why the fallback engaged (fallback mode only). */
  readonly fallbackReason?: string;
  applyIntent(intent: AvatarIntent): void;
  /** Rolling average frames per second (0 in fallback mode). */
  readonly fps: number;
  destroy(): void;
}

export interface AvatarViewOptions {
  modelUrl?: string;
  fallbackImageUrl?: string;
  lipSync?: RmsLipSync;
  idle?: IdleMotion;
}

/**
 * Mount an avatar into `container`. Never rejects for rendering reasons:
 * failures produce the static-image fallback view.
 */
export async function createAvatarView(
  container: HTMLElement,
  options: AvatarViewOptions = {},
): Promise<AvatarView> {
  const lipSync = options.lipSync ?? new RmsLipSync();
  try {
    await loadCubismCore();
    const avatar = await Live2DAvatar.create(container, {
      modelUrl: options.modelUrl ?? DEFAULT_MODEL_URL,
      lipSync,
      idle: options.idle ?? new IdleMotion(),
    });
    return avatar;
  } catch (err) {
    const reason = err instanceof Error ? err.message : String(err);
    console.warn("Live2D unavailable, using static fallback:", reason);
    return new StaticFallbackView(
      container,
      options.fallbackImageUrl ?? DEFAULT_FALLBACK_IMAGE_URL,
      reason,
    );
  }
}

interface Live2DAvatarConfig {
  modelUrl: string;
  lipSync: RmsLipSync;
  idle: IdleMotion;
}

/** The event surface the package's broken d.ts drops from InternalModel. */
interface InternalModelEmitter {
  on(event: "afterMotionUpdate", fn: () => void): void;
}

/** Frame parameter values written into the Cubism core model. */
interface FrameParams {
  angleX: number;
  angleY: number;
  angleZ: number;
  bodyAngleX: number;
  breath: number;
  eyeOpen: number;
  mouthOpen: number;
}

export class Live2DAvatar implements AvatarView {
  readonly mode = "live2d" as const;

  private intent: AvatarIntent = intentOf(INITIAL_SNAPSHOT);
  private pending: FrameParams | null = null;
  private fpsEma = 0;
  private resizeObserver: ResizeObserver;

  private constructor(
    private readonly container: HTMLElement,
    private readonly app: Application,
    private readonly model: Live2DModel,
    private readonly lipSync: RmsLipSync,
    private readonly idle: IdleMotion,
  ) {
    // Take over all parameter animation: no canned motions, no built-in
    // auto-blink/breath — everything comes from IdleMotion + lip sync so the
    // behavior is identical on the #12 custom rig (which has no motions).
    const internal = this.model.internalModel as Cubism4InternalModel;
    internal.eyeBlink = undefined;
    (internal as { breath?: unknown }).breath = undefined;
    // afterMotionUpdate fires between the motion update and saveParameters(),
    // so values written here persist and are seen by physics (hair/body sway).
    // (Cast: the package's bundled d.ts loses the EventEmitter base class.)
    (internal as unknown as InternalModelEmitter).on("afterMotionUpdate", () =>
      this.writeParams(),
    );

    this.app.stage.addChild(this.model);
    this.app.ticker.add(this.onTick, this, UPDATE_PRIORITY.NORMAL);

    this.resizeObserver = new ResizeObserver(() => this.layout());
    this.resizeObserver.observe(this.container);
    this.layout();
  }

  static async create(
    container: HTMLElement,
    config: Live2DAvatarConfig,
  ): Promise<Live2DAvatar> {
    const { Live2DModel, MotionPreloadStrategy } = await import(
      "pixi-live2d-display-lipsyncpatch/cubism4"
    );
    const canvas = document.createElement("canvas");
    canvas.className = "avatar-canvas";
    let app: Application | null = null;
    try {
      app = new Application({
        view: canvas,
        backgroundAlpha: 0,
        antialias: true,
        autoDensity: true,
        resolution: Math.min(window.devicePixelRatio || 1, 2),
        width: Math.max(1, container.clientWidth),
        height: Math.max(1, container.clientHeight),
      });
      const model = await Live2DModel.from(config.modelUrl, {
        autoUpdate: false,
        autoHitTest: false,
        autoFocus: false,
        motionPreload: MotionPreloadStrategy.NONE,
        // Point the idle group at a name that doesn't exist so the library
        // never auto-plays canned idle motions over our parameters.
        idleMotionGroup: "__procedural_idle__",
      });
      container.append(canvas);
      return new Live2DAvatar(container, app, model, config.lipSync, config.idle);
    } catch (err) {
      app?.destroy(true, { children: true, texture: true });
      canvas.remove();
      throw err;
    }
  }

  get fps(): number {
    return this.fpsEma;
  }

  applyIntent(intent: AvatarIntent): void {
    this.intent = intent;
    if (intent.expressionReset) {
      // Spec: interruption/error reset the expression immediately.
      this.idle.resetExpression();
    }
    if (!intent.mouthEnabled) {
      // Spec: mouth closes the instant playback stops / interruption lands.
      this.lipSync.reset();
    }
  }

  private onTick(): void {
    const dtMs = this.app.ticker.deltaMS;
    const instantFps = dtMs > 0 ? 1000 / dtMs : 0;
    this.fpsEma = this.fpsEma === 0 ? instantFps : this.fpsEma * 0.95 + instantFps * 0.05;

    const frame = this.idle.update(dtMs, this.intent.pose);
    const mouthOpen = this.intent.mouthEnabled ? this.lipSync.sample(dtMs) : 0;
    this.pending = { ...frame, mouthOpen };
    this.model.update(dtMs); // triggers afterMotionUpdate → writeParams()
  }

  /** Runs inside the model update, before parameters are saved/rendered. */
  private writeParams(): void {
    if (!this.pending) return;
    const core = (this.model.internalModel as Cubism4InternalModel).coreModel;
    const p = this.pending;
    core.setParameterValueById("ParamAngleX", p.angleX);
    core.setParameterValueById("ParamAngleY", p.angleY);
    core.setParameterValueById("ParamAngleZ", p.angleZ);
    core.setParameterValueById("ParamBodyAngleX", p.bodyAngleX);
    core.setParameterValueById("ParamBreath", p.breath);
    core.setParameterValueById("ParamEyeLOpen", p.eyeOpen);
    core.setParameterValueById("ParamEyeROpen", p.eyeOpen);
    core.setParameterValueById("ParamMouthOpenY", p.mouthOpen);
  }

  /** Bust framing: fit width/height, zoom in on the upper body. */
  private layout(): void {
    const w = Math.max(1, this.container.clientWidth);
    const h = Math.max(1, this.container.clientHeight);
    this.app.renderer.resize(w, h);

    const ow = this.model.internalModel.originalWidth;
    const oh = this.model.internalModel.originalHeight;
    const zoom = 1.9;
    const scale = Math.min(w / ow, h / oh) * zoom;
    this.model.scale.set(scale);
    this.model.anchor.set(0.5, 0.02);
    this.model.position.set(w / 2, 0);
  }

  destroy(): void {
    this.resizeObserver.disconnect();
    this.app.ticker.remove(this.onTick, this);
    this.app.destroy(true, { children: true, texture: true });
  }
}

/** Static-image fallback (spec story 21): degrade, don't crash. */
class StaticFallbackView implements AvatarView {
  readonly mode = "fallback" as const;
  readonly fps = 0;
  private readonly img: HTMLImageElement;
  private readonly note: HTMLParagraphElement;

  constructor(
    private readonly container: HTMLElement,
    imageUrl: string,
    readonly fallbackReason: string,
  ) {
    this.img = document.createElement("img");
    this.img.src = imageUrl;
    this.img.alt = "Static avatar placeholder";
    this.img.className = "avatar-fallback-image";
    this.note = document.createElement("p");
    this.note.className = "avatar-fallback-note";
    this.note.textContent =
      "Animated avatar unavailable on this browser — showing a still image.";
    container.append(this.img, this.note);
    container.dataset.avatarMode = "fallback";
  }

  applyIntent(intent: AvatarIntent): void {
    this.container.dataset.avatarState = intent.state;
    if (intent.state === "error" && intent.statusMessage) {
      this.note.textContent = intent.statusMessage;
    }
  }

  destroy(): void {
    this.img.remove();
    this.note.remove();
    delete this.container.dataset.avatarMode;
    delete this.container.dataset.avatarState;
  }
}
