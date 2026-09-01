"""
任务系统工具 —— 6 个工具让 Agent 管理持久化任务图。

工具名使用 task_ 前缀，与 task（子 Agent 委派）工具区分：
  task_create   创建任务，返回 ID
  task_update   添加依赖边（blockedBy）
  task_get      读取任务完整信息
  task_list     列出所有任务摘要
  task_claim    认领任务（pending → in_progress）
  task_complete 完成任务（in_progress → completed），输出新解锁项
"""

import json
from dataclasses import asdict

from pydantic import BaseModel, Field

from baseagent.tools.base import BaseTool
from codeagent.task_system import TaskStore


# ──────────────────────────────────────────────
# task_create
# ──────────────────────────────────────────────

class _CreateInput(BaseModel):
    subject: str = Field(description="任务标题（简短的行动描述）")
    description: str = Field(default="", description="任务详细描述，可选")


class TaskCreateTool(BaseTool):
    """
    创建一个新任务，返回生成的任务 ID。

    建图分两阶段：先用此工具创建所有任务节点（获得 ID），
    再用 task_update 添加依赖边。新任务始终从 pending 状态开始。
    """

    name = "task_create"
    description = (
        "创建新任务，返回唯一任务 ID。"
        "先批量创建所有任务节点，再用 task_update 添加依赖关系。"
    )
    param_class = _CreateInput

    def __init__(self, store: TaskStore):
        self._store = store

    def execute(self, parameters: _CreateInput) -> str:
        task = self._store.create(parameters.subject, parameters.description)
        return f"Created: {task.id} — {task.subject}"


# ──────────────────────────────────────────────
# task_update
# ──────────────────────────────────────────────

class _UpdateInput(BaseModel):
    task_id: str = Field(description="要更新的任务 ID（task_ 开头）")
    add_blocked_by: list[str] = Field(description="要添加的前置任务 ID 列表")


class TaskUpdateTool(BaseTool):
    """
    给任务添加前置依赖（blockedBy）。

    只能对 pending 且无 owner 的任务操作。
    重复添加已有依赖是安全的（幂等）。
    会检测自依赖和循环依赖，发现时拒绝操作。
    """

    name = "task_update"
    description = (
        "给任务添加前置依赖（blockedBy）。"
        "在所有 task_create 完成后调用，用返回的 ID 构建依赖图。"
    )
    param_class = _UpdateInput

    def __init__(self, store: TaskStore):
        self._store = store

    def execute(self, parameters: _UpdateInput) -> str:
        try:
            task = self._store.add_blocked_by(parameters.task_id, parameters.add_blocked_by)
            deps = ", ".join(task.blockedBy) or "none"
            return f"Updated {task.id} ({task.subject}): blockedBy=[{deps}]"
        except ValueError as e:
            return f"Error: {e}"


# ──────────────────────────────────────────────
# task_get
# ──────────────────────────────────────────────

class _GetInput(BaseModel):
    task_id: str = Field(description="任务 ID（task_ 开头）")


class TaskGetTool(BaseTool):
    """读取任务的完整信息，包括描述、依赖和状态。跨会话恢复时用于获取上下文。"""

    name = "task_get"
    description = "读取任务完整信息（含描述和依赖详情）。"
    param_class = _GetInput

    def __init__(self, store: TaskStore):
        self._store = store

    def execute(self, parameters: _GetInput) -> str:
        try:
            task = self._store.load(parameters.task_id)
            return json.dumps(asdict(task), ensure_ascii=False, indent=2)
        except ValueError as e:
            return f"Error: {e}"


# ──────────────────────────────────────────────
# task_list
# ──────────────────────────────────────────────

class _ListInput(BaseModel):
    pass


