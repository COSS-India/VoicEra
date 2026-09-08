"use client";

import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { createPortal } from "react-dom";
import { Search } from "lucide-react";
import type { PromptModule } from "@/lib/prompt-modules";

const VARIABLE_PATTERN = /\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}/g;
const IDENTIFIER_PATTERN = /^[a-zA-Z_][a-zA-Z0-9_]*$/;

/** Every `{{var}}` name referenced in `text`, in order of first appearance, deduped. */
export function extractVariableNames(text: string): string[] {
  const seen = new Set<string>();
  const names: string[] = [];
  for (const match of text.matchAll(VARIABLE_PATTERN)) {
    const name = match[1]!;
    if (!seen.has(name)) {
      seen.add(name);
      names.push(name);
    }
  }
  return names;
}

/** Applies `sanitize` to the plain-text parts of `text`, leaving any
 * `{{var}}` tokens untouched — so a filter like "no special characters" can
 * still allow the `{`/`}`/`_` that variable tokens are made of. */
function sanitizeAroundVariables(text: string, sanitize: (segment: string) => string): string {
  let result = "";
  let lastIndex = 0;
  for (const match of text.matchAll(VARIABLE_PATTERN)) {
    const index = match.index ?? 0;
    result += sanitize(text.slice(lastIndex, index));
    result += match[0];
    lastIndex = index + match[0].length;
  }
  result += sanitize(text.slice(lastIndex));
  return result;
}

/** Loose multi-word match — every word in the query must show up somewhere in
 * the module's searchable text. Not true semantic search (no embeddings
 * available client-side), but forgiving of word order and partial matches,
 * which covers most of what a "search by meaning" box needs in practice. */
function moduleMatchesQuery(m: PromptModule, query: string): boolean {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (words.length === 0) return true;
  const haystack = `${m.name} ${m.short} ${m.tag} ${m.category} ${m.why}`.toLowerCase();
  return words.every((w) => haystack.includes(w));
}

function renderTokens(root: HTMLElement, text: string) {
  root.innerHTML = "";
  let lastIndex = 0;
  for (const match of text.matchAll(VARIABLE_PATTERN)) {
    const index = match.index ?? 0;
    if (index > lastIndex) {
      root.appendChild(document.createTextNode(text.slice(lastIndex, index)));
    }
    const badge = document.createElement("span");
    badge.contentEditable = "false";
    badge.dataset.var = match[1];
    badge.className =
      "mx-0.5 inline-block rounded-v-sm border border-purple-500/20 bg-purple-500/10 px-1.5 py-0.5 font-mono text-[12.5px] font-medium text-purple-700 select-none";
    badge.textContent = match[0];
    root.appendChild(badge);
    lastIndex = index + match[0].length;
  }
  if (lastIndex < text.length) {
    root.appendChild(document.createTextNode(text.slice(lastIndex)));
  }
}

/** Caret position as a plain-text character offset — badge spans count as the
 * length of their literal "{{name}}" text, since that's also how `text` (the
 * value this editor reports via onChange) counts them. */
function getCaretOffset(root: HTMLElement): number | null {
  const sel = window.getSelection();
  if (!sel || sel.rangeCount === 0) return null;
  const range = sel.getRangeAt(0);
  if (!root.contains(range.startContainer)) return null;
  const pre = document.createRange();
  pre.selectNodeContents(root);
  pre.setEnd(range.startContainer, range.startOffset);
  return pre.toString().length;
}

function setCaretOffset(root: HTMLElement, offset: number) {
  const sel = window.getSelection();
  if (!sel) return;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let remaining = offset;
  let node: Text | null;
  // eslint-disable-next-line no-cond-assign
  while ((node = walker.nextNode() as Text | null)) {
    const len = node.textContent?.length ?? 0;
    if (remaining <= len) {
      const range = document.createRange();
      range.setStart(node, Math.max(0, remaining));
      range.collapse(true);
      sel.removeAllRanges();
      sel.addRange(range);
      return;
    }
    remaining -= len;
  }
  const range = document.createRange();
  range.selectNodeContents(root);
  range.collapse(false);
  sel.removeAllRanges();
  sel.addRange(range);
}

/** Bounding rect of the current collapsed caret, in viewport coordinates. */
function getCaretRect(root: HTMLElement): DOMRect {
  const sel = window.getSelection();
  if (sel && sel.rangeCount > 0) {
    const rect = sel.getRangeAt(0).getBoundingClientRect();
    if (rect.width || rect.height || rect.top || rect.left) return rect;
  }
  return root.getBoundingClientRect();
}

