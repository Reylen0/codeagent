from pydantic import BaseModel, Field

from baseagent.tools.base import BaseTool


class CronCreateParam(BaseModel):
    cron_expr: str = Field(
        description=(
            "标准 5 字段 cron 表达式（分 时 日 月 周），例如："
            " '0 9 * * 1-5'（工作日 9 点）、'*/30 * * * *'（每 30 分钟）"
        )
    )
    prompt: str = Field(description="定时触发时注入到 Agent 的提示内容")
    recurring: bool = Field(
        default=True,
        description="是否循环执行；false 表示只触发一次后自动删除",
    )


class CronDeleteParam(BaseModel):
    job_id: str = Field(description="要取消的定时任务 ID，例如 cron_0001")


class CronListParam(BaseModel):
    pass


class CronCreateTool(BaseTool):
    name = "cron_create"
    description = (
        "创建定时任务。到期时将 prompt 注入为用户消息，触发 Agent 响应。"
        "支持标准 5 字段 cron 表达式，可设置是否循环执行。"
    )
    param_class = CronCreateParam

    def __init__(self, cron_manager):
        self._mgr = cron_manager

    def execute(self, parameters: CronCreateParam) -> str:
        try:
            job_id = self._mgr.schedule(
                parameters.cron_expr, parameters.prompt, parameters.recurring
            )
            jobs = self._mgr.list_jobs()
            job = next((j for j in jobs if j["id"] == job_id), None)
            next_fire = job["next_fire"] if job else "未知"
            flag = "循环" if parameters.recurring else "一次性"
            return (
                f"定时任务已创建：{job_id} [{flag}]\n"
                f"Cron: {parameters.cron_expr}\n"
                f"Prompt: {parameters.prompt}\n"
                f"下次触发: {next_fire}"
            )
        except Exception as e:
            return f"Error: {e}"


class CronDeleteTool(BaseTool):
    name = "cron_delete"
    description = "取消并删除指定 ID 的定时任务。"
    param_class = CronDeleteParam

    def __init__(self, cron_manager):
        self._mgr = cron_manager

    def execute(self, parameters: CronDeleteParam) -> str:
        ok = self._mgr.cancel(parameters.job_id)
        if ok:
            return f"定时任务 {parameters.job_id} 已取消。"
        return f"Error: 未找到定时任务 {parameters.job_id}"


class CronListTool(BaseTool):
    name = "cron_list"
    description = "列出所有活跃的定时任务及其下次触发时间。"
    param_class = CronListParam

    def __init__(self, cron_manager):
        self._mgr = cron_manager

    def execute(self, parameters: CronListParam) -> str:
        jobs = self._mgr.list_jobs()
        if not jobs:
            return "当前没有活跃的定时任务。"
        lines = ["活跃定时任务："]
        for j in jobs:
            flag = "循环" if j["recurring"] else "一次性"
            lines.append(
                f"  {j['id']} [{flag}]  下次: {j['next_fire']}\n"
                f"    Cron: {j['cron_expr']}\n"
                f"    Prompt: {j['prompt']}"
            )
        return "\n".join(lines)
