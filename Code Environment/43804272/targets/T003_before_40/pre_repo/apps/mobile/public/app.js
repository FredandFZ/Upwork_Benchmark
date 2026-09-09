const statusNode = document.querySelector("[data-status]");
const featureNode = document.querySelector("[data-features]");

function renderFeature(feature) {
  const article = document.createElement("article");
  article.className = "card";
  const title = document.createElement("h2");
  title.textContent = feature.title;
  const family = document.createElement("p");
  family.className = "eyebrow";
  family.textContent = [feature.family, feature.lifecycle, feature.execution?.status].filter(Boolean).join(" · ");
  const configuration = document.createElement("pre");
  configuration.textContent = JSON.stringify(feature.configuration, null, 2);
  article.append(title, family, configuration);
  return article;
}

async function boot() {
  const response = await fetch("/api/snapshot");
  if (!response.ok) throw new Error("Snapshot request failed with " + response.status);
  const snapshot = await response.json();
  statusNode.textContent = String(snapshot.features.length) + " reconstructed capabilities";
  if (snapshot.features.length === 0) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "This baseline is ready for the first project change.";
    featureNode.append(empty);
    return;
  }
  for (const feature of snapshot.features) featureNode.append(renderFeature(feature));
}

boot().catch((error) => {
  statusNode.textContent = "Runtime unavailable";
  statusNode.dataset.error = error.message;
});
