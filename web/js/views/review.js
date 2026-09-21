import { add, h, clear, announce } from "../util/dom.js";
import { icon } from "../util/icons.js";
import { FIELDS, REASON, categoryLabel, formatConfidence } from "../util/format.js";
import { caseBanner, fieldRows, sortRows } from "../store.js";
import { routeHash } from "../router.js";
import { labelChip, statusChipEl } from "../components/chips.js";
import { documentsView } from "../components/fields.js";

const STORAGE_KEY = "ladinglens-review-corrections-v1";
const REVIEW_FIELDS = [...FIELDS, ["amount_money", "Amount / money"]];
const URGENT_REASONS = new Set(["processing_error", "missing_attachment", "unreadable"]);

const excerpt = (text, limit = 150) => {
  const clean = String(text ?? "").replace(/\s+/g, " ").trim();
  return clean.length > limit ? `${clean.slice(0, limit)}...` : clean;
};

function readSaved() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
  } catch {
    return {};
  }
}

function writeSaved(saved) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(saved));
    return true;
  } catch {
    return false;
  }
}

function reviewReason(row) {
  if (row.review_reason) return REASON[row.review_reason] ?? row.review_reason;
  if (row.status === "MISMATCH") return "Document mismatch";
  return "Needs human check";
}

function isReviewCandidate(row) {
  return row.status === "NEEDS_REVIEW" || row.review_reason === "processing_error";
}

function isUrgent(row) {
  return URGENT_REASONS.has(row.review_reason) || row.review_reason === "processing_error";
}

function bestValue(record, key, saved) {
  if (saved?.fields && Object.prototype.hasOwnProperty.call(saved.fields, key)) return saved.fields[key] ?? "";
  const row = fieldRows(record, FIELDS).find((field) => field.key === key);
  if (!row) return "";
  return row.bl ?? row.si ?? record.mismatches?.[key]?.bl ?? record.mismatches?.[key]?.si ?? "";
}

function sourceText(record, key) {
  const row = fieldRows(record, FIELDS).find((field) => field.key === key);
  if (!row) return "Optional business value.";
  const parts = [];
  if (row.si != null) parts.push(`SI: ${row.si}`);
  if (row.bl != null) parts.push(`BL: ${row.bl}`);
  if (row.issues.length) parts.push(row.issues.map((issue) => REASON[issue.reason] ?? issue.reason).join(", "));
  return parts.join(" | ") || "No trusted value found yet.";
}

function downloadJson(name, data) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = h("a", { href: url, download: name });
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 500);
}

/**
 * Human Review tab. It is the holding area for cases the model could not finish.
 * Corrections are stored in localStorage so the static demo remains editable.
 */
