# -*- coding: utf-8 -*-
"""资金调度配置模块。

这里把用户资产与定投预算集中管理，避免策略代码里散落硬编码。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PortfolioConfig:
    """资金配置。"""

    monthly_invest_rmb: float = 2000.0
    hk_cash: float = 10000.0
    ibkr_cash_usd: float = 2000.0
    rmb_cash: float = 50000.0


def get_portfolio_config() -> PortfolioConfig:
    """返回默认资金配置。"""

    return PortfolioConfig()


def monthly_hkd_budget(config: PortfolioConfig, cost: float) -> float:
    """把月度人民币预算按当前成本粗略换算成港币预算。"""

    if cost <= 0:
        return 0.0
    return config.monthly_invest_rmb / cost


def hkd_months_buffer(config: PortfolioConfig, cost: float) -> float:
    """计算当前港币余额大约够几个月使用。"""

    monthly_budget = monthly_hkd_budget(config, cost)
    if monthly_budget <= 0:
        return 0.0
    return config.hk_cash / monthly_budget

