from typing import Optional

from ..callbacks.base import BaseCallBack

from ..core.exceptions import AgentException, LLMException

from ..tools.executor import ToolExecutor
from ..tools.registry import ToolRegistry
from ..tools.base import BaseTool

from ..core.llm import BaseAgentLLM
from ..core.agent import Agent
from ..core.message import Message
from ..memory.base import BaseMemory


class ToolAgent(Agent):
    """带工具的简单agent"""
    def __init__(
        self, 
        name: str,
        llm: BaseAgentLLM,
        system_prompt: Optional[str] = None,
        tools: Optional[list[BaseTool]] = None,
        memory: Optional[BaseMemory] = None,
        description: Optional[str] = None,
        callbacks: Optional[list[BaseCallBack]] = None,
        max_iterations: int = 10
    ):
        super().__init__(name, llm, system_prompt, memory, description, callbacks)
        self.max_iterations = max_iterations
        self.tools = tools
        self.tool_registry = ToolRegistry()
        for tool in tools or []:
            self.tool_registry.register(tool)
        self.tool_executor = ToolExecutor(self.tool_registry)

    def run(self, session_id: str | None, input_text: str, **kwargs) -> str:
        """
        运行简单Agent-包含工具
        
        Args:
            session_id: 会话ID
            input_text: 用户输入
            **kwargs: 其他参数
            
        Returns:
            Agent响应
        """
        try:
            self._emit("on_agent_start", self.name, input_text)
            final_text = None
            # 1. 构建初始消息列表（system prompt + 历史 + 用户输入）
            messages = []
            if self.system_prompt:
                messages.append({"role": "system", "content": self.system_prompt})
            if session_id is not None:
                for msg in self.get_context(session_id):
                    messages.append(msg)
            messages.append({"role": "user", "content": input_text})
            # 2. 获取所有工具的 schema
            tools_schema = self.tool_registry.get_schemas()
            # 3. 循环开始：
            for step in range(self.max_iterations):
                self._emit("on_llm_start", messages)
                try:
                    # 3.1 调用 LLM，传入消息列表和工具 schema
                    response = self.llm.invoke(messages=messages, tools=tools_schema, **kwargs)
                except Exception as e:
                    self._emit("on_llm_error", e)
                    raise LLMException(f"LLM调用失败: {str(e)}")
                self._emit("on_llm_end", response)
                # 3.2 如果 LLM 返回 tool_calls → 执行每个工具，把结果加入消息列表，继续循环
                messages.append({
                    "role": "assistant",
                    "content": response.content,
                    "tool_calls": response.tool_calls
                })
                if response.is_tool_call():
                    for tool_call in response.tool_calls:
                        name = tool_call["function"]["name"]   # 工具名
                        self._emit("on_tool_start", name, tool_call)
                        tool_result = self.tool_executor.execute(tool_call=tool_call)
                        self._emit("on_tool_end", name, tool_result)
                        messages.append(tool_result)
                # 3.3 如果 LLM 没有 tool_calls → 取出文字回答，结束循环
                else: 
                    final_text = response.content
                    break
            if final_text is None:
                raise AgentException(f"超过最大迭代次数 {self.max_iterations}，未能得到最终答案")
            # 4. 保存对话历史
            if session_id is not None:
                self.add_message(session_id, Message(input_text, "user"))
                self.add_message(session_id, Message(final_text, "assistant"))
            # 5. 返回最终回答
            self._emit("on_agent_end", self.name, final_text)
            return final_text
        except Exception as e:
            self._emit("on_agent_error", self.name, e)
            raise e

    def stream_run(self, session_id: str | None, input_text: str, **kwargs) -> iter:
        """
        运行简单Agent-包含工具
        
        Args:
            session_id: 会话ID
            input_text: 用户输入
            **kwargs: 其他参数
            
        Returns:
            Agent响应
        """
        try:
            self._emit("on_agent_start", self.name, input_text)
            final_text = None
            # 1. 构建初始消息列表（system prompt + 历史 + 用户输入）
            messages = []
            if self.system_prompt:
                messages.append({"role": "system", "content": self.system_prompt})
            if session_id is not None:
                for msg in self.get_context(session_id):
                    messages.append(msg)
            messages.append({"role": "user", "content": input_text})
            # 2. 获取所有工具的 schema
            tools_schema = self.tool_registry.get_schemas()
            # 3. 循环开始：
            for step in range(self.max_iterations):
                self._emit("on_llm_start", messages)
                try:
                    # 3.1 调用 LLM，传入消息列表和工具 schema
                    response = self.llm.invoke(messages=messages, tools=tools_schema, **kwargs)
                except Exception as e:
                    self._emit("on_llm_error", e)
                    raise LLMException(f"LLM调用失败: {str(e)}")
                self._emit("on_llm_end", response)
                # 3.2 如果 LLM 返回 tool_calls → 执行每个工具，把结果加入消息列表，继续循环
                if response.is_tool_call():
                    messages.append({
                        "role": "assistant",
                        "content": response.content,
                        "tool_calls": response.tool_calls
                    })
                    for tool_call in response.tool_calls:
                        name = tool_call["function"]["name"]   # 工具名
                        self._emit("on_tool_start", name, tool_call)
                        tool_result = self.tool_executor.execute(tool_call=tool_call)
                        self._emit("on_tool_end", name, tool_result)
                        messages.append(tool_result)
                # 3.3 如果 LLM 没有 tool_calls → 取出文字回答，结束循环
                else: 
                    final_text = response.content
                    break
            if final_text is None:
                raise AgentException(f"超过最大迭代次数 {self.max_iterations}，未能得到最终答案")
            # 流式调用LLM
            final_text = ""
            for chunk in self.llm.think(messages, **kwargs):
                final_text += chunk
                yield chunk
            self._emit("on_agent_end", self.name, final_text)
            # 4. 保存对话历史
            if session_id is not None:
                self.add_message(session_id, Message(input_text, "user"))
                self.add_message(session_id, Message(final_text, "assistant"))
        except Exception as e:
            self._emit("on_agent_error", self.name, e)
            raise e