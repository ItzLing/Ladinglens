import test from "node:test";
import assert from "node:assert/strict";
import {
  caseBanner, createStore, fieldRows, filterRows, groupCounts, isFailed, needsAttention, sortRows, statusChip, tabCounts,
} from "../../web/js/store.js";
import { FIELDS } from "../../web/js/util/format.js";

const row = (id, category, status, extra = {}) => ({
  email_id: id, subject: `Subject ${id}`, from: "a@x.com", summary: null,
  category, status, review_reason: null, defect_fields: [], issue_count: 0, ...extra,
});

const ROWS = [
  row("e1", "BL_COMPARISON", "OK"),
  row("e2", "BL_COMPARISON", "MISMATCH", { defect_fields: ["consignee", "notify_party"] }),
  row("e3", "SPAM", "OK", { subject: "Cheap watches" }),
  row("e4", "BL_COMPARISON", "NEEDS_REVIEW", { review_reason: "missing_value", issue_count: 2 }),
  row("e5", "GENERAL", "NEEDS_REVIEW", { review_reason: "processing_error" }),
  row("e6", "SI_REQUEST", "OK", { summary: "Wants a new shipping instruction" }),
];

test("what needs attention: mismatches, reviews and failures", () => {
  assert.deepEqual(ROWS.filter(needsAttention).map((r) => r.email_id), ["e2", "e4", "e5"]);
  assert.equal(isFailed(ROWS[4]), true);
  assert.equal(isFailed(ROWS[3]), false);
});

test("status chips say what happened, and nothing for non-comparisons", () => {
  assert.deepEqual(statusChip(ROWS[0]), { kind: "ok", icon: "check", text: "No mismatch" });
  assert.equal(statusChip(ROWS[1]).text, "2 mismatches");
  assert.equal(statusChip(row("x", "BL_COMPARISON", "MISMATCH", { defect_fields: ["a"] })).text, "1 mismatch");
  assert.equal(statusChip(ROWS[3]).text, "2 to review");
  assert.equal(statusChip(row("x", "BL_COMPARISON", "NEEDS_REVIEW", { review_reason: "unreadable" })).text, "Document unreadable");
  assert.deepEqual(statusChip(ROWS[4]), { kind: "failed", icon: "refresh", text: "Failed. Retry" });
  assert.equal(statusChip(ROWS[2]), null);
  assert.equal(statusChip(ROWS[5]), null);
});

test("sorting puts failures first, then reviews, mismatches, the rest, by ID", () => {
  assert.deepEqual(sortRows(ROWS).map((r) => r.email_id), ["e5", "e4", "e2", "e1", "e3", "e6"]);
});

test("sorting does not change the original list", () => {
  const copy = [...ROWS];
  sortRows(ROWS);
  assert.deepEqual(ROWS, copy);
});

test("the Need attention tab, All emails tab, and a label filter", () => {
  assert.deepEqual(filterRows(ROWS, { tab: "attention" }).map((r) => r.email_id), ["e5", "e4", "e2"]);
  assert.equal(filterRows(ROWS, { tab: "all" }).length, 6);
  assert.deepEqual(filterRows(ROWS, { tab: "all", group: "SPAM" }).map((r) => r.email_id), ["e3"]);
  assert.deepEqual(filterRows(ROWS, { tab: "attention", group: "BL_COMPARISON" }).map((r) => r.email_id), ["e4", "e2"]);
  assert.deepEqual(filterRows(ROWS, { tab: "attention", group: "SPAM" }), []);
});

test("search covers ID, subject, sender and summary, ignoring case", () => {
  assert.deepEqual(filterRows(ROWS, { tab: "all", q: "WATCHES" }).map((r) => r.email_id), ["e3"]);
  assert.deepEqual(filterRows(ROWS, { tab: "all", q: "e4" }).map((r) => r.email_id), ["e4"]);
  assert.deepEqual(filterRows(ROWS, { tab: "all", q: "new shipping" }).map((r) => r.email_id), ["e6"]);
  assert.equal(filterRows(ROWS, { tab: "all", q: "a@x.com" }).length, 6);
  assert.deepEqual(filterRows(ROWS, { tab: "all", q: "zzz" }), []);
});

test("group counts follow the tab but not the chosen group", () => {
  assert.deepEqual(groupCounts(ROWS, { tab: "attention" }), { BL_COMPARISON: 2, GENERAL: 1 });
  assert.deepEqual(groupCounts(ROWS, { tab: "all" }), { BL_COMPARISON: 3, SPAM: 1, GENERAL: 1, SI_REQUEST: 1 });
  assert.deepEqual(groupCounts(ROWS, { tab: "all", q: "watches" }), { SPAM: 1 });
});

