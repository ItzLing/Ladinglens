import { FIELDS, REASON, categoryLabel, plural } from "./util/format.js";

// ---- pure selectors, unit-tested ----

export function isFailed(row) {
  return row.review_reason === "processing_error";
}

export function needsAttention(row) {
  return row.status === "MISMATCH" || row.status === "NEEDS_REVIEW";
}

/** A case only a person can settle: it needs review, or it failed on the model API. Review's queue is exactly these. */
export function needsPerson(row) {
  return row.status === "NEEDS_REVIEW" || isFailed(row);
}

/** What to show as a row's status, or null when the label says it all. */
export function statusChip(row) {
  if (isFailed(row)) return { kind: "failed", icon: "refresh", text: "Failed. Retry" };
  if (row.status === "MISMATCH") {
    const n = row.defect_fields?.length ?? 0;
    return { kind: "mismatch", icon: "x", text: plural(n, "mismatch", "mismatches") };
  }
  if (row.status === "NEEDS_REVIEW") {
    const text = row.issue_count > 0 ? `${row.issue_count} to review` : REASON[row.review_reason] ?? "Needs review";
    return { kind: "review", icon: "alert", text };
  }
  if (row.status === "OK" && row.category === "BL_COMPARISON") {
    return { kind: "ok", icon: "check", text: "No mismatch" };
  }
  return null;
}

const rank = (row) => (isFailed(row) ? 0 : row.status === "NEEDS_REVIEW" ? 1 : row.status === "MISMATCH" ? 2 : 3);

/** Failed first, then review, then mismatches, then the rest; by ID within each. */
export function sortRows(rows) {
  return [...rows].sort((a, b) => rank(a) - rank(b) || a.email_id.localeCompare(b.email_id));
}

function matchesQuery(row, q) {
  if (!q) return true;
  const needle = q.trim().toLowerCase();
  return [row.email_id, row.subject, row.from, row.summary].some((v) => String(v ?? "").toLowerCase().includes(needle));
}

const inTab = (row, tab) => tab !== "attention" || needsAttention(row);

export function filterRows(rows, { tab = "attention", group = null, q = "" } = {}) {
  return sortRows(rows.filter((r) => inTab(r, tab) && (!group || r.category === group) && matchesQuery(r, q)));
}

/** Rows per label for the group chips, ignoring the chosen group so each chip shows what it would give. */
export function groupCounts(rows, { tab = "attention", q = "" } = {}) {
  const counts = {};
  for (const r of rows) if (inTab(r, tab) && matchesQuery(r, q)) counts[r.category] = (counts[r.category] ?? 0) + 1;
  return counts;
}

export function tabCounts(rows, { group = null, q = "" } = {}) {
  const pool = rows.filter((r) => (!group || r.category === group) && matchesQuery(r, q));
  return { attention: pool.filter(needsAttention).length, all: pool.length };
}

/** The 7 field rows for the detail table, from `extracted` or, for older runs, from `mismatches`. */
export function fieldRows(record, fields) {
  const extracted = record.extracted ?? {};
  const issues = record.field_issues ?? [];
  const haveExtracted = extracted.SI || extracted.BL;
  return fields.map(([key, label]) => {
    const si = haveExtracted ? extracted.SI?.fields?.[key] ?? null : record.mismatches?.[key]?.si ?? null;
    const bl = haveExtracted ? extracted.BL?.fields?.[key] ?? null : record.mismatches?.[key]?.bl ?? null;
    const own = issues.filter((i) => i.field === key);
    return {
      key, label, si, bl,
      siSource: extracted.SI?.sources?.[key] ?? null,
      blSource: extracted.BL?.sources?.[key] ?? null,
      issues: own,
      differs: Boolean(record.mismatches?.[key]),
      // an older run only recorded the fields that differed, so the rest are unknown
      known: haveExtracted || Boolean(record.mismatches?.[key]),
    };
  });
}

export const STATUS_LABEL = { OK: "No mismatch", MISMATCH: "Mismatch", NEEDS_REVIEW: "Needs review" };
export const PRIORITY_LABEL = { high: "High", medium: "Medium", low: "Low" };
const PRIORITY_RANK = { high: 0, medium: 1, low: 2 };

/** Fix mismatches first, then review uncertain cases, then archive the clean checks. */
export function priorityOf(row) {
  if (row.status === "MISMATCH") return "high";
  if (row.status === "NEEDS_REVIEW") return "medium";
  return "low";
}

