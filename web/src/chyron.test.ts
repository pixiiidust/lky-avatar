import { describe, expect, it } from "vitest";
import { chyronView, type ChyronInputs } from "./chyron.ts";

const inputs = (over: Partial<ChyronInputs>): ChyronInputs => ({
  compact: false,
  engaged: false,
  expanded: false,
  ...over,
});

describe("chyronView", () => {
  it("keeps the full notice on desktop, whatever the session has done", () => {
    expect(chyronView(inputs({}))).toEqual({
      mode: "full",
      toggle: false,
      expanded: true,
    });
    expect(chyronView(inputs({ engaged: true }))).toEqual({
      mode: "full",
      toggle: false,
      expanded: true,
    });
    expect(chyronView(inputs({ engaged: true, expanded: true })).mode).toBe("full");
  });

  it("greets a small viewport with the full notice until the visitor engages", () => {
    expect(chyronView(inputs({ compact: true }))).toEqual({
      mode: "full",
      toggle: false,
      expanded: true,
    });
  });

  it("folds to the pill once the visitor engages on a small viewport", () => {
    expect(chyronView(inputs({ compact: true, engaged: true }))).toEqual({
      mode: "pill",
      toggle: true,
      expanded: false,
    });
  });

  it("re-expands on demand, and folds again", () => {
    const open = chyronView(inputs({ compact: true, engaged: true, expanded: true }));
    expect(open).toEqual({ mode: "full", toggle: true, expanded: true });
    // The visitor folds it back: same rule, expanded withdrawn.
    expect(
      chyronView(inputs({ compact: true, engaged: true, expanded: false })).mode,
    ).toBe("pill");
  });

  it("returns to the full notice when the viewport grows past the breakpoint", () => {
    expect(
      chyronView(inputs({ compact: false, engaged: true, expanded: false })).mode,
    ).toBe("full");
  });

  it("never hides the disclosure entirely", () => {
    for (const compact of [false, true]) {
      for (const engaged of [false, true]) {
        for (const expanded of [false, true]) {
          const view = chyronView({ compact, engaged, expanded });
          expect(["full", "pill"]).toContain(view.mode);
        }
      }
    }
  });
});
