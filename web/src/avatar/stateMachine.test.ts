/**
 * TEST SEAM 2 (spec.md): the avatar state machine as a pure module.
 * "Given sequences of agent events, assert emitted avatar states and
 * parameters: interruption closes the mouth immediately; silence means zero
 * mouth movement; error yields neutral pose. No browser, no rig, no audio."
 *
 * Issue #12's final model must pass these same tests unchanged.
 */
import { describe, expect, it } from "vitest";
import {
  AvatarStateMachine,
  DEFAULT_ERROR_MESSAGE,
  INITIAL_SNAPSHOT,
  intentOf,
  transition,
  type AgentEvent,
  type AgentReportedState,
  type AvatarState,
  type MachineSnapshot,
} from "./stateMachine.ts";

function snap(
  state: AvatarState,
  playbackActive = false,
  statusMessage: string | null = null,
): MachineSnapshot {
  return { state, playbackActive, statusMessage };
}

const ALL_STATES: AvatarState[] = [
  "idle",
  "listening",
  "thinking",
  "speaking",
  "interrupted",
  "error",
];

describe("initial state", () => {
  it("starts idle, mouth disabled, neutral pose, no status message", () => {
    const intent = intentOf(INITIAL_SNAPSHOT);
    expect(intent).toEqual({
      state: "idle",
      mouthEnabled: false,
      expressionReset: false,
      pose: "neutral",
      statusMessage: null,
    });
  });
});

describe("agent-state events", () => {
  const mappings: Array<[AgentReportedState, AvatarState]> = [
    ["initializing", "idle"],
    ["idle", "idle"],
    ["listening", "listening"],
    ["thinking", "thinking"],
    ["speaking", "speaking"],
  ];

  for (const [reported, expected] of mappings) {
    it(`maps reported "${reported}" to avatar state "${expected}"`, () => {
      const { snapshot } = transition(INITIAL_SNAPSHOT, {
        type: "agent-state",
        state: reported,
      });
      expect(snapshot.state).toBe(expected);
    });
  }

  it("recovers from error on any agent-state event and clears the message", () => {
    const { snapshot, intent } = transition(snap("error", false, "boom"), {
      type: "agent-state",
      state: "listening",
    });
    expect(snapshot.state).toBe("listening");
    expect(intent.statusMessage).toBeNull();
  });

  it("leaves interrupted when the agent moves on (e.g. thinking)", () => {
    const { snapshot } = transition(snap("interrupted"), {
      type: "agent-state",
      state: "thinking",
    });
    expect(snapshot.state).toBe("thinking");
  });

  it("sets the expected poses", () => {
    expect(intentOf(snap("listening")).pose).toBe("attentive");
    expect(intentOf(snap("thinking")).pose).toBe("reflective");
    expect(intentOf(snap("speaking")).pose).toBe("animated");
    expect(intentOf(snap("idle")).pose).toBe("neutral");
  });
});

describe("mouth rules (spec: silence ⇒ zero mouth movement)", () => {
  it("only enables the mouth in speaking WITH active playback", () => {
    for (const state of ALL_STATES) {
      for (const playback of [false, true]) {
        const intent = intentOf(snap(state, playback));
        expect(intent.mouthEnabled).toBe(state === "speaking" && playback);
      }
    }
  });

  it("keeps the mouth closed while speaking is reported but no audio plays yet", () => {
    const { intent } = transition(INITIAL_SNAPSHOT, {
      type: "agent-state",
      state: "speaking",
    });
    expect(intent.mouthEnabled).toBe(false);
  });

  it("enables the mouth once playback starts during speaking", () => {
    const speaking = transition(INITIAL_SNAPSHOT, {
      type: "agent-state",
      state: "speaking",
    }).snapshot;
    const { intent } = transition(speaking, { type: "playback-started" });
    expect(intent.mouthEnabled).toBe(true);
  });

  it("hard-disables the mouth the moment playback stops", () => {
    const { intent, snapshot } = transition(snap("speaking", true), {
      type: "playback-stopped",
    });
    expect(intent.mouthEnabled).toBe(false);
    expect(snapshot.playbackActive).toBe(false);
  });
});

