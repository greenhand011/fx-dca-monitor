"""策略分析模块。

本模块基于历史 CSV 数据给出两类策略判断：
1. 策略 A：最近 90 天综合成本 cost 的 25% / 75% 分位判断；
2. 策略 B：基于港币联系汇率区间，对 USD/HKD 强弱进行额外提示。

同时考虑冷启动问题：
当有效样本少于 10 条时，不进行分位判断，避免信号失真。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Optional

import pandas as pd

from calculator import HISTORY_FILE


def _load_history_for_strategy(csv_path: str) -> pd.DataFrame:
    """读取并清洗历史数据，为策略计算做准备。"""

    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"历史数据文件不存在：{path.resolve()}")

    history_df = pd.read_csv(path, encoding="utf-8-sig")
    if history_df.empty:
        raise ValueError("历史数据文件为空，暂时无法执行策略分析。")

    required_columns = ["date", "cny_hkd", "usd_hkd", "cost"]
    missing_columns = [column for column in required_columns if column not in history_df.columns]
    if missing_columns:
        raise ValueError(f"历史数据缺少必要列：{missing_columns}")

    # 先仅保留必要列，避免其他脏列干扰。
    history_df = history_df[required_columns].copy()

    # 日期解析必须宽松但可控：解析失败的行才会被丢弃，不能误伤全部历史数据。
    history_df["date"] = pd.to_datetime(history_df["date"].astype(str).str.strip(), errors="coerce")
    for column in ["cny_hkd", "usd_hkd", "cost"]:
        history_df[column] = pd.to_numeric(history_df[column], errors="coerce")

    # dropna 只清理真正缺失的脏数据，不应该清空正常历史样本。
    history_df = history_df.dropna(subset=required_columns).copy()
    history_df = history_df.sort_values("date").drop_duplicates(subset=["date"], keep="last").reset_index(drop=True)
    print("策略读取数据条数:", len(history_df))

    if history_df.empty:
        raise ValueError("历史数据清洗后为空，无法执行策略分析。")

    return history_df


def _analyze_quantile_strategy(history_df: pd.DataFrame) -> Dict[str, str]:
    """执行基于最近 90 天成本分位的策略 A。"""

    latest_row = history_df.iloc[-1]

    # 以最近一条记录日期作为锚点，向前回看 90 天。
    latest_date = latest_row["date"]
    recent_df = history_df[history_df["date"] >= latest_date - pd.Timedelta(days=89)].copy()

    if len(recent_df) < 10:
        return {
            "strategy_a_signal": "⏳ 冷启动：样本少于 10 条，暂不做分位判断",
            "quantile_info": (
                f"最近90天有效样本仅 {len(recent_df)} 条，继续积累数据后再判断高低位。"
            ),
        }

    q25 = float(recent_df["cost"].quantile(0.25))
    q75 = float(recent_df["cost"].quantile(0.75))
    latest_cost = float(latest_row["cost"])

    if latest_cost < q25:
        signal = "🟢 强烈建议：当前综合成本低于最近90天25%分位"
    elif latest_cost > q75:
        signal = "🔴 暂缓操作：当前综合成本高于最近90天75%分位"
    else:
        signal = "🟡 中性观察：当前综合成本位于最近90天中间区间"

    quantile_info = (
        f"最近90天样本 {len(recent_df)} 条，25%分位={q25:.6f}，"
        f"75%分位={q75:.6f}，当前成本={latest_cost:.6f}。"
    )

    return {
        "strategy_a_signal": signal,
        "quantile_info": quantile_info,
    }


def _analyze_linked_rate_strategy(usd_hkd: float) -> str:
    """执行基于港币联系汇率区间的策略 B。"""

    if usd_hkd <= 7.78:
        return "⭐️ 强：USD/HKD 位于联系汇率强方附近"
    if usd_hkd >= 7.83:
        return "⚠️ 弱：USD/HKD 位于联系汇率弱方附近"
    return "➖ 中性：USD/HKD 位于联系汇率区间中部"


def _build_final_advice(strategy_a_signal: str, strategy_b_signal: str) -> str:
    """综合两类策略信号，输出更易理解的最终建议。"""

    if "🟢" in strategy_a_signal and "⭐️" in strategy_b_signal:
        return "✅ 建议优先执行：成本分位较优，且港币位于偏强区间。"

    if "🔴" in strategy_a_signal or "⚠️" in strategy_b_signal:
        return "🛑 建议偏谨慎：可暂缓、分批缩量，等待更合适窗口。"

    if "⏳" in strategy_a_signal and "⭐️" in strategy_b_signal:
        return "📈 建议小额执行：分位样本不足，但联系汇率信号偏强。"

    return "📌 建议按计划小额定投，并持续观察历史分位变化。"


def run_strategy_analysis(
    csv_path: str = HISTORY_FILE,
    logger: Optional[logging.Logger] = None,
) -> Dict[str, str]:
    """读取历史数据并返回完整策略分析结果。"""

    history_df = _load_history_for_strategy(csv_path)
    latest_row = history_df.iloc[-1]

    quantile_result = _analyze_quantile_strategy(history_df)
    strategy_b_signal = _analyze_linked_rate_strategy(float(latest_row["usd_hkd"]))
    final_advice = _build_final_advice(
        quantile_result["strategy_a_signal"],
        strategy_b_signal,
    )

    result = {
        "date": latest_row["date"].strftime("%Y-%m-%d"),
        "strategy_a_signal": quantile_result["strategy_a_signal"],
        "strategy_b_signal": strategy_b_signal,
        "quantile_info": quantile_result["quantile_info"],
        "final_advice": final_advice,
        "sample_count": str(len(history_df)),
    }

    if logger:
        logger.info("策略分析完成：%s | %s", result["strategy_a_signal"], result["strategy_b_signal"])

    return result
