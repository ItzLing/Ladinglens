import { h, clear } from "../util/dom.js";
import { icon } from "../util/icons.js";
import { routeHash } from "../router.js";

const ITEMS = [
  { tab: "home", label: "Home", icon: "logo", logo: true },
  { tab: "parsing", label: "Parsing", icon: "mail" },
  { tab: "review", label: "Review", icon: "book" },
  { tab: "report", label: "Report", icon: "chart" },
  { tab: "data", label: "Database", icon: "database" },
];

export function renderRail(nav, { tab, dark, onToggleTheme }) {
  clear(nav).append(
    ...ITEMS.map((item) =>
      h(
        "a",
        {
          class: `rail-link${item.logo ? " logo" : ""}`,
          href: routeHash(item.tab),
          "aria-label": item.label,
          "aria-current": item.tab === tab ? "page" : null,
        },
        icon(item.icon),
        h("span", { class: "rail-tip" }, item.label),
      ),
    ),
    h("span", { class: "spacer" }),
    h(
      "button",
      { class: "rail-link", type: "button", "aria-label": dark ? "Switch to light theme" : "Switch to dark theme", onclick: onToggleTheme },
      icon(dark ? "sun" : "moon"),
      h("span", { class: "rail-tip" }, dark ? "Light theme" : "Dark theme"),
    ),
  );
}
