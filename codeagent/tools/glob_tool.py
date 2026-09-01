import glob as _glob
import os

from pydantic import BaseModel, Field

from baseagent.tools.base import BaseTool

# 搜索时跳过的目录
_SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    ".mypy_cache", "dist", "build", ".pytest_cache", ".tox",
}


class GlobToolParam(BaseModel):
    pattern: str = Field(description="Glob 模式，如 **/*.py、src/**/*.ts、tests/test_*.py")
    path: str = Field(default=".", description="搜索根目录，默认当前工作目录")


class GlobTool(BaseTool):
    """文件名模式搜索工具"""

    name: str = "glob"
    description: str = (
        "按 glob 模式递归搜索文件，返回相对路径列表。"
        "支持 ** 跨目录通配，如 **/*.py 搜索所有 Python 文件。"
        "自动跳过 .git、node_modules、__pycache__ 等目录。"
    )
    param_class = GlobToolParam

    def execute(self, parameters: GlobToolParam) -> str:
        root = os.path.abspath(parameters.path)
        if not os.path.isdir(root):
            return f"错误: 目录不存在 — {root}"

        full_pattern = os.path.join(root, parameters.pattern)
        try:
            raw_matches = _glob.glob(full_pattern, recursive=True)
        except Exception as e:
            return f"错误: glob 搜索失败 — {e}"

        matches = []
        for m in sorted(raw_matches):
            if not os.path.isfile(m):
                continue
            rel = os.path.relpath(m, root)
            parts = rel.replace("\\", "/").split("/")
            if any(p in _SKIP_DIRS for p in parts):
                continue
            matches.append(rel.replace("\\", "/"))

        if not matches:
            return f"未找到匹配 '{parameters.pattern}' 的文件（搜索于 {root}）"

        return "\n".join(matches) + f"\n\n共 {len(matches)} 个文件"
