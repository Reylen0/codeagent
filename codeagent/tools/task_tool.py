"""
Task 工具 —— 把子任务委派给独立的子 Agent，实现 context 隔离。

子 Agent 拥有全新的 messages[]，干完活只把最终文字返回给父 Agent。
父 Agent 的 context 里不会出现子任务的中间工具调用结果。
"""

from pydantic import BaseModel, Field

from baseagent.tools.base import BaseTool


class TaskInput(BaseModel):
    prompt: str = Field(description="交给子 Agent 的任务描述，需完整说明目标和上下文")


class TaskTool(BaseTool):
    """
    在独立 context 中运行子任务，只返回最终结论。

    适用场景：
    - 需要大量读文件的调查性任务（避免污染父 context）
    - 相对独立的子任务，结果可以用一段文字表达
    - 父 Agent 想保持 context 整洁时

    注意：子 Agent 与父 Agent 共享同一工作目录，文件修改对双方可见。
    """

    name = "task"
    description = (
        "在独立对话上下文中运行一个子任务，只返回最终结论文字。"
        "适合调查性或独立性较强的子任务，防止大量中间步骤污染父 Agent 的上下文。"
        "子 Agent 拥有完整的代码工具集，与父 Agent 共享工作目录。"
    )
    param_class = TaskInput

    def __init__(self, config):
        # 延迟导入，避免循环引用（TaskTool ← code_agent ← TaskTool）
        self._config = config

    def execute(self, parameters: TaskInput) -> str:
        from codeagent.agent.code_agent import CodeAgent
        from codeagent.config import CodeAgentConfig

        # 子 Agent 用同一套配置，但标记为 subagent（不再注册 task 工具，防止递归）
        sub_config = CodeAgentConfig(
            workdir=self._config.workdir,
            model=self._config.model,
            api_key=self._config.api_key,
            base_url=self._config.base_url,
            temperature=self._config.temperature,
            max_tokens=self._config.max_tokens,
            max_iterations=self._config.max_iterations,
            allow_bash=self._config.allow_bash,
            is_subagent=True,           # 防止子 Agent 再注册 task 工具
        )

        print(f"\n[task] 子任务开始: {parameters.prompt[:80]}{'…' if len(parameters.prompt) > 80 else ''}", flush=True)

        sub_agent = CodeAgent(sub_config)
        # session_id=None：不加载历史、不保存历史，全新隔离的 context
        result = sub_agent.run(session_id=None, input_text=parameters.prompt)

        print(f"[task] 子任务完成", flush=True)
        return result
