"""compact 工具 —— 让 Agent 主动触发上下文压缩。"""

from pydantic import BaseModel

from baseagent.tools.base import BaseTool


class _EmptyInput(BaseModel):
    pass


class CompactTool(BaseTool):
    """
    主动压缩对话历史，释放 context 空间。

    适合在完成一个大阶段后调用：先把阶段成果写入文件，
    再调 compact 清场，为下一阶段保留足够的 context 空间。
    压缩后历史会被 LLM 摘要替代，细节不可恢复，
    因此应在当前阶段的重要文件操作全部完成后再调用。
    """

    name = "compact"
    description = (
        "摘要并压缩对话历史，释放 context 空间。"
        "在完成一个大阶段后调用，为后续步骤腾出空间。"
        "注意：调用后历史细节将被摘要替代，不可恢复，"
        "请确保当前阶段的文件操作已全部完成再调用。"
    )
    param_class = _EmptyInput

    def __init__(self, compactor):
        self._compactor = compactor

    def execute(self, parameters: _EmptyInput) -> str:
        # 不立即压缩，设置标志位由 stream_run 在本轮工具批次结束后处理
        # 这样同一批次里的其他工具（如 file_write）会先执行完毕
        self._compactor.compact_requested = True
        return "Compaction requested after this tool batch."
