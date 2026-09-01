from abc import ABC, abstractmethod

from .llm_response import LLMResponse


class BaseLLMAdapter(ABC):
    """LLM适配器基类"""

    def __init__(self, model: str, api_key: str, base_url: str, timeout: int = 60):
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.timeout = timeout
        self._client = None

    @abstractmethod
    def _create_client(self):
        """创建客户端"""
        pass

    @abstractmethod
    def invoke(self, messages: list[dict[str, str]], **kwargs) -> LLMResponse:
        """调用大语言模型 非流式响应"""
        pass

    @abstractmethod
    def invoke_stream(self, messages: list[dict[str, str]], **kwargs) -> iter:
        """调用大语言模型 流式响应"""
        pass

class OpenAIAdapter(BaseLLMAdapter):
    """OpenAI兼容接口适配器（默认）

    支持：
    - OpenAI官方API
    - 所有OpenAI兼容接口（DeepSeek、Qwen、Kimi、智谱等）
    - Thinking Models（o1、deepseek-reasoner等）
    """
    def _create_client(self):
        """创建OpenAI客户端"""
        from openai import OpenAI

        return OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.timeout
        )

    def invoke(self, messages: list[dict[str, str]], tools: list[dict] = None, **kwargs) -> LLMResponse:
        """调用大语言模型 非流式响应"""
        if not self._client:
            self._client = self._create_client()

        response = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools,
            **kwargs
        )
        message = response.choices[0].message
        tool_calls = []
        if message.tool_calls:
            for tc in message.tool_calls:
                tool_calls.append({
                    "id": tc.id,
                    "type": tc.type,
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments
                    }
                })
        return LLMResponse(content=message.content, tool_calls=tool_calls)

    def invoke_stream(self, messages: list[dict[str, str]], **kwargs) -> iter:
        """调用大语言模型 流式响应"""
        if not self._client:
            self._client = self._create_client()

        response = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            stream=True,
            **kwargs
        )

        for chunk in response:
            if not chunk.choices:
                continue
            content = chunk.choices[0].delta.content or ""
            if content:
                yield content

def create_adapter(model: str, api_key: str, base_url: str, timeout: int) -> BaseLLMAdapter:
    """
    根据base_url自动选择适配器

    检测逻辑：
    - anthropic.com -> AnthropicAdapter
    - googleapis.com 或 generativelanguage -> GeminiAdapter
    - 其他 -> OpenAIAdapter（默认）
    """
    # 暂时只支持openai兼容接口，后续可扩展其他适配器
    return OpenAIAdapter(model, api_key, base_url, timeout)
    