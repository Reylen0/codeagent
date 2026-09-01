"""
Goal Loop —— 独立评估器决定是否继续工作。

工作流：
  1. /goal <条件> 设置目标，Agent 立即开始工作
  2. 每轮模型停止调用工具时，GoalController.evaluate() 做一次独立 LLM 判断
  3. ok=false → 把原因追加到 messages，continue 继续下一轮
  4. ok=true  → 真正退出循环
  5. impossible / 连续 block 超限 → 强制停止，交还用户控制
"""

import json
import time
from dataclasses import dataclass, field

_EVALUATOR_SYSTEM = """\
你是一个独立的目标完成度评估器，只负责判断目标是否已经达成。

规则：
1. 只根据对话历史中实际出现的内容（工具输出、命令结果、返回码）判断
2. 不要假设未明确报告的命令已成功执行
3. 如果关键验证步骤还没有运行，或结果尚未出现在对话里，判断为未完成
4. 如果目标在当前条件下根本无法完成，设置 impossible=true

以 JSON 格式回复（不要其他内容）：
{"ok": true/false, "reason": "简短原因（1-2句）", "impossible": true/false}"""

_MAX_EVAL_MESSAGES = 20    # 只取最近 N 条消息送给评估器
_MAX_MSG_CHARS = 3000      # 单条消息最多截取字符数
_MAX_CONSECUTIVE_BLOCKS = 5  # 连续未完成超过此数则强制停止


@dataclass
class GoalState:
    condition: str
    eval_count: int = 0
    started_at: float = field(default_factory=time.time)
    last_reason: str = ""
    consecutive_blocks: int = 0


@dataclass
class GoalDecision:
    action: str    # "allow" | "block" | "impossible" | "give_up"
    reason: str = ""


class GoalController:
    """
    管理单个会话的目标条件，并在每轮结束时调用评估器。

    - set(condition)   设置新目标
    - clear()          清除目标
    - is_active()      是否有活跃目标
    - evaluate(messages, llm) 独立 LLM 判断是否完成
    - status()         人类可读的状态摘要
    """

    def __init__(self, llm):
        self._llm = llm
        self._state: GoalState | None = None

    # ── 公开接口 ──────────────────────────────────────────────────────────────

    def set(self, condition: str):
        self._state = GoalState(condition=condition)

    def clear(self):
        self._state = None

    def is_active(self) -> bool:
        return self._state is not None

    def status(self) -> str:
        if not self._state:
            return "未设置目标"
        s = self._state
        elapsed = int(time.time() - s.started_at)
        lines = [
            f"目标条件: {s.condition}",
            f"评估次数: {s.eval_count}  已用时: {elapsed}s",
        ]
        if s.last_reason:
            lines.append(f"最近评估: {s.last_reason}")
        return "\n".join(lines)

    def evaluate(self, messages: list) -> GoalDecision:
        """在每轮结束时调用，判断是否继续。"""
        if not self._state:
            return GoalDecision(action="allow")

        # 连续 block 超限 → 强制停止，避免无限循环
        if self._state.consecutive_blocks >= _MAX_CONSECUTIVE_BLOCKS:
            return GoalDecision(
                action="give_up",
                reason=f"已连续 {_MAX_CONSECUTIVE_BLOCKS} 次评估为未完成，交还用户控制",
            )

        eval_messages = self._build_eval_messages(messages)

        try:
            response = self._llm.invoke(messages=eval_messages, tools=[])
            data = _parse_json(response.content or "")
        except Exception as exc:
            # 评估失败 → 停止自动续跑，不能假装完成
            return GoalDecision(action="give_up", reason=f"评估器调用失败: {exc}")

        self._state.eval_count += 1
        ok = data.get("ok", False)
        reason = data.get("reason", "")
        impossible = data.get("impossible", False)
        self._state.last_reason = reason

        if impossible:
            self._state.consecutive_blocks = 0
            return GoalDecision(action="impossible", reason=reason)
        if ok:
            self._state.consecutive_blocks = 0
            return GoalDecision(action="allow", reason=reason)

        self._state.consecutive_blocks += 1
        return GoalDecision(action="block", reason=reason)

    # ── 内部实现 ──────────────────────────────────────────────────────────────

    def _build_eval_messages(self, messages: list) -> list:
        """截取最近消息，构造评估器的输入。"""
        recent = [m for m in messages if m.get("role") in ("user", "assistant", "tool")]
        recent = recent[-_MAX_EVAL_MESSAGES:]

        truncated = []
        for m in recent:
            content = str(m.get("content") or "")
            if len(content) > _MAX_MSG_CHARS:
                half = _MAX_MSG_CHARS // 2
                content = content[:half] + "\n…（内容已截断）…\n" + content[-half:]
            truncated.append({"role": m["role"], "content": content})

        return [
            {"role": "system", "content": _EVALUATOR_SYSTEM},
            *truncated,
            {
                "role": "user",
                "content": (
                    f"目标条件：{self._state.condition}\n\n"
                    "根据以上对话历史，目标是否已经完成？"
                ),
            },
        ]


# ── 辅助函数 ──────────────────────────────────────────────────────────────────

def _parse_json(text: str) -> dict:
    """从 LLM 输出中提取 JSON，兼容 markdown 代码块包裹。"""
    text = text.strip()
    if "```" in text:
        parts = text.split("```")
        for part in parts[1::2]:
            part = part.lstrip("json").strip()
            try:
                return json.loads(part)
            except json.JSONDecodeError:
                continue
    return json.loads(text)
