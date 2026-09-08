/** Where on the tour card the dashed arrow originates. */
export type WalkthroughArrowFrom = "logo" | "left" | "top" | "bottom-left";

/** Where on the spotlight the arrow lands. */
export type WalkthroughTargetAnchor =
  | "center"
  | "left-edge"
  | "top-center"
  | "bottom-center";

/** Preferred placement of the tour card relative to its target. */
export type WalkthroughCardPlacement =
  | "right-of-target"
  | "below-target"
  | "bottom-right"
  | "above-target";

/** One step of a guided tour: a page it belongs to, optional DOM target via
 * `data-tour="<target>"`, and copy for the overlay card. Steps without a
 * `target` render as a centered intro card with no spotlight. */
export interface WalkthroughStep {
  id: string;
  page: string;
  title: string;
  body: string;
  /** `data-tour` attribute on the spotlighted element; omit for intro steps. */
  target?: string;
  cardPlacement?: WalkthroughCardPlacement;
  arrowFrom?: WalkthroughArrowFrom;
  targetAnchor?: WalkthroughTargetAnchor;
  /** Curve strength; negative bows downward, positive upward. */
  arrowBow?: number;
  /** Full-screen dim with a centered card — no spotlight or arrow. */
  presentation?: "intro" | "spotlight";
}
