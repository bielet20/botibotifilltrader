import asyncio
import itertools
import json
from datetime import datetime, timezone
from pathlib import Path

from apps.engine.market_data import MarketDataEngine
from apps.engine.paired_balanced import PairedBalancedStrategy


def _align_by_time(a, b):
    map_a = {c['time']: c for c in a}
    map_b = {c['time']: c for c in b}
    times = sorted(set(map_a.keys()) & set(map_b.keys()))
    return [map_a[t] for t in times], [map_b[t] for t in times]


def simulate_pair(candles_a, candles_b, cfg):
    strategy = PairedBalancedStrategy(lookback=cfg['lookback'])
    fee_rate = cfg['fee_rate']

    notional = cfg['allocation'] * 0.48
    cash = 10000.0
    cum_pnl = 0.0
    peak = 0.0
    max_dd = 0.0
    trades = 0
    wins = 0
    losses = 0

    pos = None

    for i in range(cfg['lookback'] + 5, len(candles_a)):
        history_a = candles_a[: i + 1]
        history_b = candles_b[: i + 1]
        price_a = float(history_a[-1]['close'])
        price_b = float(history_b[-1]['close'])

        decision = strategy.evaluate(
            {
                'history_a': history_a,
                'history_b': history_b,
                'entry_z': cfg['entry_z'],
                'exit_z': cfg['exit_z'],
                'min_correlation': cfg['min_corr'],
            }
        )

        if pos is not None:
            pnl_a = ((price_a - pos['entry_a']) * pos['qty_a']) if pos['side_a'] == 'long' else ((pos['entry_a'] - price_a) * pos['qty_a'])
            pnl_b = ((price_b - pos['entry_b']) * pos['qty_b']) if pos['side_b'] == 'long' else ((pos['entry_b'] - price_b) * pos['qty_b'])
            unrealized = pnl_a + pnl_b

            should_close = False
            if unrealized <= -cfg['stop_loss_abs']:
                should_close = True
            elif unrealized >= cfg['take_profit_abs']:
                should_close = True
            elif decision.action == 'close_pair' and (i - pos['opened_index']) >= cfg['min_hold_bars']:
                should_close = True

            if should_close:
                fee_close = (pos['qty_a'] * price_a + pos['qty_b'] * price_b) * fee_rate
                realized = unrealized - pos['fee_open'] - fee_close
                cum_pnl += realized
                cash += realized
                trades += 2
                if realized > 0:
                    wins += 1
                elif realized < 0:
                    losses += 1
                pos = None

        if pos is None and decision.action == 'open_pair':
            qty_a = max(0.000001, notional / max(price_a, 1e-9))
            qty_b = max(0.000001, notional / max(price_b, 1e-9))
            fee_open = (qty_a * price_a + qty_b * price_b) * fee_rate
            pos = {
                'qty_a': qty_a,
                'qty_b': qty_b,
                'entry_a': price_a,
                'entry_b': price_b,
                'side_a': 'long' if decision.side_a.value == 'buy' else 'short',
                'side_b': 'long' if decision.side_b.value == 'buy' else 'short',
                'fee_open': fee_open,
                'opened_index': i,
            }

        peak = max(peak, cum_pnl)
        max_dd = max(max_dd, peak - cum_pnl)

    score = cum_pnl - (max_dd * 0.5)
    win_rate = (wins / max((wins + losses), 1)) * 100.0

    return {
        'cum_pnl': round(cum_pnl, 6),
        'max_drawdown_abs': round(max_dd, 6),
        'trades': trades,
        'wins': wins,
        'losses': losses,
        'win_rate': round(win_rate, 2),
        'score': round(score, 6),
    }


async def main():
    symbol_a = 'BTC/USDT'
    symbol_b = 'ETH/USDT'
    timeframe = '15m'
    limit = 800

    mde = MarketDataEngine('binance')
    candles_a = await mde.fetch_ohlcv(symbol_a, timeframe=timeframe, limit=limit)
    candles_b = await mde.fetch_ohlcv(symbol_b, timeframe=timeframe, limit=limit)
    await mde.close()

    candles_a, candles_b = _align_by_time(candles_a, candles_b)
    if len(candles_a) < 300:
        raise RuntimeError(f'Not enough aligned candles: {len(candles_a)}')

    grid = {
        'entry_z': [1.1, 1.3, 1.5, 1.7],
        'exit_z': [0.2, 0.3, 0.4],
        'min_corr': [0.25, 0.35, 0.45],
        'lookback': [80, 120, 160],
        'min_hold_bars': [4, 8],
    }

    base = {
        'allocation': 400.0,
        'fee_rate': 0.001,
        'stop_loss_abs': 4.8,
        'take_profit_abs': 3.6,
    }

    results = []
    for entry_z, exit_z, min_corr, lookback, min_hold_bars in itertools.product(
        grid['entry_z'], grid['exit_z'], grid['min_corr'], grid['lookback'], grid['min_hold_bars']
    ):
        cfg = {
            **base,
            'entry_z': entry_z,
            'exit_z': exit_z,
            'min_corr': min_corr,
            'lookback': lookback,
            'min_hold_bars': min_hold_bars,
        }
        metrics = simulate_pair(candles_a, candles_b, cfg)
        results.append({**cfg, **metrics})

    results.sort(key=lambda x: (x['score'], x['cum_pnl'], x['win_rate']), reverse=True)
    best = results[:10]

    out = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'symbol_a': symbol_a,
        'symbol_b': symbol_b,
        'timeframe': timeframe,
        'aligned_candles': len(candles_a),
        'best': best,
    }

    reports = Path('reports')
    reports.mkdir(exist_ok=True)
    out_file = reports / f"pair_opt_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    out_file.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')

    print(str(out_file))
    print(json.dumps(best[0], ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(main())
