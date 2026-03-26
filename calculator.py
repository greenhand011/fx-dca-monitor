"""修复版：保证历史数据永远不会丢"""

import pandas as pd
from pathlib import Path
from typing import Optional
import logging
from datetime import datetime

HISTORY_FILE = "history_rates.csv"
CSV_COLUMNS = ["date", "cny_hkd", "usd_hkd", "cost"]


def calculate_cost(cny_hkd: float, usd_hkd: float) -> float:
    return round(cny_hkd * usd_hkd, 6)


def save_rate_record(
    cny_hkd: float,
    usd_hkd: float,
    cost: float,
    csv_path: str = HISTORY_FILE,
    logger: Optional[logging.Logger] = None,
):
    path = Path(csv_path)

    today = datetime.now().strftime("%Y-%m-%d")

    new_row = pd.DataFrame([{
        "date": today,
        "cny_hkd": cny_hkd,
        "usd_hkd": usd_hkd,
        "cost": cost,
    }])

    # ===== 核心修复 =====
    if path.exists():
        df = pd.read_csv(path, encoding="utf-8-sig")

        print("📊 读取CSV原始条数:", len(df))

        # 统一日期格式
        df["date"] = df["date"].astype(str).str.replace("/", "-")

        # 如果今天已存在 → 更新
        if today in df["date"].values:
            df.loc[df["date"] == today, ["cny_hkd", "usd_hkd", "cost"]] = [
                cny_hkd, usd_hkd, cost
            ]
        else:
            df = pd.concat([df, new_row], ignore_index=True)

    else:
        df = new_row

    # 排序 + 去重
    df = df.drop_duplicates(subset=["date"], keep="last")
    df = df.sort_values("date")

    print("✅ 写入后CSV条数:", len(df))

    df.to_csv(path, index=False, encoding="utf-8-sig")