describe("playback promotion", () => {
  for (const state of ["idle", "listening", "thinking"] as const) {
    it(`promotes ${state} → speaking when audio becomes audible`, () => {
      const { snapshot } = transition(snap(state), { type: "playback-started" });
      expect(snapshot.state).toBe("speaking");
      expect(snapshot.playbackActive).toBe(true);
    });
  }

  for (const state of ["interrupted", "error"] as const) {
    it(`does NOT promote ${state} on stale playback`, () => {
      const { snapshot, intent } = transition(snap(state), {
        type: "playback-started",
      });
      expect(snapshot.state).toBe(state);
      expect(intent.mouthEnabled).toBe(false);
    });
  }

  it("playback-stopped outside interrupted keeps the current state", () => {
    for (const state of ["idle", "listening", "thinking", "speaking", "error"] as const) {
      const { snapshot } = transition(snap(state, true), { type: "playback-stopped" });
      expect(snapshot.state).toBe(state);
    }
  });
});

describe("interruption (spec: mouth closes immediately, expression resets)", () => {
  it("explicit interruption from any state closes the mouth and resets expression", () => {
    for (const state of ALL_STATES) {
      const { snapshot, intent } = transition(snap(state, true), {
        type: "interruption",
      });
      expect(snapshot.state).toBe("interrupted");
      expect(intent.mouthEnabled).toBe(false);
      expect(intent.expressionReset).toBe(true);
    }
  });

  it("infers interruption when the agent flips speaking→listening while audio still plays", () => {
    const { snapshot, intent } = transition(snap("speaking", true), {
      type: "agent-state",
      state: "listening",
    });
    expect(snapshot.state).toBe("interrupted");
    expect(intent.mouthEnabled).toBe(false);
    expect(intent.expressionReset).toBe(true);
  });

  it("does NOT infer interruption on a normal end of turn (audio already stopped)", () => {
    const { snapshot, intent } = transition(snap("speaking", false), {
      type: "agent-state",
      state: "listening",
    });
    expect(snapshot.state).toBe("listening");
    expect(intent.expressionReset).toBe(false);
  });

  it("resolves interrupted → listening when the flushed audio finishes stopping", () => {
    const interrupted = transition(snap("speaking", true), {
      type: "interruption",
    }).snapshot;
    const { snapshot } = transition(interrupted, { type: "playback-stopped" });
    expect(snapshot.state).toBe("listening");
  });

  it("interrupted pose is attentive (the visitor has the floor)", () => {
    expect(intentOf(snap("interrupted")).pose).toBe("attentive");
  });
});

describe("error (spec: neutral pose + visible status message)", () => {
  it("connection error from any state yields neutral pose, closed mouth, message, reset", () => {
    for (const state of ALL_STATES) {
      const { snapshot, intent } = transition(snap(state, true), {
        type: "connection-error",
        message: "LiveKit connection lost",
      });
      expect(snapshot.state).toBe("error");
      expect(intent.pose).toBe("neutral");
      expect(intent.mouthEnabled).toBe(false);
      expect(intent.expressionReset).toBe(true);
      expect(intent.statusMessage).toBe("LiveKit connection lost");
    }
  });

  it("uses a default visible message when none is provided", () => {
    const { intent } = transition(INITIAL_SNAPSHOT, { type: "connection-error" });
    expect(intent.statusMessage).toBe(DEFAULT_ERROR_MESSAGE);
    expect(intent.statusMessage).not.toBeNull();
  });

  it("stays in error (message intact) when the disconnect that follows arrives", () => {
    const errored = transition(INITIAL_SNAPSHOT, {
      type: "connection-error",
      message: "boom",
    }).snapshot;
    const { snapshot, intent } = transition(errored, { type: "disconnected" });
    expect(snapshot.state).toBe("error");
    expect(intent.statusMessage).toBe("boom");
  });
});

