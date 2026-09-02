import json
import os
from typing import Optional

from dotenv import load_dotenv

from baseagent.agent.tool_agent import ToolAgent
from baseagent.core.exceptions import AgentException, LLMException
from baseagent.core.llm import BaseAgentLLM
from baseagent.core.message import Message
from baseagent.memory.buffer_memory import BufferMemory

from baseagent.tools.builtin.get_current_time_tool import GetCurrentTimeTool
from codeagent.background import BackgroundManager
from codeagent.compactor import ContextCompactor
from codeagent.config import CodeAgentConfig
from codeagent.cron import CronManager
from codeagent.goal import GoalController
from codeagent.hooks import load_shell_hooks
from codeagent.mcp_manager import MCPManager
from codeagent.memory_extract import extract_memories
from codeagent.memory_recall import MemoryRecall
from codeagent.memory_store import MemoryStore
from codeagent.permission import PermissionToolExecutor
from codeagent.prompts.system_prompts import build_system_prompt
from codeagent.skills import SkillLoader
from codeagent.tools import (
    GlobTool,
    GrepTool,
    FileReadTool,
    FileWriteTool,
    FileEditTool,
    LsTool,
    GitTool,
    BashTool,
    TodoWriteTool,
    TaskTool,
    LoadSkillTool,
    CompactTool,
    WriteMemoryTool,
    TaskCreateTool,
    TaskUpdateTool,
    TaskGetTool,
    TaskListTool,
    TaskClaimTool,
    TaskCompleteTool,
    CronCreateTool,
    CronDeleteTool,
    CronListTool,
)

load_dotenv()

_PROMPT_TOO_LONG_KEYWORDS = ("prompt_too_long", "too many tokens", "context_length_exceeded")
_MAX_REACTIVE_RETRIES = 1


