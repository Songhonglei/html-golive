#!/usr/bin/env python3
"""
audit_log.py — golive 本地审计日志模块

日志路径：$GOLIVE_HOME/logs/
  - golive.log             当日日志（不存在时自动创建）
  - golive.YYYY-MM-DD.log  历史日志（懒触发按天归档）
  - errors.log             失败记录汇总，90天有效期，不自动删除

用法：
    # 方式一：直接调用
    from golive.core.audit_log import log_call
    log_call(
        operation="publish",
        endpoint="local",
        params={"name": "xxx", "htmlSize": 1024},
        success=True,
        duration_ms=800,
        result={"siteId": "xxx"},
    )

    # 方式二：上下文管理器（自动计时，异常自动记录后继续上抛）
    with AuditLogger("publish", endpoint="local", params={...}) as ctx:
        result = do_publish(...)
        ctx.set_result(result)
"""

from __future__ import annotations

import datetime
import json
import sys
import time
import traceback
from contextlib import contextmanager
from pathlib import Path

from golive.i18n import t as _t
from typing import Any

# ── 路径配置（GOLIVE_HOME/logs/） ────────────────────────────────────────────
from golive.core.paths import get_log_dir as _get_log_dir  # noqa: E402

# LOG_DIR 等是模块级常量，在 import 时初始化（触发一次 mkdir，可接受）
LOG_DIR = _get_log_dir()
LOG_FILE = LOG_DIR / "golive.log"
ERRORS_FILE = LOG_DIR / "errors.log"

# 普通日志保留天数
_KEEP_DAYS = 30
# errors.log 单条记录有效期（天）
_ERROR_EXPIRE_DAYS = 90

# 需要脱敏的字段关键词（大小写不敏感）
_SENSITIVE_KEYS = {"token", "api_key", "apikey", "authorization", "password", "secret"}


# ── 初始化 ────────────────────────────────────────────────────────────────────
def _ensure_log_dir():
    LOG_DIR.mkdir(parents=True, exist_ok=True)


# ── 脱敏 ──────────────────────────────────────────────────────────────────────
def _sanitize(obj: Any, depth: int = 0) -> Any:
    """递归脱敏，敏感 key 的 value 替换为 '***'，最多 3 层。"""
    if depth > 3:
        return obj
    if isinstance(obj, dict):
        return {
            k: "***" if any(s in k.lower() for s in _SENSITIVE_KEYS)
               else _sanitize(v, depth + 1)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_sanitize(i, depth + 1) for i in obj]
    return obj


# ── 日志切分（懒触发） ─────────────────────────────────────────────────────────
def _rotate_if_needed():
    """
    写日志前检查 golive.log 的最后修改日。
    若不是今天，则归档为 golive.YYYY-MM-DD.log，再顺带清理 30 天前的归档。
    """
    if not LOG_FILE.exists():
        return  # 不存在，直接新建，无需处理

    try:
        mtime_date = datetime.date.fromtimestamp(LOG_FILE.stat().st_mtime)
        today = datetime.date.today()
        if mtime_date >= today:
            return  # 今天的，不需要切分

        # 归档
        archive = LOG_DIR / f"golive.{mtime_date}.log"
        if not archive.exists():
            LOG_FILE.rename(archive)

        # 清理超过 30 天的归档（errors.log 不在此范围）
        _cleanup_old_archives()
    except Exception:
        pass  # 切分失败不阻断写入


def _cleanup_old_archives():
    """删除超过 _KEEP_DAYS 天的 golive.YYYY-MM-DD.log 归档文件。"""
    try:
        cutoff = datetime.date.today() - datetime.timedelta(days=_KEEP_DAYS)
        for f in LOG_DIR.glob("golive.????-??-??.log"):
            try:
                # 从文件名解析日期
                date_str = f.stem.replace("golive.", "")
                file_date = datetime.date.fromisoformat(date_str)
                if file_date < cutoff:
                    f.unlink(missing_ok=True)
            except Exception:
                pass
    except Exception:
        pass


