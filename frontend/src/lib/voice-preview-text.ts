/** Text helpers for voice previews. The preview box shows the greeting as
 * written, `{{placeholders}}` included; only the server strips them before
 * synthesis so they're never spoken. `stripPlaceholders` mirrors the server's
 * `strip_placeholders` (apps/api/app/services/tts_preview_service.py) solely
 * so the character counter matches what the API measures against its limit. */

export const PREVIEW_MAX_CHARS = 300;

// [\p{L}\p{N}_] is Python's Unicode `\w`; JS `\w` is ASCII-only.
const PLACEHOLDER_RE = /\{\{\s*[\p{L}\p{N}_]+\s*\}\}/gu;
const SPACE_BEFORE_PUNCT_RE = /\s+([,.!?;:])/g;
const WHITESPACE_RE = /\s+/g;

export function stripPlaceholders(text: string): string {
  return text
    .replace(PLACEHOLDER_RE, "")
    .replace(SPACE_BEFORE_PUNCT_RE, "$1")
    .replace(WHITESPACE_RE, " ")
    .trim();
}
