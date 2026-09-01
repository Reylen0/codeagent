import os

from pydantic import BaseModel, Field

from baseagent.tools.base import BaseTool

_MAX_FILE_SIZE = 2_000_000  # 2MB


class FileEditToolParam(BaseModel):
    path: str = Field(description="要编辑的文件路径（绝对路径或相对路径）")
    old_string: str = Field(description="要替换的原始字符串，必须在文件中精确匹配且唯一")
    new_string: str = Field(description="替换后的新字符串，可以为空字符串（表示删除）")
    encoding: str = Field(default="utf-8", description="文件编码，默认 utf-8")


class FileEditTool(BaseTool):
    """精确字符串替换工具"""

    name: str = "file_edit"
    description: str = (
        "在文件中将 old_string 精确替换为 new_string。"
        "old_string 必须在文件中唯一出现一次，否则返回错误。"
        "适合局部修改文件；若需重写整个文件，使用 file_write 工具。"
        "提示：old_string 应包含足够的上下文（如周围几行）以保证唯一性。"
    )
    param_class = FileEditToolParam

    def execute(self, parameters: FileEditToolParam) -> str:
        path = os.path.abspath(parameters.path)

        if not os.path.exists(path):
            return f"错误: 文件不存在 — {path}"
        if not os.path.isfile(path):
            return f"错误: 路径不是文件 — {path}"
        if os.path.getsize(path) > _MAX_FILE_SIZE:
            return f"错误: 文件超过 2MB，请使用 file_write 整体替换"

        try:
            with open(path, "r", encoding=parameters.encoding, errors="replace") as f:
                content = f.read()
        except Exception as e:
            return f"错误: 读取失败 — {e}"

        old = parameters.old_string
        count = content.count(old)

        if count == 0:
            # 提供定位提示
            first_line = old.split("\n")[0][:60]
            return (
                f"错误: 未找到 old_string（文件 {os.path.basename(path)}）\n"
                f"  首行内容: {repr(first_line)}\n"
                f"  请检查空格、换行符或编码是否与文件实际内容一致"
            )
        if count > 1:
            return (
                f"错误: old_string 在文件中出现了 {count} 次，无法确定替换位置\n"
                f"  请在 old_string 中添加更多上下文使其唯一"
            )

        new_content = content.replace(old, parameters.new_string, 1)

        try:
            with open(path, "w", encoding=parameters.encoding, errors="replace") as f:
                f.write(new_content)
        except Exception as e:
            return f"错误: 写入失败 — {e}"

        old_lines = old.count("\n") + 1
        new_lines = parameters.new_string.count("\n") + 1
        delta = new_lines - old_lines
        sign = f"+{delta}" if delta >= 0 else str(delta)
        return f"已编辑: {path}  ({sign} 行)"
