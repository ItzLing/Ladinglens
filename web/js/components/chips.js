import { h } from "../util/dom.js";
import { icon } from "../util/icons.js";
import { categoryLabel } from "../util/format.js";
import { statusChip } from "../store.js";

export function statusChipEl(row) {
  const chip = statusChip(row);
  return chip ? h("span", { class: `chip ${chip.kind}` }, icon(chip.icon), chip.text) : null;
}

export function labelChip(category) {
  return h("span", { class: "chip label" }, categoryLabel(category));
}
