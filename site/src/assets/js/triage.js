import { el, clear, pill, revealed, countHidden, loadData, markReady, hashParams, setHash, initTheme, prettyJSON, short } from "./common.js";

initTheme();
const root = document.getElementById("triage-root");
const controls = document.getElementById("triage-controls");
const IMPACT = [["L1", "one person"], ["L2", "the client"], ["L3", "the MSP"], ["L4", "the community"]];
let reveal = true;
let tickets = [];

function stepCard(n, title, ...body) {
  return el("section", { class: "card", "aria-labelledby": "step-" + n },
    el("h2", { id: "step-" + n }, el("span", { class: "muted" }, n + " · "), title), ...body);
}

function noLeverReason(tr) {
  const line = tr.why.find((w) => w.startsWith("No lever") || w.startsWith("Injection flagged"));
  return line || "No lever proposed.";
}

function render(t) {
  const tr = t.triage;
  clear(root);
  const hidden = countHidden(t.subject + t.body);

  // 1. the ticket
  root.append(stepCard(1, "The ticket arrives (untrusted text)",
    el("p", { class: "muted small" }, "Synthetic ticket from the repo's fixtures. The subject and body are typed by the requester, so they are treated as untrusted data. Lever parameters may only come from the PSA form fields."),
    el("dl", { class: "facts" },
      el("dt", null, "Ticket"), el("dd", null, el("code", null, t.id)),
      el("dt", null, "Client"), el("dd", null, t.client),
      el("dt", null, "Requester"), el("dd", null, t.requester),
      el("dt", null, "Affected user (form field)"), el("dd", null, t.affected_user || "empty"),
      el("dt", null, "Technician (form field)"), el("dd", null, t.technician)),
    el("pre", { class: "untrusted", "aria-label": "Ticket subject and body" },
      revealed("Subject: " + t.subject + "\n\n" + t.body, reveal)),
    hidden ? el("p", { class: "banner warn" }, el("strong", null, hidden + " hidden character" + (hidden === 1 ? "" : "s") + " "),
      reveal ? "are shown as red badges above. A person reading the ticket in a normal viewer would not see them." :
        "are in this text but not shown. Tick “Show hidden characters” to see them.") : null));

  // 2. injection tripwire
  const inj = tr.injection;
  root.append(stepCard(2, "Injection tripwire",
    inj.flagged
      ? el("div", null,
          el("p", { class: "banner bad", role: "status" }, el("strong", null, "Flagged. "), "Reported for a person to review, never followed. The ticket goes to the security queue and gets no lever."),
          el("ul", null, inj.reasons.map((r) => el("li", null, el("code", null, r.rule), ": ", el("span", null, revealed(r.evidence, reveal))))))
      : el("p", { class: "banner ok", role: "status" }, el("strong", null, "Nothing flagged. "), "The detector found no instruction-like text. It is a tripwire, not the control: the lever registry is.")));

  // 3. what the model sees
  root.append(stepCard(3, "What the model sees",
    el("p", { class: "muted small" }, "core/guard wrap_untrusted(): hidden characters stripped, look-alike markers neutralised, and the open and close markers carry a hash of the content, so text inside cannot forge a closing marker."),
    el("pre", { class: "wrapped" }, t.wrapped)));

  // 4. classification and routing
  const gold = t.gold;
  const cmp = (field) => (gold[field] === tr[field] ? pill("matches the lead's label", "ok") : pill("lead's label: " + gold[field], "warn"));
  root.append(stepCard(4, "Classification and routing",
    el("dl", { class: "facts" },
      el("dt", null, "Category"), el("dd", null, el("strong", null, tr.category), " ", cmp("category")),
      el("dt", null, "Priority"), el("dd", null, el("strong", null, tr.priority), " ", cmp("priority")),
      el("dt", null, "Queue"), el("dd", null, el("strong", null, tr.queue), " ", cmp("queue"))),
    el("h3", null, "Why"), el("ul", null, tr.why.map((w) => el("li", null, w))),
    el("h3", null, "Data used"), el("ul", null, tr.data_used.map((d) => el("li", null, d))),
    el("p", { class: "muted small" }, "The model here is the repo's deterministic mock (keyword rules), so this shows the pipeline, not model quality.")));

  // 5. lever proposal
  const p = tr.proposal;
  if (p) {
    const diff = tr.dry_run.diff;
    root.append(stepCard(5, "One lever is proposed, by rules, and dry-run",
      el("dl", { class: "facts" },
        el("dt", null, "Lever"), el("dd", null, el("code", null, p.lever), " ", pill("risk " + tr.risk_class, "warn")),
        el("dt", null, "For"), el("dd", null, Object.entries(p.params).map(([k, v]) => k + " = " + v).join(", ")),
        el("dt", null, "Proposal"), el("dd", null, el("code", null, p.id), " ", pill(p.status, "info")),
        el("dt", null, "Requested by"), el("dd", null, p.requested_by + " (the ticket's technician; executing needs a lead)"),
        el("dt", null, "Dry-run"), el("dd", null, "as ", el("code", null, tr.dry_run.identity), ": ", tr.dry_run.status, ", ",
          String(diff.length), " change(s), applied: ", el("strong", null, String(tr.dry_run.applied)))),
      el("div", { class: "table-wrap" }, el("table", null,
        el("caption", { class: "visually-hidden" }, "Dry-run diff"),
        el("thead", null, el("tr", null, el("th", { scope: "col" }, "Op"), el("th", { scope: "col" }, "Path"), el("th", { scope: "col" }, "Before"), el("th", { scope: "col" }, "After"))),
        el("tbody", null, diff.map((c) => el("tr", null, el("td", null, el("code", null, c.op)), el("td", { class: "mono small" }, c.path),
          el("td", { class: "mono small" }, c.before === null ? "—" : JSON.stringify(c.before)),
          el("td", { class: "mono small" }, c.after === null ? "—" : JSON.stringify(c.after)))))))));
  } else {
    root.append(stepCard(5, "Lever proposal",
      el("p", { class: "banner" + (inj.flagged ? " bad" : "") }, el("strong", null, "No lever. "), noLeverReason(tr)),
      el("p", { class: "muted small" }, gold.expected_lever ? "The lead's label expected " + gold.expected_lever + "." : "The lead's label also expects no lever.")));
  }

  // 6. who this affects
  if (p && tr.who_this_affects) {
    root.append(stepCard(6, "Who this affects (from the lever's registry entry, never the ticket)",
      el("ul", { class: "impact" }, IMPACT.map(([lvl, label]) => el("li", null, el("span", { class: "lvl", title: label }, lvl),
        el("span", null, el("strong", null, label + ": "), tr.who_this_affects[lvl])))),
      tr.before_approval ? el("p", { class: "banner warn" }, el("strong", null, "Before approval: "), tr.before_approval + ", never a number given in the ticket.") : null));
  }

  // 7. the audit record
  if (t.audit_line) {
    const rec = JSON.parse(t.audit_line);
    root.append(stepCard(7, "The dry-run is already in the audit log",
      el("p", { class: "muted small" }, "One hash-chained record, exactly as core/audit wrote it during the build. Contact details are masked before writing."),
      el("p", { class: "mono small" }, "seq " + rec.seq + " · prev_hash " + short(rec.prev_hash, 16) + " · hash " + short(rec.hash, 16)),
      el("pre", null, prettyJSON(rec)),
      t.id === "T-3101"
        ? el("p", null, el("a", { class: "btn", href: "approvals.html" }, "Take this proposal to the approval queue →"))
        : el("p", { class: "muted small" }, "The approval demo replays Priya's ticket, T-3101.")));
  }

  root.append(el("details", null, el("summary", null, "Plain-text output, as the command line printed it"),
    el("div", { class: "body" }, el("p", { class: "small muted" }, "python -m workflows.triage " + t.id),
      el("pre", null, revealed(t.explain, reveal)))));
}

