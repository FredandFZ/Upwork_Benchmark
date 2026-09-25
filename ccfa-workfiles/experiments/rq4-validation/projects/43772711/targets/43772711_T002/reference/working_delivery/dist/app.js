
const menuButton = document.querySelector(".menu-button");
const navigation = document.querySelector("#site-navigation");
menuButton.addEventListener("click", () => {
  const open = menuButton.getAttribute("aria-expanded") !== "true";
  menuButton.setAttribute("aria-expanded", String(open));
  navigation.dataset.open = String(open);
});
