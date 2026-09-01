from datetime import datetime
import zoneinfo

from pydantic import BaseModel, Field

from ..base import BaseTool


class GetCurrentTimeParam(BaseModel):
    timezone: str = Field(
        default="",
        description="时区名称，例如 Asia/Shanghai、America/New_York，留空使用本地时区"
    )


class GetCurrentTimeTool(BaseTool):
    """获取当前时间工具"""

    name: str = "get_current_time"
    description: str = "获取当前时间、时区和星期几"
    param_class = GetCurrentTimeParam

    WEEKDAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]

    def execute(self, parameters: GetCurrentTimeParam) -> dict:
        if parameters.timezone:
            try:
                tz = zoneinfo.ZoneInfo(parameters.timezone)
            except zoneinfo.ZoneInfoNotFoundError:
                return {"error": f"未知时区: {parameters.timezone}"}
            now = datetime.now(tz)
            tz_name = parameters.timezone
        else:
            now = datetime.now().astimezone()
            offset = now.strftime("%z")
            tz_name = f"UTC{offset[:3]}:{offset[3:]}"

        return (
            f"当前时间: {now.strftime('%Y-%m-%d %H:%M:%S')} ({self.WEEKDAYS[now.weekday()]})\n"
            f"时区: {tz_name}"
        )
