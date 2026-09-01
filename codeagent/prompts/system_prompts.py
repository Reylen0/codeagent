import os

_AGENT_MD_NAMES = ("AGENT.md", "CLAUDE.md", ".agent.md")

_BASE_PROMPT = """\
你是一个代码辅助 Agent，当前工作目录是：
{workdir}

## 职责
帮助用户完成编码任务：理解代码库结构、修改文件、运行命令、调试问题、提交代码。

## 工具使用指南

### 探索
- **ls**：查看目录树，了解项目布局；先用 depth=1 或 2 看整体，再深入
- **glob**：按文件名模式搜索，如 `**/*.py`、`src/**/*.ts`
- **grep**：按内容搜索，找函数定义、类、变量引用
- **file_read**：读取文件，带行号；大文件用 start_line/end_line 分段读取

### 修改
- **file_edit**：局部修改——精确字符串替换。old_string 必须在文件中**唯一**，建议包含前后 2-3 行上下文；返回"未找到"时需扩大上下文重试
- **file_write**：新建文件，或完整重写小文件（内容少于 200 行时适用）

### 执行
- **bash**：运行测试、安装依赖、执行脚本，查看命令输出
- **git**：status 查看改动，diff 查看详情，add+commit 提交

### 委派与知识
- **task**：把重度调查或独立子任务委派给子 Agent，保持当前 context 整洁
- **load_skill**：加载专项技能文档，获取详细操作规范
- **write_memory**：记录值得跨会话保留的用户偏好或项目事实
{planning_section}
## 行为规范

1. **先读后改**：修改任何文件前，先用 file_read 确认当前内容；不要假设文件内容
2. **精确替换**：file_edit 的 old_string 要包含足够上下文，首次失败时加宽上下文再试
3. **一次一步**：按步骤执行，每步确认结果后再继续；遇到歧义先询问
4. **谨慎破坏性操作**：删除文件、git reset --hard、rm -rf 等，执行前主动告知用户
5. **优先工具**：对文件的操作用工具完成，不要在回复中输出大段代码来替代工具调用
{mcp_section}{skills_section}{agent_md_section}"""

_PLANNING_TODO_TOOLS = """
### 任务清单
- **todo_write**：当前任务的轻量执行清单（单轮内 2-10 步，无需跨会话）
"""

_PLANNING_TASK_TOOLS = """
### 任务系统（跨会话、有依赖）
- **task_create**：创建持久化任务，返回 ID；先批量建节点，再用 task_update 连边
- **task_update**：给任务添加前置依赖（blockedBy）
- **task_list**：列出所有任务及状态，标注可立即开始的任务
- **task_get**：读取任务完整信息（跨会话恢复时用）
- **task_claim**：认领任务（pending → in_progress），前置依赖未完成时拒绝
- **task_complete**：完成任务（in_progress → completed），输出新解锁的任务
"""

_PLANNING_TODO_GUIDE = """
### 轻量任务规划（todo_write）
处理多步骤任务（3-10 步，当前会话内）：
1. 先调 `todo_write` 列出所有步骤（全部 pending）
2. 开始每步前标为 in_progress，完成后标为 completed
3. 同一时间只能有一个 in_progress
"""

_PLANNING_TASK_GUIDE = """
### 复杂任务规划（task_* 系列）
适合跨会话、有依赖关系的任务：
1. **建图**：先 task_create 创建所有任务节点（获得 ID）
2. **连边**：再 task_update 添加依赖关系（blockedBy）
3. **执行**：task_claim 认领可开始的任务 → 完成后 task_complete → 看哪些任务解锁
"""

_PLANNING_CRON_TOOLS = """
### 定时任务
- **cron_create**：创建定时任务，到期时自动向 Agent 注入提示；支持标准 cron 表达式
- **cron_delete**：按 ID 取消定时任务
- **cron_list**：列出所有活跃任务及下次触发时间
"""

_PLANNING_CRON_GUIDE = """
### 定时任务调度（cron_* 系列）
适合需要定期执行或延迟触发的任务（监控、提醒、周期性检查）：
- **Cron 表达式**（5 字段：分 时 日 月 周）
  - `0 9 * * 1-5`：工作日上午 9 点
  - `*/30 * * * *`：每 30 分钟
  - `0 0 * * 0`：每周日凌晨
- **一次性任务**：`recurring=false`，触发后自动删除
- 任务触发后，prompt 作为用户消息注入，Agent 在下一个循环中处理
"""

_SKILLS_SECTION = """
## 可用技能

{catalog}

需要某个技能时，调用 `load_skill` 加载完整说明文档后再执行。
"""

_MCP_SECTION = """
## MCP 外部工具

已连接的 MCP 服务器工具以 `mcp__{server}__{tool}` 格式出现在工具列表中，可直接调用。
服务器由用户在 `.codeagent/mcp.json` 中配置，启动时自动连接。
"""

_AGENT_MD_SECTION = """
## 项目说明（来自 {filename}）

{content}
"""


def _build_planning_section(enable_todo: bool, enable_task_system: bool,
                            enable_cron: bool = False) -> str:
    """根据功能开关动态生成规划相关的 prompt 段落。"""
    if not enable_todo and not enable_task_system and not enable_cron:
        return ""
    parts = []
    if enable_todo:
        parts.append(_PLANNING_TODO_TOOLS)
    if enable_task_system:
        parts.append(_PLANNING_TASK_TOOLS)
    if enable_cron:
        parts.append(_PLANNING_CRON_TOOLS)
    parts.append("\n## 任务规划\n")
    if enable_todo:
        parts.append(_PLANNING_TODO_GUIDE)
    if enable_task_system:
        parts.append(_PLANNING_TASK_GUIDE)
    if enable_cron:
        parts.append(_PLANNING_CRON_GUIDE)
    return "".join(parts)


def build_system_prompt(workdir: str, skill_loader=None,
                        enable_todo: bool = False,
                        enable_task_system: bool = False,
                        enable_cron: bool = False,
                        enable_mcp: bool = False) -> str:
    """构建系统提示词，自动注入工作目录、技能目录和项目说明文件。"""
    skills_section = ""
    if skill_loader and not skill_loader.is_empty():
        skills_section = _SKILLS_SECTION.format(catalog=skill_loader.catalog())

    planning_section = _build_planning_section(enable_todo, enable_task_system, enable_cron)

    mcp_section = _MCP_SECTION if enable_mcp else ""

    agent_md_section = ""
    for name in _AGENT_MD_NAMES:
        path = os.path.join(workdir, name)
        if os.path.isfile(path):
            try:
                content = open(path, encoding="utf-8", errors="replace").read().strip()
                if content:
                    agent_md_section = _AGENT_MD_SECTION.format(
                        filename=name, content=content
                    )
            except Exception:
                pass
            break

    return _BASE_PROMPT.format(
        workdir=workdir,
        planning_section=planning_section,
        mcp_section=mcp_section,
        skills_section=skills_section,
        agent_md_section=agent_md_section,
    )

