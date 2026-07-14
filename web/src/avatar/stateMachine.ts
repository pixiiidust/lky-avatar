/**
 * Avatar state machine — the project's SECOND TEST SEAM (spec.md, Testing
 * Decisions). A pure module: no DOM, no pixi, no LiveKit imports. Given agent
 * events it emits declarative avatar parameter intents; the renderer
 * (Live2DAvatar) and any future model (#12) apply them.
 *
 * Spec rules encoded here (do not weaken without changing the spec):
 *   - interrupted  ⇒ mouth closes immediately + expression resets
 *   - error        ⇒ neutral pose + visible status message
 *   - silence      ⇒ zero mouth movement (mouth is only ever enabled while
 *                    the machine is in `speaking` AND playback is active;
 *                    within speech the RMS envelope keeps silence at zero)
 *
 * Issues #6 (brain into skeleton) and #12 (final avatar) consume this exact
 * contract: feed `AgentEvent`s in, apply `AvatarIntent`s out.
 */

/** Avatar states (spec: idle | listening | thinking | speaking | interrupted | error). */
export type AvatarState =
  | "idle"
  | "listening"
  | "thinking"
  | "speaking"
  | "interrupted"
  | "error";

/**
 * Agent state values as published by LiveKit Agents via the
 * `lk.agent.state` participant attribute.
 */
export type AgentReportedState =
  | "initializing"
  | "idle"
  | "listening"
  | "thinking"
  | "speaking";

/** Inputs: everything the outside world may tell the machine. */
export type AgentEvent =
  /** `lk.agent.state` participant-attribute change. */
  | { type: "agent-state"; state: AgentReportedState }
  /** Remote agent audio became audible to the visitor. */
  | { type: "playback-started" }
  /** Remote agent audio stopped being audible (end of turn, flush, or track gone). */
  | { type: "playback-stopped" }
  /** Explicit interruption signal (barge-in detected by the integration layer). */
  | { type: "interruption" }
  /** Connection/session failure with an optional human-readable message. */
  | { type: "connection-error"; message?: string }
  /** Clean disconnect (user pressed disconnect, session ended normally). */
  | { type: "disconnected" };

/** Coarse pose the renderer maps onto head/body parameters. */
export type AvatarPose = "neutral" | "attentive" | "reflective" | "animated";

/**
 * Declarative output. The renderer must be able to apply an intent
 * idempotently at any time.
 */
export interface AvatarIntent {
  state: AvatarState;
  /**
   * false ⇒ the renderer must hold `ParamMouthOpenY` at 0 *now* (hard zero,
   * no decay). true ⇒ the mouth may follow the RMS lip-sync envelope.
   */
  mouthEnabled: boolean;
  /**
   * One-shot edge flag: true only on transitions that require an immediate
   * reset of expression/head parameters to neutral (entering interrupted,
   * entering error, returning to idle on disconnect).
   */
  expressionReset: boolean;
  pose: AvatarPose;
  /** Visible status message; non-null in the error state. */
  statusMessage: string | null;
}

/** Serializable machine state — everything `transition` needs besides the event. */
export interface MachineSnapshot {
  state: AvatarState;
  /** Whether remote audio is currently audible to the visitor. */
  playbackActive: boolean;
  statusMessage: string | null;
}

export const INITIAL_SNAPSHOT: MachineSnapshot = Object.freeze({
  state: "idle",
  playbackActive: false,
  statusMessage: null,
});

export const DEFAULT_ERROR_MESSAGE =
  "Connection error — the conversation was lost. Please reconnect.";

const POSE_BY_STATE: Record<AvatarState, AvatarPose> = {
  idle: "neutral",
  listening: "attentive",
  thinking: "reflective",
  speaking: "animated",
  // The visitor interrupted because they want to talk: look attentive.
  interrupted: "attentive",
  error: "neutral",
};

