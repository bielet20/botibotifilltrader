import argparse
import csv
import json
import math
import os
import time
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import fcntl

from apps.shared.database import SessionLocal
from apps.shared.models import BotDB, TradeDB, PositionDB

LAB_IDS = {
    "Bot-LAB-EMA-BTC",
    "Bot-LAB-EMA-ETH",
    "Bot-LAB-GRID-BTC",
    "Bot-LAB-ADAPT-BTC",
    "Bot-LAB-PAIR-BTC-ETH",
}


def safe_float(value, default: float = 0.0) -> float:
    try:
        parsed = float(value or default)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(parsed):
        return default
    return parsed


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def compute_max_drawdown(cumulative_points):
    peak = 0.0
    max_dd = 0.0
    for value in cumulative_points:
        if value > peak:
            peak = value
        dd = peak - value
        if dd > max_dd:
            max_dd = dd
    return max_dd


def collect_snapshot():
    with SessionLocal() as db:
        bots = db.query(BotDB).filter(BotDB.id.in_(list(LAB_IDS))).all()
        trades = db.query(TradeDB).filter(TradeDB.bot_id.in_(list(LAB_IDS))).order_by(TradeDB.time.asc()).all()
        positions = db.query(PositionDB).filter(PositionDB.bot_id.in_(list(LAB_IDS)), PositionDB.is_open == True).all()

    per_bot = {}
    for bot_id in LAB_IDS:
        bt = [t for t in trades if t.bot_id == bot_id]
        pnl_points = []
        cumulative = 0.0
        for t in bt:
            cumulative += safe_float(t.pnl)
            pnl_points.append(cumulative)

        scored = [t for t in bt if safe_float(t.pnl) != 0.0]
        wins = sum(1 for t in scored if safe_float(t.pnl) > 0.0)
        losses = sum(1 for t in scored if safe_float(t.pnl) < 0.0)
        pnl = sum(safe_float(t.pnl) for t in bt)
        fees = sum(safe_float(t.fee) for t in bt)
        net = pnl - fees
        win_rate = (wins / len(scored) * 100.0) if scored else 0.0
        profit_sum = sum(safe_float(t.pnl) for t in scored if safe_float(t.pnl) > 0.0)
        loss_sum = abs(sum(safe_float(t.pnl) for t in scored if safe_float(t.pnl) < 0.0))
        profit_factor = (profit_sum / loss_sum) if loss_sum > 0 else 0.0
        max_dd = compute_max_drawdown(pnl_points)

        bot_row = next((b for b in bots if b.id == bot_id), None)
        status = bot_row.status if bot_row else "missing"

        per_bot[bot_id] = {
            "status": status,
            "trades": len(bt),
            "scored_trades": len(scored),
            "wins": wins,
            "losses": losses,
            "win_rate": round(win_rate, 4),
            "pnl": round(pnl, 8),
            "fees": round(fees, 8),
            "net": round(net, 8),
            "profit_factor": round(profit_factor, 6),
            "max_drawdown_abs": round(max_dd, 8),
        }

    open_positions = [
        {
            "bot_id": p.bot_id,
            "symbol": p.symbol,
            "side": p.side,
            "qty": safe_float(p.quantity),
            "entry": safe_float(p.entry_price),
            "current": safe_float(p.current_price),
            "upnl": safe_float(p.unrealized_pnl),
        }
        for p in positions
    ]

    aggregate = {
        "trades": sum(v["trades"] for v in per_bot.values()),
        "scored_trades": sum(v["scored_trades"] for v in per_bot.values()),
        "wins": sum(v["wins"] for v in per_bot.values()),
        "losses": sum(v["losses"] for v in per_bot.values()),
        "pnl": round(sum(v["pnl"] for v in per_bot.values()), 8),
        "fees": round(sum(v["fees"] for v in per_bot.values()), 8),
        "net": round(sum(v["net"] for v in per_bot.values()), 8),
    }
    aggregate["win_rate"] = round((aggregate["wins"] / aggregate["scored_trades"] * 100.0), 4) if aggregate["scored_trades"] > 0 else 0.0

    return {
        "timestamp": utc_now_iso(),
        "aggregate": aggregate,
        "per_bot": per_bot,
        "open_positions": open_positions,
    }


def append_csv_row(csv_path: Path, snapshot: dict):
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    exists = csv_path.exists()
    with csv_path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not exists:
            writer.writerow([
                "timestamp",
                "bot_id",
                "status",
                "trades",
                "scored_trades",
                "wins",
                "losses",
                "win_rate",
                "pnl",
                "fees",
                "net",
                "profit_factor",
                "max_drawdown_abs",
            ])
        for bot_id, data in snapshot["per_bot"].items():
            writer.writerow([
                snapshot["timestamp"],
                bot_id,
                data["status"],
                data["trades"],
                data["scored_trades"],
                data["wins"],
                data["losses"],
                data["win_rate"],
                data["pnl"],
                data["fees"],
                data["net"],
                data["profit_factor"],
                data["max_drawdown_abs"],
            ])
        f.flush()
        os.fsync(f.fileno())


