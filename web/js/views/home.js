import { h, clear } from "../util/dom.js";
import { formatTime, plural } from "../util/format.js";
import { routeHash } from "../router.js";

const FEATURES = [
  { name: "OCR", text: "Reads scanned pages and reports how sure it is about every word." },
  { name: "LLM", text: "Classifies emails and maps differently labelled fields." },
];

const STEPS = [
  ["01", "Classify", "Sort inbox messages by intent."],
  ["02", "Extract", "Read SI and draft BL fields."],
  ["03", "Compare", "Flag mismatched shipment values."],
  ["04", "Review", "Escalate uncertain cases with evidence."],
];

const OUTCOMES = [
  ["Primary user", "Shipping operations team"],
  ["Business value", "Less manual checking, fewer BL corrections"],
  ["Decision rule", "Escalate when unsure; never guess"],
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
    h("h2", {}, "How it works"),
    h("p", { class: "secondary" }, "Business users see which emails need attention, which documents already match, and exactly what must be fixed before the draft Bill of Lading is finalized."),
    h("div", { class: "route", "aria-label": "Processing route" }, STEPS.map(([n, name, text]) => h("div", { class: "route-step" }, h("span", { class: "step-num" }, n), h("strong", {}, name), h("span", {}, text)))),
    h("div", { class: "outcomes", "aria-label": "Business outcomes" }, OUTCOMES.map(([label, text]) => h("div", { class: "outcome" }, h("span", {}, label), h("strong", {}, text)))),
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
