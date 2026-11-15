const STORAGE_KEY = "ruang-warga-theme";
const html = document.documentElement;

const isDark = () => html.classList.contains("dark");

function syncIcons() {
  const sun = document.getElementById("dark-mode-sun");
  const moon = document.getElementById("dark-mode-moon");
  sun?.classList.toggle("hidden", isDark());
  moon?.classList.toggle("hidden", !isDark());
}

function setTheme(dark) {
  html.classList.toggle("dark", dark);
  try {
    localStorage.setItem(STORAGE_KEY, dark ? "dark" : "light");
  } catch (e) {}
  syncIcons();
}

syncIcons();

document
  .getElementById("dark-mode-toggle")
  ?.addEventListener("click", () => setTheme(!isDark()));
