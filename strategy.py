# -*- coding: utf-8 -*-
"""资金调度策略模块。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Optional

import pandas as pd

from calculator import HISTORY_FILE
from portfolio import PortfolioConfig, get_portfolio_config, hkd_months_buffer, monthly_hkd_budget


def _load_history_for_strategy(csv_path: str) -> pd.DataFrame:
    """读取并清洗历史数据。"""

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

    history_df = history_df[required_columns].copy()
    history_df["date"] = pd.to_datetime(history_df["date"].astype(str).str.strip(), errors="coerce")
    for column in ["cny_hkd", "usd_hkd", "cost"]:
        history_df[column] = pd.to_numeric(history_df[column], errors="coerce")

    history_df = history_df.dropna(subset=required_columns).copy()
    history_df = (
        history_df.sort_values("date")
        .drop_duplicates(subset=["date"], keep="last")
        .reset_index(drop=True)
    )

    print("策略读取数据条数:", len(history_df))

    if history_df.empty:
        raise ValueError("历史数据清洗后为空，无法执行策略分析。")

    return history_df


def _classify_market_position(latest_cost: float, q25: float, q75: float) -> Dict[str, str]:
    """把分位结果翻译成更容易理解的人话。"""

    if latest_cost < q25:
        return {
            "level": "低位",
            "bias": "人民币强",
            "label": "低位（人民币强）",
            "tag": "LOW",
        }
    if latest_cost > q75:
        return {
            "level": "高位",
            "bias": "人民币弱",
            "label": "高位（人民币弱）",
            "tag": "HIGH",
        }
    return {
        "level": "中位",
        "bias": "中性",
        "label": "中位（均衡）",
        "tag": "MID",
    }


def _build_rmb_to_hkd_advice(position_tag: str, monthly_invest_rmb: float) -> Dict[str, str]:
    """生成 RMB -> HKD 的换汇建议。"""

    if position_tag == "LOW":
        target_rmb = monthly_invest_rmb * 1.5
        top_rmb = monthly_invest_rmb * 2.0
        return {
            "title": "建议：强力加仓",
            "percent": "+50% ~ +100%",
            "example": f"{monthly_invest_rmb:.0f} → {target_rmb:.0f} ~ {top_rmb:.0f} RMB",
            "detail": "当前属于低位，适合把本月定投预算抬高一档。",
        }

    if position_tag == "HIGH":
        lower_rmb = monthly_invest_rmb * 0.5
        return {
            "title": "建议：明显减仓",
            "percent": "-50% ~ -100%",
            "example": f"{monthly_invest_rmb:.0f} → 0 ~ {lower_rmb:.0f} RMB",
            "detail": "当前属于高位，尽量少换或暂停换汇。",
        }

    return {
        "title": "建议：正常定投",
        "percent": "0%",
        "example": f"{monthly_invest_rmb:.0f} RMB",
        "detail": "当前处于中位，按月正常执行即可。",
    }


def _build_hkd_stockpile_advice(
    position_tag: str,
    hk_cash: float,
    monthly_invest_rmb: float,
    cost: float,
) -> str:
    """判断是否应该提前囤港币。"""

    monthly_hkd = monthly_hkd_budget(PortfolioConfig(monthly_invest_rmb=monthly_invest_rmb), cost)
    target_3m = monthly_hkd * 3
    target_6m = monthly_hkd * 6

    if position_tag == "LOW" and hk_cash < target_3m:
        return f"建议提前储备 3-6 个月港币，当前余额约为 {hk_cash:.0f} HKD，目标区间约 {target_3m:.0f} ~ {target_6m:.0f} HKD。"

    if position_tag == "LOW":
        return "港币储备暂时够用，可以继续按计划分批执行。"

    return "当前不是特别便宜的窗口，不建议额外囤港币。"


def _build_rmb_reversal_advice(position_tag: str) -> str:
    """判断是否可以把部分资金换回人民币。"""

    if position_tag == "HIGH":
        return "💰 可考虑将部分资金换回人民币。"
    if position_tag == "LOW":
        return "🚫 不建议换回人民币。"
    return "🔄 暂时观望，等更清晰的高位再考虑换回人民币。"


def _build_hkd_to_usd_advice(usd_hkd: float) -> str:
    """简化版港币 -> 美元建议。"""

    if usd_hkd <= 7.78:
        return "USD/HKD 偏强，若有美元需求可分批换入。"
    if usd_hkd >= 7.83:
        return "USD/HKD 偏弱，美元换入先等等更好。"
    return "USD/HKD 中性，按需小额处理即可。"


def run_strategy_analysis(
    csv_path: str = HISTORY_FILE,
    portfolio: Optional[PortfolioConfig] = None,
    logger: Optional[logging.Logger] = None,
) -> Dict[str, str]:
    """读取历史数据并生成资金调度建议。"""

    portfolio = portfolio or get_portfolio_config()
    history_df = _load_history_for_strategy(csv_path)
    latest_row = history_df.iloc[-1]

    latest_date = latest_row["date"]
    recent_df = history_df[history_df["date"] >= latest_date - pd.Timedelta(days=89)].copy()
    if recent_df.empty:
        recent_df = history_df.copy()

    sample_count = len(recent_df)
    latest_cost = float(latest_row["cost"])

    if sample_count < 10:
        market_info = {
            "market_position_level": "中位",
            "market_position_bias": "样本不足",
            "market_position_label": "中位（样本不足）",
            "market_position_text": "当前样本还不够，先继续积累历史数据。",
            "market_tag": "STARTUP",
            "quantile_info": f"最近90天样本仅 {sample_count} 条，暂不做分位判断。",
        }
        rmb_advice = {
            "title": "建议：先正常定投",
            "percent": "0%",
            "example": f"{portfolio.monthly_invest_rmb:.0f} RMB",
            "detail": "样本不足时，先按原计划执行，等数据积累更充分后再调整。",
        }
        stockpile_advice = "样本不足，暂不建议围绕囤港币做激进调整。"
        reversal_advice = "🔄 暂不急着换回人民币。"
    else:
        q25 = float(recent_df["cost"].quantile(0.25))
        q75 = float(recent_df["cost"].quantile(0.75))
        market = _classify_market_position(latest_cost, q25, q75)
        market_info = {
            "market_position_level": market["level"],
            "market_position_bias": market["bias"],
            "market_position_label": market["label"],
            "market_position_text": f"📊 当前汇率位置：{market['level']}（{market['bias']}）",
            "market_tag": market["tag"],
            "quantile_info": f"最近90天样本 {sample_count} 条，当前处于 {market['level']} 区间。",
        }
        rmb_advice = _build_rmb_to_hkd_advice(market["tag"], portfolio.monthly_invest_rmb)
        stockpile_advice = _build_hkd_stockpile_advice(
            market["tag"],
            portfolio.hk_cash,
            portfolio.monthly_invest_rmb,
            latest_cost,
        )
        reversal_advice = _build_rmb_reversal_advice(market["tag"])

    hkd_to_usd_advice = _build_hkd_to_usd_advice(float(latest_row["usd_hkd"]))

    result = {
        "date": latest_row["date"].strftime("%Y-%m-%d"),
        "sample_count": str(sample_count),
        "cny_hkd": f"{float(latest_row['cny_hkd']):.6f}",
        "usd_hkd": f"{float(latest_row['usd_hkd']):.6f}",
        "cost": f"{latest_cost:.6f}",
        "market_position_level": market_info["market_position_level"],
        "market_position_bias": market_info["market_position_bias"],
        "market_position_label": market_info["market_position_label"],
        "market_position_text": market_info["market_position_text"],
        "market_tag": market_info["market_tag"],
        "quantile_info": market_info["quantile_info"],
        "rmb_to_hkd_title": rmb_advice["title"],
        "rmb_to_hkd_percent": rmb_advice["percent"],
        "rmb_to_hkd_example": rmb_advice["example"],
        "rmb_to_hkd_detail": rmb_advice["detail"],
        "hkd_stockpile_advice": stockpile_advice,
        "rmb_reversal_advice": reversal_advice,
        "hkd_to_usd_advice": hkd_to_usd_advice,
        "monthly_invest_rmb": f"{portfolio.monthly_invest_rmb:.0f}",
        "hk_cash": f"{portfolio.hk_cash:.0f}",
        "ibkr_cash_usd": f"{portfolio.ibkr_cash_usd:.0f}",
        "rmb_cash": f"{portfolio.rmb_cash:.0f}",
    }

    if logger:
        logger.info(
            "策略分析完成：%s | %s | %s",
            result["market_position_label"],
            result["rmb_to_hkd_percent"],
            result["rmb_reversal_advice"],
        )

    return result

