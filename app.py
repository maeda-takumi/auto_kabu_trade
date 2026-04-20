from __future__ import annotations

import configparser
import json
import sqlite3
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import webview

BASE_DIR = Path(__file__).resolve().parent
DB_DIR = BASE_DIR / "db"
DB_PATH = DB_DIR / "trade_data.sqlite3"

CONFIG_DIR = BASE_DIR / "config"
CONFIG_PATH = CONFIG_DIR / "kabusapi_config.ini"


@dataclass
class KabuStationConfig:
    base_url: str
    api_password: str
    timeout_sec: float = 8.0


class KabuStationClient:
    def __init__(self, config: KabuStationConfig) -> None:
        self.base_url = config.base_url.rstrip("/")
        self.api_password = config.api_password
        self.timeout_sec = config.timeout_sec
        self._token: str | None = None

    def send_order(self, payload: Dict[str, Any]) -> str:
        result = self._request("POST", "/sendorder", payload, use_token=True)
        order_id = result.get("OrderId")
        if not order_id:
            raise RuntimeError(f"OrderId がレスポンスにありません: {result}")
        return str(order_id)

    def get_orders(self, product: int = 2) -> List[Dict[str, Any]]:
        return self._request("GET", f"/orders?product={product}", use_token=True)

    def get_positions(self, product: int = 2) -> List[Dict[str, Any]]:
        return self._request("GET", f"/positions?product={product}", use_token=True)

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        return self._request(
            "PUT",
            "/cancelorder",
            payload={"OrderID": str(order_id)},
            use_token=True,
        )

    def _ensure_token(self) -> str:
        if self._token:
            return self._token

        response = self._request(
            "POST",
            "/token",
            payload={"APIPassword": self.api_password},
            use_token=False,
        )
        token = response.get("Token")
        if not token:
            raise RuntimeError("/token のレスポンスに Token がありません")
        self._token = str(token)
        return self._token

    def _request(
        self,
        method: str,
        path: str,
        payload: Dict[str, Any] | None = None,
        use_token: bool = False,
    ) -> Any:
        url = f"{self.base_url}{path}"

        headers = {"Content-Type": "application/json"}
        if use_token:
            headers["X-API-KEY"] = self._ensure_token()

        body = None
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")

        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            if use_token and exc.code == 401:
                self._token = None
                headers["X-API-KEY"] = self._ensure_token()
                retry_req = urllib.request.Request(url, data=body, method=method, headers=headers)
                with urllib.request.urlopen(retry_req, timeout=self.timeout_sec) as retry_resp:
                    return json.loads(retry_resp.read().decode("utf-8"))
            raise RuntimeError(f"kabu API HTTPエラー {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"kabu API接続エラー: {exc}") from exc



class TradingConsoleApi:
    def __init__(self) -> None:
        self.db_path = DB_PATH
        self._initialize_db()
        self.client: KabuStationClient | None = None
        self.config_error: str | None = None
        self._initialize_client()

    def get_initial_data(self) -> Dict[str, str]:
        if self.config_error:
            return {
                "dbStatus": f"DB接続: {self.db_path.name}",
                "apiStatus": f"API未接続: {self.config_error}",
            }
        return {
            "dbStatus": f"DB接続: {self.db_path.name}",
            "apiStatus": "API接続設定: OK",
        }

    def submit_orders(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self.client:
            raise RuntimeError("API設定が不足しているため注文を実行できません")
        entries = payload.get("entries") or []
        if not entries:
            raise ValueError("entries が空です")

        created_at = self._now_iso()
        side = payload.get("side") or "BUY"
        order_type = payload.get("orderType") or "MARKET"
        time_in_force = payload.get("timeInForce") or "DAY"

        exchange = int(payload.get("exchange") or 1)
        security_type = int(payload.get("securityType") or 1)
        cash_margin = int(payload.get("cashMargin") or 2)
        margin_trade_type = int(payload.get("marginTradeType") or 1)
        deliv_type = int(payload.get("delivType") or 0)
        fund_type = str(payload.get("fundType") or "11")
        account_type = int(payload.get("accountType") or 4)
        expire_day = int(payload.get("expireDay") or 0)
        note = (payload.get("note") or "").strip()

        success_count = 0
        failure_count = 0

        with sqlite3.connect(self.db_path) as conn:
            for entry in entries:
                symbol = (entry.get("symbol") or "").strip()
                qty = int(entry.get("quantity") or 0)
                order_price = float(entry.get("orderPrice") or 0)
                take_profit = self._parse_nullable_number(entry.get("takeProfit"))
                stop_loss = self._parse_nullable_number(entry.get("stopLoss"))

                if not symbol or qty <= 0:
                    continue

                status = "ENTRY_SENT"
                entry_order_id: str | None = None
                last_error: str | None = None

                try:
                    entry_order_payload = self._build_entry_order_payload(
                        symbol=symbol,
                        side=side,
                        qty=qty,
                        order_type=order_type,
                        order_price=order_price,
                        exchange=exchange,
                        security_type=security_type,
                        cash_margin=cash_margin,
                        margin_trade_type=margin_trade_type,
                        deliv_type=deliv_type,
                        fund_type=fund_type,
                        account_type=account_type,
                        expire_day=expire_day,
                    )
                    entry_order_id = self.client.send_order(entry_order_payload)
                    success_count += 1
                except Exception as exc:  # noqa: BLE001
                    status = "ERROR"
                    last_error = str(exc)
                    failure_count += 1

                conn.execute(
                    """
                    INSERT INTO orders (
                        symbol, side, quantity, order_price, order_type,
                        time_in_force, take_profit, stop_loss, note,
                        status, created_at, updated_at,
                        exchange, security_type, cash_margin, margin_trade_type, deliv_type,
                        fund_type, account_type, expire_day,
                        entry_order_id, tp_order_id, sl_order_id, hold_id,
                        protection_status, last_error
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        symbol,
                        side,
                        qty,
                        order_price,
                        order_type,
                        time_in_force,
                        take_profit,
                        stop_loss,
                        note,
                        status,
                        created_at,
                        created_at,
                        exchange,
                        security_type,
                        cash_margin,
                        margin_trade_type,
                        deliv_type,
                        fund_type,
                        account_type,
                        expire_day,
                        entry_order_id,
                        None,
                        None,
                        None,
                        "NOT_SENT",
                        last_error,
                    ),
                )
            conn.commit()

        if success_count == 0 and failure_count > 0:
            raise RuntimeError("全件失敗しました。モニター画面で詳細を確認してください")

        return {
            "status": "ENTRY_SENT",
            "count": success_count,
            "failed": failure_count,
        }

    def get_monitor_data(self) -> Dict[str, Any]:
        if self.client:
            self._sync_orders_with_api()
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            orders = conn.execute(
                """
                SELECT id, symbol, side, quantity, status, updated_at,
                       entry_order_id, tp_order_id, sl_order_id, hold_id, last_error
                FROM orders
                ORDER BY id DESC
                LIMIT 30
                """
            ).fetchall()

        status_rows = []
        for row in orders:
            extra = []
            if row["entry_order_id"]:
                extra.append(f"entry={row['entry_order_id']}")
            if row["tp_order_id"]:
                extra.append(f"tp={row['tp_order_id']}")
            if row["sl_order_id"]:
                extra.append(f"sl={row['sl_order_id']}")
            if row["hold_id"]:
                extra.append(f"hold={row['hold_id']}")
            if row["last_error"]:
                extra.append(f"err={row['last_error']}")

            status_rows.append(
                {
                    "orderId": row["id"],
                    "symbol": row["symbol"],
                    "side": "買い" if row["side"] == "BUY" else "売り",
                    "quantity": row["quantity"],
                    "status": " | ".join([row["status"], *extra]) if extra else row["status"],
                    "updatedAt": self._to_hhmmss(row["updated_at"]),
                }
            )

        active_count = sum(
            1 for row in status_rows if not row["status"].startswith("EXIT_FILLED") and "ERROR" not in row["status"]
        )
        filled_count = sum(1 for row in status_rows if row["status"].startswith("EXIT_FILLED"))

        return {
            "activeCount": active_count,
            "filledCount": filled_count,
            "realizedPnl": 0,
            "statusRows": status_rows,
            "snapshotAt": self._to_hhmmss(self._now_iso()),
        }

    def _sync_orders_with_api(self) -> None:
        assert self.client is not None

        try:
            api_orders = self.client.get_orders(product=2)
            positions = self.client.get_positions(product=2)
        except Exception as exc:  # noqa: BLE001
            self._mark_sync_error(str(exc))
            return

        orders_by_id = {
            str(item.get("ID")): item
            for item in api_orders
            if item.get("ID") is not None
        }

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT *
                FROM orders
                WHERE status NOT IN ('ERROR', 'EXIT_FILLED')
                ORDER BY id ASC
                LIMIT 50
                """
            ).fetchall()

            now = self._now_iso()
            for row in rows:
                entry_order_id = row["entry_order_id"]
                hold_id = row["hold_id"]

                if not entry_order_id:
                    continue

                api_entry = orders_by_id.get(str(entry_order_id))
                is_entry_done = self._is_order_completed(api_entry)
                if is_entry_done and not hold_id:
                    hold_id = self._find_hold_id(positions, row)
                    if hold_id:
                        conn.execute(
                            """
                            UPDATE orders
                            SET hold_id = ?, status = 'POSITION_IDENTIFIED', updated_at = ?, last_error = NULL
                            WHERE id = ?
                            """,
                            (hold_id, now, row["id"]),
                        )

                if hold_id and row["protection_status"] != "SENT":
                    try:
                        tp_id, sl_id = self._send_protection_orders(row, hold_id)
                        conn.execute(
                            """
                            UPDATE orders
                            SET tp_order_id = ?, sl_order_id = ?, protection_status = 'SENT',
                                status = 'MONITORING', updated_at = ?, last_error = NULL
                            WHERE id = ?
                            """,
                            (tp_id, sl_id, now, row["id"]),
                        )
                    except Exception as exc:  # noqa: BLE001
                        conn.execute(
                            """
                            UPDATE orders
                            SET status = 'ERROR', last_error = ?, updated_at = ?
                            WHERE id = ?
                            """,
                            (str(exc), now, row["id"]),
                        )
                        continue

                if hold_id and not self._hold_exists(positions, hold_id):
                    self._cancel_if_alive(row["tp_order_id"], orders_by_id)
                    self._cancel_if_alive(row["sl_order_id"], orders_by_id)
                    conn.execute(
                        """
                        UPDATE orders
                        SET status = 'EXIT_FILLED', updated_at = ?, last_error = NULL
                        WHERE id = ?
                        """,
                        (now, row["id"]),
                    )

            conn.commit()

    def _send_protection_orders(self, row: sqlite3.Row, hold_id: str) -> tuple[str | None, str | None]:
        assert self.client is not None

        close_side = "1" if row["side"] == "BUY" else "2"
        trigger_under_over = 2 if row["side"] == "BUY" else 1

        tp_order_id: str | None = None
        sl_order_id: str | None = None

        if row["take_profit"] is not None:
            tp_payload = {
                "Symbol": row["symbol"],
                "Exchange": row["exchange"],
                "SecurityType": row["security_type"],
                "Side": close_side,
                "CashMargin": 3,
                "MarginTradeType": row["margin_trade_type"],
                "DelivType": 0,
                "FundType": "11",
                "AccountType": row["account_type"],
                "Qty": row["quantity"],
                "FrontOrderType": 20,
                "Price": float(row["take_profit"]),
                "ExpireDay": row["expire_day"],
                "ClosePositions": [{"HoldID": str(hold_id), "Qty": row["quantity"]}],
            }
            tp_order_id = self.client.send_order(tp_payload)

        if row["stop_loss"] is not None:
            sl_payload = {
                "Symbol": row["symbol"],
                "Exchange": row["exchange"],
                "SecurityType": row["security_type"],
                "Side": close_side,
                "CashMargin": 3,
                "MarginTradeType": row["margin_trade_type"],
                "DelivType": 0,
                "FundType": "11",
                "AccountType": row["account_type"],
                "Qty": row["quantity"],
                "FrontOrderType": 30,
                "Price": 0,
                "ExpireDay": row["expire_day"],
                "ReverseLimitOrder": {
                    "TriggerSec": 1,
                    "TriggerPrice": float(row["stop_loss"]),
                    "UnderOver": trigger_under_over,
                    "AfterHitOrderType": 10,
                    "AfterHitPrice": 0,
                },
                "ClosePositions": [{"HoldID": str(hold_id), "Qty": row["quantity"]}],
            }
            sl_order_id = self.client.send_order(sl_payload)

        return tp_order_id, sl_order_id

    def _cancel_if_alive(self, order_id: str | None, orders_by_id: Dict[str, Dict[str, Any]]) -> None:
        if not order_id:
            return
        current = orders_by_id.get(str(order_id))
        if not current:
            return
        if self._is_order_completed(current):
            return

        assert self.client is not None
        self.client.cancel_order(order_id)

    @staticmethod
    def _is_order_completed(order: Dict[str, Any] | None) -> bool:
        if not order:
            return False
        state = order.get("State")
        if state in (4, 5):
            return True

        details = order.get("Details") or []
        if any((item.get("RecType") == 8) for item in details if isinstance(item, dict)):
            return True
        return False

    @staticmethod
    def _find_hold_id(positions: List[Dict[str, Any]], row: sqlite3.Row) -> str | None:
        desired_side = "2" if row["side"] == "BUY" else "1"
        symbol = str(row["symbol"])

        for position in positions:
            if str(position.get("Symbol")) != symbol:
                continue
            if str(position.get("Side")) != desired_side:
                continue
            hold_id = position.get("HoldID")
            leaves_qty = int(position.get("LeavesQty") or 0)
            if hold_id and leaves_qty >= int(row["quantity"]):
                return str(hold_id)
        return None

    @staticmethod
    def _hold_exists(positions: List[Dict[str, Any]], hold_id: str) -> bool:
        return any(str(pos.get("HoldID")) == str(hold_id) for pos in positions)

    def _mark_sync_error(self, error_message: str) -> None:
        now = self._now_iso()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE orders
                SET last_error = ?, updated_at = ?
                WHERE status NOT IN ('ERROR', 'EXIT_FILLED')
                """,
                (error_message, now),
            )
            conn.commit()

    def _initialize_client(self) -> None:
        try:
            config = self._load_config()
            self.client = KabuStationClient(config)
        except Exception as exc:  # noqa: BLE001
            self.client = None
            self.config_error = str(exc)

    def _load_config(self) -> KabuStationConfig:
        if not CONFIG_PATH.exists():
            example_path = CONFIG_DIR / "kabusapi_config.ini.example"
            raise FileNotFoundError(
                "設定ファイルがありません。\n"
                f"設定先: {CONFIG_PATH}\n"
                f"雛形: {example_path}\n"
                "雛形をコピーして作成してください。"
            )

        parser = configparser.ConfigParser()
        parser.read(CONFIG_PATH, encoding="utf-8")

        if "kabusapi" not in parser:
            raise ValueError("[kabusapi] セクションが必要です")

        section = parser["kabusapi"]
        base_url = (section.get("base_url") or "").strip()
        api_password = (section.get("api_password") or "").strip()
        timeout_sec = float(section.get("timeout_sec") or "8")

        if not base_url:
            raise ValueError("base_url を設定してください")
        if not api_password:
            raise ValueError("api_password を設定してください")

        return KabuStationConfig(
            base_url=base_url,
            api_password=api_password,
            timeout_sec=timeout_sec,
        )

    @staticmethod
    def _build_entry_order_payload(
        *,
        symbol: str,
        side: str,
        qty: int,
        order_type: str,
        order_price: float,
        exchange: int,
        security_type: int,
        cash_margin: int,
        margin_trade_type: int,
        deliv_type: int,
        fund_type: str,
        account_type: int,
        expire_day: int,
    ) -> Dict[str, Any]:
        front_order_type = 10 if order_type == "MARKET" else 20

        return {
            "Symbol": symbol,
            "Exchange": exchange,
            "SecurityType": security_type,
            "Side": "2" if side == "BUY" else "1",
            "CashMargin": cash_margin,
            "MarginTradeType": margin_trade_type,
            "DelivType": deliv_type,
            "FundType": fund_type,
            "AccountType": account_type,
            "Qty": qty,
            "FrontOrderType": front_order_type,
            "Price": 0 if front_order_type == 10 else order_price,
            "ExpireDay": expire_day,
        }
    def _initialize_db(self) -> None:
        DB_DIR.mkdir(parents=True, exist_ok=True)

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    order_price REAL NOT NULL,
                    order_type TEXT NOT NULL,
                    time_in_force TEXT NOT NULL,
                    take_profit REAL,
                    stop_loss REAL,
                    note TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    exchange INTEGER NOT NULL DEFAULT 1,
                    security_type INTEGER NOT NULL DEFAULT 1,
                    cash_margin INTEGER NOT NULL DEFAULT 2,
                    margin_trade_type INTEGER NOT NULL DEFAULT 1,
                    deliv_type INTEGER NOT NULL DEFAULT 0,
                    fund_type TEXT NOT NULL DEFAULT '11',
                    account_type INTEGER NOT NULL DEFAULT 4,
                    expire_day INTEGER NOT NULL DEFAULT 0,
                    entry_order_id TEXT,
                    tp_order_id TEXT,
                    sl_order_id TEXT,
                    hold_id TEXT,
                    protection_status TEXT NOT NULL DEFAULT 'NOT_SENT',
                    last_error TEXT
                )
                """
            )
            self._migrate_orders_table(conn)
            conn.commit()

    def _migrate_orders_table(self, conn: sqlite3.Connection) -> None:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(orders)").fetchall()}

        required_columns = {
            "exchange": "INTEGER NOT NULL DEFAULT 1",
            "security_type": "INTEGER NOT NULL DEFAULT 1",
            "cash_margin": "INTEGER NOT NULL DEFAULT 2",
            "margin_trade_type": "INTEGER NOT NULL DEFAULT 1",
            "deliv_type": "INTEGER NOT NULL DEFAULT 0",
            "fund_type": "TEXT NOT NULL DEFAULT '11'",
            "account_type": "INTEGER NOT NULL DEFAULT 4",
            "expire_day": "INTEGER NOT NULL DEFAULT 0",
            "entry_order_id": "TEXT",
            "tp_order_id": "TEXT",
            "sl_order_id": "TEXT",
            "hold_id": "TEXT",
            "protection_status": "TEXT NOT NULL DEFAULT 'NOT_SENT'",
            "last_error": "TEXT",
        }


        for name, ddl in required_columns.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE orders ADD COLUMN {name} {ddl}")

    @staticmethod
    def _parse_nullable_number(value: Any) -> float | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        return float(text)

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _to_hhmmss(iso_ts: str) -> str:
        dt = datetime.fromisoformat(iso_ts)
        return dt.astimezone().strftime("%H:%M:%S")


if __name__ == "__main__":
    api = TradingConsoleApi()
    webview.create_window(
        title="Auto Kabu Trade Console",
        url=str((BASE_DIR / "ui" / "index.html").resolve()),
        js_api=api,
        fullscreen=True,
        width=1420,
        height=900,
        min_size=(1080, 720),
    )
    webview.start(debug=False)