function pick(id) {
  const t = tickets.find((x) => x.id === id) || tickets[0];
  const select = document.getElementById("ticket-select");
  if (select) select.value = t.id;
  setHash({ t: t.id });
  render(t);
}

function buildControls() {
  clear(controls);
  const select = el("select", { id: "ticket-select" });
  const clients = [...new Set(tickets.map((t) => t.client))];
  for (const c of clients) {
    const group = el("optgroup", { label: c });
    for (const t of tickets.filter((x) => x.client === c)) {
      const flag = t.triage.injection.flagged ? " (flagged)" : t.triage.proposal ? " (lever proposed)" : "";
      group.append(el("option", { value: t.id }, t.id + " · " + t.subject.replace(/[​-‏⁠-⁩﻿‪-‮­]/g, "") + flag));
    }
    select.append(group);
  }
  select.addEventListener("change", () => pick(select.value));
  const reveal_box = el("input", { type: "checkbox", id: "reveal", checked: true });
  reveal_box.addEventListener("change", () => { reveal = reveal_box.checked; pick(select.value); });
  controls.append(
    el("label", { for: "ticket-select" }, "Ticket (" + tickets.length + " synthetic)", select),
    el("div", { class: "btn-row" },
      el("button", { class: "btn secondary", type: "button", onclick: () => pick("T-3101") }, "Priya's MFA reset"),
      el("button", { class: "btn secondary", type: "button", onclick: () => pick("T-3129") }, "Hidden instruction"),
      el("button", { class: "btn secondary", type: "button", onclick: () => pick(tickets[Math.floor(Math.random() * tickets.length)].id) }, "Random ticket")),
    el("label", { class: "inline", for: "reveal" }, el("span", null, reveal_box, " Show hidden characters")));
}

(async function main() {
  let data;
  try { data = await loadData("data/triage.json", root); } catch (e) { return; }
  tickets = data.tickets;
  if (!tickets.length) {
    root.append(el("p", { class: "state" }, "The build produced no tickets, so there is nothing to show."));
    markReady();
    return;
  }
  const v = document.getElementById("triage-verify");
  if (v) v.textContent = data.audit_verify.line + " (" + data.audit_records + " dry-run records from triaging all " + tickets.length + " tickets).";
  buildControls();
  pick(hashParams().t || "T-3101");
  markReady();
})();
