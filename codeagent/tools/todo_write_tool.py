"""
任务计划工具 —— 帮助 Agent 在多步骤任务中维护执行状态。

TodoManager 持有内存中的任务列表，负责校验和渲染。
TodoWriteTool 是对外暴露的 BaseTool 实现，每次调用全量替换列表。
"""

import json
from typing import Literal

from pydantic import BaseModel, Field

from baseagent.tools.base import BaseTool

_STATUS_SYMBOL = {
    "pending":     "[ ]",
    "in_progress": "[>]",
    "completed":   "[✓]",
}

_MAX_ITEMS = 20


# ──────────────────────────────────────────────
# Pydantic 参数模型（供 run() 校验用）
# ──────────────────────────────────────────────

class _TodoItem(BaseModel):
    content: str = Field(description="任务内容")
    status: Literal["pending", "in_progress", "completed"] = Field(
        default="pending", description="任务状态"
    )


class TodoWriteInput(BaseModel):
    todos: list[_TodoItem] = Field(description="完整任务列表（全量替换）")


# ──────────────────────────────────────────────
# TodoManager
# ──────────────────────────────────────────────

class TodoManager:
    """内存中的任务列表，负责校验规则和渲染输出。"""

    def __init__(self):
        self.items: list[dict] = []

    # ── 公开接口 ──────────────────────────────

    def update(self, todos) -> str:
        """
        替换当前任务列表，返回渲染字符串。
        接受 list[_TodoItem]（来自 Pydantic 解析）或 list[dict] 或 JSON 字符串。
        """
        # 1. 统一解析为 list[dict]
        normalized, err = self._normalize(todos)
        if err:
            return f"Error: {err}"

        # 2. 校验
        err = self._validate(normalized)
        if err:
            return f"Error: {err}"

        self.items = normalized
        return self.render()

    def render(self) -> str:
        if not self.items:
            return "(no todos)"
        lines = ["TODO:"]
        for item in self.items:
            sym = _STATUS_SYMBOL.get(item["status"], "[ ]")
            lines.append(f"  {sym} {item['content']}")
        return "\n".join(lines)

    def is_empty(self) -> bool:
        return len(self.items) == 0

    # ── 内部工具 ──────────────────────────────

    @staticmethod
    def _normalize(todos) -> tuple[list[dict], str | None]:
        """把各种输入形式统一成 list[dict]，返回 (result, error)。"""
        if isinstance(todos, str):
            try:
                todos = json.loads(todos)
            except json.JSONDecodeError:
                return [], "todos must be a list or a JSON string"

        if not isinstance(todos, list):
            return [], "todos must be a list"

        if len(todos) > _MAX_ITEMS:
            return [], f"too many todos (max {_MAX_ITEMS})"

        result = []
        for item in todos:
            if isinstance(item, dict):
                content = item.get("content", "").strip()
                status  = item.get("status", "pending")
            else:
                # Pydantic _TodoItem
                content = item.content.strip()
                status  = item.status
            result.append({"content": content, "status": status})

        return result, None

    @staticmethod
    def _validate(items: list[dict]) -> str | None:
        """校验规则，返回错误信息或 None。"""
        in_progress = 0
        for item in items:
            if not item["content"]:
                return "todo content must not be empty"
            if item["status"] not in _STATUS_SYMBOL:
                return f"invalid status '{item['status']}'"
            if item["status"] == "in_progress":
                in_progress += 1

        if in_progress > 1:
            return "only one todo can be in_progress at a time"

        return None


# ──────────────────────────────────────────────
# TodoWriteTool
# ──────────────────────────────────────────────

class TodoWriteTool(BaseTool):
    """
    任务计划工具，帮助 Agent 追踪多步骤任务的执行进度。

    使用规则：
    - 开始复杂任务前，先调用此工具列出所有步骤（全部 pending）
    - 开始每个步骤前，标记为 in_progress
    - 完成后标记为 completed
    - 同一时间只能有一个 in_progress 项
    - 每次调用是全量替换，传入完整列表
    """

    name = "todo_write"
    description = (
        "创建或更新任务列表，跟踪多步骤任务的执行进度。"
        "开始复杂任务时先列出所有步骤（全部 pending）；"
        "执行每步前标记为 in_progress；完成后标记为 completed。"
        "同一时间只能有一个 in_progress 项。每次调用全量替换列表。"
    )
    param_class = TodoWriteInput

    def __init__(self):
        self.manager = TodoManager()

    def execute(self, parameters: TodoWriteInput) -> str:
        result = self.manager.update(parameters.todos)
        print(result, flush=True)
        return result
