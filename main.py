# -*- coding: utf-8 -*-
"""项目主入口。"""

from __future__ import annotations

import sys

from calculator import HISTORY_FILE, calculate_cost, save_rate_record
from data_fetcher import fetch_cny_hkd_with_fallback, fetch_usd_hkd_with_fallback
from notifier import send_feishu_report
from portfolio import get_portfolio_config
from strategy import run_strategy_analysis
from utils import setup_logger


def run() -> int:
    """执行完整资金调度流程。"""

    logger = setup_logger()
    csv_path = HISTORY_FILE
    print("当前使用CSV路径:", csv_path)

    portfolio = get_portfolio_config()
    logger.info("fx-dca-monitor 开始执行。")

    try:
        logger.info("步骤 1/6：获取 CNY/HKD 汇率（含容灾）。")
        cny_hkd, cny_source = fetch_cny_hkd_with_fallback(logger=logger, attempts=3)
        logger.info("CNY/HKD 最终采用来源：%s，值为 %.6f", cny_source, cny_hkd)

        logger.info("步骤 2/6：获取 USD/HKD 汇率（含容灾）。")
        usd_hkd, usd_source = fetch_usd_hkd_with_fallback(logger=logger, attempts=3)
        logger.info("USD/HKD 最终采用来源：%s，值为 %.6f", usd_source, usd_hkd)

        logger.info("步骤 3/6：计算综合成本。")
        cost = calculate_cost(cny_hkd, usd_hkd)

        logger.info("步骤 4/6：写入历史文件。")
        save_rate_record(
            cny_hkd=cny_hkd,
            usd_hkd=usd_hkd,
            cost=cost,
            csv_path=csv_path,
            logger=logger,
        )

        logger.info("步骤 5/6：运行资金调度策略。")
        strategy_result = run_strategy_analysis(
            csv_path=csv_path,
            portfolio=portfolio,
            logger=logger,
        )

        logger.info("步骤 6/6：发送飞书消息。")
        report_data = {
            "date": strategy_result["date"],
            "cny_hkd": f"{cny_hkd:.6f}",
            "usd_hkd": f"{usd_hkd:.6f}",
            "cost": f"{cost:.6f}",
            "cny_source": cny_source,
            "usd_source": usd_source,
            "market_position_text": strategy_result["market_position_text"],
            "rmb_to_hkd_title": strategy_result["rmb_to_hkd_title"],
            "rmb_to_hkd_percent": strategy_result["rmb_to_hkd_percent"],
            "rmb_to_hkd_example": strategy_result["rmb_to_hkd_example"],
            "rmb_to_hkd_detail": strategy_result["rmb_to_hkd_detail"],
            "hkd_stockpile_advice": strategy_result["hkd_stockpile_advice"],
            "rmb_reversal_advice": strategy_result["rmb_reversal_advice"],
            "hkd_to_usd_advice": strategy_result["hkd_to_usd_advice"],
        }
        send_result = send_feishu_report(report_data=report_data, logger=logger)

        if send_result:
            logger.info("主流程执行完成，飞书通知已发送。")
        else:
            logger.warning("主流程执行完成，但飞书通知未发送或发送失败。")

        return 0
    except Exception as exc:
        logger.exception("主流程执行失败：%s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(run())

