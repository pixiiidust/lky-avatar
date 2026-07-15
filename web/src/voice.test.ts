import { describe, expect, it } from "vitest";
import { voiceNoticeFor } from "./voice.ts";

describe("voiceNoticeFor", () => {
  it("slates the voice outage in the studio's vocabulary", () => {
    const notice = voiceNoticeFor("error");
    expect(notice).not.toBeNull();
    expect(notice!.caption).toBe("Sound is down");
    // The message must reassure that the interview continues on the record.
    expect(notice!.message).toMatch(/replies continue/i);
    expect(notice!.message).toMatch(/on the record/i);
  });

  it("clears on recovery", () => {
    expect(voiceNoticeFor("ok")).toBeNull();
  });

  it("fails open on unknown or empty statuses", () => {
    expect(voiceNoticeFor("")).toBeNull();
    expect(voiceNoticeFor("degraded")).toBeNull();
    expect(voiceNoticeFor("ERROR")).toBeNull(); // the contract is lowercase
  });
});
