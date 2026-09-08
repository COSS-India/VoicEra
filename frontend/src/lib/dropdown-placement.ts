export type DropdownMenuCoords = {
  left: number;
  width: number;
  maxHeight: number;
  top?: number;
  bottom?: number;
};

const MIN_MENU_HEIGHT = 120;

/** Fixed-position dropdown placement — flips above the trigger when the menu
 * would not fit below and there is more room above, or when the trigger sits
 * in the lower half of the viewport with more space above than below. */
export function dropdownMenuCoords(
  rect: DOMRect,
  desiredHeight: number,
  margin = 4,
): DropdownMenuCoords {
  const spaceBelow = window.innerHeight - rect.bottom - margin;
  const spaceAbove = rect.top - margin;
  const crampedBelow = spaceBelow < desiredHeight;
  const moreRoomAbove = spaceAbove > spaceBelow;
  const lowerViewport = rect.top > window.innerHeight * 0.45;
  const placeAbove = (crampedBelow && moreRoomAbove) || (lowerViewport && moreRoomAbove);
  const maxHeight = Math.max(MIN_MENU_HEIGHT, Math.min(desiredHeight, placeAbove ? spaceAbove : spaceBelow));
  return {
    left: rect.left,
    width: rect.width,
    maxHeight,
    ...(placeAbove
      ? { bottom: window.innerHeight - rect.top + margin }
      : { top: rect.bottom + margin }),
  };
}
