import pandas as pd
from pathlib import Path
from typing import Dict

from calculator import HISTORY_FILE

BASE_AMOUNT = 1000


def run_strategy_analysis(csv_path=HISTORY_FILE, logger=None):

    path = Path(csv_path)
    print("📂 使用CSV:", path.resolve())

    df = pd.read_csv(path)

    print("📊 原始数据条数:", len(df))

    # ===== 修复关键点 =====
    df["date"] = df["date"].astype(str).str.replace("/", "-")
    df["date"] = pd.to_datetime(df["date"], errors="coerce")

    df = df.dropna(subset=["date", "cost"])
    df = df.sort_values("date")

    print("✅ 清洗后条数:", len(df))

    latest = df.iloc[-1]
    latest_cost = latest["cost"]

    recent = df[df["date"] >= latest["date"] - pd.Timedelta(days=90)]

    print("📊 90天样本:", len(recent))

    if len(recent) < 10:
        return {
            "date": latest["date"].strftime("%Y-%m-%d"),
            "strategy_a_signal": "⏳ 冷启动",
            "strategy_b_signal": "➖ 港币中性",
            "quantile_info": f"样本={len(recent)}",
            "final_advice": "继续定投",
        }

    q25 = recent["cost"].quantile(0.25)
    q75 = recent["cost"].quantile(0.75)

    # ===== 买入 =====
    if latest_cost < q25:
        buy = "🟢 人民币强 → 加仓"
        amount = BASE_AMOUNT * 2
    elif latest_cost > q75:
        buy = "🔴 人民币弱 → 减仓"
        amount = BASE_AMOUNT * 0.5
    else:
        buy = "🟡 正常"
        amount = BASE_AMOUNT

    # ===== 卖出（你要的）=====
    if latest_cost > q75:
        sell = "💰 可换回人民币（美元强）"
    elif latest_cost < q25:
        sell = "🚫 不建议换回人民币"
    else:
        sell = "➖ 暂无换回机会"

    return {
        "date": latest["date"].strftime("%Y-%m-%d"),
        "strategy_a_signal": buy,
        "strategy_b_signal": sell,
        "quantile_info": f"样本={len(recent)} q25={q25:.4f} q75={q75:.4f}",
        "final_advice": f"💵 本次建议换汇：{amount} RMB",
    }