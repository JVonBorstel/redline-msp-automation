// Pages rendered fully at build time need only the theme switch and a few progressive enhancements.
import { initTheme, markReady } from "./common.js";

initTheme();

// Lever table filter (levers.html). Without JavaScript every lever is listed.
const filters = document.getElementById("lever-filters");
if (filters) {
  const rows = [...document.querySelectorAll("[data-lever]")];
  const status = document.getElementById("lever-count");
  filters.hidden = false;
  filters.addEventListener("click", (ev) => {
    const b = ev.target.closest("button[data-filter]");
    if (!b) return;
    for (const other of filters.querySelectorAll("button[data-filter]")) other.setAttribute("aria-pressed", String(other === b));
    const f = b.dataset.filter;
    let n = 0;
    for (const r of rows) {
      const show = f === "all" || r.dataset.class === f || r.dataset.risk === f;
      r.hidden = !show;
      if (show) n++;
    }
    if (status) status.textContent = n ? "Showing " + n + " of " + rows.length + " levers." : "No levers match this filter.";
  });
}

// Baseline tenant tabs (baseline.html). Without JavaScript both tenants are shown one after the other.
const tabs = document.getElementById("tenant-tabs");
if (tabs) {
  const panels = [...document.querySelectorAll("[data-tenant-panel]")];
  const buttons = [...tabs.querySelectorAll("[role=tab]")];
  tabs.hidden = false;
  const select = (id, focus) => {
    for (const b of buttons) {
      const on = b.dataset.tenant === id;
      b.setAttribute("aria-selected", String(on));
      b.tabIndex = on ? 0 : -1;
      if (on && focus) b.focus();
    }
    for (const p of panels) p.hidden = p.dataset.tenantPanel !== id;
  };
  buttons.forEach((b, i) => {
    b.addEventListener("click", () => select(b.dataset.tenant, false));
    b.addEventListener("keydown", (ev) => {
      if (ev.key !== "ArrowRight" && ev.key !== "ArrowLeft") return;
      const next = buttons[(i + (ev.key === "ArrowRight" ? 1 : buttons.length - 1)) % buttons.length];
      select(next.dataset.tenant, true);
    });
  });
  select(buttons[0].dataset.tenant, false);
}

markReady();
