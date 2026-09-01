const root = document.querySelector("#app");

function valueText(value) {
  if (Array.isArray(value)) return value.map(valueText).join(" · ");
  if (value && typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function renderFeature(feature) {
  const items = Object.entries(feature.configuration)
    .slice(0, 8)
    .map(([key, value]) => `<li><strong>${key.replaceAll("_", " ")}</strong><span>${valueText(value)}</span></li>`)
    .join("");
  return `<article class="feature"><p>${feature.family || "Current capability"}</p><h2>${feature.title}</h2><ul>${items}</ul></article>`;
}

async function boot() {
  const response = await fetch("/api/state");
  const state = await response.json();
  if (!state.features.length) return;
  document.title = state.projectName;
  const hero = state.hero
    ? `<section class="hero"><div><p class="eyebrow">Current application</p><h1>${state.hero.headline_text || state.projectName}</h1><p>${state.hero.subheadline_text || ""}</p><a class="button" href="#features">${state.hero.cta_text || "Explore"}</a></div><div class="cover" aria-label="Current cover presentation"><span>BOOK</span></div></section>`
    : `<header><p class="eyebrow">Current application</p><h1>${state.projectName}</h1></header>`;
  root.innerHTML = `${hero}<section id="features" class="features">${state.features.map(renderFeature).join("")}</section>`;
}

boot().catch((error) => {
  root.innerHTML = `<h1>Application unavailable</h1><pre>${error.message}</pre>`;
});
