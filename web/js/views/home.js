import { h, clear } from "../util/dom.js";
import { CATEGORY_ORDER, categoryLabel, formatConfidence, formatTime } from "../util/format.js";
import { PRIORITY_LABEL, needsPerson, nextStep, priorityOf, sortByPriority } from "../store.js";
import { routeHash } from "../router.js";
import { labelChip, statusChipEl } from "../components/chips.js";

const STEPS = [
  ["01", "Classify", "Sort inbox messages by intent."],
  ["02", "Extract", "Read SI and draft BL fields."],
  ["03", "Compare", "Flag mismatched shipment values."],
  ["04", "Review", "Escalate uncertain cases with evidence."],
];

const STATUS_OPTIONS = [
  ["", "All results"],
  ["MISMATCH", "Mismatch"],
  ["NEEDS_REVIEW", "Needs review"],
  ["OK", "No mismatch"],
];

function statCards(summary = {}) {
  return [
    ["Emails processed", summary.total ?? 0, "whole inbox"],
    ["Comparison requests", summary.categories?.BL_COMPARISON ?? 0, "routed to document checking"],
    ["Mismatches found", summary.defects ?? 0, "fields needing correction"],
    ["Human review", summary.statuses?.NEEDS_REVIEW ?? 0, "uncertain or failed cases"],
    ["Clean checks", summary.statuses?.OK ?? 0, "no mismatch detected"],
  ];
}

function hasEmailData(report) {
  return (report?.emails ?? []).length > 0;
}

function statusMatches(row, status) {
  if (!status) return true;
  return row.status === status;
}

function categoryMatches(row, category) {
  if (!category) return true;
  return row.category === category;
}

function queryMatches(row, query) {
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  return [
    row.email_id,
    row.subject,
    row.from,
    row.summary,
    row.defect_fields?.join(" "),
  ].some((value) => String(value ?? "").toLowerCase().includes(needle));
}

function filteredRows(rows, filters) {
  return sortByPriority(rows.filter((row) =>
    categoryMatches(row, filters.category) &&
    statusMatches(row, filters.status) &&
    queryMatches(row, filters.q)));
}

function categoryBars(summary = {}) {
  const categories = summary.categories ?? {};
  const total = Math.max(1, Object.values(categories).reduce((sum, value) => sum + Number(value ?? 0), 0));
  const rows = CATEGORY_ORDER.filter((category) => categories[category] || categories[category] === 0);
  if (!rows.length) return h("div", { class: "home-empty" }, "No category data yet.");
  return h("div", { class: "mix-bars" },
    rows.map((category) => {
      const value = categories[category] ?? 0;
      return h("div", { class: "mix-row" },
        h("div", { class: "mix-label" }, categoryLabel(category)),
        h("div", { class: "mix-track" }, h("span", { style: `width:${Math.round((value / total) * 100)}%` })),
        h("div", { class: "mix-value" }, value));
    }));
}

function queueRows(rows) {
  if (!rows.length) {
    return h("tbody", {}, h("tr", {}, h("td", { colspan: "8", class: "home-table-empty" }, "No emails match these filters.")));
  }
  return h("tbody", {},
    rows.slice(0, 12).map((row) => {
      const target = needsPerson(row) ? "review" : "parsing";
      return (
      h("tr", {},
        h("td", {}, h("span", { class: `priority ${priorityOf(row)}` }, PRIORITY_LABEL[priorityOf(row)])),
        h("td", {}, h("a", { class: "mono", href: routeHash(target, row.email_id) }, row.email_id)),
        h("td", { class: "home-subject" }, h("a", { href: routeHash(target, row.email_id) }, row.subject || "(no subject)")),
        h("td", {}, labelChip(row.category)),
        h("td", {}, statusChipEl(row) ?? h("span", { class: "chip ok" }, "OK")),
        h("td", {}, formatConfidence(row.confidence)),
        h("td", { class: "home-next", title: nextStep(row) }, nextStep(row)),
        h("td", { class: "home-flagged" }, (row.defect_fields ?? []).join(", ") || "-"),
      ));
    }),
  );
}

function option(value, label, selected) {
  return h("option", { value, selected: selected ? true : null }, label);
}

