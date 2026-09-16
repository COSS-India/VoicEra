export interface DiffToken {
  type: "same" | "added" | "removed";
  text: string;
}

const tokenize = (s: string): string[] => s.match(/\S+|\s+/g) ?? [];

/** Minimal LCS-based word-level diff — fine for prompt-length text (no dependency needed). */
export function diffWords(a: string, b: string): DiffToken[] {
  const left = tokenize(a);
  const right = tokenize(b);
  const n = left.length;
  const m = right.length;

  const lcs: number[][] = Array.from({ length: n + 1 }, () => new Array<number>(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      lcs[i][j] = left[i] === right[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
    }
  }

  const tokens: DiffToken[] = [];
  const push = (type: DiffToken["type"], text: string) => {
    const last = tokens[tokens.length - 1];
    if (last && last.type === type) last.text += text;
    else tokens.push({ type, text });
  };

  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (left[i] === right[j]) {
      push("same", left[i]);
      i++;
      j++;
    } else if (lcs[i + 1][j] >= lcs[i][j + 1]) {
      push("removed", left[i]);
      i++;
    } else {
      push("added", right[j]);
      j++;
    }
  }
  while (i < n) push("removed", left[i++]);
  while (j < m) push("added", right[j++]);

  return tokens;
}
