import { h, clear } from "../util/dom.js";
import { formatTime, plural } from "../util/format.js";
import { routeHash } from "../router.js";

const FEATURES = [
  { name: "OCR", text: "Reads scanned pages and reports how sure it is about every word." },
  { name: "LLM", text: "Classifies emails and maps differently labelled fields." },
];

export function mountHome(root, { getReport, api }) {
  const attention = h("p", { class: "attention" });

  const page = h(
    "div",
    { class: "page" },
    h("hr", { class: "rule", style: "margin-top:0" }),
    h("h2", {}, "Features"),
    h("div", { class: "features" }, FEATURES.map((f) => h("div", { class: "feature" }, h("strong", {}, f.name), h("span", {}, f.text)))),
    h("hr", { class: "rule" }),
    h(
      "div",
      { class: "tagline" },
      h("p", {}, "Quick, reliable email verification."),
      h("p", {}, "Classify, extract data & compare."),
      h("p", {}, "All around help, every day, every time."),
    ),
    attention,
  );
  clear(root).append(page);

  function render() {
    const report = getReport();
    clear(attention);
    if (!report) return;
    const n = report.summary?.needs_attention ?? 0;
    if (api.mode === "static") {
      attention.append(`Demo data, generated ${formatTime(report.generated_at)}. `, h("a", { href: routeHash("parsing") }, "Open the list"));
    } else if (n > 0) {
      attention.append(h("strong", {}, plural(n, "email needs", "emails need")), " attention. ", h("a", { href: routeHash("parsing") }, "Open the list"));
    } else {
      attention.append("Nothing needs attention. ", h("a", { href: routeHash("parsing") }, "Open the list"));
    }
  }
  render();
  return { refresh: render };
}
