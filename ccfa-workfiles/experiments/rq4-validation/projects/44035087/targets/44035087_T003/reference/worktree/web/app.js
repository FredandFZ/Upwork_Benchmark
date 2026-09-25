const categories = [
  ["under_1200_sqft", "Under 1200 sqft"],
  ["1201_2400_sqft", "1201–2400 sqft"],
  ["2401_3600_sqft", "2401–3600 sqft"],
  ["3600_plus_sqft", "3600+ sqft"]
];
const prices = {"basic":[325,475,625,775],"essential":[450,625,800,975],"premium":[575,775,975,1175],"signature":[725,950,1175,1400]};
const selector = document.querySelector("#square-footage-tier");
function dollars(value) { return new Intl.NumberFormat("en-US", {style:"currency", currency:"USD", maximumFractionDigits:0}).format(value); }
function renderCards() {
  const tierIndex = categories.findIndex(([key]) => key === selector.value);
  for (const card of document.querySelectorAll(".package")) {
    card.querySelector(".price").textContent = dollars(prices[card.dataset.package][tierIndex]);
    card.querySelector(".band").textContent = categories[tierIndex][1];
  }
}
const tbody = document.querySelector("#price-matrix");
for (const [name, values] of Object.entries(prices)) {
  const row = document.createElement("tr");
  row.innerHTML = `<th scope="row">${name[0].toUpperCase() + name.slice(1)}</th>${values.map(value => `<td>${dollars(value)}</td>`).join("")}`;
  tbody.appendChild(row);
}
selector.addEventListener("change", renderCards);
renderCards();