class CodeAgent(ToolAgent):
    """
    代码辅助 Agent。

    在 ToolAgent 基础上：
    - 预装代码工具集（glob/grep/file_read/file_write/file_edit/ls/git/bash）
    - 规划工具（todo_write）、委派工具（task）、技能工具（load_skill）
    - 上下文压缩（compact 工具 + 自动四步管线）
    - 工具执行权限检查（PermissionToolExecutor）
    - 用户自定义 Shell 钩子（.codeagent/settings.json）
    """

    def __init__(self, config: Optional[CodeAgentConfig] = None):
        config = config or CodeAgentConfig()

        os.chdir(config.workdir)

        llm = BaseAgentLLM(
            model=config.model,
            api_key=config.api_key,
            base_url=config.base_url,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
        )

        skill_loader = SkillLoader(config.workdir)

        # 初始化记忆系统
        memory_store = MemoryStore(config.workdir)
        memory_recall = MemoryRecall(memory_store, llm)

        tools = [
            GetCurrentTimeTool(),
            GlobTool(),
            GrepTool(),
            FileReadTool(),
            FileWriteTool(),
            FileEditTool(),
            LsTool(),
            GitTool(),
        ]

        # 后台任务管理器（bash 工具持有引用）
        bg_manager = BackgroundManager()

        if config.allow_bash:
            tools.append(BashTool(background_manager=bg_manager))

        # todo_write：轻量任务清单（可选）
        todo_tool = None
        if config.enable_todo:
            todo_tool = TodoWriteTool()
            tools.append(todo_tool)

        tools.append(LoadSkillTool(skill_loader))
        tools.append(WriteMemoryTool(memory_store))

        # task_* 系列：持久化任务图（可选）
        if config.enable_task_system:
            from codeagent.task_system import TaskStore
            task_store = TaskStore(config.workdir)
            tools.append(TaskCreateTool(task_store))
            tools.append(TaskUpdateTool(task_store))
            tools.append(TaskGetTool(task_store))
            tools.append(TaskListTool(task_store))
            tools.append(TaskClaimTool(task_store))
            tools.append(TaskCompleteTool(task_store))

        # cron_* 系列：定时任务调度（可选）
        cron_manager = CronManager(config.workdir)
        if config.enable_cron:
            tools.append(CronCreateTool(cron_manager))
            tools.append(CronDeleteTool(cron_manager))
            tools.append(CronListTool(cron_manager))

        # MCP：运行时动态工具池（可选，server 列表从 .codeagent/mcp.json 加载）
        mcp_manager = MCPManager()
        if config.enable_mcp:
            mcp_config = os.path.join(config.workdir, ".codeagent", "mcp.json")
            if os.path.isfile(mcp_config):
                mcp_manager.load_config(mcp_config)

        if not config.is_subagent:
            tools.append(TaskTool(config))

        # 创建压缩器，compact 工具持有引用以设置 compact_requested 标志
        compactor = ContextCompactor(config.workdir, llm)
        tools.append(CompactTool(compactor))

        super().__init__(
            name="CodeAgent",
            llm=llm,
            system_prompt=build_system_prompt(config.workdir, skill_loader,
                                              enable_todo=config.enable_todo,
                                              enable_task_system=config.enable_task_system,
                                              enable_cron=config.enable_cron,
                                              enable_mcp=config.enable_mcp),
            tools=tools,
            memory=BufferMemory(window_size=config.memory_window),
            description="代码辅助 Agent，支持文件读写、搜索、Shell 执行和 Git 操作",
            max_iterations=config.max_iterations,
        )

        self.config = config
        self._compactor = compactor
        self._memory_store = memory_store
        self._memory_recall = memory_recall
        self._bg_manager = bg_manager
        self._cron_manager = cron_manager
        self._mcp_manager = mcp_manager
        self._goal = GoalController(llm)

        self.tool_executor = PermissionToolExecutor(
            self.tool_registry,
            config.workdir,
            todo_manager=todo_tool.manager if todo_tool else None,
        )

        hook = load_shell_hooks(config.workdir)
        if hook:
            self.callbacks.append(hook)

    # ── 辅助：执行 MCP 工具调用 ──────────────────────────────────────────

    def _execute_mcp_tool(self, tool_call: dict) -> dict:
        name = tool_call["function"]["name"]
        try:
            args = json.loads(tool_call["function"].get("arguments", "{}"))
        except json.JSONDecodeError:
            args = {}
        result_content = self._mcp_manager.call_tool(name, args)
        return {
            "role": "tool",
            "tool_call_id": tool_call.get("id", ""),
            "content": result_content,
        }

    # ── 辅助：保存完整轮次到 memory ───────────────────────────────────────

    def _save_turn(self, session_id: str, messages: list, final_text: str, turn_start: int):
        """
        把本轮新增的消息（user + 所有工具调用/结果）保存到 memory。
        turn_start 是本轮 user 消息在 messages 中的索引。
        final_text 单独追加，因为流式输出不写入 messages。
        """
        for msg in messages[turn_start:]:
            self.add_message(session_id, Message(
                content=msg.get("content") or "",
                role=msg.get("role"),
                tool_calls=msg.get("tool_calls"),
                tool_call_id=msg.get("tool_call_id"),
            ))
        self.add_message(session_id, Message(final_text, "assistant"))

    # ── 重写 run，加入压缩管线（子 Agent 使用此方法）────────────────────

    def run(self, session_id: str | None, input_text: str, **kwargs) -> str:
        try:
            self._emit("on_agent_start", self.name, input_text)
            final_text = None

            # 召回相关记忆，临时追加到 system prompt（仅对本轮生效，不修改 self.system_prompt）
            turn_system = self.system_prompt
            if not self.config.is_subagent and not self._memory_store.is_empty():
                relevant = self._memory_recall.select_relevant(input_text)
                if relevant:
                    turn_system += self._memory_recall.build_recall_section(relevant)

            messages = []
            if turn_system:
                messages.append({"role": "system", "content": turn_system})
            if session_id is not None:
                for msg in self.get_context(session_id):
                    messages.append(msg)
            messages.append({"role": "user", "content": input_text})
            turn_start = len(messages) - 1  # 本轮 user 消息的索引

            tools_schema = self.tool_registry.get_schemas()
            reactive_retries = 0

            for step in range(self.max_iterations):
                # 每轮重建工具池：base tools + 已连接的 MCP 工具
                current_tools = tools_schema + self._mcp_manager.get_extra_schemas()
                messages = self._compactor.prepare(messages, input_text)

                # 收集已完成的后台任务通知，注入为 user 消息
                for notification in self._bg_manager.collect():
                    messages.append({"role": "user", "content": notification})
                # 收集已触发的定时任务通知，注入为 user 消息
                for notification in self._cron_manager.collect():
                    messages.append({"role": "user", "content": notification})

                self._emit("on_llm_start", messages)
                try:
                    response = self.llm.invoke(messages=messages, tools=current_tools, **kwargs)
                    reactive_retries = 0
                except Exception as e:
                    msg = str(e).lower()
                    if any(k in msg for k in _PROMPT_TOO_LONG_KEYWORDS) and reactive_retries < _MAX_REACTIVE_RETRIES:
                        messages = self._compactor.reactive_compact(messages, input_text)
                        reactive_retries += 1
                        try:
                            response = self.llm.invoke(messages=messages, tools=current_tools, **kwargs)
                        except Exception as retry_err:
                            raise LLMException(f"LLM 调用失败（压缩后重试）: {retry_err}")
                    else:
                        self._emit("on_llm_error", e)
                        raise LLMException(f"LLM 调用失败: {e}")
                self._emit("on_llm_end", response)

                messages.append({
                    "role": "assistant",
                    "content": response.content,
                    "tool_calls": response.tool_calls,
                })
                if response.is_tool_call():
                    self.tool_executor.begin_batch()
                    for tool_call in response.tool_calls:
                        name = tool_call["function"]["name"]
                        self._emit("on_tool_start", name, tool_call)
                        if name.startswith("mcp__"):
                            tool_result = self._execute_mcp_tool(tool_call)
                        else:
                            tool_result = self.tool_executor.execute(tool_call=tool_call)
                        self._emit("on_tool_end", name, tool_result)
                        messages.append(tool_result)

                    if self._compactor.compact_requested:
                        self._compactor.compact_requested = False
                        messages = self._compactor.compact_history(messages, input_text)
                else:
                    final_text = response.content
                    # Goal Loop：独立评估器判断是否真的完成
                    if self._goal.is_active():
                        decision = self._goal.evaluate(messages)
                        if decision.action == "block":
                            messages.append({"role": "user", "content": f"[目标未达成] {decision.reason}"})
                            continue
                    break

            if final_text is None:
                raise AgentException(f"超过最大迭代次数 {self.max_iterations}，未能得到最终答案")

            self._emit("on_agent_end", self.name, final_text)

            if session_id is not None:
                self._save_turn(session_id, messages, final_text, turn_start)
                if not self.config.is_subagent:
                    extract_messages = list(messages)
                    extract_messages.append({"role": "assistant", "content": final_text})
                    extract_memories(extract_messages, self.llm, self._memory_store)

            return final_text

        except Exception as e:
            self._emit("on_agent_error", self.name, e)
            raise e

    # ── 重写 stream_run，加入压缩管线 ────────────────────────────────────

    def stream_run(self, session_id: str | None, input_text: str, **kwargs):
        """
        工具循环 + 上下文压缩版本的 stream_run。

        每次 llm.invoke() 前运行四步压缩管线；
        捕获 prompt_too_long 错误后 reactive_compact 重试一次；
        本轮工具批次结束后若 compact_requested=True 则执行摘要压缩。
        最终回答始终通过 llm.think() 流式输出。
        """
        try:
            self._emit("on_agent_start", self.name, input_text)
            final_text = None

            # 召回相关记忆，临时追加到 system prompt（仅对本轮生效，不修改 self.system_prompt）
            turn_system = self.system_prompt
            if not self.config.is_subagent and not self._memory_store.is_empty():
                relevant = self._memory_recall.select_relevant(input_text)
                if relevant:
                    turn_system += self._memory_recall.build_recall_section(relevant)

            messages = []
            if turn_system:
                messages.append({"role": "system", "content": turn_system})
            if session_id is not None:
                for msg in self.get_context(session_id):
                    messages.append(msg)
            messages.append({"role": "user", "content": input_text})
            turn_start = len(messages) - 1  # 本轮 user 消息的索引

            tools_schema = self.tool_registry.get_schemas()
            reactive_retries = 0

            for step in range(self.max_iterations):
                # 每轮重建工具池：base tools + 已连接的 MCP 工具
                current_tools = tools_schema + self._mcp_manager.get_extra_schemas()
                # ── 压缩管线：每次调 LLM 前运行 ──────────────────────────
                messages = self._compactor.prepare(messages, input_text)

                # 收集已完成的后台任务通知，注入为 user 消息
                for notification in self._bg_manager.collect():
                    messages.append({"role": "user", "content": notification})
                # 收集已触发的定时任务通知，注入为 user 消息
                for notification in self._cron_manager.collect():
                    messages.append({"role": "user", "content": notification})

                self._emit("on_llm_start", messages)
                try:
                    response = self.llm.invoke(messages=messages, tools=current_tools, **kwargs)
                    reactive_retries = 0
                except Exception as e:
                    msg = str(e).lower()
                    if any(k in msg for k in _PROMPT_TOO_LONG_KEYWORDS) and reactive_retries < _MAX_REACTIVE_RETRIES:
                        print("[compact] prompt_too_long, reactive compact...", flush=True)
                        messages = self._compactor.reactive_compact(messages, input_text)
                        reactive_retries += 1
                        try:
                            response = self.llm.invoke(messages=messages, tools=current_tools, **kwargs)
                        except Exception as retry_err:
                            raise LLMException(f"LLM 调用失败（压缩后重试）: {retry_err}")
                    else:
                        self._emit("on_llm_error", e)
                        raise LLMException(f"LLM 调用失败: {e}")
                self._emit("on_llm_end", response)

                if response.is_tool_call():
                    messages.append({
                        "role": "assistant",
                        "content": response.content,
                        "tool_calls": response.tool_calls,
                    })
                    self.tool_executor.begin_batch()
                    for tool_call in response.tool_calls:
                        name = tool_call["function"]["name"]
                        self._emit("on_tool_start", name, tool_call)
                        if name.startswith("mcp__"):
                            tool_result = self._execute_mcp_tool(tool_call)
                        else:
                            tool_result = self.tool_executor.execute(tool_call=tool_call)
                        self._emit("on_tool_end", name, tool_result)
                        messages.append(tool_result)

                    # compact 工具触发：本批次全部执行完毕后再压缩
                    if self._compactor.compact_requested:
                        self._compactor.compact_requested = False
                        messages = self._compactor.compact_history(messages, input_text)
                else:
                    final_text = response.content
                    # Goal Loop：独立评估器判断是否真的完成
                    if self._goal.is_active():
                        decision = self._goal.evaluate(messages)
                        if decision.action == "block":
                            messages.append({"role": "user", "content": f"[目标未达成] {decision.reason}"})
                            continue
                    break

            if final_text is None:
                raise AgentException(f"超过最大迭代次数 {self.max_iterations}，未能得到最终答案")

            # 流式输出最终回答
            final_text = ""
            for chunk in self.llm.think(messages, **kwargs):
                final_text += chunk
                yield chunk

            self._emit("on_agent_end", self.name, final_text)

            if session_id is not None:
                self._save_turn(session_id, messages, final_text, turn_start)
                if not self.config.is_subagent:
                    extract_messages = list(messages)
                    extract_messages.append({"role": "assistant", "content": final_text})
                    extract_memories(extract_messages, self.llm, self._memory_store)

        except Exception as e:
            self._emit("on_agent_error", self.name, e)
            raise e
