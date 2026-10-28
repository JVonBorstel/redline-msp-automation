import { el, clear, pill, loadData, markReady, hashParams, setHash, initTheme, short, prettyJSON } from "./common.js";
import { verifyLines } from "./chain.js";

initTheme();
const queueRoot = document.getElementById("queue-root");
const chainRoot = document.getElementById("chain-root");
const afterRoot = document.getElementById("after-root");

let D = null;            // approvals.json
let byId = new Map();     // node id -> node
let current = "s";        // current node id
let pauseStep = 0;        // how many pause-switch steps have been replayed (approved end states only)
let edits = new Map();    // seq -> edited raw line (the visitor's tampering)
let seen = 0;             // records already shown (to highlight new ones)
let lastResponse = null;

function pathTo(id) {
  const out = [];
  for (let n = byId.get(id); n; n = n.parent ? byId.get(n.parent) : null) out.unshift(n);
  return out;
}

function originalLines() {
  const lines = pathTo(current).flatMap((n) => n.new_lines);
  const node = byId.get(current);
  if (node.pause) for (const s of node.pause.slice(0, pauseStep)) lines.push(...s.new_lines);
  return lines;
}

function headPin() {
  const node = byId.get(current);
  if (node.pause && pauseStep > 0) return node.pause[pauseStep - 1].verify.head;
  return node.verify.head;
}

function lines() {
  return originalLines().map((line, i) => (edits.has(i + 1) ? edits.get(i + 1) : line));
}

function denials(id) {
  return pathTo(id).filter((n) => n.action === "N" || n.action === "T").length;
}

function statusKind(s) {
  return s === "ok" || s === "executed" ? "ok" : s === "denied" || s === "failed" ? "bad" : s === "rejected" ? "warn" : "info";
}

// ---------------------------------------------------------------- queue column
function renderQueue() {
  const node = byId.get(current);
  const rows = node.queue;
  const priya = rows.find((r) => r.id === D.proposal_id);
  const others = rows.filter((r) => r.id !== D.proposal_id && r.status === "pending");
  clear(queueRoot);
  queueRoot.append(el("p", { class: "muted small" }, "Signed in (demo picker, synthetic) as ", el("strong", null, D.viewer),
    ". A lead sees only proposals for their own clients."));

  const dry = originalLines().map((l) => JSON.parse(l)).find((r) => r.mode === "dry-run" && r.lever === priya.lever && r.params.upn === priya.params.upn);
  const card = el("section", { class: "card proposal-card", "aria-labelledby": "priya-h" },
    el("h3", { id: "priya-h" }, el("code", null, priya.lever), " for ", priya.client, " ", pill(priya.id, "info"), " ", pill(priya.status, statusKind(priya.status))),
    el("dl", { class: "facts" },
      el("dt", null, "Person affected"), el("dd", null, priya.params.upn),
      el("dt", null, "What it means for her (L1)"), el("dd", null, D.lever.impact ? D.lever.impact.L1 : "no impact trace registered"),
      el("dt", null, "What will change (dry-run)"), el("dd", null, dry ? dry.result.changes.map((c) => el("div", { class: "mono small" }, c.op + " " + c.path)) : "no dry-run on record"),
      el("dt", null, "Undo"), el("dd", null, (D.lever.undo ? "undo lever: " + D.lever.undo : "no undo lever: manual undo") + " (" + D.lever.reversibility + ")"),
      el("dt", null, "From"), el("dd", null, priya.source + " " + priya.ref),
      el("dt", null, "Requested by"), el("dd", null, priya.requested_by),
      el("dt", null, "Why"), el("dd", null, priya.reason),
      priya.status !== "pending" ? [el("dt", null, "Decided by"), el("dd", null, priya.decided_by + " at " + priya.decided_at + " UTC"),
        el("dt", null, "Requester verification"), el("dd", null, priya.verification ? priya.verification.method + (priya.verification.ref ? " (" + priya.verification.ref + ")" : "") + " by " + priya.verification.by : "none recorded")] : null));

  if (!node.terminal) {
    const used = denials(current);
    const actions = el("div", { class: "actions", role: "group", "aria-label": "Decide this proposal" });
    for (const key of ["N", "T", "A", "J"]) {
      const a = D.actions[key];
      const child = byId.get(current + key);
      const kind = key === "A" ? "btn" : key === "J" ? "btn danger" : "btn secondary";
      const b = el("button", { class: kind, type: "button", disabled: !child }, a.label);
      b.addEventListener("click", () => act(key));
      actions.append(b);
    }
    card.append(actions);
    if (used >= D.max_denials) {
      card.append(el("p", { class: "muted small" }, "Refused attempts are precomputed up to " + D.max_denials + " in a row; approve, reject or start over."));
    }
  } else {
    card.append(el("div", { class: "btn-row" }, el("button", { class: "btn secondary", type: "button", onclick: reset }, "Start over")));
  }
  queueRoot.append(card);

  const resp = el("div", { id: "response", "aria-live": "polite", tabindex: "-1" });
  if (lastResponse) {
    const r = lastResponse;
    const ok = r.http_status === 303;
    resp.append(el("div", { class: "banner " + (ok ? "ok" : "bad") },
      el("strong", null, ok ? "HTTP 303, then the queue page says: " : "HTTP " + r.http_status + ": "), r.message),
      el("p", { class: "muted small" }, "The form the page posted: ", el("code", null, Object.entries(r.form).map(([k, v]) => k + "=" + v).join("&")),
        " (plus the CSRF token). There is no box for a phone number: only where the number on file came from is recorded."));
  }
  queueRoot.append(resp);

  if (others.length) {
    queueRoot.append(el("h3", null, "Also waiting (not part of this replay)"));
    for (const o of others) {
      queueRoot.append(el("div", { class: "card small" }, el("code", null, o.lever), " for ", o.params.upn || o.client, " · ", o.client, " · from ", o.source + " " + o.ref,
        el("div", { class: "muted" }, o.reason)));
    }
  }
}

