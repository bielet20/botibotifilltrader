import asyncio
import os
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

from scripts.monitor_paper_fleet import (
    collect_snapshot,
    append_csv_row,
    append_jsonl_row,
    build_final_summary,
    atomic_write_json,
)


def _as_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        v = value.strip().lower()
        if v in {"1", "true", "yes", "y", "on"}:
            return True
        if v in {"0", "false", "no", "n", "off"}:
            return False
    if value is None:
        return default
    return bool(value)


class PaperMonitorRuntimeService:
    def __init__(self):
        self.enabled = _as_bool(os.getenv("AUTO_PAPER_MONITOR_ENABLED", "false"), False)
        self.default_hours = float(os.getenv("AUTO_PAPER_MONITOR_HOURS", "2") or 2)
        self.default_interval = int(float(os.getenv("AUTO_PAPER_MONITOR_INTERVAL_SEC", "120") or 120))
        self.default_prefix = str(os.getenv("AUTO_PAPER_MONITOR_PREFIX", "paper_lab_prod") or "paper_lab_prod")

        self._task = None
        self._lock = asyncio.Lock()
        self._running = False
        self._started_at = None
        self._deadline = None
        self._last_error = None
        self._last_snapshot = None

        self._csv_path = None
        self._jsonl_path = None
        self._summary_path = None
        self._prefix = self.default_prefix
        self._interval = self.default_interval
        self._hours = self.default_hours

    def latest_status(self):
        now = datetime.now(timezone.utc)
        remaining_sec = None
        if self._deadline:
            remaining = (self._deadline - now).total_seconds()
            remaining_sec = max(0, int(remaining))

        return {
            "enabled": self.enabled,
            "running": self._running,
            "started_at": self._started_at.isoformat() if self._started_at else None,
            "deadline": self._deadline.isoformat() if self._deadline else None,
            "remaining_sec": remaining_sec,
            "last_error": self._last_error,
            "prefix": self._prefix,
            "hours": self._hours,
            "interval_sec": self._interval,
            "files": {
                "csv": str(self._csv_path) if self._csv_path else None,
                "jsonl": str(self._jsonl_path) if self._jsonl_path else None,
                "summary": str(self._summary_path) if self._summary_path else None,
            },
            "aggregate": (self._last_snapshot or {}).get("aggregate") if self._last_snapshot else None,
            "timestamp": now.isoformat(),
        }

    async def start(self, hours=None, interval_sec=None, prefix=None, trigger="manual"):
        async with self._lock:
            if self._running:
                return {"started": False, "reason": "already_running", **self.latest_status()}

            self._hours = float(hours if hours is not None else self.default_hours)
            self._interval = int(interval_sec if interval_sec is not None else self.default_interval)
            self._prefix = str(prefix or self.default_prefix)
            self._last_error = None
            self._last_snapshot = None

            reports = Path("reports")
            reports.mkdir(exist_ok=True)

            stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            run_id = f"{stamp}_{uuid.uuid4().hex[:6]}"
            self._csv_path = reports / f"{self._prefix}_monitor_{run_id}.csv"
            self._jsonl_path = reports / f"{self._prefix}_monitor_{run_id}.jsonl"
            self._summary_path = reports / f"{self._prefix}_summary_{run_id}.json"

            self._started_at = datetime.now(timezone.utc)
            self._deadline = self._started_at + timedelta(seconds=max(1.0, self._hours * 3600.0))

            self._running = True
            self._task = asyncio.create_task(self._run_loop(trigger=trigger))
            return {"started": True, **self.latest_status()}

    async def stop(self, trigger="manual"):
        async with self._lock:
            if not self._running:
                return {"stopped": False, "reason": "not_running", **self.latest_status()}

            task = self._task
            self._task = None
            self._running = False

        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                self._last_error = f"stop_error: {exc}"

        return {"stopped": True, "trigger": trigger, **self.latest_status()}

    async def _run_loop(self, trigger="manual"):
        try:
            while True:
                snapshot = collect_snapshot()
                self._last_snapshot = snapshot
                append_csv_row(self._csv_path, snapshot)
                append_jsonl_row(self._jsonl_path, snapshot)

                now = datetime.now(timezone.utc)
                if now >= self._deadline:
                    break

                remaining = max(0.0, (self._deadline - now).total_seconds())
                sleep_for = min(max(1, self._interval), remaining)
                if sleep_for <= 0:
                    break
                await asyncio.sleep(sleep_for)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self._last_error = f"runtime_error: {exc}"
        finally:
            try:
                started = self._started_at.isoformat() if self._started_at else datetime.now(timezone.utc).isoformat()
                ended = datetime.now(timezone.utc).isoformat()
                if self._last_snapshot is None:
                    self._last_snapshot = collect_snapshot()
                summary = build_final_summary(self._last_snapshot, started, ended)
                if self._last_error:
                    summary["run_status"] = self._last_error
                atomic_write_json(self._summary_path, summary)
            except Exception as exc:
                self._last_error = f"summary_error: {exc}"
            finally:
                self._running = False
                self._task = None
