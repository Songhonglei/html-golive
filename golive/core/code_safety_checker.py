#!/usr/bin/env python3
"""
code_safety_checker.py — html-go-live HTML 代码安全检查模块

功能：
  扫描待发布 HTML 中内嵌的 JS/CSS 代码，检测三类工程安全问题：

  B 类 — 机密凭证明文（BLOCK，--skip-security 也不跳过，注释里也拦）
    B1  token/key/secret/appSecret 赋值为 ≥8 位字符串字面量
    B2  password/passwd/pwd 赋值为 ≥6 位字符串字面量
    B3  Bearer/Basic 明文（≥20 位）
    B4  私钥块（BEGIN PRIVATE KEY）
    B5  数据库连接串含用户名密码（jdbc/mongodb/redis/mysql/postgresql://user:pass@）
    B6  云平台 AK/SK 对（AccessKeyId/AccessKeySecret/aws_access ≥16 位）

  A 类 — 硬编码身份信息用于逻辑处理（WARN，可跳过，--yes 自动跳过）
    A1  邮箱完整地址或前缀出现在 if/switch/==/indexOf/includes/fetch/query 等逻辑语句中
        （纯展示不拦，只拦「用作固定查询/判断条件」的场景）

  C 类 — 本地绝对路径硬编码（WARN，可跳过，--yes 自动跳过）
    C1  Unix 绝对路径（/home/xxx/ /Users/xxx/ /root/）出现在字符串赋值中
    C2  Windows 绝对路径（C:\\Users\\ D:\\home\\）出现在字符串赋值中

协作关系：
  - 本模块扫描「工程安全问题」，security_scanner.py 扫描「业务敏感数据」
  - 调用方在 security_scanner.run_security_scan 之前调用本模块
  - B 类 BLOCK 时直接 sys.exit(1)，A/C 类 WARN 时询问用户（--yes 自动跳过）

返回值（run_check）：
  (passed: bool, issues: list[dict])
  - passed=True  → 无 BLOCK 问题，发布可继续
  - passed=False → 存在 BLOCK 问题，调用方应 sys.exit(1)
  issues 每项结构：
    {"level": "BLOCK"|"WARN", "category": "B1"|"A1"|"C1"...,
     "label": str, "context": str, "line_hint": str}
"""


from __future__ import annotations
import re
import sys

from golive.i18n import t as _t

# ── 规则定义 ──────────────────────────────────────────────────────────────────

# B 类：机密凭证（BLOCK）——在原始 HTML 全文扫描，注释里也拦
_B_RULES: list[tuple[str, str, re.Pattern]] = [
    # B1: token/key/secret 赋值（变量名包含这些词，值为 ≥8 位字符串）
    (
        "B1",
        "机密凭证：token/key/secret 明文赋值",
        re.compile(
            r'(?:token|apikey|api_key|secret|appSecret|app_secret|access_key|'
            r'accesskey|private_key|privatekey|auth_token|authtoken|bearer_token|'
            r'client_secret|clientsecret|refresh_token|refreshtoken|id_token|idtoken)\s*'
            r'[=:]\s*["\']([A-Za-z0-9+/\-_@.]{8,})["\']',
            re.IGNORECASE,
        ),
    ),
    # B2: password/passwd/pwd 赋值
    (
        "B2",
        "机密凭证：password/passwd/pwd 明文赋值",
        re.compile(
            r'(?:password|passwd|pwd)\s*[=:]\s*["\']([^"\']{6,})["\']',
            re.IGNORECASE,
        ),
    ),
    # B3: Authorization: Bearer/Basic 明文
    (
        "B3",
        "机密凭证：Authorization Bearer/Basic 明文",
        re.compile(
            r'(?:Bearer|Basic)\s+([A-Za-z0-9+/=\-_]{20,})',
            re.IGNORECASE,
        ),
    ),
    # B4: 私钥块（字符串拆分，避免 SAST 误报本文件自身）
    (
        "B4",
        "机密凭证：私钥块（BEGIN PRIVATE KEY）",
        re.compile(
            "-----BEGIN" + r"\s+[A-Z ]*" + "PRIVATE" + r"\s+KEY-----",
        ),
    ),
    # B5: 数据库连接串含用户名密码
    (
        "B5",
        "机密凭证：数据库连接串含明文密码",
        re.compile(
            r'(?:jdbc|mongodb|redis|mysql|postgresql|postgres)\s*:\s*//\s*\w[^@\s]*:[^@\s]+@',
            re.IGNORECASE,
        ),
    ),
    # B6: 云平台 AK/SK
    (
        "B6",
        "机密凭证：云平台 AccessKeyId/AccessKeySecret 明文",
        re.compile(
            r'(?:AccessKeyId|AccessKeySecret|aws_access_key_id|aws_secret_access_key)\s*'
            r'[=:]\s*["\']([A-Za-z0-9/+\-_]{16,})["\']',
            re.IGNORECASE,
        ),
    ),
]

