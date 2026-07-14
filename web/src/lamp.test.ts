import { describe, expect, it } from "vitest";
import { lampView, type LampInputs } from "./lamp.ts";
import type { AvatarState } from "./avatar/stateMachine.ts";

const connected = (avatarState: AvatarState, brainStatus = "ok"): LampInputs => ({
  connection: "connected",
  avatarState,
  brainStatus,
});

describe("lampView", () => {
  it("gives every machine state a distinct caption (legible at a glance)", () => {
    const states: AvatarState[] = [
      "idle",
      "listening",
      "thinking",
      "speaking",
      "interrupted",
      "error",
    ];
    const captions = states.map((s) => lampView(connected(s)).caption);
    expect(new Set(captions).size).toBe(states.length);
  });

  it("speaks the broadcast vocabulary", () => {
    expect(lampView(connected("speaking"))).toEqual({
      caption: "ON AIR",
      light: "full",
      live: true,
    });
    expect(lampView(connected("interrupted"))).toEqual({
      caption: "FLOOR IS YOURS",
      light: "low",
      live: true,
    });
    expect(lampView(connected("error"))).toEqual({
      caption: "OFF AIR",
      light: "off",
      live: false,
    });
    expect(lampView(connected("thinking")).light).toBe("pulse");
  });

  it("shows the occupied studio while the brain is busy", () => {
    expect(lampView(connected("listening", "busy"))).toEqual({
      caption: "IN SESSION",
      light: "low",
      live: true,
    });
    // ...but an error outranks the busy notice.
    expect(lampView(connected("error", "busy")).caption).toBe("OFF AIR");
  });

  it("is cold while disconnected or connecting, whatever the machine says", () => {
    expect(
      lampView({ connection: "disconnected", avatarState: "speaking", brainStatus: "ok" }),
    ).toEqual({ caption: "STANDBY", light: "off", live: false });
    expect(
      lampView({ connection: "connecting", avatarState: "speaking", brainStatus: "ok" }),
    ).toEqual({ caption: "CONNECTING", light: "off", live: false });
  });
});
