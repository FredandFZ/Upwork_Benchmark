
const project = document.body.dataset.project;
const endpoint = document.body.dataset.endpoint;
const fieldSets = {
  "42204309": [["buyer", "Buyer", "reader@example.test"], ["amount_usd", "Amount (USD)", "30"], ["referral_code", "Referral code", ""]],
  "43772711": [["administrator", "Administrator", "admin@example.test"], ["company", "Company", "Example Co"], ["role", "Agent role", "assistant"]],
  "43804272": [["samples", "Angle samples", "2,8,5"]],
  "44035087": [["square_feet", "Square feet", "1800"], ["package", "Package", "basic"]]
};
const fields = document.querySelector("#fields");
for (const [name, label, value] of fieldSets[project]) {
  const wrapper = document.createElement("label");
  wrapper.textContent = label;
  const input = document.createElement("input"); input.name = name; input.value = value;
  wrapper.appendChild(input); fields.appendChild(wrapper);
}
document.querySelector("#action-form").addEventListener("submit", async event => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(event.currentTarget));
  if (project === "43804272") data.samples = data.samples.split(",").map(Number);
  if (data.amount_usd) data.amount_usd = Number(data.amount_usd);
  if (data.square_feet) data.square_feet = Number(data.square_feet);
  const response = await fetch(endpoint, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(data)});
  const payload = await response.json();
  document.querySelector("#result").textContent = JSON.stringify(payload, null, 2);
  if (response.ok && payload.feedback) {
    const modal = document.querySelector("#mint-modal");
    document.querySelector("#mint-token").textContent = `Token ID: ${payload.feedback.token_id}`;
    const message = document.querySelector("#mint-message");
    message.replaceChildren();
    if (payload.feedback.variant === "coded-referral") {
      message.append("$12 commission + $1,250 prize draw ticket has gone to your chosen ");
      const title = document.createElement("em");
      title.className = "book-title";
      title.textContent = "From Workshop Floor to Fresh Start";
      message.append(title, " NFT holder");
    } else {
      message.textContent = payload.feedback.copy;
    }
    if (typeof modal.showModal === "function") modal.showModal(); else modal.setAttribute("open", "");
  }
});
document.querySelector("#close-modal").addEventListener("click", () => document.querySelector("#mint-modal").close());
