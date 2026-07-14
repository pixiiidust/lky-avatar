/**
 * Studio lamp — the design's signature element (docs/design-interview-studio.md §4).
 *
 * A pure mapping from what the client knows (connection phase, avatar state
 * machine state, brain status) to the lamp's presentation: a caption in the
 * broadcast/parliamentary vocabulary plus a light behavior. One accent color,
 * six legible states — never six status colors.
 *
 * Pure module: no DOM imports, unit-tested in lamp.test.ts.
 */

import type { AvatarState } from "./avatar/stateMachine.ts";

/** How the lamp face is lit. `pulse` degrades to `low` under reduced motion (CSS). */
export type LampLight = "off" | "low" | "full" | "pulse";

export interface LampView {
  caption: string;
  light: LampLight;
  /**
   * true while a live exchange is possible (drives the "warm" housing).
   * false = the set is cold (standby, connecting, off-air error).
   */
  live: boolean;
}

export type ConnectionPhase = "disconnected" | "connecting" | "connected";

export interface LampInputs {
  connection: ConnectionPhase;
  avatarState: AvatarState;
  /** Last `lky.brain` status reported by the agent ("ok" | "busy" | "error"). */
  brainStatus: string;
}

const BY_STATE: Record<AvatarState, LampView> = {
  idle: { caption: "STANDBY", light: "off", live: true },
  listening: { caption: "LISTENING", light: "low", live: true },
  thinking: { caption: "THINKING", light: "pulse", live: true },
  speaking: { caption: "ON AIR", light: "full", live: true },
  interrupted: { caption: "FLOOR IS YOURS", light: "low", live: true },
  error: { caption: "OFF AIR", light: "off", live: false },
};

export function lampView(inputs: LampInputs): LampView {
  if (inputs.connection === "disconnected") {
    return { caption: "STANDBY", light: "off", live: false };
  }
  if (inputs.connection === "connecting") {
    return { caption: "CONNECTING", light: "off", live: false };
  }
  // The single-slot brain is mid-interview with someone else: the studio is
  // occupied regardless of what our local machine thinks.
  if (inputs.brainStatus === "busy" && inputs.avatarState !== "error") {
    return { caption: "IN SESSION", light: "low", live: true };
  }
  return BY_STATE[inputs.avatarState];
}
