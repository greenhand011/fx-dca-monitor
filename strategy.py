"""策略分析模块（修复版 - 支持真实历史数据）"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Optional

import pandas as pd

from calculator import HISTORY_FILE


def _parse_date_safe(date_series: pd.Series) -> pd.Series:
    """增强版日期解析：兼容 2025/12/26 和 2025-12-26"""

    # 统一替换 / → -
    date_series = date_series.astype(str).str.strip().str.replace("/", "-", regex=False)

    # 强制格式解析（避免 pandas 猜错）
    parsed = pd.to_datetime(date_series, format="%Y-%m-%d", errors="coerce")

    return parsed


def _load_history_for_strategy(csv_path: str) -> pd.DataFrame:
    """读取并清洗历史数据"""

    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"历史数据文件不存在：{path.resolve()}")

    history_df = pd.read_csv(path, encoding="utf-8-sig")

    required_columns = ["date", "cny_hkd", "usd_hkd", "cost"]
    history_df = history_df[required_columns].copy()

    # ✅ 修复点1：强制标准化日期格式
    history_df["date"] = _parse_date_safe(history_df["date"])

    # ✅ 修复点2：数值强制转换
    for col in ["cny_hkd", "usd_hkd", "cost"]:
        history_df[col] = pd.to_numeric(history_df[col], errors="coerce")

    # ✅ 修复点3：只丢弃真正坏数据
    history_df = history_df.dropna(subset=["date", "cost"])

    # ✅ 修复点4：排序 + 去重
    history_df = (
        history_df.sort_values("date")
        .drop_duplicates(subset=["date"], keep="last")
        .reset_index(drop=True)
    )

    print("✅ 策略读取数据条数:", len(history_df))
    print("📅 日期范围:", history_df["date"].min(), "→", history_df["date"].max())

    return history_df


def _analyze_quantile_strategy(history_df: pd.DataFrame) -> Dict[str, str]:
    """策略A：分位数分析（修复版）"""

    latest_row = history_df.iloc[-1]
    latest_date = latest_row["date"]

    # ✅ 修复点5：确保窗口正确
    start_date = latest_date - pd.Timedelta(days=89)
    recent_df = history_df[history_df["date"] >= start_date].copy()

    print("📊 最近90天样本数:", len(recent_df))

    if len(recent_df) < 10:
        return {
            "strategy_a_signal": "⏳ 冷启动：样本少于 10 条，暂不做分位判断",
            "quantile_info": f"最近90天有效样本仅 {len(recent_df)} 条，继续积累数据后再判断高低位。",
        }

    q25 = recent_df["cost"].quantile(0.25)
    q75 = recent_df["cost"].quantile(0.75)
    latest_cost = latest_row["cost"]

    if latest_cost < q25:
        signal = "🟢 强烈建议：人民币强势，适合多换汇"
    elif latest_cost > q75:
        signal = "🔴 暂缓操作：当前换汇成本偏高"
    else:
        signal = "🟡 中性：处于正常区间"

    return {
        "strategy_a_signal": signal,
        "quantile_info": (
            f"最近90天样本 {len(recent_df)} 条，"
            f"25%={q25:.6f}，75%={q75:.6f}，当前={latest_cost:.6f}"
        ),
    }


def _analyze_reverse_strategy(cost: float, q25: float, q75: float) -> str:
    """🔥 新增：什么时候换回人民币"""

    if cost > q75:
        return "💰 建议：当前美元较强，可考虑分批换回人民币"
    elif cost < q25:
        return "🚫 不建议换回人民币：当前人民币强势"
    else:
        return "➖ 观望：未到明显换回窗口"


def _analyze_linked_rate_strategy(usd_hkd: float) -> str:
    if usd_hkd <= 7.78:
        return "⭐️ 港币强：可换美元"
    if usd_hkd >= 7.83:
        return "⚠️ 港币弱：可暂缓换美元"
    return "➖ 港币中性"


def run_strategy_analysis(
    csv_path: str = HISTORY_FILE,
    logger: Optional[logging.Logger] = None,
) -> Dict[str, str]:

    history_df = _load_history_for_strategy(csv_path)
    latest_row = history_df.iloc[-1]

    quantile_result = _analyze_quantile_strategy(history_df)

    usd_hkd = float(latest_row["usd_hkd"])
    strategy_b = _analyze_linked_rate_strategy(usd_hkd)

    final_advice = quantile_result["strategy_a_signal"]

    return {
        "date": latest_row["date"].strftime("%Y-%m-%d"),
        "strategy_a_signal": quantile_result["strategy_a_signal"],
        "strategy_b_signal": strategy_b,
        "quantile_info": quantile_result["quantile_info"],
        "final_advice": final_advice,
        "sample_count": str(len(history_df)),
    }