interface PickerState {
  mode: "variable" | "module";
  /** Character offset in the plain-text value where the trigger char sat. */
  insertAt: number;
  query: string;
  top: number;
  left: number;
}

function PickerShell({
  popupRef,
  inputRef,
  query,
  onQueryChange,
  onKeyDown,
  placeholder,
  top,
  left,
  children,
}: {
  popupRef: React.RefObject<HTMLDivElement | null>;
  inputRef: React.RefObject<HTMLInputElement | null>;
  query: string;
  onQueryChange: (query: string) => void;
  onKeyDown: (e: React.KeyboardEvent<HTMLInputElement>) => void;
  placeholder: string;
  top: number;
  left: number;
  children: React.ReactNode;
}) {
  return createPortal(
    <div
      ref={popupRef}
      style={{ position: "fixed", top, left }}
      className="z-[1000] w-80 overflow-hidden rounded-v-sm border border-v-line bg-white shadow-[0_8px_24px_rgba(11,11,12,0.12)]"
    >
      <div className="relative border-b border-v-line">
        <Search
          className="pointer-events-none absolute left-3 top-1/2 size-3.5 -translate-y-1/2 text-v-muted"
          strokeWidth={1.75}
        />
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => onQueryChange(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder={placeholder}
          className="w-full py-2 pl-8 pr-3 text-[13px] focus:outline-none"
        />
      </div>
      <div className="max-h-64 overflow-y-auto py-1">{children}</div>
    </div>,
    document.body,
  );
}

function useClosePickerOnOutsideClick(popupRef: React.RefObject<HTMLDivElement | null>, onClose: () => void) {
  useEffect(() => {
    function onDocMouseDown(e: MouseEvent) {
      if (!popupRef.current?.contains(e.target as Node)) onClose();
    }
    document.addEventListener("mousedown", onDocMouseDown);
    return () => document.removeEventListener("mousedown", onDocMouseDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}

function VariablePicker({
  state,
  variables,
  onQueryChange,
  onPick,
  onClose,
}: {
  state: PickerState;
  variables: string[];
  onQueryChange: (query: string) => void;
  onPick: (name: string) => void;
  onClose: () => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const popupRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);
  useClosePickerOnOutsideClick(popupRef, onClose);

  const q = state.query.trim().toLowerCase();
  const filtered = q ? variables.filter((v) => v.toLowerCase().includes(q)) : variables;
  const exactMatch = variables.some((v) => v.toLowerCase() === q);
  const canCreate = state.query.trim().length > 0 && !exactMatch && IDENTIFIER_PATTERN.test(state.query.trim());

  function confirm() {
    if (filtered.length === 1) {
      onPick(filtered[0]!);
    } else if (canCreate) {
      onPick(state.query.trim());
    }
  }

  return (
    <PickerShell
      popupRef={popupRef}
      inputRef={inputRef}
      query={state.query}
      onQueryChange={(q2) => onQueryChange(q2.replace(/[^a-zA-Z0-9_]/g, ""))}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.preventDefault();
          onClose();
        } else if (e.key === "Enter") {
          e.preventDefault();
          confirm();
        }
      }}
      placeholder="Search variables…"
      top={state.top}
      left={state.left}
    >
      {filtered.map((name) => (
        <button
          key={name}
          type="button"
          onMouseDown={(e) => e.preventDefault()}
          onClick={() => onPick(name)}
          className="flex w-full cursor-pointer items-center gap-2 px-3.5 py-2 text-left text-[13px] transition-colors hover:bg-v-soft"
        >
          <span className="rounded-v-sm border border-purple-500/20 bg-purple-500/10 px-1.5 py-0.5 font-mono text-[11.5px] font-medium text-purple-700">
            {`{{${name}}}`}
          </span>
        </button>
      ))}
      {canCreate ? (
        <button
          type="button"
          onMouseDown={(e) => e.preventDefault()}
          onClick={() => onPick(state.query.trim())}
          className="flex w-full cursor-pointer items-center gap-2 px-3.5 py-2 text-left text-[13px] text-v-muted transition-colors hover:bg-v-soft"
        >
          Create <span className="font-mono text-purple-700">{`{{${state.query.trim()}}}`}</span>
        </button>
      ) : null}
      {filtered.length === 0 && !canCreate ? (
        <div className="px-3.5 py-2.5 text-sm text-v-muted">
          {variables.length === 0 ? "No variables yet — type a name to create one." : "No matches."}
        </div>
      ) : null}
    </PickerShell>
  );
}

function ModulePicker({
  state,
  modules,
  onQueryChange,
  onPick,
  onClose,
}: {
  state: PickerState;
  modules: PromptModule[];
  onQueryChange: (query: string) => void;
  onPick: (m: PromptModule) => void;
  onClose: () => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const popupRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);
  useClosePickerOnOutsideClick(popupRef, onClose);

  const filtered = useMemo(
    () => modules.filter((m) => moduleMatchesQuery(m, state.query)),
    [modules, state.query],
  );

  return (
    <PickerShell
      popupRef={popupRef}
      inputRef={inputRef}
      query={state.query}
      onQueryChange={onQueryChange}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.preventDefault();
          onClose();
        } else if (e.key === "Enter") {
          e.preventDefault();
          if (filtered[0]) onPick(filtered[0]);
        }
      }}
      placeholder="Search prompt modules…"
      top={state.top}
      left={state.left}
    >
      {filtered.map((m) => (
        <button
          key={m.id}
          type="button"
          onMouseDown={(e) => e.preventDefault()}
          onClick={() => onPick(m)}
          className="flex w-full cursor-pointer flex-col gap-0.5 px-3.5 py-2.5 text-left transition-colors hover:bg-v-soft"
        >
          <span className="flex items-center gap-1.5">
            <span className="text-[13px] font-semibold text-v-fg">{m.name}</span>
            <span className="rounded-full bg-v-soft px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-[.08em] text-v-muted">
              {m.tag}
            </span>
          </span>
          <span className="line-clamp-1 text-[11.5px] font-light text-v-muted">{m.short}</span>
        </button>
      ))}
      {filtered.length === 0 ? (
        <div className="px-3.5 py-2.5 text-sm text-v-muted">No modules match &ldquo;{state.query}&rdquo;.</div>
      ) : null}
    </PickerShell>
  );
}

