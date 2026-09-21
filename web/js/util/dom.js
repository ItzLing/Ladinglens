// Build DOM with text nodes only, never innerHTML, so nothing from the dataset can inject markup.

/** Append children, skipping null and false. Native append() would write the word "null". */
export function add(el, ...children) {
  for (const child of children.flat(Infinity)) {
    if (child == null || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

export function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props ?? {})) {
    if (value == null || value === false) continue;
    if (key === "class") el.className = value;
    else if (key.startsWith("on") && typeof value === "function") el.addEventListener(key.slice(2).toLowerCase(), value);
    else if (value === true) el.setAttribute(key, "");
    else el.setAttribute(key, value);
  }
  return add(el, children);
}

export function clear(el) {
  el.replaceChildren();
  return el;
}

/** Say something to screen readers without moving focus. */
export function announce(message) {
  const live = document.getElementById("live");
  if (live) live.textContent = message;
}
