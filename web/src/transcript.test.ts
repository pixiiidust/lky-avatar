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
});
