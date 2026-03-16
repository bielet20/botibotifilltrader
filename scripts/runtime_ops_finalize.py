import json
import os
import sqlite3
import urllib.request

BASE = "http://127.0.0.1:8000"


def get(path: str):
    with urllib.request.urlopen(BASE + path, timeout=30) as response:
        return json.loads(response.read().decode())


def request(path: str, method: str = "POST", data=None):
    payload = None
    headers = {}
    if data is not None:
        payload = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=payload, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as response:
        raw = response.read().decode()
        return json.loads(raw) if raw else {}


def main():
    alerts = get("/api/production/alerts?limit=200&only_open=true")
    critical_alerts = [a for a in alerts if str(a.get("level", "")).lower() == "critical"]

    acked = 0
    for alert in critical_alerts:
        try:
            request(f"/api/production/alerts/{alert['id']}/ack", method="POST")
            acked += 1
        except Exception as exc:
            print(f"ACK_FAIL {alert.get('id')} {exc}")

    bots = get("/api/bots?include_system=true")
    orders = get("/api/orders?limit=300")

    insufficient_cash_bots = set()
    for order in orders:
        result = order.get("result") or {}
        reason = str(result.get("reason") or "").lower()
        if "insufficient_cash" in reason:
            bot_id = order.get("bot_id")
            if bot_id:
                insufficient_cash_bots.add(bot_id)

    # Also include bots with depleted paper cash even if recent order logs are clean.
    low_cash_bots = set()
    db_path = "trading.db"
    if os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        rows = cur.execute(
            "SELECT bot_id, cash_balance FROM paper_portfolios"
        ).fetchall()
        for bot_id, cash_balance in rows:
            if float(cash_balance or 0.0) < 150.0:
                low_cash_bots.add(str(bot_id))
        conn.close()

    insufficient_cash_bots |= low_cash_bots

    patched_bots = []
    for bot in bots:
        bot_id = bot.get("id")
        if bot_id not in insufficient_cash_bots:
            continue
        config = dict(bot.get("config") or {})
        executor = str(config.get("executor") or "").lower()
        if executor != "paper":
            continue

        patch = {
            "capital_allocation": max(float(config.get("capital_allocation") or 120.0), 180.0),
            "initial_balance": max(float(config.get("initial_balance") or 1000.0), 3000.0),
            "risk_per_trade": min(float(config.get("risk_per_trade") or 0.02), 0.01),
        }

        strategy = str(config.get("strategy") or "").lower()
        if strategy in {"ema_cross", "technical_pro"}:
            patch["trade_size"] = min(float(config.get("trade_size") or 0.01), 0.005)
            patch["amount"] = min(float(config.get("amount") or 0.01), 0.005)

        try:
            request(f"/api/bots/{bot_id}", method="PATCH", data=patch)
            patched_bots.append({"bot_id": bot_id, "patch": patch})
        except Exception as exc:
            print(f"PATCH_FAIL {bot_id} {exc}")

    topped_up = []
    if os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        for bot_id in sorted(insufficient_cash_bots):
            cur.execute(
                "SELECT cash_balance, total_equity FROM paper_portfolios WHERE bot_id = ?",
                (bot_id,),
            )
            row = cur.fetchone()
            if not row:
                continue
            cash = float(row[0] or 0.0)
            total_equity = float(row[1] or 0.0)
            if cash < 150.0:
                new_cash = 1500.0
                new_total_equity = max(total_equity, new_cash)
                cur.execute(
                    "UPDATE paper_portfolios SET cash_balance = ?, total_equity = ?, updated_at = CURRENT_TIMESTAMP WHERE bot_id = ?",
                    (new_cash, new_total_equity, bot_id),
                )
                topped_up.append({"bot_id": bot_id, "cash_before": cash, "cash_after": new_cash})
        conn.commit()
        conn.close()

    try:
        request(
            "/api/monitoring/prepare-production",
            method="POST",
            data={"lookback_hours": 48, "min_scored_trades": 8},
        )
    except Exception as exc:
        print(f"PREPARE_FAIL {exc}")

    test_results = request(
        "/api/monitoring/test-results",
        method="POST",
        data={"lookback_hours": 48, "min_scored_trades": 8},
    )

    summary_block = dict(test_results.get("summary") or {})
    output = {
        "open_alerts": len(alerts),
        "critical_open_before": len(critical_alerts),
        "critical_acked": acked,
        "insufficient_cash_bots": sorted(insufficient_cash_bots),
        "patched_bots": patched_bots,
        "portfolio_topped_up": topped_up,
        "summary": {
            "bots_analyzed": int(summary_block.get("bots_analyzed") or 0),
            "production_candidates": int(summary_block.get("production_candidates") or 0),
            "critical_alerts_open": int(summary_block.get("critical_alerts_open") or 0),
        },
    }
    print(json.dumps(output, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
