# -*- coding: utf-8 -*-
"""飞书通知模块。"""

from __future__ import annotations

import logging
import os
from typing import Dict, Optional

import requests


def format_data_source(source: str) -> str:
    """把内部来源标识转换成飞书里更容易看懂的文案。"""

    mapping = {
        "BOC": "✅ 正常（BOC）",
        "API": "⚠️ 备用（API）",
        "HISTORY": "⚠️ 历史（HISTORY）",
        "FALLBACK": "🚨 估算（FALLBACK）",
        "YFINANCE": "✅ 正常（YFINANCE）",
        "UNKNOWN": "❓ 未知",
    }
    return mapping.get(source, f"❓ {source}")


def build_feishu_card(report_data: Dict[str, str]) -> Dict[str, object]:
    """构造飞书 interactive 卡片。"""

    cny_source = format_data_source(report_data.get("cny_source", "UNKNOWN"))
    usd_source = format_data_source(report_data.get("usd_source", "UNKNOWN"))

    summary_content = (
        f"**日期**：{report_data['date']}\n"
        f"**CNY→HKD**：`{report_data['cny_hkd']}`  \n"
        f"**USD→HKD**：`{report_data['usd_hkd']}`  \n"
        f"**综合成本**：`{report_data['cost']}`  \n"
        f"**CNY 数据来源**：{cny_source}\n"
        f"**USD 数据来源**：{usd_source}"
    )

    strategy_content = (
        f"**{report_data['market_position_text']}**\n\n"
        f"**换汇建议**：{report_data['rmb_to_hkd_title']}  \n"
        f"**建议幅度**：{report_data['rmb_to_hkd_percent']}  \n"
        f"**示例金额**：{report_data['rmb_to_hkd_example']}  \n"
        f"**说明**：{report_data['rmb_to_hkd_detail']}\n\n"
        f"**是否囤港币**：{report_data['hkd_stockpile_advice']}\n\n"
        f"**是否换回人民币**：{report_data['rmb_reversal_advice']}\n\n"
        f"**港币 → 美元建议**：{report_data['hkd_to_usd_advice']}"
    )

    return {
        "msg_type": "interactive",
        "card": {
            "config": {
                "wide_screen_mode": True,
                "enable_forward": True,
            },
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": "📊 资金调度引擎日报",
                },
                "template": "blue",
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": summary_content,
                    },
                },
                {"tag": "hr"},
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": strategy_content,
                    },
                },
                {"tag": "hr"},
                {
                    "tag": "note",
                    "elements": [
                        {
                            "tag": "plain_text",
                            "content": "🤖 fx-dca-monitor 自动生成，重点关注换汇节奏和资金调度。",
                        }
                    ],
                },
            ],
        },
    }


def send_feishu_report(
    report_data: Dict[str, str],
    logger: Optional[logging.Logger] = None,
) -> bool:
    """发送飞书卡片消息。"""

    webhook = os.getenv("FEISHU_WEBHOOK", "").strip()
    if not webhook:
        if logger:
            logger.warning("未检测到环境变量 FEISHU_WEBHOOK，跳过飞书推送。")
        return False

    payload = build_feishu_card(report_data)

    try:
        response = requests.post(webhook, json=payload, timeout=15)
        response.raise_for_status()
        data = response.json()

        status_code = data.get("StatusCode", 0)
        code = data.get("code", 0)
        if status_code not in (0, None) or code not in (0, None):
            raise ValueError(f"飞书返回业务失败：{data}")

        if logger:
            logger.info("飞书卡片消息发送成功。")
        return True
    except requests.RequestException as exc:
        if logger:
            logger.error("飞书消息发送失败，网络异常：%s", exc)
        return False
    except ValueError as exc:
        if logger:
            logger.error("飞书消息发送失败，返回结果异常：%s", exc)
        return False
    except Exception as exc:
        if logger:
            logger.exception("飞书消息发送过程中出现未知异常：%s", exc)
        return False

