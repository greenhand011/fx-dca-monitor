"""
飞书消息推送模块
功能：
1. 构建飞书卡片
2. 发送 webhook 消息
"""

from __future__ import annotations

import json
import logging
import os
from typing import Dict, Optional

import requests


def _build_feishu_card(report_data: Dict[str, str]) -> Dict:
    """构建飞书卡片"""

    card = {
        "config": {
            "wide_screen_mode": True
        },
        "elements": [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        f"**📊 跨境换汇日报**\n\n"
                        f"**日期：** {report_data.get('date', '')}\n\n"
                        f"**数据来源：** ✅ 正常（BOC）\n\n"
                        f"---\n\n"
                        f"**CNY→HKD：** `{report_data.get('cny_hkd', '')}`\n\n"
                        f"**USD→HKD：** `{report_data.get('usd_hkd', '')}`\n\n"
                        f"**综合成本：** `{report_data.get('cost', '')}`\n\n"
                    )
                }
            },
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        f"---\n\n"
                        f"**分位信息**\n{report_data.get('quantile_info', '')}\n\n"
                        f"**策略A**\n{report_data.get('strategy_a_signal', '')}\n\n"
                        f"**策略B**\n{report_data.get('strategy_b_signal', '')}\n\n"
                    )
                }
            },
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        f"---\n\n"
                        f"**策略建议**\n{report_data.get('final_advice', '')}"
                    )
                }
            }
        ]
    }

    return card


def send_feishu_report(
    report_data: Dict[str, str],
    logger: Optional[logging.Logger] = None,
) -> bool:

    webhook_url = os.environ.get("FEISHU_WEBHOOK")

    if not webhook_url:
        if logger:
            logger.error("未配置 FEISHU_WEBHOOK")
        return False

    card = _build_feishu_card(report_data)

    payload = {
        "msg_type": "interactive",
        "card": card
    }

    headers = {
        "Content-Type": "application/json; charset=utf-8"
    }

    try:
        response = requests.post(
            webhook_url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            timeout=30,
        )

        if response.status_code != 200:
            if logger:
                logger.error("HTTP失败：%s", response.text)
            return False

        result = response.json()

        if result.get("StatusCode") == 0:
            if logger:
                logger.info("飞书发送成功")
            return True

        if logger:
            logger.error("飞书返回失败：%s", result)

        return False

    except Exception as e:
        if logger:
            logger.exception("发送异常：%s", e)
        return False