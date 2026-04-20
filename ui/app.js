const orderForm = document.getElementById("orderForm");
const dbStatus = document.getElementById("dbStatus");
const activeCount = document.getElementById("activeCount");
const filledCount = document.getElementById("filledCount");
const realizedPnL = document.getElementById("realizedPnL");
const statusTableBody = document.getElementById("statusTableBody");
const lastUpdated = document.getElementById("lastUpdated");
const orderRows = document.getElementById("orderRows");
const addRowButton = document.getElementById("addRowButton");

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

const createOrderRow = (defaultValues = {}) => {
  const row = document.createElement("div");
  row.className = "order-row";
  row.innerHTML = `
    <label>
      銘柄コード
      <input class="row-symbol" type="text" placeholder="例: 7203" required />
    </label>
    <label>
      注文数量
      <input class="row-quantity" type="number" min="1" value="100" required />
    </label>
    <label>
      注文価格（成行は0）
      <input class="row-order-price" type="number" min="0" step="0.1" value="0" required />
    </label>
    <label>
      利確指値価格（任意）
      <input class="row-take-profit" type="number" min="0" step="0.1" />
    </label>
    <label>
      損切逆指値価格（任意）
      <input class="row-stop-loss" type="number" min="0" step="0.1" />
    </label>
    <div class="row-actions">
      <button class="danger remove-row-button" type="button">この行を削除</button>
    </div>
  `;

  row.querySelector(".row-symbol").value = defaultValues.symbol || "";
  row.querySelector(".row-quantity").value = defaultValues.quantity || 100;
  row.querySelector(".row-order-price").value = defaultValues.orderPrice || 0;
  row.querySelector(".row-take-profit").value = defaultValues.takeProfit || "";
  row.querySelector(".row-stop-loss").value = defaultValues.stopLoss || "";

  row.querySelector(".remove-row-button").addEventListener("click", () => {
    if (orderRows.children.length <= 1) {
      window.alert("最低1件の注文行が必要です");
      return;
    }
    row.remove();
  });

  orderRows.appendChild(row);
};

const resetOrderRows = () => {
  orderRows.innerHTML = "";
  createOrderRow();
};

addRowButton.addEventListener("click", () => {
  createOrderRow();
});
orderForm.addEventListener("keydown", (event) => {
  if (event.key !== "Enter") {
    return;
  }

  const target = event.target;
  if (target instanceof HTMLTextAreaElement) {
    return;
  }

  event.preventDefault();
});

orderForm.addEventListener("submit", async (event) => {
  event.preventDefault();

  const entries = Array.from(orderRows.querySelectorAll(".order-row")).map((row) => ({
    symbol: row.querySelector(".row-symbol").value,
    quantity: Number(row.querySelector(".row-quantity").value),
    orderPrice: Number(row.querySelector(".row-order-price").value),
    takeProfit: row.querySelector(".row-take-profit").value,
    stopLoss: row.querySelector(".row-stop-loss").value,
  }));

  const payload = {
    entries,
    side: document.getElementById("side").value,
    orderType: document.getElementById("orderType").value,
    timeInForce: document.getElementById("timeInForce").value,
    exchange: Number(document.getElementById("exchange").value),
    securityType: 1,
    cashMargin: Number(document.getElementById("cashMargin").value),
    marginTradeType: Number(document.getElementById("marginTradeType").value),
    delivType: Number(document.getElementById("delivType").value),
    fundType: document.getElementById("fundType").value,
    accountType: Number(document.getElementById("accountType").value),
    expireDay: Number(document.getElementById("expireDay").value),
    note: document.getElementById("note").value,
  };

  const result = await window.pywebview.api.submit_orders(payload);
  window.alert(`${result.count}件の注文登録が完了しました`);
  orderForm.reset();
  resetOrderRows();
  document.getElementById("delivType").value = 2;
  document.getElementById("fundType").value = "AA";
  document.getElementById("expireDay").value = 0;
  await loadMonitor();
});

const initialize = async () => {
  resetOrderRows();
  const init = await window.pywebview.api.get_initial_data();
  dbStatus.textContent = init.dbStatus;
  await loadMonitor();
  window.setInterval(loadMonitor, 5000);
};

window.addEventListener("pywebviewready", initialize);