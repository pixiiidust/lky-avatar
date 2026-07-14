/**
 * Session export (issue #40) — serializes the transcript model into the two
 * downloadable artifacts:
 *
 *  1. a JSONL eval trace: one `{"type":"session",…}` header line carrying
 *     the generating configuration, then one `{"type":"turn",…}` line per
 *     FINALIZED turn — the machine format the docs/eval-process.md LLM-judge
 *     flow consumes and diffs across configuration changes;
 *  2. a Markdown "transcript of record": a printed document with a title
 *     block (date + the locked disclosure wording), speaker-labelled turns,
 *     written notes marked as such, and interruptions recorded
 *     Hansard-style as `[Interruption.]`.
 *
 * Pure module: no DOM imports, unit-tested in export.test.ts. Everything
 * environmental (clock, build identity, disclosure wording) is passed in.
 *
 * ## Why several header fields are always null
 *
 * The JSONL header must state the configuration that generated the session,
 * but this client only fills fields it can TRUTHFULLY know. The voice agent
 * publishes exactly two participant attributes to the room — `lk.agent.state`
 * (listening/thinking/speaking) and `lky.brain` (ok|busy|error) — and neither
 * carries serving configuration. `prompt_variant`, `sim_date`, `model_alias`,
 * `tts_provider`, `tts_ref`, and `tts_speed` all live in the agent's
 * server-side environment (services/voice_agent), so the client sets them to
 * null rather than inventing values. To recover them for an eval, correlate
 * the trace's timestamps with the agent's session log (its `LATENCY` /
 * `INTERRUPT` lines share the same wall clock) or with the deployment's
 * recorded configuration. `app_version` / `git_sha` describe the WEB CLIENT
 * build (injected by vite at build time) and may themselves be null when the
 * build environment had no git available.
 *
 * Timestamps are ISO-8601 UTC with millisecond precision throughout.
 * `interrupted` means: the turn's playback was audibly cut short by a
 * barge-in, as observed by this client (see TranscriptStore.markInterruption).
 */

import type { Segment } from "./transcript.ts";

/** Where the record came from: a live LiveKit session or the keyless demo
 * harness (`?avatarDemo=1`). A demo trace must never be judged as live. */
export type ExportSource = "live" | "demo";

/** What the client truthfully knows about the session's configuration. */
export interface SessionInfo {
  /** epoch ms when the session began (connect success / demo start); null
   * if the record was exported without a session ever starting. */
  startedAt: number | null;
  source: ExportSource;
  /** web-client build identity (vite `define`); null when unknown */
  appVersion: string | null;
  gitSha: string | null;
  /** The locked disclosure wording, exactly as shown on the page. */
  disclosure: string;
}

export interface ExportInputs {
  session: SessionInfo;
  /** The record, in order (TranscriptStore.list()). Interim segments are
   * skipped: the export contains finalized turns only. */
  segments: Segment[];
  /** epoch ms of the export action itself */
  exportedAt: number;
}

const iso = (ms: number): string => new Date(ms).toISOString();

/** Finalized turns, in record order. */
function finalizedTurns(segments: Segment[]): Segment[] {
  return segments.filter((seg) => seg.final).sort((a, b) => a.order - b.order);
}

/** Roles are fixed vocabulary: the visitor asks, lky answers. */
function roleOf(seg: Segment): "visitor" | "lky" {
  return seg.speaker === "you" ? "visitor" : "lky";
}

// --- JSONL eval trace --------------------------------------------------------

export function toJsonl(inputs: ExportInputs): string {
  const { session, exportedAt } = inputs;
  const header = {
    type: "session",
    started_at: session.startedAt === null ? null : iso(session.startedAt),
    exported_at: iso(exportedAt),
    source: session.source,
    app_version: session.appVersion,
    git_sha: session.gitSha,
    // Server-side configuration the client cannot truthfully know — always
    // null here; see the module docstring for how to recover them.
    prompt_variant: null,
    sim_date: null,
    model_alias: null,
    tts_provider: null,
    tts_ref: null,
    tts_speed: null,
  };
  const lines = [JSON.stringify(header)];
  finalizedTurns(inputs.segments).forEach((seg, i) => {
    lines.push(
      JSON.stringify({
        type: "turn",
        turn: i + 1,
        role: roleOf(seg),
        mode: seg.kind,
        text: seg.text,
        started_at: iso(seg.startedAt),
        ended_at: seg.endedAt === null ? null : iso(seg.endedAt),
        interrupted: seg.interrupted,
      }),
    );
  });
  return lines.join("\n") + "\n";
}

// --- Markdown transcript of record -------------------------------------------

const MONTHS = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

/** "14 July 2026, 09:31 UTC" — unambiguous, deterministic (no locale). */
function dateline(ms: number): string {
  const d = new Date(ms);
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mm = String(d.getUTCMinutes()).padStart(2, "0");
  return (
    `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}, ` +
    `${hh}:${mm} UTC`
  );
}

function attribution(seg: Segment): string {
  const name = roleOf(seg) === "visitor" ? "YOU" : "LEE";
  return seg.kind === "written" ? `**${name}** *(written note)*:` : `**${name}:**`;
}

export function toMarkdown(inputs: ExportInputs): string {
  const { session, exportedAt } = inputs;
  const turns = finalizedTurns(inputs.segments);
  const out: string[] = [
    "# Lee Kuan Yew, in conversation",
    "",
    `**Transcript of record — ${dateline(session.startedAt ?? exportedAt)}**`,
    "",
    `> ${session.disclosure}`,
    "",
    "---",
    "",
  ];
  if (turns.length === 0) {
    out.push("*No turns were recorded.*", "");
  }
  for (const seg of turns) {
    const cut = seg.interrupted ? " *[Interruption.]*" : "";
    out.push(`${attribution(seg)} ${seg.text}${cut}`, "");
  }
  return out.join("\n");
}

// --- Filenames ----------------------------------------------------------------

/** Six base-36 characters; `random` injectable for tests. */
export function newShortId(random: () => number = Math.random): string {
  let id = "";
  while (id.length < 6) id += Math.floor(random() * 36).toString(36);
  return id;
}

/** `lky-session-<ISO date>-<shortid>.{jsonl,md}` */
export function exportFilenames(
  exportedAt: number,
  shortId: string,
): { jsonl: string; md: string } {
  const date = iso(exportedAt).slice(0, 10);
  const stem = `lky-session-${date}-${shortId}`;
  return { jsonl: `${stem}.jsonl`, md: `${stem}.md` };
}