function act(key) {
  const child = byId.get(current + key);
  if (!child) return;
  current = child.id;
  lastResponse = child.response;
  edits = new Map();
  pauseStep = 0;
  save();
  renderAll();
  const resp = document.getElementById("response"); // the clicked button is gone; keep keyboard users in place
  if (resp) resp.focus({ preventScroll: false });
}

function reset() {
  current = "s"; lastResponse = null; edits = new Map(); pauseStep = 0; seen = 0;
  save();
  renderAll();
}

function save() {
  setHash({ path: current === "s" ? "" : current, pause: pauseStep || "" });
}

// ---------------------------------------------------------------- chain column
async function renderChain() {
  const ls = lines();
  const verdict = await verifyLines(ls, headPin());
  clear(chainRoot);
  const vbox = el("div", { class: "banner " + (verdict.ok ? "ok" : "bad"), role: "status", "aria-live": "polite" },
    el("strong", null, "Verify chain: "), verdict.line,
    el("div", { class: "small" }, "Checked just now in your browser: SHA-256 over each record, each record's link to the one before, and the head pin."));
  const verifyBtn = el("button", { class: "btn secondary", type: "button" }, "Verify again");
  verifyBtn.addEventListener("click", () => renderChain());
  chainRoot.append(vbox, el("div", { class: "btn-row" }, verifyBtn));

  // tamper controls
  const original = originalLines();
  const tamper = el("details", { open: edits.size > 0 }, el("summary", null, "Try to tamper with the log"));
  const body = el("div", { class: "body" });
  const quickIdx = original.findIndex((l) => l.includes(D.tamper.find));
  const quick = el("button", { class: "btn danger", type: "button", disabled: quickIdx < 0 }, "Change one letter of who approved it (lead-lee → lead-leo)");
  quick.addEventListener("click", () => { edits.set(quickIdx + 1, original[quickIdx].replace(D.tamper.find, D.tamper.replace)); renderChain(); });
  const restore = el("button", { class: "btn secondary", type: "button", disabled: edits.size === 0 }, "Restore the original log");
  restore.addEventListener("click", () => { edits = new Map(); renderChain(); });
  body.append(el("p", { class: "small" }, "This is step 8 of the demo script: edit one record, then verify. The quick button needs an executed approval in the log."),
    el("div", { class: "btn-row" }, quick, restore));
  const sel = el("select", { id: "edit-seq" }, original.map((_, i) => el("option", { value: i + 1 }, "seq " + (i + 1))));
  const area = el("textarea", { id: "edit-text", spellcheck: "false", "aria-label": "Raw JSON of the chosen record" });
  const load = () => { const i = Number(sel.value); area.value = edits.get(i) ?? original[i - 1]; };
  sel.addEventListener("change", load);
  const saveBtn = el("button", { class: "btn secondary", type: "button" }, "Save my edit and verify");
  saveBtn.addEventListener("click", () => { const i = Number(sel.value); if (area.value !== original[i - 1]) edits.set(i, area.value); else edits.delete(i); renderChain(); });
  body.append(el("label", { for: "edit-seq", class: "small" }, "Or edit any record yourself: "), sel, area, el("div", { class: "btn-row" }, saveBtn));
  body.append(el("p", { class: "small muted" }, "At build time the real Python verifier was given the same one-letter edit on the plain approve path. It printed: ",
    el("code", null, D.tamper.python_verifier_output)));
  tamper.append(body);
  chainRoot.append(tamper);
  if (original.length) { sel.value = String(original.length); load(); }

  if (!ls.length) {
    chainRoot.append(el("p", { class: "state" }, "No records yet."));
    return;
  }
  const list = el("ol", { class: "chain", "aria-label": "Audit records, oldest first" });
  ls.forEach((raw, i) => {
    let r = null;
    try { r = JSON.parse(raw); } catch (e) { r = null; }
    const seq = i + 1;
    const broken = !verdict.ok && verdict.broken_seq !== null && seq >= verdict.broken_seq;
    const li = el("li", { class: (seq > seen ? "new " : "") + (broken ? "bad" : "") });
    if (!r) {
      li.append(el("div", { class: "card rec" }, el("strong", null, "seq " + seq + ": "), "not valid JSON (edited)"));
    } else {
      const res = r.result || {};
      li.append(el("div", { class: "card rec" },
        el("div", { class: "rec-head" }, el("strong", null, "#" + r.seq), pill(r.mode, "info"), el("code", null, r.lever),
          pill(res.status || "?", statusKind(res.status)), edits.has(seq) ? pill("edited by you", "bad") : null),
        el("div", { class: "small" }, "by ", el("strong", null, r.agent), " (" + r.actor_kind + ") for ", r.client || "all clients",
          r.approver ? [" · approved by ", el("strong", null, r.approver)] : null),
        res.reason ? el("div", { class: "small muted" }, res.reason) : null,
        el("div", { class: "hashes" }, el("span", null, "prev " + short(r.prev_hash, 12)), " → ", el("span", null, "hash " + short(r.hash, 12))),
        el("details", null, el("summary", { class: "small" }, "Raw record"), el("div", { class: "body" }, el("pre", { class: "small" }, prettyJSON(r))))));
    }
    list.append(li);
  });
  chainRoot.append(list);
  seen = ls.length;
}

