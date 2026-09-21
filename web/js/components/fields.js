import { h } from "../util/dom.js";
import { icon } from "../util/icons.js";
import { FIELDS, SOURCE } from "../util/format.js";
import { fieldRows } from "../store.js";
import { valuesDiffer, wordDiff } from "../util/diff.js";

const marks = (segments) => segments.map((s) => (s.changed ? h("mark", { class: "diff" }, s.text) : s.text));
const blank = () => h("span", { class: "blank" }, "—");
const chip = (kind, iconName, text) => h("span", { class: `chip ${kind}` }, icon(iconName), text);
// Only say how a value was read when it differs from how the rest of its document was read.
const via = (source, usual) => (source && source !== "text" && source !== usual ? h("span", { class: "via" }, SOURCE[source] ?? source) : null);

/** How most of a document's fields were read, so it can be said once instead of on every row. */
export function usualSource(sources = {}) {
  const counts = {};
  for (const source of Object.values(sources)) counts[source] = (counts[source] ?? 0) + 1;
  return Object.entries(counts).sort((a, b) => b[1] - a[1])[0]?.[0] ?? null;
}

function issueNotes(issues, document) {
  return issues
    .filter((i) => i.document === document)
    .map((i) => [
      i.evidence ? h("span", { class: "evidence" }, i.evidence) : null,
      i.detail ? h("span", { class: "via" }, i.detail) : null,
    ]);
}

function cells(r, usual) {
  const needs = r.issues.length > 0;
  if (!r.known) return { si: [blank()], bl: [blank()], result: h("span", { class: "blank" }, "Not recorded"), needs: false };

  if (needs) {
    return {
      si: [r.si ?? blank(), via(r.siSource, usual.SI), issueNotes(r.issues, "SI")],
      bl: [r.bl ?? blank(), via(r.blSource, usual.BL), issueNotes(r.issues, "BL")],
      result: chip("review", "alert", "Review"),
      needs: true,
    };
  }
  if (r.si != null && r.bl != null && (r.differs || valuesDiffer(r.si, r.bl))) {
    const diff = wordDiff(r.si, r.bl);
    return {
      si: [marks(diff.a), via(r.siSource, usual.SI)],
      bl: [marks(diff.b), via(r.blSource, usual.BL)],
      result: chip("mismatch", "x", "Differs"),
      needs: false,
    };
  }
  if (r.si == null && r.bl == null) {
    return { si: [blank()], bl: [blank()], result: h("span", { class: "blank" }, "Not found"), needs: false };
  }
  return {
    si: [r.si ?? blank(), via(r.siSource, usual.SI)],
    bl: [r.bl ?? blank(), via(r.blSource, usual.BL)],
    result: chip("ok", "check", "Match"),
    needs: false,
  };
}

/** All 7 fields, SI beside BL, with what differs highlighted. */
export function fieldTable(record) {
  const older = !(record.extracted?.SI || record.extracted?.BL);
  const usual = { SI: usualSource(record.extracted?.SI?.sources), BL: usualSource(record.extracted?.BL?.sources) };
  const unusual = ["SI", "BL"].filter((d) => usual[d] && usual[d] !== "text");
  const rows = fieldRows(record, FIELDS).map((r) => {
    const c = cells(r, usual);
    return h("tr", { class: c.needs ? "needs" : null }, h("td", { class: "f" }, r.label), h("td", { "data-label": "SI (reference)" }, c.si), h("td", { "data-label": "BL (draft)" }, c.bl), h("td", { class: "res" }, c.result));
  });
  return h(
    "div",
    {},
    h(
      "table",
      { class: "fields" },
      h("caption", { class: "sr-only" }, "The seven shipment fields read from the SI and the BL"),
      h("thead", {}, h("tr", {}, h("th", { class: "f" }, "Field"), h("th", {}, "SI (reference)"), h("th", {}, "BL (draft)"), h("th", { class: "res" }, "Result"))),
      h("tbody", {}, rows),
    ),
    unusual.length
      ? h("p", { class: "muted", style: "margin-top:8px;font-size:12px" }, unusual.map((d) => `${d}: ${SOURCE[usual[d]] ?? usual[d]}.`).join(" "))
      : null,
    older ? h("p", { class: "muted", style: "margin-top:8px;font-size:12px" }, "This result is from an older run that only kept the fields that differ.") : null,
  );
}

const TITLE = { SI: "Shipping Instruction", BL: "Bill of Lading" };

/** The SI and BL as text, or as page images for a scan. */
export function documentsView(kase, api) {
  const docs = kase.documents ?? [];
  if (!docs.length) return null;
  const emailId = kase.email.email_id;
  const column = (d) => {
    let body;
    if (d.kind === "text") body = h("pre", { class: "doc" }, d.text ?? "");
    else if (d.kind === "scan") {
      const url = (n) => api.pageUrl(emailId, d.role, n);
      body = url(1)
        ? Array.from({ length: d.pages }, (_, i) =>
            h("img", { class: "doc-image", src: url(i + 1), loading: "lazy", alt: `Page ${i + 1} of the ${TITLE[d.role]}, a scanned image` }))
        : h("p", { class: "muted" }, "This is a scanned document. Page images need the running app.");
    } else body = h("p", { class: "muted" }, "This file could not be read.");
    return h("div", {}, h("h3", {}, TITLE[d.role] ?? d.role), body);
  };
  return h("div", { class: "docs" }, docs.map(column));
}
