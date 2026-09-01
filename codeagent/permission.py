"""
权限管线 —— 工具执行前的三道闸门

闸门 1：硬拒绝列表        命中 → 直接拒绝，不执行
闸门 2：规则匹配          命中 → 进入闸门 3
闸门 3：用户审批          用户输入 y/N 决定允许或拒绝

三道都未命中 → 放行执行。
"""

import json
import os
from pathlib import Path

from baseagent.tools.executor import ToolExecutor
from baseagent.tools.registry import ToolRegistry

# ──────────────────────────────────────────────
# 闸门 1：硬拒绝模式（bash 专用）
# bash_tool 自带一层拦截，这里补充更精确的 Windows 场景
# ──────────────────────────────────────────────
_BASH_HARD_DENY: list[tuple[str, str]] = [
    ("rm -rf /",          "递归删除根目录"),
    ("rm -rf \\",         "递归删除根目录"),
    ("sudo rm",           "以 sudo 执行删除"),
    (":(){ :|:",          "fork bomb"),
    ("rd /s /q c:\\",     "递归删除 C 盘"),
    ("rd /s /q c:/",      "递归删除 C 盘"),
    ("format c:",         "格式化 C 盘"),
    ("del /f /s /q c:\\", "递归删除 C 盘文件"),
]

# ──────────────────────────────────────────────
# 闸门 2：软规则 —— 命中时转到闸门 3 让用户决定
# 格式：(工具名集合, 检查函数(args, workdir) -> bool, 展示给用户的原因)
# ──────────────────────────────────────────────
_RULES: list[tuple[set, object, str]] = [
    # 写文件 / 编辑文件：路径逃出工作目录
    (
        {"file_write", "file_edit"},
        lambda args, wd: not _inside_workdir(args.get("path", "."), wd),
        "写入路径在工作目录之外",
    ),
    # 读文件：路径逃出工作目录（读比写风险低，仍询问）
    (
        {"file_read"},
        lambda args, wd: not _inside_workdir(args.get("path", "."), wd),
        "读取路径在工作目录之外",
    ),
    # Bash：包含 rm / del / rmdir 等删除命令
    (
        {"bash"},
        lambda args, _: _has_any(args.get("command", ""), ["rm ", "del ", "rmdir ", "Remove-Item"]),
        "命令包含删除操作",
    ),
    # Bash：向系统路径写入
    (
        {"bash"},
        lambda args, _: _has_any(args.get("command", ""), [
            "> /etc/", "> /usr/", "> /bin/", "> /boot/",
            "> C:\\Windows\\", "> C:\\System32",
        ]),
        "命令向系统路径写入",
    ),
    # Bash：修改文件权限为 777
    (
        {"bash"},
        lambda args, _: "chmod 777" in args.get("command", ""),
        "命令将权限设置为 777",
    ),
]


# ──────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────
def _inside_workdir(path: str, workdir: str) -> bool:
    """判断 path 是否在 workdir 内（包含 workdir 本身）。"""
    try:
        resolved = Path(os.path.abspath(path)).resolve()
        wd = Path(os.path.abspath(workdir)).resolve()
        resolved.relative_to(wd)
        return True
    except ValueError:
        return False


def _has_any(text: str, patterns: list[str]) -> bool:
    text_lower = text.lower()
    return any(p.lower() in text_lower for p in patterns)


def _short(val: object, limit: int = 80) -> str:
    s = str(val)
    return s[:limit] + "…" if len(s) > limit else s


# ──────────────────────────────────────────────
# PermissionToolExecutor
# ──────────────────────────────────────────────
_REMINDER = (
    "\n\n<reminder>请更新 TODO 列表：将已完成的任务标记为 completed，"
    "将当前正在进行的任务标记为 in_progress。</reminder>"
)
_REMINDER_THRESHOLD = 3   # 连续多少轮没调用 todo_write 后触发


class PermissionToolExecutor(ToolExecutor):
    """
    在工具执行前插入三道权限闸门，同时跟踪 TODO 更新频率。
    继承 ToolExecutor，只重写 execute()，其余逻辑不变。
    """

    def __init__(self, registry: ToolRegistry, workdir: str, todo_manager=None):
        super().__init__(registry)
        self.workdir = os.path.abspath(workdir)
        self._todo_manager = todo_manager   # TodoManager 引用，用于判断列表是否非空
        self._rounds_since_todo = 0         # 距上次调用 todo_write 的工具轮次

    def execute(self, tool_call: dict) -> dict:
        tool_call_id = tool_call.get("id", "")
        function = tool_call.get("function", {})
        name = function.get("name", "")

        try:
            args = json.loads(function.get("arguments", "{}"))
        except Exception:
            args = {}

        # ── 闸门 1：硬拒绝 ──────────────────────────────────────────
        if name == "bash":
            command = args.get("command", "").lower()
            for pattern, reason in _BASH_HARD_DENY:
                if pattern.lower() in command:
                    print(f"\n[DENY] {reason} (pattern: {repr(pattern)})", flush=True)
                    return self._denied(tool_call_id, f"硬拒绝: {reason}")

        # ── 闸门 2 + 3：规则匹配 → 用户审批 ─────────────────────────
        for tool_names, check_fn, reason in _RULES:
            if name not in tool_names:
                continue
            try:
                triggered = check_fn(args, self.workdir)
            except Exception:
                triggered = False
            if not triggered:
                continue

            # 命中规则，进入闸门 3
            allowed = self._ask_user(name, args, reason)
            if not allowed:
                return self._denied(tool_call_id, "用户拒绝执行")
            break  # 用户批准，放行，不再检查后续规则

        # ── 放行：交给原始执行器 ─────────────────────────────────────
        result = super().execute(tool_call)

        # ── Reminder：督促 Agent 更新 TODO ──────────────────────────
        if name == "todo_write":
            self._rounds_since_todo = 0
        else:
            self._rounds_since_todo += 1
            if (self._rounds_since_todo >= _REMINDER_THRESHOLD
                    and self._todo_manager
                    and not self._todo_manager.is_empty()):
                result = dict(result)
                result["content"] += _REMINDER
                self._rounds_since_todo = 0

        return result

    # ──────────────────────────────────────────────
    # 辅助方法
    # ──────────────────────────────────────────────
    @staticmethod
    def _denied(tool_call_id: str, reason: str) -> dict:
        return {"role": "tool", "tool_call_id": tool_call_id, "content": f"Permission denied: {reason}"}

    @staticmethod
    def _ask_user(tool_name: str, args: dict, reason: str) -> bool:
        """闸门 3：暂停，展示上下文，等待用户决策。"""
        # 精简显示参数，避免大段内容刷屏
        display: dict = {}
        for k, v in args.items():
            display[k] = _short(v, 100) if k != "content" else f"<{len(str(v))} chars>"

        print(f"\n[WARN] {reason}")
        print(f"    tool : {tool_name}")
        for k, v in display.items():
            print(f"    {k}: {v}")
        try:
            choice = input("    允许执行？[y/N] ").strip().lower()
            print()
            return choice in ("y", "yes")
        except (EOFError, KeyboardInterrupt):
            print()
            return False
