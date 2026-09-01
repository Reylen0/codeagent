"""
任务系统 —— 文件持久化的任务图，支持依赖关系和跨会话恢复。

每个任务是 .codeagent/tasks/{id}.json 文件。
状态机：pending → (claim) → in_progress → (complete) → completed
"""

import json
import os
import secrets
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional

_TASKS_DIR = os.path.join(".codeagent", "tasks")


@dataclass
class Task:
    id: str
    subject: str
    description: str = ""
    status: str = "pending"          # pending | in_progress | completed
    owner: Optional[str] = None
    blockedBy: list[str] = field(default_factory=list)


class TaskStore:
    """任务文件的读写、校验和依赖管理。"""

    def __init__(self, workdir: str):
        self._workdir = os.path.abspath(workdir)
        self._dir = Path(self._workdir) / _TASKS_DIR

    # ── 公开接口 ──────────────────────────────────────────────────────────

    def create(self, subject: str, description: str = "") -> Task:
        """创建新任务，分配唯一 ID，写入磁盘。"""
        subject = subject.strip()
        if not subject:
            raise ValueError("subject must not be empty")

        # 生成不冲突的 ID
        for _ in range(10):
            task_id = f"task_{secrets.token_hex(4)}"
            if not (self._dir / f"{task_id}.json").exists():
                break

        self._dir.mkdir(parents=True, exist_ok=True)
        task = Task(id=task_id, subject=subject, description=description)
        self.save(task)
        return task

    def save(self, task: Task):
        """将任务写入磁盘（覆盖已有文件）。"""
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._dir / f"{task.id}.json"
        path.write_text(
            json.dumps(asdict(task), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load(self, task_id: str) -> Task:
        """按 ID 加载任务，ID 格式非法或文件不存在时抛异常。"""
        _validate_id(task_id)
        path = self._dir / f"{task_id}.json"
        if not path.is_file():
            raise ValueError(f"Task {task_id} not found")
        return Task(**json.loads(path.read_text(encoding="utf-8")))

    def list_all(self) -> list[Task]:
        """返回所有任务，按文件名排序。"""
        if not self._dir.is_dir():
            return []
        tasks = []
        for path in sorted(self._dir.glob("task_*.json")):
            try:
                tasks.append(Task(**json.loads(path.read_text(encoding="utf-8"))))
            except Exception:
                pass
        return tasks

    def exists(self, task_id: str) -> bool:
        try:
            _validate_id(task_id)
        except ValueError:
            return False
        return (self._dir / f"{task_id}.json").is_file()

    def can_start(self, task: Task) -> bool:
        """所有 blockedBy 依赖都已 completed 时返回 True。"""
        for dep_id in task.blockedBy:
            if not self.exists(dep_id):
                return False
            if self.load(dep_id).status != "completed":
                return False
        return True

    def incomplete_deps(self, task: Task) -> list[str]:
        """返回未完成的依赖描述列表。"""
        result = []
        for dep_id in task.blockedBy:
            if not self.exists(dep_id):
                result.append(f"{dep_id} (not found)")
            else:
                dep = self.load(dep_id)
                if dep.status != "completed":
                    result.append(f"{dep_id} ({dep.subject}: {dep.status})")
        return result

    def add_blocked_by(self, task_id: str, dep_ids: list[str]) -> Task:
        """
        给 task_id 添加 blockedBy 依赖边。
        校验：目标必须是 pending 且无 owner；依赖必须存在；不能自依赖；不能成环。
        """
        task = self.load(task_id)
        if task.status != "pending":
            raise ValueError(f"Task {task_id} is {task.status}, only pending tasks can have dependencies added")
        if task.owner is not None:
            raise ValueError(f"Task {task_id} is already owned by {task.owner}")

        for dep_id in dep_ids:
            if dep_id == task_id:
                raise ValueError(f"Task cannot depend on itself: {dep_id}")
            if not self.exists(dep_id):
                raise ValueError(f"Dependency {dep_id} not found")

        # 去重合并
        new_blocked_by = list(task.blockedBy)
        for dep_id in dep_ids:
            if dep_id not in new_blocked_by:
                new_blocked_by.append(dep_id)

        # 构建临时图做环检测
        graph = {t.id: list(t.blockedBy) for t in self.list_all()}
        graph[task_id] = new_blocked_by
        if _has_cycle(task_id, graph):
            raise ValueError("Adding these dependencies would create a cycle")

        task.blockedBy = new_blocked_by
        self.save(task)
        return task


# ── 工具函数 ─────────────────────────────────────────────────────────────

def _validate_id(task_id: str):
    if not isinstance(task_id, str) or not task_id.startswith("task_"):
        raise ValueError(f"Invalid task ID: {task_id!r} (must start with 'task_')")


def _has_cycle(start_id: str, graph: dict[str, list[str]]) -> bool:
    """DFS 检测从 start_id 出发是否存在环（沿 blockedBy 方向）。"""
    visited: set[str] = set()
    stack: set[str] = set()

    def dfs(node: str) -> bool:
        if node in stack:
            return True
        if node in visited or node not in graph:
            return False
        visited.add(node)
        stack.add(node)
        for dep in graph[node]:
            if dfs(dep):
                return True
        stack.discard(node)
        return False

    return dfs(start_id)
