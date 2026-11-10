(function () {
  "use strict";
  var root = document.documentElement;
  var themeButton = document.querySelector("[data-theme-toggle]");
  var themeIcon = document.querySelector("[data-theme-icon]");
  var sidebarToggle = document.querySelector("[data-sidebar-toggle]");
  var sidebarCollapse = document.querySelector("[data-sidebar-collapse]");
  var backdrop = document.querySelector("[data-sidebar-backdrop]");
  var sidebar = document.getElementById("app-sidebar");

  var themePreference = root.dataset.themePreference || "system";
  var systemTheme = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
  function setTheme(preference) {
    themePreference = preference;
    var effective = preference === "system" && systemTheme ? (systemTheme.matches ? "dark" : "light") : preference;
    root.dataset.themePreference = preference;
    root.dataset.theme = effective;
    if (themeIcon) themeIcon.textContent = preference === "system" ? "◐" : (effective === "dark" ? "☀" : "☾");
    if (themeButton) {
      var label = preference === "system" ? "تغییر حالت نمایش؛ فعلی: سیستم" : (effective === "dark" ? "فعال‌کردن حالت روشن" : "فعال‌کردن حالت تاریک");
      themeButton.setAttribute("aria-label", label);
      themeButton.title = preference === "system" ? "حالت نمایش: پیروی از تنظیم دستگاه" : label;
    }
  }
  if (themeButton) {
    setTheme(themePreference);
    themeButton.addEventListener("click", function () {
      var next = themePreference === "system" ? "dark" : (themePreference === "dark" ? "light" : "system");
      setTheme(next);
      try { localStorage.setItem("office-kmc-theme", next); } catch (_) {}
    });
    if (systemTheme) {
      var onSystemThemeChange = function () { if (themePreference === "system") setTheme("system"); };
      if (systemTheme.addEventListener) systemTheme.addEventListener("change", onSystemThemeChange);
      else if (systemTheme.addListener) systemTheme.addListener(onSystemThemeChange);
    }
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
