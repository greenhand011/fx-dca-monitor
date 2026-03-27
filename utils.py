# -*- coding: utf-8 -*-
"""通用工具模块。"""

from __future__ import annotations

import logging
import random
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional, Tuple, Type


CHINA_TIMEZONE = timezone(timedelta(hours=8))

USER_AGENTS = [
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.0 Safari/605.1.15"
    ),
    (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_3 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.0 Mobile/15E148 Safari/604.1"
    ),
]


def setup_logger(name: str = "fx_dca_monitor") -> logging.Logger:
    """创建统一日志对象。"""

    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    handler.setLevel(logging.INFO)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def get_random_user_agent() -> str:
    """随机返回一个浏览器 UA。"""

    return random.choice(USER_AGENTS)


def safe_float(value: Any) -> Optional[float]:
    """安全转换成浮点数。"""

    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def get_china_now() -> datetime:
    """获取北京时间当前时间。"""

    return datetime.now(CHINA_TIMEZONE)


def get_china_date_str() -> str:
    """获取北京时间日期字符串。"""

    return get_china_now().strftime("%Y-%m-%d")


def configure_yfinance_cache(logger: Optional[logging.Logger] = None) -> Path:
    """把 yfinance 缓存目录固定到项目内，减少系统权限问题。"""

    cache_dir = Path(__file__).resolve().parent / ".cache" / "yfinance"
    cache_dir.mkdir(parents=True, exist_ok=True)

    try:
        import yfinance.cache as yf_cache

        yf_cache.set_cache_location(str(cache_dir))
        if logger:
            logger.info("已配置 yfinance 缓存目录：%s", cache_dir)
    except Exception as exc:
        if logger:
            logger.warning("配置 yfinance 缓存目录失败：%s", exc)

    return cache_dir


def execute_with_retry(
    func: Callable[..., Any],
    *args: Any,
    attempts: int = 3,
    delay_seconds: float = 2.0,
    backoff: float = 1.5,
    exceptions: Tuple[Type[BaseException], ...] = (Exception,),
    logger: Optional[logging.Logger] = None,
    operation_name: str = "未命名操作",
    **kwargs: Any,
) -> Any:
    """执行带重试的函数。"""

    if attempts < 1:
        raise ValueError("attempts 必须大于等于 1")

    last_error: Optional[BaseException] = None
    current_delay = delay_seconds

    for attempt in range(1, attempts + 1):
        try:
            return func(*args, **kwargs)
        except exceptions as exc:  # type: ignore[misc]
            last_error = exc
            if logger:
                logger.warning(
                    "%s 第 %s/%s 次执行失败：%s",
                    operation_name,
                    attempt,
                    attempts,
                    exc,
                )
            if attempt < attempts:
                if logger:
                    logger.info("%s 将在 %.1f 秒后重试。", operation_name, current_delay)
                time.sleep(current_delay)
                current_delay *= backoff

    if last_error is not None:
        raise last_error
    raise RuntimeError(f"{operation_name} 重试执行结束，但未返回结果。")

