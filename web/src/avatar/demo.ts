/**
 * Keyless avatar demo (`?avatarDemo=1`): drives the avatar with a scripted
 * fake-agent event sequence plus a locally generated speech-like tone, so
 * idle / blink / lip-sync / interruption behavior and the 50 FPS target can
 * be eyeballed without any LiveKit credentials. See web/README.md.
 */

import {
  AvatarStateMachine,
  type AgentEvent,
  type AvatarIntent,
} from "./stateMachine.ts";
import type { RmsLipSync } from "./lipSync.ts";
import type { AvatarView } from "./Live2DAvatar.ts";

export interface DemoContext {
  view: AvatarView;
  lipSync: RmsLipSync;
  /** Where demo controls are appended. */
  panel: HTMLElement;
  /** Called after every event with the resulting intent (status display). */
  onIntent: (intent: AvatarIntent) => void;
  /** Where the (audible) demo audio element is parked. */
  audioSink: HTMLElement;
}

/**
 * Generates a speech-like amplitude-modulated tone into a MediaStream and an
 * audible <audio> element — the same "played audio" path the real client
 * uses, so the analyser taps genuine playback.
 */
class ToneSpeaker {
  private ctx: AudioContext | null = null;
  private gain: GainNode | null = null;
  private dest: MediaStreamAudioDestinationNode | null = null;
  private el: HTMLAudioElement | null = null;
  private stopTimer: number | null = null;

  constructor(
    private readonly audioSink: HTMLElement,
    private readonly onStarted: () => void,
    private readonly onStopped: () => void,
  ) {}

  private ensureGraph(): { ctx: AudioContext; gain: GainNode; stream: MediaStream } {
    if (!this.ctx) {
      this.ctx = new AudioContext();
      this.dest = this.ctx.createMediaStreamDestination();
      const osc = this.ctx.createOscillator();
      osc.type = "sawtooth";
      osc.frequency.value = 110; // elder-statesman baritone, allegedly
      const shape = this.ctx.createBiquadFilter();
      shape.type = "lowpass";
      shape.frequency.value = 900;
      this.gain = this.ctx.createGain();
      this.gain.gain.value = 0;
      osc.connect(shape).connect(this.gain).connect(this.dest);
      osc.start();
      this.el = document.createElement("audio");
      this.el.srcObject = this.dest.stream;
      this.el.dataset.demo = "tone";
      this.audioSink.append(this.el);
      this.el.addEventListener("playing", this.onStarted);
      this.el.addEventListener("pause", this.onStopped);
    }
    return { ctx: this.ctx, gain: this.gain!, stream: this.dest!.stream };
  }

  get stream(): MediaStream {
    return this.ensureGraph().stream;
  }

  /** Speak for `ms`, with syllable bursts and a mid-utterance silence. */
  speak(ms: number): void {
    const { ctx, gain } = this.ensureGraph();
    void ctx.resume();
    void this.el!.play();
    gain.gain.cancelScheduledValues(ctx.currentTime);
    let t = ctx.currentTime + 0.05;
    const end = t + ms / 1000;
    let sinceRest = 0;
    gain.gain.setValueAtTime(0, ctx.currentTime);
    while (t < end) {
      // One "syllable": quick rise, quick fall.
      const level = 0.25 + Math.random() * 0.4;
      gain.gain.linearRampToValueAtTime(level, t + 0.06);
      gain.gain.linearRampToValueAtTime(0.05, t + 0.16);
      t += 0.18;
      sinceRest += 0.18;
      if (sinceRest > 1.2) {
        // Pause between phrases — the mouth must visibly close here
        // (spec: silence ⇒ zero mouth movement).
        gain.gain.linearRampToValueAtTime(0, t + 0.03);
        t += 0.45;
        sinceRest = 0;
      }
    }
    gain.gain.linearRampToValueAtTime(0, end + 0.05);
    if (this.stopTimer !== null) window.clearTimeout(this.stopTimer);
    this.stopTimer = window.setTimeout(() => this.stop(), ms + 120);
  }

  /** Immediate stop (interruption): silence + pause the element. */
  stop(): void {
    if (this.stopTimer !== null) {
      window.clearTimeout(this.stopTimer);
      this.stopTimer = null;
    }
    if (this.ctx && this.gain) {
      this.gain.gain.cancelScheduledValues(this.ctx.currentTime);
      this.gain.gain.setValueAtTime(0, this.ctx.currentTime);
    }
    this.el?.pause();
  }
}

