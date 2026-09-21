import { h, clear } from "../util/dom.js";
import { CATEGORY_ORDER, categoryLabel, formatConfidence } from "../util/format.js";
import { caseBanner, filterRows, groupCounts, isFailed, needsPerson, tabCounts } from "../store.js";
import { labelChip, statusChipEl } from "../components/chips.js";
import { fieldTable } from "../components/fields.js";
import { emailAndDocuments, mountCasePane, otherTabLink, retryButton, rowButton } from "../components/casepane.js";
import { icon } from "../util/icons.js";

const excerpt = (body) => {
  const text = String(body ?? "").replace(/\s+/g, " ").trim();
  return text.length > 220 ? `${text.slice(0, 220)}…` : text || "No text in this email.";
};

/**
 * The Parsing tab: every email, and what the system found in it. It only reads: nothing
 * here changes a verdict. Cases that need a person can be opened in Review.
 *
 * ctx: { api, getReport(), view: {tab, group, q}, onRetried() }
 */
export function mountParsing(root, ctx) {
  const { api, view } = ctx;

  const tabsEl = h("div", { class: "tabs", role: "tablist", "aria-label": "Which emails" });
  const groupsEl = h("div", { class: "groups", role: "group", "aria-label": "Filter by label" });
  const search = h("input", {
    class: "search", type: "search", placeholder: "Search subject, sender or ID", "aria-label": "Search emails", value: view.q,
    oninput: (e) => { view.q = e.target.value; renderList(); },
  });

  const rows = () => ctx.getReport()?.emails ?? [];
  const visible = () => filterRows(rows(), view);

  const pane = mountCasePane(root, {
    tab: "parsing",
    ctx,
    top: [tabsEl, h("div", { class: "filters" }, groupsEl, search)],
    search,
    labels: { list: "Email list", listbox: "Emails", detail: "Email detail", back: "All emails", select: "Select an email to see what the system found.", missing: (id) => `There is no result for ${id}.` },
    rows: visible,
    header: (row) => [
      h("div", { class: "case-head" }, labelChip(row.category), statusChipEl(row)),
      h("h2", { class: "case-title" }, row.subject || "(no subject)"),
      h("p", { class: "case-sub" }, `${row.email_id} · from ${row.from || "unknown sender"}`),
    ],
    sections,
  });
  const listEl = pane.listEl;

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
        rowButton("parsing", r, pane.selectedId(),
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

  function sections(row, kase) {
    const record = kase.record;
    const banner = caseBanner(record, row.category);
    const isComparison = row.category === "BL_COMPARISON";
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

    if (isFailed(row)) nodes.push(h("p", {}, retryButton(row, { api, ctx })));
    if (needsPerson(row)) nodes.push(h("p", {}, otherTabLink("review", row, "Open in Review to correct or delegate")));
    if (isComparison && !["processing_error", "missing_attachment", "unreadable", "low_confidence"].includes(record.review_reason)) {
      nodes.push(h("div", { class: "section" }, h("h3", {}, "Fields"), fieldTable(record)));
    } else if (!isComparison) {
      nodes.push(h("p", { class: "muted" }, "This email is not a document check, so there is nothing to compare."));
    }
    nodes.push(emailAndDocuments(kase, api));
    return nodes;
  }

  renderList();
  pane.renderDetail();

  return {
    setId: pane.setId,
    refresh() {
      renderList();
      pane.refresh();
    },
    move: pane.move,
    focusSearch: pane.focusSearch,
  };
}
