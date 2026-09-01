from typing import Optional


class LLMResponse:
    """
    LLM响应对象，封装了LLM的输出结果。
    """
    def __init__(self, content: Optional[str] = None, tool_calls: Optional[list[dict]] = None):
        self.content = content
        self.tool_calls = tool_calls or []

    def to_dict(self) -> dict:
        """
        将LLM响应对象转换为字典格式，便于序列化和传输。
        """
        return {
            "content": self.content,
            "tool_calls": self.tool_calls
        }

    def __str__(self) -> str:
        """
        返回LLM响应对象的字符串表示，便于调试和日志记录。
        """
        return f"LLM_Response(content={self.content}, tool_calls={self.tool_calls})"

    def is_tool_call(self) -> bool:
        """
        判断LLM响应中是否包含工具调用。
        """
        return len(self.tool_calls) > 0