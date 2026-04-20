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

    def submit_order(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        symbol = (payload.get("symbol") or "").strip()
        side = payload.get("side") or "BUY"
        quantity = int(payload.get("quantity") or 0)
        order_price = float(payload.get("orderPrice") or 0)
        order_type = payload.get("orderType") or "MARKET"
        time_in_force = payload.get("timeInForce") or "DAY"

        take_profit = self._parse_nullable_number(payload.get("takeProfit"))
        stop_loss = self._parse_nullable_number(payload.get("stopLoss"))
        note = (payload.get("note") or "").strip()

        created_at = self._now_iso()

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO orders (
                    symbol, side, quantity, order_price, order_type,
                    time_in_force, take_profit, stop_loss, note, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    symbol,
                    side,
                    quantity,
                    order_price,
                    order_type,
                    time_in_force,
                    take_profit,
                    stop_loss,
                    note,
                    "PENDING",
                    created_at,
                    created_at,
                ),
            )
            conn.commit()
            order_id = cursor.lastrowid

        return {"orderId": order_id, "status": "PENDING"}

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
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

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