"""
定时任务管理器 —— 给 Agent 一个内部时钟。

工作流：
  1. schedule(cron_expr, prompt) 注册定时任务，返回 job_id
  2. 后台线程每 10s 检查一次，到期时把 (job_id, prompt) 放入就绪队列
  3. collect() 取出已触发的任务，格式化为 <cron_notification> 注入 Agent 循环
  4. jobs 持久化到 .codeagent/scheduled_tasks.json，重启后自动恢复
"""

import json
import os
import threading
import time
from dataclasses import dataclass, asdict
from datetime import datetime

try:
    from croniter import croniter as _croniter
    _HAS_CRONITER = True
except ImportError:
    _HAS_CRONITER = False

_CHECK_INTERVAL = 10  # seconds


@dataclass
class CronJob:
    id: str
    cron_expr: str
    prompt: str
    recurring: bool
    next_fire: float    # unix timestamp
    created_at: float


class CronManager:
    """
    管理定时 cron 任务的生命周期。

    线程安全：所有对 _jobs / _ready 的读写都在 _lock 保护下进行。
    后台线程为 daemon，主进程退出时自动终止。
    """

    def __init__(self, workdir: str):
        self._storage = os.path.join(workdir, ".codeagent", "scheduled_tasks.json")
        self._jobs: dict[str, CronJob] = {}
        self._ready: list[tuple[str, str]] = []   # (job_id, prompt)
        self._lock = threading.Lock()
        self._counter = 0

        self._load()

        t = threading.Thread(target=self._loop, daemon=True)
        t.start()

    # ── 公开接口 ──────────────────────────────────────────────────────────────

    def schedule(self, cron_expr: str, prompt: str, recurring: bool = True) -> str:
        """注册定时任务，返回 job_id。"""
        if not _HAS_CRONITER:
            raise RuntimeError("croniter 未安装，请先运行: pip install croniter>=2.0")
        if not _croniter.is_valid(cron_expr):
            raise ValueError(f"无效的 cron 表达式: {cron_expr!r}")

        with self._lock:
            self._counter += 1
            job_id = f"cron_{self._counter:04d}"
            next_fire = _croniter(cron_expr, datetime.now()).get_next(float)
            self._jobs[job_id] = CronJob(
                id=job_id,
                cron_expr=cron_expr,
                prompt=prompt,
                recurring=recurring,
                next_fire=next_fire,
                created_at=time.time(),
            )
        self._save()
        return job_id

    def cancel(self, job_id: str) -> bool:
        """取消并删除任务，不存在时返回 False。"""
        with self._lock:
            if job_id not in self._jobs:
                return False
            del self._jobs[job_id]
        self._save()
        return True

    def list_jobs(self) -> list[dict]:
        """返回所有活跃任务的摘要列表。"""
        with self._lock:
            result = []
            for job in self._jobs.values():
                next_dt = datetime.fromtimestamp(job.next_fire).strftime("%Y-%m-%d %H:%M:%S")
                result.append({
                    "id": job.id,
                    "cron_expr": job.cron_expr,
                    "prompt": job.prompt,
                    "recurring": job.recurring,
                    "next_fire": next_dt,
                })
        return result

    def collect(self) -> list[str]:
        """取出所有已触发的任务，格式化为通知字符串列表。"""
        with self._lock:
            ready = list(self._ready)
            self._ready.clear()
        return [
            f"<cron_notification>\n"
            f"Scheduled task {job_id} fired.\n"
            f"Prompt: {prompt}\n"
            f"</cron_notification>"
            for job_id, prompt in ready
        ]

    def is_empty(self) -> bool:
        with self._lock:
            return len(self._jobs) == 0

    # ── 内部实现 ──────────────────────────────────────────────────────────────

    def _loop(self):
        while True:
            time.sleep(_CHECK_INTERVAL)
            self._check()

    def _check(self):
        now = time.time()
        fired: list[tuple[str, str, str, bool]] = []

        with self._lock:
            for job in self._jobs.values():
                if job.next_fire <= now:
                    fired.append((job.id, job.prompt, job.cron_expr, job.recurring))

        if not fired:
            return

        with self._lock:
            for job_id, prompt, cron_expr, recurring in fired:
                self._ready.append((job_id, prompt))
                if recurring:
                    if job_id in self._jobs:
                        self._jobs[job_id].next_fire = _croniter(
                            cron_expr, datetime.now()
                        ).get_next(float)
                else:
                    self._jobs.pop(job_id, None)

        self._save()

    def _save(self):
        os.makedirs(os.path.dirname(self._storage), exist_ok=True)
        with self._lock:
            data = {jid: asdict(j) for jid, j in self._jobs.items()}
        try:
            with open(self._storage, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _load(self):
        if not os.path.isfile(self._storage):
            return
        try:
            with open(self._storage, encoding="utf-8") as f:
                data = json.load(f)
            for job_id, d in data.items():
                job = CronJob(**d)
                # 重启后如果 next_fire 已过期，重新计算下次时间
                if _HAS_CRONITER and job.next_fire <= time.time():
                    job.next_fire = _croniter(
                        job.cron_expr, datetime.now()
                    ).get_next(float)
                self._jobs[job_id] = job
                try:
                    num = int(job_id.split("_")[1])
                    if num >= self._counter:
                        self._counter = num
                except (IndexError, ValueError):
                    pass
        except Exception:
            pass
