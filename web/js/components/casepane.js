import { add, h, clear, announce } from "../util/dom.js";
import { icon } from "../util/icons.js";
import { routeHash } from "../router.js";
import { documentsView } from "./fields.js";

// What Parsing and Review have in common: a list of emails on the left, one email's case on
// the right, and the same original email and documents underneath. Each view keeps only what
// is its own (Parsing its filters and field table, Review its queue rules, corrections and
// delegation).

export function fold(title, content, open = false) {
  return h("details", { class: "fold", open: open ? "" : null }, h("summary", {}, title), h("div", { class: "fold-body" }, content));
}

/** The original email and its documents, folded, as both tabs show them. */
export function emailAndDocuments(kase, api) {
  const docs = documentsView(kase, api);
  return h(
    "div",
    { class: "section" },
    h("h3", {}, "Original email and documents"),
    fold("Email body", h("pre", { class: "doc" }, kase.email.body || ""), true),
    docs ? fold("Documents", docs) : null,
  );
}

// What the last retry of each email said, so a failed-again note survives the list redrawing.
const retryNotes = new Map();

/**
 * Retry just this one email (not every failed one), with the outcome said in place.
 * Returns a small wrapper holding the button and the note beside it.
 */
export function retryButton(row, { api, ctx }, { label = "Retry this email", small = false } = {}) {
  const button = h("button", { class: `btn${small ? " small" : ""}`, type: "button", title: `Run ${row.email_id} again` }, icon("refresh"), label);
  const note = h("span", { class: "muted retry-note", title: retryNotes.get(row.email_id) ?? null }, retryNotes.get(row.email_id) ?? "");
  button.addEventListener("click", async (event) => {
    event.stopPropagation();
    button.disabled = true;
    button.lastChild.textContent = "Retrying…";
    note.textContent = "";
    try {
      const result = await api.retry(row.email_id, ctx.getReport().scope);
      if (result.failed) retryNotes.set(row.email_id, "Failed again on the model API, often a rate limit or an exhausted quota.");
      else retryNotes.delete(row.email_id);
      announce(result.failed ? "It failed again on the model API." : "Retried.");
      await ctx.onRetried(); // redraws with the new result
    } catch (err) {
      announce(err.message);
      retryNotes.set(row.email_id, err.message);
      note.textContent = err.message;
      note.title = err.message;
      button.disabled = false;
      button.lastChild.textContent = label;
    }
  });
  return h("span", { class: "retry" }, button, note);
}

/** A link to the same email in the other tab. */
export function otherTabLink(tab, row, label) {
  return h("a", { class: "btn small", href: routeHash(tab, row.email_id) }, label);
}

/** One selectable row in the list. `tab` decides where it goes and what its element ID is. */
export function rowButton(tab, row, selectedId, ...children) {
  return h(
    "button",
    {
      class: "row", role: "option", type: "button", id: `${tab}-row-${row.email_id}`,
      "aria-selected": String(row.email_id === selectedId),
      onclick: () => { location.hash = routeHash(tab, row.email_id); },
    },
    ...children,
  );
}

/**
 * Lay out the two panes and run the selection: which email is open, loading its case, keeping
 * the list highlight in step, and j / k movement.
 *
 * opts: { tab, ctx, top: [nodes above the list], search: the search input,
 *         labels: { list, listbox, detail, back, select, missing(id) },
 *         paneClass, rows(): the emails j / k walks through, emptyDetail(): node,
 *         header(row): nodes, sections(row, kase): nodes }
 */
export function mountCasePane(root, opts) {
  const { tab, ctx, labels } = opts;
  let selectedId = null;
  let token = 0;

  const listEl = h("div", { class: "list-scroll", role: "listbox", "aria-label": labels.listbox, tabindex: "0" });
  const detailEl = h("section", { class: "pane-detail", "aria-label": labels.detail });
  const panes = h(
    "div",
    { class: `panes${opts.paneClass ? ` ${opts.paneClass}` : ""}` },
    h("section", { class: "pane-list", "aria-label": labels.list }, ...opts.top, listEl),
    detailEl,
  );
  clear(root).append(panes);

  const backButton = () => h("a", { class: "btn small back", href: routeHash(tab) }, icon("back"), labels.back);

  function markSelected() {
    for (const el of listEl.querySelectorAll('[role="option"]')) el.setAttribute("aria-selected", String(el.id === `${tab}-row-${selectedId}`));
    document.getElementById(`${tab}-row-${selectedId}`)?.scrollIntoView({ block: "nearest" });
  }

  async function renderDetail() {
    const mine = ++token;
    clear(detailEl);
    panes.classList.toggle("has-selection", Boolean(selectedId));
    if (!selectedId) {
      detailEl.append(opts.emptyDetail ? opts.emptyDetail() : h("div", { class: "empty" }, labels.select));
      return;
    }
    const row = (ctx.getReport()?.emails ?? []).find((r) => r.email_id === selectedId);
    if (!row) {
      detailEl.append(backButton(), h("div", { class: "empty" }, labels.missing(selectedId)));
      return;
    }
    const body = h("div", {}, h("div", { class: "skeleton" }));
    detailEl.append(backButton(), ...opts.header(row), body);
    try {
      const kase = await ctx.api.caseFor(selectedId, ctx.getReport().scope);
      if (mine !== token) return;
      add(clear(body), opts.sections(row, kase));
    } catch (err) {
      if (mine !== token) return;
      clear(body).append(h("div", { class: "banner review" }, icon("alert"), err.message));
    }
  }

  return {
    listEl,
    renderDetail,
    markSelected,
    selectedId: () => selectedId,
    setId(id) {
      selectedId = id;
      markSelected();
      renderDetail();
    },
    /** After the view has redrawn its list. */
    refresh() {
      markSelected();
      renderDetail();
    },
    /** j / k: move to the next or previous email in the list. */
    move(delta) {
      const list = opts.rows();
      if (!list.length) return;
      const at = list.findIndex((r) => r.email_id === selectedId);
      const next = list[Math.min(list.length - 1, Math.max(0, at === -1 ? 0 : at + delta))];
      location.hash = routeHash(tab, next.email_id);
    },
    focusSearch() { opts.search.focus(); },
  };
}
