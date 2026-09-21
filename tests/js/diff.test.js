import test from "node:test";
import assert from "node:assert/strict";
import { wordDiff, valuesDiffer, normalizeToken } from "../../web/js/util/diff.js";

const changed = (segs) => segs.filter((s) => s.changed).map((s) => s.text.trim());
const joined = (segs) => segs.map((s) => s.text).join("");

test("identical values highlight nothing", () => {
  const d = wordDiff("BALL & DOGGETT PTY LTD", "BALL & DOGGETT PTY LTD");
  assert.deepEqual(changed(d.a), []);
  assert.deepEqual(changed(d.b), []);
});

test("only the words that differ are highlighted", () => {
  const d = wordDiff("BALL & DOGGETT AUSTRALIA PTY LTD", "BALL & DOGGETT AUSTRAL PTY LTD");
  assert.deepEqual(changed(d.a), ["AUSTRALIA"]);
  assert.deepEqual(changed(d.b), ["AUSTRAL"]);
});

test("completely different values are highlighted in full", () => {
  const d = wordDiff("EAST BRIGHT FZ-LLC", "UAB NOVAKOPA");
  assert.deepEqual(changed(d.a), ["EAST BRIGHT FZ-LLC"]);
  assert.deepEqual(changed(d.b), ["UAB NOVAKOPA"]);
});

test("the segments always rebuild the original text", () => {
  for (const [a, b] of [["A B C", "A X C"], ["one  two", "one two three"], ["", "x"], ["x", ""]]) {
    const d = wordDiff(a, b);
    assert.equal(joined(d.a), a);
    assert.equal(joined(d.b), b);
  }
});

test("case, separators and thousands commas are not differences, like compare.py", () => {
  assert.equal(valuesDiffer("243,588 KG", "243588 kg"), false);
  assert.equal(valuesDiffer("A | B; C", "A B C"), false);
  assert.equal(valuesDiffer("P.O. BOX 5069, DUBAI", "p.o. box 5069 dubai"), false);
  assert.deepEqual(changed(wordDiff("243,588 KG", "243588 kg").a), []);
});

test("real differences are still differences", () => {
  assert.equal(valuesDiffer("243,588 KG", "243,589 KG"), true);
  assert.equal(valuesDiffer("6 x 40'HC", "6 x 20'FCL"), true);
  assert.equal(valuesDiffer("NANTONG, CHINA", "NINGBO, CHINA"), true);
});

test("missing values are handled without throwing", () => {
  assert.equal(valuesDiffer(null, undefined), false);
  assert.equal(valuesDiffer(null, "x"), true);
  assert.deepEqual(wordDiff(null, "x").a, []);
});

test("a shifted word is matched, not marked as changed", () => {
  const d = wordDiff("ACME TRADING LTD", "ACME LTD");
  assert.deepEqual(changed(d.a), ["TRADING"]);
  assert.deepEqual(changed(d.b), []);
});

test("normalizeToken", () => {
  assert.equal(normalizeToken("Dubai,"), "DUBAI");
  assert.equal(normalizeToken("1,234"), "1234");
});
