"""真实历史汇率初始化脚本。

本脚本用于一次性初始化最近 90 天的真实历史数据，并覆盖生成 history_rates.csv。

数据来源：
1. USD/HKD：使用 yfinance 的 USDHKD=X 日线收盘价；
2. HKD/CNY：使用 exchangerate.host timeseries 接口。

计算逻辑：
1. 先得到 usd_hkd；
2. 再得到 hkd_cny；
3. 转换为 cny_hkd = 1 / hkd_cny；
4. 计算综合成本 cost = cny_hkd * usd_hkd。

对齐规则：
1. 以 USD/HKD 的交易日为主；
2. 若 API 某天缺少 HKD/CNY 数据，则对齐后使用前值填充；
3. 最终覆盖生成 history_rates.csv，供策略模块直接使用。
"""

from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import requests
import urllib3
import yfinance as yf

from calculator import HISTORY_FILE
from data_fetcher import USD_HKD_TICKER
from utils import configure_yfinance_cache, get_china_now, setup_logger


HKD_CNY_TIMESERIES_URL = "https://api.exchangerate.host/timeseries"
USD_HKD_TIMESERIES_URL = "https://api.exchangerate.host/timeseries"
FRANKFURTER_BASE_URL = "https://api.frankfurter.app"
CURRENCY_API_JSDELIVR_URL = "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@{date}/v1/currencies/{base}.json"
CURRENCY_API_PAGES_URL = "https://{date}.currency-api.pages.dev/v1/currencies/{base}.json"


# 仅在明确触发 TLS 兼容兜底时使用 verify=False，因此这里关闭对应告警，
# 避免日志被重复的 InsecureRequestWarning 干扰。
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def request_json_with_tls_fallback(url: str, params: dict, timeout: int, logger, request_name: str) -> dict:
    """请求 JSON 接口，并在 TLS 握手异常时尝试 verify=False 兜底。"""

    try:
        response = requests.get(url, params=params, timeout=timeout)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.SSLError as exc:
        logger.warning("%s 出现 SSL 异常，尝试使用 verify=False 重新请求。", request_name)
        logger.warning("%s SSL 异常详情：%s", request_name, exc)

        response = requests.get(url, params=params, timeout=timeout, verify=False)
        response.raise_for_status()
        return response.json()


def fetch_timeseries_from_frankfurter(
    start_date: str,
    end_date: str,
    base: str,
    symbol: str,
    logger,
    request_name: str,
) -> dict:
    """从 frankfurter.app 获取历史汇率，作为 exchangerate.host 的后备源。"""

    logger.warning("%s 主接口不可用，切换到 frankfurter.app 历史汇率接口。", request_name)

    url = f"{FRANKFURTER_BASE_URL}/{start_date}..{end_date}"
    params = {
        "from": base,
        "to": symbol,
    }

    data = request_json_with_tls_fallback(
        url,
        params=params,
        timeout=15,
        logger=logger,
        request_name=f"{request_name}（frankfurter）",
    )

    rates = data.get("rates")
    if not isinstance(rates, dict) or not rates:
        raise ValueError(f"{request_name} 的 frankfurter 后备源返回空数据：{data}")

    return data


def fetch_daily_rate_from_currency_api(date_str: str, base: str, symbol: str, timeout: int, logger) -> Optional[float]:
    """从公开 currency-api 按日期获取单日汇率。

    该接口不需要 access_key，适合作为最后一层真实历史数据后备源。
    """

    urls = [
        CURRENCY_API_JSDELIVR_URL.format(date=date_str, base=base.lower()),
        CURRENCY_API_PAGES_URL.format(date=date_str, base=base.lower()),
    ]

    for url in urls:
        try:
            data = request_json_with_tls_fallback(
                url=url,
                params={},
                timeout=timeout,
                logger=logger,
                request_name=f"currency-api {base}/{symbol} {date_str}",
            )
            base_payload = data.get(base.lower())
            if not isinstance(base_payload, dict):
                continue

            value = base_payload.get(symbol.lower())
            if value is None:
                continue

            return float(value)
        except Exception:
            continue

    return None


