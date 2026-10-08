"use client";

import {
  isValidElement,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type OptionHTMLAttributes,
  type ReactNode,
  type RefObject,
  type SelectHTMLAttributes,
} from "react";
import { createPortal } from "react-dom";
import { Check, ChevronDown } from "lucide-react";
import { dropdownMenuCoords, type DropdownMenuCoords } from "@/lib/dropdown-placement";

interface SelectOption {
  value: string;
  label: ReactNode;
  disabled?: boolean;
}

/** Reads plain <option> (and <optgroup>-wrapped <option>) children, same shape
 * every existing native-select call site already passes — so swapping the
 * import is the only change most callers need. */
function optionsFromChildren(children: ReactNode): SelectOption[] {
  const options: SelectOption[] = [];
  function walk(node: ReactNode) {
    if (Array.isArray(node)) {
      node.forEach(walk);
      return;
    }
    if (!isValidElement(node)) return;
    if (node.type === "option") {
      const props = node.props as OptionHTMLAttributes<HTMLOptionElement>;
      options.push({
        value: String(props.value ?? ""),
        label: props.children,
        disabled: props.disabled,
      });
      return;
    }
    const childProps = node.props as { children?: ReactNode };
    if (childProps?.children) walk(childProps.children);
  }
  walk(children);
  return options;
}

interface SelectProps extends Omit<SelectHTMLAttributes<HTMLSelectElement>, "size" | "multiple"> {
  /** "md" (default) matches the app's pill form-field size; "sm" is the compact
   * toolbar-pill size used for filters like sort/agent pickers. */
  size?: "sm" | "md";
  /** Optional control drawn before an option's label, in the trigger and in each
   * row (e.g. a voice's play button). Rendered beside, not inside, the option
   * buttons, so it can be its own button; return null to leave a value bare. */
  renderLeading?: (value: string) => ReactNode;
}

const LEADING_PAD = "pl-12";

/** ARIA roles for the menu. A listbox may only contain options, so a menu whose
 * rows carry their own buttons (renderLeading) becomes a grid: each row is a
 * `row`, and the leading control and the option are its `gridcell`s. */
const MENU_ROLES = {
  listbox: { menu: "listbox", row: undefined, cell: "option" },
  grid: { menu: "grid", row: "row", cell: "gridcell" },
} as const;
type MenuRoles = (typeof MENU_ROLES)[keyof typeof MENU_ROLES];

/** Positions `leading` over the left padding of the button it wraps. With no
 * leading control and no row role it renders the button alone, unchanged. */
function LeadingSlot({
  leading,
  rowRole,
  children,
}: {
  leading: ReactNode;
  rowRole?: "row";
  children: ReactNode;
}) {
  if (!leading && !rowRole) return children;
  return (
    <div role={rowRole} className="relative w-full">
      <span role={rowRole && "gridcell"} className="absolute left-3 top-1/2 z-10 -translate-y-1/2">
        {leading}
      </span>
      {children}
    </div>
  );
}

function SelectOptionRow({
  option,
  selected,
  leading,
  roles,
  onSelect,
}: {
  option: SelectOption;
  selected: boolean;
  leading: ReactNode;
  roles: MenuRoles;
  onSelect: (value: string) => void;
}) {
  return (
    <LeadingSlot leading={leading} rowRole={roles.row}>
      <button
        type="button"
        role={roles.cell}
        aria-selected={selected}
        disabled={option.disabled}
        onClick={() => onSelect(option.value)}
        className={`flex w-full cursor-pointer items-center justify-between gap-2 px-3.5 py-2.5 text-left text-[14px] transition-colors hover:bg-v-soft disabled:cursor-not-allowed disabled:opacity-40 ${
          selected ? "bg-v-soft font-medium text-v-fg" : "text-v-fg"
        } ${leading ? LEADING_PAD : ""}`}
      >
        <span className="min-w-0 truncate">{option.label}</span>
        {selected ? <Check className="size-3.5 shrink-0 text-v-accent" strokeWidth={2} /> : null}
      </button>
    </LeadingSlot>
  );
}