/** What a person should do with this email next, in one sentence. */
export function nextStep(row) {
  if (isFailed(row)) return "Retry this email. The failure was not about the documents.";
  if (row.status === "MISMATCH") return "Ask the documentation team to correct the flagged BL fields.";
  if (row.status === "NEEDS_REVIEW") return "Send to a person with the attachments and the reason.";
  return {
    BL_COMPARISON: "Approve the document check and continue the release workflow.",
    SPAM: "Archive or block the sender.",
    INVOICE_QUERY: "Route to the finance or billing queue.",
    SI_REQUEST: "Route to the SI preparation queue.",
  }[row.category] ?? "No document check needed.";
}

/** Mismatches first, then reviews, then clean checks; by ID within each. Does not change the array it is given. */
export function sortByPriority(rows) {
  return [...rows].sort((a, b) => PRIORITY_RANK[priorityOf(a)] - PRIORITY_RANK[priorityOf(b)] || a.email_id.localeCompare(b.email_id));
}

/** The result as one plain phrase, for the CSV and the summary. */
export function resultText(row) {
  if (isFailed(row)) return REASON.processing_error;
  if (row.status === "NEEDS_REVIEW") return REASON[row.review_reason] ?? STATUS_LABEL.NEEDS_REVIEW;
  return STATUS_LABEL[row.status] ?? "No mismatch";
}

/** The four headline numbers of the Report tab. */
export function reportTiles(summary = {}) {
  return [
    { label: "Emails processed", value: summary.total ?? 0, note: "whole inbox" },
    { label: "Comparison requests", value: summary.categories?.BL_COMPARISON ?? 0, note: "routed to document checking" },
    { label: "Mismatches found", value: summary.defects ?? 0, note: "SI and BL disagree" },
    { label: "Escalated to a human", value: summary.statuses?.NEEDS_REVIEW ?? 0, note: "not decided automatically" },
  ];
}

/** Three reading aids for the inbox mix: how much needed no person, what is left to do, and what was checked. */
export function reportInsights(summary = {}) {
  const total = summary.total ?? 0;
  const statuses = summary.statuses ?? {};
  const decided = (statuses.OK ?? 0) + (statuses.MISMATCH ?? 0);
  return [
    { label: "Automation ready", value: `${total ? Math.round((decided / total) * 100) : 0}%`, note: "classified or compared without manual triage" },
    { label: "Action required", value: (statuses.MISMATCH ?? 0) + (statuses.NEEDS_REVIEW ?? 0), note: "mismatches plus review cases" },
    { label: "Document checks", value: summary.categories?.BL_COMPARISON ?? 0, note: "emails routed into SI/BL verification" },
  ];
}

/** Explains whichever escalation reason dominates, so a large review count never stands unexplained. */
export function escalationNote(summary = {}) {
  const reasons = summary.review_reasons ?? {};
  if (reasons.processing_error) {
    return `${plural(reasons.processing_error, "email")} could not be processed because the model API failed, not because of anything in the documents. They are escalated rather than guessed at, and can be retried without re-running the rest.`;
  }
  if (reasons.unreadable) {
    return `${plural(reasons.unreadable, "email")} carry an attachment that could not be read: a corrupt or empty file, or a type this version does not open. Rather than guess at its contents, the system escalates them for a person.`;
  }
  return null;
}

/** A short plain-text summary of the run, to paste into a message. */
export function summaryText(report) {
  const s = report?.summary ?? {};
  const statuses = s.statuses ?? {};
  return [
    "Ladinglens report",
    `Emails processed: ${s.total ?? 0}`,
    `Comparison requests: ${s.categories?.BL_COMPARISON ?? 0}`,
    `Mismatches found: ${s.defects ?? 0}`,
    `Needs human review: ${statuses.NEEDS_REVIEW ?? 0}`,
    `Action required: ${(statuses.MISMATCH ?? 0) + (statuses.NEEDS_REVIEW ?? 0)}`,
  ].join("\n");
}

const csvCell = (value) => `"${String(value ?? "").replaceAll('"', '""')}"`;

/** The rows as CSV text, in the order given. */
export function rowsToCsv(rows) {
  const header = ["priority", "email_id", "subject", "from", "category", "result", "confidence", "next_step", "fields_flagged"];
  const lines = rows.map((r) =>
    [
      PRIORITY_LABEL[priorityOf(r)],
      r.email_id,
      r.subject,
      r.from,
      categoryLabel(r.category),
      resultText(r),
      typeof r.confidence === "number" ? `${Math.round(r.confidence * 100)}%` : "",
      nextStep(r),
      (r.defect_fields ?? []).map((k) => FIELD_LABEL[k] ?? k).join(", "),
    ].map(csvCell).join(","),
  );
  return [header.map(csvCell).join(","), ...lines].join("\n");
}

