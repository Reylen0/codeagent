from pydantic import BaseModel, Field

from baseagent.tools.base import BaseTool


class ConnectMCPParam(BaseModel):
    name: str = Field(
        description="MCP server 别名，用作工具前缀，如 'github'、'filesystem'"
    )
    command: list[str] = Field(
        description=(
            "启动 server 的命令列表，例如 "
            "['npx', '-y', '@modelcontextprotocol/server-github'] 或 "
            "['python', 'my_server.py']"
        )
    )


class ConnectMCPTool(BaseTool):
    name = "connect_mcp"
    description = (
        "连接到 MCP 服务器，动态发现并注册其提供的工具。"
        "连接成功后，新工具以 mcp__{name}__{tool} 格式出现在工具列表中，可直接调用。"
    )
    param_class = ConnectMCPParam

    def __init__(self, mcp_manager):
        self._mgr = mcp_manager

    def execute(self, parameters: ConnectMCPParam) -> str:
        try:
            return self._mgr.connect(parameters.name, parameters.command)
        except Exception as exc:
            return f"Error: {exc}"