def fetch_range_from_currency_api(
    start_date: str,
    end_date: str,
    base: str,
    symbol: str,
    logger,
    business_days_only: bool = False,
) -> pd.DataFrame:
    """按日期循环调用 currency-api，构建一段时间的历史汇率。"""

    logger.warning(
        "开始使用 currency-api 最终后备源获取 %s/%s 历史数据：%s -> %s",
        base,
        symbol,
        start_date,
        end_date,
    )

    date_range = pd.date_range(start=start_date, end=end_date, freq="D")
    records = []

    for current_date in date_range:
        if business_days_only and current_date.weekday() >= 5:
            continue

        date_str = current_date.strftime("%Y-%m-%d")
        value = fetch_daily_rate_from_currency_api(
            date_str=date_str,
            base=base,
            symbol=symbol,
            timeout=15,
            logger=logger,
        )
        if value is None or value <= 0:
            continue

        records.append(
            {
                "date": date_str,
                f"{base.lower()}_{symbol.lower()}": float(value),
            }
        )

    result_df = pd.DataFrame(records)
    if result_df.empty:
        raise ValueError(f"currency-api 无法返回 {base}/{symbol} 历史数据。")

    logger.info(
        "成功通过 currency-api 获取 %s 条 %s/%s 历史记录。",
        len(result_df),
        base,
        symbol,
    )
    return result_df


