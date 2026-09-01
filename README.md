# CodeAgent

一个类 Claude Code 的本地代码辅助 Agent，基于 `baseagent` 框架构建。在终端中与代码库对话，完成读写、搜索、调试、提交等日常开发任务。

---

## 特性

| 模块 | 说明 |
|------|------|
| **代码工具** | 文件读写、精确编辑、glob/grep 搜索、目录浏览、Git 操作 |
| **Shell 执行** | bash 工具，支持后台异步运行（`run_in_background`） |
| **权限管控** | 三级门控：硬拒绝危险命令 → 规则匹配 → 用户确认 |
| **Shell 钩子** | `.codeagent/settings.json` 配置 pre/post 工具钩子 |
| **上下文压缩** | 四步自动压缩管线，防止超出 context 限制 |
| **跨会话记忆** | 自动提取并持久化用户偏好和项目事实到 `.codeagent/memory/` |
| **技能系统** | `.codeagent/skills/` 存放专项操作规范，按需加载 |
| **任务规划** | `todo_write`（轻量清单）+ `task_*` 系列（持久化任务图，支持依赖关系） |
| **后台任务** | bash 命令可在后台线程执行，结果以通知形式注入下一轮 |
| **定时任务** | cron 调度器，支持标准 5 字段表达式，配置持久化 |
| **MCP 外部工具** | 通过 `.codeagent/mcp.json` 接入任意 MCP 服务器（stdio/SSE），兼容 Claude Desktop 配置格式 |
| **目标循环** | `/goal` 命令设置完成条件，独立评估器自动判断是否继续工作 |
| **子 Agent** | 将重度子任务委派给隔离的子 Agent，保持主 context 整洁 |

---

## 快速开始

### 安装

**方式一：直接从 GitHub 安装（推荐）**

```bash
pip install git+https://github.com/Reylen0/codeagent.git
```

**方式二：克隆后本地安装（便于修改）**

```bash
git clone https://github.com/Reylen0/codeagent.git
cd codeagent
pip install -e .
```

### 配置

**方式一：在工作目录创建 `.env` 文件**

```env
LLM_BASE_URL=https://your-openai-compatible-endpoint/v1
LLM_API_KEY=sk-...
LLM_MODEL_ID=claude-sonnet-4-6
```

**方式二：设置系统环境变量（全局生效）**

```bash
# Linux / macOS（写入 ~/.bashrc 或 ~/.zshrc）
export LLM_BASE_URL=https://your-openai-compatible-endpoint/v1
export LLM_API_KEY=sk-...
export LLM_MODEL_ID=claude-sonnet-4-6

# Windows PowerShell
$env:LLM_API_KEY = "sk-..."
$env:LLM_BASE_URL = "https://..."
$env:LLM_MODEL_ID = "claude-sonnet-4-6"
```

> 两种方式可以共存：`.env` 文件优先级更高，适合按项目覆盖配置。

### 运行

```bash
codeagent                          # 在当前目录启动
codeagent --workdir /your/repo     # 指定工作目录
codeagent --no-bash                # 禁用 Shell 执行
codeagent --max-iter 100           # 设置最大迭代轮数
```

---

## CLI 命令

| 命令 | 说明 |
|------|------|
| `/help` | 显示帮助 |
| `/clear` | 清空对话历史 |
| `/tools` | 列出已加载的工具 |
| `/mcp` | 查看已连接的 MCP 服务器和工具列表 |
| `/mcp disable <name>` | 断开指定 MCP 服务器 |
| `/goal <条件>` | 设置目标并立即开始工作 |
| `/goal` | 查看当前目标状态 |
| `/goal clear` | 清除目标 |
| `/exit` | 退出 |

行末加 `\` 可换行输入多行内容。

---

## 项目配置

在工作目录下创建 `.codeagent/` 目录进行配置：

### Shell 钩子 `.codeagent/settings.json`

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "bash",
        "hooks": [{ "type": "command", "command": "echo '[bash] $TOOL_INPUT'" }]
      }
    ]
  }
}
```

### MCP 服务器 `.codeagent/mcp.json`

兼容 Claude Desktop / ModelScope 配置格式：

