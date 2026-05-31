"""定时轮询任务"""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from config import POLL_INTERVAL_MINUTES
from services.announcement import AnnouncementService


_scheduler: BackgroundScheduler = None


def _poll_job():
    """实际的轮询任务"""
    print("=" * 50)
    print(f"[Scheduler] 开始轮询股票池... {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    results = AnnouncementService.poll_all_stocks()
    total_new = sum(v for v in results.values() if v > 0)
    print(f"[Scheduler] 轮询完成，共新增 {total_new} 条公告")
    print("=" * 50)


def start_scheduler(interval_minutes: int = POLL_INTERVAL_MINUTES) -> BackgroundScheduler:
    """启动后台定时轮询"""
    global _scheduler
    if _scheduler and _scheduler.running:
        print("[Scheduler] 调度器已在运行")
        return _scheduler

    _scheduler = BackgroundScheduler()
    _scheduler.add_job(
        _poll_job,
        trigger=IntervalTrigger(minutes=interval_minutes),
        id="stock_poll",
        replace_existing=True,
    )
    _scheduler.start()
    print(f"[Scheduler] 已启动，每 {interval_minutes} 分钟轮询一次")
    return _scheduler


def stop_scheduler():
    """停止定时轮询"""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown()
        print("[Scheduler] 已停止")


def trigger_once():
    """手动触发一次轮询"""
    _poll_job()


from datetime import datetime  # noqa: E402
