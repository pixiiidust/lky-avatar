/**
 * Disclosure chyron — fold/expand logic (issue #33, operator revision).
 *
 * The locked disclosure wording runs as a broadcast chyron across the bottom
 * edge. On a small viewport it is a five-line slab, so once the visitor has
 * engaged (first connect, or a first turn on the record) the chyron folds to
 * a one-line slate pill — the oxblood tab and FICTIONAL SIMULATION — with an
 * affordance that restores the full notice. It is a fold, never a dismissal:
 * `mode` is only ever "full" or "pill" (the disclosure must stay persistent
 * and unmissable), and the locked wording returns byte-for-byte on expand.
 * Desktop never folds.
 *
 * Pure module: no DOM imports, unit-tested in chyron.test.ts.
 */

export type ChyronMode = "full" | "pill";

export interface ChyronView {
  /** How the chyron renders. There is deliberately no "hidden". */
  mode: ChyronMode;
  /** Whether the fold toggle participates (compact viewport + engaged). */
  toggle: boolean;
  /** aria-expanded for the toggle while it participates. */
  expanded: boolean;
}

export interface ChyronInputs {
  /** Small-viewport layout active (the same breakpoint that stacks the set). */
  compact: boolean;
  /** The visitor has engaged: connected once, or a first turn is on the record. */
  engaged: boolean;
  /** The visitor explicitly re-expanded the folded notice. */
  expanded: boolean;
}

export function chyronView(inputs: ChyronInputs): ChyronView {
  const toggle = inputs.compact && inputs.engaged;
  const mode: ChyronMode = toggle && !inputs.expanded ? "pill" : "full";
  return { mode, toggle, expanded: mode === "full" };
}
