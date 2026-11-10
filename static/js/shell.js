(function () {
  "use strict";
  var root = document.documentElement;
  var themeButton = document.querySelector("[data-theme-toggle]");
  var themeIcon = document.querySelector("[data-theme-icon]");
  var sidebarToggle = document.querySelector("[data-sidebar-toggle]");
  var sidebarCollapse = document.querySelector("[data-sidebar-collapse]");
  var backdrop = document.querySelector("[data-sidebar-backdrop]");
  var sidebar = document.getElementById("app-sidebar");

  function setTheme(theme) {
    root.dataset.theme = theme;
    if (themeIcon) themeIcon.textContent = theme === "dark" ? "☀" : "☾";
    if (themeButton) themeButton.setAttribute("aria-label", theme === "dark" ? "فعال‌کردن حالت روشن" : "فعال‌کردن حالت تاریک");
  }
  if (themeButton) {
    setTheme(root.dataset.theme || "light");
    themeButton.addEventListener("click", function () {
      var next = root.dataset.theme === "dark" ? "light" : "dark";
      setTheme(next);
      try { localStorage.setItem("office-kmc-theme", next); } catch (_) {}
    });
  }

  function setMobileSidebar(open) {
    root.dataset.sidebarOpen = open ? "true" : "false";
    if (sidebarToggle) sidebarToggle.setAttribute("aria-expanded", open ? "true" : "false");
    if (backdrop) backdrop.hidden = !open;
    if (open && sidebar) {
      var firstLink = sidebar.querySelector("a");
      if (firstLink) firstLink.focus();
    } else if (sidebarToggle) sidebarToggle.focus();
  }
  if (sidebarToggle) sidebarToggle.addEventListener("click", function () { setMobileSidebar(root.dataset.sidebarOpen !== "true"); });
  if (backdrop) backdrop.addEventListener("click", function () { setMobileSidebar(false); });
  if (sidebarCollapse) sidebarCollapse.addEventListener("click", function () {
    var collapsed = root.dataset.sidebarCollapsed !== "true";
    root.dataset.sidebarCollapsed = collapsed ? "true" : "false";
    try { localStorage.setItem("office-kmc-sidebar-collapsed", collapsed ? "true" : "false"); } catch (_) {}
    sidebarCollapse.setAttribute("aria-label", collapsed ? "باز کردن منو" : "جمع کردن منو");
  });
  try {
    if (window.matchMedia && window.matchMedia("(min-width: 761px)").matches &&
        localStorage.getItem("office-kmc-sidebar-collapsed") === "true") {
      root.dataset.sidebarCollapsed = "true";
    }
  } catch (_) {}
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && root.dataset.sidebarOpen === "true") setMobileSidebar(false);
  });
  if (sidebar) {
    var currentPath = window.location.pathname.replace(/\/$/, "");
    sidebar.querySelectorAll("a.sidebar-link").forEach(function (link) {
      var path;
      try { path = new URL(link.href, window.location.origin).pathname.replace(/\/$/, ""); } catch (_) { return; }
      if (path && path === currentPath) link.setAttribute("aria-current", "page");
    });
  }
}());