def append_jsonl_row(jsonl_path: Path, snapshot: dict):
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    with jsonl_path.open("a", encoding="utf-8") as jf:
        jf.write(json.dumps(snapshot, ensure_ascii=False) + "\n")
        jf.flush()
        os.fsync(jf.fileno())


def atomic_write_json(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=str(path.parent)) as tf:
        tf.write(json.dumps(payload, ensure_ascii=False, indent=2))
        tf.flush()
        os.fsync(tf.fileno())
        temp_path = Path(tf.name)
    os.replace(temp_path, path)


def acquire_run_lock(lock_path: Path):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = lock_path.open("w", encoding="utf-8")
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock_file.write(str(os.getpid()))
        lock_file.flush()
        os.fsync(lock_file.fileno())
        return lock_file
    except BlockingIOError:
        lock_file.close()
        raise RuntimeError(f"Another monitor run is active (lock: {lock_path})")


def score_bot(data: dict):
    sample_factor = min(data["trades"] / 120.0, 1.0)
    win_component = min(max(data["win_rate"] / 100.0, 0.0), 1.0)
    pf_component = min(data["profit_factor"] / 2.0, 1.0)
    net_component = 1.0 if data["net"] > 0 else 0.0
    dd_penalty = min(data["max_drawdown_abs"] / 150.0, 1.0)

    raw = (0.30 * sample_factor) + (0.25 * win_component) + (0.25 * pf_component) + (0.20 * net_component)
    score = max(0.0, raw * (1.0 - 0.35 * dd_penalty))
    return round(score * 100.0, 2)


def build_final_summary(final_snapshot: dict, started_at: str, ended_at: str):
    ranking = []
    for bot_id, data in final_snapshot["per_bot"].items():
        s = score_bot(data)
        promote = (
            data["trades"] >= 120
            and data["win_rate"] >= 55.0
            and data["profit_factor"] >= 1.25
            and data["net"] > 0
            and data["max_drawdown_abs"] <= 300.0
        )
        ranking.append({
            "bot_id": bot_id,
            "score": s,
            "promote_candidate": promote,
            **data,
        })

    ranking.sort(key=lambda x: x["score"], reverse=True)

    return {
        "window": {
            "started_at": started_at,
            "ended_at": ended_at,
        },
        "aggregate": final_snapshot["aggregate"],
        "ranking": ranking,
        "promotion_criteria": {
            "min_trades": 120,
            "min_win_rate_pct": 55.0,
            "min_profit_factor": 1.25,
            "positive_net": True,
            "max_drawdown_abs": 300.0,
        },
        "open_positions": final_snapshot["open_positions"],
    }


def main():
    parser = argparse.ArgumentParser(description="Monitor paper lab fleet")
    parser.add_argument("--hours", type=float, default=12.0, help="Monitoring duration in hours")
    parser.add_argument("--interval", type=int, default=300, help="Snapshot interval in seconds")
    parser.add_argument("--prefix", type=str, default="paper_lab", help="Output filename prefix")
    args = parser.parse_args()

    started_at = utc_now_iso()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_id = f"{stamp}_{uuid.uuid4().hex[:6]}"
    reports = Path("reports")
    reports.mkdir(exist_ok=True)

    csv_path = reports / f"{args.prefix}_monitor_{run_id}.csv"
    jsonl_path = reports / f"{args.prefix}_monitor_{run_id}.jsonl"
    summary_path = reports / f"{args.prefix}_summary_{run_id}.json"
    lock_path = reports / f"{args.prefix}.lock"

    deadline = time.time() + max(1.0, args.hours * 3600.0)
    last_snapshot = None
    loop_error = None

    lock_file = acquire_run_lock(lock_path)

    try:
        while True:
            now = time.time()
            snapshot = collect_snapshot()
            last_snapshot = snapshot

            append_csv_row(csv_path, snapshot)
            append_jsonl_row(jsonl_path, snapshot)

            print(f"[monitor] {snapshot['timestamp']} agg={snapshot['aggregate']}")

            if now >= deadline:
                break

            sleep_for = min(args.interval, max(0.0, deadline - now))
            if sleep_for <= 0:
                break
            time.sleep(sleep_for)
    except KeyboardInterrupt:
        loop_error = "interrupted"
        print("[monitor] interrupted")
    except Exception as exc:
        loop_error = f"runtime_error: {exc}"
        raise
    finally:
        ended_at = utc_now_iso()
        if last_snapshot is None:
            last_snapshot = collect_snapshot()
        summary = build_final_summary(last_snapshot, started_at, ended_at)
        if loop_error:
            summary["run_status"] = loop_error
        atomic_write_json(summary_path, summary)

        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        finally:
            lock_file.close()

    print("[monitor] completed")
    print(f"[monitor] csv={csv_path}")
    print(f"[monitor] jsonl={jsonl_path}")
    print(f"[monitor] summary={summary_path}")


if __name__ == "__main__":
    main()