# A 类：硬编码身份信息用于逻辑处理（WARN）
# 策略：在 JS 代码块（<script>...</script>）中扫描，而非全文
# 只拦「用于逻辑处理」的场景：邮箱/前缀出现在 if/switch/==/indexOf/includes/fetch/query 行
_A_EMAIL_PATTERN = re.compile(
    r'[\w.\-+]+@[\w\-]+(?:\.[\w\-]+)+',
    re.IGNORECASE,
)
# 硬编码身份信息的逻辑处理上下文关键词（行级检测）
_A_LOGIC_KEYWORDS = re.compile(
    r'\b(?:if|switch|case|===|!==|==|!=|indexOf|includes|startsWith|endsWith|'
    r'fetch|ajax|axios|request|query|filter|find|match|search|replace|'
    r'userId|user_id|creatorId|creator_id|authorId|author_id|email|'
    r'WHERE|FROM|SELECT|JOIN)\b',
    re.IGNORECASE,
)

# C 类：本地绝对路径（WARN）
_C_RULES: list[tuple[str, str, re.Pattern]] = [
    (
        "C1",
        "硬编码路径：Unix 绝对路径（/home/xxx/ 或 /Users/xxx/）",
        re.compile(
            r'["\'](?:/home/\w+/|/Users/\w+/|/root/)[\w./\-]*["\']',
        ),
    ),
    (
        "C2",
        "硬编码路径：Windows 绝对路径（C:\\Users\\ 等）",
        re.compile(
            r'["\'][A-Za-z]:\\\\(?:Users|home|Documents|Desktop)\\\\[\w\\./\-]*["\']',
            re.IGNORECASE,
        ),
    ),
]


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def _mask_value(text: str, window: int = 40) -> str:
    """截取上下文并对明文值做部分遮罩。"""
    snippet = text[:window * 2].strip()
    # 遮罩：引号内 8 位以上的值，保留前 4 位
    snippet = re.sub(
        r'(["\'])([A-Za-z0-9+/\-_@.]{4})[A-Za-z0-9+/\-_@.=]{4,}\1',
        r'\1\2****\1',
        snippet,
    )
    # 遮罩：连续 6 位以上数字
    snippet = re.sub(r'(\d{2})\d{4,}(\d{2})', r'\1****\2', snippet)
    return snippet.strip()


def _extract_scripts(html: str) -> list[str]:
    """提取 HTML 中所有内联 <script>...</script> 块的内容（排除外链脚本 src=...）。"""
    blocks = []
    for m in re.finditer(r'<script\b(?![^>]*\bsrc\s*=)[^>]*>([\s\S]*?)</script>', html, re.IGNORECASE):
        blocks.append(m.group(1))
    return blocks


def _find_line_hint_for_match(html: str, m: re.Match) -> str:
    """根据给定 match 对象找到所在行（截断显示）。"""
    start = html.rfind('\n', 0, m.start())
    end = html.find('\n', m.end())
    line = html[start + 1: end if end != -1 else m.end() + 60].strip()
    return line[:120]


# ── 核心检查 ──────────────────────────────────────────────────────────────────

def _check_b_class(html: str) -> list[dict]:
    """B 类检查：在原始 HTML 全文扫描机密凭证（注释里也拦）。每条规则报告所有命中。"""
    issues = []
    for cat, label, pattern in _B_RULES:
        for m in pattern.finditer(html):
            line_hint = _find_line_hint_for_match(html, m)
            context = _mask_value(line_hint or m.group(0))
            issues.append({
                "level": "BLOCK",
                "category": cat,
                "label": label,
                "context": context,
                "line_hint": line_hint,
            })
    return issues


def _check_a_class(html: str) -> list[dict]:
    """
    A 类检查：在 <script> 块中检测硬编码邮箱/用户 ID 用于逻辑处理。
    只拦「与逻辑关键词同行」的场景，纯展示不拦。
    """
    issues = []
    scripts = _extract_scripts(html)
    found_emails: set[str] = set()

    for script in scripts:
        for line in script.splitlines():
            emails = _A_EMAIL_PATTERN.findall(line)
            if not emails:
                continue
            # 检查同行是否有逻辑处理关键词
            if not _A_LOGIC_KEYWORDS.search(line):
                continue
            for email in emails:
                if email in found_emails:
                    continue
                found_emails.add(email)
                context = _mask_value(line.strip())
                issues.append({
                    "level": "WARN",
                    "category": "A1",
                    "label": f"硬编码身份信息：邮箱 {email} 用于逻辑处理",
                    "context": context,
                    "line_hint": line.strip()[:120],
                })

    return issues


def _check_c_class(html: str) -> list[dict]:
    """C 类检查：在 <script> 块中检测本地绝对路径赋值。"""
    issues = []
    # 仅在 script 块中检测，避免 CSS url() 误报
    scripts = _extract_scripts(html)
    script_content = "\n".join(scripts)

    for cat, label, pattern in _C_RULES:
        for m in pattern.finditer(script_content):
            line_hint = _find_line_hint_for_match(script_content, m)
            context = _mask_value(line_hint or m.group(0))
            issues.append({
                "level": "WARN",
                "category": cat,
                "label": label,
                "context": context,
                "line_hint": line_hint,
            })
    return issues