export function mountHome(root, { getReport, api }) {
  const filters = { q: "", category: "", status: "" };
  const shell = h("div", { class: "page wide home-dashboard" });
  clear(root).append(shell);

  function setFilter(patch) {
    Object.assign(filters, patch);
    render();
  }

  function renderHero(report) {
    const summary = report?.summary ?? {};
    return h("section", { class: "home-hero-grid" },
      h("div", { class: "home-hero card" },
        h("p", { class: "home-eyebrow" }, "Shipping operations console"),
        h("h2", {}, "Find the emails that matter, then prove every document difference."),
        h("p", { class: "home-copy" }, "Every message is classified first. Only document comparison requests move into field extraction, mismatch checking, and human review when the system cannot decide confidently."),
        h("div", { class: "home-steps" }, STEPS.map(([num, title, text]) =>
          h("div", { class: "home-step" }, h("span", {}, num), h("strong", {}, title), h("p", {}, text)))),
      ),
      h("aside", { class: "home-stats" }, statCards(summary).map(([label, value, note]) =>
        h("div", { class: "home-stat card" }, h("span", {}, label), h("strong", {}, value), h("p", {}, note)))),
    );
  }

  function renderMix(report) {
    const generated = formatTime(report?.generated_at);
    return h("aside", { class: "home-mix card" },
      h("div", { class: "home-card-head" },
        h("div", {}, h("h2", {}, "Inbox mix"), h("p", {}, "Classification count by email category."))),
      categoryBars(report?.summary),
      hasEmailData(report)
        ? h("p", { class: "home-note" }, api.mode === "static" ? `Demo data generated ${generated}.` : `Run generated ${generated}.`)
        : h("div", { class: "home-warn" }, "This report currently has no emails. Run the pipeline, rebuild web/report.json, then refresh this page to see the review queue."));
  }

  function renderToolbar(report) {
    const categories = report?.summary?.categories ?? {};
    const statusCounts = report?.summary?.statuses ?? {};
    const total = report?.summary?.total ?? 0;
    return h("div", { class: "home-tools" },
      h("input", {
        class: "search",
        type: "search",
        placeholder: "Search subject, sender, email ID or flagged field",
        value: filters.q,
        "aria-label": "Search dashboard emails",
        oninput: (event) => setFilter({ q: event.target.value }),
      }),
      h("select", {
        class: "select",
        value: filters.category,
        "aria-label": "Filter by category",
        onchange: (event) => setFilter({ category: event.target.value }),
      },
        option("", "All categories", filters.category === ""),
        CATEGORY_ORDER.map((category) => option(category, `${categoryLabel(category)} (${categories[category] ?? 0})`, filters.category === category))),
      h("select", {
        class: "select",
        value: filters.status,
        "aria-label": "Filter by result",
        onchange: (event) => setFilter({ status: event.target.value }),
      },
        STATUS_OPTIONS.map(([value, label]) => option(value, value ? `${label} (${statusCounts[value] ?? 0})` : `${label} (${total})`, filters.status === value))),
    );
  }

  function renderQuickFilters(report) {
    const summary = report?.summary ?? {};
    const buttons = [
      ["", "All", summary.total ?? 0],
      ["MISMATCH", "Mismatch", summary.statuses?.MISMATCH ?? 0],
      ["NEEDS_REVIEW", "Needs review", summary.statuses?.NEEDS_REVIEW ?? 0],
      ["OK", "No mismatch", summary.statuses?.OK ?? 0],
    ];
    return h("div", { class: "home-pills" }, buttons.map(([status, label, count]) =>
      h("button", { class: "group", type: "button", "aria-pressed": String(filters.status === status), onclick: () => setFilter({ status }) },
        `${label} `, h("span", { class: "n" }, count))));
  }

  function renderQueue(report) {
    const rows = filteredRows(report?.emails ?? [], filters);
    const total = report?.emails?.length ?? 0;
    return h("section", { class: "home-queue card" },
      h("div", { class: "home-card-head" },
        h("div", {}, h("h2", {}, "Review queue"), h("p", {}, "Prioritised by what a person must do: fix mismatches first, then review uncertain cases, then archive clean checks.")),
        h("span", { class: "home-count" }, `${rows.length} of ${total} emails`)),
      h("div", { class: "home-table-wrap" },
        h("table", { class: "home-table" },
          h("thead", {}, h("tr", {},
            h("th", {}, "Priority"),
            h("th", {}, "Email"),
            h("th", {}, "Subject"),
            h("th", {}, "Category"),
            h("th", {}, "Result"),
            h("th", {}, "Confidence"),
            h("th", {}, "Next step"),
            h("th", {}, "Fields flagged"))),
          queueRows(rows))));
  }

  function render() {
    const report = getReport();
    clear(shell).append(
      renderHero(report),
      h("section", { class: "home-lower" },
        renderMix(report),
        h("div", { class: "home-work" },
          renderToolbar(report),
          renderQuickFilters(report),
          renderQueue(report))),
    );
  }

  render();
  return { refresh: render };
}
