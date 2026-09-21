import { add, h, clear, announce } from "../util/dom.js";
import { icon } from "../util/icons.js";
import { FIELDS, REASON, categoryLabel, formatConfidence } from "../util/format.js";
import { caseBanner, delegate, fieldRows, isFailed, needsPerson, sortRows, takeBack } from "../store.js";
import { labelChip, statusChipEl } from "../components/chips.js";
import { emailAndDocuments, mountCasePane, otherTabLink, retryButton, rowButton } from "../components/casepane.js";

const STORAGE_KEY = "ladinglens-review-corrections-v1";
const DELEGATION_KEY = "ladinglens-review-delegations-v1";
const REVIEW_FIELDS = [...FIELDS, ["amount_money", "Amount / money"]];
const URGENT_REASONS = new Set(["processing_error", "missing_attachment", "unreadable"]);

function readSaved() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
  } catch {
    return {};
  }
}

function readDelegations() {
  try {
    return JSON.parse(localStorage.getItem(DELEGATION_KEY) || "{}");
  } catch {
    return {};
  }
}

function writeDelegations(map) {
  try {
    localStorage.setItem(DELEGATION_KEY, JSON.stringify(map));
    return true;
  } catch {
    return false;
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
  let mode = "open";
  let q = "";
  let saved = readSaved();
  let delegations = readDelegations();

  const tabsEl = h("div", { class: "tabs", role: "tablist", "aria-label": "Review status" });
  const search = h("input", {
    class: "search", type: "search", placeholder: "Search review cases", "aria-label": "Search review cases",
    oninput: (e) => { q = e.target.value; renderList(); },
  });
  const pane = mountCasePane(root, {
    tab: "review",
    ctx,
    paneClass: "review-panes",
    top: [tabsEl, h("div", { class: "filters" }, search)],
    search,
    labels: { list: "Review list", listbox: "Review queue", detail: "Human review detail", back: "Review queue", select: "Select a case to review and correct the fields.", missing: (id) => `There is no case for ${id}.` },
    rows: () => activeRows(),
    emptyDetail: () => emptyDetail(),
    header: (row) => detailHeader(row),
    sections: (row, kase) => detailSections(row, kase),
  });
  const listEl = pane.listEl;

  const rows = () => ctx.getReport()?.emails ?? [];
  const reviewRows = () => sortRows(rows().filter((row) => needsPerson(row) && !delegations[row.email_id]));
  const delegatedRows = () => sortRows(rows().filter((row) => Boolean(delegations[row.email_id])));
  const savedRows = () => sortRows(rows().filter((row) => Boolean(saved[row.email_id])));
  const activeRows = () => {
    const pool = mode === "saved" ? savedRows() : mode === "delegated" ? delegatedRows() : reviewRows();
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
    const counts = { open: reviewRows().length, delegated: delegatedRows().length, saved: savedRows().length };
    clear(tabsEl).append(
      ...[["open", "To review"], ["delegated", "Delegated"], ["saved", "Saved"]].map(([key, label]) =>
        h("button", { class: "tab", role: "tab", type: "button", "aria-selected": String(mode === key), onclick: () => setMode(key) },
          label, h("span", { class: "count" }, counts[key])),
      ),
    );
  }

  function renderRows() {
    const list = activeRows();
    clear(listEl);
    if (!list.length) {
      const empty = { saved: "No saved corrections yet.", delegated: "Nothing has been delegated yet." }[mode] ?? "Nothing is waiting for review.";
      listEl.append(h("div", { class: "empty" }, empty));
      return;
    }
    listEl.append(
      ...list.map((row) =>
        rowButton("review", row, pane.selectedId(),
          h("div", { class: "id" }, row.email_id),
          h("div", { class: "subject" }, row.subject || "(no subject)"),
          h("div", { class: "meta" },
            h("span", { class: `chip ${isUrgent(row) ? "failed" : "review"}` }, icon(isUrgent(row) ? "alert" : "info"), isUrgent(row) ? "Urgent" : "Normal"),
            labelChip(row.category),
            statusChipEl(row),
            delegations[row.email_id] ? h("span", { class: "chip label" }, icon("user"), `Delegated to ${delegations[row.email_id].to}`) : null,
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
      pane.markSelected();
      announce("Correction saved.");
    }

    function clearOne() {
      const next = { ...saved };
      delete next[row.email_id];
      saved = next;
      writeSaved(saved);
      announce("Saved correction cleared.");
      renderList();
      pane.renderDetail();
    }

    function exportSaved() {
      downloadJson("ladinglens-review-corrections.json", Object.values(saved));
      announce("Saved corrections exported.");
    }

    return form;
  }

  /** Demo delegation: type a name, press Send. Nothing leaves the browser. */
  function buildDelegate(row) {
    const given = delegations[row.email_id];
    const box = h("div", { class: "section review-delegate" }, h("h3", {}, "Delegate this case"));
    if (given) {
      add(box,
        h("div", { class: "delegated" },
          icon("user"),
          h("span", {}, "Delegated to ", h("strong", {}, given.to), ` on ${new Date(given.at).toLocaleString()}`),
          h("button", { class: "btn small", type: "button", onclick: () => {
            delegations = takeBack(delegations, row.email_id);
            writeDelegations(delegations);
            announce(`Took ${row.email_id} back.`);
            renderList();
            pane.renderDetail();
          } }, "Take back")));
    } else {
      const name = h("input", { name: "person", class: "search", placeholder: "Name of the person to handle this", "aria-label": "Person to delegate this case to", autocomplete: "off", maxlength: "80" });
      const label = h("span", {}, "Send");
      const send = h("button", { class: "btn", type: "submit", disabled: true }, icon("send"), label);
      name.addEventListener("input", () => {
        const who = name.value.trim();
        send.disabled = !who;
        label.textContent = who ? `Send to ${who}` : "Send";
      });
      add(box,
        h("form", { class: "delegate-form", onsubmit: (event) => {
          event.preventDefault();
          const next = delegate(delegations, row.email_id, name.value);
          if (next === delegations) return;
          delegations = next;
          if (!writeDelegations(delegations)) announce("Could not save in this browser.");
          else announce(`Delegated ${row.email_id} to ${delegations[row.email_id].to}.`);
          renderList();
          pane.renderDetail();
        } }, name, send));
    }
    add(box, h("small", { class: "muted" }, "Demo only: nothing is emailed. The hand-over is kept in this browser."));
    return box;
  }

  function detailHeader(row) {
    return [
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
    return [
      banner ? h("div", { class: `banner ${banner.kind}` }, icon(banner.icon), banner.text) : null,
      isFailed(row) ? h("p", {}, retryButton(row, { api, ctx })) : null,
      h("p", {}, otherTabLink("parsing", row, "See how it was parsed")),
      buildDelegate(row),
      buildForm(row, kase),
      emailAndDocuments(kase, api),
    ];
  }

  function emptyDetail() {
    const failed = reviewRows().filter(isFailed).length;
    return h("div", { class: "empty" },
      "Select a case to review and correct the fields.",
      failed ? h("p", { class: "muted", style: "margin-top:8px" }, `${failed} of these failed on the model API, often a rate limit or an exhausted quota, not because of the documents. Retry them once the quota is back.`) : null);
  }

  renderList();
  pane.renderDetail();

  return {
    setId: pane.setId,
    refresh() {
      saved = readSaved();
      delegations = readDelegations();
      renderList();
      pane.refresh();
    },
    move: pane.move,
    focusSearch: pane.focusSearch,
  };
}
