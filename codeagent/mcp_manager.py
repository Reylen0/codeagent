"""
MCP 工具管理器 —— 运行时连接外部 MCP 服务器，动态发现并调用其工具。

工作流：
  1. load_config() 读取 .codeagent/mcp.json，批量启动 server 子进程
  2. 发现工具列表，以 mcp__{server}__{tool} 格式注册
  3. get_extra_schemas() 返回 OpenAI 格式 schema（每轮 LLM 调用前拼入 tools_schema）
  4. call_tool(prefixed_name, args) 路由到对应 server 执行

配置文件格式（标准 MCP 格式，与 Claude Desktop / ModelScope 兼容）：
  {
    "mcpServers": {
      "github": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github"],
        "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "..."}
      }
    }
  }
"""

import asyncio
import json
import os
import re
import threading

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.client.sse import sse_client
    _HAS_MCP = True
except ImportError:
    _HAS_MCP = False

_NAME_UNSAFE = re.compile(r"[^a-zA-Z0-9_]")
_MAX_TOOL_NAME_LEN = 64


def _normalize(s: str) -> str:
    """把 server/tool 名中的非字母数字下划线字符替换为下划线。"""
    return _NAME_UNSAFE.sub("_", s)


class _MCPConnection:
    """
    单个 MCP server 的持久连接。

    在独立 daemon 线程里运行 asyncio 事件循环，保持 stdio 子进程和会话不关闭。
    外部通过 call_tool() 同步调用；内部用 run_coroutine_threadsafe 跨线程提交协程。
    """

    def __init__(self, name: str, command: str, args: list[str],
                 env: dict[str, str] | None = None,
                 url: str | None = None):
        self.name = name
        self.tools: list[dict] = []

        self._loop = asyncio.new_event_loop()
        self._session = None
        self._shutdown_event: asyncio.Event | None = None
        self._ready = threading.Event()
        self._error: Exception | None = None

        t = threading.Thread(
            target=self._run, args=(command, args, env, url), daemon=True
        )
        t.start()

        if not self._ready.wait(timeout=30):
            raise TimeoutError(f"MCP server '{name}' 连接超时（30s）")
        if self._error:
            raise self._error

    def _run(self, command: str, args: list[str], env: dict | None, url: str | None):
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._main(command, args, env, url))

    async def _main(self, command: str, args: list[str], env: dict | None, url: str | None):
        self._shutdown_event = asyncio.Event()
        try:
            if url:
                # SSE 传输：server 独立运行，通过 HTTP 连接
                cm = sse_client(url)
            else:
                # stdio 传输：启动子进程，通过 stdin/stdout 通信
                # 合并当前环境变量，避免子进程丢失 PATH 等基础变量
                merged_env = {**os.environ, **(env or {})}
                cm = stdio_client(StdioServerParameters(command=command, args=args, env=merged_env))
            async with cm as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.list_tools()
                    self.tools = []
                    for t in result.tools:
                        d = t.model_dump()
                        schema = (
                            d.get("inputSchema")
                            or d.get("input_schema")
                            or {"type": "object", "properties": {}}
                        )
                        self.tools.append({
                            "name": t.name,
                            "description": t.description or "",
                            "inputSchema": schema,
                        })
                    self._session = session
                    self._ready.set()
                    await self._shutdown_event.wait()
        except Exception as exc:
            # 展开 asyncio TaskGroup / ExceptionGroup，取第一个真正的子异常
            actual = exc
            while hasattr(actual, "exceptions") and actual.exceptions:
                actual = actual.exceptions[0]
            self._error = actual
            self._ready.set()

    def call_tool(self, tool_name: str, args: dict) -> str:
        if self._session is None or not self._loop.is_running():
            return "Error: MCP 连接已关闭"
        future = asyncio.run_coroutine_threadsafe(
            self._session.call_tool(tool_name, args),
            self._loop,
        )
        try:
            result = future.result(timeout=30)
            texts = []
            for item in (result.content or []):
                texts.append(item.text if hasattr(item, "text") else str(item))
            return "\n".join(texts) if texts else "(no output)"
        except TimeoutError:
            return "Error: 工具调用超时（30s）"
        except Exception as exc:
            return f"MCP error: {exc}"

    def close(self):
        if self._shutdown_event and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._shutdown_event.set)