test("tab counts follow the group and search", () => {
  assert.deepEqual(tabCounts(ROWS), { attention: 3, all: 6 });
  assert.deepEqual(tabCounts(ROWS, { group: "BL_COMPARISON" }), { attention: 2, all: 3 });
});

const ex = (fields, sources = {}) => ({ file: "f", fields, sources });
const allNull = Object.fromEntries(FIELDS.map(([k]) => [k, null]));

test("field rows come from the extracted values when the run kept them", () => {
  const record = {
    extracted: {
      SI: ex({ ...allNull, shipper: "ACME", consignee: "BOB LLC" }, { shipper: "text" }),
      BL: ex({ ...allNull, shipper: "ACME", consignee: "ROB LLC" }, { shipper: "vision" }),
    },
    mismatches: { consignee: { si: "BOB LLC", bl: "ROB LLC" } },
    field_issues: [],
  };
  const rows = fieldRows(record, FIELDS);
  assert.equal(rows.length, 7);
  const shipper = rows.find((r) => r.key === "shipper");
  assert.deepEqual([shipper.si, shipper.bl, shipper.differs, shipper.siSource, shipper.blSource], ["ACME", "ACME", false, "text", "vision"]);
  const consignee = rows.find((r) => r.key === "consignee");
  assert.equal(consignee.differs, true);
  assert.equal(rows.every((r) => r.known), true);
});

test("an older run that only kept the differing fields shows just those as known", () => {
  const record = { mismatches: { consignee: { si: "BOB", bl: "ROB" } }, field_issues: [] };
  const rows = fieldRows(record, FIELDS);
  assert.deepEqual(rows.filter((r) => r.known).map((r) => r.key), ["consignee"]);
  assert.equal(rows.find((r) => r.key === "consignee").si, "BOB");
});

test("a field with an issue carries it, and its value is empty", () => {
  const issue = { field: "gross_weight_kg", document: "BL", reason: "unreadable", evidence: "Gross Weight: ____MT" };
  const record = {
    extracted: { SI: ex({ ...allNull, gross_weight_kg: "131,058 KG" }), BL: ex({ ...allNull }) },
    mismatches: {}, field_issues: [issue],
  };
  const weight = fieldRows(record, FIELDS).find((r) => r.key === "gross_weight_kg");
  assert.equal(weight.bl, null);
  assert.deepEqual(weight.issues, [issue]);
});

test("a record with no data at all does not throw", () => {
  assert.equal(fieldRows({}, FIELDS).length, 7);
});

test("the store notifies subscribers and can be unsubscribed", () => {
  const store = createStore({ a: 1 });
  const seen = [];
  const off = store.subscribe((s) => seen.push(s.a));
  store.set({ a: 2 });
  off();
  store.set({ a: 3 });
  assert.deepEqual(seen, [2]);
  assert.equal(store.get().a, 3);
});

test("the banner says why a case is here, in plain words", () => {
  const banner = (record, category = "BL_COMPARISON") => caseBanner(record, category);
  assert.deepEqual(banner({ status: "OK" }), { kind: "ok", icon: "check", text: "No mismatch detected." });
  assert.equal(banner({ status: "OK" }, "SPAM"), null);
  assert.equal(banner({ status: "MISMATCH", defect_fields: ["consignee", "notify_party"] }).text,
    "2 fields differ between the SI and the BL: Consignee, Notify party.");
  assert.equal(banner({ status: "MISMATCH", defect_fields: ["gross_weight_kg"] }).text,
    "1 field differs between the SI and the BL: Gross weight (kg).");
  assert.match(banner({ status: "NEEDS_REVIEW", review_reason: "missing_value", field_issues: [{}, {}] }).text, /^2 fields could not be trusted/);
  assert.match(banner({ status: "NEEDS_REVIEW", review_reason: "unreadable" }).text, /could not be read/);
  assert.match(banner({ status: "NEEDS_REVIEW", review_reason: "missing_attachment" }).text, /missing/);
  assert.match(banner({ status: "NEEDS_REVIEW", review_reason: "low_confidence" }).text, /not sure/);
  assert.match(banner({ status: "NEEDS_REVIEW", review_reason: "wrong_doc_type" }).text, /needs a person/);
});

test("a failure is never described as a verdict on the documents", () => {
  const b = caseBanner({ status: "NEEDS_REVIEW", review_reason: "processing_error" }, "BL_COMPARISON");
  assert.match(b.text, /not a verdict on the documents/);
  assert.equal(b.kind, "review");
});
