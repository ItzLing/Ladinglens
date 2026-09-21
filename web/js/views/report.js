import { add, h, clear } from "../util/dom.js";
import { icon } from "../util/icons.js";
import { CATEGORY_ORDER, FIELDS, categoryLabel, formatTime, plural } from "../util/format.js";
import {
  PRIORITY_LABEL, STATUS_LABEL, escalationNote, nextStep, priorityOf, reportGroups, reportInsights, reportTiles, rowsToCsv, statusCounts, summaryText,
} from "../store.js";
import { routeHash } from "../router.js";
import { statusChipEl } from "../components/chips.js";

const PAGE = 25;
const STATUS_ORDER = ["MISMATCH", "NEEDS_REVIEW", "OK"];
const FIELD_LABEL = Object.fromEntries(FIELDS);

/**
 * The Report tab: the run in numbers, then every email, folded by label so the page stays short.
 * Each row opens the email in Parsing. It only reads.
 *
 * ctx: { getReport() }
 */
export function mountReport(root, ctx) {
  const filters = { status: "", q: "" };
  const open = new Set(); // labels the reader unfolded
  const shown = {}; // rows shown per label, grown by "Show more"

  const stamp = h("span", { class: "muted" });
  const tiles = h("div", { class: "tiles" });
  const banner = h("div", { class: "banner review", hidden: true });
  const bars = h("div", { class: "bars" });
  const count = h("span", { class: "muted count" });
  const list = h("div", { class: "folds" });

  const insights = h("div", { class: "insights" });
  const pills = h("div", { class: "groups", role: "group", "aria-label": "Filter by result" });
  const copyBtn = h("button", { class: "btn small", type: "button", onclick: copySummary }, "Copy summary");
  const csvBtn = h("button", { class: "btn small", type: "button", onclick: exportCsv }, "Export CSV");
  const search = h("input", {
    class: "search", type: "search", placeholder: "Search subject, sender or email ID", "aria-label": "Search emails",
    oninput: (e) => { filters.q = e.target.value; renderList(); },
  });

  clear(root).append(
    h(
      "div",
      { class: "page wide" },
      h("p", { class: "secondary" }, "Shipping Instruction vs. draft Bill of Lading discrepancy review. Every inbox email is classified; comparison requests have seven shipment fields extracted from both documents and diffed."),
      h("div", { class: "stamp" }, stamp, h("span", { class: "grow" }), copyBtn, csvBtn),
      tiles,
      banner,
      h("section", { class: "card" }, h("h2", {}, "Inbox mix"), h("p", { class: "secondary" }, "Classification count by email category. Only comparison requests continue to document checking."), insights, bars),
      h("h2", { class: "list-title" }, "Emails"),
      h("div", { class: "toolbar" }, search, count),
      pills,
      list,
    ),
  );

  function renderSummary(report) {
    const s = report.summary ?? {};
    stamp.textContent = report.generated_at ? `Run of ${formatTime(report.generated_at)}` : "";
    clear(tiles).append(
      ...reportTiles(s).map((t) =>
        h("div", { class: "tile" }, h("div", { class: "tile-label" }, t.label), h("div", { class: "tile-value" }, t.value), h("div", { class: "tile-note" }, t.note))),
    );

    clear(insights).append(
      ...reportInsights(s).map((i) =>
        h("div", { class: "insight" }, h("span", {}, i.label), h("strong", {}, i.value), h("small", {}, i.note))),
    );

    const note = escalationNote(s);
    banner.hidden = !note;
    clear(banner);
    if (note) add(banner, icon("alert"), note);

    const categories = s.categories ?? {};
    const max = Math.max(1, ...Object.values(categories));
    clear(bars).append(
      ...CATEGORY_ORDER.filter((c) => categories[c]).map((c) =>
        h(
          "div",
          { class: "bar-row" },
          h("span", { class: "bar-name" }, categoryLabel(c)),
          h("div", { class: "bar-track" }, h("div", { class: "bar-fill", style: `width:${((categories[c] / max) * 100).toFixed(1)}%` })),
          h("span", { class: "bar-val" }, categories[c]),
        )),
    );
  }

  const emailRow = (r) =>
    h(
      "a",
      { class: "rrow", href: routeHash("parsing", r.email_id) },
      h("span", { class: "id" }, r.email_id.replace("email_", "#")),
      h("span", { class: "subject" }, r.subject || "(no subject)", h("small", {}, nextStep(r))),
      h("span", { class: "result" }, h("span", { class: `priority ${priorityOf(r)}` }, PRIORITY_LABEL[priorityOf(r)]), statusChipEl(r)),
      h("span", { class: "flagged" }, (r.defect_fields ?? []).map((f) => FIELD_LABEL[f] ?? f).join(", ")),
    );

  function fold(group, filtering) {
    const { category, items, mismatches, reviews } = group;
    const limit = shown[category] ?? PAGE;
    const body = h("div", { class: "fold-body" }, items.slice(0, limit).map(emailRow));
    if (items.length > limit) {
      body.append(
        h("button", { class: "btn small more", type: "button", onclick: () => { shown[category] = limit + PAGE; renderList(); } },
          `Show ${Math.min(PAGE, items.length - limit)} more (${items.length - limit} left)`),
      );
    }
    const details = h(
      "details",
      { class: "fold", open: filtering || open.has(category) },
      h(
        "summary",
        {},
        h("span", { class: "fold-name" }, categoryLabel(category)),
        h("span", { class: "fold-n" }, plural(items.length, "email")),
        mismatches ? h("span", { class: "chip mismatch" }, icon("x"), plural(mismatches, "mismatch", "mismatches")) : null,
        reviews ? h("span", { class: "chip review" }, icon("alert"), `${reviews} to review`) : null,
      ),
      body,
    );
    // remember what the reader unfolded, unless a filter opened it for them
    details.addEventListener("toggle", () => {
      if (filtering) return;
      if (details.open) open.add(category);
      else open.delete(category);
    });
    return details;
  }

  function renderPills(rows) {
    const counts = statusCounts(rows, { q: filters.q });
    clear(pills).append(
      ...[["", "All"], ...STATUS_ORDER.map((k) => [k, STATUS_LABEL[k]])].map(([value, label]) =>
        h("button", { class: "group", type: "button", "aria-pressed": String(filters.status === value), onclick: () => { filters.status = value; renderList(); } },
          label, h("span", { class: "n" }, counts[value] ?? 0))),
    );
  }

  function visibleRows() {
    return reportGroups(ctx.getReport()?.emails ?? [], filters, CATEGORY_ORDER).flatMap((g) => g.items);
  }

  function flash(button, text) {
    const label = button.textContent;
    button.textContent = text;
    setTimeout(() => { button.textContent = label; }, 1400);
  }

  async function copySummary() {
    const text = summaryText(ctx.getReport());
    try {
      await navigator.clipboard.writeText(text);
      flash(copyBtn, "Copied");
    } catch {
      flash(copyBtn, "Copy not allowed");
    }
  }

  function exportCsv() {
    const url = URL.createObjectURL(new Blob([rowsToCsv(visibleRows())], { type: "text/csv;charset=utf-8" }));
    const link = h("a", { href: url, download: "ladinglens-report.csv" });
    document.body.append(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  function renderList() {
    const rows = ctx.getReport()?.emails ?? [];
    renderPills(rows);
    const groups = reportGroups(rows, filters, CATEGORY_ORDER);
    const filtering = Boolean(filters.status || filters.q.trim());
    const matching = groups.reduce((n, g) => n + g.items.length, 0);
    count.textContent = `${matching} of ${rows.length} emails`;
    clear(list);
    if (!groups.length) return list.append(h("div", { class: "empty" }, "No emails match these filters."));
    list.append(...groups.map((g) => fold(g, filtering)));
  }

  function render() {
    const report = ctx.getReport();
    if (!report) return;
    renderSummary(report);
    renderList();
  }
  render();
  return { refresh: render };
}
