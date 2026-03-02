#!/usr/bin/env python3
import argparse
import csv
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib import request, error


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def http_json(url: str, method: str = "GET", timeout: int = 10):
    req = request.Request(url=url, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            data = resp.read().decode("utf-8")
            return json.loads(data) if data else None
    except error.HTTPError as e:
        return {"_http_error": e.code, "_message": e.read().decode("utf-8", errors="ignore")}
    except Exception as e:
        return {"_error": str(e)}


def safe_number(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return float(default)


def get_invested_breakdown(positions):
    by_symbol = {}
    for p in positions or []:
        symbol = p.get("symbol", "UNKNOWN")
        qty = safe_number(p.get("quantity", 0.0))
        px = safe_number(p.get("current_price", 0.0))
        value = qty * px
        by_symbol[symbol] = by_symbol.get(symbol, 0.0) + value
    total = sum(by_symbol.values())
    return total, by_symbol


def post_start_all_bots(base_url: str):
    bots = http_json(f"{base_url}/api/bots") or []
    started = []
    for b in bots:
        bot_id = b.get("id")
        if not bot_id:
            continue
        res = http_json(f"{base_url}/api/bots/{bot_id}/start", method="POST")
        started.append({"bot_id": bot_id, "result": res})
    return started


def post_stop_all_bots(base_url: str):
    bots = http_json(f"{base_url}/api/bots") or []
    stopped = []
    for b in bots:
        bot_id = b.get("id")
        if not bot_id:
            continue
        res = http_json(f"{base_url}/api/bots/{bot_id}/stop", method="POST")
        stopped.append({"bot_id": bot_id, "result": res})
    return stopped


def main():
    parser = argparse.ArgumentParser(description="Monitor de prueba larga en Testnet con histórico de valor de activos.")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Base URL de la API")
    parser.add_argument("--duration-min", type=int, default=15, help="Duración total de prueba en minutos")
    parser.add_argument("--interval-sec", type=int, default=30, help="Intervalo de muestreo en segundos")
    parser.add_argument("--start-bots", action="store_true", help="Inicia todos los bots al comenzar")
    parser.add_argument("--stop-bots-at-end", action="store_true", help="Detiene todos los bots al finalizar")
    parser.add_argument("--output-dir", default="reports", help="Directorio de salida")
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    jsonl_path = out_dir / f"testnet_monitor_{stamp}.jsonl"
    csv_path = out_dir / f"testnet_monitor_{stamp}.csv"
    summary_path = out_dir / f"testnet_monitor_summary_{stamp}.json"

    health = http_json(f"{args.base_url}/api/health")
    if not isinstance(health, dict) or health.get("status") != "ok":
        raise SystemExit(f"API no disponible en {args.base_url}: {health}")

    if args.start_bots:
        starts = post_start_all_bots(args.base_url)
        print(f"[monitor] bots start results: {starts}")

    start_ts = time.time()
    end_ts = start_ts + (args.duration_min * 60)

    fieldnames = [
        "timestamp",
        "running_bots",
        "total_trades",
        "total_volume",
        "total_pnl",
        "total_fees",
        "open_positions",
        "invested_value_total",
        "assets_breakdown_json",
    ]

    snapshots = []

    with jsonl_path.open("w", encoding="utf-8") as jf, csv_path.open("w", newline="", encoding="utf-8") as cf:
        writer = csv.DictWriter(cf, fieldnames=fieldnames)
        writer.writeheader()

        while time.time() < end_ts:
            ts = now_iso()
            health = http_json(f"{args.base_url}/api/health") or {}
            stats = http_json(f"{args.base_url}/api/stats") or {}
            positions = http_json(f"{args.base_url}/api/positions") or []

            invested_total, by_symbol = get_invested_breakdown(positions)

            snap = {
                "timestamp": ts,
                "health": health,
                "stats": stats,
                "positions": positions,
                "invested_value_total": invested_total,
                "assets_breakdown": by_symbol,
            }
            snapshots.append(snap)
            jf.write(json.dumps(snap, ensure_ascii=False) + "\n")

            row = {
                "timestamp": ts,
                "running_bots": health.get("running_bots", 0),
                "total_trades": stats.get("total_trades", 0),
                "total_volume": stats.get("total_volume", 0),
                "total_pnl": stats.get("total_pnl", 0),
                "total_fees": stats.get("total_fees", 0),
                "open_positions": stats.get("open_positions", 0),
                "invested_value_total": round(invested_total, 6),
                "assets_breakdown_json": json.dumps(by_symbol, ensure_ascii=False),
            }
            writer.writerow(row)

            print(
                f"[snapshot] {ts} | bots={row['running_bots']} trades={row['total_trades']} "
                f"open_pos={row['open_positions']} invested=${row['invested_value_total']:.2f}"
            )
            time.sleep(args.interval_sec)

    first_stats = snapshots[0]["stats"] if snapshots else {}
    last_stats = snapshots[-1]["stats"] if snapshots else {}
    first_invested = snapshots[0].get("invested_value_total", 0.0) if snapshots else 0.0
    last_invested = snapshots[-1].get("invested_value_total", 0.0) if snapshots else 0.0

    summary = {
        "started_at": datetime.fromtimestamp(start_ts, tz=timezone.utc).isoformat(),
        "ended_at": datetime.now(timezone.utc).isoformat(),
        "duration_minutes": args.duration_min,
        "interval_seconds": args.interval_sec,
        "snapshot_count": len(snapshots),
        "trades_start": first_stats.get("total_trades", 0),
        "trades_end": last_stats.get("total_trades", 0),
        "trades_delta": safe_number(last_stats.get("total_trades", 0)) - safe_number(first_stats.get("total_trades", 0)),
        "pnl_start": safe_number(first_stats.get("total_pnl", 0)),
        "pnl_end": safe_number(last_stats.get("total_pnl", 0)),
        "pnl_delta": safe_number(last_stats.get("total_pnl", 0)) - safe_number(first_stats.get("total_pnl", 0)),
        "invested_value_start": first_invested,
        "invested_value_end": last_invested,
        "invested_value_delta": last_invested - first_invested,
        "outputs": {
            "jsonl": str(jsonl_path),
            "csv": str(csv_path),
            "summary": str(summary_path),
        },
    }

    if args.stop_bots_at_end:
        stops = post_stop_all_bots(args.base_url)
        summary["stop_results"] = stops

    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== TESTNET LONG-RUN SUMMARY ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
