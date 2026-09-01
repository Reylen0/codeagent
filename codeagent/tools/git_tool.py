import locale
import os
import subprocess
import sys

from pydantic import BaseModel, Field

from baseagent.tools.base import BaseTool

_TIMEOUT = 30

if sys.platform == "win32":
    import ctypes
    _SYS_ENCODING = f"cp{ctypes.windll.kernel32.GetOEMCP()}"
else:
    _SYS_ENCODING = locale.getpreferredencoding(False) or "utf-8"

_ALLOWED_ACTIONS = {"status", "diff", "add", "commit", "log", "branch", "show"}


class GitToolParam(BaseModel):
    action: str = Field(
        description=(
            "git 操作名称，支持: "
            "status（查看状态）、diff（查看改动）、add（暂存文件）、"
            "commit（提交）、log（查看历史）、branch（列出分支）、show（查看某次提交）"
        )
    )
    files: str = Field(
        default="",
        description="add 操作的目标文件或目录，空格分隔；留空则暂存所有改动（git add .）",
    )
    message: str = Field(
        default="",
        description="commit 操作的提交信息（-m 参数）",
    )
    count: int = Field(
        default=10,
        description="log 操作显示的提交条数，默认 10",
    )
    extra: str = Field(
        default="",
        description="附加给 git 命令的额外参数，直接追加在命令末尾",
    )
    workdir: str = Field(
        default=".",
        description="执行 git 命令的工作目录，默认当前目录",
    )


class GitTool(BaseTool):
    """Git 操作工具"""

    name: str = "git"
    description: str = (
        "执行常用 git 操作：查看状态、查看 diff、暂存文件、提交、查看日志。"
        "在指定工作目录下运行，适合对当前项目进行版本控制操作。"
    )
    param_class = GitToolParam

    def execute(self, parameters: GitToolParam) -> str:
        action = parameters.action.lower().strip()
        if action not in _ALLOWED_ACTIONS:
            return (
                f"错误: 不支持的操作 '{action}'，"
                f"可用操作: {', '.join(sorted(_ALLOWED_ACTIONS))}"
            )

        workdir = os.path.abspath(parameters.workdir)
        if not os.path.isdir(workdir):
            return f"错误: 工作目录不存在 — {workdir}"

        cmd = self._build_command(action, parameters)
        return self._run(cmd, workdir)

    def _build_command(self, action: str, p: GitToolParam) -> list[str]:
        base = ["git"]

        if action == "status":
            cmd = base + ["status", "--short", "--branch"]

        elif action == "diff":
            cmd = base + ["diff"]
            if p.files:
                cmd += ["--", *p.files.split()]

        elif action == "add":
            targets = p.files.split() if p.files.strip() else ["."]
            cmd = base + ["add", "--"] + targets

        elif action == "commit":
            if not p.message.strip():
                return ["git", "status"]  # 无 message 时安全降级到 status
            cmd = base + ["commit", "-m", p.message]

        elif action == "log":
            cmd = base + ["log", f"--max-count={p.count}", "--oneline", "--decorate"]

        elif action == "branch":
            cmd = base + ["branch", "-vv"]

        elif action == "show":
            cmd = base + ["show", "--stat"]

        else:
            cmd = base + [action]

        if p.extra.strip():
            cmd += p.extra.split()

        return cmd

    def _run(self, cmd: list[str], cwd: str) -> str:
        try:
            proc = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=_TIMEOUT,
                encoding=_SYS_ENCODING,
                errors="replace",
            )
        except FileNotFoundError:
            return "错误: 未找到 git 命令，请确认 git 已安装并在 PATH 中"
        except subprocess.TimeoutExpired:
            return f"错误: git 命令超时（{_TIMEOUT}s）"
        except Exception as e:
            return f"错误: {e}"

        parts = []
        if proc.stdout.strip():
            parts.append(proc.stdout.rstrip())
        if proc.stderr.strip():
            parts.append(f"[stderr]\n{proc.stderr.rstrip()}")
        if proc.returncode != 0 and not parts:
            parts.append(f"[退出码: {proc.returncode}]")

        return "\n".join(parts) if parts else "(无输出)"
