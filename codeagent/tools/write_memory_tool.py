"""write_memory 工具 —— 让 Agent 主动写入一条持久化记忆。"""

from typing import Literal

from pydantic import BaseModel, Field

from baseagent.tools.base import BaseTool
from codeagent.memory_store import MemoryStore


class WriteMemoryInput(BaseModel):
    name: str = Field(
        description="记忆的唯一名称，用 kebab-case 英文短语，如 indent-preference"
    )
    mem_type: Literal["user", "feedback", "project", "reference"] = Field(
        description=(
            "记忆类型：\n"
            "  user       = 用户偏好（缩进风格、语言习惯等）\n"
            "  feedback   = 行为指导（不要做什么、怎么做更好）\n"
            "  project    = 项目事实（架构决策、模块用途等）\n"
            "  reference  = 外部资源指针（文档链接、工单 ID 等）"
        )
    )
    description: str = Field(description="一行摘要（80 字以内），用于记忆目录索引")
    body: str = Field(description="详细内容")


class WriteMemoryTool(BaseTool):
    """
    写入一条持久化记忆，未来会话中可被按需召回。

    适用场景：
    - 用户说"记住这个偏好"
    - 发现值得长期保留的项目事实或用户习惯
    - 记录对后续工作有持续指导意义的原则

    不适合记录只对当前任务有效的临时指令。
    """

    name = "write_memory"
    description = (
        "写入一条持久化记忆，在未来的会话中可被按需召回。"
        "适合记录用户偏好、项目事实、可复用的行为指导、外部资源指针。"
        "不适合记录只对当前任务有效的临时指令（如'本次不要创建文件'）。"
    )
    param_class = WriteMemoryInput

    def __init__(self, memory_store: MemoryStore):
        self._store = memory_store

    def execute(self, parameters: WriteMemoryInput) -> str:
        path = self._store.write(
            name=parameters.name,
            mem_type=parameters.mem_type,
            description=parameters.description,
            body=parameters.body,
        )
        rel = str(path.relative_to(self._store._workdir))
        print(f"[memory] written: {rel}", flush=True)
        return f"Memory saved: {parameters.name} ({parameters.mem_type}) → {rel}"
