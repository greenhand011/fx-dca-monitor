"""项目主入口。

执行流程如下：
1. 获取中国银行港币现汇卖出价；
2. 获取离岸 USD/HKD 汇率；
3. 计算综合成本；
4. 写入/更新历史 CSV；
5. 运行策略分析；
6. 推送飞书日报。

要求中强调了全流程 try/except 和打印日志，
因此这里会对每个关键阶段进行日志记录，并在顶层统一兜底。
"""

from __future__ import annotations

import sys

from calculator import calculate_cost, save_rate_record
from data_fetcher import fetch_cny_hkd_with_fallback, fetch_usd_hkd_with_fallback
from notifier import send_feishu_report
from strategy import run_strategy_analysis
from utils import setup_logger


def run() -> int:
    """执行完整业务流程，并返回适合命令行退出的状态码。"""

    logger = setup_logger()
    logger.info("fx-dca-monitor 开始执行。")

    try:
        logger.info("步骤 1/6：开始获取 CNY/HKD 汇率（含容灾切换）。")
        cny_hkd, cny_hkd_source = fetch_cny_hkd_with_fallback(logger=logger, attempts=3)
        logger.info("CNY/HKD 最终采用来源：%s，值为 %.6f", cny_hkd_source, cny_hkd)

        logger.info("步骤 2/6：开始获取离岸 USD/HKD 汇率（含容灾切换）。")
        usd_hkd, usd_hkd_source = fetch_usd_hkd_with_fallback(logger=logger, attempts=3)
        logger.info("USD/HKD 最终采用来源：%s，值为 %.6f", usd_hkd_source, usd_hkd)

        logger.info("步骤 3/6：开始计算综合成本。")
        cost = calculate_cost(cny_hkd, usd_hkd)

        logger.info("步骤 4/6：开始写入历史文件。")
        save_rate_record(
            cny_hkd=cny_hkd,
            usd_hkd=usd_hkd,
            cost=cost,
            logger=logger,
        )

        logger.info("步骤 5/6：开始运行策略分析。")
        strategy_result = run_strategy_analysis(logger=logger)

        logger.info("步骤 6/6：开始发送飞书消息。")
        report_data = {
            "date": strategy_result["date"],
            "cny_hkd": f"{cny_hkd:.6f}",
            "usd_hkd": f"{usd_hkd:.6f}",
            "cost": f"{cost:.6f}",
            "data_source": cny_hkd_source,
            "quantile_info": strategy_result["quantile_info"],
            "strategy_a_signal": strategy_result["strategy_a_signal"],
            "strategy_b_signal": strategy_result["strategy_b_signal"],
            "final_advice": strategy_result["final_advice"],
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
