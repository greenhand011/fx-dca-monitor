"""通用工具模块。

本文件集中放置项目中多个模块都会复用的基础能力，例如：
1. 日志初始化，保证本地运行和 GitHub Actions 中都有清晰输出；
2. 随机 User-Agent，降低网页抓取被简单拦截的概率；
3. 通用重试执行器，统一处理网络抖动、临时失败等常见场景；
4. 时间与数值转换工具，避免各模块重复实现。
"""

from __future__ import annotations

import logging
import random
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional, Sequence, Tuple, Type


# 北京时间时区对象。由于 requirements 中未要求额外安装 pytz，
# 这里直接使用固定 UTC+8 的方式即可满足项目需要。
CHINA_TIMEZONE = timezone(timedelta(hours=8))


# 常见浏览器 User-Agent 列表，用于请求中国银行网页时随机挑选。
# 这样做并不能完全避免反爬限制，但能减少固定请求头带来的风险。
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
    """创建并返回统一格式的日志对象。

    为了避免重复添加 Handler，这里会先判断 logger 是否已经初始化。
    """

    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    logger.addHandler(stream_handler)
    logger.propagate = False
    return logger


def get_random_user_agent() -> str:
    """随机返回一个浏览器 User-Agent。"""

    return random.choice(USER_AGENTS)


def safe_float(value: Any) -> Optional[float]:
    """将任意输入尽量安全地转换为浮点数。

    常见网页数据里可能包含空格、逗号、中文空串等情况，
    这里统一做一次预处理，失败则返回 None。
    """

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
    """获取北京时间日期字符串，格式为 YYYY-MM-DD。"""

    return get_china_now().strftime("%Y-%m-%d")


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
    """执行带重试的函数调用。

    参数说明：
    - attempts: 最大尝试次数，至少为 1；
    - delay_seconds: 第一次失败后的等待秒数；
    - backoff: 每次失败后等待时长的放大倍数；
    - exceptions: 需要触发重试的异常类型；
    - operation_name: 用于日志输出的操作名。
    """

    if attempts < 1:
        raise ValueError("attempts 必须大于等于 1")

    current_delay = delay_seconds
    last_error: Optional[BaseException] = None

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
                    logger.info(
                        "%s 将在 %.1f 秒后重试。",
                        operation_name,
                        current_delay,
                    )
                time.sleep(current_delay)
                current_delay *= backoff

    if last_error is not None:
        raise last_error

    raise RuntimeError(f"{operation_name} 重试执行结束，但未返回结果。")
