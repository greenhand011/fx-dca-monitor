"""汇率数据抓取模块。

本模块负责两类数据源：
1. 中国银行外汇牌价页面中的“港币”现汇卖出价；
2. yfinance 提供的离岸 USD/HKD 汇率。

设计目标：
1. 尽量保证抓取逻辑清晰、可维护；
2. 对网络失败、页面结构变化、空数据等情况做好异常处理；
3. 对离岸汇率查询加入重试机制，减少临时性失败影响。
"""

from __future__ import annotations

import logging
from typing import Optional

import requests
import yfinance as yf
from bs4 import BeautifulSoup

from utils import execute_with_retry, get_random_user_agent, safe_float


BOC_RATE_URL = "https://www.boc.cn/sourcedb/whpj/"
USD_HKD_TICKER = "USDHKD=X"


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
