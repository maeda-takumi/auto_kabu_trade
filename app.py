from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List

import webview

BASE_DIR = Path(__file__).resolve().parent
MD_DIR = BASE_DIR / "md"


@dataclass
class DocSummary:
    title: str
    updated: str
    highlights: List[str]
    file: str


class TradingDashboardApi:
    def __init__(self) -> None:
        self.is_running = False

    def get_initial_data(self) -> dict:
        summaries = [asdict(item) for item in self._load_doc_summaries()]
        return {
            "status": "停止中",
            "isRunning": self.is_running,
            "summaries": summaries,
            "riskRules": [
                "1回あたりの最大発注金額を監視",
                "1日の最大損失を超えたら停止",
                "想定外建玉を検知したら緊急停止",
            ],
            "stateFlow": [
                "SIGNAL_DETECTED",
                "ENTRY_ORDER_SENT",
                "ENTRY_FILLED",
                "POSITION_IDENTIFIED",
                "TP_SL_ORDERS_SENT",
                "EXIT_FILLED",
                "CLOSED",
            ],
        }

    def toggle_trading(self) -> dict:
        self.is_running = not self.is_running
        return {
            "isRunning": self.is_running,
            "status": "稼働中" if self.is_running else "停止中",
        }

    def _load_doc_summaries(self) -> List[DocSummary]:
        summaries: List[DocSummary] = []
        files = [
            MD_DIR / "kabu_station_api_order_guide.md",
            MD_DIR / "kabu_station_trading_logic.md",
            MD_DIR / "kabu_station_auto_trading_function_groups.md",
        ]

        for file in files:
            text = file.read_text(encoding="utf-8")
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            title = lines[0].lstrip("# ") if lines else file.stem

            updated = "更新日未記載"
            for line in lines[:8]:
                if "更新日" in line:
                    updated = line.replace("更新日:", "").strip()
                    break

            highlights = []
            for line in lines:
                if line.startswith("- "):
                    highlights.append(line.removeprefix("- ").strip())
                if len(highlights) == 4:
                    break

            summaries.append(
                DocSummary(
                    title=title,
                    updated=updated,
                    highlights=highlights,
                    file=file.name,
                )
            )

        return summaries


if __name__ == "__main__":
    api = TradingDashboardApi()
    webview.create_window(
        title="Auto Kabu Trade Console",
        url=str((BASE_DIR / "ui" / "index.html").resolve()),
        js_api=api,
        width=1360,
        height=860,
        min_size=(1024, 700),
    )
    webview.start(debug=False)