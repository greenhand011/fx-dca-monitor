# -*- coding: utf-8 -*-
"""计算与历史落库模块。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import pandas as pd

from utils import get_china_date_str, safe_write_csv_atomic


HISTORY_FILE = "history_rates.csv"
CSV_COLUMNS = ["date", "cny_hkd", "usd_hkd", "cost"]


def calculate_cost(cny_hkd: float, usd_hkd: float) -> float:
    """计算综合成本。"""

    if cny_hkd <= 0:
        raise ValueError(f"cny_hkd 必须大于 0，当前值为：{cny_hkd}")
    if usd_hkd <= 0:
        raise ValueError(f"usd_hkd 必须大于 0，当前值为：{usd_hkd}")
    return round(cny_hkd * usd_hkd, 6)


def _load_or_init_history(csv_path: str) -> pd.DataFrame:
    """读取历史 CSV，不存在则返回空表。"""

    path = Path(csv_path)
    if not path.exists():
        return pd.DataFrame(columns=CSV_COLUMNS)

    history_df = pd.read_csv(path, encoding="utf-8-sig")
    missing_columns = [column for column in CSV_COLUMNS if column not in history_df.columns]
    if missing_columns:
        raise ValueError(f"历史 CSV 缺少必要列：{missing_columns}")
    return history_df[CSV_COLUMNS].copy()


def save_rate_record(
    cny_hkd: float,
    usd_hkd: float,
    cost: float,
    csv_path: str = HISTORY_FILE,
    logger: Optional[logging.Logger] = None,
    record_date: Optional[str] = None,
) -> pd.DataFrame:
    """保存或更新历史记录，只更新当天，不覆盖全表。"""

    final_date = record_date or get_china_date_str()
    history_df = _load_or_init_history(csv_path)

    new_record = {
        "date": final_date,
        "cny_hkd": round(cny_hkd, 6),
        "usd_hkd": round(usd_hkd, 6),
        "cost": round(cost, 6),
    }

    if history_df.empty:
        history_df = pd.DataFrame([new_record], columns=CSV_COLUMNS)
        if logger:
            logger.info("历史文件不存在或为空，已创建首条记录。")
    else:
        history_df = history_df[CSV_COLUMNS].copy()
        history_df["date"] = history_df["date"].astype(str).str.strip()
        for column in ["cny_hkd", "usd_hkd", "cost"]:
            history_df[column] = pd.to_numeric(history_df[column], errors="coerce")

        same_day_mask = history_df["date"] == final_date
        if same_day_mask.any():
            history_df.loc[same_day_mask, "cny_hkd"] = new_record["cny_hkd"]
            history_df.loc[same_day_mask, "usd_hkd"] = new_record["usd_hkd"]
            history_df.loc[same_day_mask, "cost"] = new_record["cost"]
            if logger:
                logger.info("检测到 %s 已存在记录，已执行更新。", final_date)
        else:
            history_df = pd.concat(
                [history_df, pd.DataFrame([new_record], columns=CSV_COLUMNS)],
                ignore_index=True,
            )
            if logger:
                logger.info("已追加 %s 的新汇率记录。", final_date)

    history_df["date"] = pd.to_datetime(history_df["date"], errors="coerce")
    history_df = history_df.dropna(subset=["date"]).copy()
    for column in ["cny_hkd", "usd_hkd", "cost"]:
        history_df[column] = pd.to_numeric(history_df[column], errors="coerce")
    history_df = history_df.dropna(subset=["cny_hkd", "usd_hkd", "cost"]).copy()
    history_df = (
        history_df.sort_values("date")
        .drop_duplicates(subset=["date"], keep="last")
        .reset_index(drop=True)
    )
    history_df["date"] = history_df["date"].dt.strftime("%Y-%m-%d")

    path = safe_write_csv_atomic(history_df, csv_path=csv_path, logger=logger)
    print("写入后CSV总条数:", len(history_df))

    if logger:
        logger.info("历史数据已写入 CSV：%s", path.resolve())

    return history_df
