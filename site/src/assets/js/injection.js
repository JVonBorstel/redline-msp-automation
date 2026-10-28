import { el, clear, pill, revealed, countHidden, loadData, markReady, initTheme } from "./common.js";

initTheme();
const heroRoot = document.getElementById("hero-root");
const corpusRoot = document.getElementById("corpus-root");
let reveal = true;

function renderHero(t, probe) {
  clear(heroRoot);
  const tr = t.triage;
  const box = el("input", { type: "checkbox", id: "reveal-hero", checked: reveal });
  box.addEventListener("change", () => { reveal = box.checked; renderHero(t, probe); });
  heroRoot.append(
    el("section", { class: "card" },
      el("h3", null, "Ticket ", el("code", null, t.id), " as it arrived"),
      el("p", { class: "small muted" }, t.client + " · from " + t.requester + " · looks like a password reset"),
      el("pre", { class: "untrusted" }, revealed("Subject: " + t.subject + "\n\n" + t.body, reveal)),
      el("label", { for: "reveal-hero", class: "small" }, box, " Show the " + countHidden(t.subject + t.body) + " hidden characters")),
    el("section", { class: "card" },
      el("h3", null, "What the tripwire reported"),
      el("p", { class: "banner bad" }, el("strong", null, "Flagged: "), "reported, not followed."),
      el("ul", null, tr.injection.reasons.map((r) => el("li", null, el("code", null, r.rule), ": ", revealed(r.evidence, reveal)))),
      el("dl", { class: "facts" },
        el("dt", null, "Queue"), el("dd", null, tr.queue, " ", pill("security", "bad")),
        el("dt", null, "Priority"), el("dd", null, tr.priority),
        el("dt", null, "Lever"), el("dd", null, tr.proposal ? tr.proposal.lever : "none: a flagged ticket never gets a lever"))),
    el("section", { class: "card" },
      el("h3", null, "The demo script's one-liner"),
      el("pre", null, probe.text),
      el("p", null, "Flagged: ", el("strong", null, String(probe.flagged)), " · rules: ", probe.rules.map((r) => el("code", null, r)).flatMap((n, i) => (i ? [", ", n] : [n])))));
}

const FILTERS = [
  ["all", "All", () => true],
  ["injection", "Injection", (c) => c.kind === "injection"],
  ["benign", "Benign", (c) => c.kind === "benign"],
  ["missed", "Missed", (c) => c.kind === "injection" && !c.flagged],
  ["false", "False alarms", (c) => c.kind === "benign" && c.flagged],
];

function renderCorpus(cases, filter) {
  clear(corpusRoot);
  const chips = el("div", { class: "chips", role: "group", "aria-label": "Filter the corpus" });
  for (const [key, label, fn] of FILTERS) {
    const n = cases.filter(fn).length;
    const b = el("button", { class: "chip", type: "button", "aria-pressed": String(key === filter) }, label + " (" + n + ")");
    b.addEventListener("click", () => renderCorpus(cases, key));
    chips.append(b);
  }
  corpusRoot.append(chips);
  const fn = FILTERS.find((f) => f[0] === filter)[2];
  const shown = cases.filter(fn);
  if (!shown.length) {
    corpusRoot.append(el("p", { class: "state", role: "status" }, filter === "missed"
      ? "No missed injections in this corpus. Remember it was written alongside the rules, so this is a consistency check, not a real-world detection rate."
      : filter === "false" ? "No false alarms in this corpus (same caveat: written alongside the rules)."
        : "No cases match this filter."));
    return;
  }
  corpusRoot.append(el("p", { class: "small muted", role: "status" }, "Showing " + shown.length + " of " + cases.length + " synthetic cases."));
  corpusRoot.append(el("div", { class: "table-wrap" }, el("table", null,
    el("caption", { class: "visually-hidden" }, "Injection corpus cases"),
    el("thead", null, el("tr", null, ["Case", "Kind", "Source", "Detector", "Text", "Why it is in the corpus"].map((h) => el("th", { scope: "col" }, h)))),
    el("tbody", null, shown.map((c) => el("tr", null,
      el("td", null, el("code", null, c.id)),
      el("td", null, c.kind),
      el("td", null, c.source),
      el("td", null, c.flagged ? pill("flagged", "bad") : pill("clean", "ok"), c.rules.length ? el("div", { class: "small mono" }, c.rules.join(", ")) : null),
      el("td", { class: "small" }, revealed(c.text, true)),
      el("td", { class: "small muted" }, c.note)))))));
}

(async function main() {
  let inj, tri;
  try {
    [inj, tri] = await Promise.all([loadData("data/injection.json", heroRoot), fetch("data/triage.json").then((r) => {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    })]);
  } catch (e) {
    if (!document.body.dataset.error) {
      document.body.dataset.error = String(e.message || e);
      heroRoot.append(el("div", { class: "state error", role: "alert" }, "This demo could not load data/triage.json (" + (e.message || e) + ")."));
    }
    clear(corpusRoot);
    return;
  }
  const t = tri.tickets.find((x) => x.id === "T-3129");
  if (t) renderHero(t, inj.probe); else heroRoot.append(el("p", { class: "state" }, "Ticket T-3129 is not in this build's fixtures."));
  renderCorpus(inj.cases, "all");
  markReady();
})();
