import { add, h, clear } from "../util/dom.js";
import { icon } from "../util/icons.js";
import { categoryLabel, formatTime } from "../util/format.js";

const PAGE = 20;

const COLUMNS = {
  results: [
    ["Email", (d) => d.email_id],
    ["Scope", (d) => d.scope],
    ["Label", (d) => categoryLabel(d.record?.category)],
    ["Status", (d) => d.record?.status],
    ["Tries", (d) => d.attempts ?? ""],
    ["Updated", (d) => formatTime(d.updated_at)],
  ],
  runs: [
    ["Scope", (d) => d.scope],
    ["Started", (d) => formatTime(d.started_at)],
    ["Finished", (d) => formatTime(d.finished_at)],
    ["Limit", (d) => d.limit ?? "all"],
    ["Result", (d) => (d.counts ? Object.entries(d.counts).map(([k, v]) => `${v} ${k}`).join(", ") : "")],
    ["Version", (d) => d.version],
  ],
};

/** A read-only view of what the system has stored. Nothing here edits. */
export function mountData(root, { api }) {
  let status = null;
  let name = "results";
  let skip = 0;
  let emailId = "";

  const card = h("div", { class: "card" });
  const collections = h("div", { class: "collections" });
  const toolbar = h("div", { class: "toolbar" });
  const table = h("div", {});
  clear(root).append(h("div", { class: "page" }, card, h("h2", { style: "margin-bottom:12px" }, "Collections"), collections, toolbar, table));

  function renderCard() {
    clear(card);
    if (!status) return card.append(h("p", { class: "muted" }, "Loading…"));
    if (status.backend === "static") {
      return card.append(h("h2", {}, "Database"), h("p", { class: "secondary" }, "This is a read-only demo, so there is no database to show. Start the app to see what is stored."));
    }
    if (!status.configured) {
      return card.append(
        h("h2", {}, h("span", { class: "chip" }, "Files"), "MongoDB is not configured"),
        h("p", { class: "secondary" }, "Results are kept in files in the results folder. To also keep them in MongoDB, add these to .env and restart the app:"),
        h("pre", {}, "MONGODB_URI=mongodb+srv://user:password@cluster.example.mongodb.net\nMONGODB_DB=ladinglens"),
      );
    }
    const ok = status.connected;
    add(
      card,
      h("h2", {}, h("span", { class: `chip ${ok ? "ok" : "review"}` }, icon(ok ? "check" : "alert"), ok ? "Connected" : "Not connected"), "MongoDB"),
      h("p", { class: "secondary" }, `Database ${status.database} on ${status.server ?? "the configured server"}.`),
      ok ? null : h("p", {}, status.error ?? "The server could not be reached.", " The app keeps working from the files in the results folder."),
    );
  }

  function renderCollections() {
    clear(collections);
    for (const c of status?.collections ?? []) {
      collections.append(
        h("button", { class: "group", type: "button", "aria-pressed": String(c.name === name), onclick: () => { name = c.name; skip = 0; emailId = ""; renderCollections(); load(); } },
          c.name, h("span", { class: "n" }, c.count)),
      );
    }
  }

  function renderToolbar() {
    clear(toolbar);
    if (name !== "results") return;
    toolbar.append(
      h("input", {
        class: "search", style: "max-width:260px", type: "search", placeholder: "Filter by email ID", "aria-label": "Filter by email ID", value: emailId,
        onchange: (e) => { emailId = e.target.value.trim(); skip = 0; load(); },
      }),
    );
  }

  async function load() {
    renderToolbar();
    clear(table);
    if (!status?.collections?.length) return;
    let page;
    try {
      page = await api.dbDocs(name, { emailId, limit: PAGE, skip });
    } catch (err) {
      return table.append(h("div", { class: "banner review" }, icon("alert"), err.message));
    }
    const cols = COLUMNS[name] ?? [];
    if (!page.items.length) return table.append(h("div", { class: "empty" }, "Nothing stored here yet."));

    const rows = page.items.flatMap((doc, i) => {
      const detail = h("tr", { hidden: true }, h("td", { colspan: cols.length + 1 }, h("pre", { class: "json" }, JSON.stringify(doc, null, 2))));
      const button = h("button", { class: "btn small", type: "button", "aria-expanded": "false" }, "JSON");
      button.addEventListener("click", () => {
        const open = detail.hidden;
        detail.hidden = !open;
        button.setAttribute("aria-expanded", String(open));
      });
      return [h("tr", {}, ...cols.map(([, get]) => h("td", {}, get(doc) ?? "")), h("td", {}, button)), detail];
    });

    const from = skip + 1, to = skip + page.items.length;
    table.append(
      h("div", { class: "pager" },
        h("span", {}, `${from}–${to} of ${page.total}`),
        h("button", { class: "btn small", type: "button", disabled: skip === 0 ? "" : null, onclick: () => { skip = Math.max(0, skip - PAGE); load(); } }, "Previous"),
        h("button", { class: "btn small", type: "button", disabled: to >= page.total ? "" : null, onclick: () => { skip += PAGE; load(); } }, "Next"),
        page.source ? h("span", { class: "muted" }, `from ${page.source}`) : null),
      h("table", { class: "docs-table" },
        h("thead", {}, h("tr", {}, ...cols.map(([label]) => h("th", {}, label)), h("th", {}, ""))),
        h("tbody", {}, rows)),
    );
  }

  renderCard();
  api.dbStatus().then((s) => {
    status = s;
    if (!status.collections.some((c) => c.name === name)) name = status.collections[0]?.name ?? "results";
    renderCard();
    renderCollections();
    load();
  }).catch((err) => {
    clear(card).append(h("div", { class: "banner review" }, icon("alert"), err.message));
  });

  return { refresh() {} };
}
