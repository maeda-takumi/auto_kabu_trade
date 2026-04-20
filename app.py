from __future__ import annotations

import random
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import webview

BASE_DIR = Path(__file__).resolve().parent
DB_DIR = BASE_DIR / "db"
DB_PATH = DB_DIR / "trade_data.sqlite3"

STATUS_PROGRESS = {
    "PENDING": "WORKING",
    "WORKING": "FILLED",
    "FILLED": "FILLED",
}


class TradingConsoleApi:
    def __init__(self) -> None:
        self.db_path = DB_PATH
        self._initialize_db()

    def get_initial_data(self) -> Dict[str, str]:
        return {"dbStatus": f"DB接続: {self.db_path.name}"}

    def submit_orders(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        entries = payload.get("entries") or []
        if not entries:
            raise ValueError("entries が空です")

        side = payload.get("side") or "BUY"
        order_type = payload.get("orderType") or "MARKET"
        time_in_force = payload.get("timeInForce") or "DAY"

        exchange = int(payload.get("exchange") or 1)
        security_type = int(payload.get("securityType") or 1)
        cash_margin = int(payload.get("cashMargin") or 1)
        margin_trade_type = int(payload.get("marginTradeType") or 1)
        deliv_type = int(payload.get("delivType") or 2)
        fund_type = str(payload.get("fundType") or "AA")
        account_type = int(payload.get("accountType") or 4)
        expire_day = int(payload.get("expireDay") or 0)
        note = (payload.get("note") or "").strip()

        created_at = self._now_iso()

        values = []
        for entry in entries:
            symbol = (entry.get("symbol") or "").strip()
            if not symbol:
                continue

            values.append(
                (
                    symbol,
                    side,
                    int(entry.get("quantity") or 0),
                    float(entry.get("orderPrice") or 0),
                    order_type,
                    time_in_force,
                    self._parse_nullable_number(entry.get("takeProfit")),
                    self._parse_nullable_number(entry.get("stopLoss")),
                    note,
                    "PENDING",
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
                )
            )

        if not values:
            raise ValueError("有効な銘柄コードがありません")

        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                """
                INSERT INTO orders (
                    symbol, side, quantity, order_price, order_type,
                    time_in_force, take_profit, stop_loss, note, status, created_at, updated_at,
                    exchange, security_type, cash_margin, margin_trade_type, deliv_type,
                    fund_type, account_type, expire_day
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            conn.commit()

        return {"status": "PENDING", "count": len(values)}

    def get_monitor_data(self) -> Dict[str, Any]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            self._advance_mock_status(conn)

            orders = conn.execute(
                """
                SELECT id, symbol, side, quantity, status, updated_at
                FROM orders
                ORDER BY id DESC
                LIMIT 30
                """
            ).fetchall()

        status_rows = [
            {
                "orderId": row["id"],
                "symbol": row["symbol"],
                "side": "買い" if row["side"] == "BUY" else "売り",
                "quantity": row["quantity"],
                "status": row["status"],
                "updatedAt": self._to_hhmmss(row["updated_at"]),
            }
            for row in orders
        ]

        active_count = sum(1 for row in status_rows if row["status"] in {"PENDING", "WORKING"})
        filled_count = sum(1 for row in status_rows if row["status"] == "FILLED")
        realized_pnl = filled_count * 1200

        return {
            "activeCount": active_count,
            "filledCount": filled_count,
            "realizedPnl": realized_pnl,
            "statusRows": status_rows,
            "snapshotAt": self._to_hhmmss(self._now_iso()),
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
                    cash_margin INTEGER NOT NULL DEFAULT 1,
                    margin_trade_type INTEGER NOT NULL DEFAULT 1,
                    deliv_type INTEGER NOT NULL DEFAULT 2,
                    fund_type TEXT NOT NULL DEFAULT 'AA',
                    account_type INTEGER NOT NULL DEFAULT 4,
                    expire_day INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            self._migrate_orders_table(conn)
            conn.commit()

    def _migrate_orders_table(self, conn: sqlite3.Connection) -> None:
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(orders)").fetchall()
        }

        required_columns = {
            "exchange": "INTEGER NOT NULL DEFAULT 1",
            "security_type": "INTEGER NOT NULL DEFAULT 1",
            "cash_margin": "INTEGER NOT NULL DEFAULT 1",
            "margin_trade_type": "INTEGER NOT NULL DEFAULT 1",
            "deliv_type": "INTEGER NOT NULL DEFAULT 2",
            "fund_type": "TEXT NOT NULL DEFAULT 'AA'",
            "account_type": "INTEGER NOT NULL DEFAULT 4",
            "expire_day": "INTEGER NOT NULL DEFAULT 0",
        }

        for name, ddl in required_columns.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE orders ADD COLUMN {name} {ddl}")

    def _advance_mock_status(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute(
            """
            SELECT id, status
            FROM orders
            WHERE status IN ('PENDING', 'WORKING')
            ORDER BY id DESC
            LIMIT 12
            """
        ).fetchall()

        now = self._now_iso()

        for row in rows:
            if random.random() < 0.35:
                next_status = STATUS_PROGRESS[row["status"]]
                conn.execute(
                    "UPDATE orders SET status = ?, updated_at = ? WHERE id = ?",
                    (next_status, now, row["id"]),
                )

        conn.commit()

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
        width=1420,
        height=900,
        min_size=(1080, 720),
    )
    webview.start(debug=False)