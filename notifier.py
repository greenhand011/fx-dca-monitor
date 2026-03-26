"""飞书通知模块。

本模块负责把当日汇率和策略分析结果发送到飞书群机器人。
题目要求使用 interactive 卡片消息，因此这里构造飞书卡片 JSON。
"""

from __future__ import annotations

import logging
import os
from typing import Dict, Optional

import requests


def format_data_source(source: str) -> str:
    """将内部数据源标识转换为更易读的飞书展示文案。"""

    source_mapping = {
        "BOC": "✅ 正常（BOC）",
        "API": "⚠️ 备用（API）",
        "HISTORY": "⚠️ 历史（HISTORY）",
        "FALLBACK": "🚨 估算（FALLBACK）",
    }
    return source_mapping.get(source, f"❓ 未知来源（{source}）")


def build_feishu_card(report_data: Dict[str, str]) -> Dict[str, object]:
    """根据汇率与策略结果构造飞书 interactive 卡片。"""

    source_text = format_data_source(report_data.get("data_source", "UNKNOWN"))

    summary_markdown = (
        f"**日期**：{report_data['date']}\n"
        f"**数据来源**：{source_text}\n"
        f"**CNY→HKD**：`{report_data['cny_hkd']}`\n"
        f"**USD→HKD**：`{report_data['usd_hkd']}`\n"
        f"**综合成本**：`{report_data['cost']}`"
    )

    strategy_markdown = (
        f"**分位信息**\n{report_data['quantile_info']}\n\n"
        f"**策略A**\n{report_data['strategy_a_signal']}\n\n"
        f"**策略B**\n{report_data['strategy_b_signal']}\n\n"
        f"**策略建议**\n{report_data['final_advice']}"
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
                    "content": "📊 跨境换汇日报",
                },
                "template": "blue",
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": summary_markdown,
                    },
                },
                {"tag": "hr"},
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": strategy_markdown,
                    },
                },
                {"tag": "hr"},
                {
                    "tag": "note",
                    "elements": [
                        {
                            "tag": "plain_text",
                            "content": "🤖 由 fx-dca-monitor 自动生成，用于辅助判断换汇与定投节奏。",
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
    """发送飞书卡片消息。

    返回值说明：
    - True: 已成功发送；
    - False: 因未配置 webhook 或发送失败而未送达。
    """

    webhook = os.getenv("FEISHU_WEBHOOK", "").strip()
    if not webhook:
        if logger:
            logger.warning("未检测到环境变量 FEISHU_WEBHOOK，跳过飞书推送。")
        return False

    payload = build_feishu_card(report_data)

    try:
        response = requests.post(webhook, json=payload, timeout=15)
        response.raise_for_status()

        # 飞书 webhook 一般会返回 {"StatusCode":0,...} 或 code/msg 风格结构。
        # 这里兼容不同返回格式，只要状态码正常且业务码为成功就视为发送成功。
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
