"""
用户自定义 Shell 钩子系统

用户在项目目录下放置 .codeagent/settings.json，定义在 agent 生命周期
各阶段自动执行的 shell 命令。格式参考 .codeagent/settings.json.example。
"""

import json
import locale
import os
import subprocess
import sys

from baseagent.callbacks.base import BaseCallBack

if sys.platform == "win32":
    import ctypes
    _SYS_ENCODING = f"cp{ctypes.windll.kernel32.GetOEMCP()}"
else:
    _SYS_ENCODING = locale.getpreferredencoding(False) or "utf-8"

_SETTINGS_PATH = os.path.join(".codeagent", "settings.json")
_HOOK_TIMEOUT = 30

# 支持的事件名 → BaseCallBack 方法名（一一对应）
_SUPPORTED_EVENTS = {
    "on_tool_start",
    "on_tool_end",
    "on_agent_start",
    "on_agent_end",
}


class ShellHook(BaseCallBack):
    """
    从 .codeagent/settings.json 加载的 Shell 命令钩子。

    settings.json 格式：
    {
      "hooks": {
        "on_tool_end": [
          { "match_tool": "file_write", "command": "git add -A" },
          { "match_tool": "file_edit",  "command": "git add -A" }
        ],
        "on_agent_end": [
          { "command": "echo session done >> .codeagent/session.log" }
        ]
      }
    }

    rule 字段：
      command     必填，要执行的 shell 命令
                  支持模板变量：{tool}（工具名）、{workdir}
      match_tool  可选，只在指定工具触发时执行；省略则匹配所有工具
    """

    def __init__(self, hooks_config: dict, workdir: str):
        self._config = hooks_config   # {"on_tool_end": [...], ...}
        self._workdir = workdir

    # ── BaseCallBack 事件 ──────────────────────────────────────────────

    def on_tool_start(self, name: str, tool_call: dict):
        self._trigger("on_tool_start", tool_name=name)

    def on_tool_end(self, name: str, result: dict):
        self._trigger("on_tool_end", tool_name=name)

    def on_agent_start(self, agent_name: str, input_text: str):
        self._trigger("on_agent_start", tool_name=None)

    def on_agent_end(self, agent_name: str, final_text: str):
        self._trigger("on_agent_end", tool_name=None)

    # ── 内部执行 ──────────────────────────────────────────────────────

    def _trigger(self, event: str, tool_name: str | None):
        for rule in self._config.get(event, []):
            # match_tool 过滤：有指定且不匹配则跳过
            if "match_tool" in rule and rule["match_tool"] != tool_name:
                continue
            command = rule.get("command", "").strip()
            if not command:
                continue
            # 模板替换
            command = command.format(
                tool=tool_name or "",
                workdir=self._workdir,
            )
            self._exec(command)

    def _exec(self, command: str):
        try:
            subprocess.run(
                command,
                shell=True,
                cwd=self._workdir,
                timeout=_HOOK_TIMEOUT,
                encoding=_SYS_ENCODING,
                errors="replace",
            )
        except subprocess.TimeoutExpired:
            print(f"[hook] command timed out: {command[:60]}", flush=True)
        except Exception as e:
            print(f"[hook] error: {e}", flush=True)


# ── 加载函数 ─────────────────────────────────────────────────────────

def load_shell_hooks(workdir: str) -> ShellHook | None:
    """从 <workdir>/.codeagent/settings.json 读取 hooks 配置，返回 ShellHook 或 None。"""
    path = os.path.join(workdir, _SETTINGS_PATH)
    if not os.path.isfile(path):
        return None

    try:
        with open(path, encoding="utf-8") as f:
            settings = json.load(f)
    except Exception as e:
        print(f"[hooks] failed to read {path}: {e}", flush=True)
        return None

    hooks_config = settings.get("hooks", {})
    if not hooks_config:
        return None

    # 校验事件名，过滤掉不认识的，给出提示
    unknown = set(hooks_config) - _SUPPORTED_EVENTS
    if unknown:
        print(f"[hooks] unknown events ignored: {sorted(unknown)}", flush=True)
        hooks_config = {k: v for k, v in hooks_config.items() if k in _SUPPORTED_EVENTS}

    if not hooks_config:
        return None

    loaded = [e for e in hooks_config if hooks_config[e]]
    print(f"[hooks] loaded from {_SETTINGS_PATH}: {loaded}", flush=True)
    return ShellHook(hooks_config, workdir)