# ── 对外主入口 ────────────────────────────────────────────────────────────────

def run_check(
    html: str,
    auto_yes: bool = False,
    skip_warn: bool = False,
) -> tuple[bool, list[dict]]:
    """
    执行代码安全检查。

    Args:
        html:       待发布的 HTML 字符串
        auto_yes:   True = --yes 模式，A/C 类 WARN 自动跳过（B 类不受影响）
        skip_warn:  True = --skip-code-check 模式，A/C 类 WARN 直接跳过不输出（B 类不受影响）

    Returns:
        (passed, issues)
        - passed=True  → 无 BLOCK，A/C 类已处置，发布可继续
        - passed=False → 存在 BLOCK 问题，调用方应 sys.exit(1)
        issues: 全部问题列表（含已跳过的 WARN）
    """
    all_issues: list[dict] = []

    # 收集所有问题
    all_issues.extend(_check_b_class(html))
    all_issues.extend(_check_a_class(html))
    all_issues.extend(_check_c_class(html))

    if not all_issues:
        print(_t("safety.check_passed"), file=sys.stderr)
        return True, []

    # 分组
    block_issues = [i for i in all_issues if i["level"] == "BLOCK"]
    warn_issues  = [i for i in all_issues if i["level"] == "WARN"]

    _SEP = "─" * 60

    # ── 打印 BLOCK 报告 ──
    if block_issues:
        print(file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        print(_t("safety.block_title"), file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        print(_t("safety.block_count", count=len(block_issues)), file=sys.stderr)
        for idx, issue in enumerate(block_issues, 1):
            print(_t("safety.block_item", idx=idx, cat=issue['category'], label=issue['label']), file=sys.stderr)
            if issue["context"]:
                print(_t("safety.block_context", context=issue['context']), file=sys.stderr)
        print(file=sys.stderr)
        print(_t("safety.block_hint_title"), file=sys.stderr)
        print(_t("safety.block_hint_token"), file=sys.stderr)
        print(_t("safety.block_hint_password"), file=sys.stderr)
        print(_t("safety.block_hint_db"), file=sys.stderr)
        print(_t("safety.block_hint_cloud"), file=sys.stderr)
        print(f"\n{_SEP}", file=sys.stderr)

    # ── 打印 WARN 报告（有 BLOCK 时跳过交互，skip_warn 时直接静默跳过）──
    if warn_issues and not skip_warn:
        print(file=sys.stderr)
        print(_SEP, file=sys.stderr)
        print(_t("safety.warn_title"), file=sys.stderr)
        print(_SEP, file=sys.stderr)
        print(_t("safety.warn_count", count=len(warn_issues)), file=sys.stderr)
        for idx, issue in enumerate(warn_issues, 1):
            print(_t("safety.block_item", idx=idx, cat=issue['category'], label=issue['label']), file=sys.stderr)
            if issue["context"]:
                print(_t("safety.block_context", context=issue['context']), file=sys.stderr)
        print(file=sys.stderr)
        print(_t("safety.block_hint_title"), file=sys.stderr)
        print(_t("safety.warn_hint_email"), file=sys.stderr)
        print(_t("safety.warn_hint_path"), file=sys.stderr)

        if block_issues:
            # 已有 BLOCK 阻断，WARN 仅输出不再询问
            print(_t("safety.warn_block_note"), file=sys.stderr)
            print(_SEP, file=sys.stderr)
        elif auto_yes:
            print(_t("safety.warn_yes_note"), file=sys.stderr)
            print(_SEP, file=sys.stderr)
        else:
            # 交互确认
            print(_t("safety.warn_prompt"), file=sys.stderr, end=" ")
            try:
                ans = input().strip().lower()
            except (EOFError, KeyboardInterrupt):
                ans = ""
            print(_SEP, file=sys.stderr)
            if ans not in ("y", "yes", "是", "继续"):
                print(_t("safety.abort"), file=sys.stderr)
                return False, all_issues

    # BLOCK 存在 → 无论 WARN 如何都返回 False
    if block_issues:
        return False, all_issues

    return True, all_issues


# ── 独立 CLI（供 agent 直接调用诊断）────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description=_t("safety.cli_desc"))
    ap.add_argument("file", help=_t("safety.cli_arg_file"))
    ap.add_argument("--yes", action="store_true", help=_t("safety.cli_arg_yes"))
    ap.add_argument("--skip-code-check", action="store_true", help=_t("safety.cli_arg_skip"))
    _args = ap.parse_args()

    from pathlib import Path as _Path
    _html = _Path(_args.file).read_text(encoding="utf-8", errors="replace")
    _passed, _issues = run_check(
        _html,
        auto_yes=_args.yes,
        skip_warn=_args.skip_code_check,
    )
    sys.exit(0 if _passed else 1)
