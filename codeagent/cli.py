"""CodeAgent CLI 入口"""

import argparse
import json
import re
import sys

from dotenv import load_dotenv

load_dotenv()

from baseagent.callbacks.base import BaseCallBack
from codeagent.agent.code_agent import CodeAgent
from codeagent.config import CodeAgentConfig

# ──────────────────────────────────────────────
# 颜色常量（Windows CMD / ANSI 终端通用）
# ──────────────────────────────────────────────
_RESET  = "\033[0m"
_DIM    = "\033[2m"
_CYAN   = "\033[36m"
_GREEN  = "\033[32m"
_YELLOW = "\033[33m"
_RED    = "\033[31m"
_BOLD   = "\033[1m"


def _c(text: str, *codes: str) -> str:
    """包裹 ANSI 颜色，Windows 下若不支持则原样返回。"""
    if sys.platform == "win32":
        try:
            import ctypes
            # 开启 ANSI 支持（Windows 10+）
            ctypes.windll.kernel32.SetConsoleMode(
                ctypes.windll.kernel32.GetStdHandle(-11), 7
            )
        except Exception:
            return text
    return "".join(codes) + text + _RESET


# ──────────────────────────────────────────────
# 回调：在 CLI 中显示工具调用信息
# ──────────────────────────────────────────────
class _CLICallback(BaseCallBack):

    def on_llm_start(self, messages):
        print(_c("  … ", _DIM), end="\r", flush=True)

    def on_llm_end(self, response):
        print("     ", end="\r", flush=True)  # 清除 "  … " 提示

    def on_tool_start(self, name: str, tool_call: dict):
        args = tool_call.get("function", {}).get("arguments", {})
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                args = {}

        hint = ""
        if isinstance(args, dict):
            key = next(iter(args), None)
            if key:
                val = str(args[key]).replace("\n", "\\n")[:60]
                hint = f"  {key}={repr(val)}"

        print(_c(f"\n  ▶ {name}{hint}", _CYAN, _DIM), flush=True)

    def on_tool_end(self, name: str, result: dict):
        content = str(result.get("content", "")).strip()
        first_line = content.split("\n")[0][:100]
        suffix = "…" if "\n" in content else ""
        print(_c(f"  ✓ {first_line}{suffix}", _DIM), flush=True)

    def on_tool_error(self, name: str, error: Exception):
        print(_c(f"  ✗ {name}: {error}", _RED), flush=True)


# ──────────────────────────────────────────────
# 多行输入：行尾 \ 续行
# ──────────────────────────────────────────────
def _read_input(prompt: str) -> str:
    lines = []
    first = True
    while True:
        try:
            line = input(prompt if first else "... ")
        except EOFError:
            raise
        first = False
        if line.endswith("\\"):
            lines.append(line[:-1])
        else:
            lines.append(line)
            break
    return "\n".join(lines)


# ──────────────────────────────────────────────
# 特殊命令处理
# ──────────────────────────────────────────────
_HELP_TEXT = f"""
{_BOLD}可用命令:{_RESET}
  /clear           清空对话历史
  /tools           列出已加载的工具
  /mcp             列出已连接的 MCP 服务器及其工具
  /mcp disable <name>  断开指定 MCP 服务器
  /goal <条件>     设置目标并立即开始工作（如：/goal 让所有测试通过）
  /goal            查看当前目标状态
  /goal clear      清除目标
  /help            显示此帮助
  /exit            退出（也可输入 quit 或 exit）

  行末加 \\ 可换行输入多行内容，按 Enter 提交
  Ctrl+C    中断当前输出（不退出程序）
"""


def _cmd_tools(agent: CodeAgent):
    print()
    for name, tool in agent.tool_registry._tools.items():
        desc = tool.description.split("。")[0][:60]
        print(f"  {_c(name, _CYAN):<25s} {desc}")
    print()


def _cmd_mcp(agent: CodeAgent, sub: str = ""):
    mgr = agent._mcp_manager
    sub = sub.strip()

    # /mcp disable <name>
    if sub.startswith("disable "):
        name = sub[len("disable "):].strip()
        if not name:
            print(_c("  用法: /mcp disable <server>\n", _YELLOW))
            return
        ok = mgr.disconnect(name)
        if ok:
            print(_c(f"  已断开 MCP 服务器 '{name}'\n", _DIM))
        else:
            print(_c(f"  未找到 MCP 服务器 '{name}'\n", _RED))
        return

    # /mcp — 列出所有服务器
    servers = mgr.list_servers()
    print()
    if not servers:
        print(_c("  未连接任何 MCP 服务器", _DIM))
        if mgr.load_log:
            print(_c("  启动日志：", _YELLOW))
            for line in mgr.load_log:
                color = _RED if "失败" in line or "Error" in line else _DIM
                print(_c(f"    {line}", color))
        else:
            print(_c("  配置文件: .codeagent/mcp.json", _DIM))
        print()
        return
    for srv in servers:
        tool_count = len(srv["tools"])
        srv_name = srv["name"]
        print(f"  {_c(srv_name, _CYAN + _BOLD)}  {_c(f'{tool_count} 个工具', _DIM)}")
        for t in srv["tools"]:
            safe_srv = re.sub(r"[^a-zA-Z0-9_]", "_", srv_name)
            safe_t = re.sub(r"[^a-zA-Z0-9_]", "_", t)
            print(f"    {_c(f'mcp__{safe_srv}__{safe_t}', _DIM)}")
        print()
    print(_c("  用法: /mcp disable <server>  断开指定服务器\n", _DIM))


