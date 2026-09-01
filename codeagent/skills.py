"""
技能加载系统 —— 按需加载项目专属知识文档。

SkillLoader 扫描 .codeagent/skills/*/SKILL.md，
从 YAML frontmatter 提取 name/description 构建目录。
Agent 启动时只把目录注入 system prompt，
需要时通过 load_skill 工具加载完整内容。
"""

import os
import re
from pathlib import Path

_SKILLS_DIR = os.path.join(".codeagent", "skills")
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_KV_RE = re.compile(r"^(\w+)\s*:\s*(.+)$", re.MULTILINE)


class SkillLoader:
    """扫描技能目录，提供目录查询和内容加载。"""

    def __init__(self, workdir: str):
        self._workdir = os.path.abspath(workdir)
        self._skills: dict[str, dict] = {}   # name → {name, description, content}
        self.scan()

    # ── 公开接口 ──────────────────────────────

    def scan(self):
        """扫描 .codeagent/skills/*/SKILL.md，重建注册表。"""
        self._skills.clear()
        skills_root = Path(self._workdir) / _SKILLS_DIR

        if not skills_root.is_dir():
            return

        for manifest in sorted(skills_root.glob("*/SKILL.md")):
            if not manifest.is_file():
                continue
            # 安全检查：路径必须在 skills_root 内
            try:
                manifest.resolve().relative_to(skills_root.resolve())
            except ValueError:
                continue

            content = manifest.read_text(encoding="utf-8", errors="replace")
            name, description = self._parse_meta(content, manifest.parent.name)
            self._skills[name] = {
                "name": name,
                "description": description,
                "content": content,
            }

    def catalog(self) -> str:
        """返回技能目录字符串，用于注入 system prompt。"""
        if not self._skills:
            return ""
        lines = []
        for skill in self._skills.values():
            lines.append(f"- {skill['name']}: {skill['description']}")
        return "\n".join(lines)

    def load(self, name: str) -> str:
        """按名称返回完整 SKILL.md 内容，名称不存在时返回错误信息。"""
        skill = self._skills.get(name)
        if skill:
            return skill["content"]
        available = ", ".join(self._skills) or "none"
        return f"Error: Unknown skill '{name}'. Available: {available}"

    def is_empty(self) -> bool:
        return len(self._skills) == 0

    # ── 内部工具 ──────────────────────────────

    @staticmethod
    def _parse_meta(content: str, dir_name: str) -> tuple[str, str]:
        """从 YAML frontmatter 提取 name/description，缺失时使用默认值。"""
        name = dir_name
        description = ""

        m = _FRONTMATTER_RE.match(content)
        if m:
            for key, val in _KV_RE.findall(m.group(1)):
                if key == "name":
                    name = val.strip() or name
                elif key == "description":
                    description = val.strip()

        # description 缺失时取正文第一个非空行
        if not description:
            body = content[m.end():] if m else content
            for line in body.splitlines():
                line = line.strip().lstrip("# ").strip()
                if line:
                    description = line[:120]
                    break

        return name, description
