/**
 * RMS lip sync (spec: "Lip sync v1 drives mouth openness from the RMS of the
 * *played* audio (Web Audio analyser) — never from generation-side timing
 * alone — so the mouth can never move out of step with what the visitor
 * hears, and closes the instant playback stops.")
 *
 * Split in two:
 *   - `computeRms` + `LipSyncEnvelope`: pure math, unit-tested.
 *   - `RmsLipSync`: thin Web Audio wrapper (AnalyserNode on the played
 *     remote track / stream). Not unit-tested by design (spec: providers and
 *     audio plumbing are perceptual/integration concerns).
 */

/** Root mean square of float PCM samples in [-1, 1]. */
export function computeRms(samples: Float32Array): number {
  if (samples.length === 0) return 0;
  let sum = 0;
  for (let i = 0; i < samples.length; i++) {
    const s = samples[i]!;
    sum += s * s;
  }
  return Math.sqrt(sum / samples.length);
}

export interface EnvelopeConfig {
  /** Time constant (ms) for the mouth opening toward a louder target. */
  attackMs: number;
  /** Time constant (ms) for the mouth closing toward a quieter target. */
  releaseMs: number;
  /** RMS→openness gain applied above the noise gate. */
  gain: number;
  /** RMS at or below this is silence: target openness 0 (spec story 20). */
  noiseGate: number;
  /** Values below this snap to exactly 0 so "closed" is truly closed. */
  closedEpsilon: number;
}

export const DEFAULT_ENVELOPE: EnvelopeConfig = Object.freeze({
  attackMs: 45,
  releaseMs: 130,
  gain: 5,
  noiseGate: 0.01,
  closedEpsilon: 0.02,
});

/**
 * Attack/decay smoothing from raw RMS to `ParamMouthOpenY` in [0, 1].
 * Pure and frame-rate independent (exponential smoothing over dt).
 */
export class LipSyncEnvelope {
  private valueInternal = 0;

  constructor(private readonly config: EnvelopeConfig = DEFAULT_ENVELOPE) {}

  get value(): number {
    return this.valueInternal;
  }

  /** Advance the envelope by `dtMs` given the current RMS; returns openness. */
  update(rms: number, dtMs: number): number {
    const { attackMs, releaseMs, gain, noiseGate, closedEpsilon } = this.config;
    const target =
      rms <= noiseGate ? 0 : Math.min(1, Math.max(0, (rms - noiseGate) * gain));
    const tau = target > this.valueInternal ? attackMs : releaseMs;
    const alpha = tau <= 0 ? 1 : 1 - Math.exp(-Math.max(0, dtMs) / tau);
    this.valueInternal += (target - this.valueInternal) * alpha;
    if (target === 0 && this.valueInternal < closedEpsilon) {
      this.valueInternal = 0; // snap fully shut — silence means closed, not "almost"
    }
    return this.valueInternal;
  }

  /** Hard zero — used when playback stops or the state machine closes the mouth. */
  reset(): void {
    this.valueInternal = 0;
  }
}

/**
 * Web Audio analyser over the audio the visitor actually hears.
 *
 * Attach either a remote `MediaStreamTrack` (LiveKit: the same track the
 * skeleton plays through its <audio> element) or a whole `MediaStream`
 * (keyless demo: a generated tone routed through a MediaStreamDestination).
 * The analyser taps the stream without rerouting playback.
 */
export class RmsLipSync {
  private ctx: AudioContext | null = null;
  private analyser: AnalyserNode | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private buffer: Float32Array<ArrayBuffer> | null = null;

  constructor(readonly envelope: LipSyncEnvelope = new LipSyncEnvelope()) {}

  attachTrack(track: MediaStreamTrack): void {
    this.attachStream(new MediaStream([track]));
  }

  attachStream(stream: MediaStream): void {
    this.detach();
    this.ctx ??= new AudioContext();
    void this.ctx.resume().catch(() => {
      /* resumed on the next user gesture */
    });
    this.analyser = this.ctx.createAnalyser();
    this.analyser.fftSize = 1024;
    this.buffer = new Float32Array(this.analyser.fftSize);
    this.source = this.ctx.createMediaStreamSource(stream);
    this.source.connect(this.analyser);
    // Deliberately NOT connected to ctx.destination: playback stays on the
    // <audio> element; we only observe.
  }

  detach(): void {
    this.source?.disconnect();
    this.source = null;
    this.analyser = null;
    this.buffer = null;
    this.envelope.reset();
  }

  /** Current RMS of the attached audio; 0 when nothing is attached. */
  currentRms(): number {
    if (!this.analyser || !this.buffer) return 0;
    this.analyser.getFloatTimeDomainData(this.buffer);
    return computeRms(this.buffer);
  }

  /** Advance the envelope one frame; returns mouth openness in [0, 1]. */
  sample(dtMs: number): number {
    return this.envelope.update(this.currentRms(), dtMs);
  }

  /** Hard-zero the mouth (playback stopped / state machine says closed). */
  reset(): void {
    this.envelope.reset();
  }

  async dispose(): Promise<void> {
    this.detach();
    if (this.ctx) {
      await this.ctx.close().catch(() => {});
      this.ctx = null;
    }
  }
}