# ── 核心写入 ──────────────────────────────────────────────────────────────────
def _build_entry(
    operation: str,
    endpoint: str,
    params: dict,
    success: bool,
    duration_ms: int,
    result: Any = None,
    error: str | None = None,
) -> dict:
    now = datetime.datetime.now().astimezone()
    entry = {
        "timestamp": now.isoformat(),
        "operation": operation,
        "endpoint": endpoint,
        "params": _sanitize(params),
        "success": success,
        "duration_ms": duration_ms,
    }
    if success and result is not None:
        entry["result"] = _sanitize(result) if isinstance(result, dict) else result
    if not success:
        entry["error"] = error or "未知错误"
        # errors.log 额外记录过期时间
        entry["expire_at"] = (
            now + datetime.timedelta(days=_ERROR_EXPIRE_DAYS)
        ).isoformat()
    return entry


def _append_line(file_path: Path, entry: dict):
    """追加一行 JSON 到目标文件，文件不存在时自动创建。"""
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    try:
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(line)
    except (PermissionError, OSError) as e:
        import sys as _sys
        print(_t("audit.write_failed", path=file_path, error=e), file=_sys.stderr)


def log_call(
    operation: str,
    endpoint: str,
    params: dict,
    success: bool,
    duration_ms: int,
    result: Any = None,
    error: str | None = None,
):
    """
    写一条审计日志。

    Args:
        operation:    操作标识，如 "htmlToDoc" / "createTemplate"
        endpoint:     调用的接口 URL
        params:       入参摘要（不要传原始 HTML 内容，只传 name/size 等摘要）
        success:      是否成功
        duration_ms:  耗时毫秒
        result:       成功时的结果摘要（可选）
        error:        失败时的错误信息（可选）
    """
    try:
        _ensure_log_dir()
        _rotate_if_needed()
        entry = _build_entry(operation, endpoint, params, success, duration_ms, result, error)
        _append_line(LOG_FILE, entry)
        if not success:
            _append_line(ERRORS_FILE, entry)
    except Exception:
        pass  # 日志写入失败绝对不能影响主流程


# ── 上下文管理器 ──────────────────────────────────────────────────────────────
class AuditLogger:
    """
    上下文管理器，自动计时，异常时自动记录错误日志后继续上抛。

    用法：
        with AuditLogger("createTemplate", endpoint=url, params=p) as ctx:
            data = call_api(...)
            ctx.set_result({"templateId": data})
    """

    def __init__(self, operation: str, endpoint: str, params: dict):
        self.operation = operation
        self.endpoint = endpoint
        self.params = params
        self._start: float = 0.0
        self._result: Any = None

    def set_result(self, result: Any):
        self._result = result

    def __enter__(self):
        self._start = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        duration_ms = int((time.time() - self._start) * 1000)
        if exc_type is None:
            log_call(
                operation=self.operation,
                endpoint=self.endpoint,
                params=self.params,
                success=True,
                duration_ms=duration_ms,
                result=self._result,
            )
        else:
            error_msg = f"{exc_type.__name__}: {exc_val}"
            log_call(
                operation=self.operation,
                endpoint=self.endpoint,
                params=self.params,
                success=False,
                duration_ms=duration_ms,
                error=error_msg,
            )
        return False  # 不吞异常，继续上抛


# ── 便捷查询（供 SKILL.md 触发词使用） ────────────────────────────────────────
def get_log_paths() -> dict:
    """返回日志文件路径信息（供 AI 直接引用）。"""
    _ensure_log_dir()
    return {
        "log_dir": str(LOG_DIR),
        "today_log": str(LOG_FILE),
        "errors_log": str(ERRORS_FILE),
        "today_log_exists": LOG_FILE.exists(),
        "errors_log_exists": ERRORS_FILE.exists(),
    }


def tail_errors(n: int = 20) -> list[dict]:
    """读取 errors.log 最后 n 条记录，返回 list[dict]。
    使用 deque(maxlen=n) 逐行读取，避免大文件一次性加载进内存。
    """
    if not ERRORS_FILE.exists():
        return []
    try:
        from collections import deque
        buf: deque[str] = deque(maxlen=n)
        with open(ERRORS_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    buf.append(line)
        result = []
        for line in buf:
            try:
                result.append(json.loads(line))
            except Exception:
                pass
        return result
    except Exception:
        return []
