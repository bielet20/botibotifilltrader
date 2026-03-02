# Catálogo de 10 Bots (Tendencias habituales y enfoque seguro)

Este catálogo define 10 presets para arrancar bots de forma rápida y consistente.

## Objetivo
- Tener configuraciones reutilizables para mercados de tendencia, lateralidad y escenarios mixtos.
- Priorizar perfiles conservadores o medio-bajos de riesgo.
- Facilitar selección y guardado desde el modal de creación de bots.

## Dónde se usan
- Backend: `apps/shared/bot_presets.py`
- API de presets: `GET /api/bot-presets`
- Crear desde preset: `POST /api/bot-presets/{preset_id}/create`
- Guardar en cápsula sin lanzar: `POST /api/bot-presets/{preset_id}/save`
- UI: selector `Preset recomendado (10 bots seguros)` en el modal de creación.

## Presets disponibles

| ID | Nombre | Estrategia | Mercado objetivo | Riesgo | Configuración clave |
|---|---|---|---|---|---|
| `preset_ema_conservador_btc` | EMA Conservador BTC | `ema_cross` | Tendencia suave | Bajo | EMA 12/26, BTC/USDT |
| `preset_ema_conservador_eth` | EMA Conservador ETH | `ema_cross` | Tendencia suave | Bajo | EMA 10/30, ETH/USDT |
| `preset_technical_pro_balanced` | Technical Pro Balanceado | `technical_pro` | Mixto | Medio-bajo | Filtros técnicos múltiples |
| `preset_algo_expert_defensivo` | Algo Expert Defensivo | `algo_expert` | Mixto | Medio-bajo | Híbrido con filtros de señal |
| `preset_grid_btc_wide` | Grid BTC Rango Amplio | `grid_trading` | Lateral amplio | Bajo | 58k–72k, 8 grids |
| `preset_grid_btc_tight` | Grid BTC Rango Controlado | `grid_trading` | Lateral controlado | Medio-bajo | 62k–68k, 12 grids |
| `preset_grid_eth_stable` | Grid ETH Estable | `grid_trading` | Lateral amplio | Medio-bajo | 2.8k–4.2k, 10 grids |
| `preset_dynamic_reinvest_safe` | Dynamic Reinvest Seguro | `dynamic_reinvest` | Tendencia media | Medio | TP 2% + reinversión parcial |
| `preset_technical_pro_range_filter` | Technical Pro con Filtro de Rango | `technical_pro` | Mixto | Medio-bajo | Rango 60k–70k |
| `preset_ema_swing_defensivo` | EMA Swing Defensivo | `ema_cross` | Tendencia volátil | Medio-bajo | EMA 20/50 |

## Política de seguridad por defecto
- `executor: paper` en todos los presets (simulado).
- `risk_config.max_drawdown` entre `0.04` y `0.05`.
- `capital_allocation` inicial conservador (`500`) para pruebas.

## Flujo recomendado de uso
1. Abrir **Crear Nuevo Bot**.
2. Elegir un preset en el selector.
3. Revisar la documentación rápida que aparece debajo.
4. Ajustar símbolo o capital si hace falta.
5. Elegir entre:
	- **Guardar en Cápsula** (archivado, sin ejecución), o
	- **Finalizar y Lanzar Bot** (se crea en ejecución).

## Notas operativas
- En producción real, validar liquidez, spread, comisiones y horario del mercado.
- Ajustar límites/rangos periódicamente según volatilidad reciente.
- Para Hyperliquid mainnet, cambiar `executor` conscientemente y confirmar formato de símbolo.
