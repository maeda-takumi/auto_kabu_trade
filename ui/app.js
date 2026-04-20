const statusBadge = document.getElementById("statusBadge");
const toggleButton = document.getElementById("toggleButton");
const stateFlow = document.getElementById("stateFlow");
const riskRules = document.getElementById("riskRules");
const docCards = document.getElementById("docCards");

const renderStatus = (isRunning, status) => {
  statusBadge.textContent = status;
  statusBadge.classList.toggle("running", isRunning);
  toggleButton.textContent = isRunning ? "停止する" : "稼働開始";
};

const renderList = (target, items) => {
  target.innerHTML = "";
  items.forEach((item) => {
    const li = document.createElement("li");
    li.textContent = item;
    target.appendChild(li);
  });
};

const renderDocs = (summaries) => {
  docCards.innerHTML = "";
  summaries.forEach((summary) => {
    const card = document.createElement("article");
    card.className = "doc-card";
    card.innerHTML = `
      <h4>${summary.title}</h4>
      <p class="doc-meta">${summary.updated} ・ ${summary.file}</p>
      <ul>${summary.highlights.map((point) => `<li>${point}</li>`).join("")}</ul>
    `;
    docCards.appendChild(card);
  });
};

const initialize = async () => {
  const data = await window.pywebview.api.get_initial_data();
  renderStatus(data.isRunning, data.status);
  renderList(stateFlow, data.stateFlow);
  renderList(riskRules, data.riskRules);
  renderDocs(data.summaries);
};

toggleButton.addEventListener("click", async () => {
  const data = await window.pywebview.api.toggle_trading();
  renderStatus(data.isRunning, data.status);
});

window.addEventListener("pywebviewready", initialize);