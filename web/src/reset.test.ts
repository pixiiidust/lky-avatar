import { describe, expect, it } from "vitest";
import { nextReset, resetView, type ResetState } from "./reset.ts";

describe("nextReset", () => {
  it("connecting puts the studio on air", () => {
    expect(nextReset("standby", { type: "connected" })).toEqual({
      state: "live",
      clearRecord: false,
    });
  });

  it("ending with words on the record offers the export before clearing", () => {
    expect(nextReset("live", { type: "ended", recordHasEntries: true })).toEqual({
      state: "wrap",
      clearRecord: false,
    });
  });

  it("ending an empty session goes straight back to standby, cleared", () => {
    expect(nextReset("live", { type: "ended", recordHasEntries: false })).toEqual({
      state: "standby",
      clearRecord: true,
    });
  });

  it("start afresh clears the record and lands at the pre-connect state", () => {
    expect(nextReset("wrap", { type: "start-afresh" })).toEqual({
      state: "standby",
      clearRecord: true,
    });
  });

  it("a failed connect attempt never pops the wrap card or clears anything", () => {
    // connect() fails before "connected" is ever dispatched: state is still
    // standby (or wrap, if a previous record is being kept around).
    expect(nextReset("standby", { type: "ended", recordHasEntries: true })).toEqual({
      state: "standby",
      clearRecord: false,
    });
    expect(nextReset("wrap", { type: "ended", recordHasEntries: true })).toEqual({
      state: "wrap",
      clearRecord: false,
    });
  });

  it("beginning anew from the wrap dismisses the offer but keeps the record until connected", () => {
    // The record only clears once the new session connects — a failed
    // connect must not cost the visitor their transcript.
    expect(nextReset("wrap", { type: "begin" })).toEqual({
      state: "standby",
      clearRecord: false,
    });
  });

  it("a full end-to-end pass: connect, end, export offered, start afresh", () => {
    let state: ResetState = "standby";
    let cleared = 0;
    const dispatch = (event: Parameters<typeof nextReset>[1]): void => {
      const t = nextReset(state, event);
      state = t.state;
      if (t.clearRecord) cleared++;
    };
    dispatch({ type: "begin" });
    dispatch({ type: "connected" });
    expect(resetView(state).control).toBe("end");
    dispatch({ type: "ended", recordHasEntries: true });
    expect(resetView(state).offerExport).toBe(true);
    expect(cleared).toBe(0); // nothing cleared before the offer
    dispatch({ type: "start-afresh" });
    expect(state).toBe("standby");
    expect(cleared).toBe(1);
    expect(resetView(state)).toEqual({ control: "begin", offerExport: false });
  });
});

describe("resetView", () => {
  it("maps each state to its control + wrap-card visibility", () => {
    expect(resetView("standby")).toEqual({ control: "begin", offerExport: false });
    expect(resetView("live")).toEqual({ control: "end", offerExport: false });
    expect(resetView("wrap")).toEqual({ control: "begin", offerExport: true });
  });
});
