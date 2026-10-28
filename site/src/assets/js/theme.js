// Applies the theme before first paint (loaded in <head>, no module, no network).
// Order: ?theme=light|dark in the address (not saved; used for screenshots and shared links), then the saved
// choice (storage may be blocked: then "auto", which follows the device setting).
(function () {
  var t = null;
  try { t = new URLSearchParams(window.location.search).get("theme"); } catch (e) { t = null; }
  if (t !== "light" && t !== "dark") {
    try { t = window.localStorage.getItem("theme"); } catch (e) { t = null; }
  }
  if (t === "light" || t === "dark") { document.documentElement.setAttribute("data-theme", t); }
})();
