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

  return (
    <>
      <button
        ref={btnRef}
        type="button"
        id={id}
        aria-haspopup="listbox"
        aria-expanded={open}
        disabled={disabled}
        onClick={toggle}
        className={`flex cursor-pointer items-center justify-between gap-2 text-left transition-colors hover:border-v-accent focus:border-v-accent focus:outline-none disabled:cursor-not-allowed disabled:opacity-50 ${sizeClasses} ${className}`}
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
      {open && coords
        ? createPortal(
            <div
              ref={menuRef}
              role="listbox"
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
                  <button
                    key={o.value}
                    type="button"
                    role="option"
                    aria-selected={o.value === activeValue}
                    disabled={o.disabled}
                    onClick={() => selectValue(o.value)}
                    className={`flex w-full cursor-pointer items-center justify-between gap-2 px-3.5 py-2.5 text-left text-[14px] transition-colors hover:bg-v-soft disabled:cursor-not-allowed disabled:opacity-40 ${
                      o.value === activeValue ? "bg-v-soft font-medium text-v-fg" : "text-v-fg"
                    }`}
                  >
                    <span className="min-w-0 truncate">{o.label}</span>
                    {o.value === activeValue ? (
                      <Check className="size-3.5 shrink-0 text-v-accent" strokeWidth={2} />
                    ) : null}
                  </button>
                ))
              )}
            </div>,
            document.body,
          )
        : null}
    </>
  );
}
