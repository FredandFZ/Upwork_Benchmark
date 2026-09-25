const selector = document.querySelector("#locale");
const status = document.querySelector("#locale-status");
let supported = [];

async function loadConfig() {
  const response = await fetch("/api/app/config");
  const config = await response.json();
  supported = [...new Set([...config.localization.android.locales, ...config.localization.ios.locales])];
  for (const locale of supported) {
    const option = document.createElement("option");
    option.value = locale;
    option.textContent = locale;
    selector.appendChild(option);
  }
  document.querySelector("#android-count").textContent = `${config.localization.android.language_count} languages`;
  document.querySelector("#ios-count").textContent = `${config.localization.ios.language_count} languages`;
  status.textContent = `${supported.length} unique locales available across both stores.`;
}

document.querySelector("#apply-locale").addEventListener("click", async () => {
  const response = await fetch("/api/locales", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({locale: selector.value})});
  const result = await response.json();
  if (!response.ok) { status.textContent = result.error; return; }
  document.documentElement.lang = result.locale;
  document.documentElement.dir = result.direction;
  status.textContent = `Locale ${result.locale} applied (${result.direction}).`;
});

loadConfig();
