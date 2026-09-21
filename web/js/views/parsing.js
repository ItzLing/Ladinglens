import { add, h, clear, announce } from "../util/dom.js";
import { icon } from "../util/icons.js";
import { CATEGORY_ORDER, categoryLabel, formatConfidence } from "../util/format.js";
import { caseBanner, filterRows, groupCounts, isFailed, tabCounts } from "../store.js";
import { routeHash } from "../router.js";
import { labelChip, statusChipEl } from "../components/chips.js";
import { documentsView, fieldTable } from "../components/fields.js";

const excerpt = (body) => {
  const text = String(body ?? "").replace(/\s+/g, " ").trim();
  return text.length > 220 ? `${text.slice(0, 220)}…` : text || "No text in this email.";
};

/**
 * The Parsing tab: a list of emails on the left, what the system found on the right.
 * It only reads: nothing here changes a verdict.
 *
 * ctx: { api, getReport(), view: {tab, group, q}, onRetried() }
 */
export function mountParsing(root, ctx) {
  const { api, view } = ctx;
  let selectedId = null;
  let token = 0;

  const tabsEl = h("div", { class: "tabs", role: "tablist", "aria-label": "Which emails" });
  const groupsEl = h("div", { class: "groups", role: "group", "aria-label": "Filter by label" });
  const search = h("input", {
    class: "search", type: "search", placeholder: "Search subject, sender or ID", "aria-label": "Search emails", value: view.q,
    oninput: (e) => { view.q = e.target.value; renderList(); },
  });
  const listEl = h("div", { class: "list-scroll", role: "listbox", "aria-label": "Emails", tabindex: "0" });
  const detailEl = h("section", { class: "pane-detail", "aria-label": "Email detail" });
  const panes = h(
    "div",
    { class: "panes" },
    h("section", { class: "pane-list", "aria-label": "Email list" }, tabsEl, h("div", { class: "filters" }, groupsEl, search), listEl),
    detailEl,
  );
  clear(root).append(panes);

  const rows = () => ctx.getReport()?.emails ?? [];
  const visible = () => filterRows(rows(), view);

  function setView(patch) {
    Object.assign(view, patch);
    renderList();
  }

  function renderTabs() {
    const counts = tabCounts(rows(), { group: view.group, q: view.q });
    clear(tabsEl).append(
      ...[["attention", "Need attention"], ["all", "All emails"]].map(([key, label]) =>
        h("button", { class: "tab", role: "tab", type: "button", "aria-selected": String(view.tab === key), onclick: () => setView({ tab: key }) },
          label, h("span", { class: "count" }, counts[key])),
      ),
    );
  }

  function renderGroups() {
    const counts = groupCounts(rows(), { tab: view.tab, q: view.q });
    const shown = CATEGORY_ORDER.filter((c) => counts[c] || view.group === c);
    clear(groupsEl).append(
      ...shown.map((c) =>
        h("button", { class: "group", type: "button", "aria-pressed": String(view.group === c), onclick: () => setView({ group: view.group === c ? null : c }) },
          categoryLabel(c), h("span", { class: "n" }, counts[c] ?? 0)),
      ),
    );
  }

  function renderRows() {
    const list = visible();
    clear(listEl);
    if (!list.length) {
      const filtered = view.group || view.q;
      listEl.append(
        h("div", { class: "empty" },
          view.tab === "attention" && !filtered ? "Nothing needs attention." : "No emails match.",
          view.tab === "attention" ? h("p", {}, h("button", { class: "btn small", type: "button", onclick: () => setView({ tab: "all", group: null, q: "" }) }, "Show all emails")) : null),
      );
      return;
    }
    listEl.append(
      ...list.map((r) =>
        h("button", { class: "row", role: "option", type: "button", id: `row-${r.email_id}`, "aria-selected": String(r.email_id === selectedId), onclick: () => { location.hash = routeHash("parsing", r.email_id); } },
          h("div", { class: "id" }, r.email_id),
          h("div", { class: "subject" }, r.subject || "(no subject)"),
          h("div", { class: "meta" }, labelChip(r.category), statusChipEl(r)),
        ),
      ),
    );
  }

  function renderList() {
    renderTabs();
    renderGroups();
    renderRows();
  }

  function markSelected() {
    for (const el of listEl.querySelectorAll('[role="option"]')) el.setAttribute("aria-selected", String(el.id === `row-${selectedId}`));
    document.getElementById(`row-${selectedId}`)?.scrollIntoView({ block: "nearest" });
  }

  const backButton = () => h("a", { class: "btn small back", href: routeHash("parsing") }, icon("back"), "All emails");

  function header(row) {
    return [
      backButton(),
      h("div", { class: "case-head" }, labelChip(row.category), statusChipEl(row)),
      h("h2", { class: "case-title" }, row.subject || "(no subject)"),
      h("p", { class: "case-sub" }, `${row.email_id} · from ${row.from || "unknown sender"}`),
    ];
  }

  function fold(title, content, open = false) {
    return h("details", { class: "fold", open: open ? "" : null }, h("summary", {}, title), h("div", { class: "fold-body" }, content));
  }

  function sections(row, kase) {
    const record = kase.record;
    const banner = caseBanner(record, row.category);
    const isComparison = row.category === "BL_COMPARISON";
    const docs = documentsView(kase, api);
    const nodes = [
      h("div", { class: "kv" }, "Confidence score", h("strong", { title: "How sure the classifier is about this label" }, formatConfidence(row.confidence))),
      record.summary
        ? h("p", { class: "summary" }, record.summary)
        : h("p", { class: "summary muted" }, excerpt(kase.email.body)),
      h("div", { class: "kv" }, "Group",
        h("button", { class: "group", type: "button", "aria-pressed": String(view.group === row.category), title: "Show only this label in the list", onclick: () => setView({ group: view.group === row.category ? null : row.category }) }, categoryLabel(row.category))),
      h("hr", { class: "rule" }),
      banner ? h("div", { class: `banner ${banner.kind}`, role: banner.kind === "review" ? "status" : null }, icon(banner.icon), banner.text) : null,
    ];

    if (isFailed(row)) {
      nodes.push(h("p", {}, h("button", { class: "btn", type: "button", onclick: (e) => retry(row, e.currentTarget) }, icon("refresh"), "Retry this email")));
    }
    if (isComparison && !["processing_error", "missing_attachment", "unreadable", "low_confidence"].includes(record.review_reason)) {
      nodes.push(h("div", { class: "section" }, h("h3", {}, "Fields"), fieldTable(record)));
    } else if (!isComparison) {
      nodes.push(h("p", { class: "muted" }, "This email is not a document check, so there is nothing to compare."));
    }
    nodes.push(h("div", { class: "section" }, h("h3", {}, "Email context and detail"),
      fold("Email body", h("pre", { class: "doc" }, kase.email.body || ""), true),
      docs ? fold("Documents", docs) : null));
    return nodes;
  }

  async function retry(row, button) {
    button.disabled = true;
    try {
      const result = await api.retry(row.email_id, ctx.getReport().scope);
      announce(result.failed ? "It failed again on the model API." : "Retried.");
      await ctx.onRetried();
    } catch (err) {
      announce(err.message);
      button.disabled = false;
      button.after(h("span", { class: "muted", style: "margin-left:8px" }, err.message));
    }
  }

  async function renderDetail() {
    const mine = ++token;
    clear(detailEl);
    panes.classList.toggle("has-selection", Boolean(selectedId));
    if (!selectedId) {
      detailEl.append(h("div", { class: "empty" }, "Select an email to see what the system found."));
      return;
    }
    const row = rows().find((r) => r.email_id === selectedId);
    if (!row) {
      detailEl.append(backButton(), h("div", { class: "empty" }, `There is no result for ${selectedId}.`));
      return;
    }
    const body = h("div", {}, h("div", { class: "skeleton" }));
    detailEl.append(...header(row), body);
    try {
      const kase = await api.caseFor(selectedId, ctx.getReport().scope);
      if (mine !== token) return;
      add(clear(body), sections(row, kase));
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
      renderList();
      markSelected();
      renderDetail();
    },
    /** j / k: move to the next or previous email in the list. */
    move(delta) {
      const list = visible();
      if (!list.length) return;
      const at = list.findIndex((r) => r.email_id === selectedId);
      const next = list[Math.min(list.length - 1, Math.max(0, at === -1 ? 0 : at + delta))];
      location.hash = routeHash("parsing", next.email_id);
    },
    focusSearch() { search.focus(); },
  };
}
