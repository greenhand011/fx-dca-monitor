"""汇率数据抓取模块。

本模块负责两类数据：
1. CNY/HKD：用于估算人民币换港币的基础成本；
2. USD/HKD：用于估算美元换港币的离岸汇率。

其中 CNY/HKD 是本次工程升级的重点，已经从单一数据源升级为多层容灾：
1. 主数据源：中国银行外汇牌价；
2. 备用数据源：exchangerate.host API；
3. 本地历史兜底：history_rates.csv 中最近一次有效记录；
4. 最终固定估算值：0.92。

这样即使外部网站短时不可用，主程序也不会因为 CNY/HKD 数据源失败而直接崩溃。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import pandas as pd
import requests
import yfinance as yf
from bs4 import BeautifulSoup

from calculator import HISTORY_FILE
from utils import execute_with_retry, get_random_user_agent, safe_float


BOC_RATE_URL = "https://www.boc.cn/sourcedb/whpj/"
EXCHANGE_RATE_API_URL = "https://api.exchangerate.host/convert?from=CNY&to=HKD"
USD_HKD_TICKER = "USDHKD=X"
DEFAULT_CNY_HKD_FALLBACK = 0.92


def _parse_boc_hkd_sell_price(html_text: str) -> float:
    """从中国银行网页 HTML 中解析港币现汇卖出价。

    中国银行页面通常会以表格形式展示牌价。
    常见列顺序为：
    币种 / 现汇买入价 / 现钞买入价 / 现汇卖出价 / 现钞卖出价 / 中行折算价 / 发布日期 / 发布时间

    因此“现汇卖出价”一般位于第 4 列（索引 3）。
    """

    soup = BeautifulSoup(html_text, "html.parser")
    rows = soup.find_all("tr")

    for row in rows:
        cells = [cell.get_text(strip=True) for cell in row.find_all(["td", "th"])]
        if not cells:
            continue

        # 只要本行任一单元格包含“港币”，就视为目标行。
        if any("港币" in cell for cell in cells):
            if len(cells) < 4:
                raise ValueError("已找到港币行，但列数不足，无法提取现汇卖出价。")

            sell_price_raw = cells[3]
            sell_price = safe_float(sell_price_raw)
            if sell_price is None:
                raise ValueError(f"港币现汇卖出价无法转换为数字：{sell_price_raw}")

            # 题目要求将牌价除以 100。
            cny_hkd = round(sell_price / 100, 6)
            return cny_hkd

    raise ValueError("未在中国银行页面中找到“港币”对应的牌价行。")


def fetch_boc_cny_hkd(logger: Optional[logging.Logger] = None, attempts: int = 3) -> float:
    """抓取中国银行“港币”现汇卖出价，并按要求除以 100 后返回。"""

    def _download_boc_page() -> float:
        headers = {
            # 每次请求都重新生成 UA，尽量模拟更自然的访问行为。
            "User-Agent": get_random_user_agent(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Cache-Control": "no-cache",
        }

        response = requests.get(BOC_RATE_URL, headers=headers, timeout=15)
        response.raise_for_status()

        # 中国银行页面编码偶尔可能不是 requests 默认猜测的结果，
        # 这里显式使用 apparent_encoding 进行兜底。
        response.encoding = response.apparent_encoding or response.encoding or "utf-8"
        return _parse_boc_hkd_sell_price(response.text)

    try:
        cny_hkd = execute_with_retry(
            _download_boc_page,
            attempts=max(attempts, 1),
            delay_seconds=2.0,
            backoff=1.5,
            exceptions=(Exception,),
            logger=logger,
            operation_name="获取中国银行港币现汇卖出价",
        )
        if logger:
            logger.info("成功获取中国银行港币现汇卖出价：%.6f", cny_hkd)
        return cny_hkd
    except requests.RequestException as exc:
        raise RuntimeError(f"请求中国银行牌价页面失败：{exc}") from exc
    except Exception as exc:
        raise RuntimeError(f"解析中国银行港币牌价失败：{exc}") from exc


def fetch_cny_hkd_from_api(logger: Optional[logging.Logger] = None) -> float:
    """从 exchangerate.host 获取 CNY/HKD 汇率。

    该接口返回 JSON，其中 result 字段通常就是换算结果。
    """

    try:
        response = requests.get(EXCHANGE_RATE_API_URL, timeout=10)
        response.raise_for_status()

        data = response.json()
        result = safe_float(data.get("result"))
        if result is None or result <= 0:
            raise ValueError(f"API 返回 result 异常：{data}")

        cny_hkd = round(float(result), 6)
        if logger:
            logger.info("成功从备用 API 获取 CNY/HKD：%.6f", cny_hkd)
        return cny_hkd
    except requests.RequestException as exc:
        raise RuntimeError(f"请求备用 API 获取 CNY/HKD 失败：{exc}") from exc
    except ValueError as exc:
        raise RuntimeError(f"备用 API 返回数据异常：{exc}") from exc
    except Exception as exc:
        raise RuntimeError(f"备用 API 解析 CNY/HKD 失败：{exc}") from exc


def _get_last_valid_rate_from_history(
    column_name: str,
    csv_path: str = HISTORY_FILE,
    logger: Optional[logging.Logger] = None,
) -> Optional[float]:
    """从历史 CSV 中读取指定列的最后一条有效值。"""

    path = Path(csv_path)
    if not path.exists():
        if logger:
            logger.warning("历史数据文件不存在，无法读取 %s 的历史兜底值。", column_name)
        return None

    try:
        history_df = pd.read_csv(path)
        if history_df.empty or column_name not in history_df.columns:
            if logger:
                logger.warning("历史数据为空或缺少 %s 列，无法读取历史兜底值。", column_name)
            return None

        history_df[column_name] = pd.to_numeric(history_df[column_name], errors="coerce")
        valid_series = history_df[column_name].dropna()
        valid_series = valid_series[valid_series > 0]

        if valid_series.empty:
            if logger:
                logger.warning("历史数据中没有有效的 %s 值，无法读取历史兜底值。", column_name)
            return None

        last_valid_value = round(float(valid_series.iloc[-1]), 6)
        if logger:
            logger.info("成功从历史数据中读取最后有效 %s：%.6f", column_name, last_valid_value)
        return last_valid_value
    except Exception as exc:
        if logger:
            logger.warning("读取历史数据失败，无法读取 %s 的历史兜底值：%s", column_name, exc)
        return None


def get_last_valid_cny_hkd(
    csv_path: str = HISTORY_FILE,
    logger: Optional[logging.Logger] = None,
) -> Optional[float]:
    """从历史 CSV 中读取最后一条有效的 cny_hkd。"""

    return _get_last_valid_rate_from_history("cny_hkd", csv_path=csv_path, logger=logger)


def get_last_valid_usd_hkd(
    csv_path: str = HISTORY_FILE,
    logger: Optional[logging.Logger] = None,
) -> Optional[float]:
    """从历史 CSV 中读取最后一条有效的 usd_hkd。"""

    return _get_last_valid_rate_from_history("usd_hkd", csv_path=csv_path, logger=logger)


def fetch_cny_hkd_with_fallback(
    logger: Optional[logging.Logger] = None,
    attempts: int = 3,
) -> tuple[float, str]:
    """统一入口：按 BOC -> API -> HISTORY -> FALLBACK 顺序获取 CNY/HKD。

    返回：
    - value: 最终采用的汇率值；
    - source: 数据来源标识，取值为 BOC / API / HISTORY / FALLBACK。
    """

    try:
        value = fetch_boc_cny_hkd(logger=logger, attempts=attempts)
        return value, "BOC"
    except Exception as exc:
        if logger:
            logger.warning("BOC失败，切换到API")
            logger.warning("BOC 数据源异常详情：%s", exc)

    try:
        value = fetch_cny_hkd_from_api(logger=logger)
        return value, "API"
    except Exception as exc:
        if logger:
            logger.warning("API失败，使用历史数据")
            logger.warning("API 数据源异常详情：%s", exc)

    history_value = get_last_valid_cny_hkd(logger=logger)
    if history_value is not None:
        if logger:
            logger.warning("已切换到 HISTORY 数据源，继续执行主流程。")
        return history_value, "HISTORY"

    if logger:
        logger.warning("使用最终fallback估算值")

    return DEFAULT_CNY_HKD_FALLBACK, "FALLBACK"


def _download_usd_hkd_from_yfinance() -> float:
    """从 yfinance 下载 USD/HKD 最新收盘价或最近可用价格。"""

    ticker = yf.Ticker(USD_HKD_TICKER)

    # 选择最近 5 天是为了覆盖周末、节假日等无交易日场景，
    # 只要这几天中存在一个有效 Close，就可以拿到最近可用汇率。
    history = ticker.history(period="5d", interval="1d", auto_adjust=False)

    if history.empty:
        raise ValueError("yfinance 返回的数据为空，无法获取 USD/HKD。")

    if "Close" not in history.columns:
        raise ValueError("yfinance 返回数据缺少 Close 列。")

    close_series = history["Close"].dropna()
    if close_series.empty:
        raise ValueError("yfinance Close 列全部为空。")

    usd_hkd = float(close_series.iloc[-1])
    if usd_hkd <= 0:
        raise ValueError(f"USD/HKD 返回值异常：{usd_hkd}")

    return round(usd_hkd, 6)


def fetch_usd_hkd(logger: Optional[logging.Logger] = None, attempts: int = 3) -> float:
    """获取离岸 USD/HKD 汇率，并带有至少 3 次重试。"""

    usd_hkd = execute_with_retry(
        _download_usd_hkd_from_yfinance,
        attempts=max(attempts, 3),
        delay_seconds=2.0,
        backoff=2.0,
        exceptions=(Exception,),
        logger=logger,
        operation_name="获取离岸 USD/HKD 汇率",
    )

    if logger:
        logger.info("成功获取离岸 USD/HKD 汇率：%.6f", usd_hkd)

    return usd_hkd


def fetch_usd_hkd_with_fallback(
    logger: Optional[logging.Logger] = None,
    attempts: int = 3,
) -> tuple[float, str]:
    """为 USD/HKD 提供容灾入口，避免 yfinance 限流时主流程中断。

    容灾顺序：
    1. yfinance 实时数据；
    2. 历史 CSV 中最近有效的 usd_hkd；
    3. 最终估算值 7.80。
    """

    try:
        value = fetch_usd_hkd(logger=logger, attempts=attempts)
        return value, "YFINANCE"
    except Exception as exc:
        if logger:
            logger.warning("USD/HKD 实时数据失败，使用历史数据")
            logger.warning("USD/HKD 实时数据异常详情：%s", exc)

    history_value = get_last_valid_usd_hkd(logger=logger)
    if history_value is not None:
        if logger:
            logger.warning("已切换到 USD/HKD HISTORY 数据源，继续执行主流程。")
        return history_value, "HISTORY"

    if logger:
        logger.warning("USD/HKD 使用最终估算值 7.80")

    return 7.8, "FALLBACK"