```json
{
  "mcpServers": {
    "tavily": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "tavily-mcp"],
      "env": { "TAVILY_API_KEY": "your-key" }
    },
    "remote": {
      "type": "sse",
      "url": "http://localhost:3000/sse"
    }
  }
}
```

### 技能文档 `.codeagent/skills/<name>/SKILL.md`

在 `SKILL.md` 中写入专项操作规范（如 git-commit 规范、代码风格指南），Agent 按需通过 `load_skill` 加载。

### 项目说明 `AGENT.md` 或 `CLAUDE.md`

放在工作目录根路径，Agent 启动时自动读取并追加到系统提示词。

---

## 使用示例

```
> 这个项目的入口文件在哪里？
> 帮我在 utils.py 里加一个 parse_date 函数
> 运行测试，看哪些失败了
> 在后台安装依赖，同时帮我阅读 README
> git commit 当前改动，message 写"add parse_date utility"
```

### 目标循环

```
> /goal 让 pytest tests/ 全部通过，不修改测试文件

Agent: [自动修复代码，直到所有测试通过]

> /goal
目标条件: 让 pytest tests/ 全部通过，不修改测试文件
评估次数: 3  已用时: 52s
最近评估: pytest 输出显示 12 passed，目标已达成
```

---

## 项目结构

```
codeagent/
├── agent/
│   └── code_agent.py        # 主 Agent 类，集成所有模块
├── tools/
│   ├── glob_tool.py         # 文件名模式搜索
│   ├── grep_tool.py         # 文件内容搜索
│   ├── file_read_tool.py    # 带行号的文件读取
│   ├── file_write_tool.py   # 文件写入/创建
│   ├── file_edit_tool.py    # 精确字符串替换
│   ├── ls_tool.py           # 目录列表
│   ├── git_tool.py          # Git 操作集合
│   ├── bash_tool.py         # Shell 命令（支持后台执行）
│   ├── todo_write_tool.py   # 轻量任务清单
│   ├── task_tools.py        # 持久化任务图（6 个工具）
│   ├── cron_tools.py        # 定时任务（3 个工具）
│   ├── load_skill_tool.py   # 按需加载技能文档
│   ├── compact_tool.py      # 手动触发上下文压缩
│   └── write_memory_tool.py # 显式写入跨会话记忆
├── background.py            # 后台任务管理器
├── compactor.py             # 四步上下文压缩管线
├── config.py                # Agent 配置
├── cron.py                  # 定时任务调度器
├── goal.py                  # 目标循环评估器
├── hooks.py                 # Shell 钩子加载
├── mcp_manager.py           # MCP 服务器连接管理
├── memory_extract.py        # 自动提取跨会话记忆
├── memory_recall.py         # 记忆召回与注入
├── memory_store.py          # 记忆持久化存储
├── permission.py            # 工具执行权限管控
├── prompts/
│   └── system_prompts.py    # 系统提示词动态构建
├── skills.py                # 技能文档加载器
└── task_system.py           # 持久化任务图数据层

baseagent/                   # 通用 Agent 框架（子模块）
chat.py                      # CLI 入口
```

---

## 配置项

通过 `CodeAgentConfig` 在代码中调整行为：

```python
from codeagent.agent.code_agent import CodeAgent
from codeagent.config import CodeAgentConfig

agent = CodeAgent(CodeAgentConfig(
    workdir=".",               # 工作目录
    model="claude-sonnet-4-6",
    allow_bash=True,           # 启用 Shell 工具
    enable_todo=False,         # 启用轻量任务清单
    enable_task_system=False,  # 启用持久化任务图
    enable_cron=False,         # 启用定时任务
    enable_mcp=True,           # 启用 MCP 外部工具
    max_iterations=50,         # 最大工具调用轮数
    memory_window=200,         # 历史消息窗口大小
))
```

---

## 依赖

| 包 | 用途 |
|----|------|
| `openai>=1.0` | LLM API 客户端（OpenAI 兼容接口） |
| `pydantic>=2.0` | 参数校验与 schema 生成 |
| `python-dotenv>=1.0` | 环境变量加载 |
| `numpy>=1.26` | RAG 向量计算 |
| `croniter>=2.0` | Cron 表达式解析 |
| `mcp>=1.0` | MCP 协议客户端 |
| `tzdata>=2024.1` | Windows 时区数据库 |

---

## License

MIT
