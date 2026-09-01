import locale
import re
import subprocess
import sys
from typing import Optional

from pydantic import BaseModel, Field

from baseagent.tools.base import BaseTool

_TIMEOUT = 30
_MAX_OUTPUT = 50_000

# Windows 系统命令输出使用 OEM 代码页（如 GBK/936），其他平台跟随 locale
if sys.platform == "win32":
    import ctypes
    _SYS_ENCODING = f"cp{ctypes.windll.kernel32.GetOEMCP()}"
else:
    _SYS_ENCODING = locale.getpreferredencoding(False) or "utf-8"

# 危险命令模式（命令开头匹配）
_DANGEROUS_PATTERNS = [
    r"rm\s+-[^\s]*r",       # rm -rf / rm -r
    r"rm\s+/",              # rm /...
    r":\(\)\{",             # fork bomb
    r"mkfs",                # 格式化磁盘
    r"dd\s+",               # dd 磁盘操作
    r">\s*/dev/sd",         # 写入磁盘设备
    r"chmod\s+-R\s+777",    # 递归改权限
    r"sudo\s+rm",           # sudo 删除
    r"shutdown",            # 关机
    r"reboot",              # 重启
    r"format\s+[a-zA-Z]:",  # Windows 格式化
    r"del\s+/[sqf]",        # Windows 递归删除
    r"rd\s+/s",             # Windows 递归删除目录
]

_DANGEROUS_RE = re.compile(
    "|".join(_DANGEROUS_PATTERNS),
    re.IGNORECASE
)


class BashToolParam(BaseModel):
    command: str = Field(description="要执行的 shell 命令，例如 ls -la 或 python --version")
    timeout: int = Field(default=_TIMEOUT, description="超时秒数，默认 30（后台任务忽略此参数）")
    run_in_background: bool = Field(
        default=False,
        description="设为 true 时命令在后台线程执行，立刻返回任务 ID，不阻塞 Agent 循环。"
                    "适合耗时命令（安装依赖、跑测试、构建等）。"
                    "结果会在后续轮次开始时以 <task_notification> 形式返回。"
    )


class BashTool(BaseTool):
    """执行 Shell 命令工具

    ⚠️  安全警告:本工具会在本机直接执行任意 shell 命令。
    在面向外部用户的场景中使用时，请注意提示注入风险——
    恶意输入可能诱导 LLM 调用此工具执行危险命令。
    内置了常见危险命令拦截，但无法覆盖所有攻击面。
    """

    name: str = "bash"
    description: str = (
        "在本地执行 shell 命令并返回标准输出和标准错误。"
        "耗时命令（安装依赖、跑测试、构建）可设 run_in_background=true 在后台执行，"
        "不阻塞 Agent 循环，结果在后续轮次以通知形式返回。"
    )
    param_class = BashToolParam

    def __init__(self, background_manager=None):
        self._bg_manager = background_manager  # BackgroundManager | None

    def execute(self, parameters: BashToolParam) -> str:
        command = parameters.command.strip()

        if _DANGEROUS_RE.search(command):
            return "Error: Dangerous command blocked"

        # 后台执行路径
        if parameters.run_in_background and self._bg_manager is not None:
            bg_id = self._bg_manager.start(command)
            return (
                f"[Background task {bg_id} started]\n"
                f"Command: {command}\n"
                f"The result will appear as a <task_notification> in a later turn."
            )

        # 同步执行路径
        if sys.platform == "win32":
            shell_args = command
            use_shell = True
        else:
            shell_args = ["bash", "-c", command]
            use_shell = False

        try:
            proc = subprocess.run(
                shell_args,
                shell=use_shell,
                capture_output=True,
                text=True,
                timeout=parameters.timeout,
                encoding=_SYS_ENCODING,
                errors="replace",
            )
        except subprocess.TimeoutExpired:
            return f"错误: 命令执行超时 ({parameters.timeout}s)"
        except Exception as e:
            return f"错误: {e}"

        parts = []
        if proc.stdout:
            parts.append(proc.stdout[:_MAX_OUTPUT])
        if proc.stderr:
            parts.append(f"[stderr]\n{proc.stderr[:_MAX_OUTPUT]}")
        if proc.returncode != 0:
            parts.append(f"[退出码: {proc.returncode}]")

        return "\n".join(parts) if parts else "(无输出)"
