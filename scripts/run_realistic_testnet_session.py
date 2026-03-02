import json
import sqlite3
import time
from datetime import datetime, timezone
from urllib import request

BASE = "http://localhost:8000"
DB = "trading.db"


def call(url, method="GET", data=None):
    payload = None
    headers = {}
    if data is not None:
        payload = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = request.Request(url, data=payload, method=method, headers=headers)
    with request.urlopen(req, timeout=15) as r:
        body = r.read().decode("utf-8")
        return json.loads(body) if body else {}


def main():
    for bot in ["Bot-571", "Bot-890"]:
        try:
            print("stop", bot, call(f"{BASE}/api/bots/{bot}/stop", "POST"))
        except Exception as e:
            print("stop", bot, "skip", e)

    new_cfg = {
        "upper_limit": 67050,
        "lower_limit": 66850,
        "num_grids": 20,
        "allocation": 25,
        "leverage": 5,
        "executor": "hyperliquid",
        "hyperliquid_testnet": True,
        "symbol": "BTC/USDC:USDC",
        "risk_config": {"max_drawdown": 0.05},
    }

    print("patch", call(f"{BASE}/api/bots/Bot-571", "PATCH", new_cfg))
    print("start", call(f"{BASE}/api/bots/Bot-571/start", "POST"))

    start_utc = datetime.now(timezone.utc)
    print("start_utc", start_utc.isoformat())

    for i in range(24):
        try:
            h = call(f"{BASE}/api/health")
            p = call(f"{BASE}/api/positions")
            print(f"tick {i + 1:02d}/24 | bots={h.get('running_bots')} open_pos={len(p)}")
        except Exception as e:
            print("tick err", e)
        time.sleep(15)

    try:
        print("stop2", call(f"{BASE}/api/bots/Bot-571/stop", "POST"))
    except Exception as e:
        print("stop2 skip", e)

    end_utc = datetime.now(timezone.utc)
    print("end_utc", end_utc.isoformat())

    start_sql = start_utc.replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")
    end_sql = end_utc.replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")

    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT COUNT(*),
               COALESCE(SUM(pnl),0),
               COALESCE(SUM(fee),0),
               COALESCE(SUM(pnl)-SUM(fee),0)
        FROM trades
        WHERE bot_id='Bot-571' AND time >= ? AND time <= ?
        """,
        (start_sql, end_sql),
    )
    count_, gross, fees, net = cur.fetchone()
    print("RESULT", json.dumps({
        "trades": count_,
        "gross_pnl": round(gross, 8),
        "fees": round(fees, 8),
        "net_pnl": round(net, 8),
        "start": start_sql,
        "end": end_sql,
    }))

    cur.execute(
        """
        SELECT side, price, amount, fee, pnl, time
        FROM trades
        WHERE bot_id='Bot-571' AND time >= ? AND time <= ?
        ORDER BY time DESC
        LIMIT 10
        """,
        (start_sql, end_sql),
    )
    rows = cur.fetchall()
    print("LAST_TRADES")
    for r in rows:
        print(r)
    conn.close()


if __name__ == "__main__":
    main()
