import { h, clear } from "../util/dom.js";
import { routeHash } from "../router.js";

const COPY = {
  review: {
    title: "Review",
    text: "This tab is still being designed. It will be where a person confirms or corrects what the system could not settle.",
  },
};

export function mountSoon(root, { tab }) {
  const copy = COPY[tab];
  clear(root).append(
    h(
      "div",
      { class: "page" },
      h("div", { class: "card" }, h("h2", {}, `${copy.title}: design in progress`), h("p", { class: "secondary" }, copy.text), h("p", {}, "Until then you can inspect any email in ", h("a", { href: routeHash("parsing") }, "Parsing"), ".")),
    ),
  );
  return { refresh() {} };
}
