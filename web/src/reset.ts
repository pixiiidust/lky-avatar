/**
 * End-the-interview / start-afresh flow (issue #13).
 *
 * The visible reset control must (1) disconnect, (2) OFFER the record
 * export (issue #40) before anything is cleared, then (3) land the studio
 * back at its pre-connect state with the record wiped. Three states:
 *
 *   standby — pre-connect; the set is cold, the record is (or has just
 *             been) cleared.
 *   live    — an interview is running; the primary control ends it.
 *   wrap    — the interview has ended with words on the record; the wrap
 *             card offers the export and the "Start afresh" control clears.
 *
 * Pure module (no DOM, no LiveKit): a reducer plus a view mapping, tested
 * in reset.test.ts; main.ts owns the side effects (disconnect, clear).
 */

export type ResetState = "standby" | "live" | "wrap";

export type ResetEvent =
  /** A session connected successfully. */
  | { type: "connected" }
  /** The session ended — visitor's End click, remote disconnect, or a
   * failed connect attempt. */
  | { type: "ended"; recordHasEntries: boolean }
  /** The visitor chose to clear the record and return to pre-connect. */
  | { type: "start-afresh" }
  /** The visitor asked to begin a (new) interview. */
  | { type: "begin" };

export interface ResetTransition {
  state: ResetState;
  /** Effect for the caller: wipe the transcript + session identifiers. */
  clearRecord: boolean;
}

export function nextReset(state: ResetState, event: ResetEvent): ResetTransition {
  switch (event.type) {
    case "connected":
      return { state: "live", clearRecord: false };
    case "ended":
      if (state !== "live") {
        // A failed connect attempt or a duplicate disconnect: nothing was
        // on air, so there is nothing to wrap up.
        return { state, clearRecord: false };
      }
      return event.recordHasEntries
        ? { state: "wrap", clearRecord: false } // offer the export first
        : { state: "standby", clearRecord: true }; // nothing worth keeping
    case "start-afresh":
      return { state: "standby", clearRecord: true };
    case "begin":
      // Beginning anew dismisses the wrap offer; the record itself is
      // cleared only once the new session actually connects (a failed
      // connect must not cost the visitor their transcript).
      return { state: "standby", clearRecord: false };
  }
}

export interface ResetView {
  /** Label + action of the primary session control. */
  control: "begin" | "end";
  /** Whether the wrap card (export offer + "Start afresh") is visible. */
  offerExport: boolean;
}

export function resetView(state: ResetState): ResetView {
  switch (state) {
    case "standby":
      return { control: "begin", offerExport: false };
    case "live":
      return { control: "end", offerExport: false };
    case "wrap":
      return { control: "begin", offerExport: true };
  }
}
