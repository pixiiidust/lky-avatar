/**
 * Ordered store of transcription segments (interim + final).
 *
 * LiveKit Agents publishes transcriptions as text streams on the
 * `lk.transcription` topic. Each update for a segment arrives as its own
 * stream identified by the `lk.segment_id` attribute; text chunks within one
 * stream are deltas to be concatenated, and a NEW stream for the same
 * segment id REPLACES the previous text (that is how interim STT results
 * are updated). `lk.transcription_final === "true"` marks the segment done.
 *
 * Typed questions ("pass a note", issue #33) enter the record locally via
 * {@link TranscriptStore.addNote}: the agent consumes `lk.chat` text input
 * without echoing it back on the transcription topic, so the client is the
 * one that sets the written question into the record.
 */

export type SegmentKind = "spoken" | "written";

export interface Segment {
  id: string;
  /** participant identity that spoke this segment */
  speaker: string;
  text: string;
  final: boolean;
  /** spoken transcription vs a typed note passed to the interviewer */
  kind: SegmentKind;
  /** insertion order, for stable rendering */
  order: number;
}

export class TranscriptStore {
  private segments = new Map<string, Segment>();
  private counter = 0;
  private noteCounter = 0;

  /** Called when a new stream starts for a segment: reset its text. */
  beginSegment(id: string, speaker: string): void {
    const existing = this.segments.get(id);
    if (existing) {
      existing.text = "";
    } else {
      this.segments.set(id, {
        id,
        speaker,
        text: "",
        final: false,
        kind: "spoken",
        order: this.counter++,
      });
    }
  }

  /** Append a text-chunk delta to a segment. */
  appendText(id: string, delta: string): void {
    const seg = this.segments.get(id);
    if (seg) seg.text += delta;
  }

  markFinal(id: string): void {
    const seg = this.segments.get(id);
    if (seg) seg.final = true;
  }

  /**
   * A typed note passed to the interviewer: enters the record already final,
   * marked `written`. Returns the generated segment id.
   */
  addNote(speaker: string, text: string): string {
    const id = `note-${this.noteCounter++}`;
    this.segments.set(id, {
      id,
      speaker,
      text,
      final: true,
      kind: "written",
      order: this.counter++,
    });
    return id;
  }

  clear(): void {
    this.segments.clear();
    this.counter = 0;
    this.noteCounter = 0;
  }

  list(): Segment[] {
    return [...this.segments.values()].sort((a, b) => a.order - b.order);
  }
}