export function mountReview(root, ctx) {
  const { api } = ctx;
  let selectedId = null;
  let token = 0;
  let mode = "open";
  let q = "";
  let saved = readSaved();

  const tabsEl = h("div", { class: "tabs", role: "tablist", "aria-label": "Review status" });
  const search = h("input", {
    class: "search", type: "search", placeholder: "Search review cases", "aria-label": "Search review cases",
    oninput: (e) => { q = e.target.value; renderList(); },
  });
  const listEl = h("div", { class: "list-scroll", role: "listbox", "aria-label": "Review queue", tabindex: "0" });
  const detailEl = h("section", { class: "pane-detail", "aria-label": "Human review detail" });
  const panes = h(
    "div",
    { class: "panes review-panes" },
    h("section", { class: "pane-list", "aria-label": "Review list" }, tabsEl, h("div", { class: "filters" }, search), listEl),
    detailEl,
  );
  clear(root).append(panes);

  const rows = () => ctx.getReport()?.emails ?? [];
  const reviewRows = () => sortRows(rows().filter(isReviewCandidate));
  const savedRows = () => sortRows(rows().filter((row) => Boolean(saved[row.email_id])));
  const activeRows = () => {
    const pool = mode === "saved" ? savedRows() : reviewRows();
    const needle = q.trim().toLowerCase();
    return needle
      ? pool.filter((row) => [row.email_id, row.subject, row.from, row.summary, reviewReason(row)].some((value) => String(value ?? "").toLowerCase().includes(needle)))
      : pool;
  };

  function setMode(next) {
    mode = next;
    renderList();
  }

  function renderTabs() {
    const counts = { open: reviewRows().length, saved: savedRows().length };
    clear(tabsEl).append(
      ...[["open", "To review"], ["saved", "Saved"]].map(([key, label]) =>
        h("button", { class: "tab", role: "tab", type: "button", "aria-selected": String(mode === key), onclick: () => setMode(key) },
          label, h("span", { class: "count" }, counts[key])),
      ),
    );
  }

  function renderRows() {
    const list = activeRows();
    clear(listEl);
    if (!list.length) {
      listEl.append(h("div", { class: "empty" }, mode === "saved" ? "No saved corrections yet." : "Nothing is waiting for review."));
      return;
    }
    listEl.append(
      ...list.map((row) =>
        h("button", { class: "row", role: "option", type: "button", id: `review-row-${row.email_id}`, "aria-selected": String(row.email_id === selectedId), onclick: () => { location.hash = routeHash("review", row.email_id); } },
          h("div", { class: "id" }, row.email_id),
          h("div", { class: "subject" }, row.subject || "(no subject)"),
          h("div", { class: "meta" },
            h("span", { class: `chip ${isUrgent(row) ? "failed" : "review"}` }, icon(isUrgent(row) ? "alert" : "info"), isUrgent(row) ? "Urgent" : "Normal"),
            labelChip(row.category),
            statusChipEl(row),
            saved[row.email_id] ? h("span", { class: "chip ok" }, icon("check"), "Saved") : null),
          h("div", { class: "review-reason" }, reviewReason(row)),
        ),
      ),
    );
  }

  function renderList() {
    renderTabs();
    renderRows();
  }

  function markSelected() {
    for (const el of listEl.querySelectorAll('[role="option"]')) el.setAttribute("aria-selected", String(el.id === `review-row-${selectedId}`));
    document.getElementById(`review-row-${selectedId}`)?.scrollIntoView({ block: "nearest" });
  }

  const backButton = () => h("a", { class: "btn small back", href: routeHash("review") }, icon("back"), "Review queue");

  function fold(title, content, open = false) {
    return h("details", { class: "fold", open: open ? "" : null }, h("summary", {}, title), h("div", { class: "fold-body" }, content));
  }

  function buildForm(row, kase) {
    const record = kase.record;
    const correction = saved[row.email_id] ?? {};
    const fields = new Map();
    const note = h("textarea", { class: "review-note", rows: "5", placeholder: "Add reviewer notes, decision reason, or follow-up needed." }, correction.notes ?? "");
    const status = h("span", { class: "review-saved" }, correction.updated_at ? `Saved ${new Date(correction.updated_at).toLocaleString()}` : "Not saved yet");

    const form = h("form", { class: "review-form", onsubmit: (event) => save(event) });
    const grid = h("div", { class: "review-grid" });
    for (const [key, label] of REVIEW_FIELDS) {
      const input = h("input", { name: key, value: key === "amount_money" ? correction.fields?.[key] ?? "" : bestValue(record, key, correction), autocomplete: "off" });
      fields.set(key, input);
      grid.append(
        h("label", { class: "review-field" },
          h("span", {}, label),
          input,
          h("small", {}, sourceText(record, key))),
      );
    }

    add(form,
      h("div", { class: "section review-case" },
        h("h3", {}, "Case problem"),
        h("div", { class: "kv" }, "Email", h("strong", {}, row.email_id)),
        h("div", { class: "kv" }, "Label", h("strong", {}, categoryLabel(row.category))),
        h("div", { class: "kv" }, "Confidence", h("strong", {}, formatConfidence(row.confidence))),
        h("div", { class: "kv" }, "Reason", h("strong", {}, reviewReason(row)))),
      h("div", { class: "section" }, h("h3", {}, "Corrected values"), grid),
      h("div", { class: "section" }, h("h3", {}, "Reviewer notes"), note),
      h("div", { class: "review-actions" },
        h("button", { class: "btn", type: "submit" }, icon("check"), "Save correction"),
        h("button", { class: "btn", type: "button", onclick: clearOne }, icon("x"), "Clear saved"),
        h("button", { class: "btn", type: "button", onclick: exportSaved }, icon("database"), "Export JSON"),
        status),
    );

    function payload() {
      const values = {};
      for (const [key, input] of fields) values[key] = input.value.trim();
      return {
        email_id: row.email_id,
        subject: row.subject ?? "",
        category: row.category,
        review_reason: row.review_reason,
        fields: values,
        notes: note.value.trim(),
        updated_at: new Date().toISOString(),
      };
    }

    function save(event) {
      event.preventDefault();
      saved = { ...saved, [row.email_id]: payload() };
      if (!writeSaved(saved)) {
        announce("Could not save in this browser.");
        return;
      }
      status.textContent = `Saved ${new Date(saved[row.email_id].updated_at).toLocaleString()}`;
      renderList();
      markSelected();
      announce("Correction saved.");
    }

    function clearOne() {
      const next = { ...saved };
      delete next[row.email_id];
      saved = next;
      writeSaved(saved);
      announce("Saved correction cleared.");
      renderList();
      renderDetail();
    }

    function exportSaved() {
      downloadJson("ladinglens-review-corrections.json", Object.values(saved));
      announce("Saved corrections exported.");
    }

    return form;
  }

  function detailHeader(row) {
    return [
      backButton(),
      h("div", { class: "case-head" },
        h("span", { class: `chip ${isUrgent(row) ? "failed" : "review"}` }, icon(isUrgent(row) ? "alert" : "info"), isUrgent(row) ? "Urgent" : "Normal"),
        labelChip(row.category),
        statusChipEl(row)),
      h("h2", { class: "case-title" }, row.subject || "(no subject)"),
      h("p", { class: "case-sub" }, `${row.email_id} - from ${row.from || "unknown sender"}`),
    ];
  }

  function detailSections(row, kase) {
    const banner = caseBanner(kase.record, row.category);
    const docs = documentsView(kase, api);
    return [
      banner ? h("div", { class: `banner ${banner.kind}` }, icon(banner.icon), banner.text) : null,
      buildForm(row, kase),
      h("div", { class: "section" }, h("h3", {}, "Original email and documents"),
        fold("Email body", h("pre", { class: "doc" }, kase.email.body || ""), true),
        docs ? fold("Documents", docs) : null),
    ];
  }

  async function renderDetail() {
    const mine = ++token;
    clear(detailEl);
    panes.classList.toggle("has-selection", Boolean(selectedId));
    if (!selectedId) {
      detailEl.append(h("div", { class: "empty" }, "Select a case to review and correct the fields."));
      return;
    }
    const row = rows().find((candidate) => candidate.email_id === selectedId);
    if (!row) {
      detailEl.append(backButton(), h("div", { class: "empty" }, `There is no case for ${selectedId}.`));
      return;
    }
    const body = h("div", {}, h("div", { class: "skeleton" }));
    detailEl.append(...detailHeader(row), body);
    try {
      const kase = await api.caseFor(selectedId, ctx.getReport().scope);
      if (mine !== token) return;
      clear(body).append(...detailSections(row, kase));
    } catch (err) {
      if (mine !== token) return;
      clear(body).append(h("div", { class: "banner review" }, icon("alert"), err.message));
    }
  }

  renderList();
  renderDetail();

  return {
    setId(id) {
      selectedId = id;
      markSelected();
      renderDetail();
    },
    refresh() {
      saved = readSaved();
      renderList();
      markSelected();
      renderDetail();
    },
    move(delta) {
      const list = activeRows();
      if (!list.length) return;
      const at = list.findIndex((row) => row.email_id === selectedId);
      const next = list[Math.min(list.length - 1, Math.max(0, at === -1 ? 0 : at + delta))];
      location.hash = routeHash("review", next.email_id);
    },
    focusSearch() { search.focus(); },
  };
}
