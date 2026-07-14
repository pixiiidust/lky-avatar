import { describe, expect, it } from "vitest";
import { TranscriptStore } from "./transcript.ts";

describe("TranscriptStore", () => {
  it("accumulates deltas and replaces text when a segment restarts", () => {
    const store = new TranscriptStore();
    store.beginSegment("s1", "you");
    store.appendText("s1", "how ");
    store.appendText("s1", "do we");
    expect(store.list()[0]).toMatchObject({
      text: "how do we",
      final: false,
      kind: "spoken",
    });
    // New stream for the same id = interim update: text resets.
    store.beginSegment("s1", "you");
    store.appendText("s1", "how do we stay competitive?");
    store.markFinal("s1");
    expect(store.list()).toHaveLength(1);
    expect(store.list()[0]).toMatchObject({
      text: "how do we stay competitive?",
      final: true,
    });
  });

  it("adds typed notes as final written segments, in order", () => {
    const store = new TranscriptStore();
    store.beginSegment("s1", "lee");
    store.appendText("s1", "Go ahead.");
    const noteId = store.addNote("you", "What about housing?");
    const [first, second] = store.list();
    expect(first.id).toBe("s1");
    expect(second).toMatchObject({
      id: noteId,
      speaker: "you",
      text: "What about housing?",
      final: true,
      kind: "written",
    });
  });

  it("clear resets ordering and note ids", () => {
    const store = new TranscriptStore();
    store.addNote("you", "a");
    store.clear();
    const id = store.addNote("you", "b");
    expect(id).toBe("note-0");
    expect(store.list()[0].order).toBe(0);
  });

  it("timestamps segments with the injected clock: start on creation, end on final", () => {
    let t = 1000;
    const store = new TranscriptStore(() => t);
    store.beginSegment("s1", "you");
    t = 2000;
    store.beginSegment("s1", "you"); // interim restart must not move startedAt
    expect(store.list()[0]).toMatchObject({ startedAt: 1000, endedAt: null });
    t = 3000;
    store.markFinal("s1");
    t = 4000;
    store.markFinal("s1"); // idempotent: endedAt keeps the first finalization
    expect(store.list()[0]).toMatchObject({ startedAt: 1000, endedAt: 3000 });
    const noteId = store.addNote("you", "hi"); // notes are instantaneous
    const note = store.list().find((s) => s.id === noteId)!;
    expect(note).toMatchObject({ startedAt: 4000, endedAt: 4000 });
  });

  it("markInterruption flags the most recent segment from that speaker only", () => {
    const store = new TranscriptStore();
    store.beginSegment("s1", "lee");
    store.beginSegment("s2", "you");
    store.beginSegment("s3", "lee");
    store.markInterruption("lee");
    const [s1, s2, s3] = store.list();
    expect(s1.interrupted).toBe(false);
    expect(s2.interrupted).toBe(false);
    expect(s3.interrupted).toBe(true);
    // No segment from the speaker yet: a no-op, not a crash.
    new TranscriptStore().markInterruption("lee");
  });
});