export function startAvatarDemo(context: DemoContext): void {
  const machine = new AvatarStateMachine();
  const dispatch = (event: AgentEvent): void => {
    const intent = machine.handle(event);
    context.view.applyIntent(intent);
    context.onIntent(intent);
    log(`${event.type}${"state" in event ? `(${event.state})` : ""} → ${intent.state}`);
  };

  const tone = new ToneSpeaker(
    context.audioSink,
    () => dispatch({ type: "playback-started" }),
    () => dispatch({ type: "playback-stopped" }),
  );

  // --- controls -----------------------------------------------------------
  const panel = context.panel;
  panel.hidden = false;

  const readout = document.createElement("p");
  readout.className = "demo-readout";
  panel.append(readout);

  const logEl = document.createElement("ol");
  logEl.className = "demo-log";

  const buttons = document.createElement("div");
  buttons.className = "demo-buttons";
  panel.append(buttons, logEl);

  function log(line: string): void {
    const li = document.createElement("li");
    li.textContent = line;
    logEl.prepend(li);
    while (logEl.childElementCount > 12) logEl.lastElementChild?.remove();
  }

  function button(label: string, onClick: () => void): HTMLButtonElement {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = label;
    b.addEventListener("click", onClick);
    buttons.append(b);
    return b;
  }

  const speakFor = (ms: number): void => {
    dispatch({ type: "agent-state", state: "speaking" });
    // Attach the analyser to the demo stream the first time we speak.
    context.lipSync.attachStream(tone.stream);
    tone.speak(ms);
  };

  // --- scripted sequence ---------------------------------------------------
  let scriptRun = 0; // increment cancels any running script
  const sleep = (ms: number): Promise<void> =>
    new Promise((resolve) => window.setTimeout(resolve, ms));

  async function runScript(run: number): Promise<void> {
    const alive = (): boolean => run === scriptRun;
    while (alive()) {
      dispatch({ type: "agent-state", state: "idle" });
      await sleep(2000);
      if (!alive()) return;
      dispatch({ type: "agent-state", state: "listening" });
      await sleep(2200);
      if (!alive()) return;
      dispatch({ type: "agent-state", state: "thinking" });
      await sleep(1600);
      if (!alive()) return;

      // Speak, then get interrupted mid-sentence: the mouth must snap shut
      // and the expression reset the moment "Interrupt" lands.
      speakFor(6000);
      await sleep(3200);
      if (!alive()) return;
      dispatch({ type: "interruption" });
      tone.stop();
      await sleep(1800);
      if (!alive()) return;

      // A full uninterrupted turn.
      dispatch({ type: "agent-state", state: "thinking" });
      await sleep(1100);
      if (!alive()) return;
      speakFor(4200);
      await sleep(4600);
      if (!alive()) return;
      dispatch({ type: "agent-state", state: "listening" });
      await sleep(1400);
      if (!alive()) return;

      // Error: neutral pose + visible status message, then recovery.
      dispatch({ type: "connection-error", message: "Demo: simulated connection error" });
      await sleep(3000);
      if (!alive()) return;
      dispatch({ type: "agent-state", state: "listening" });
      await sleep(1500);
      if (!alive()) return;
      dispatch({ type: "disconnected" });
      await sleep(2200);
    }
  }

  const runBtn = button("▶ Run script", () => {
    scriptRun++;
    if (runBtn.dataset.running === "1") {
      delete runBtn.dataset.running;
      runBtn.textContent = "▶ Run script";
      tone.stop();
      dispatch({ type: "disconnected" });
    } else {
      runBtn.dataset.running = "1";
      runBtn.textContent = "■ Stop script";
      void runScript(scriptRun);
    }
  });

  button("Listening", () => dispatch({ type: "agent-state", state: "listening" }));
  button("Thinking", () => dispatch({ type: "agent-state", state: "thinking" }));
  button("Speak 5s", () => speakFor(5000));
  button("Interrupt", () => {
    dispatch({ type: "interruption" });
    tone.stop();
  });
  button("Error", () =>
    dispatch({ type: "connection-error", message: "Demo: simulated connection error" }),
  );
  button("Disconnect", () => dispatch({ type: "disconnected" }));

  // --- FPS / state readout (50+ FPS is an acceptance criterion) ------------
  window.setInterval(() => {
    const intent = machine.intent;
    const fps = context.view.fps;
    readout.textContent =
      `mode: ${context.view.mode} · fps: ${fps.toFixed(0)}` +
      ` · state: ${intent.state} · mouth: ${intent.mouthEnabled ? "live" : "closed"}`;
    readout.dataset.fpsOk = fps === 0 || fps >= 50 ? "1" : "0";
  }, 500);

  context.onIntent(machine.intent);
}
