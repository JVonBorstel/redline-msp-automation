// Shared helpers. Every piece of data is put on the page with textContent (never innerHTML), so ticket text,
// including the hostile ones, can only ever be shown, not run.

export function el(tag, attrs, ...children) {
  const node = document.createElement(tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") node.className = v;
      else if (k === "text") node.textContent = v;
      else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
      else node.setAttribute(k, v === true ? "" : String(v));
    }
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}

export function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
  return node;
}

export function pill(text, kind) {
  return el("span", { class: "pill" + (kind ? " " + kind : "") }, text);
}

// Invisible and direction-control characters, shown as visible badges so a reader can see what a model would get.
const HIDDEN = {
  "­": "SHY", "​": "ZWSP", "‌": "ZWNJ", "‍": "ZWJ", "‎": "LRM", "‏": "RLM",
  "⁠": "WJ", "⁡": "FA", "⁢": "IT", "⁣": "IS", "⁤": "IP", "﻿": "BOM",
  "‪": "LRE", "‫": "RLE", "‬": "PDF", "‭": "LRO", "‮": "RLO",
  "⁦": "LRI", "⁧": "RLI", "⁨": "FSI", "⁩": "PDI",
};
const HIDDEN_RE = new RegExp("[" + Object.keys(HIDDEN).join("") + "]", "g");

export function countHidden(text) {
  return (String(text).match(HIDDEN_RE) || []).length;
}

export function revealed(text, reveal) {
  const frag = document.createDocumentFragment();
  const s = String(text);
  if (!reveal) { frag.append(document.createTextNode(s)); return frag; }
  let last = 0;
  for (const m of s.matchAll(HIDDEN_RE)) {
    if (m.index > last) frag.append(document.createTextNode(s.slice(last, m.index)));
    const code = "U+" + m[0].codePointAt(0).toString(16).toUpperCase().padStart(4, "0");
    frag.append(el("abbr", { class: "zw", title: "hidden character " + code }, HIDDEN[m[0]]));
    last = m.index + m[0].length;
  }
  if (last < s.length) frag.append(document.createTextNode(s.slice(last)));
  return frag;
}

// Loads one generated data file into `region`, with loading, error (and retry) states. Resolves to the JSON.
export async function loadData(url, region) {
  region.setAttribute("aria-busy", "true");
  clear(region).append(el("p", { class: "state", role: "status" }, "Loading the data the build generated…"));
  try {
    const res = await fetch(url, { cache: "no-cache" });
    if (!res.ok) throw new Error("HTTP " + res.status);
    const data = await res.json();
    region.removeAttribute("aria-busy");
    clear(region);
    return data;
  } catch (err) {
    region.removeAttribute("aria-busy");
    document.body.dataset.error = String(err && err.message ? err.message : err);
    const retry = el("button", { class: "btn secondary", type: "button" }, "Try again");
    retry.addEventListener("click", () => window.location.reload());
    clear(region).append(el("div", { class: "state error", role: "alert" },
      el("p", null, el("strong", null, "This demo could not load its data. "),
        "The file ", el("code", null, url), " did not load (" + (err && err.message ? err.message : err) + "). ",
        "If you opened the page straight from disk, serve the folder over HTTP instead."),
      retry));
    throw err;
  }
}

export function markReady() {
  document.body.dataset.ready = "1";
}

export function short(hash, n = 10) {
  return hash ? String(hash).slice(0, n) + "…" : "";
}

export function hashParams() {
  const out = {};
  const h = window.location.hash.replace(/^#/, "");
  for (const part of h.split("&")) {
    if (!part) continue;
    const [k, v] = part.split("=");
    out[decodeURIComponent(k)] = v === undefined ? "" : decodeURIComponent(v);
  }
  return out;
}

export function setHash(params) {
  const s = Object.entries(params).filter(([, v]) => v !== null && v !== undefined && v !== "")
    .map(([k, v]) => encodeURIComponent(k) + "=" + encodeURIComponent(v)).join("&");
  history.replaceState(null, "", s ? "#" + s : window.location.pathname + window.location.search);
}

// Theme switch: auto -> light -> dark -> auto. Saving can fail (private mode); the switch still works for the visit.
export function initTheme() {
  const btn = document.getElementById("theme-btn");
  if (!btn) return;
  const root = document.documentElement;
  const label = () => {
    const t = root.getAttribute("data-theme") || "auto";
    btn.textContent = "Theme: " + t;
    btn.setAttribute("aria-label", "Colour theme: " + t + ". Activate to change.");
  };
  label();
  btn.addEventListener("click", () => {
    const now = root.getAttribute("data-theme") || "auto";
    const next = now === "auto" ? "light" : now === "light" ? "dark" : "auto";
    if (next === "auto") root.removeAttribute("data-theme"); else root.setAttribute("data-theme", next);
    try {
      if (next === "auto") window.localStorage.removeItem("theme"); else window.localStorage.setItem("theme", next);
    } catch (e) { /* storage blocked: keep the choice for this page view only */ }
    label();
  });
}

export function prettyJSON(value) {
  return JSON.stringify(value, null, 2);
}
