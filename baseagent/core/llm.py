"""BaseAgent统一LLM接口 - 基于OpenAI原生API"""

import os
from typing import Optional, Iterator

from .llm_adapters import create_adapter
from .llm_response import LLMResponse

from .exceptions import BaseAgentException, LLMException

class BaseAgentLLM:
    """
    BaseAgent统一LLM客户端

    设计理念：
    - 统一配置：只需 LLM_MODEL_ID、LLM_API_KEY、LLM_BASE_URL、LLM_TIMEOUT

    支持的接口：
    - OpenAI及所有兼容接口（DeepSeek、Qwen、Kimi、智谱、Ollama等）
    - Anthropic Claude
    - Google Gemini
    """

    def __init__(
        self,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        timeout: Optional[int] = None,
        **kwargs
    ):
        """
        初始化LLM客户端

        参数优先级：传入参数 > 环境变量

        Args:
            model: 模型名称，默认从 LLM_MODEL_ID 读取
            api_key: API密钥，默认从 LLM_API_KEY 读取
            base_url: 服务地址，默认从 LLM_BASE_URL 读取
            temperature: 温度参数，默认0.7
            max_tokens: 最大token数
            timeout: 超时时间（秒），默认从 LLM_TIMEOUT 读取，默认60秒
        """
        # 加载配置
        self.model = model or os.getenv("LLM_MODEL_ID")
        self.api_key = api_key or os.getenv("LLM_API_KEY")
        self.base_url = base_url or os.getenv("LLM_BASE_URL")
        self.timeout = timeout or int(os.getenv("LLM_TIMEOUT", "60"))

        self.temperature = temperature
        self.max_tokens = max_tokens
        self.kwargs = kwargs


        # 验证必要参数
        if not self.model:
            raise BaseAgentException("必须提供模型名称（model参数或LLM_MODEL_ID环境变量）")
        if not self.api_key:
            raise BaseAgentException("必须提供API密钥（api_key参数或LLM_API_KEY环境变量）")
        if not self.base_url:
            raise BaseAgentException("必须提供服务地址（base_url参数或LLM_BASE_URL环境变量）")

        # 创建OpenAI客户端
        self._client = create_adapter(self.model, self.api_key, self.base_url, self.timeout)

    def think(self, messages: list[dict[str, str]], **kwargs) -> Iterator[str]:
        """
        调用大语言模型进行思考，并返回流式响应。
        这是主要的调用方法，默认使用流式响应以获得更好的用户体验。

        Args:
            messages: 消息列表
            temperature: 温度参数，如果未提供则使用初始化时的值

        Yields:
            str: 流式响应的文本片段
        """
        call_kwargs = {
            "temperature": kwargs.pop("temperature", self.temperature),
        }
        if self.max_tokens:
            call_kwargs["max_tokens"] = kwargs.pop("max_tokens", self.max_tokens)
        call_kwargs.update(kwargs)

        try:
            for chunk in self._client.invoke_stream(messages=messages, **call_kwargs):
                yield chunk
        except Exception as e:
            raise LLMException(f"LLM调用失败: {str(e)}")

    def invoke(self, messages: list[dict[str, str]], **kwargs) -> LLMResponse:
        """
        非流式调用LLM，返回完整响应。
        适用于不需要流式输出的场景。
        """
        call_kwargs = {
            "temperature": kwargs.pop("temperature", self.temperature),
        }
        if self.max_tokens:
            call_kwargs["max_tokens"] = kwargs.pop("max_tokens", self.max_tokens)
        call_kwargs.update(kwargs)

        try:
            return self._client.invoke(messages=messages, **call_kwargs)
        except Exception as e:
            raise LLMException(f"LLM调用失败: {str(e)}")
