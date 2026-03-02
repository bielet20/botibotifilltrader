# Plan de despliegue a producción (Trading Bot Platform)

Fecha: 28-02-2026
Objetivo: pasar de entorno validado en testnet a producción real con riesgo controlado y capacidad de rollback inmediata.

## 1) Estrategia general

- Despliegue por fases: Testnet estable -> Paper en producción -> Capital real reducido -> Escalado gradual.
- Solo una variable de riesgo por fase (capital, número de bots o apalancamiento), nunca todas a la vez.
- Cada fase tiene criterios de entrada, métricas mínimas y criterios de salida.

## 2) Pre-requisitos técnicos (antes de Día 1)

### Configuración y secretos
- Verificar variables en .env para Hyperliquid mainnet/testnet.
- Confirmar que HYPERLIQUID_USE_TESTNET esté correcto según fase.
- Validar wallet y signing key con prueba de conectividad en modo check-only.

### Estado de la app
- API levantada y saludable: /api/health = 200.
- Endpoints críticos OK: /api/bots, /api/stats, /api/positions, /api/orders, /api/bot-presets, /api/bot-advisor/analyze.
- Sin bots activos inesperados antes de iniciar fase.

### Base de datos y auditoría
- Backup de trading.db antes del cutover.
- Verificar persistencia de order_log y positions.
- Confirmar carpeta reports operativa y con permisos de escritura.

## 3) Fase 0 - Día 1 (Shadow + Paper en producción)

Duración recomendada: 24 horas.

### Objetivo
- Validar estabilidad del runtime en entorno productivo sin riesgo de capital real.

### Ejecución
- Activar 2 bots en paper con símbolos líquidos (ejemplo BTC/USDT y ETH/USDT).
- Ejecutar monitor de sesión larga (15 min por bloque, repetido en jornada).
- Usar asesor de bots para confirmar coherencia de recomendaciones por horizonte.

### Límites
- Executor: paper.
- Apalancamiento real: 0.
- Sin auto-start de bots en restart hasta validar.

### Criterios de éxito
- Uptime API > 99% en jornada.
- 0 errores críticos de ejecución.
- Sin fugas de sesión de exchange en logs relevantes.

## 4) Fase 1 - Día 2 (Testnet Realista + Dry Run Operativo)

Duración recomendada: 1 día.

### Objetivo
- Ensayar operación completa como si fuera real, pero en testnet.

### Ejecución
- Lanzar 3-4 bots con combinaciones de estrategia:
  - 1 grid_trading
  - 1 technical_pro
  - 1 ema_cross
  - opcional 1 dynamic_reinvest
- Probar ciclo completo:
  - guardar en cápsula
  - restaurar + iniciar
  - stop
  - archive
  - auto-ejecución advisor

### Criterios de éxito
- Todos los flujos UI/API funcionales sin intervención manual en DB.
- Reportes generados correctamente en reports/.
- Estado de bots consistente entre Mis Bots y Cápsula.

## 5) Fase 2 - Día 3 (Producción real con capital mínimo)

Duración recomendada: 1 día.

### Objetivo
- Primera exposición real limitada para validar ejecución de órdenes y latencia.

### Ejecución
- 1 bot real inicialmente (executor hyperliquid).
- Capital máximo por bot: 1% a 2% del capital total disponible.
- Apalancamiento conservador (por ejemplo 2x-3x).
- Priorizar strategy de menor frecuencia (ema_cross o technical_pro conservador).

### Guardrails
- Kill switch global probado al inicio del día.
- Stop manual definido (persona responsable + tiempo máximo de reacción).
- Ventana de operación limitada (ejemplo 2-4 horas iniciales).

### Criterios de éxito
- Órdenes reales ejecutadas y registradas correctamente.
- Conciliación posiciones API vs exchange sin desvíos.
- Fee y pnl coherentes con expected.

## 6) Fase 3 - Semana 1 (Escalado gradual)

### Escalado recomendado
- Día 4-5: 2 bots reales.
- Día 6-7: 3-4 bots reales, aumentando capital por pasos de 25% respecto al día anterior.

### Regla de escalado
- Solo escalar si se cumplen 3 condiciones:
  - sin incidentes críticos en 24h,
  - reconciliación correcta de posiciones,
  - drawdown intradía dentro del límite definido.

## 7) Métricas de go/no-go diarias

- Salud sistema: /api/health, errores 5xx, reconexiones.
- Trading: trades_delta, net_pnl, fees, win_rate.
- Riesgo: drawdown, exposición abierta, número de órdenes abiertas.
- Operación: coherencia estados bots (running/stopped, archived/no archived).

## 8) Plan de rollback (obligatorio)

Ante cualquier incidente crítico:
1. Activar kill switch.
2. Stop de todos los bots.
3. Deshabilitar auto-start temporal.
4. Exportar evidencia (logs + reportes + estado bots/positions).
5. Volver a modo paper o testnet.
6. Abrir postmortem con causa raíz y acción correctiva.

## 9) Checklist operativo diario (rápido)

### Antes de abrir
- API saludable.
- Bots esperados en estado correcto.
- Límites de riesgo cargados.
- Credenciales válidas y entorno correcto (testnet/mainnet).

### Durante sesión
- Monitoreo cada 15 min de stats, positions y orders.
- Revisión de desviaciones de pnl/fees.
- Verificación de latencia y rechazos de orden.

### Cierre de sesión
- Stop o continuidad según fase.
- Exportar reportes.
- Registrar resumen diario (incidencias y decisiones).

## 10) Recomendación final

- Estado actual: listo para despliegue por fases con control estricto.
- No recomendado pasar a escalado agresivo hasta completar al menos 72h de operación sin incidentes críticos.