/** The portalled option list, positioned by `coords` next to the trigger. */
function SelectMenu({
  menuRef,
  coords,
  options,
  activeValue,
  renderLeading,
  onSelect,
}: {
  menuRef: RefObject<HTMLDivElement | null>;
  coords: DropdownMenuCoords;
  options: SelectOption[];
  activeValue: string;
  renderLeading?: (value: string) => ReactNode;
  onSelect: (value: string) => void;
}) {
  const roles = MENU_ROLES[renderLeading ? "grid" : "listbox"];
  return (
    <div
      ref={menuRef}
      role={roles.menu}
      style={{
        position: "fixed",
        left: coords.left,
        minWidth: coords.width,
        maxHeight: coords.maxHeight,
        ...(coords.top !== undefined ? { top: coords.top } : { bottom: coords.bottom }),
      }}
      className="z-[1000] overflow-y-auto rounded-v-sm border border-v-line bg-white py-1 shadow-[0_8px_24px_rgba(11,11,12,0.12)]"
    >
      {options.length === 0 ? (
        <div className="px-3.5 py-2.5 text-sm text-v-muted">No options</div>
      ) : (
        options.map((o) => (
          <SelectOptionRow
            key={o.value}
            option={o}
            selected={o.value === activeValue}
            leading={renderLeading?.(o.value)}
            roles={roles}
            onSelect={onSelect}
          />
        ))
      )}
    </div>
  );
}

/**
 * Drop-in replacement for a native <select> — same value/onChange/<option>
 * children API (onChange still receives a `{ target: { value } }`-shaped
 * event), but renders a portal-based custom dropdown so it's never clipped by
 * an ancestor's overflow:hidden and matches the rest of the design system.
 * Doesn't support `multiple` — nothing in the app uses it; LanguageSearchSelect
 * already covers multi-select language picking with its own UI.
 */
export function Select({
  value,
  defaultValue,
  onChange,
  children,
  disabled,
  className = "",
  size = "md",
  name,
  id,
  renderLeading,
  ...rest
}: SelectProps) {
  const options = useMemo(() => optionsFromChildren(children), [children]);
  const [open, setOpen] = useState(false);
  const [coords, setCoords] = useState<DropdownMenuCoords | null>(null);
  const btnRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onDocMouseDown(e: MouseEvent) {
      if (menuRef.current?.contains(e.target as Node) || btnRef.current?.contains(e.target as Node)) return;
      setOpen(false);
    }
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    function close() {
      setOpen(false);
    }
    document.addEventListener("mousedown", onDocMouseDown);
    document.addEventListener("keydown", onKeyDown);
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    return () => {
      document.removeEventListener("mousedown", onDocMouseDown);
      document.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("resize", close);
    };
  }, [open]);

  // Fixed-position menus don't get pushed back on-screen by the browser like a
  // native <select> would — without this, a trigger in the lower half of a
  // long page opens a menu that runs past the viewport edge with no way to
  // reach the bottom options. Flip above the trigger, and clamp height to
  // whichever side actually has room, so the full list is always reachable.
  function toggle() {
    if (disabled) return;
    if (!open && btnRef.current) {
      setCoords(dropdownMenuCoords(btnRef.current.getBoundingClientRect(), 288, 6));
    }
    setOpen((v) => !v);
  }

  function selectValue(next: string) {
    setOpen(false);
    if (!onChange) return;
    // Synthetic — enough for every call site's `(e) => setX(e.target.value)`
    // without threading a parallel non-event API through the whole app.
    const event = {
      target: { value: next, name },
      currentTarget: { value: next, name },
    } as unknown as ChangeEvent<HTMLSelectElement>;
    onChange(event);
  }

  const activeValue = value ?? defaultValue ?? "";
  const selected = options.find((o) => o.value === activeValue);

  const sizeClasses =
    size === "sm"
      ? "rounded-v-lg border border-v-line bg-white px-3.5 py-2.5 text-xs font-medium"
      : "w-full box-border rounded-v-lg border border-v-line-strong bg-white text-v-fg text-[13.5px] px-3.5 py-[11px]";

  const triggerLeading = renderLeading?.(String(activeValue));

  return (
    <>
      <LeadingSlot leading={triggerLeading}>
        <button
          ref={btnRef}
          type="button"
          id={id}
          aria-haspopup={renderLeading ? "grid" : "listbox"}
          aria-expanded={open}
          disabled={disabled}
          onClick={toggle}
          className={`flex cursor-pointer items-center justify-between gap-2 text-left transition-colors hover:border-v-accent focus:border-v-accent focus:outline-none disabled:cursor-not-allowed disabled:opacity-50 ${sizeClasses} ${triggerLeading ? LEADING_PAD : ""} ${className}`}
          {...(rest as Record<string, unknown>)}
        >
          <span className={`min-w-0 truncate ${selected ? "" : "text-v-muted"}`}>
            {selected?.label ?? "Select…"}
          </span>
          <ChevronDown
            className={`size-[13px] shrink-0 text-v-faint transition-transform ${open ? "rotate-180" : ""}`}
            strokeWidth={2}
          />
        </button>
      </LeadingSlot>
      {open && coords
        ? createPortal(
            <SelectMenu
              menuRef={menuRef}
              coords={coords}
              options={options}
              activeValue={String(activeValue)}
              renderLeading={renderLeading}
              onSelect={selectValue}
            />,
            document.body,
          )
        : null}
    </>
  );
}
