"""项目主入口（最终稳定版）

功能：
1. 自动初始化历史数据（云端首次运行）
2. 获取汇率（带容灾）
3. 计算成本
4. 写入CSV（不覆盖历史）
5. 策略分析（保证非冷启动）
6. 飞书推送
"""

from __future__ import annotations

import sys
import os
from pathlib import Path

from calculator import HISTORY_FILE, calculate_cost, save_rate_record
from data_fetcher import fetch_cny_hkd_with_fallback, fetch_usd_hkd_with_fallback
from notifier import send_feishu_report
from strategy import run_strategy_analysis
from utils import setup_logger


def ensure_history_initialized(logger):
    """确保历史数据存在（解决GitHub Actions冷启动问题）"""

    csv_path = Path(HISTORY_FILE)

    # 文件不存在 或 数据太少 → 初始化
    if (not csv_path.exists()) or (csv_path.exists() and len(open(csv_path).readlines()) < 10):
        logger.warning("⚠️ 检测到历史数据不足，开始初始化历史汇率数据...")

        try:
            import subprocess
            subprocess.run(["python", "init_history_real.py"], check=True)
            logger.info("✅ 历史数据初始化完成")
        except Exception as e:
            logger.error("❌ 初始化历史数据失败: %s", e)


def run() -> int:
    logger = setup_logger()

    csv_path = HISTORY_FILE

    # ✅ 打印绝对路径（关键调试）
    print("📂 CSV绝对路径:", os.path.abspath(csv_path))

    logger.info("fx-dca-monitor 开始执行。")

    try:
        # ===== 0. 先确保历史数据存在 =====
        ensure_history_initialized(logger)

        # ===== 1. 获取 CNY/HKD =====
        logger.info("步骤 1/6：获取 CNY/HKD 汇率")
        cny_hkd, cny_source = fetch_cny_hkd_with_fallback(logger=logger, attempts=3)
        logger.info("CNY/HKD 来源：%s 值：%.6f", cny_source, cny_hkd)

        # ===== 2. 获取 USD/HKD =====
        logger.info("步骤 2/6：获取 USD/HKD 汇率")
        usd_hkd, usd_source = fetch_usd_hkd_with_fallback(logger=logger, attempts=3)
        logger.info("USD/HKD 来源：%s 值：%.6f", usd_source, usd_hkd)

        # ===== 3. 计算成本 =====
        logger.info("步骤 3/6：计算成本")
        cost = calculate_cost(cny_hkd, usd_hkd)

        # ===== 4. 写入CSV =====
        logger.info("步骤 4/6：写入历史数据")
        save_rate_record(
            cny_hkd=cny_hkd,
            usd_hkd=usd_hkd,
            cost=cost,
            csv_path=csv_path,
            logger=logger,
        )

        # ===== 5. 策略分析 =====
        logger.info("步骤 5/6：运行策略分析")
        strategy_result = run_strategy_analysis(csv_path=csv_path, logger=logger)

        # ===== 6. 飞书推送 =====
        logger.info("步骤 6/6：发送飞书消息")

        report_data = {
            "date": strategy_result["date"],
            "cny_hkd": f"{cny_hkd:.6f}",
            "usd_hkd": f"{usd_hkd:.6f}",
            "cost": f"{cost:.6f}",
            "data_source": cny_source,
            "quantile_info": strategy_result["quantile_info"],
            "strategy_a_signal": strategy_result["strategy_a_signal"],
            "strategy_b_signal": strategy_result["strategy_b_signal"],
            "final_advice": strategy_result["final_advice"],
        }

        send_result = send_feishu_report(report_data=report_data, logger=logger)

        if send_result:
            logger.info("✅ 执行完成，飞书已发送")
        else:
            logger.warning("⚠️ 执行完成，但飞书发送失败")

        return 0

    except Exception as exc:
        logger.exception("❌ 主流程执行失败：%s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(run())