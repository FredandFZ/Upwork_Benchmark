
const choices = [...document.querySelectorAll("[data-theme-choice]")];
for (const choice of choices) {
  choice.addEventListener("click", () => {
    const theme = choice.dataset.themeChoice;
    document.body.dataset.theme = theme;
    for (const button of choices) {
      button.setAttribute("aria-pressed", String(button === choice));
    }
  });
}
