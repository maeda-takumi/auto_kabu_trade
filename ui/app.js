const orderForm = document.getElementById("orderForm");
const dbStatus = document.getElementById("dbStatus");
const activeCount = document.getElementById("activeCount");
const filledCount = document.getElementById("filledCount");
const realizedPnL = document.getElementById("realizedPnL");
const statusTableBody = document.getElementById("statusTableBody");
const lastUpdated = document.getElementById("lastUpdated");

const formatNumber = (value) => new Intl.NumberFormat("ja-JP").format(value);

const renderMonitor = (data) => {
  activeCount.textContent = data.activeCount;
  filledCount.textContent = data.filledCount;
  const pnl = Number(data.realizedPnl || 0);
  realizedPnL.textContent = `¥${formatNumber(pnl)}`;

  statusTableBody.innerHTML = "";
  data.statusRows.forEach((row) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${row.updatedAt}</td>
      <td>${row.orderId}</td>
      <td>${row.symbol}</td>
      <td>${row.side}</td>
      <td>${row.quantity}</td>
      <td>${row.status}</td>
    `;
    statusTableBody.appendChild(tr);
  });

  lastUpdated.textContent = `最終更新: ${data.snapshotAt}`;
};

const loadMonitor = async () => {
  const monitor = await window.pywebview.api.get_monitor_data();
  renderMonitor(monitor);
};

orderForm.addEventListener("submit", async (event) => {
  event.preventDefault();

  const payload = {
    symbol: document.getElementById("symbol").value,
    side: document.getElementById("side").value,
    quantity: Number(document.getElementById("quantity").value),
    orderPrice: Number(document.getElementById("orderPrice").value),
    orderType: document.getElementById("orderType").value,
    timeInForce: document.getElementById("timeInForce").value,
    takeProfit: document.getElementById("takeProfit").value,
    stopLoss: document.getElementById("stopLoss").value,
    note: document.getElementById("note").value,
  };

  await window.pywebview.api.submit_order(payload);
  window.alert("注文が完了しました");
  orderForm.reset();
  document.getElementById("quantity").value = 100;
  document.getElementById("orderPrice").value = 0;
  await loadMonitor();
});

const initialize = async () => {
  const init = await window.pywebview.api.get_initial_data();
  dbStatus.textContent = init.dbStatus;
  await loadMonitor();
  window.setInterval(loadMonitor, 5000);
};

window.addEventListener("pywebviewready", initialize);