# ──────────────────────────────────────────────
# Goal 命令
# ──────────────────────────────────────────────
_GOAL_CLEAR_ALIASES = {"clear", "stop", "off", "reset", "none", "cancel"}


def _cmd_goal(agent: CodeAgent, sub: str) -> str | None:
    """
    返回 None  → 命令已处理，不需要触发 Agent 轮次
    返回 str   → 目标条件，需要立即触发一轮 Agent
    """
    sub = sub.strip()

    if sub.lower() in _GOAL_CLEAR_ALIASES:
        agent._goal.clear()
        print(_c("  目标已清除\n", _DIM))
        return None

    if not sub:
        print()
        if agent._goal.is_active():
            for line in agent._goal.status().splitlines():
                print(f"  {_c(line, _CYAN)}")
        else:
            print(_c("  未设置目标", _DIM))
            print(_c("  用法: /goal <完成条件>", _DIM))
        print()
        return None

    # 设置新目标，立即开始工作
    agent._goal.set(sub)
    print(_c(f"  目标已设置，开始工作…\n", _GREEN))
    return sub   # 触发一轮 Agent，以目标条件为输入


# ──────────────────────────────────────────────
# 启动 Banner
# ──────────────────────────────────────────────
def _print_banner(agent: CodeAgent, cfg: CodeAgentConfig):
    tools = list(agent.tool_registry._tools.keys())
    print(_c("╔══════════════════════════════════════╗", _BOLD))
    print(_c("║           CodeAgent  CLI             ║", _BOLD))
    print(_c("╚══════════════════════════════════════╝", _BOLD))
    print(f"  工作目录  {_c(cfg.workdir, _YELLOW)}")
    print(f"  模型      {_c(cfg.model or '?', _CYAN)}")
    print(f"  工具      {_c(', '.join(tools), _DIM)}")
    print(f"  输入 {_c('/help', _CYAN)} 查看命令\n")


# ──────────────────────────────────────────────
# main
# ──────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="CodeAgent CLI — 代码辅助 Agent")
    parser.add_argument("--workdir", "-w", default=".", metavar="DIR",
                        help="工作目录，默认当前目录")
    parser.add_argument("--no-bash", action="store_true",
                        help="禁用 bash 工具")
    parser.add_argument("--max-iter", type=int, default=50, metavar="N",
                        help="最大工具调用轮数，默认 50")
    args = parser.parse_args()

    cfg = CodeAgentConfig(
        workdir=args.workdir,
        allow_bash=not args.no_bash,
        max_iterations=args.max_iter,
    )

    agent = CodeAgent(cfg)
    agent.callbacks.append(_CLICallback())

    _print_banner(agent, cfg)

    SESSION_ID = "cli"

    while True:
        # ── 读取输入 ──
        try:
            user_input = _read_input(_c("你: ", _BOLD)).strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break

        if not user_input:
            continue

        # ── 特殊命令 ──
        cmd = user_input.lower()

        if cmd in ("quit", "exit", "/exit", "/quit"):
            print("再见！")
            break

        if cmd in ("clear", "/clear"):
            agent.clear_history(SESSION_ID)
            print(_c("对话历史已清空\n", _DIM))
            continue

        if cmd in ("/tools",):
            _cmd_tools(agent)
            continue

        if cmd == "/mcp" or cmd.startswith("/mcp "):
            _cmd_mcp(agent, user_input[4:].strip())
            continue

        if cmd == "/goal" or cmd.startswith("/goal "):
            sub = user_input[5:].strip() if len(user_input) > 5 else ""
            trigger = _cmd_goal(agent, sub)
            if trigger is None:
                continue
            user_input = trigger   # 用目标条件作为本轮输入，继续执行 Agent

        if cmd in ("help", "/help"):
            print(_HELP_TEXT)
            continue

        # ── 调用 Agent ──
        try:
            has_output = False
            for chunk in agent.stream_run(SESSION_ID, user_input):
                if not has_output:
                    # 工具调用输出后补一个空行再打 "Agent: "
                    print(f"\n{_c('Agent: ', _GREEN + _BOLD)}", end="", flush=True)
                    has_output = True
                print(chunk, end="", flush=True)
            print("\n")
        except KeyboardInterrupt:
            print(_c("\n[已中断]\n", _DIM))
        except Exception as e:
            print(_c(f"\n错误: {e}\n", _RED))


if __name__ == "__main__":
    main()
