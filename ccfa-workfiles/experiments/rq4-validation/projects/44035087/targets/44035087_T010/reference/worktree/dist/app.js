const form = document.querySelector("#quote-form");
const result = document.querySelector("#result");
form.addEventListener("submit", async event => {
  event.preventDefault();
  const payload = Object.fromEntries(new FormData(form));
  const response = await fetch(document.body.dataset.endpoint, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload)
  });
  const body = await response.json();
  result.textContent = response.ok ? `Thanks, ${body.name}. Your quote request has been received.` : body.error;
});