class MCPManager:
    """
    管理多个 MCP server 连接。

    - load_config()       从 .codeagent/mcp.json 批量连接（标准 MCP 格式）
    - get_extra_schemas() 返回 OpenAI function calling 格式 schema
    - call_tool()         路由 mcp__{server}__{tool} 调用
    """

    def __init__(self):
        self._connections: dict[str, _MCPConnection] = {}
        self.load_log: list[str] = []   # load_config 的完整结果，供调试查看

    # ── 公开接口 ──────────────────────────────────────────────────────────────

    def connect(self, name: str, command: str = "", args: list[str] = [],
                env: dict[str, str] | None = None,
                url: str | None = None) -> str:
        """启动并连接单个 MCP server，返回发现的工具列表摘要。"""
        if not _HAS_MCP:
            raise RuntimeError("mcp 未安装，请先运行: pip install mcp")
        if name in self._connections:
            return f"MCP server '{name}' 已连接。"
        conn = _MCPConnection(name, command, args, env, url)
        self._connections[name] = conn
        safe = _normalize(name)
        tool_names = [f"mcp__{safe}__{_normalize(t['name'])}" for t in conn.tools]
        return (
            f"已连接到 '{name}'，发现 {len(conn.tools)} 个工具：\n"
            + "\n".join(f"  {n}" for n in tool_names)
        )

    def get_extra_schemas(self) -> list[dict]:
        """返回所有已连接 server 的工具 schema（OpenAI function calling 格式）。"""
        schemas = []
        seen: set[str] = set()
        for srv_name, conn in self._connections.items():
            safe_srv = _normalize(srv_name)
            for tool in conn.tools:
                safe_tool = _normalize(tool["name"])
                prefixed = f"mcp__{safe_srv}__{safe_tool}"
                if len(prefixed) > _MAX_TOOL_NAME_LEN or prefixed in seen:
                    continue
                seen.add(prefixed)
                schemas.append({
                    "type": "function",
                    "function": {
                        "name": prefixed,
                        "description": tool.get("description", ""),
                        "parameters": tool.get("inputSchema") or {
                            "type": "object",
                            "properties": {},
                        },
                    },
                })
        return schemas

    def call_tool(self, prefixed_name: str, args: dict) -> str:
        """执行 mcp__{server}__{tool} 格式的工具调用。"""
        parts = prefixed_name.split("__", 2)
        if len(parts) != 3 or parts[0] != "mcp":
            return f"Error: 非法 MCP 工具名 '{prefixed_name}'"

        safe_srv, safe_tool = parts[1], parts[2]
        conn = None
        original_tool = None

        for srv_name, c in self._connections.items():
            if _normalize(srv_name) == safe_srv:
                conn = c
                for t in c.tools:
                    if _normalize(t["name"]) == safe_tool:
                        original_tool = t["name"]
                        break
                break

        if conn is None:
            return f"Error: MCP server '{safe_srv}' 未连接"
        if original_tool is None:
            return f"Error: 工具 '{safe_tool}' 在 server '{safe_srv}' 中不存在"

        return conn.call_tool(original_tool, args)

    def list_servers(self) -> list[dict]:
        return [
            {"name": n, "tools": [t["name"] for t in c.tools]}
            for n, c in self._connections.items()
        ]

    def disconnect(self, name: str) -> bool:
        """断开并移除指定 server，返回是否成功。"""
        conn = self._connections.pop(name, None)
        if conn is None:
            return False
        conn.close()
        return True

    def load_config(self, config_path: str) -> list[str]:
        """
        读取标准 MCP 配置文件并批量连接 server。

        标准格式（与 Claude Desktop / ModelScope 兼容）：
        {
          "mcpServers": {
            "github": {
              "type": "stdio",
              "command": "npx",
              "args": ["-y", "@modelcontextprotocol/server-github"],
              "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "..."}
            },
            "remote": {
              "type": "sse",
              "url": "http://localhost:3000/sse"
            }
          }
        }

        type 默认为 stdio。
        """
        try:
            with open(config_path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            return [f"Error reading {config_path}: {exc}"]

        servers = data.get("mcpServers", {})
        results = []
        for name, cfg in servers.items():
            if cfg.get("disabled", False):
                results.append(f"[{name}] 已禁用，跳过")
                continue
            transport = cfg.get("type", "stdio")
            try:
                if transport == "sse":
                    url = cfg.get("url")
                    if not url:
                        results.append(f"[{name}] 跳过：sse 类型缺少 url 字段")
                        continue
                    msg = self.connect(name, url=url)
                else:
                    command = cfg.get("command")
                    if not command:
                        results.append(f"[{name}] 跳过：缺少 command 字段")
                        continue
                    args = cfg.get("args", [])
                    env = cfg.get("env") or None
                    msg = self.connect(name, command=command, args=args, env=env)
                results.append(f"[{name}] {msg}")
            except Exception as exc:
                results.append(f"[{name}] 连接失败: {exc}")
        self.load_log = results
        return results
