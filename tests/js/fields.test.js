import test from "node:test";
import assert from "node:assert/strict";
import { usualSource } from "../../web/js/components/fields.js";

test("the usual source is how most of a document's fields were read", () => {
  assert.equal(usualSource({ a: "vision", b: "vision", c: "ocr" }), "vision");
  assert.equal(usualSource({ a: "text", b: "text" }), "text");
  assert.equal(usualSource({ a: "ocr", b: "ocr", c: "ocr_llm", d: "ocr_llm", e: "ocr_llm" }), "ocr_llm");
});

test("no sources recorded means no usual source, and does not throw", () => {
  assert.equal(usualSource({}), null);
  assert.equal(usualSource(undefined), null);
});