def fetch_usd_hkd_history_from_yfinance(start_date: str, end_date: str, logger) -> pd.DataFrame:
    """从 yfinance 获取最近 90 天 USD/HKD 日线收盘价。"""

    logger.info("开始从 yfinance 获取 USD/HKD 历史数据：%s -> %s", start_date, end_date)

    try:
        configure_yfinance_cache(logger=logger)
        ticker = yf.Ticker(USD_HKD_TICKER)

        # yfinance 的 end 参数通常是“开区间”，因此这里额外 +1 天，
        # 以确保 end_date 当天如果存在数据时也能被包含进来。
        history = ticker.history(
            start=start_date,
            end=(pd.to_datetime(end_date) + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
            interval="1d",
            auto_adjust=False,
        )

        if history.empty:
            raise ValueError("yfinance 返回的 USD/HKD 历史数据为空。")

        if "Close" not in history.columns:
            raise ValueError("yfinance 返回数据缺少 Close 列。")

        usd_df = history.reset_index()[["Date", "Close"]].copy()
        usd_df["date"] = pd.to_datetime(usd_df["Date"]).dt.strftime("%Y-%m-%d")
        usd_df["usd_hkd"] = pd.to_numeric(usd_df["Close"], errors="coerce")
        usd_df = usd_df[["date", "usd_hkd"]].dropna().copy()
        usd_df = usd_df[usd_df["usd_hkd"] > 0].sort_values("date").reset_index(drop=True)

        if usd_df.empty:
            raise ValueError("USD/HKD 历史数据清洗后为空。")

        logger.info("成功获取 %s 条 USD/HKD 历史记录。", len(usd_df))
        return usd_df
    except Exception as exc:
        raise RuntimeError(f"获取 USD/HKD 历史数据失败：{exc}") from exc


def fetch_usd_hkd_history_from_api(start_date: str, end_date: str, logger) -> pd.DataFrame:
    """当 yfinance 不可用时，从 exchangerate.host 获取 USD/HKD 历史数据。"""

    logger.info("开始从 exchangerate.host 获取 USD/HKD 历史数据：%s -> %s", start_date, end_date)

    params = {
        "start_date": start_date,
        "end_date": end_date,
        "base": "USD",
        "symbols": "HKD",
    }

    try:
        data = request_json_with_tls_fallback(
            USD_HKD_TIMESERIES_URL,
            params=params,
            timeout=15,
            logger=logger,
            request_name="USD/HKD timeseries",
        )

        if not data.get("rates"):
            data = fetch_timeseries_from_frankfurter(
                start_date=start_date,
                end_date=end_date,
                base="USD",
                symbol="HKD",
                logger=logger,
                request_name="USD/HKD timeseries",
            )

        rates = data.get("rates")
        if not isinstance(rates, dict) or not rates:
            raise ValueError(f"USD/HKD timeseries 返回 rates 为空或结构异常：{data}")

        records = []
        for date_str, payload in rates.items():
            if not isinstance(payload, dict):
                continue

            hkd_value = payload.get("HKD")
            try:
                usd_hkd = float(hkd_value)
            except (TypeError, ValueError):
                continue

            if usd_hkd <= 0:
                continue

            records.append({"date": date_str, "usd_hkd": usd_hkd})

        usd_df = pd.DataFrame(records)
        if usd_df.empty:
            raise ValueError("备用 API 返回的 USD/HKD 历史数据为空。")

        # 为了尽量贴近 yfinance 日线交易日，这里只保留工作日数据。
        usd_df["date"] = pd.to_datetime(usd_df["date"])
        usd_df = usd_df[usd_df["date"].dt.weekday < 5].copy()
        usd_df["date"] = usd_df["date"].dt.strftime("%Y-%m-%d")
        usd_df = usd_df.sort_values("date").reset_index(drop=True)

        if usd_df.empty:
            raise ValueError("备用 API 的 USD/HKD 历史数据过滤工作日后为空。")

        logger.info("成功通过备用 API 获取 %s 条 USD/HKD 历史记录。", len(usd_df))
        return usd_df
    except Exception as exc:
        logger.warning("USD/HKD timeseries 与 frankfurter 均不可用，切换到 currency-api。")
        logger.warning("USD/HKD 历史 API 异常详情：%s", exc)

        try:
            return fetch_range_from_currency_api(
                start_date=start_date,
                end_date=end_date,
                base="USD",
                symbol="HKD",
                logger=logger,
                business_days_only=True,
            )
        except Exception as final_exc:
            raise RuntimeError(f"备用 API 获取 USD/HKD 历史数据失败：{final_exc}") from final_exc


def fetch_usd_hkd_history(start_date: str, end_date: str, logger) -> pd.DataFrame:
    """获取 USD/HKD 历史数据。

    默认优先使用 yfinance。
    如果 yfinance 出现限流、超时或网络异常，则自动切换到 exchangerate.host
    的 USD/HKD timeseries，尽量保证历史初始化脚本可执行。
    """

    try:
        return fetch_usd_hkd_history_from_yfinance(start_date, end_date, logger)
    except Exception as exc:
        logger.warning("yfinance 历史数据获取失败，切换到备用 USD/HKD API。")
        logger.warning("yfinance 历史数据异常详情：%s", exc)
        return fetch_usd_hkd_history_from_api(start_date, end_date, logger)


def fetch_hkd_cny_history(start_date: str, end_date: str, logger) -> pd.DataFrame:
    """从 exchangerate.host 获取 HKD/CNY 区间历史汇率。"""

    logger.info("开始从 exchangerate.host 获取 HKD/CNY 历史数据：%s -> %s", start_date, end_date)

    params = {
        "start_date": start_date,
        "end_date": end_date,
        "base": "HKD",
        "symbols": "CNY",
    }

    try:
        data = request_json_with_tls_fallback(
            HKD_CNY_TIMESERIES_URL,
            params=params,
            timeout=15,
            logger=logger,
            request_name="HKD/CNY timeseries",
        )

        if not data.get("rates"):
            data = fetch_timeseries_from_frankfurter(
                start_date=start_date,
                end_date=end_date,
                base="HKD",
                symbol="CNY",
                logger=logger,
                request_name="HKD/CNY timeseries",
            )

        rates = data.get("rates")
        if not isinstance(rates, dict) or not rates:
            raise ValueError(f"timeseries 接口返回 rates 为空或结构异常：{data}")

        records = []
        for date_str, payload in rates.items():
            if not isinstance(payload, dict):
                continue

            cny_value = payload.get("CNY")
            try:
                hkd_cny = float(cny_value)
            except (TypeError, ValueError):
                continue

            if hkd_cny <= 0:
                continue

            records.append({"date": date_str, "hkd_cny": hkd_cny})

        hkd_cny_df = pd.DataFrame(records)
        if hkd_cny_df.empty:
            raise ValueError("HKD/CNY 历史数据为空，无法初始化。")

        hkd_cny_df = hkd_cny_df.sort_values("date").reset_index(drop=True)
        logger.info("成功获取 %s 条 HKD/CNY 历史记录。", len(hkd_cny_df))
        return hkd_cny_df
    except Exception as exc:
        logger.warning("HKD/CNY timeseries 与 frankfurter 均不可用，切换到 currency-api。")
        logger.warning("HKD/CNY 历史 API 异常详情：%s", exc)

        try:
            return fetch_range_from_currency_api(
                start_date=start_date,
                end_date=end_date,
                base="HKD",
                symbol="CNY",
                logger=logger,
                business_days_only=False,
            )
        except Exception as final_exc:
            raise RuntimeError(f"获取 HKD/CNY 历史数据失败：{final_exc}") from final_exc


def build_history_rates_dataframe(
    usd_hkd_df: pd.DataFrame,
    hkd_cny_df: pd.DataFrame,
    logger,
) -> pd.DataFrame:
    """按 USD/HKD 日期对齐并生成最终 history_rates DataFrame。"""

    logger.info("开始对齐 USD/HKD 与 HKD/CNY 历史数据。")

    merged_df = usd_hkd_df.merge(hkd_cny_df, on="date", how="left")
    merged_df = merged_df.sort_values("date").reset_index(drop=True)

    # 题目要求：如果 API 某天缺数据，则以前值填充。
    merged_df["hkd_cny"] = merged_df["hkd_cny"].ffill()

    # 如果最前几行仍为空，说明序列一开始就缺数据。
    # 这里再用首个可用值回填，仅用于消除起始空洞，避免初始化被少量缺口阻断。
    if merged_df["hkd_cny"].isna().any():
        logger.warning("检测到 HKD/CNY 序列起始位置缺失，使用首个可用值回填起始空洞。")
        merged_df["hkd_cny"] = merged_df["hkd_cny"].bfill()

    if merged_df["hkd_cny"].isna().any():
        raise ValueError("HKD/CNY 对齐后仍存在缺失值，无法生成完整历史数据。")

    merged_df["cny_hkd"] = 1 / merged_df["hkd_cny"]
    merged_df["cost"] = merged_df["cny_hkd"] * merged_df["usd_hkd"]

    result_df = merged_df[["date", "cny_hkd", "usd_hkd", "cost"]].copy()
    for column in ["cny_hkd", "usd_hkd", "cost"]:
        result_df[column] = pd.to_numeric(result_df[column], errors="coerce").round(6)

    result_df = result_df.dropna().sort_values("date").reset_index(drop=True)

    if len(result_df) < 60:
        raise ValueError(f"初始化后的历史记录不足 60 条，当前仅 {len(result_df)} 条。")

    logger.info("历史数据对齐完成，共生成 %s 条记录。", len(result_df))
    return result_df


def write_history_csv(history_df: pd.DataFrame, csv_path: str = HISTORY_FILE, logger=None) -> Path:
    """覆盖写入 history_rates.csv。"""

    path = Path(csv_path)
    history_df.to_csv(path, index=False, encoding="utf-8-sig")

    if logger:
        logger.info("已覆盖写入历史数据文件：%s", path.resolve())

    return path


def initialize_real_history() -> int:
    """执行真实历史数据初始化流程。"""

    logger = setup_logger("fx_dca_monitor.init")
    logger.info("开始初始化最近 90 天真实历史汇率数据。")

    try:
        end_date = get_china_now().date()
        start_date = end_date - timedelta(days=90)

        start_date_str = start_date.strftime("%Y-%m-%d")
        end_date_str = end_date.strftime("%Y-%m-%d")

        usd_hkd_df = fetch_usd_hkd_history(start_date_str, end_date_str, logger)
        hkd_cny_df = fetch_hkd_cny_history(start_date_str, end_date_str, logger)
        history_df = build_history_rates_dataframe(usd_hkd_df, hkd_cny_df, logger)
        write_history_csv(history_df, logger=logger)

        logger.info(
            "真实历史数据初始化完成：起始=%s，结束=%s，记录数=%s。",
            history_df.iloc[0]["date"],
            history_df.iloc[-1]["date"],
            len(history_df),
        )
        return 0
    except Exception as exc:
        logger.exception("初始化真实历史数据失败：%s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(initialize_real_history())
