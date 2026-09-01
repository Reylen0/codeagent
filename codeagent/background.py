"""
后台任务管理器 —— 让慢操作在独立线程中运行，Agent 循环不阻塞。

工作流：
  1. start(command) 启动后台线程，立刻返回 bg_id 占位符
  2. 线程完成后把结果放入就绪队列
  3. 每次 llm.invoke() 前，collect() 取出已完成的任务，格式化为通知消息
"""

import subprocess
import sys
import threading
import locale
from typing import Optional

if sys.platform == "win32":
    import ctypes
    _SYS_ENCODING = f"cp{ctypes.windll.kernel32.GetOEMCP()}"
else:
    _SYS_ENCODING = locale.getpreferredencoding(False) or "utf-8"

_MAX_OUTPUT = 20_000   # 后台任务输出截断长度


class BackgroundManager:
    """
    管理后台 bash 任务的生命周期。

    线程安全：所有对 tasks/results/_ready 的修改都在锁保护下进行。
    线程为 daemon，主进程退出时自动终止。
    """

    def __init__(self):
        self._tasks: dict[str, dict] = {}   # bg_id → {command, status}
        self._results: dict[str, str] = {}  # bg_id → 格式化结果文本
        self._ready: list[str] = []         # 已完成待收集的 bg_id 列表
        self._lock = threading.Lock()
        self._counter = 0

    # ── 公开接口 ──────────────────────────────────────────────────────────

    def start(self, command: str) -> str:
        """启动后台任务，返回 bg_id。"""
        with self._lock:
            self._counter += 1
            bg_id = f"bg_{self._counter:04d}"
            self._tasks[bg_id] = {"command": command, "status": "running"}

        thread = threading.Thread(
            target=self._run,
            args=(bg_id, command),
            daemon=True,
        )
        thread.start()
        return bg_id

    def collect(self) -> list[str]:
        """取出所有已完成的任务，格式化为通知字符串列表。"""
        with self._lock:
            ready = list(self._ready)
            self._ready.clear()

        notifications = []
        for bg_id in ready:
            result = self._results.pop(bg_id, "(no output)")
            notifications.append(result)
        return notifications

    def has_running(self) -> bool:
        with self._lock:
            return any(t["status"] == "running" for t in self._tasks.values())

    # ── 内部实现 ──────────────────────────────────────────────────────────

    def _run(self, bg_id: str, command: str):
        """后台线程执行入口。"""
        try:
            if sys.platform == "win32":
                proc = subprocess.run(
                    command, shell=True,
                    capture_output=True, text=True,
                    encoding=_SYS_ENCODING, errors="replace",
                )
            else:
                proc = subprocess.run(
                    ["bash", "-c", command],
                    capture_output=True, text=True,
                    encoding=_SYS_ENCODING, errors="replace",
                )
            output = _format_output(proc.stdout, proc.stderr, proc.returncode)
            status = "completed" if proc.returncode == 0 else "failed"
            label = f"completed (exit {proc.returncode})" if proc.returncode == 0 else f"failed (exit {proc.returncode})"
        except Exception as e:
            output = f"Error: {e}"
            status = "failed"
            label = "failed"

        result = (
            f"<task_notification>\n"
            f"Background task {bg_id} {label}.\n"
            f"Command: {command}\n"
            f"Output:\n{output}\n"
            f"</task_notification>"
        )

        with self._lock:
            self._tasks[bg_id]["status"] = status
            self._results[bg_id] = result
            self._ready.append(bg_id)


# ── 辅助函数 ─────────────────────────────────────────────────────────────

def _format_output(stdout: str, stderr: str, returncode: int) -> str:
    parts = []
    if stdout:
        parts.append(stdout[:_MAX_OUTPUT])
    if stderr:
        parts.append(f"[stderr]\n{stderr[:_MAX_OUTPUT]}")
    if not parts:
        parts.append("(no output)")
    return "\n".join(parts)
