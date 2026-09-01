import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CodeAgentConfig:
    """CodeAgent 配置"""

    # 工作目录，所有文件操作的根路径
    workdir: str = "."

    # LLM 参数（优先级高于环境变量）
    model: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    temperature: float = 0.2       # 代码任务用低温度，减少随机性
    max_tokens: Optional[int] = None

    # Agent 行为
    max_iterations: int = 20       # 工具调用最大轮数
    memory_window: int = 200        # 保留的历史消息条数
    allow_bash: bool = False        # 是否启用 bash 工具
    enable_todo: bool = False       # 是否启用 todo_write（轻量任务清单）
    enable_task_system: bool = False  # 是否启用 task_* 系列（持久化任务图）
    enable_cron: bool = False        # 是否启用 cron_* 系列（定时任务调度）
    enable_mcp: bool = True         # 是否启用 MCP 工具（connect_mcp + 动态工具池）
    is_subagent: bool = False       # 子 Agent 标记，为 True 时不注册 task 工具（防递归）

    def __post_init__(self):
        self.workdir = os.path.abspath(self.workdir)
        if self.model is None:
            self.model = os.getenv("LLM_MODEL_ID")
        if self.api_key is None:
            self.api_key = os.getenv("LLM_API_KEY")
        if self.base_url is None:
            self.base_url = os.getenv("LLM_BASE_URL")
