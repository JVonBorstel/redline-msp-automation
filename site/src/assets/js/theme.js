// Applies the theme and the motion choice before first paint (loaded in <head>, no module, no network).
// Theme order: ?theme=light|dark in the address (not saved; used for screenshots and shared links), then the saved
// choice (storage may be blocked: then "auto", which follows the device setting).
(function () {
  var root = document.documentElement;
  root.classList.add("js"); // lets the CSS fold the nav behind a Menu button only when it can open
  var t = null;
  try { t = new URLSearchParams(window.location.search).get("theme"); } catch (e) { t = null; }
  if (t !== "light" && t !== "dark") {
    try { t = window.localStorage.getItem("theme"); } catch (e) { t = null; }
  }
  if (t === "light" || t === "dark") { root.setAttribute("data-theme", t); }
  try { if (window.localStorage.getItem("motion") === "reduce") { root.dataset.motion = "reduce"; } } catch (e) { /* blocked */ }
})();

// The camera between pages (cross-document view transitions; browsers without them just load the page).
// The nav is the map: moving to a page further along it pans right, back along it pans left. A link clicked in the
// page body (a pipeline step, a story card) becomes the next page's title, so the reader dives into what they chose.
// This must be a classic script in <head>: page modules run too late to see "pagereveal".
(function () {
  var root = document.documentElement;
  var still = function () {
    return root.dataset.motion === "reduce" ||
      (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  };
  var file = function (url) {
    try { return new URL(url, window.location.href).pathname.split("/").pop() || "index.html"; } catch (e) { return ""; }
  };
  var order = function (url) {
    var links = document.querySelectorAll(".nav a");
    var name = file(url);
    for (var i = 0; i < links.length; i++) { if (links[i].getAttribute("href") === name) { return i; } }
    return -1;
  };
  var clicked = null;
  document.addEventListener("click", function (ev) {
    clicked = ev.target instanceof Element ? ev.target.closest("a[href]") : null;
  }, true);

  window.addEventListener("pageswap", function (ev) {
    try { window.sessionStorage.setItem("camera-from", window.location.href); } catch (e) { /* blocked */ }
    if (!ev.viewTransition) { return; }
    if (still()) { ev.viewTransition.skipTransition(); return; }
    var a = clicked;
    if (!a || a.closest(".nav") || !ev.activation || !ev.activation.entry) { return; }
    if (file(a.href) !== file(ev.activation.entry.url)) { return; }
    var r = a.getBoundingClientRect();
    if (r.bottom < 0 || r.top > window.innerHeight) { return; }
    var h1 = document.querySelector("main h1");
    if (h1) { h1.style.setProperty("view-transition-name", "none"); }
    a.style.setProperty("view-transition-name", "page-title");
  });

  window.addEventListener("pagereveal", function (ev) {
    if (!ev.viewTransition) { return; }
    if (still()) { ev.viewTransition.skipTransition(); return; }
    if (!ev.viewTransition.types) { return; }
    // Where the reader came from: the Navigation API when it knows, else what the last page noted on its way out.
    var act = window.navigation && window.navigation.activation;
    var from = act && act.from ? act.from.url : null;
    if (!from) { try { from = window.sessionStorage.getItem("camera-from"); } catch (e) { from = null; } }
    if (!from) { return; }
    var d = order(window.location.href) - order(from);
    ev.viewTransition.types.add(d > 0 ? "forward" : d < 0 ? "backward" : "same");
  });
})();
