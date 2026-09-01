"""load_skill 工具 —— 按名称加载完整技能文档。"""

from pydantic import BaseModel, Field

from baseagent.tools.base import BaseTool
from codeagent.skills import SkillLoader


class LoadSkillInput(BaseModel):
    name: str = Field(description="技能名称，必须是目录中列出的名称之一")


class LoadSkillTool(BaseTool):
    """
    加载指定技能的完整说明文档。

    技能目录在 system prompt 中列出，调用此工具获取完整内容。
    name 参数必须与目录中的技能名称完全匹配。
    """

    name = "load_skill"
    description = (
        "加载指定技能的完整说明文档（SKILL.md）。"
        "system prompt 中已列出可用技能的名称和简介，"
        "当任务需要某个技能时，先调用此工具加载完整内容再执行。"
    )
    param_class = LoadSkillInput

    def __init__(self, skill_loader: SkillLoader):
        self._loader = skill_loader

    def execute(self, parameters: LoadSkillInput) -> str:
        return self._loader.load(parameters.name)