class TaskListTool(BaseTool):
    """列出所有任务及状态摘要，标注可立即开始的任务（✓ ready）。"""

    name = "task_list"
    description = "列出所有任务及状态摘要，标注哪些已解锁可开始。"
    param_class = _ListInput

    def __init__(self, store: TaskStore):
        self._store = store

    def execute(self, parameters: _ListInput) -> str:
        tasks = self._store.list_all()
        if not tasks:
            return "(no tasks)"
        lines = []
        for t in tasks:
            parts = [f"{t.id} [{t.status}]"]
            if t.owner:
                parts.append(f"owner={t.owner}")
            parts.append(f"— {t.subject}")
            if t.blockedBy:
                parts.append(f"[blocked by: {', '.join(t.blockedBy)}]")
            if t.status == "pending" and self._store.can_start(t):
                parts.append("✓ ready")
            lines.append(" ".join(parts))
        return "\n".join(lines)


# ──────────────────────────────────────────────
# task_claim
# ──────────────────────────────────────────────

class _ClaimInput(BaseModel):
    task_id: str = Field(description="要认领的任务 ID")
    owner: str = Field(default="agent", description="认领者名称，默认 agent")


class TaskClaimTool(BaseTool):
    """
    认领任务（pending → in_progress）。

    条件：任务必须是 pending；所有前置依赖必须已 completed。
    失败时返回原因（任务不是 pending，或依赖未完成）。
    """

    name = "task_claim"
    description = (
        "认领任务（pending → in_progress）。"
        "前置依赖未全部完成时拒绝认领。"
    )
    param_class = _ClaimInput

    def __init__(self, store: TaskStore):
        self._store = store

    def execute(self, parameters: _ClaimInput) -> str:
        try:
            task = self._store.load(parameters.task_id)
        except ValueError as e:
            return f"Error: {e}"

        if task.status != "pending":
            return f"Task {parameters.task_id} is {task.status}, cannot claim"

        incomplete = self._store.incomplete_deps(task)
        if incomplete:
            return f"Blocked by: {'; '.join(incomplete)}"

        task.owner = parameters.owner
        task.status = "in_progress"
        self._store.save(task)
        return f"Claimed {parameters.task_id} ({task.subject}) by {parameters.owner}"


# ──────────────────────────────────────────────
# task_complete
# ──────────────────────────────────────────────

class _CompleteInput(BaseModel):
    task_id: str = Field(description="要完成的任务 ID")
    owner: str = Field(default="agent", description="完成者名称，必须与认领者匹配")


class TaskCompleteTool(BaseTool):
    """
    完成任务（in_progress → completed）。

    完成后自动扫描所有任务，在结果中列出新解锁（刚变为可开始）的任务。
    owner 必须与认领时一致。
    """

    name = "task_complete"
    description = (
        "完成任务（in_progress → completed）。"
        "结果中列出因此解锁的新任务。"
    )
    param_class = _CompleteInput

    def __init__(self, store: TaskStore):
        self._store = store

    def execute(self, parameters: _CompleteInput) -> str:
        try:
            task = self._store.load(parameters.task_id)
        except ValueError as e:
            return f"Error: {e}"

        if task.status != "in_progress":
            return f"Task {parameters.task_id} is {task.status}, cannot complete"
        if task.owner != parameters.owner:
            return f"Task {parameters.task_id} is owned by {task.owner!r}, not {parameters.owner!r}"

        # 记录完成前哪些 pending 任务已经可以开始
        ready_before = {
            t.id for t in self._store.list_all()
            if t.status == "pending" and t.blockedBy and self._store.can_start(t)
        }

        task.status = "completed"
        self._store.save(task)

        # 找出因此次完成而新解锁的任务
        newly_unblocked = [
            f"{t.id} ({t.subject})"
            for t in self._store.list_all()
            if t.status == "pending"
            and t.blockedBy
            and t.id not in ready_before
            and self._store.can_start(t)
        ]

        msg = f"Completed {parameters.task_id} ({task.subject})"
        if newly_unblocked:
            msg += f"\nUnblocked: {', '.join(newly_unblocked)}"
        return msg
