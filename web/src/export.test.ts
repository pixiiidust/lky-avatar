import { describe, expect, it } from "vitest";
import {
  exportFilenames,
  newShortId,
  toJsonl,
  toMarkdown,
  type ExportInputs,
  type SessionInfo,
} from "./export.ts";
import { TranscriptStore } from "./transcript.ts";

const DISCLOSURE =
  "Fictional AI simulation of Lee Kuan Yew in the present day, as an " +
  "experiment. Generated responses are not authentic quotations. Not " +
  "affiliated with or endorsed by his family or the Government of Singapore.";

const T0 = Date.UTC(2026, 6, 14, 9, 30, 0, 0); // 2026-07-14T09:30:00.000Z

/** A three-turn session: spoken question, interrupted answer, written note. */
function sampleInputs(overrides: Partial<SessionInfo> = {}): ExportInputs {
  let tick = 0;
  const store = new TranscriptStore(() => T0 + 1000 * tick++);
  store.beginSegment("s1", "you"); // t=0
  store.appendText("s1", "What about housing?");
  store.markFinal("s1"); // t=1
  store.beginSegment("s2", "lee"); // t=2
  store.appendText("s2", "Housing is not charity, it is a stake —");
  store.markFinal("s2"); // t=3
  store.markInterruption("lee");
  store.addNote("you", "And for renters?"); // t=4
  store.beginSegment("s3", "lee"); // t=5 — left interim: must be excluded
  store.appendText("s3", "Renters…");
  return {
    session: {
      startedAt: T0 - 5000,
      source: "live",
      appVersion: "0.1.0",
      gitSha: "abc1234",
      disclosure: DISCLOSURE,
      ...overrides,
    },
    segments: store.list(),
    exportedAt: T0 + 60_000,
  };
}

describe("toJsonl", () => {
  it("writes the session header as the first line, config fields it cannot know as null", () => {
    const lines = toJsonl(sampleInputs()).trimEnd().split("\n");
    const header = JSON.parse(lines[0]);
    expect(header).toEqual({
      type: "session",
      started_at: "2026-07-14T09:29:55.000Z",
      exported_at: "2026-07-14T09:31:00.000Z",
      source: "live",
      app_version: "0.1.0",
      git_sha: "abc1234",
      // Server-side config: never invented (see export.ts docstring).
      prompt_variant: null,
      sim_date: null,
      model_alias: null,
      tts_provider: null,
      tts_ref: null,
      tts_speed: null,
    });
  });

  it("emits one line per FINALIZED turn with role, mode, ms timestamps, interrupted", () => {
    const lines = toJsonl(sampleInputs()).trimEnd().split("\n");
    const turns = lines.slice(1).map((l) => JSON.parse(l));
    expect(turns).toEqual([
      {
        type: "turn",
        turn: 1,
        role: "visitor",
        mode: "spoken",
        text: "What about housing?",
        started_at: "2026-07-14T09:30:00.000Z",
        ended_at: "2026-07-14T09:30:01.000Z",
        interrupted: false,
      },
      {
        type: "turn",
        turn: 2,
        role: "lky",
        mode: "spoken",
        text: "Housing is not charity, it is a stake —",
        started_at: "2026-07-14T09:30:02.000Z",
        ended_at: "2026-07-14T09:30:03.000Z",
        interrupted: true,
      },
      {
        type: "turn",
        turn: 3,
        role: "visitor",
        mode: "written",
        text: "And for renters?",
        started_at: "2026-07-14T09:30:04.000Z",
        ended_at: "2026-07-14T09:30:04.000Z",
        interrupted: false,
      },
    ]);
    // The interim s3 segment must not appear.
    expect(turns).toHaveLength(3);
  });

  it("survives a session that never started (header still truthful) and an empty record", () => {
    const inputs = sampleInputs({ startedAt: null, appVersion: null, gitSha: null });
    inputs.segments = [];
    const lines = toJsonl(inputs).trimEnd().split("\n");
    expect(lines).toHaveLength(1);
    const header = JSON.parse(lines[0]);
    expect(header.started_at).toBeNull();
    expect(header.app_version).toBeNull();
    expect(header.git_sha).toBeNull();
  });

  it("ends with a newline and every line is valid JSON", () => {
    const text = toJsonl(sampleInputs());
    expect(text.endsWith("\n")).toBe(true);
    for (const line of text.trimEnd().split("\n")) {
      expect(() => JSON.parse(line)).not.toThrow();
    }
  });
});

describe("toMarkdown", () => {
  it("opens with the title block: date of record + the locked disclosure", () => {
    const md = toMarkdown(sampleInputs());
    expect(md).toContain("# Lee Kuan Yew, in conversation");
    expect(md).toContain("**Transcript of record — 14 July 2026, 09:29 UTC**");
    expect(md).toContain(`> ${DISCLOSURE}`);
  });

  it("labels speakers, marks written notes, records interruptions Hansard-style", () => {
    const md = toMarkdown(sampleInputs());
    expect(md).toContain("**YOU:** What about housing?");
    expect(md).toContain(
      "**LEE:** Housing is not charity, it is a stake — *[Interruption.]*",
    );
    expect(md).toContain("**YOU** *(written note)*: And for renters?");
    // Interim speech has not settled into the record.
    expect(md).not.toContain("Renters…");
  });

  it("dates from the export moment when the session never started, and says so when empty", () => {
    const inputs = sampleInputs({ startedAt: null });
    inputs.segments = [];
    const md = toMarkdown(inputs);
    expect(md).toContain("**Transcript of record — 14 July 2026, 09:31 UTC**");
    expect(md).toContain("*No turns were recorded.*");
  });
});

describe("filenames", () => {
  it("suggests lky-session-<ISO date>-<shortid>.{jsonl,md}", () => {
    expect(exportFilenames(T0, "a1b2c3")).toEqual({
      jsonl: "lky-session-2026-07-14-a1b2c3.jsonl",
      md: "lky-session-2026-07-14-a1b2c3.md",
    });
  });

  it("newShortId yields six base-36 characters", () => {
    expect(newShortId(() => 0.999999)).toMatch(/^[0-9a-z]{6}$/);
    expect(newShortId(() => 0)).toBe("000000");
  });
});