/** Rows per status for the shortcut pills, ignoring the chosen status so each pill shows what it would give. */
export function statusCounts(rows, { q = "" } = {}) {
  const pool = rows.filter((r) => matchesQuery(r, q));
  const counts = { "": pool.length };
  for (const r of pool) counts[r.status] = (counts[r.status] ?? 0) + 1;
  return counts;
}

/**
 * Hand a case to a named person. Demo only: nothing is sent, the map is what the page keeps.
 * A blank name changes nothing. Returns a new map.
 */
export function delegate(map, emailId, name, now = new Date().toISOString()) {
  const to = String(name ?? "").replace(/\s+/g, " ").trim().slice(0, 80);
  if (!emailId || !to) return map;
  return { ...map, [emailId]: { to, at: now } };
}

/** Take a case back from whoever it was handed to. Returns a new map. */
export function takeBack(map, emailId) {
  const next = { ...map };
  delete next[emailId];
  return next;
}

/**
 * What the run bar can offer, from the report on screen.
 * `left` is the emails with no saved result yet: new ones added to the inbox, or ones a stopped
 * run never reached. `startOver` is the wording of the confirmation for a fresh run, which
 * replaces the saved results, so it has to say so.
 */
export function runPlan(report) {
  const s = report?.summary ?? {};
  const full = report?.scope === "full";
  const saved = full ? s.total ?? 0 : 0;
  const inbox = s.inbox_total ?? s.total ?? 0;
  const left = full && saved > 0 ? Math.max(0, inbox - saved) : 0;
  const failed = s.failed ?? 0;
  const keep = left > 0 ? ' To keep them, cancel and use "Run new" instead.' : failed > 0 ? ' To keep the good ones, cancel and use "Retry" instead.' : "";
  const startOver = saved > 0
    ? `Start over on ${inbox} emails? This replaces the ${saved} saved results (a backup copy is kept) and uses model quota.${keep}`
    : `Run the pipeline on ${inbox || "all"} emails? This uses model quota.`;
  return { saved, left, failed, startOver };
}

/** Emails grouped by label for the folded Report list, in label order, empty groups left out. */
export function reportGroups(rows, { status = "", q = "" } = {}, order = []) {
  const pool = rows.filter((r) => (!status || r.status === status) && matchesQuery(r, q));
  const labels = [...order, ...new Set(pool.map((r) => r.category).filter((c) => !order.includes(c)))];
  return labels
    .map((category) => {
      const items = sortByPriority(pool.filter((r) => r.category === category));
      return {
        category,
        items,
        mismatches: items.filter((r) => r.status === "MISMATCH").length,
        reviews: items.filter((r) => r.status === "NEEDS_REVIEW").length,
      };
    })
    .filter((g) => g.items.length > 0);
}

const FIELD_LABEL = Object.fromEntries(FIELDS);

/** One plain sentence saying why a case is here (or that it is fine). */
export function caseBanner(record, category) {
  const reason = record.review_reason;
  if (reason === "processing_error") {
    return { kind: "review", icon: "alert", text: "Processing failed. This is not a verdict on the documents." };
  }
  if (record.status === "MISMATCH") {
    const names = (record.defect_fields ?? []).map((k) => FIELD_LABEL[k] ?? k);
    return { kind: "mismatch", icon: "x", text: `${plural(names.length, "field differs", "fields differ")} between the SI and the BL: ${names.join(", ")}.` };
  }
  if (record.status === "NEEDS_REVIEW") {
    const n = (record.field_issues ?? []).length;
    const text = {
      missing_value: `${plural(n, "field", "fields")} could not be trusted, so this case needs a person.`,
      unreadable: "A document could not be read, so nothing was compared.",
      missing_attachment: "The SI or the BL is missing, so nothing was compared.",
      low_confidence: "The system was not sure this is a document check, so it is waiting for a person.",
    }[reason] ?? "This case needs a person.";
    return { kind: "review", icon: "alert", text };
  }
  if (record.status === "OK" && category === "BL_COMPARISON") {
    return { kind: "ok", icon: "check", text: "No mismatch detected." };
  }
  return null;
}

// ---- a tiny observable store ----

export function createStore(initial) {
  let state = initial;
  const subscribers = new Set();
  return {
    get: () => state,
    set(patch) {
      state = { ...state, ...patch };
      subscribers.forEach((fn) => fn(state));
    },
    subscribe(fn) {
      subscribers.add(fn);
      return () => subscribers.delete(fn);
    },
  };
}