/**
 * A prompt textarea that renders `{{var}}` tokens as inline purple badges as
 * you type, matching the design's variable-highlighting. Typing a single "{"
 * opens a searchable picker of known variables (or lets you name a new one)
 * instead of typing the token by hand; typing "/" (when `promptModules` is
 * passed) opens a searchable picker of prompt modules to insert. The
 * plain-text value (badges included, as literal "{{var}}") is the single
 * source of truth — `onChange` always reports that string, same shape as a
 * plain textarea would.
 */
export function PromptEditor({
  value,
  onChange,
  variables,
  promptModules,
  placeholder,
  rows = 11,
  singleLine = false,
  sanitize,
}: {
  value: string;
  onChange: (value: string) => void;
  /** Known variable names to suggest in the "{" picker. */
  variables?: string[];
  /** When passed, typing "/" opens a searchable picker of these to insert. */
  promptModules?: PromptModule[];
  placeholder?: string;
  rows?: number;
  /** Blocks Enter from inserting a newline — for one-line fields like a greeting. */
  singleLine?: boolean;
  /** Applied to the plain-text parts of every edit (not to `{{var}}` tokens) —
   * e.g. stripping special characters from a spoken-aloud field. */
  sanitize?: (text: string) => string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  // null (not the initial `value`) so the mount effect always does the first render.
  const lastValue = useRef<string | null>(null);
  const composing = useRef(false);
  const [picker, setPicker] = useState<PickerState | null>(null);

  const knownVariables = useMemo(
    () => Array.from(new Set(variables ?? [])).sort((a, b) => a.localeCompare(b)),
    [variables],
  );

  // Re-render from `value` whenever it changes from outside this editor's own
  // typing (template pick, switching agents in edit mode, prompt-module insert).
  useEffect(() => {
    if (!ref.current || value === lastValue.current) return;
    const offset = getCaretOffset(ref.current);
    renderTokens(ref.current, value);
    lastValue.current = value;
    if (offset !== null) setCaretOffset(ref.current, offset);
  }, [value]);

  function openPicker(mode: PickerState["mode"], insertAt: number) {
    if (!ref.current) return;
    const rect = getCaretRect(ref.current);
    setPicker({ mode, insertAt, query: "", top: rect.bottom + 4, left: rect.left });
  }

  function closePicker() {
    if (ref.current && picker) {
      ref.current.focus();
      setCaretOffset(ref.current, picker.insertAt);
    }
    setPicker(null);
  }

  function insertAt(pos: number, insertion: string, caretAfter: number) {
    if (!ref.current) return;
    const current = ref.current.textContent ?? "";
    const next = current.slice(0, pos) + insertion + current.slice(pos);
    renderTokens(ref.current, next);
    lastValue.current = next;
    ref.current.focus();
    setCaretOffset(ref.current, caretAfter);
    setPicker(null);
    onChange(next);
  }

  function pickVariable(name: string) {
    if (!picker) return;
    const token = `{{${name}}}`;
    insertAt(picker.insertAt, token, picker.insertAt + token.length);
  }

  function pickModule(m: PromptModule) {
    if (!picker) return;
    insertAt(picker.insertAt, m.text, picker.insertAt + m.text.length);
  }

  // Browsers handle Enter in a contentEditable by inserting block elements
  // (<div>/<br>) whose boundaries don't reliably show up in `.textContent` as
  // "\n" — since renderTokens only ever builds text nodes, insert a literal
  // newline character ourselves instead of letting the browser do it.
  function handleKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    if (e.key !== "Enter" || composing.current) return;
    e.preventDefault();
    if (singleLine || !ref.current) return;
    const text = ref.current.textContent ?? "";
    const offset = getCaretOffset(ref.current) ?? text.length;
    const next = text.slice(0, offset) + "\n" + text.slice(offset);
    renderTokens(ref.current, next);
    lastValue.current = next;
    setCaretOffset(ref.current, offset + 1);
    onChange(next);
  }

  function handleInput() {
    if (!ref.current || composing.current) return;
    let text = ref.current.textContent ?? "";
    let offset = getCaretOffset(ref.current);

    // A lone "{" opens the variable picker; a lone "/" (when prompt modules
    // are configured) opens the module picker — either way, remove the
    // trigger character and let the picker build the insertion instead.
    const triggerChar = offset !== null && offset > 0 ? text[offset - 1] : null;
    const triggersVariable = triggerChar === "{";
    const triggersModule = triggerChar === "/" && promptModules !== undefined;
    if (offset !== null && (triggersVariable || triggersModule)) {
      const trimmed = text.slice(0, offset - 1) + text.slice(offset);
      renderTokens(ref.current, trimmed);
      lastValue.current = trimmed;
      setCaretOffset(ref.current, offset - 1);
      onChange(trimmed);
      openPicker(triggersVariable ? "variable" : "module", offset - 1);
      return;
    }

    if (sanitize) {
      // Re-derive the caret's position from how much of the text *before* it
      // survives sanitizing, since sanitizing can drop the very character
      // that was just typed.
      const prefixLen = offset !== null ? sanitizeAroundVariables(text.slice(0, offset), sanitize).length : null;
      text = sanitizeAroundVariables(text, sanitize);
      offset = prefixLen;
    }

    renderTokens(ref.current, text);
    lastValue.current = text;
    if (offset !== null) setCaretOffset(ref.current, offset);
    onChange(text);
  }

  return (
    <>
      <div
        ref={ref}
        contentEditable
        suppressContentEditableWarning
        onInput={handleInput}
        onKeyDown={handleKeyDown}
        onCompositionStart={() => {
          composing.current = true;
        }}
        onCompositionEnd={() => {
          composing.current = false;
          handleInput();
        }}
        data-placeholder={placeholder}
        style={{ minHeight: `${rows * 1.6}em` }}
        className="w-full box-border resize-y overflow-y-auto whitespace-pre-wrap break-words rounded-v-md border-t border-b border-l border-r border-v-line-strong bg-white px-4 py-3.5 text-sm leading-relaxed text-v-fg transition-colors focus:border-v-accent focus:outline-none empty:before:text-v-dim empty:before:content-[attr(data-placeholder)]"
      />
      {picker?.mode === "variable" ? (
        <VariablePicker
          state={picker}
          variables={knownVariables}
          onQueryChange={(query) => setPicker((p) => (p ? { ...p, query } : p))}
          onPick={pickVariable}
          onClose={closePicker}
        />
      ) : null}
      {picker?.mode === "module" ? (
        <ModulePicker
          state={picker}
          modules={promptModules ?? []}
          onQueryChange={(query) => setPicker((p) => (p ? { ...p, query } : p))}
          onPick={pickModule}
          onClose={closePicker}
        />
      ) : null}
    </>
  );
}