/** Map the LiveKit-reported agent state onto an avatar state. */
function mapAgentState(reported: AgentReportedState): AvatarState {
  return reported === "initializing" ? "idle" : reported;
}

/**
 * Steady-state intent derived from a snapshot. `expressionReset` is
 * edge-triggered and therefore always false here; use {@link transition} to
 * observe it.
 */
export function intentOf(snapshot: MachineSnapshot): AvatarIntent {
  return {
    state: snapshot.state,
    mouthEnabled: snapshot.state === "speaking" && snapshot.playbackActive,
    expressionReset: false,
    pose: POSE_BY_STATE[snapshot.state],
    statusMessage: snapshot.statusMessage,
  };
}

export interface TransitionResult {
  snapshot: MachineSnapshot;
  intent: AvatarIntent;
}

/**
 * Pure transition function.
 *
 * Interruption is accepted explicitly (`interruption`) and also inferred:
 * if the agent flips from `speaking` to `listening` while its audio is still
 * audible, the visitor barged in. The inferred path exists because the
 * client cannot always observe barge-in directly.
 */
export function transition(
  snapshot: MachineSnapshot,
  event: AgentEvent,
): TransitionResult {
  let next: MachineSnapshot;
  let expressionReset = false;

  switch (event.type) {
    case "agent-state": {
      const target = mapAgentState(event.state);
      const inferredInterruption =
        snapshot.state === "speaking" &&
        snapshot.playbackActive &&
        target === "listening";
      if (inferredInterruption) {
        next = { ...snapshot, state: "interrupted", statusMessage: null };
        expressionReset = true;
      } else {
        // Any agent-state event also recovers from interrupted/error:
        // a live agent is talking to us again.
        next = { ...snapshot, state: target, statusMessage: null };
      }
      break;
    }

    case "playback-started": {
      // Audible audio is ground truth that the agent is speaking — promote
      // calm states even if the attribute update is late. Never promote out
      // of interrupted/error: audio arriving there is stale.
      const promote =
        snapshot.state === "idle" ||
        snapshot.state === "listening" ||
        snapshot.state === "thinking";
      next = {
        ...snapshot,
        state: promote ? "speaking" : snapshot.state,
        playbackActive: true,
      };
      break;
    }

    case "playback-stopped": {
      // While interrupted, playback stopping means the flush completed and
      // the visitor has the floor: resolve to listening.
      const state = snapshot.state === "interrupted" ? "listening" : snapshot.state;
      next = { ...snapshot, state, playbackActive: false };
      break;
    }

    case "interruption": {
      next = { ...snapshot, state: "interrupted", statusMessage: null };
      expressionReset = true;
      break;
    }

    case "connection-error": {
      next = {
        state: "error",
        playbackActive: false,
        statusMessage: event.message ?? DEFAULT_ERROR_MESSAGE,
      };
      expressionReset = true;
      break;
    }

    case "disconnected": {
      if (snapshot.state === "error") {
        // Keep the visible error message; a clean-up disconnect must not
        // silently swallow the failure the visitor needs to see.
        next = { ...snapshot, playbackActive: false };
      } else {
        next = { state: "idle", playbackActive: false, statusMessage: null };
        expressionReset = true;
      }
      break;
    }
  }

  return {
    snapshot: next,
    intent: { ...intentOf(next), expressionReset },
  };
}

/**
 * Convenience stateful wrapper (still pure logic — no environment access).
 */
export class AvatarStateMachine {
  private current: MachineSnapshot = INITIAL_SNAPSHOT;

  get snapshot(): MachineSnapshot {
    return this.current;
  }

  /** Steady-state intent for the current snapshot. */
  get intent(): AvatarIntent {
    return intentOf(this.current);
  }

  /** Apply an event; returns the intent for the transition just taken. */
  handle(event: AgentEvent): AvatarIntent {
    const { snapshot, intent } = transition(this.current, event);
    this.current = snapshot;
    return intent;
  }

  reset(): void {
    this.current = INITIAL_SNAPSHOT;
  }
}
