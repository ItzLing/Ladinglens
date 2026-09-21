// Word-level difference between two values, for highlighting what changed.
// Two words count as equal under the same normalisation compare.py uses:
// case, and the separators , ; | do not matter, nor do thousands commas.

export function normalizeToken(token) {
  return token.toUpperCase().replace(/(?<=\d),(?=\d{3})/g, "").replace(/[,;|]/g, "");
}

const isSpace = (t) => /^\s+$/.test(t);

function words(text) {
  return String(text ?? "")
    .split(/(\s+)/)
    .filter((t) => t !== "")
    .map((text) => ({ text, norm: isSpace(text) ? null : normalizeToken(text) }));
}

function matchedWords(a, b) {
  const wa = a.filter((t) => t.norm), wb = b.filter((t) => t.norm);
  const table = Array.from({ length: wa.length + 1 }, () => new Array(wb.length + 1).fill(0));
  for (let i = wa.length - 1; i >= 0; i--) {
    for (let j = wb.length - 1; j >= 0; j--) {
      table[i][j] = wa[i].norm === wb[j].norm ? table[i + 1][j + 1] + 1 : Math.max(table[i + 1][j], table[i][j + 1]);
    }
  }
  const same = { a: new Set(), b: new Set() };
  let i = 0, j = 0;
  while (i < wa.length && j < wb.length) {
    if (wa[i].norm === wb[j].norm) { same.a.add(wa[i]); same.b.add(wb[j]); i++; j++; }
    else if (table[i + 1][j] >= table[i][j + 1]) i++;
    else j++;
  }
  return same;
}

function segments(tokens, same) {
  const marks = tokens.map((t) => ({ text: t.text, changed: t.norm !== null && t.norm !== "" && !same.has(t), space: t.norm === null }));
  // whitespace between two changed words is part of the highlight
  marks.forEach((m, k) => {
    if (m.space && marks[k - 1]?.changed && marks[k + 1]?.changed) m.changed = true;
  });
  const out = [];
  for (const m of marks) {
    const last = out[out.length - 1];
    if (last && last.changed === m.changed) last.text += m.text;
    else out.push({ text: m.text, changed: m.changed });
  }
  return out;
}

export function wordDiff(a, b) {
  const ta = words(a), tb = words(b);
  const same = matchedWords(ta, tb);
  return { a: segments(ta, same.a), b: segments(tb, same.b) };
}

export function valuesDiffer(a, b) {
  const norm = (v) => words(v).filter((t) => t.norm).map((t) => t.norm).join(" ");
  return norm(a) !== norm(b);
}
