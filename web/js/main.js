import { createApi } from "./api.js";
import { parseRoute } from "./router.js";
import { add, h, clear, announce } from "./util/dom.js";
import { icon } from "./util/icons.js";
import { renderRail } from "./components/rail.js";
import { mountRunbar } from "./components/runbar.js";
import { mountHome } from "./views/home.js";
import { mountParsing } from "./views/parsing.js";
import { mountData } from "./views/data.js";
import { mountSoon } from "./views/soon.js";

const railEl = document.getElementById("rail");
const topEl = document.getElementById("top");
const contentEl = document.getElementById("content");

const app = {
  api: null,
  report: null,
  route: parseRoute(location.hash),
  view: null, // the mounted view of the current tab
  // the Parsing filters survive switching tabs
  parsing: { tab: "attention", group: null, q: "" },
  runbar: null,
};

// ---- theme ----
const THEME_KEY = "ladinglens-theme";
const prefersDark = () => matchMedia("(prefers-color-scheme: dark)").matches;
function currentTheme() {
  return document.documentElement.dataset.theme ?? (prefersDark() ? "dark" : "light");
}
try { const saved = localStorage.getItem(THEME_KEY); if (saved) document.documentElement.dataset.theme = saved; } catch { /* storage may be blocked */ }
function toggleTheme() {
  const next = currentTheme() === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem(THEME_KEY, next); } catch { /* not persisted */ }
  drawRail();
}

// ---- shell ----
function drawRail() {
  renderRail(railEl, { tab: app.route.tab, dark: currentTheme() === "dark", onToggleTheme: toggleTheme });
}

const runHost = h("div", { class: "run" });

function drawHeader(version) {
  add(
    clear(topEl),
    h("h1", {}, "Ladinglens"),
    app.route.tab === "home" && version ? h("span", { class: "version" }, `v${version}`) : null,
    h("span", { class: "grow" }),
    runHost,
  );
}

const TITLES = { home: "Home", parsing: "Parsing", review: "Review", report: "Report", data: "Database" };

function mountTab() {
  const { tab, id } = app.route;
  document.title = `${TITLES[tab]} · Ladinglens`;
  drawRail();
  drawHeader(app.report?.version ?? app.version);

  const ctx = { api: app.api, getReport: () => app.report };
  if (tab === "home") app.view = mountHome(contentEl, ctx);
  else if (tab === "parsing") {
    app.view = mountParsing(contentEl, { ...ctx, view: app.parsing, onRetried: reload });
    app.view.setId(id);
  } else if (tab === "data") app.view = mountData(contentEl, ctx);
  else app.view = mountSoon(contentEl, { tab });
  app.runbar?.render();
}

let mountedTab = null;
function onRoute() {
  const previous = app.route;
  app.route = parseRoute(location.hash);
  // moving between emails inside Parsing keeps the list, its scroll and its search as they are
  if (app.route.tab === "parsing" && mountedTab === "parsing" && previous.tab === "parsing") {
    app.view.setId(app.route.id);
    return;
  }
  mountedTab = app.route.tab;
  mountTab();
}

async function reload() {
  try {
    app.report = await app.api.report();
    app.version = app.report.version ?? app.version;
  } catch (err) {
    showError(err);
    return;
  }
  app.runbar?.render();
  drawHeader(app.version);
  app.view?.refresh?.();
}

function showError(err) {
  clear(contentEl).append(
    h("div", { class: "page" },
      h("div", { class: "card" },
        h("h2", {}, "Could not load results"),
        h("p", { class: "secondary" }, err.message),
        h("p", {}, "Run the pipeline first (POST /run), or start the app with"),
        h("pre", {}, "uvicorn app.main:app"))),
  );
  announce("Could not load results.");
}

// ---- keyboard: j / k move through the list, / searches, g then h / p / d jumps ----
let goPending = false;
addEventListener("keydown", (e) => {
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName);
  if (typing) { if (e.key === "Escape") e.target.blur(); return; }
  if (goPending) {
    goPending = false;
    const target = { h: "#/", p: "#/parsing", d: "#/data" }[e.key];
    if (target) { location.hash = target; e.preventDefault(); }
    return;
  }
  if (e.key === "g") { goPending = true; return; }
  if (app.route.tab !== "parsing" || !app.view) return;
  if (e.key === "j") { app.view.move(1); e.preventDefault(); }
  else if (e.key === "k") { app.view.move(-1); e.preventDefault(); }
  else if (e.key === "/") { app.view.focusSearch(); e.preventDefault(); }
});

// ---- start ----
(async function boot() {
  drawRail();
  drawHeader(null);
  clear(contentEl).append(h("div", { class: "page muted" }, "Loading…"));
  app.api = await createApi();
  try {
    app.report = await app.api.report();
    app.version = app.report.version ?? null;
  } catch (err) {
    showError(err);
    return;
  }
  app.runbar = mountRunbar(runHost, { api: app.api, getReport: () => app.report, onDone: reload });
  addEventListener("hashchange", onRoute);
  onRoute();
})();
