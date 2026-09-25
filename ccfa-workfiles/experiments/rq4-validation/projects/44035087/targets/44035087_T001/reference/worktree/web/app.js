const tabs = ["photos", "twilights", "videos", "floor_plans", "3d_tour"];
const labels = {photos:"Photos",twilights:"Twilights",videos:"Videos",floor_plans:"Floor plans", "3d_tour":"3D tour"};
const tablist = document.querySelector(".tabs");
const gallery = document.querySelector(".gallery");
function render(selected) {
  gallery.replaceChildren();
  for (let index = 1; index <= 4; index += 1) {
    const tile = document.createElement("article");
    tile.className = "tile";
    tile.textContent = labels[selected] + " " + index;
    gallery.appendChild(tile);
  }
  for (const button of tablist.querySelectorAll("button")) {
    button.setAttribute("aria-selected", String(button.dataset.tab === selected));
  }
}
for (const tab of tabs) {
  const button = document.createElement("button");
  button.type = "button";
  button.dataset.tab = tab;
  button.setAttribute("role", "tab");
  button.textContent = labels[tab];
  button.addEventListener("click", () => render(tab));
  tablist.appendChild(button);
}
render(tabs[0]);

