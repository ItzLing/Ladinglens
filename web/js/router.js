export const TABS = ["home", "parsing", "review", "report", "data"];

const PATH = { home: "", parsing: "parsing", review: "review", report: "report", data: "data" };

export function parseRoute(hash) {
  const parts = String(hash ?? "").replace(/^#\/?/, "").split("/").filter(Boolean);
  const tab = parts[0] === undefined ? "home" : TABS.find((t) => PATH[t] === parts[0]) ?? "home";
  const id = tab === "parsing" && parts[1] ? decodeURIComponent(parts[1]) : null;
  return { tab, id };
}

export function routeHash(tab, id = null) {
  const base = `#/${PATH[tab] ?? ""}`;
  return id ? `${base}/${encodeURIComponent(id)}` : base;
}
