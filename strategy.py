from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Optional

import pandas as pd

from calculator import HISTORY_FILE


def _load_history_for_strategy(csv_path: str) -> pd.DataFrame:
    path = Path(csv_path)
    history_df = pd.read_csv(path, encoding="utf-8-sig")

    history_df["date"] = pd.to_datetime(history_df["date"], errors="coerce")
    for col in ["cny_hkd", "usd_hkd", "cost"]:
        history_df[col] = pd.to_numeric(history_df[col], errors="coerce")

    history_df = history_df.dropna().sort_values("date").reset_index(drop=True)

    print("策略读取数据条数:", len(history_df))
    return history_df


def _analyze_quantile_strategy(history_df: pd.DataFrame) -> Dict[str, str]:
    latest_row = history_df.iloc[-1]
    latest_cost = float(latest_row["cost"])

    q25 = float(history_df["cost"].quantile(0.25))
    q75 = float(history_df["cost"].quantile(0.75))

    # === 判断区间 ===
    if latest_cost < q25:
        level = "低位（人民币强）"
        action = "?? 建议：加大换汇"
        percent = "+50%"
    elif latest_cost > q75:
        level = "高位（人民币弱）"
        action = "?? 建议：减少换汇"
        percent = "-50%"
    else:
        level = "中位"
        action = "?? 建议：正常定投"
        percent = "0%"

    quantile_info = f"当前处于：{level}"

    return {
        "strategy_a_signal": action,
        "quantile_info": quantile_info,
        "adjust_percent": percent,
        "q25": q25,
        "q75": q75,
        "latest_cost": latest_cost,
    }


def _analyze_reverse_signal(latest_cost: float, q25: float, q75: float) -> str:
    """是否换回人民币"""

    if latest_cost > q75:
        return "?? 可考虑将部分资金换回人民币（当前汇率偏贵）"
    elif latest_cost < q25:
        return "?? 不建议换回人民币（当前人民币强）"
    else:
        return "? 暂无换回人民币优势"


def _analyze_linked_rate_strategy(usd_hkd: float) -> str:
    if usd_hkd <= 7.78:
        return "? 港币强（可换美元）"
    elif usd_hkd >= 7.83:
        return "? 港币弱（可暂缓换美元）"
    return "? 港币中性"


def run_strategy_analysis(
    csv_path: str = HISTORY_FILE,
    logger: Optional[logging.Logger] = None,
) -> Dict[str, str]:

    history_df = _load_history_for_strategy(csv_path)
    latest_row = history_df.iloc[-1]

    quantile = _analyze_quantile_strategy(history_df)

    reverse_signal = _analyze_reverse_signal(
        quantile["latest_cost"],
        quantile["q25"],
        quantile["q75"],
    )

    strategy_b = _analyze_linked_rate_strategy(float(latest_row["usd_hkd"]))

    final_advice = (
        f"{quantile['strategy_a_signal']}\n"
        f"建议调整幅度：{quantile['adjust_percent']}\n"
        f"{reverse_signal}"
    )

    return {
        "date": latest_row["date"].strftime("%Y-%m-%d"),
        "strategy_a_signal": quantile["strategy_a_signal"],
        "strategy_b_signal": strategy_b,
        "quantile_info": quantile["quantile_info"],
        "final_advice": final_advice,
    }