// ---------------------------------------------------------------- after approval
function renderAfter() {
  clear(afterRoot);
  const node = byId.get(current);
  if (node.action !== "A") {
    afterRoot.append(el("p", { class: "muted" }, node.action === "J"
      ? "Rejected: nothing changed in the mock tenant, and the rejection is in the log. Start over and approve to see the notice and the pause switch."
      : "Approve Priya's reset (with the callback recorded) to see the notice draft and the pause switch."));
    return;
  }
  afterRoot.append(el("section", { class: "card" }, el("h3", null, "Tell Priya, in plain words"),
    el("p", { class: "small muted" }, "python -m workflows.notify " + D.proposal_id + ": filled from a reviewed template, never written by a model. A person sends it."),
    el("pre", null, D.notice)));
  const steps = node.pause || [];
  const box = el("section", { class: "card", "aria-labelledby": "pause-h" }, el("h3", { id: "pause-h" }, "Pull the switch"),
    el("p", { class: "small" }, "If a lead sees a run of suspicious reset requests, any lead can stop that lever for that client in seconds, with no approval needed. Even a dry-run is refused while it is paused."));
  steps.slice(0, pauseStep).forEach((s) => {
    box.append(el("div", { class: "banner " + (s.result.status === "ok" ? "ok" : "bad") },
      el("div", { class: "mono small" }, s.command), el("strong", null, s.result.status + ": "), s.result.reason || "ok"));
  });
  if (pauseStep < steps.length) {
    const labels = { "pause": "Pause user.reset-mfa for Contoso Dental", "denied-while-paused": "Now try another reset at Contoso", "resume": "Resume the lever" };
    const b = el("button", { class: "btn", type: "button" }, labels[steps[pauseStep].key] || steps[pauseStep].key);
    b.addEventListener("click", () => { pauseStep++; edits = new Map(); save(); renderAll(); });
    box.append(el("div", { class: "btn-row" }, b));
  } else {
    box.append(el("p", { class: "small muted" }, "All three steps are in the audit log."));
  }
  afterRoot.append(box);
}

async function renderAll() {
  renderQueue();
  renderAfter();
  await renderChain();
}

(async function main() {
  try { D = await loadData("data/approvals.json", queueRoot); } catch (e) { clear(chainRoot); return; }
  if (!D.nodes || !D.nodes.length) {
    queueRoot.append(el("p", { class: "state" }, "The build produced no queue states, so there is nothing to replay."));
    markReady();
    return;
  }
  byId = new Map(D.nodes.map((n) => [n.id, n]));
  const h = hashParams();
  if (h.path && byId.has(h.path)) {
    current = h.path;
    lastResponse = byId.get(current).response;
    const n = byId.get(current);
    pauseStep = n.pause ? Math.min(Number(h.pause) || 0, n.pause.length) : 0;
  }
  if (h.tamper === "1") { // deep link to the demo script's step 8: one letter of the approver changed
    const original = originalLines();
    const i = original.findIndex((l) => l.includes(D.tamper.find));
    if (i >= 0) edits.set(i + 1, original[i].replace(D.tamper.find, D.tamper.replace));
  }
  seen = lines().length; // nothing flashes on first load
  await renderAll();
  markReady();
})();