describe("disconnect", () => {
  it("returns to idle with expression reset from any non-error state", () => {
    for (const state of ALL_STATES.filter((s) => s !== "error")) {
      const { snapshot, intent } = transition(snap(state, true), {
        type: "disconnected",
      });
      expect(snapshot.state).toBe("idle");
      expect(snapshot.playbackActive).toBe(false);
      expect(intent.expressionReset).toBe(true);
      expect(intent.statusMessage).toBeNull();
    }
  });
});

describe("exhaustive transition sweep", () => {
  // Every (state × playback × event) pair must produce a defined next state
  // and an intent that respects the two invariants that must NEVER break:
  //   1. mouthEnabled ⇒ state is speaking && playback active
  //   2. state error ⇒ pose neutral && statusMessage non-null
  const events: AgentEvent[] = [
    { type: "agent-state", state: "initializing" },
    { type: "agent-state", state: "idle" },
    { type: "agent-state", state: "listening" },
    { type: "agent-state", state: "thinking" },
    { type: "agent-state", state: "speaking" },
    { type: "playback-started" },
    { type: "playback-stopped" },
    { type: "interruption" },
    { type: "connection-error", message: "x" },
    { type: "disconnected" },
  ];

  it("holds the invariants across all 120 combinations", () => {
    for (const state of ALL_STATES) {
      for (const playback of [false, true]) {
        for (const event of events) {
          const start = snap(state, playback, state === "error" ? "msg" : null);
          const { snapshot, intent } = transition(start, event);
          expect(ALL_STATES).toContain(snapshot.state);
          if (intent.mouthEnabled) {
            expect(snapshot.state).toBe("speaking");
            expect(snapshot.playbackActive).toBe(true);
          }
          if (snapshot.state === "error") {
            expect(intent.pose).toBe("neutral");
            expect(intent.statusMessage).not.toBeNull();
          }
          expect(intent).toEqual({ ...intentOf(snapshot), expressionReset: intent.expressionReset });
        }
      }
    }
  });
});

describe("AvatarStateMachine wrapper", () => {
  it("walks a realistic conversation including a barge-in", () => {
    const m = new AvatarStateMachine();
    expect(m.intent.state).toBe("idle");

    expect(m.handle({ type: "agent-state", state: "listening" }).state).toBe("listening");
    expect(m.handle({ type: "agent-state", state: "thinking" }).state).toBe("thinking");
    expect(m.handle({ type: "agent-state", state: "speaking" }).mouthEnabled).toBe(false);
    expect(m.handle({ type: "playback-started" }).mouthEnabled).toBe(true);

    // Visitor barges in: agent flips to listening while audio still audible.
    const barge = m.handle({ type: "agent-state", state: "listening" });
    expect(barge.state).toBe("interrupted");
    expect(barge.mouthEnabled).toBe(false);
    expect(barge.expressionReset).toBe(true);

    // Flush completes.
    expect(m.handle({ type: "playback-stopped" }).state).toBe("listening");

    // Next turn proceeds normally and ends without an interruption.
    m.handle({ type: "agent-state", state: "thinking" });
    m.handle({ type: "agent-state", state: "speaking" });
    m.handle({ type: "playback-started" });
    expect(m.handle({ type: "playback-stopped" }).state).toBe("speaking");
    expect(m.handle({ type: "agent-state", state: "listening" }).state).toBe("listening");

    expect(m.handle({ type: "disconnected" }).state).toBe("idle");
  });

  it("reset() returns to the initial snapshot", () => {
    const m = new AvatarStateMachine();
    m.handle({ type: "connection-error" });
    m.reset();
    expect(m.snapshot).toEqual(INITIAL_SNAPSHOT);
  });
});
