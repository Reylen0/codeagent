import os

from pydantic import BaseModel, Field

from baseagent.tools.base import BaseTool

_SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    ".mypy_cache", "dist", "build", ".pytest_cache", ".tox",
}

_MAX_ENTRIES = 500  # 单次最多列出条目数


class LsToolParam(BaseModel):
    path: str = Field(default=".", description="要列出的目录路径，默认当前工作目录")
    depth: int = Field(default=2, description="目录树展开深度，默认 2，设为 1 只看顶层")
    show_hidden: str = Field(default="false", description="是否显示隐藏文件（. 开头），true 或 false")


class LsTool(BaseTool):
    """目录内容列出工具"""

    name: str = "ls"
    description: str = (
        "以树形结构列出目录内容，显示文件大小。"
        "自动跳过 .git、node_modules、__pycache__ 等目录。"
        "适合快速了解项目结构。"
    )
    param_class = LsToolParam

    def execute(self, parameters: LsToolParam) -> str:
        root = os.path.abspath(parameters.path)
        if not os.path.exists(root):
            return f"错误: 路径不存在 — {root}"

        if os.path.isfile(root):
            size = os.path.getsize(root)
            return f"{root}  ({_fmt_size(size)})"

        show_hidden = parameters.show_hidden.lower() == "true"
        lines = [root + "/"]
        counter = [0]

        self._walk(root, root, parameters.depth, 0, show_hidden, lines, counter)

        if counter[0] >= _MAX_ENTRIES:
            lines.append(f"  ... (条目过多，已截断至 {_MAX_ENTRIES} 项)")

        return "\n".join(lines)

    def _walk(
        self,
        root: str,
        current: str,
        max_depth: int,
        depth: int,
        show_hidden: bool,
        lines: list,
        counter: list,
    ) -> None:
        if depth >= max_depth or counter[0] >= _MAX_ENTRIES:
            return

        try:
            entries = sorted(os.listdir(current))
        except PermissionError:
            lines.append("  " * (depth + 1) + "[权限不足]")
            return

        dirs = [e for e in entries if os.path.isdir(os.path.join(current, e))]
        files = [e for e in entries if os.path.isfile(os.path.join(current, e))]

        indent = "  " * (depth + 1)

        for d in dirs:
            if counter[0] >= _MAX_ENTRIES:
                break
            if d in _SKIP_DIRS:
                continue
            if not show_hidden and d.startswith("."):
                continue
            lines.append(f"{indent}{d}/")
            counter[0] += 1
            self._walk(
                root, os.path.join(current, d),
                max_depth, depth + 1, show_hidden, lines, counter,
            )

        for fn in files:
            if counter[0] >= _MAX_ENTRIES:
                break
            if not show_hidden and fn.startswith("."):
                continue
            size = os.path.getsize(os.path.join(current, fn))
            lines.append(f"{indent}{fn}  ({_fmt_size(size)})")
            counter[0] += 1


def _fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n}B"
    if n < 1024 ** 2:
        return f"{n / 1024:.1f}KB"
    return f"{n / 1024 ** 2:.1f}MB"
