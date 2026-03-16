// Dashboard Application Logic

const LOCAL_API_ORIGIN = 'http://127.0.0.1:8000';
const shouldUseLocalApiOrigin = !(window.location.hostname === '127.0.0.1' || window.location.hostname === 'localhost')
    || window.location.port !== '8000';

if (typeof window !== 'undefined' && typeof window.fetch === 'function') {
    const originalFetch = window.fetch.bind(window);
    window.fetch = (resource, init) => {
        if (!shouldUseLocalApiOrigin || typeof resource !== 'string') {
            return originalFetch(resource, init);
        }

        if (resource.startsWith('/')) {
            return originalFetch(`${LOCAL_API_ORIGIN}${resource}`, init);
        }

        return originalFetch(resource, init);
    };
}

// Global helper to close modal - placed outside DOMContentLoaded for global access
window.closeCreateBotModal = function () {
    console.log("EXEC_CLOSE_MODAL"); // Log for subagent monitoring
    const modal = document.getElementById('createBotModal');
    if (modal) {
        modal.style.display = 'none';
    } else {
        // Fallback for different DOM structure/ID
        const overlay = document.querySelector('.modal-overlay#createBotModal');
        if (overlay) overlay.style.display = 'none';
    }

    // Safety: close any other overlays found
    document.querySelectorAll('.modal-overlay').forEach(o => o.style.display = 'none');
};

document.addEventListener('DOMContentLoaded', () => {
    console.log('Antigravity Dashboard Initialized');

    // UI Elements
    const botTableBody = document.getElementById('botTableBody');
    const vaultTableBody = document.getElementById('vaultTableBody');
    const killSwitchBtn = document.getElementById('killSwitchBtn');

    // Tab Switching Logic
    const navLinks = document.querySelectorAll('.nav-link, .profile-circle[data-tab]');
    const sections = document.querySelectorAll('.tab-content');
    const sectionTitle = document.getElementById('sectionTitle');
    const sectionSubtitle = document.getElementById('sectionSubtitle');
    const sidebar = document.querySelector('.sidebar');
    const menuToggle = document.getElementById('menuToggle');
    const sidebarOverlay = document.getElementById('sidebarOverlay');
    const previewPopup = document.getElementById('previewPopup');
    const previewCanvas = document.getElementById('previewCanvas');
    const previewTitle = document.getElementById('previewTitle');
    const previewStats = document.getElementById('previewStats');
    const fieldSelectorModal = document.getElementById('fieldSelectorModal');
    const fieldOptions = document.getElementById('fieldOptions');
    const closeFieldModal = document.getElementById('closeFieldModal');
    const saveFields = document.getElementById('saveFields');
    const newBotPreset = document.getElementById('newBotPreset');
    const presetQuickDoc = document.getElementById('presetQuickDoc');
    const advisorResults = document.getElementById('advisorResults');
    const newBotPrompt = document.getElementById('newBotPrompt');
    const generateBotFromTextBtn = document.getElementById('generateBotFromTextBtn');
    const botPromptStatus = document.getElementById('botPromptStatus');
    const botFilterSearch = document.getElementById('botFilterSearch');
    const botFilterStrategy = document.getElementById('botFilterStrategy');
    const botFilterStatus = document.getElementById('botFilterStatus');
    const compareSymbolAInput = document.getElementById('compareSymbolA');
    const compareSymbolBInput = document.getElementById('compareSymbolB');
    const comparePriceA = document.getElementById('comparePriceA');
    const comparePriceB = document.getElementById('comparePriceB');
    const compareResultA = document.getElementById('compareResultA');
    const compareResultB = document.getElementById('compareResultB');
    const compareLastUpdate = document.getElementById('compareLastUpdate');
    const refreshMainnetVisualBtn = document.getElementById('refreshMainnetVisualBtn');
    const mainnetVisualHeader = document.getElementById('mainnetVisualHeader');
    const mainnetVisualGrid = document.getElementById('mainnetVisualGrid');
    const mainnetVisualDetail = document.getElementById('mainnetVisualDetail');
    const testInsightsContent = document.getElementById('testInsightsContent');
    const refreshTestInsights = document.getElementById('refreshTestInsights');
    const testInsightsWindow = document.getElementById('testInsightsWindow');
    const testInsightsMinTrades = document.getElementById('testInsightsMinTrades');
    const intelligenceTopSummary = document.getElementById('intelligenceTopSummary');
    const intelligenceTopTableBody = document.getElementById('intelligenceTopTableBody');
    const refreshIntelligenceTop = document.getElementById('refreshIntelligenceTop');
    const botTrafficLightHeader = document.getElementById('botTrafficLightHeader');
    const botTrafficLightSummary = document.getElementById('botTrafficLightSummary');
    const botTrafficLightList = document.getElementById('botTrafficLightList');
    const toggleRuntimeOpsOverviewBtn = document.getElementById('toggleRuntimeOpsOverviewBtn');
    const runtimeOpsOverviewStatus = document.getElementById('runtimeOpsOverviewStatus');
    const settingsWalletAddressInput = document.getElementById('settingsWalletAddress');
    const settingsSigningKeyInput = document.getElementById('settingsSigningKey');
    const settingsUseTestnetSelect = document.getElementById('settingsUseTestnet');
    const settingsStatus = document.getElementById('settingsStatus');
    const saveHyperliquidSettingsBtn = document.getElementById('saveHyperliquidSettingsBtn');
    const runtimeOpsStatus = document.getElementById('runtimeOpsStatus');
    const refreshRuntimeOpsBtn = document.getElementById('refreshRuntimeOpsBtn');
    const startRuntimeOpsBtn = document.getElementById('startRuntimeOpsBtn');
    const stopRuntimeOpsBtn = document.getElementById('stopRuntimeOpsBtn');
    const takeProfitAdaptiveStatus = document.getElementById('takeProfitAdaptiveStatus');
    const refreshTakeProfitAdaptiveBtn = document.getElementById('refreshTakeProfitAdaptiveBtn');
    const asset30dSymbol = document.getElementById('asset30dSymbol');
    const asset30dTimeframe = document.getElementById('asset30dTimeframe');
    const asset30dSource = document.getElementById('asset30dSource');
    const asset30dAllocation = document.getElementById('asset30dAllocation');
    const asset30dAnalyzeBtn = document.getElementById('asset30dAnalyzeBtn');
    const asset30dRecommendBtn = document.getElementById('asset30dRecommendBtn');
    const asset30dStatus = document.getElementById('asset30dStatus');
    const asset30dMetrics = document.getElementById('asset30dMetrics');
    const asset30dAdvisor = document.getElementById('asset30dAdvisor');
    const microScalpSymbol = document.getElementById('microScalpSymbol');
    const microScalpAllocation = document.getElementById('microScalpAllocation');
    const microScalpCreateBtn = document.getElementById('microScalpCreateBtn');
    const microScalpStatus = document.getElementById('microScalpStatus');

    let botPresets = [];
    let advisorMap = {};
    let assetAdvisorMap = {};

    // Custom Confirmation Modal Elements
    const customConfirmModal = document.getElementById('customConfirmModal');
    const confirmTitle = document.getElementById('confirmTitle');
    const confirmMessage = document.getElementById('confirmMessage');
    const cancelConfirm = document.getElementById('cancelConfirm');
    const executeConfirm = document.getElementById('executeConfirm');
    let confirmCallback = null;

    function showCustomConfirm(title, message, callback) {
        if (!customConfirmModal) return;
        confirmTitle.innerText = title;
        confirmMessage.innerText = message;
        confirmCallback = callback;
        customConfirmModal.style.display = 'flex';
    }

    if (cancelConfirm) {
        cancelConfirm.addEventListener('click', () => {
            customConfirmModal.style.display = 'none';
            confirmCallback = null;
        });
    }

    if (executeConfirm) {
        executeConfirm.addEventListener('click', () => {
            if (confirmCallback) confirmCallback();
            customConfirmModal.style.display = 'none';
            confirmCallback = null;
        });
    }

    function choosePriceDecimals(price) {
        if (!Number.isFinite(price) || price <= 0) return 6;
        if (price >= 1000) return 2;
        if (price >= 100) return 3;
        if (price >= 1) return 4;
        return 6;
    }

    async function autoPopulateGridLimits(force = false) {
        const strategy = document.getElementById('newBotStrategy')?.value;
        if (strategy !== 'grid_trading') return;

        const symbolInput = document.getElementById('newBotSymbol');
        const upperInput = document.getElementById('newBotUpperLimit');
        const lowerInput = document.getElementById('newBotLowerLimit');
        const gridsInput = document.getElementById('newBotNumGrids');
        const hint = document.getElementById('gridAutoHint');

        if (!symbolInput || !upperInput || !lowerInput) return;

        const currentUpper = Number(upperInput.value || 0);
        const currentLower = Number(lowerInput.value || 0);
        const shouldFill = force || !(currentUpper > 0 && currentLower > 0 && currentUpper > currentLower);
        if (!shouldFill) return;

        const fetchSymbol = normalizeSymbolForMarketData(symbolInput.value);
        if (hint) hint.textContent = `Calculando rango automático para ${fetchSymbol}...`;

        try {
            const response = await fetch('/api/market/data/fetch', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    symbol: fetchSymbol,
                    timeframe: '1h',
                    source: 'live',
                    limit: 120
                })
            });

            if (!response.ok) {
                const err = await response.json();
                throw new Error(err.detail || 'No se pudo obtener mercado en vivo');
            }

            const data = await response.json();
            const candles = Array.isArray(data.candles) ? data.candles : [];
            if (!candles.length) {
                throw new Error('Sin velas disponibles para calcular límites');
            }

            const closes = candles.map((c) => Number(c.close || 0)).filter((x) => x > 0);
            const highs = candles.map((c) => Number(c.high || 0));
            const lows = candles.map((c) => Number(c.low || 0));
            if (!closes.length) {
                throw new Error('Datos de cierre inválidos');
            }

            const last = closes[closes.length - 1];
            const mean = closes.reduce((acc, val) => acc + val, 0) / closes.length;
            const center = (last * 0.7) + (mean * 0.3);

            const ranges = highs
                .map((high, idx) => {
                    const low = lows[idx] || 0;
                    const base = closes[idx] || 0;
                    if (high <= 0 || low <= 0 || base <= 0) return 0;
                    return Math.max(0, (high - low) / base);
                })
                .filter((x) => x > 0);

            const avgRange = ranges.length
                ? (ranges.reduce((acc, val) => acc + val, 0) / ranges.length)
                : 0.01;

            const bandPct = Math.max(0.05, Math.min(0.22, avgRange * 6));
            const upper = center * (1 + bandPct);
            const lower = center * (1 - bandPct);
            const decimals = choosePriceDecimals(center);

            upperInput.value = upper.toFixed(decimals);
            lowerInput.value = lower.toFixed(decimals);

            if (gridsInput) {
                const suggestedGrids = bandPct >= 0.14 ? 14 : bandPct >= 0.09 ? 12 : 10;
                gridsInput.value = String(suggestedGrids);
            }

            if (hint) {
                const volatilityPct = (bandPct * 100).toFixed(2);
                hint.textContent = `Auto para ${fetchSymbol}: precio ${last.toFixed(decimals)} · rango ±${volatilityPct}% (${data.source || 'live'}).`;
            }
        } catch (error) {
            console.error('Grid auto limits error:', error);
            if (hint) hint.textContent = `No se pudo auto-calcular para ${fetchSymbol}: ${error.message}`;
        }
    }

    function toNumber(value, fallback = 0) {
        const parsed = Number(value);
        return Number.isFinite(parsed) ? parsed : fallback;
    }

    function getMarginRiskMeta(marginUsagePct) {
        if (marginUsagePct >= 70) {
            return { color: 'var(--accent-ruby)', label: 'RIESGO ALTO' };
        }
        if (marginUsagePct >= 35) {
            return { color: 'var(--accent-blue)', label: 'RIESGO MEDIO' };
        }
        return { color: 'var(--accent-emerald)', label: 'RIESGO BAJO' };
    }

    let comparisonInterval = null;

    function stopComparisonAutoRefresh() {
        if (comparisonInterval) {
            clearInterval(comparisonInterval);
            comparisonInterval = null;
        }
    }

    async function fetchComparisonPrice(symbol) {
        const response = await fetch('/api/market/data/fetch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                symbol,
                timeframe: '1m',
                source: 'live',
                limit: 2,
            })
        });

        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || `No se pudo obtener precio para ${symbol}`);
        }

        const payload = await response.json();
        const candles = Array.isArray(payload.candles) ? payload.candles : [];
        const lastClose = Number(candles.at(-1)?.close);
        if (!Number.isFinite(lastClose) || lastClose <= 0) {
            throw new Error(`Sin precio válido para ${symbol}`);
        }

        return {
            price: lastClose,
            source: payload.source || 'live',
        };
    }

    async function refreshComparisonPrices(showAlerts = false) {
        if (!compareSymbolAInput || !compareSymbolBInput) return;

        const symbolA = (compareSymbolAInput.value || 'BTC/USDT').trim().toUpperCase();
        const symbolB = (compareSymbolBInput.value || 'ETH/USDT').trim().toUpperCase();

        const updateBox = (target, color, text) => {
            if (!target) return;
            target.style.borderColor = color;
            const stat = target.querySelector('.stat-subtitle');
            if (stat) stat.textContent = text;
        };

        try {
            const [a, b] = await Promise.all([
                fetchComparisonPrice(symbolA),
                fetchComparisonPrice(symbolB)
            ]);

            if (comparePriceA) comparePriceA.textContent = a.price.toFixed(4);
            if (comparePriceB) comparePriceB.textContent = b.price.toFixed(4);

            updateBox(compareResultA, 'rgba(56,189,248,0.55)', `${symbolA} · ${a.source}`);
            updateBox(compareResultB, 'rgba(16,185,129,0.55)', `${symbolB} · ${b.source}`);

            if (compareLastUpdate) {
                compareLastUpdate.textContent = `Última actualización: ${new Date().toLocaleTimeString()}`;
            }
        } catch (error) {
            console.error('Comparison refresh error:', error);
            if (compareLastUpdate) {
                compareLastUpdate.textContent = `Última actualización: error (${error.message})`;
            }
            updateBox(compareResultA, 'rgba(239,68,68,0.45)', 'Error de actualización');
            updateBox(compareResultB, 'rgba(239,68,68,0.45)', 'Error de actualización');
            if (showAlerts) {
                alert(`No se pudo actualizar comparación: ${error.message}`);
            }
        }
    }

    function startComparisonAutoRefresh() {
        stopComparisonAutoRefresh();
        refreshComparisonPrices(false);
        comparisonInterval = setInterval(() => {
            refreshComparisonPrices(false);
        }, 15000);
    }

    function renderSettingsStatus(checks, saved = false, useTestnet = true) {
        if (!settingsStatus || !checks) return;
        const ready = !!checks.ready_for_real_market;
        const authOk = !!checks.mainnet_auth_ok;
        const selectedEnv = String(checks.selected_env || (useTestnet ? 'testnet' : 'mainnet')).toLowerCase();
        const selectedEnvLabel = selectedEnv.toUpperCase();
        const selectedValueFallback = selectedEnv === 'testnet'
            ? checks.testnet_account_value
            : checks.mainnet_account_value;
        const selectedWithdrawableFallback = selectedEnv === 'testnet'
            ? checks.testnet_withdrawable
            : checks.mainnet_withdrawable;
        const selectedMarginUsedFallback = selectedEnv === 'testnet'
            ? checks.testnet_margin_used
            : checks.mainnet_margin_used;
        const selectedMarginUsagePctFallback = selectedEnv === 'testnet'
            ? checks.testnet_margin_usage_pct
            : checks.mainnet_margin_usage_pct;
        const selectedAccountValue = toNumber(checks.selected_env_account_value, toNumber(selectedValueFallback, 0));
        const selectedWithdrawable = toNumber(checks.selected_env_withdrawable, toNumber(selectedWithdrawableFallback, 0));
        const selectedMarginUsed = toNumber(checks.selected_env_margin_used, toNumber(selectedMarginUsedFallback, 0));
        const selectedMarginUsagePct = toNumber(
            checks.selected_env_margin_usage_pct,
            toNumber(selectedMarginUsagePctFallback, selectedAccountValue > 0 ? (selectedMarginUsed / selectedAccountValue) * 100 : 0)
        );
        const selectedRiskMeta = getMarginRiskMeta(selectedMarginUsagePct);
        const selectedAccountError = checks.selected_env_account_error || '';
        const testnetValue = toNumber(checks.testnet_account_value, 0);
        const mainnetValue = toNumber(checks.mainnet_account_value, 0);
        const mainnetWithdrawable = toNumber(checks.mainnet_withdrawable, 0);
        const mainnetMarginUsed = toNumber(checks.mainnet_margin_used, 0);
        const marginUsagePct = toNumber(checks.mainnet_margin_usage_pct, mainnetValue > 0 ? (mainnetMarginUsed / mainnetValue) * 100 : 0);
        const riskMeta = getMarginRiskMeta(marginUsagePct);
        const authError = checks.mainnet_auth_error || checks.selected_env_auth_error || '';
        const title = ready ? '✅ Listo para mercado real' : '⚠️ No listo para mercado real';
        const savedLine = saved ? 'Configuración guardada correctamente. ' : '';

        settingsStatus.innerHTML = [
            `<strong>${title}</strong>`,
            `<div style="margin-top: 6px;">${savedLine}Auth mainnet: ${authOk ? 'OK' : 'ERROR'}</div>`,
            `<div><strong>Saldo billetera conectada (${selectedEnvLabel}):</strong> $${selectedAccountValue.toFixed(2)}</div>`,
            `<div>${selectedEnvLabel} disponible: $${selectedWithdrawable.toFixed(2)} | Margen en uso: $${selectedMarginUsed.toFixed(2)} | <span style="color:${selectedRiskMeta.color}; font-weight:700;">${selectedMarginUsagePct.toFixed(2)}% (${selectedRiskMeta.label})</span></div>`,
            `<div>Saldo testnet: $${testnetValue.toFixed(2)} | Saldo mainnet: $${mainnetValue.toFixed(2)}</div>`,
            `<div>Mainnet disponible: $${mainnetWithdrawable.toFixed(2)} | Margen en uso: $${mainnetMarginUsed.toFixed(2)} | <span style="color:${riskMeta.color}; font-weight:700;">${marginUsagePct.toFixed(2)}% (${riskMeta.label})</span></div>`,
            selectedAccountError ? `<div style="color: #facc15; margin-top: 4px;">${selectedEnvLabel}: no se pudo leer equity (${selectedAccountError})</div>` : '',
            authError ? `<div style="color: var(--accent-ruby); margin-top: 4px;">${authError}</div>` : ''
        ].join('');
    }

    async function loadHyperliquidSettings() {
        if (!settingsStatus) return;
        settingsStatus.textContent = 'Estado: cargando configuración...';
        try {
            const response = await fetch('/api/settings/hyperliquid');
            if (!response.ok) {
                const err = await response.json();
                throw new Error(err.detail || 'No se pudo cargar la configuración');
            }
            const data = await response.json();
            if (settingsWalletAddressInput) {
                settingsWalletAddressInput.value = data.wallet_address || '';
                settingsWalletAddressInput.placeholder = data.wallet_masked || '0x...';
            }
            if (settingsSigningKeyInput) {
                settingsSigningKeyInput.value = '';
                settingsSigningKeyInput.placeholder = data.signing_key_present ? '******** (guardada)' : '0x...';
            }
            if (settingsUseTestnetSelect) {
                settingsUseTestnetSelect.value = data.use_testnet ? 'true' : 'false';
            }
            renderSettingsStatus(data.checks, false, !!data.use_testnet);
        } catch (error) {
            console.error('Error loading Hyperliquid settings:', error);
            settingsStatus.textContent = 'Error cargando ajustes: ' + error.message;
        }
    }

    async function saveHyperliquidSettings() {
        if (!saveHyperliquidSettingsBtn || !settingsStatus) return;

        const wallet = (settingsWalletAddressInput?.value || '').trim();
        const signingKey = (settingsSigningKeyInput?.value || '').trim();
        const useTestnet = (settingsUseTestnetSelect?.value || 'true') === 'true';

        if (!wallet) {
            alert('Debes informar la wallet de Hyperliquid.');
            return;
        }
        if (!signingKey) {
            alert('Debes informar la signing key para guardar y validar.');
            return;
        }

        saveHyperliquidSettingsBtn.disabled = true;
        const previousText = saveHyperliquidSettingsBtn.textContent;
        saveHyperliquidSettingsBtn.textContent = 'GUARDANDO...';
        settingsStatus.textContent = 'Guardando y validando credenciales...';

        try {
            const response = await fetch('/api/settings/hyperliquid/save', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    wallet_address: wallet,
                    signing_key: signingKey,
                    use_testnet: useTestnet
                })
            });

            if (!response.ok) {
                const err = await response.json();
                throw new Error(err.detail || 'No se pudo guardar configuración');
            }

            const data = await response.json();
            if (settingsSigningKeyInput) {
                settingsSigningKeyInput.value = '';
                settingsSigningKeyInput.placeholder = '******** (guardada)';
            }
            renderSettingsStatus(data.checks, true, !!data.use_testnet);
        } catch (error) {
            console.error('Error saving Hyperliquid settings:', error);
            settingsStatus.textContent = 'Error guardando ajustes: ' + error.message;
            alert('Error guardando ajustes: ' + error.message);
        } finally {
            saveHyperliquidSettingsBtn.disabled = false;
            saveHyperliquidSettingsBtn.textContent = previousText;
        }
    }

    function renderRuntimeOpsStatus(paperStatus, orchestratorStatus) {
        const paperRunning = !!paperStatus?.running;
        const orchestratorRunning = !!orchestratorStatus?.running;
        const opsRunning = paperRunning && orchestratorRunning;
        const paperColor = paperRunning ? 'var(--accent-emerald)' : 'var(--accent-ruby)';
        const orchColor = orchestratorRunning ? 'var(--accent-emerald)' : 'var(--accent-ruby)';
        const agg = paperStatus?.aggregate || {};

        if (runtimeOpsStatus) {
            runtimeOpsStatus.innerHTML = [
                `<div><strong>Monitor paper:</strong> <span style="color:${paperColor}; font-weight:700;">${paperRunning ? 'ACTIVO' : 'PARADO'}</span> · intervalo ${paperStatus?.interval_sec ?? '-'}s · prefijo ${paperStatus?.prefix || '-'}</div>`,
                `<div style="margin-top:4px;"><strong>Orquestador:</strong> <span style="color:${orchColor}; font-weight:700;">${orchestratorRunning ? 'ACTIVO' : 'PARADO'}</span> · intervalo ${orchestratorStatus?.interval_sec ?? '-'}s</div>`,
                `<div style="margin-top:4px; color: var(--text-muted);">Trades: ${agg?.trades ?? '-'} · WinRate: ${agg?.win_rate ?? '-'} · Net: ${agg?.net ?? '-'}</div>`
            ].join('');
        }

        if (runtimeOpsOverviewStatus) {
            runtimeOpsOverviewStatus.innerHTML = `
                <strong>Operación automática:</strong>
                <span style="color:${opsRunning ? 'var(--accent-emerald)' : 'var(--accent-ruby)'}; font-weight:700;">${opsRunning ? 'ACTIVA' : 'PARADA'}</span>
                · Monitor: ${paperRunning ? 'ON' : 'OFF'} · Orquestador: ${orchestratorRunning ? 'ON' : 'OFF'}
                <span style="color: var(--text-muted);"> · Trades ${agg?.trades ?? '-'} · Net ${agg?.net ?? '-'}</span>
            `;
        }

        if (toggleRuntimeOpsOverviewBtn) {
            toggleRuntimeOpsOverviewBtn.textContent = opsRunning ? 'MODO PRODUCCIÓN OFF' : 'MODO PRODUCCIÓN ON';
            toggleRuntimeOpsOverviewBtn.style.borderColor = opsRunning ? 'var(--accent-ruby)' : 'var(--accent-emerald)';
            toggleRuntimeOpsOverviewBtn.style.color = opsRunning ? 'var(--accent-ruby)' : 'var(--accent-emerald)';
        }
    }

    async function loadRuntimeOpsStatus() {
        if (!runtimeOpsStatus) return;
        runtimeOpsStatus.textContent = 'Estado: consultando operación automática...';
        try {
            const [paperRes, orchRes] = await Promise.all([
                fetch('/api/paper-monitor/status'),
                fetch('/api/autotrader/orchestrator/status')
            ]);

            if (!paperRes.ok) {
                const err = await paperRes.json();
                throw new Error(err.detail || 'No se pudo obtener estado del monitor paper');
            }
            if (!orchRes.ok) {
                const err = await orchRes.json();
                throw new Error(err.detail || 'No se pudo obtener estado del orquestador');
            }

            const paperStatus = await paperRes.json();
            const orchestratorStatus = await orchRes.json();
            renderRuntimeOpsStatus(paperStatus, orchestratorStatus);
        } catch (error) {
            console.error('Error loading runtime ops status:', error);
            runtimeOpsStatus.textContent = 'Error consultando estado: ' + error.message;
        }
    }

    function renderTakeProfitAdaptiveStatus(tpStatus) {
        if (!takeProfitAdaptiveStatus) return;

        const profile = String(tpStatus?.profile || 'manual').toUpperCase();
        const profileColor = profile === 'AUTO' ? 'var(--accent-emerald)' : 'var(--accent-blue)';
        const trackedCount = Number(tpStatus?.tracked_count || 0);
        const orchestratorRunning = !!tpStatus?.orchestrator_running;
        const tracked = Array.isArray(tpStatus?.tracked_positions) ? tpStatus.tracked_positions : [];
        const updatedAt = tpStatus?.timestamp ? new Date(tpStatus.timestamp).toLocaleTimeString() : '-';

        const topTracked = tracked.slice(0, 3).map((p) => {
            const gain = Number(p.last_gain_pct || 0);
            const retrace = Number(p.last_retrace_pct || 0);
            const gainColor = gain >= 0 ? 'var(--accent-emerald)' : 'var(--accent-ruby)';
            return `<div style="margin-top:4px;">• ${p.symbol || '-'} · ${p.side || '-'} · peak ${(Number(p.peak_gain_pct || 0) * 100).toFixed(2)}% · gain <span style="color:${gainColor};">${(gain * 100).toFixed(2)}%</span> · retrace ${(retrace * 100).toFixed(2)}%</div>`;
        }).join('');

        const stateInfo = tpStatus?.state_exists
            ? `state: ${tpStatus?.state_file || '-'} (${trackedCount} posiciones monitorizadas)`
            : `state: ${tpStatus?.state_file || '-'} (sin archivo aún)`;

        const readError = tpStatus?.state_read_error
            ? `<div style="margin-top:6px; color: var(--accent-ruby);">Error leyendo estado: ${tpStatus.state_read_error}</div>`
            : '';

        takeProfitAdaptiveStatus.innerHTML = [
            `<div><strong>Perfil activo:</strong> <span style="color:${profileColor}; font-weight:700;">${profile}</span> · Orquestador ${orchestratorRunning ? 'ON' : 'OFF'}</div>`,
            `<div style="margin-top:4px;"><strong>Thresholds:</strong> minNet $${Number(tpStatus?.min_net_pnl || 0).toFixed(2)} · hardTP ${(Number(tpStatus?.hard_take_profit_pct || 0) * 100).toFixed(2)}% · trigger ${(Number(tpStatus?.trailing_trigger_pct || 0) * 100).toFixed(2)}% · retrace ${(Number(tpStatus?.trailing_retrace_pct || 0) * 100).toFixed(2)}% · stopLoss ${(Number(tpStatus?.stop_loss_pct || 0) * 100).toFixed(2)}% · maxNetLoss $${Number(tpStatus?.max_net_loss_abs || 0).toFixed(2)}</div>`,
            `<div style="margin-top:4px;"><strong>Volatilidad:</strong> tf ${tpStatus?.volatility_timeframe || '-'} · lookback ${tpStatus?.volatility_lookback || '-'} · low ${(Number(tpStatus?.volatility_low_threshold_pct || 0) * 100).toFixed(3)}% · high ${(Number(tpStatus?.volatility_high_threshold_pct || 0) * 100).toFixed(3)}%</div>`,
            `<div style="margin-top:4px;"><strong>Ladder:</strong> ${tpStatus?.trailing_ladder || '-'}</div>`,
            `<div style="margin-top:4px;"><strong>Estado guard:</strong> ${stateInfo}</div>`,
            `<div style="margin-top:4px;"><strong>Top monitorizadas:</strong>${topTracked || '<div style="margin-top:4px; color: var(--text-muted);">Sin posiciones en state aún.</div>'}</div>`,
            `<div style="margin-top:6px; color: var(--text-muted);">Actualizado: ${updatedAt}</div>`,
            readError,
        ].join('');
    }

    async function loadTakeProfitAdaptiveStatus() {
        if (!takeProfitAdaptiveStatus) return;
        takeProfitAdaptiveStatus.textContent = 'Estado: consultando take profit adaptativo...';
        try {
            const res = await fetch('/api/take-profit/status', { cache: 'no-store' });
            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || 'No se pudo consultar estado de take profit');
            }
            const data = await res.json();
            renderTakeProfitAdaptiveStatus(data);
        } catch (error) {
            console.error('Error loading take profit adaptive status:', error);
            takeProfitAdaptiveStatus.textContent = 'Error consultando take profit adaptativo: ' + error.message;
        }
    }

    async function loadMainnetVisualControl() {
        if (!mainnetVisualHeader || !mainnetVisualGrid || !mainnetVisualDetail) return;

        mainnetVisualHeader.textContent = 'Cargando estado de producción...';
        try {
            const reqOpts = { cache: 'no-store' };
            const ts = Date.now();
            const [settingsRes, prodStatusRes, positionsRes, botsRes, alertsRes, runtimeRes] = await Promise.all([
                fetch('/api/settings/hyperliquid', reqOpts),
                fetch('/api/production/status', reqOpts),
                // Keep UI responsive by reading cached positions first.
                fetch(`/api/positions?sync=false&_ts=${ts}`, reqOpts),
                fetch('/api/bots', reqOpts),
                fetch('/api/production/alerts?limit=20&only_open=true', reqOpts),
                fetch('/api/autotrader/orchestrator/status', reqOpts)
            ]);

            if (!settingsRes.ok || !prodStatusRes.ok || !positionsRes.ok || !botsRes.ok || !alertsRes.ok || !runtimeRes.ok) {
                throw new Error('No se pudo cargar control mainnet');
            }

            const settings = await settingsRes.json();
            const prodStatus = await prodStatusRes.json();
            const positions = await positionsRes.json();
            const bots = await botsRes.json();
            const alerts = await alertsRes.json();
            const runtime = await runtimeRes.json();

            // Trigger exchange sync in background without blocking this render cycle.
            fetch(`/api/positions?sync=true&_ts=${ts}`, reqOpts).catch((syncError) => {
                console.warn('Background positions sync failed:', syncError);
            });

            const checks = settings?.checks || {};
            const selectedEnv = String(checks.selected_env || (settings?.use_testnet ? 'testnet' : 'mainnet')).toLowerCase();
            const selectedEnvLabel = selectedEnv.toUpperCase();
            const accountValue = toNumber(
                checks.selected_env_account_value,
                selectedEnv === 'testnet' ? checks.testnet_account_value : checks.mainnet_account_value
            );
            const availableCapitalRaw = toNumber(
                checks.selected_env_withdrawable,
                selectedEnv === 'testnet' ? checks.testnet_withdrawable : checks.mainnet_withdrawable
            );
            const availableCapital = Number.isFinite(availableCapitalRaw)
                ? availableCapitalRaw
                : Math.max(accountValue - toNumber(checks.selected_env_margin_used, 0), 0);
            const marginUsedRaw = toNumber(checks.selected_env_margin_used, NaN);
            const marginUsed = Number.isFinite(marginUsedRaw)
                ? marginUsedRaw
                : Math.max(accountValue - availableCapital, 0);
            const exposureNotional = toNumber(
                checks.selected_env_exposure_notional,
                selectedEnv === 'testnet' ? 0 : checks.mainnet_exposure_notional
            );
            const marginUsagePct = toNumber(checks.selected_env_margin_usage_pct, accountValue > 0 ? (marginUsed / accountValue) * 100 : 0);
            const riskMeta = getMarginRiskMeta(marginUsagePct);
            const authOk = !!checks.selected_env_auth_ok;
            const ready = !!checks.ready_for_real_market;

            const criticalOpen = Array.isArray(alerts)
                ? alerts.filter((a) => String(a.level || '').toLowerCase() === 'critical').length
                : 0;

            const liveBots = Array.isArray(bots)
                ? bots.filter((b) => {
                    const cfg = b.config || {};
                    return String(cfg.executor || '').toLowerCase() === 'hyperliquid' && !cfg.hyperliquid_testnet;
                })
                : [];
            const runningLiveBots = liveBots.filter((b) => String(b.status || '').toLowerCase() === 'running');

            const rawPositionsCount = Array.isArray(positions) ? positions.length : 0;
            const inferredOpenByExposure = selectedEnv === 'mainnet' && exposureNotional > 0 && rawPositionsCount === 0;
            const positionsCount = inferredOpenByExposure ? 1 : rawPositionsCount;
            const guardCount = Number(prodStatus?.count || 0);
            const runtimeRunning = !!runtime?.running;
            const noOpenPositions = positionsCount === 0;
            const updatedAt = new Date().toLocaleTimeString();

            const statusColor = ready ? 'var(--accent-emerald)' : 'var(--accent-ruby)';
            mainnetVisualHeader.innerHTML = `
                <strong>Billetera conectada (${selectedEnvLabel}):</strong>
                <span style="color:${statusColor}; font-weight:700;">${ready ? 'PREPARADA' : 'NO PREPARADA'}</span>
                · Auth ${selectedEnvLabel}: ${authOk ? 'OK' : 'ERROR'}
                · Equity: $${accountValue.toFixed(2)}
                · Disponible: $${availableCapital.toFixed(2)}
                · Margen uso: $${marginUsed.toFixed(2)}
                · <span style="color:${riskMeta.color}; font-weight:700;">Margen %: ${marginUsagePct.toFixed(2)}% (${riskMeta.label})</span>
                · Runtime: ${runtimeRunning ? 'ON' : 'OFF'}
                · Actualizado: ${updatedAt}
            `;

            mainnetVisualGrid.innerHTML = [
                `<div style="padding:10px; border:1px solid rgba(255,255,255,0.08); border-radius:10px; background: rgba(255,255,255,0.02);"><div style="font-size:0.68rem; color: var(--text-muted); text-transform: uppercase;">Capital Disponible</div><div style="font-size:1rem; font-weight:700; color:${availableCapital > 0 ? 'var(--accent-emerald)' : 'var(--text-secondary)'}; margin-top:4px;">$${availableCapital.toFixed(2)}</div><div style="font-size:0.68rem; color: var(--text-muted); margin-top:2px;">Withdrawable ${selectedEnvLabel}</div></div>`,
                `<div style="padding:10px; border:1px solid rgba(255,255,255,0.08); border-radius:10px; background: rgba(255,255,255,0.02);"><div style="font-size:0.68rem; color: var(--text-muted); text-transform: uppercase;">Margen en Uso</div><div style="font-size:1rem; font-weight:700; color:${marginUsed > 0 ? 'var(--accent-blue)' : 'var(--text-secondary)'}; margin-top:4px;">$${marginUsed.toFixed(2)}</div><div style="font-size:0.68rem; color: var(--text-muted); margin-top:2px;">Equity - disponible</div></div>`,
                `<div style="padding:10px; border:1px solid rgba(255,255,255,0.08); border-radius:10px; background: rgba(255,255,255,0.02);"><div style="font-size:0.68rem; color: var(--text-muted); text-transform: uppercase;">Posiciones Abiertas</div><div style="font-size:1rem; font-weight:700; color:${positionsCount > 0 ? 'var(--accent-emerald)' : 'var(--text-secondary)'}; margin-top:4px;">${positionsCount}</div><div style="font-size:0.68rem; color: var(--text-muted); margin-top:2px;">Exposición: $${exposureNotional.toFixed(2)}</div></div>`,
                `<div style="padding:10px; border:1px solid rgba(255,255,255,0.08); border-radius:10px; background: rgba(255,255,255,0.02);"><div style="font-size:0.68rem; color: var(--text-muted); text-transform: uppercase;">Alertas Críticas</div><div style="font-size:1rem; font-weight:700; color:${criticalOpen > 0 ? 'var(--accent-ruby)' : 'var(--accent-emerald)'}; margin-top:4px;">${criticalOpen}</div><div style="font-size:0.68rem; color: var(--text-muted); margin-top:2px;">Guard rows: ${guardCount}</div></div>`
            ].join('');

            const positionRows = (Array.isArray(positions) ? positions : []).slice(0, 3).map((p) => {
                const upnl = Number(p.unrealized_pnl || 0);
                return `<div style="margin-top:4px;">• ${p.symbol} · ${p.side} · qty ${Number(p.quantity || 0).toFixed(4)} · uPnL <span style="color:${upnl >= 0 ? 'var(--accent-emerald)' : 'var(--accent-ruby)'};">${upnl >= 0 ? '+' : ''}${upnl.toFixed(4)}</span></div>`;
            }).join('');

            const latestAlert = Array.isArray(alerts) && alerts.length > 0 ? alerts[0] : null;
            const latestAlertText = latestAlert
                ? `${latestAlert.level || '-'} · ${latestAlert.bot_id || '-'} · ${latestAlert.reason_code || '-'} · ${latestAlert.message || '-'}`
                : 'Sin alertas abiertas.';

            const noPositionsBadge = noOpenPositions
                ? `<div style="margin-top:8px; padding:8px 10px; border:1px solid rgba(250,204,21,0.55); border-radius:8px; color:#facc15; font-weight:700; text-transform:uppercase; letter-spacing:.03em;">Sin posiciones abiertas en ${selectedEnvLabel}</div>`
                : `<div style="margin-top:8px; padding:8px 10px; border:1px solid rgba(16,185,129,0.45); border-radius:8px; color:var(--accent-emerald); font-weight:700; text-transform:uppercase; letter-spacing:.03em;">${selectedEnvLabel} con posiciones activas</div>`;

            const inferredHint = inferredOpenByExposure
                ? '<div style="margin-top:6px; color:#facc15; font-size:0.72rem;">Posicion detectada por exposicion mainnet. Sincronizacion local en curso.</div>'
                : '';

            mainnetVisualDetail.innerHTML = `
                <div style="margin-bottom:4px;"><strong>Bots live:</strong> ${runningLiveBots.length}/${liveBots.length} running · hyperliquid ${selectedEnvLabel.toLowerCase()}</div>
                <div style="margin-bottom:4px;"><strong>Uso de margen:</strong> <span style="color:${riskMeta.color}; font-weight:700;">${marginUsagePct.toFixed(2)}% (${riskMeta.label})</span> del equity</div>
                <div><strong>Última alerta:</strong> ${latestAlertText}</div>
                ${noPositionsBadge}
                ${inferredHint}
                <div style="margin-top:6px;"><strong>Top posiciones:</strong>${positionRows || '<div style="margin-top:4px; color: var(--text-muted);">Sin detalle de posiciones (reintentando sync).</div>'}</div>
            `;
        } catch (error) {
            console.error('Error loading mainnet visual control:', error);
            const fallbackTime = new Date().toLocaleTimeString();
            mainnetVisualHeader.textContent = `Error cargando estado de producción en tiempo real (${fallbackTime}).`;
            mainnetVisualGrid.innerHTML = '<div style="padding:10px; border:1px solid rgba(239,68,68,0.45); border-radius:10px; color: var(--accent-ruby);">No se pudo consultar estado mainnet.</div>';
            mainnetVisualDetail.textContent = `Reintenta con ACTUALIZAR MAINNET. Detalle: ${error.message || 'sin detalle'}`;
        }
    }

    async function startRuntimeOps() {
        const hasSettingsBtn = !!startRuntimeOpsBtn;
        const hasOverviewBtn = !!toggleRuntimeOpsOverviewBtn;
        const prevSettings = hasSettingsBtn ? startRuntimeOpsBtn.textContent : '';
        const prevOverview = hasOverviewBtn ? toggleRuntimeOpsOverviewBtn.textContent : '';
        if (hasSettingsBtn) {
            startRuntimeOpsBtn.disabled = true;
            startRuntimeOpsBtn.textContent = 'INICIANDO...';
        }
        if (hasOverviewBtn) {
            toggleRuntimeOpsOverviewBtn.disabled = true;
            toggleRuntimeOpsOverviewBtn.textContent = 'INICIANDO...';
        }

        try {
            const paperResp = await fetch('/api/paper-monitor/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    hours: 2,
                    interval_sec: 120,
                    prefix: 'paper_lab_prod_ui'
                })
            });
            const orchResp = await fetch('/api/autotrader/orchestrator/start', { method: 'POST' });
            const autoActivateResp = await fetch('/api/monitoring/auto-activate-ready', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    lookback_hours: 24,
                    min_scored_trades: 8,
                    top_n: 10,
                    require_runtime_ready: false,
                    max_last_trade_age_hours: 24,
                    auto_patch_executor: true
                })
            });

            if (!paperResp.ok) {
                const err = await paperResp.json();
                throw new Error(err.detail || 'No se pudo iniciar monitor paper');
            }
            if (!orchResp.ok) {
                const err = await orchResp.json();
                throw new Error(err.detail || 'No se pudo iniciar orquestador');
            }

            let autoSummary = 'Autoactivación: sin respuesta';
            if (autoActivateResp.ok) {
                const autoData = await autoActivateResp.json();
                autoSummary = `Autoactivación producción: ${autoData.activated || 0} activados, ${autoData.blocked || 0} bloqueados, ${autoData.production_candidates_detected || 0} preparados detectados, ${autoData.skipped_not_running || 0} omitidos por no running, ${autoData.skipped_stale_trade || 0} omitidos por inactividad`;
            } else {
                let errDetail = '';
                try {
                    const err = await autoActivateResp.json();
                    errDetail = err.detail || '';
                } catch (_) {
                    errDetail = '';
                }
                autoSummary = `Autoactivación producción no completada${errDetail ? `: ${errDetail}` : ''}`;
            }

            await loadRuntimeOpsStatus();
            alert(`Operación automática iniciada desde la app.\n${autoSummary}`);
        } catch (error) {
            console.error('Error starting runtime ops:', error);
            alert('No se pudo iniciar operación automática: ' + error.message);
        } finally {
            if (hasSettingsBtn) {
                startRuntimeOpsBtn.disabled = false;
                startRuntimeOpsBtn.textContent = prevSettings;
            }
            if (hasOverviewBtn) {
                toggleRuntimeOpsOverviewBtn.disabled = false;
                toggleRuntimeOpsOverviewBtn.textContent = prevOverview;
            }
        }
    }

    async function stopRuntimeOps() {
        const hasSettingsBtn = !!stopRuntimeOpsBtn;
        const hasOverviewBtn = !!toggleRuntimeOpsOverviewBtn;
        const prevSettings = hasSettingsBtn ? stopRuntimeOpsBtn.textContent : '';
        const prevOverview = hasOverviewBtn ? toggleRuntimeOpsOverviewBtn.textContent : '';
        if (hasSettingsBtn) {
            stopRuntimeOpsBtn.disabled = true;
            stopRuntimeOpsBtn.textContent = 'PARANDO...';
        }
        if (hasOverviewBtn) {
            toggleRuntimeOpsOverviewBtn.disabled = true;
            toggleRuntimeOpsOverviewBtn.textContent = 'PARANDO...';
        }

        try {
            await fetch('/api/paper-monitor/stop', { method: 'POST' });
            await fetch('/api/autotrader/orchestrator/stop', { method: 'POST' });
            await loadRuntimeOpsStatus();
            alert('Operación automática detenida.');
        } catch (error) {
            console.error('Error stopping runtime ops:', error);
            alert('No se pudo detener operación automática: ' + error.message);
        } finally {
            if (hasSettingsBtn) {
                stopRuntimeOpsBtn.disabled = false;
                stopRuntimeOpsBtn.textContent = prevSettings;
            }
            if (hasOverviewBtn) {
                toggleRuntimeOpsOverviewBtn.disabled = false;
                toggleRuntimeOpsOverviewBtn.textContent = prevOverview;
            }
        }
    }

    async function toggleRuntimeOpsOverview() {
        try {
            const [paperRes, orchRes] = await Promise.all([
                fetch('/api/paper-monitor/status'),
                fetch('/api/autotrader/orchestrator/status')
            ]);

            if (!paperRes.ok || !orchRes.ok) {
                throw new Error('No se pudo consultar estado operativo');
            }

            const paperStatus = await paperRes.json();
            const orchestratorStatus = await orchRes.json();
            const running = !!paperStatus?.running && !!orchestratorStatus?.running;

            if (running) {
                await stopRuntimeOps();
            } else {
                await startRuntimeOps();
            }
        } catch (error) {
            console.error('Error toggling runtime ops from overview:', error);
            alert('No se pudo cambiar el modo producción: ' + error.message);
        }
    }

    const runComparisonBtn = document.getElementById('runComparisonBtn');
    if (runComparisonBtn) {
        runComparisonBtn.addEventListener('click', async () => {
            runComparisonBtn.innerText = 'ANALYZING...';
            runComparisonBtn.disabled = true;

            try {
                await refreshComparisonPrices(true);
            } finally {
                runComparisonBtn.innerText = 'EXECUTE SIDE-BY-SIDE ANALYSIS';
                runComparisonBtn.disabled = false;
            }
        });
    }

    if (compareSymbolAInput) {
        compareSymbolAInput.addEventListener('change', () => refreshComparisonPrices(false));
        compareSymbolAInput.addEventListener('blur', () => refreshComparisonPrices(false));
    }
    if (compareSymbolBInput) {
        compareSymbolBInput.addEventListener('change', () => refreshComparisonPrices(false));
        compareSymbolBInput.addEventListener('blur', () => refreshComparisonPrices(false));
    }

    // Launch from Comparison
    document.querySelectorAll('.launch-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const symbolInputId = btn.dataset.symbolId;
            const symbol = document.getElementById(symbolInputId).value;

            document.getElementById('newBotSymbol').value = symbol;
            createBotModal.style.display = 'flex';
        });
    });

    navLinks.forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            const targetId = link.dataset.tab;
            if (!targetId) return;

            // Update Navigation UI
            navLinks.forEach(l => l.classList.remove('active'));
            link.classList.add('active');

            // Update Content Visibility
            sections.forEach(section => {
                if (section.id === targetId) {
                    section.classList.add('active');
                    section.style.animation = 'fadeIn 0.5s ease-out forwards';
                } else {
                    section.classList.remove('active');
                }
            });

            // Update Header Title & Subtitle
            if (sectionTitle) {
                const titleMap = {
                    'overview': 'Panel de Inteligencia',
                    'bots': 'Flota de Bots',
                    'vault': 'Cámara de Seguridad',
                    'strategies': 'Configuración de Algoritmos',
                    'comparison': 'Análisis Comparativo',
                    'backtesting': 'Simulación Histórica',
                    'settings': 'Preferencias Globales'
                };
                const subtitleMap = {
                    'overview': 'Rendimiento institucional y monitorización de activos en tiempo real.',
                    'bots': 'Despliega y supervisa tu flota de algoritmos de alta frecuencia.',
                    'vault': 'Bots archivados y configuraciones de éxito para reutilización rápida.',
                    'strategies': 'Ajusta los parámetros técnicos de tus estrategias de trading.',
                    'comparison': 'Compara activos y lanza ejecuciones directas desde el análisis.',
                    'backtesting': 'Valida tus estrategias mediante simulaciones de mercado real.',
                    'settings': 'Gestión de credenciales de exchange y límites de riesgo global.'
                };
                sectionTitle.innerText = titleMap[targetId] || 'Dashboard';
                if (sectionSubtitle) sectionSubtitle.innerText = subtitleMap[targetId] || '';
            }

            if (window.lucide) lucide.createIcons();

            if (targetId === 'comparison') {
                startComparisonAutoRefresh();
            } else {
                stopComparisonAutoRefresh();
            }

            if (targetId === 'settings') {
                loadHyperliquidSettings();
                loadRuntimeOpsStatus();
            }

            if (targetId === 'overview') {
                loadMainnetVisualControl();
                fetchTestInsights();
            }

            // Close sidebar on mobile after navigation
            if (sidebar && sidebar.classList.contains('active')) {
                sidebar.classList.remove('active');
                if (sidebarOverlay) sidebarOverlay.classList.remove('active');
            }
        });
    });

    // Backtesting UI Logic
    const runBtBtn = document.getElementById('runBacktestBtn');
    const visualizeAssetDataBtn = document.getElementById('visualizeAssetDataBtn');
    const exportAssetDataBtn = document.getElementById('exportAssetDataBtn');
    const importAssetDataBtn = document.getElementById('importAssetDataBtn');
    const assetDataSource = document.getElementById('assetDataSource');
    const assetDataLimit = document.getElementById('assetDataLimit');
    const assetDataFormat = document.getElementById('assetDataFormat');
    const assetDataImportInput = document.getElementById('assetDataImportInput');
    const assetDataStatus = document.getElementById('assetDataStatus');
    if (runBtBtn) {
        runBtBtn.addEventListener('click', async () => {
            const symbol = document.getElementById('btSymbol').value;
            const timeframe = document.getElementById('btTimeframe').value;
            const strategy = document.getElementById('btStrategy').value;

            runBtBtn.innerText = 'Calculating Simulation...';
            runBtBtn.disabled = true;

            try {
                const response = await fetch('/api/backtest/run', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ symbol, timeframe, strategy, limit: 100 })
                });

                if (!response.ok) {
                    const errData = await response.json();
                    throw new Error(errData.detail || 'Server error during simulation');
                }

                const result = await response.json();
                displayBacktestResults(result);
            } catch (error) {
                console.error('Backtest error:', error);
                alert('Simulation failed: ' + error.message);
                // Reset results view if it was open
                document.getElementById('backtestResults').style.display = 'none';
            } finally {
                runBtBtn.innerText = 'RUN HISTORICAL SIMULATION';
                runBtBtn.disabled = false;
            }
        });
    }

    async function fetchAssetCandles() {
        const symbol = document.getElementById('btSymbol')?.value || 'BTC/USDT';
        const timeframe = document.getElementById('btTimeframe')?.value || '1h';
        const source = assetDataSource?.value || 'live';
        const limit = parseInt(assetDataLimit?.value || '300', 10);

        const response = await fetch('/api/market/data/fetch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ symbol, timeframe, source, limit })
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'No se pudieron cargar los datos del activo');
        }

        return response.json();
    }

    function renderAssetDataChart(payload) {
        const canvas = document.getElementById('assetDataChart');
        if (!canvas || !payload?.candles?.length) return;

        const ctx = canvas.getContext('2d');
        if (assetDataChart) assetDataChart.destroy();

        const labels = payload.candles.map((c) => new Date(c.time).toLocaleString());
        const prices = payload.candles.map((c) => c.close);

        assetDataChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels,
                datasets: [{
                    label: `${payload.symbol} close`,
                    data: prices,
                    borderColor: '#38bdf8',
                    backgroundColor: 'rgba(56, 189, 248, 0.12)',
                    fill: true,
                    tension: 0.2,
                    pointRadius: 0,
                    borderWidth: 2
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: true } },
                scales: {
                    x: { ticks: { color: 'rgba(255,255,255,0.5)', maxRotation: 45, minRotation: 45 } },
                    y: { ticks: { color: 'rgba(255,255,255,0.5)' } }
                }
            }
        });
    }

    function downloadTextFile(filename, content, mimeType) {
        const blob = new Blob([content], { type: mimeType });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
    }

    if (visualizeAssetDataBtn) {
        visualizeAssetDataBtn.addEventListener('click', async () => {
            try {
                visualizeAssetDataBtn.disabled = true;
                visualizeAssetDataBtn.textContent = 'CARGANDO...';
                const payload = await fetchAssetCandles();
                renderAssetDataChart(payload);
                if (assetDataStatus) {
                    assetDataStatus.textContent = `Visualización: ${payload.symbol} ${payload.timeframe} · fuente=${payload.source} · velas=${payload.rows}`;
                }
            } catch (error) {
                console.error('Asset data visualize error:', error);
                if (assetDataStatus) assetDataStatus.textContent = `Error visualizando datos: ${error.message}`;
                alert(`Error visualizando datos: ${error.message}`);
            } finally {
                visualizeAssetDataBtn.disabled = false;
                visualizeAssetDataBtn.textContent = 'VISUALIZAR DATOS';
            }
        });
    }

    if (exportAssetDataBtn) {
        exportAssetDataBtn.addEventListener('click', async () => {
            const symbol = document.getElementById('btSymbol')?.value || 'BTC/USDT';
            const timeframe = document.getElementById('btTimeframe')?.value || '1h';
            const source = assetDataSource?.value || 'live';
            const limit = parseInt(assetDataLimit?.value || '300', 10);
            const format = assetDataFormat?.value || 'json';

            try {
                exportAssetDataBtn.disabled = true;
                exportAssetDataBtn.textContent = 'EXPORTANDO...';
                const response = await fetch('/api/market/data/export', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ symbol, timeframe, source, limit, format })
                });

                if (!response.ok) {
                    const err = await response.json();
                    throw new Error(err.detail || 'No se pudo exportar');
                }

                const data = await response.json();
                const mime = data.format === 'csv' ? 'text/csv;charset=utf-8' : 'application/json;charset=utf-8';
                downloadTextFile(data.filename, data.content, mime);
                if (assetDataStatus) assetDataStatus.textContent = `Exportado: ${data.filename} (${data.rows} velas)`;
            } catch (error) {
                console.error('Asset data export error:', error);
                if (assetDataStatus) assetDataStatus.textContent = `Error exportando datos: ${error.message}`;
                alert(`Error exportando datos: ${error.message}`);
            } finally {
                exportAssetDataBtn.disabled = false;
                exportAssetDataBtn.textContent = 'EXPORTAR DATOS';
            }
        });
    }

    if (importAssetDataBtn) {
        importAssetDataBtn.addEventListener('click', async () => {
            const symbol = document.getElementById('btSymbol')?.value || 'BTC/USDT';
            const timeframe = document.getElementById('btTimeframe')?.value || '1h';
            const format = assetDataFormat?.value || 'json';
            const data = assetDataImportInput?.value || '';

            if (!data.trim()) {
                alert('Pega datos JSON o CSV en el cuadro de importación.');
                return;
            }

            try {
                importAssetDataBtn.disabled = true;
                importAssetDataBtn.textContent = 'IMPORTANDO...';
                const response = await fetch('/api/market/data/import', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ symbol, timeframe, format, data })
                });

                if (!response.ok) {
                    const err = await response.json();
                    throw new Error(err.detail || 'No se pudo importar');
                }

                const result = await response.json();
                if (assetDataStatus) {
                    assetDataStatus.textContent = `Importado: ${result.symbol} ${result.timeframe} · ${result.rows} velas`;
                }
            } catch (error) {
                console.error('Asset data import error:', error);
                if (assetDataStatus) assetDataStatus.textContent = `Error importando datos: ${error.message}`;
                alert(`Error importando datos: ${error.message}`);
            } finally {
                importAssetDataBtn.disabled = false;
                importAssetDataBtn.textContent = 'IMPORTAR DATOS';
            }
        });
    }

    // --- CHART INITIALIZATION ---
    let performanceChart;
    let backtestChart;
    let assetDataChart;
    let asset30dChart;
    let portfolioSparkline;
    let pnlSparkline;
    const dashboardState = {
        stats: null,
        trades: [],
        positions: []
    };

    function initCharts() {
        const perfCtx = document.getElementById('performanceChart')?.getContext('2d');
        if (perfCtx) {
            performanceChart = new Chart(perfCtx, {
                type: 'line',
                data: {
                    labels: [],
                    datasets: [{
                        label: 'PnL acumulado (últimas 50 operaciones)',
                        data: [],
                        borderColor: '#38bdf8',
                        backgroundColor: (context) => {
                            const ctx = context.chart.ctx;
                            const gradient = ctx.createLinearGradient(0, 0, 0, 300);
                            gradient.addColorStop(0, 'rgba(56, 189, 248, 0.2)');
                            gradient.addColorStop(1, 'rgba(56, 189, 248, 0)');
                            return gradient;
                        },
                        fill: true,
                        tension: 0.4,
                        borderWidth: 3,
                        pointRadius: 0,
                        pointHoverRadius: 6,
                        pointBackgroundColor: '#38bdf8'
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            backgroundColor: 'rgba(5, 7, 10, 0.9)',
                            titleFont: { family: 'Outfit', size: 14 },
                            bodyFont: { family: 'Inter', size: 12 },
                            padding: 12,
                            borderColor: 'rgba(255, 255, 255, 0.1)',
                            borderWidth: 1,
                            displayColors: false
                        }
                    },
                    scales: {
                        x: {
                            grid: { display: false },
                            ticks: { color: 'rgba(255,255,255,0.4)', font: { size: 10 } }
                        },
                        y: {
                            grid: { color: 'rgba(255,255,255,0.05)', drawBorder: false },
                            ticks: {
                                color: 'rgba(255,255,255,0.4)',
                                font: { size: 10 },
                                callback: (val) => '$' + Number(val).toLocaleString(undefined, { maximumFractionDigits: 2 })
                            }
                        }
                    }
                }
            });
        }

        const sparklineOptions = {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false }, tooltip: { enabled: false } },
            scales: { x: { display: false }, y: { display: false } },
            elements: { point: { radius: 0 } }
        };

        const portSparkCtx = document.getElementById('portfolioSparkline')?.getContext('2d');
        if (portSparkCtx) {
            portfolioSparkline = new Chart(portSparkCtx, {
                type: 'line',
                data: {
                    labels: [],
                    datasets: [{
                        data: [],
                        borderColor: '#38bdf8',
                        borderWidth: 1.5,
                        tension: 0.4
                    }]
                },
                options: sparklineOptions
            });
        }

        const pnlSparkCtx = document.getElementById('pnlSparkline')?.getContext('2d');
        if (pnlSparkCtx) {
            pnlSparkline = new Chart(pnlSparkCtx, {
                type: 'line',
                data: {
                    labels: [],
                    datasets: [{
                        data: [],
                        borderColor: '#10b981',
                        borderWidth: 1.5,
                        tension: 0.4
                    }]
                },
                options: sparklineOptions
            });
        }
    }

    initCharts();

    function displayBacktestResults(data) {
        const resultsDiv = document.getElementById('backtestResults');
        const metricsDiv = document.getElementById('btMetrics');
        const tradesDiv = document.getElementById('btTrades');

        resultsDiv.style.display = 'block';

        // Render Metrics
        metricsDiv.innerHTML = Object.entries(data.metrics).map(([key, val]) => `
            <div class="stat-card glass" style="text-align: center;">
                <div style="font-size: 0.7rem; color: var(--text-muted); text-transform: uppercase;">${key.replace('_', ' ')}</div>
                <div style="font-size: 1.2rem; font-weight: 700; color: var(--accent-blue);">${val}</div>
            </div>
        `).join('');

        // Render Equity Curve Chart
        const btCtx = document.getElementById('backtestChart').getContext('2d');
        if (backtestChart) backtestChart.destroy();

        // Calculate cumulative pnl for equity curve
        let currentEquity = 10000; // Mock initial capital
        const equityData = data.trades.reverse().map(t => {
            // Very simplified equity calculation for visualization
            const pnl = t.side === 'sell' ? (t.price * 0.01) : -(t.price * 0.01);
            currentEquity += pnl;
            return { x: new Date(t.time), y: currentEquity };
        });

        backtestChart = new Chart(btCtx, {
            type: 'line',
            data: {
                labels: equityData.map(d => d.x.toLocaleDateString()),
                datasets: [{
                    label: 'Equity',
                    data: equityData.map(d => d.y),
                    borderColor: '#38bdf8',
                    backgroundColor: 'rgba(56, 189, 248, 0.1)',
                    fill: true,
                    tension: 0.2,
                    borderWidth: 2,
                    pointRadius: 2
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    x: { grid: { display: false }, ticks: { color: 'rgba(255,255,255,0.5)', maxRotation: 45, minRotation: 45 } },
                    y: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: 'rgba(255,255,255,0.5)' } }
                }
            }
        });

        // Render Trades
        tradesDiv.innerHTML = `
            <table style="width: 100%; border-collapse: collapse; margin-top: 1rem;">
                <thead style="font-size: 0.75rem; color: var(--text-muted); text-align: left;">
                    <tr>
                        <th style="padding: 10px;">Time</th>
                        <th style="padding: 10px;">Side</th>
                        <th style="padding: 10px;">Price</th>
                    </tr>
                </thead>
                <tbody style="font-size: 0.85rem;">
                    ${data.trades.map(t => `
                        <tr style="border-top: 1px solid rgba(255,255,255,0.05);">
                            <td style="padding: 10px;">${new Date(t.time).toLocaleString()}</td>
                            <td style="padding: 10px; color: ${t.side === 'buy' ? 'var(--accent-blue)' : 'var(--accent-emerald)'}; font-weight: 600;">${t.side.toUpperCase()}</td>
                            <td style="padding: 10px;">$${t.price.toLocaleString()}</td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        `;
    }
    async function fetchBots() {
        try {
            const response = await fetch('/api/bots?include_system=false');
            const bots = await response.json();

            const isSystemManagedBot = (bot) => {
                const cfg = bot?.config || {};
                const managedBy = String(cfg.managed_by || '').trim().toLowerCase();
                const botId = String(bot?.id || '').trim().toUpperCase();
                return managedBy === 'adaptive_orchestrator' || botId.startsWith('AUTO-ADAPT-');
            };

            const activeBots = bots
                .filter(b => !b.is_archived && !isSystemManagedBot(b))
                .sort((a, b) => {
                    const aRunning = a.status === 'running' ? 1 : 0;
                    const bRunning = b.status === 'running' ? 1 : 0;
                    if (aRunning !== bRunning) return bRunning - aRunning;
                    return (a.id || '').localeCompare(b.id || '');
                });
            const archivedBots = bots.filter(b => b.is_archived && !isSystemManagedBot(b));
            const filteredActiveBots = activeBots.filter((bot) => {
                const searchTerm = String(botFilterSearch?.value || '').trim().toLowerCase();
                const strategyFilter = String(botFilterStrategy?.value || '').trim().toLowerCase();
                const statusFilter = String(botFilterStatus?.value || '').trim().toLowerCase();

                const botId = String(bot.id || '').toLowerCase();
                const botName = String((bot.id || '').split('_')[0] || '').toLowerCase();
                const botSymbol = String((bot.config || {}).symbol || bot.symbol || '').toLowerCase();
                const botStrategy = String(bot.strategy || '').toLowerCase();
                const botStatus = String(bot.status || '').toLowerCase();

                const matchesSearch = !searchTerm
                    || botId.includes(searchTerm)
                    || botName.includes(searchTerm)
                    || botSymbol.includes(searchTerm);
                const matchesStrategy = !strategyFilter || botStrategy === strategyFilter;
                const matchesStatus = !statusFilter || (statusFilter === 'running' ? botStatus === 'running' : botStatus !== 'running');

                return matchesSearch && matchesStrategy && matchesStatus;
            });

            const botManagerInfo = document.getElementById('botManagerInfo');
            const vaultManagerInfo = document.getElementById('vaultManagerInfo');
            if (botManagerInfo) {
                const runningCount = activeBots.filter(b => b.status === 'running').length;
                const waitingCount = activeBots.filter(b => b.status !== 'running').length;
                const activeIds = activeBots
                    .filter(b => b.status === 'running')
                    .map(b => b.id)
                    .slice(0, 3)
                    .join(', ');
                const activeTail = activeBots.filter(b => b.status === 'running').length > 3 ? '…' : '';
                botManagerInfo.textContent = `${filteredActiveBots.length} filtrados de ${activeBots.length} · ${runningCount} ACTIVOS · ${waitingCount} EN ESPERA${activeIds ? ` · Activos ahora: ${activeIds}${activeTail}` : ''}`;
            }
            if (vaultManagerInfo) {
                vaultManagerInfo.textContent = `${archivedBots.length} bots archivados en cápsula`;
            }

            updateBotTable(filteredActiveBots);
            updateVaultTable(archivedBots);
        } catch (error) {
            console.error('Error fetching bots:', error);
        }
    }

    function updateVaultTable(bots) {
        if (!vaultTableBody) return;

        if (!Array.isArray(bots) || bots.length === 0) {
            vaultTableBody.innerHTML = '<tr><td colspan="5" style="text-align: center; padding: 2rem; color: var(--text-muted);">Vault is empty.</td></tr>';
            return;
        }

        vaultTableBody.innerHTML = bots.map(bot => `
            <tr>
                <td style="padding: 1rem; border-bottom: 1px solid rgba(255,255,255,0.05);">${bot.id}</td>
                <td style="padding: 1rem; border-bottom: 1px solid rgba(255,255,255,0.05);"><span class="strategy-badge">${bot.strategy}</span></td>
                <td style="padding: 1rem; border-bottom: 1px solid rgba(255,255,255,0.05);">$${bot.config?.capital_allocation || bot.config?.allocation || bot.capital_allocation || 0}</td>
                <td style="padding: 1rem; border-bottom: 1px solid rgba(255,255,255,0.05);">${bot.status}</td>
                <td style="padding: 1rem; border-bottom: 1px solid rgba(255,255,255,0.05); text-align: right;">
                    <button class="glass restore-bot-btn" data-id="${bot.id}" style="padding: 5px; color: var(--accent-emerald); cursor: pointer; border: none;" title="Restore">
                        <i data-lucide="refresh-cw" style="width: 16px; height: 16px;"></i>
                    </button>
                    <button class="glass restore-start-bot-btn" data-id="${bot.id}" style="padding: 5px; color: var(--accent-blue); cursor: pointer; border: none;" title="Restore + Start">
                        <i data-lucide="play-circle" style="width: 16px; height: 16px;"></i>
                    </button>
                    <button class="glass delete-bot-btn" data-id="${bot.id}" style="padding: 5px; color: var(--accent-ruby); cursor: pointer; border: none;" title="Permanently Delete">
                        <i data-lucide="trash-2" style="width: 16px; height: 16px;"></i>
                    </button>
                </td>
            </tr>
        `).join('');

        if (window.lucide) lucide.createIcons();
    }

    function updateBotTable(bots) {
        if (!botTableBody) return;

        if (!Array.isArray(bots) || bots.length === 0) {
            botTableBody.innerHTML = '<tr><td colspan="9" style="text-align: center; padding: 2rem; color: var(--text-muted);">No hay bots en Mis Bots (activos o en espera).</td></tr>';
            return;
        }

        botTableBody.innerHTML = bots.map(bot => {
            const botTrades = dashboardState.trades.filter((trade) => trade.bot_id === bot.id);
            const botRealizedPnl = botTrades.reduce((acc, trade) => acc + (Number(trade.pnl) || 0), 0);
            const pnlColor = botRealizedPnl >= 0 ? 'var(--accent-emerald)' : 'var(--accent-ruby)';
            const pnlPrefix = botRealizedPnl >= 0 ? '+' : '';

            const scoredTrades = botTrades.filter((trade) => Number(trade.pnl) !== 0);
            const winningTrades = scoredTrades.filter((trade) => Number(trade.pnl) > 0).length;
            const successRate = scoredTrades.length > 0
                ? `${((winningTrades / scoredTrades.length) * 100).toFixed(1)}%`
                : 'N/D';

            const uptimeText = bot.status === 'running' ? 'En ejecución' : 'Detenido';

            return `
            <tr class="bot-row ${bot.status === 'running' ? 'bot-running' : 'bot-waiting'}" data-id="${bot.id}">
                <td style="padding: 1rem; border-bottom: 1px solid rgba(255,255,255,0.05);">${bot.id}</td>
                <td style="padding: 1rem; border-bottom: 1px solid rgba(255,255,255,0.05); font-weight: 500;">${bot.id.split('_')[0].toUpperCase()}</td>
                <td style="padding: 1rem; border-bottom: 1px solid rgba(255,255,255,0.05);"><span class="strategy-badge">${bot.strategy}</span></td>
                <td style="padding: 1rem; border-bottom: 1px solid rgba(255,255,255,0.05);">
                    <span class="status-pill ${bot.status === 'running' ? 'status-pill-active' : 'status-pill-waiting'}">
                        ${bot.status === 'running' ? 'ACTIVO' : 'EN ESPERA'}
                    </span>
                </td>
                <td style="padding: 1rem; border-bottom: 1px solid rgba(255,255,255,0.05);">$${bot.config?.capital_allocation || bot.config?.allocation || bot.capital_allocation || 0}</td>
                <td style="padding: 1rem; border-bottom: 1px solid rgba(255,255,255,0.05); color: ${pnlColor}; font-weight: 600;">${pnlPrefix}$${botRealizedPnl.toFixed(3)}</td>
                <td style="padding: 1rem; border-bottom: 1px solid rgba(255,255,255,0.05);">${uptimeText}</td>
                <td style="padding: 1rem; border-bottom: 1px solid rgba(255,255,255,0.05);">${successRate}</td>
                <td style="padding: 1rem; border-bottom: 1px solid rgba(255,255,255,0.05); text-align: right;">
                    <button class="glass bot-action" data-id="${bot.id}" data-running="${bot.status === 'running' ? 'true' : 'false'}" data-lucide="${bot.status === 'running' ? 'pause-circle' : 'play-circle'}" style="padding: 5px; color: ${bot.status === 'running' ? 'var(--accent-ruby)' : 'var(--accent-emerald)'}; cursor: pointer; border: none;" title="${bot.status === 'running' ? 'Stop Bot' : 'Start Bot'}">
                        <i data-lucide="${bot.status === 'running' ? 'pause-circle' : 'play-circle'}" style="width: 16px; height: 16px;"></i>
                    </button>
                    <button class="glass edit-bot-btn" data-id="${bot.id}" style="padding: 5px; color: var(--accent-blue); cursor: pointer; border: none;" title="Edit Config">
                        <i data-lucide="settings-2" style="width: 16px; height: 16px;"></i>
                    </button>
                    <button class="glass archive-bot-btn" data-id="${bot.id}" style="padding: 5px; color: var(--accent-blue); cursor: pointer; border: none;" title="Archive to Vault">
                        <i data-lucide="archive" style="width: 16px; height: 16px;"></i>
                    </button>
                    <button class="glass delete-bot-btn" data-id="${bot.id}" style="padding: 5px; color: var(--accent-ruby); cursor: pointer; border: none;" title="Delete">
                        <i data-lucide="trash-2" style="width: 16px; height: 16px;"></i>
                    </button>
                </td>
            </tr>
        `;
        }).join('');

        updateTableVisibility();
        if (window.lucide) lucide.createIcons();

        // Attach hover events to bot rows
        botTableBody.querySelectorAll('.bot-row').forEach(row => {
            row.addEventListener('mouseenter', (e) => {
                const botId = row.dataset.id;
                const bot = bots.find(b => b.id === botId);
                const botTrades = dashboardState.trades
                    .filter((trade) => trade.bot_id === botId)
                    .sort((a, b) => new Date(a.time) - new Date(b.time));

                let cumulative = 0;
                const previewData = botTrades.map((trade) => {
                    cumulative += Number(trade.pnl) || 0;
                    return cumulative;
                });

                const scoredTrades = botTrades.filter((trade) => Number(trade.pnl) !== 0);
                const wins = scoredTrades.filter((trade) => Number(trade.pnl) > 0).length;
                const successRate = scoredTrades.length > 0
                    ? ((wins / scoredTrades.length) * 100).toFixed(1)
                    : 'N/D';

                const stats = `Trades visibles: ${botTrades.length} | Éxito: ${successRate === 'N/D' ? 'N/D' : `${successRate}%`}`;
                showPreview(
                    e,
                    `Bot Performance: ${botId}`,
                    previewData.length >= 2 ? previewData : [0, 0],
                    stats,
                    bot
                );
            });
            row.addEventListener('mouseleave', (e) => {
                // Only hide if NOT moving into the preview popup
                if (e.relatedTarget && e.relatedTarget.closest('.preview-popup')) return;
                hidePreview();
            });
            row.addEventListener('mousemove', (e) => {
                if (previewPopup && previewPopup.style.display === 'block') {
                    // Only update position if NOT over the popup itself
                    if (!e.target.closest('.preview-popup')) {
                        updatePreviewPosition(e);
                    }
                }
            });
        });
    }

    function updateTableVisibility() {
        const table = document.querySelector('.bot-list table');
        if (!table) return;

        const headers = table.querySelectorAll('thead th');
        const rows = table.querySelectorAll('tbody tr');

        headers.forEach((th, idx) => {
            const fieldName = th.textContent.trim();
            const isVisible = botVisibleFields.includes(fieldName);
            th.style.display = isVisible ? 'table-cell' : 'none';

            rows.forEach(row => {
                const td = row.cells[idx];
                if (td) td.style.display = isVisible ? 'table-cell' : 'none';
            });
        });
    }

    // Kill Switch Interaction
    if (killSwitchBtn) {
        killSwitchBtn.addEventListener('click', async () => {
        const confirmed = confirm('⚠️ WARNING: This will immediately halt all active bots and trading processes. Do you want to proceed?');

        if (confirmed) {
            try {
                const response = await fetch('/risk/kill-switch', { method: 'POST' });
                const data = await response.json();

                alert('🛑 GLOBAL KILL SWITCH ACTIVATED: ' + data.message);

                document.body.style.filter = 'grayscale(1) saturate(0.5)';
                killSwitchBtn.textContent = 'SYSTEM HALTED';
                killSwitchBtn.disabled = true;

                fetchBots(); // Refresh UI

            } catch (error) {
                console.error('Error triggering kill switch:', error);
                alert('Failed to trigger kill switch. Please check connection.');
            }
        }
        });
    }

    // Fetch and Update Trade List
    async function fetchTrades() {
        try {
            const response = await fetch('/api/trades');
            const trades = await response.json();

            dashboardState.trades = Array.isArray(trades) ? trades : [];
            updateTradeFeed(trades);
            refreshDerivedVisuals();
        } catch (error) {
            console.error('Error fetching trades:', error);
        }
    }

    function updateTradeFeed(trades) {
        const sidePanel = document.getElementById('recentTradesContent');
        if (!sidePanel) return;

        if (trades.length === 0) {
            sidePanel.innerHTML = '<div style="color: var(--text-muted); font-size: 0.8rem; text-align: center; padding: 2rem;">No hay operaciones registradas.</div>';
            return;
        }

        // Add a header row
        sidePanel.innerHTML = `
        <div style="display: grid; grid-template-columns: 2fr 1.8fr 1fr; padding: 0 0.75rem 0.5rem; border-bottom: 1px solid rgba(255,255,255,0.06); margin-bottom: 0.5rem;">
            <div style="font-size: 0.68rem; color: var(--text-muted); font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em;">Operación</div>
            <div style="font-size: 0.68rem; color: var(--text-muted); font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; text-align: center;">Precio · Cantidad · Total</div>
            <div style="font-size: 0.68rem; color: var(--text-muted); font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; text-align: right;">PnL / Fee</div>
        </div>
        ` + trades.map(trade => {
            const pnl = trade.pnl || 0;
            const fee = trade.fee || 0;
            const pnlFormatted = (pnl >= 0 ? '+$' : '-$') + Math.abs(pnl).toFixed(3);
            const pnlColor = pnl >= 0 ? '#34d399' : '#f87171';
            const isSell = trade.side === 'sell';
            const accentColor = isSell ? '#ef4444' : '#3b82f6';
            const sideBg = isSell ? 'rgba(239,68,68,0.15)' : 'rgba(59,130,246,0.15)';
            const total = (trade.price * trade.amount).toFixed(2);
            const timeStr = new Date(trade.time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

            return `
            <div class="trade-entry" data-id="${trade.id}" style="
                display: grid;
                grid-template-columns: 2fr 1.8fr 1fr;
                align-items: center;
                padding: 0.6rem 0.75rem;
                border-radius: 8px;
                margin-bottom: 3px;
                border-left: 3px solid ${accentColor};
                background: rgba(255,255,255,0.025);
                gap: 0.5rem;
            ">
                <!-- Col 1: side badge + symbol + bot -->
                <div style="display: flex; align-items: center; gap: 0.5rem; min-width: 0;">
                    <span style="
                        font-size: 0.62rem; font-weight: 800; letter-spacing: 0.06em;
                        padding: 2px 6px; border-radius: 4px; flex-shrink: 0;
                        background: ${sideBg}; color: ${accentColor};
                    ">${trade.side.toUpperCase()}</span>
                    <div style="min-width: 0;">
                        <div style="font-weight: 700; font-size: 0.82rem; white-space: nowrap;">${trade.symbol}</div>
                        <div style="font-size: 0.65rem; color: var(--text-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${trade.bot_id}</div>
                    </div>
                </div>
                <!-- Col 2: price · qty · total -->
                <div style="text-align: center; font-size: 0.78rem;">
                    <span style="font-weight: 600;">$${trade.price.toLocaleString()}</span>
                    <span style="color: var(--text-muted); margin: 0 3px;">×</span>
                    <span style="color: var(--text-secondary);">${trade.amount}</span>
                    <div style="font-size: 0.7rem; color: var(--text-muted); margin-top: 1px;">
                        Total: <span style="color: var(--text-secondary); font-weight: 600;">$${total}</span>
                    </div>
                </div>
                <!-- Col 3: PnL + fee + time -->
                <div style="text-align: right;">
                    <div style="font-size: 0.88rem; font-weight: 800; color: ${pnlColor};">${pnlFormatted}</div>
                    <div style="font-size: 0.65rem; color: #facc15;">Fee $${fee.toFixed(4)}</div>
                    <div style="font-size: 0.62rem; color: var(--text-muted);">${timeStr}</div>
                </div>
            </div>`;
        }).join('');

        sidePanel.querySelectorAll('.trade-entry').forEach(entry => {
            entry.addEventListener('click', () => showTradeExplanation(entry.dataset.id));
            entry.addEventListener('mouseenter', () => entry.style.background = 'rgba(255,255,255,0.055)');
            entry.addEventListener('mouseleave', () => entry.style.background = 'rgba(255,255,255,0.025)');
        });
    }


    async function showTradeExplanation(tradeId) {
        const aiSummary = document.getElementById('aiMarketSummary');
        if (!aiSummary) return;
        aiSummary.innerHTML = `<i>AI is analyzing trade ${tradeId}...</i>`;

        try {
            const response = await fetch(`/api/ai/explain/${tradeId}`);
            const data = await response.json();
            aiSummary.innerHTML = `<strong>Trade Insight:</strong> ${data.explanation}`;
        } catch (error) {
            console.error('Error fetching AI explanation:', error);
            aiSummary.innerHTML = "Failed to fetch AI explanation. Please check local LLM status.";
        }
    }

    function renderPresetQuickDoc(preset) {
        if (!presetQuickDoc) return;
        if (!preset) {
            presetQuickDoc.innerHTML = 'Selecciona un preset para cargar estrategia, símbolo y parámetros base.';
            return;
        }

        presetQuickDoc.innerHTML = `
            <strong>${preset.name}</strong><br>
            ${preset.description}<br>
            Estrategia: <strong>${preset.strategy}</strong> · Riesgo: <strong>${preset.risk_level}</strong> · Mercado: <strong>${preset.market_type}</strong>
        `;
    }

    function applyPresetToCreateForm(preset) {
        if (!preset || !preset.config) return;

        const config = preset.config;
        const strategySelect = document.getElementById('newBotStrategy');
        const executorSelect = document.getElementById('newBotExecutor');
        const symbolInput = document.getElementById('newBotSymbol');
        const fastEmaInput = document.getElementById('newBotFastEma');
        const slowEmaInput = document.getElementById('newBotSlowEma');
        const upperInput = document.getElementById('newBotUpperLimit');
        const lowerInput = document.getElementById('newBotLowerLimit');
        const gridsInput = document.getElementById('newBotNumGrids');
        const allocationInput = document.getElementById('newBotAllocation');

        if (strategySelect && config.strategy) strategySelect.value = config.strategy;
        if (executorSelect && config.executor) executorSelect.value = config.executor;
        if (symbolInput && config.symbol) symbolInput.value = config.symbol;
        if (fastEmaInput && Number.isFinite(config.fast_ema)) fastEmaInput.value = config.fast_ema;
        if (slowEmaInput && Number.isFinite(config.slow_ema)) slowEmaInput.value = config.slow_ema;
        if (upperInput && Number.isFinite(config.upper_limit)) upperInput.value = config.upper_limit;
        if (lowerInput && Number.isFinite(config.lower_limit)) lowerInput.value = config.lower_limit;
        if (gridsInput && Number.isFinite(config.num_grids)) gridsInput.value = config.num_grids;
        if (allocationInput && Number.isFinite(config.capital_allocation)) allocationInput.value = config.capital_allocation;

        document.dispatchEvent(new Event('change', { bubbles: true }));

        if (strategySelect) {
            strategySelect.dispatchEvent(new Event('change', { bubbles: true }));
        }
        if (executorSelect) {
            executorSelect.dispatchEvent(new Event('change', { bubbles: true }));
        }
    }

    function applyConfigToCreateForm(config) {
        if (!config) return;
        const strategySelect = document.getElementById('newBotStrategy');
        const executorSelect = document.getElementById('newBotExecutor');
        const symbolInput = document.getElementById('newBotSymbol');
        const fastEmaInput = document.getElementById('newBotFastEma');
        const slowEmaInput = document.getElementById('newBotSlowEma');
        const upperInput = document.getElementById('newBotUpperLimit');
        const lowerInput = document.getElementById('newBotLowerLimit');
        const gridsInput = document.getElementById('newBotNumGrids');
        const allocationInput = document.getElementById('newBotAllocation');

        if (strategySelect && config.strategy) strategySelect.value = config.strategy;
        if (executorSelect && config.executor) executorSelect.value = config.executor;
        if (symbolInput && config.symbol) symbolInput.value = config.symbol;
        if (fastEmaInput && Number.isFinite(config.fast_ema)) fastEmaInput.value = config.fast_ema;
        if (slowEmaInput && Number.isFinite(config.slow_ema)) slowEmaInput.value = config.slow_ema;
        if (upperInput && Number.isFinite(config.upper_limit)) upperInput.value = config.upper_limit;
        if (lowerInput && Number.isFinite(config.lower_limit)) lowerInput.value = config.lower_limit;
        if (gridsInput && Number.isFinite(config.num_grids)) gridsInput.value = config.num_grids;
        if (allocationInput && Number.isFinite(config.capital_allocation)) allocationInput.value = config.capital_allocation;

        if (strategySelect) strategySelect.dispatchEvent(new Event('change', { bubbles: true }));
        if (executorSelect) executorSelect.dispatchEvent(new Event('change', { bubbles: true }));
    }

    function resetBotFilters() {
        if (botFilterSearch) botFilterSearch.value = '';
        if (botFilterStrategy) botFilterStrategy.value = '';
        if (botFilterStatus) botFilterStatus.value = '';
        fetchBots();
    }

    function openTab(targetId) {
        const targetLink = Array.from(navLinks || []).find(link => link.dataset.tab === targetId);
        if (targetLink) targetLink.click();
    }

    async function generateBotParamsFromPrompt() {
        if (!generateBotFromTextBtn || !newBotPrompt) return;

        const prompt = String(newBotPrompt.value || '').trim();
        const symbol = document.getElementById('newBotSymbol')?.value || 'BTC/USDT';
        const allocation = parseFloat(document.getElementById('newBotAllocation')?.value || 1000);

        if (!prompt) {
            if (botPromptStatus) {
                botPromptStatus.style.color = 'var(--accent-ruby)';
                botPromptStatus.textContent = 'Escribe primero el texto de la estrategia.';
            }
            return;
        }

        generateBotFromTextBtn.disabled = true;
        const prevLabel = generateBotFromTextBtn.textContent;
        generateBotFromTextBtn.textContent = 'GENERANDO...';
        if (botPromptStatus) {
            botPromptStatus.style.color = 'var(--text-muted)';
            botPromptStatus.textContent = 'Analizando prompt y generando parámetros...';
        }

        try {
            const response = await fetch('/api/bot-advisor/from-text', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ prompt, symbol, allocation })
            });

            if (!response.ok) {
                const err = await response.json();
                throw new Error(err.detail || 'No se pudieron generar parámetros');
            }

            const data = await response.json();
            const config = data?.config || {};
            const meta = data?.meta || {};
            applyConfigToCreateForm(config);

            if (botPromptStatus) {
                botPromptStatus.style.color = 'var(--accent-emerald)';
                botPromptStatus.textContent = `Parámetros aplicados: ${String(meta.detected_strategy || '-')} · riesgo ${String(meta.risk_level || '-')} · horizonte ${String(meta.horizon || '-')}`;
            }
        } catch (error) {
            console.error('Error generating bot params from prompt:', error);
            if (botPromptStatus) {
                botPromptStatus.style.color = 'var(--accent-ruby)';
                botPromptStatus.textContent = `Error: ${error.message}`;
            }
        } finally {
            generateBotFromTextBtn.disabled = false;
            generateBotFromTextBtn.textContent = prevLabel;
        }
    }

    function renderAdvisorResults(data) {
        if (!advisorResults) return;
        const recommendations = data?.recommendations || [];
        const marketContext = data?.market_context || {};
        advisorMap = {};

        if (!recommendations.length) {
            advisorResults.style.display = 'block';
            advisorResults.innerHTML = '<div style="font-size:0.8rem;color:var(--text-muted);">Sin recomendaciones disponibles.</div>';
            return;
        }

        recommendations.forEach((item) => {
            advisorMap[item.horizon] = item;
        });

        advisorResults.style.display = 'block';
        const marketSummary = `
            <div style="margin-bottom:8px; padding:8px; border:1px solid rgba(255,255,255,0.08); border-radius:8px; background:rgba(255,255,255,0.02);">
                <div style="font-size:0.72rem; color:var(--text-muted); text-transform:uppercase;">Contexto de mercado</div>
                <div style="font-size:0.8rem; color:var(--text-secondary); margin-top:4px;">
                    Régimen: <strong style="color:var(--accent-blue);">${marketContext.regime || 'mixto'}</strong> ·
                    Volatilidad: <strong>${marketContext.volatility_pct ?? 0}%</strong> ·
                    Tendencia: <strong>${marketContext.trend_pct ?? 0}%</strong> ·
                    Horizonte sugerido: <strong style="color:var(--accent-emerald);">${(marketContext.preferred_horizon || 'medio').toUpperCase()}</strong>
                </div>
            </div>
        `;

        advisorResults.innerHTML = marketSummary + recommendations.map((item) => {
            const actionLabel = item.recommended_action === 'tune_existing'
                ? `Base recomendada: ${item.recommended_bot_id || 'bot existente'} (sin sobrescribir)`
                : item.recommended_action === 'reduce_risk'
                    ? `Base defensiva: ${item.recommended_bot_id || 'bot existente'} (sin sobrescribir)`
                    : `Crear bot nuevo (${item.new_bot_preset_name || 'preset'})`;

            return `
                <div style="border:1px solid rgba(255,255,255,0.08); border-radius:8px; padding:10px; margin-bottom:8px; background:rgba(255,255,255,0.02);">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                        <strong style="text-transform:uppercase; color:var(--accent-blue);">${item.horizon}</strong>
                        <span style="font-size:0.72rem; color:var(--text-secondary);">Confianza ${item.confidence}%</span>
                    </div>
                    <div style="font-size:0.78rem; color:var(--text-secondary); margin-bottom:6px;">${actionLabel}</div>
                    <div style="font-size:0.72rem; color:var(--text-muted); margin-bottom:8px;">${item.reason || ''}</div>
                    <div style="font-size:0.70rem; color:var(--text-muted); margin-bottom:8px;">Crear bot ahora / Auto-ejecutar siempre crean un bot NUEVO.</div>
                    <div style="display:grid; grid-template-columns: 1fr 1fr 1fr; gap:6px;">
                        <button class="advisor-apply-btn" data-horizon="${item.horizon}" style="padding:7px; border:1px solid var(--accent-blue); color:var(--accent-blue); background:transparent; border-radius:8px; cursor:pointer;">Usar en formulario</button>
                        <button class="advisor-create-btn" data-horizon="${item.horizon}" style="padding:7px; border:1px solid var(--accent-emerald); color:var(--accent-emerald); background:transparent; border-radius:8px; cursor:pointer;">Crear bot ahora</button>
                        <button class="advisor-auto-btn" data-horizon="${item.horizon}" style="padding:7px; border:1px solid #facc15; color:#facc15; background:transparent; border-radius:8px; cursor:pointer;">Auto-ejecutar</button>
                    </div>
                </div>
            `;
        }).join('');
    }

    function renderAsset30dMetrics(payload) {
        if (!asset30dMetrics) return;
        const analysis = payload?.analysis || {};
        const rows = payload?.rows || 0;
        const metrics = [
            { label: 'Trend 30d', value: `${Number(analysis.trend_pct || 0).toFixed(2)}%` },
            { label: 'Volatilidad', value: `${Number(analysis.volatility_pct || 0).toFixed(2)}%` },
            { label: 'Max Drawdown', value: `${Number(analysis.max_drawdown_pct || 0).toFixed(2)}%` },
            { label: 'Rango', value: `${Number(analysis.range_pct || 0).toFixed(2)}%` },
            { label: 'Avg Vol', value: Number(analysis.avg_volume || 0).toLocaleString(undefined, { maximumFractionDigits: 2 }) },
            { label: 'Ultimo Close', value: Number(analysis.last_close || 0).toLocaleString(undefined, { maximumFractionDigits: 6 }) },
        ];

        asset30dMetrics.innerHTML = metrics.map((item) => `
            <div style="padding:10px; border:1px solid rgba(255,255,255,0.08); border-radius:10px; background: rgba(255,255,255,0.02);">
                <div style="font-size:0.68rem; color: var(--text-muted); text-transform: uppercase;">${item.label}</div>
                <div style="font-size:0.9rem; font-weight:700; color: var(--text-secondary); margin-top:4px;">${item.value}</div>
                <div style="font-size:0.64rem; color: var(--text-muted); margin-top:4px;">velas ${rows}</div>
            </div>
        `).join('');
    }

    function renderAsset30dChart(payload) {
        const canvas = document.getElementById('asset30dChart');
        if (!canvas || !payload?.candles?.length) return;

        const ctx = canvas.getContext('2d');
        if (asset30dChart) asset30dChart.destroy();

        const labels = payload.candles.map((c) => new Date(c.time).toLocaleString());
        const prices = payload.candles.map((c) => c.close);

        asset30dChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels,
                datasets: [{
                    label: `${payload.symbol} close`,
                    data: prices,
                    borderColor: '#60a5fa',
                    backgroundColor: 'rgba(96, 165, 250, 0.12)',
                    fill: true,
                    tension: 0.2,
                    pointRadius: 0,
                    borderWidth: 2
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: true } },
                scales: {
                    x: { ticks: { color: 'rgba(255,255,255,0.5)', maxRotation: 45, minRotation: 45 } },
                    y: { ticks: { color: 'rgba(255,255,255,0.5)' } }
                }
            }
        });
    }

    function renderAssetAdvisorResults(data) {
        if (!asset30dAdvisor) return;
        const recommendations = data?.recommendations || [];
        const marketContext = data?.market_context || {};
        assetAdvisorMap = {};

        if (!recommendations.length) {
            asset30dAdvisor.style.display = 'block';
            asset30dAdvisor.innerHTML = '<div style="font-size:0.8rem;color:var(--text-muted);">Sin recomendaciones disponibles.</div>';
            return;
        }

        recommendations.forEach((item) => {
            assetAdvisorMap[item.horizon] = item;
        });

        const marketSummary = `
            <div style="margin-bottom:8px; padding:8px; border:1px solid rgba(255,255,255,0.08); border-radius:8px; background:rgba(255,255,255,0.02);">
                <div style="font-size:0.72rem; color:var(--text-muted); text-transform:uppercase;">Contexto de mercado</div>
                <div style="font-size:0.8rem; color:var(--text-secondary); margin-top:4px;">
                    Regimen: <strong style="color:var(--accent-blue);">${marketContext.regime || 'mixto'}</strong> ·
                    Volatilidad: <strong>${marketContext.volatility_pct ?? 0}%</strong> ·
                    Tendencia: <strong>${marketContext.trend_pct ?? 0}%</strong> ·
                    Horizonte sugerido: <strong style="color:var(--accent-emerald);">${(marketContext.preferred_horizon || 'medio').toUpperCase()}</strong>
                </div>
            </div>
        `;

        asset30dAdvisor.style.display = 'block';
        asset30dAdvisor.innerHTML = marketSummary + recommendations.map((item) => {
            const actionLabel = item.recommended_action === 'tune_existing'
                ? `Base recomendada: ${item.recommended_bot_id || 'bot existente'} (sin sobrescribir)`
                : item.recommended_action === 'reduce_risk'
                    ? `Base defensiva: ${item.recommended_bot_id || 'bot existente'} (sin sobrescribir)`
                    : `Crear bot nuevo (${item.new_bot_preset_name || 'preset'})`;

            return `
                <div style="border:1px solid rgba(255,255,255,0.08); border-radius:8px; padding:10px; margin-bottom:8px; background:rgba(255,255,255,0.02);">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                        <strong style="text-transform:uppercase; color:var(--accent-blue);">${item.horizon}</strong>
                        <span style="font-size:0.72rem; color:var(--text-secondary);">Confianza ${item.confidence}%</span>
                    </div>
                    <div style="font-size:0.78rem; color:var(--text-secondary); margin-bottom:6px;">${actionLabel}</div>
                    <div style="font-size:0.72rem; color:var(--text-muted); margin-bottom:8px;">${item.reason || ''}</div>
                    <div style="display:grid; grid-template-columns: 1fr 1fr 1fr; gap:6px;">
                        <button class="asset-advisor-apply" data-horizon="${item.horizon}" style="padding:7px; border:1px solid var(--accent-blue); color:var(--accent-blue); background:transparent; border-radius:8px; cursor:pointer;">Usar en formulario</button>
                        <button class="asset-advisor-create" data-horizon="${item.horizon}" style="padding:7px; border:1px solid var(--accent-emerald); color:var(--accent-emerald); background:transparent; border-radius:8px; cursor:pointer;">Crear bot ahora</button>
                        <button class="asset-advisor-auto" data-horizon="${item.horizon}" style="padding:7px; border:1px solid #facc15; color:#facc15; background:transparent; border-radius:8px; cursor:pointer;">Auto-ejecutar</button>
                    </div>
                </div>
            `;
        }).join('');
    }

    async function runAsset30dAnalysis() {
        if (!asset30dAnalyzeBtn) return;
        const symbol = asset30dSymbol?.value || 'BTC/USDT';
        const timeframe = asset30dTimeframe?.value || '1h';
        const source = asset30dSource?.value || 'live';

        asset30dAnalyzeBtn.disabled = true;
        const prevText = asset30dAnalyzeBtn.textContent;
        asset30dAnalyzeBtn.textContent = 'ANALIZANDO...';

        try {
            const response = await fetch('/api/market/analysis', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ symbol, timeframe, source, days: 30 })
            });

            if (!response.ok) {
                const err = await response.json();
                throw new Error(err.detail || 'No se pudo analizar el historico');
            }

            const payload = await response.json();
            renderAsset30dMetrics(payload);
            renderAsset30dChart(payload);

            if (asset30dStatus) {
                asset30dStatus.textContent = `Analisis 30 dias: ${payload.symbol} ${payload.timeframe} · fuente=${payload.source} · velas=${payload.rows}`;
            }
        } catch (error) {
            console.error('Asset 30d analysis error:', error);
            if (asset30dStatus) {
                asset30dStatus.textContent = `Error analizando: ${error.message}`;
            }
        } finally {
            asset30dAnalyzeBtn.disabled = false;
            asset30dAnalyzeBtn.textContent = prevText;
        }
    }

    async function runAsset30dRecommendation() {
        if (!asset30dRecommendBtn) return;
        const symbol = asset30dSymbol?.value || 'BTC/USDT';
        const allocation = parseFloat(asset30dAllocation?.value || '500');

        asset30dRecommendBtn.disabled = true;
        const prevText = asset30dRecommendBtn.textContent;
        asset30dRecommendBtn.textContent = 'RECOMENDANDO...';

        try {
            const response = await fetch('/api/bot-advisor/analyze', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ symbol, allocation })
            });

            if (!response.ok) {
                const err = await response.json();
                throw new Error(err.detail || 'No se pudo generar recomendacion');
            }

            const data = await response.json();
            renderAssetAdvisorResults(data);
        } catch (error) {
            console.error('Asset 30d advisor error:', error);
            if (asset30dAdvisor) {
                asset30dAdvisor.style.display = 'block';
                asset30dAdvisor.innerHTML = `<div style="font-size:0.8rem;color:var(--accent-ruby);">Error: ${error.message}</div>`;
            }
        } finally {
            asset30dRecommendBtn.disabled = false;
            asset30dRecommendBtn.textContent = prevText;
        }
    }

    async function createMicroScalpBot() {
        if (!microScalpCreateBtn) return;

        const symbol = microScalpSymbol?.value || 'BTC/USDT';
        const allocation = parseFloat(microScalpAllocation?.value || '350');

        microScalpCreateBtn.disabled = true;
        const prevText = microScalpCreateBtn.textContent;
        microScalpCreateBtn.textContent = 'CREANDO...';
        if (microScalpStatus) {
            microScalpStatus.style.color = 'var(--text-muted)';
            microScalpStatus.textContent = `Creando micro-scalp para ${symbol}...`;
        }

        try {
            const response = await fetch('/api/bot-presets/preset_micro_scalp_adaptativo/create', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    overrides: {
                        symbol,
                        capital_allocation: allocation,
                        allocation,
                        executor: 'paper',
                    },
                }),
            });

            if (!response.ok) {
                const err = await response.json();
                throw new Error(err.detail || 'No se pudo crear el bot micro-scalp');
            }

            const data = await response.json();
            resetBotFilters();
            openTab('bots');
            if (microScalpStatus) {
                microScalpStatus.style.color = 'var(--accent-emerald)';
                microScalpStatus.textContent = `Bot creado: ${data.bot_id || 'micro-scalp'}`;
            }
            alert(`Micro-scalp creado en paper: ${data.bot_id || 'ok'}`);
        } catch (error) {
            console.error('Micro-scalp create error:', error);
            if (microScalpStatus) {
                microScalpStatus.style.color = 'var(--accent-ruby)';
                microScalpStatus.textContent = `Error: ${error.message}`;
            }
            alert(`No se pudo crear micro-scalp: ${error.message}`);
        } finally {
            microScalpCreateBtn.disabled = false;
            microScalpCreateBtn.textContent = prevText;
        }
    }

    async function activateProductionForBot(botId) {
        const activateProduction = async () => {
            const selectedWindow = Math.max(1, parseInt(testInsightsWindow?.value || '24', 10) || 24);
            const selectedMinTrades = Math.max(1, parseInt(testInsightsMinTrades?.value || '8', 10) || 8);
            const response = await fetch('/api/monitoring/activate-production', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    bot_id: botId,
                    lookback_hours: selectedWindow,
                    min_scored_trades: selectedMinTrades,
                })
            });

            let err = null;
            let data = null;
            if (response.ok) {
                data = await response.json();
            } else {
                err = await response.json();
            }

            return { response, data, err };
        };

        const firstAttempt = await activateProduction();
        const detail = !firstAttempt.response.ok
            ? firstAttempt.err?.detail
            : (firstAttempt.data?.activated === false ? firstAttempt.data : null);

        if (detail?.reason === 'executor_not_hyperliquid' && detail?.suggested_patch) {
            await new Promise((resolve) => {
                showCustomConfirm(
                    'Cambiar a ejecucion real',
                    `El bot ${botId} no usa Hyperliquid mainnet. Quieres aplicar el ajuste recomendado y reintentar activacion?`,
                    async () => {
                        try {
                            const patchResponse = await fetch(`/api/bots/${botId}`, {
                                method: 'PATCH',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify(detail.suggested_patch)
                            });

                            if (!patchResponse.ok) {
                                const patchErr = await patchResponse.json();
                                throw new Error(patchErr.detail || 'No se pudo aplicar patch');
                            }

                            const secondAttempt = await activateProduction();
                            if (!secondAttempt.response.ok || secondAttempt.data?.activated === false) {
                                const secondDetailPayload = secondAttempt.err?.detail || secondAttempt.data;
                                const secondDetail = secondDetailPayload ? JSON.stringify(secondDetailPayload) : 'error';
                                throw new Error(secondDetail);
                            }

                            fetchBots();
                            fetchTestInsights();
                            alert(`Produccion activada para ${secondAttempt.data.bot_id}`);
                        } catch (innerError) {
                            console.error('Error patch+activate production bot:', innerError);
                            alert('No se pudo activar en produccion tras aplicar ajuste: ' + innerError.message);
                        } finally {
                            resolve();
                        }
                    }
                );
            });
            return;
        }

        if (detail?.reason === 'bot_not_ready_for_production') {
            const metrics = detail.metrics || {};
            const readiness = detail.readiness || {};
            const criticalOpenAlerts = Number(detail.critical_open_alerts || 0);
            const scoredTrades = Number(metrics.scored_trades || 0);
            const winRate = Number(metrics.win_rate || 0);
            const netPnl = Number(metrics.net_pnl || 0);
            const readinessSummary = String(readiness.summary || '').trim();
            const blockers = Array.isArray(readiness.blockers)
                ? readiness.blockers.map((v) => String(v || '').trim()).filter(Boolean)
                : [];

            if (criticalOpenAlerts > 0) {
                showCustomConfirm(
                    'Bloqueo por alertas criticas',
                    `El bot ${botId} aun no esta listo. Alertas criticas abiertas: ${criticalOpenAlerts}. Metricas: ${scoredTrades} trades validos, win rate ${winRate.toFixed(2)}%, net PnL ${netPnl.toFixed(2)}. Quieres marcar alertas criticas de este bot como revisadas y reintentar activacion?`,
                    async () => {
                        try {
                            const acked = await acknowledgeCriticalAlertsForBot(botId);
                            if (acked > 0) {
                                await fetch('/api/production/scan', { method: 'POST' });
                            }

                            const secondAttempt = await activateProduction();
                            if (!secondAttempt.response.ok || secondAttempt.data?.activated === false) {
                                const secondDetailPayload = secondAttempt.err?.detail || secondAttempt.data;
                                const secondDetail = secondDetailPayload ? JSON.stringify(secondDetailPayload) : 'error';
                                throw new Error(secondDetail);
                            }

                            fetchBots();
                            loadMainnetVisualControl();
                            fetchTestInsights();
                            alert(`Produccion activada para ${secondAttempt.data.bot_id}`);
                        } catch (innerError) {
                            console.error('Error resolving production blockers:', innerError);
                            alert('Sigue bloqueado para produccion: ' + innerError.message);
                        }
                    }
                );
                return;
            }

            alert(
                `Bot no listo para produccion (${botId}).\n` +
                `${readinessSummary ? `Diagnostico: ${readinessSummary}\n` : ''}` +
                `Trades validos: ${scoredTrades}\n` +
                `Win rate: ${winRate.toFixed(2)}%\n` +
                `Net PnL: ${netPnl.toFixed(2)}\n` +
                `Perdidas consecutivas: ${Number(metrics.consecutive_losses || 0)}\n` +
                `Max Drawdown: ${Number(metrics.max_drawdown_abs || 0).toFixed(4)}` +
                `${blockers.length ? `\nBloqueadores: ${blockers.join(' | ')}` : ''}`
            );
            return;
        }

        if (detail) {
            const detailText = JSON.stringify(detail);
            throw new Error(detailText);
        }

        const data = firstAttempt.data;
        fetchBots();
        fetchTestInsights();
        alert(`Produccion activada para ${data.bot_id}`);
    }

    async function loadBotPresets() {
        if (!newBotPreset) return;

        try {
            const response = await fetch('/api/bot-presets');
            if (!response.ok) return;

            const data = await response.json();
            botPresets = data.presets || [];

            botPresets.forEach((preset) => {
                const opt = document.createElement('option');
                opt.value = preset.id;
                opt.textContent = `${preset.name} (${preset.risk_level})`;
                newBotPreset.appendChild(opt);
            });
        } catch (error) {
            console.error('Error loading bot presets:', error);
        }
    }

    async function acknowledgeCriticalAlertsForBot(botId) {
        const response = await fetch('/api/production/alerts?limit=50&only_open=true');
        if (!response.ok) {
            throw new Error('No se pudieron leer alertas abiertas');
        }

        const alerts = await response.json();
        if (!Array.isArray(alerts)) {
            throw new Error('Respuesta de alertas inválida');
        }

        const toAck = alerts.filter((alert) => {
            const level = String(alert.level || '').toLowerCase();
            return alert.bot_id === botId && level === 'critical';
        });

        for (const alert of toAck) {
            if (!alert.id) continue;
            await fetch(`/api/production/alerts/${alert.id}/ack`, { method: 'POST' });
        }

        return toAck.length;
    }

    function recommendationLevelLabel(level) {
        const normalized = (level || '').toLowerCase();
        if (normalized === 'offensive') return { label: 'OFENSIVO', color: 'var(--accent-emerald)' };
        if (normalized === 'defensive') return { label: 'DEFENSIVO', color: 'var(--accent-ruby)' };
        if (normalized === 'insufficient_data') return { label: 'MUESTRA CORTA', color: 'var(--accent-blue)' };
        return { label: 'MANTENER', color: 'var(--text-secondary)' };
    }

    function buildSuggestedParamsList(params = {}) {
        const entries = Object.entries(params || {});
        if (!entries.length) {
            return '<div style="font-size:0.74rem; color: var(--text-muted);">Sin cambios sugeridos.</div>';
        }

        return entries.map(([key, value]) => {
            const rendered = typeof value === 'object' ? JSON.stringify(value) : String(value);
            return `<div style="font-size:0.74rem; color: var(--text-secondary);"><strong>${key}</strong>: ${rendered}</div>`;
        }).join('');
    }

    function scoreRiskForOrdering(item = {}) {
        const metrics = item.metrics || {};
        const alerts = Number(item.open_critical_alerts || 0);
        const consecutiveLosses = Number(metrics.consecutive_losses || 0);
        const maxDrawdown = Number(metrics.max_drawdown_abs || 0);
        return alerts * 100 + consecutiveLosses * 10 + maxDrawdown;
    }

    function scorePerformanceForOrdering(item = {}) {
        const metrics = item.metrics || {};
        const netPnl = Number(metrics.net_pnl || 0);
        const winRate = Number(metrics.win_rate || 0);
        const scoredTrades = Number(metrics.scored_trades || 0);
        return (netPnl * 10) + winRate + (scoredTrades * 0.1);
    }

    function sortInsightsRows(rows = []) {
        return [...rows].sort((a, b) => {
            const candidateA = a.candidate_for_production ? 1 : 0;
            const candidateB = b.candidate_for_production ? 1 : 0;
            if (candidateB !== candidateA) return candidateB - candidateA;

            const riskA = scoreRiskForOrdering(a);
            const riskB = scoreRiskForOrdering(b);
            if (riskA !== riskB) return riskA - riskB;

            const perfA = scorePerformanceForOrdering(a);
            const perfB = scorePerformanceForOrdering(b);
            if (perfB !== perfA) return perfB - perfA;

            const botA = String(a.bot_id || '');
            const botB = String(b.bot_id || '');
            return botA.localeCompare(botB);
        });
    }

    function buildProductionReadiness(item = {}, minScoredTrades = 8) {
        const metrics = item.metrics || {};
        const readinessApi = item.readiness || {};
        const scoredTrades = Number(metrics.scored_trades || 0);
        const netPnl = Number(metrics.net_pnl || 0);
        const criticalAlerts = Number(item.open_critical_alerts || item.critical_open_alerts || 0);
        const isRunning = String(item.status || '').toLowerCase() === 'running';
        const recommendationLevel = String((item.recommendation || {}).level || '').toLowerCase();
        const apiGateOk = Boolean(readinessApi.gate_ok);
        const apiSummary = String(readinessApi.summary || '').trim();
        const apiBlockers = Array.isArray(readinessApi.blockers)
            ? readinessApi.blockers.map((value) => String(value || '').trim()).filter(Boolean)
            : [];

        if (item.candidate_for_production || apiGateOk) {
            return {
                ready: true,
                label: 'APTO PRODUCCION',
                color: 'var(--accent-emerald)',
                reasonText: apiSummary || 'Apto para entrar en produccion segun pruebas y guardrails',
                blockers: [],
            };
        }

        const blockers = [...apiBlockers];
        if (scoredTrades < minScoredTrades) {
            blockers.push(`Muestra insuficiente (${scoredTrades}/${minScoredTrades} trades validos)`);
        }
        if (criticalAlerts > 0) {
            blockers.push(`Alertas criticas abiertas (${criticalAlerts})`);
        }
        if (!isRunning) {
            blockers.push('Bot detenido');
        }
        if (recommendationLevel === 'insufficient_data') {
            blockers.push('Sin evidencia estadistica suficiente');
        }
        if (netPnl <= 0) {
            blockers.push('Net PnL no positivo');
        }

        const hasKnownBlockers = blockers.length > 0;
        const label = 'NO APTO / BLOQUEADO';
        const color = hasKnownBlockers ? 'var(--accent-ruby)' : '#facc15';
        const reasonText = apiSummary || (hasKnownBlockers
            ? blockers.join(' · ')
            : 'Aun no cumple criterios de promocion a produccion');

        return {
            ready: false,
            label,
            color,
            reasonText,
            blockers,
        };
    }

    function renderProductionEligibilityGroups(rows = [], selectedMinTrades = 8) {
        const readyRows = [];
        const blockedRows = [];

        rows.forEach((item) => {
            const readiness = buildProductionReadiness(item, selectedMinTrades);
            if (readiness.ready) {
                readyRows.push({ item, readiness });
            } else {
                blockedRows.push({ item, readiness });
            }
        });

        const renderItem = ({ item, readiness }) => {
            const m = item.metrics || {};
            const pnl = Number(m.net_pnl || 0);
            const pnlColor = pnl >= 0 ? 'var(--accent-emerald)' : 'var(--accent-ruby)';
            const status = String(item.status || '-').toUpperCase();
            const runtime = item.runtime_ready ? 'RUNNING' : 'STOPPED';
            const titleLabel = readiness.ready ? 'APTO PARA PRODUCCION' : 'BLOQUEADO PRODUCCION';
            return `
                <div style="border:1px solid rgba(255,255,255,0.08); border-left:4px solid ${readiness.color}; border-radius:10px; padding:10px; margin-bottom:8px; background:rgba(255,255,255,0.02);">
                    <div style="display:flex; justify-content:space-between; gap:8px; align-items:center; flex-wrap:wrap;">
                        <div style="font-weight:700;">${item.bot_id || '-'}</div>
                        <span style="font-size:0.66rem; border:1px solid ${readiness.color}; color:${readiness.color}; border-radius:10px; padding:2px 8px;">${titleLabel}</span>
                    </div>
                    <div style="font-size:0.72rem; color: var(--text-muted); margin-top:3px;">${item.strategy || '-'} · estado ${status} · runtime ${runtime}</div>
                    <div style="font-size:0.74rem; color: ${readiness.color}; margin-top:6px;"><strong>Resultado:</strong> ${readiness.reasonText}</div>
                    <div style="display:grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap:8px; margin-top:8px; font-size:0.72rem; color: var(--text-secondary);">
                        <div>Trades validos<br><strong>${m.scored_trades ?? 0}</strong></div>
                        <div>Win Rate<br><strong>${m.win_rate ?? 0}%</strong></div>
                        <div>Net PnL<br><strong style="color:${pnlColor};">${pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}</strong></div>
                    </div>
                </div>
            `;
        };

        const gateStateLabel = readyRows.length > 0 ? 'HAY BOTS ACTIVABLES EN PRODUCCION' : 'NO HAY BOTS APTOS PARA PRODUCCION';
        const gateStateColor = readyRows.length > 0 ? 'var(--accent-emerald)' : 'var(--accent-ruby)';

        return `
            <div style="margin-bottom:10px; padding:12px; border:2px solid ${gateStateColor}; border-radius:12px; background: ${readyRows.length > 0 ? 'rgba(16,185,129,0.08)' : 'rgba(239,68,68,0.08)'};">
                <div style="font-size:0.7rem; text-transform:uppercase; color: var(--text-muted);">Gate de produccion</div>
                <div style="font-size:0.92rem; font-weight:800; letter-spacing:0.02em; color:${gateStateColor}; margin-top:3px;">${gateStateLabel}</div>
                <div style="font-size:0.74rem; color: var(--text-secondary); margin-top:4px;">Solo los bots en <strong style="color: var(--accent-emerald);">APTO PARA PRODUCCION</strong> deben pasar al boton de activacion real.</div>
            </div>

            <div style="display:grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap:12px; margin-bottom:12px;">
                <div style="padding:10px; border:1px solid rgba(16,185,129,0.45); border-radius:10px; background: rgba(16,185,129,0.08);">
                    <div style="font-size:0.72rem; text-transform:uppercase; color: var(--text-muted);">Aptos para producción</div>
                    <div style="font-size:1.1rem; font-weight:700; color: var(--accent-emerald); margin-top:4px;">${readyRows.length}</div>
                </div>
                <div style="padding:10px; border:1px solid rgba(239,68,68,0.45); border-radius:10px; background: rgba(239,68,68,0.08);">
                    <div style="font-size:0.72rem; text-transform:uppercase; color: var(--text-muted);">No aptos / bloqueados</div>
                    <div style="font-size:1.1rem; font-weight:700; color: var(--accent-ruby); margin-top:4px;">${blockedRows.length}</div>
                </div>
            </div>

            <div style="margin-bottom:10px; padding:10px; border:1px solid rgba(16,185,129,0.35); border-radius:10px; background: rgba(16,185,129,0.05);">
                <div style="font-size:0.76rem; font-weight:700; color: var(--accent-emerald); margin-bottom:8px;">LISTA APTO PARA PRODUCCIÓN</div>
                ${readyRows.length ? readyRows.map(renderItem).join('') : '<div style="font-size:0.75rem; color: var(--text-muted);">No hay bots aptos en este rango.</div>'}
            </div>

            <div style="padding:10px; border:1px solid rgba(239,68,68,0.35); border-radius:10px; background: rgba(239,68,68,0.05);">
                <div style="font-size:0.76rem; font-weight:700; color: var(--accent-ruby); margin-bottom:8px;">LISTA NO APTO / BLOQUEADO</div>
                ${blockedRows.length ? blockedRows.map(renderItem).join('') : '<div style="font-size:0.75rem; color: var(--text-muted);">No hay bots bloqueados.</div>'}
            </div>
        `;
    }

    function buildBotSemaphore(item = {}, minScoredTrades = 8) {
        const readiness = buildProductionReadiness(item, minScoredTrades);
        const metrics = item.metrics || {};
        const scoredTrades = Number(metrics.scored_trades || 0);
        const winRate = Number(metrics.win_rate || 0);
        const netPnl = Number(metrics.net_pnl || 0);
        const critical = Number(item.open_critical_alerts || 0);

        if (critical > 0 || scoredTrades < Math.max(3, Math.floor(minScoredTrades / 2)) || netPnl < 0) {
            return {
                level: 'RED',
                color: 'var(--accent-ruby)',
                action: 'PAUSAR y revisar riesgo/alertas antes de seguir operando',
                readiness,
                metrics,
                details: `wr ${winRate.toFixed(2)}% · net ${netPnl.toFixed(2)} · trades ${scoredTrades} · alertas ${critical}`
            };
        }

        if (!readiness.ready || winRate < 55 || scoredTrades < minScoredTrades) {
            return {
                level: 'YELLOW',
                color: '#facc15',
                action: 'SEGUIR EN PAPER y acumular más muestra antes de producción',
                readiness,
                metrics,
                details: `wr ${winRate.toFixed(2)}% · net ${netPnl.toFixed(2)} · trades ${scoredTrades}`
            };
        }

        return {
            level: 'GREEN',
            color: 'var(--accent-emerald)',
            action: 'LISTO para activar producción con guardrails activos',
            readiness,
            metrics,
            details: `wr ${winRate.toFixed(2)}% · net ${netPnl.toFixed(2)} · trades ${scoredTrades}`
        };
    }

    function renderBotTrafficLightPanel(summary = {}, rows = [], minScoredTrades = 8) {
        if (!botTrafficLightHeader || !botTrafficLightSummary || !botTrafficLightList) return;

        const semRows = (rows || []).map((item) => ({ item, sem: buildBotSemaphore(item, minScoredTrades) }));
        const redCount = semRows.filter((r) => r.sem.level === 'RED').length;
        const yellowCount = semRows.filter((r) => r.sem.level === 'YELLOW').length;
        const greenCount = semRows.filter((r) => r.sem.level === 'GREEN').length;

        const globalLevel = redCount > 0 ? 'RED' : (yellowCount > 0 ? 'YELLOW' : 'GREEN');
        const globalColor = globalLevel === 'RED'
            ? 'var(--accent-ruby)'
            : (globalLevel === 'YELLOW' ? '#facc15' : 'var(--accent-emerald)');
        const globalText = globalLevel === 'RED'
            ? 'RIESGO ALTO · revisar alertas y bots en rojo'
            : (globalLevel === 'YELLOW'
                ? 'ESTADO INTERMEDIO · consolidar muestra en paper'
                : 'ESTADO SALUDABLE · sistema listo para escalar');

        botTrafficLightHeader.innerHTML = `
            <strong>Semáforo Global:</strong>
            <span style="color:${globalColor}; font-weight:700;">${globalLevel}</span>
            · ${globalText}
        `;

        botTrafficLightSummary.innerHTML = `
            <div style="padding:10px; border:1px solid rgba(255,255,255,0.08); border-radius:10px; background: rgba(16,185,129,0.08);">
                <div style="font-size:0.68rem; color: var(--text-muted); text-transform: uppercase;">Verde</div>
                <div style="font-size:1rem; font-weight:700; color: var(--accent-emerald); margin-top:4px;">${greenCount}</div>
            </div>
            <div style="padding:10px; border:1px solid rgba(255,255,255,0.08); border-radius:10px; background: rgba(250,204,21,0.08);">
                <div style="font-size:0.68rem; color: var(--text-muted); text-transform: uppercase;">Amarillo</div>
                <div style="font-size:1rem; font-weight:700; color: #facc15; margin-top:4px;">${yellowCount}</div>
            </div>
            <div style="padding:10px; border:1px solid rgba(255,255,255,0.08); border-radius:10px; background: rgba(239,68,68,0.08);">
                <div style="font-size:0.68rem; color: var(--text-muted); text-transform: uppercase;">Rojo</div>
                <div style="font-size:1rem; font-weight:700; color: var(--accent-ruby); margin-top:4px;">${redCount}</div>
            </div>
            <div style="padding:10px; border:1px solid rgba(255,255,255,0.08); border-radius:10px; background: rgba(255,255,255,0.02);">
                <div style="font-size:0.68rem; color: var(--text-muted); text-transform: uppercase;">Bots analizados</div>
                <div style="font-size:1rem; font-weight:700; color: var(--text-secondary); margin-top:4px;">${summary.bots_analyzed ?? semRows.length}</div>
            </div>
        `;

        if (!semRows.length) {
            botTrafficLightList.innerHTML = '<div style="color: var(--text-muted);">Sin datos para calcular semáforo.</div>';
            return;
        }

        botTrafficLightList.innerHTML = semRows.slice(0, 8).map(({ item, sem }) => `
            <div style="display:flex; justify-content:space-between; gap:10px; align-items:flex-start; padding:8px 0; border-bottom:1px solid rgba(255,255,255,0.06);">
                <div>
                    <div style="font-weight:700;">${item.bot_id || '-'}</div>
                    <div style="font-size:0.72rem; color: var(--text-muted);">${item.strategy || '-'} · ${sem.details}</div>
                    <div style="font-size:0.74rem; color:${sem.color}; margin-top:2px;">${sem.action}</div>
                </div>
                <span style="font-size:0.68rem; border:1px solid ${sem.color}; color:${sem.color}; border-radius:10px; padding:2px 8px; white-space:nowrap;">${sem.level}</span>
            </div>
        `).join('');
    }

    function renderIntelligenceTop(summary = {}, rows = [], selectedWindow = 24, selectedMinTrades = 8) {
        const orderedRows = sortInsightsRows(rows);

        if (intelligenceTopSummary) {
            const botsAnalyzed = summary.bots_analyzed ?? orderedRows.length;
            const productionCandidates = summary.production_candidates ?? orderedRows.filter(r => r.candidate_for_production).length;
            const criticalAlertsOpen = summary.critical_alerts_open ?? 0;
            const runtimeReady = orderedRows.filter(r => r.runtime_ready).length;

            intelligenceTopSummary.innerHTML = `
                <div style="padding:10px; border:1px solid rgba(255,255,255,0.08); border-radius:10px; background: rgba(255,255,255,0.02);">
                    <div style="font-size:0.68rem; color: var(--text-muted); text-transform: uppercase;">Ventana activa</div>
                    <div style="font-size:0.9rem; font-weight:700; color: var(--text-secondary); margin-top:4px;">${selectedWindow}h / min ${selectedMinTrades} trades</div>
                </div>
                <div style="padding:10px; border:1px solid rgba(255,255,255,0.08); border-radius:10px; background: rgba(255,255,255,0.02);">
                    <div style="font-size:0.68rem; color: var(--text-muted); text-transform: uppercase;">Bots analizados</div>
                    <div style="font-size:1rem; font-weight:700; color: var(--text-secondary); margin-top:4px;">${botsAnalyzed}</div>
                </div>
                <div style="padding:10px; border:1px solid rgba(255,255,255,0.08); border-radius:10px; background: rgba(16,185,129,0.08);">
                    <div style="font-size:0.68rem; color: var(--text-muted); text-transform: uppercase;">Candidatos producción</div>
                    <div style="font-size:1rem; font-weight:700; color: var(--accent-emerald); margin-top:4px;">${productionCandidates}</div>
                    <div style="font-size:0.68rem; color: var(--text-muted); margin-top:2px;">Running listos: ${runtimeReady}</div>
                </div>
                <div style="padding:10px; border:1px solid rgba(255,255,255,0.08); border-radius:10px; background: rgba(239,68,68,0.08);">
                    <div style="font-size:0.68rem; color: var(--text-muted); text-transform: uppercase;">Alertas críticas</div>
                    <div style="font-size:1rem; font-weight:700; color: var(--accent-ruby); margin-top:4px;">${criticalAlertsOpen}</div>
                </div>
            `;
        }

        if (!intelligenceTopTableBody) return;

        if (!orderedRows.length) {
            intelligenceTopTableBody.innerHTML = '<tr><td colspan="8" style="text-align:center; padding: 1rem; color: var(--text-muted);">No hay datos de pruebas para este rango.</td></tr>';
            return;
        }

        intelligenceTopTableBody.innerHTML = orderedRows.slice(0, 8).map((item) => {
            const m = item.metrics || {};
            const rec = item.recommendation || {};
            const suggested = rec.suggested_params || {};
            const levelInfo = recommendationLevelLabel(rec.level);
            const readiness = buildProductionReadiness(item, selectedMinTrades);
            const payloadAttr = JSON.stringify(suggested).replace(/'/g, '&apos;');
            const hasSuggested = Object.keys(suggested).length > 0;
            const netPnl = Number(m.net_pnl || 0);
            const pnlColor = netPnl >= 0 ? 'var(--accent-emerald)' : 'var(--accent-ruby)';
            const runtimeLabel = item.runtime_ready
                ? '<span style="font-size:0.66rem; border:1px solid var(--accent-blue); color: var(--accent-blue); border-radius:10px; padding:2px 7px;">RUNNING</span>'
                : `<span style="font-size:0.66rem; border:1px solid ${levelInfo.color}; color: ${levelInfo.color}; border-radius:10px; padding:2px 7px;">${levelInfo.label}</span>`;
            const alertCount = item.open_critical_alerts ?? item.critical_open_alerts ?? 0;

            return `
                <tr>
                    <td><strong>${item.bot_id}</strong><div style="font-size:0.68rem; color: var(--text-muted); margin-top:3px;">${item.strategy || '-'}</div></td>
                    <td>${runtimeLabel}</td>
                    <td>${m.win_rate ?? 0}%</td>
                    <td style="color:${pnlColor}; font-weight:700;">${netPnl >= 0 ? '+' : ''}${netPnl.toFixed(2)}</td>
                    <td>${m.scored_trades ?? 0}</td>
                    <td style="color:${alertCount > 0 ? 'var(--accent-ruby)' : 'var(--text-secondary)'};">${alertCount}</td>
                    <td>
                        <span style="font-size:0.66rem; border:1px solid ${readiness.color}; color:${readiness.color}; border-radius:10px; padding:2px 7px;">${readiness.label}</span>
                        <div style="font-size:0.64rem; color: var(--text-muted); margin-top:3px; max-width:180px;">${readiness.reasonText}</div>
                    </td>
                    <td style="text-align:right;">
                        <div style="display:flex; justify-content:flex-end; gap:6px; flex-wrap:wrap;">
                            <button class="validate-test-bot" data-bot-id="${item.bot_id}" style="padding:4px 8px; border:1px solid #facc15; color:#facc15; background: transparent; border-radius:7px; cursor:pointer; font-size:0.68rem;">VALIDAR</button>
                            <button class="apply-test-recommendation" data-bot-id="${item.bot_id}" data-payload='${payloadAttr}' ${hasSuggested ? '' : 'disabled'} style="padding:4px 8px; border:1px solid var(--accent-blue); color: var(--accent-blue); background: transparent; border-radius:7px; cursor:${hasSuggested ? 'pointer' : 'not-allowed'}; font-size:0.68rem; opacity:${hasSuggested ? '1' : '0.5'};">AJUSTAR</button>
                            <button class="start-test-bot" data-bot-id="${item.bot_id}" style="padding:4px 8px; border:1px solid var(--accent-emerald); color: var(--accent-emerald); background: transparent; border-radius:7px; cursor:pointer; font-size:0.68rem;">INICIAR</button>
                            <button class="activate-prod-bot" data-bot-id="${item.bot_id}" ${readiness.ready ? '' : 'disabled'} style="padding:4px 8px; border:1px solid ${readiness.ready ? 'var(--accent-emerald)' : 'rgba(239,68,68,0.55)'}; color: ${readiness.ready ? 'var(--accent-emerald)' : 'rgba(239,68,68,0.75)'}; background: ${readiness.ready ? 'rgba(16,185,129,0.08)' : 'rgba(239,68,68,0.06)'}; border-radius:7px; cursor:${readiness.ready ? 'pointer' : 'not-allowed'}; font-size:0.68rem; opacity:${readiness.ready ? '1' : '0.75'};">${readiness.ready ? 'PROD' : 'BLOQ'}</button>
                        </div>
                    </td>
                </tr>
            `;
        }).join('');
    }

    async function fetchTestInsights() {
        if (!testInsightsContent && !intelligenceTopSummary && !intelligenceTopTableBody) return;

        try {
            const selectedWindow = Math.max(1, parseInt(testInsightsWindow?.value || '24', 10) || 24);
            const selectedMinTrades = Math.max(1, parseInt(testInsightsMinTrades?.value || '8', 10) || 8);
            const response = await fetch('/api/monitoring/test-results', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ lookback_hours: selectedWindow, min_scored_trades: selectedMinTrades })
            });
            if (!response.ok) {
                const err = await response.json();
                throw new Error(err.detail || 'No se pudo calcular resultados');
            }

            const payload = await response.json();
            const summary = payload.summary || {};
            const rows = Array.isArray(payload.results) ? payload.results : [];
            const orderedRows = sortInsightsRows(rows);

            try {
                renderIntelligenceTop(summary, orderedRows, selectedWindow, selectedMinTrades);
            } catch (renderError) {
                console.error('Error rendering intelligence top table:', renderError);
                if (intelligenceTopTableBody) {
                    intelligenceTopTableBody.innerHTML = '<tr><td colspan="8" style="text-align:center; padding: 1rem; color: var(--accent-ruby);">Error renderizando la tabla de control.</td></tr>';
                }
            }

            try {
                renderBotTrafficLightPanel(summary, orderedRows, selectedMinTrades);
            } catch (semaphoreError) {
                console.error('Error rendering traffic light panel:', semaphoreError);
            }

            if (!orderedRows.length) {
                if (testInsightsContent) {
                    testInsightsContent.innerHTML = '<div style="color: var(--text-muted);">No hay datos de pruebas para analizar.</div>';
                }
                return;
            }

            const header = `
                <div style="margin-bottom: 12px; padding: 10px; border:1px solid rgba(255,255,255,0.08); border-radius:10px; background: rgba(255,255,255,0.02); display:grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap:8px;">
                    <div style="font-size:0.74rem; color: var(--text-secondary);">Ventana<br><strong>${selectedWindow}h</strong></div>
                    <div style="font-size:0.74rem; color: var(--text-secondary);">Mínimo trades<br><strong>${selectedMinTrades}</strong></div>
                    <div style="font-size:0.74rem; color: var(--accent-emerald);">Aptos producción<br><strong>${summary.production_candidates ?? 0}</strong></div>
                    <div style="font-size:0.74rem; color: var(--accent-ruby);">Alertas críticas<br><strong>${summary.critical_alerts_open ?? 0}</strong></div>
                </div>
            `;

            if (testInsightsContent) {
                testInsightsContent.innerHTML = header + renderProductionEligibilityGroups(orderedRows, selectedMinTrades);
            }
        } catch (error) {
            console.error('Error fetching test insights:', error);
            if (testInsightsContent) {
                testInsightsContent.innerHTML = `<div style="color: var(--accent-ruby);">Error cargando insights: ${error.message}</div>`;
            }
            if (intelligenceTopSummary) {
                intelligenceTopSummary.innerHTML = '<div style="padding:10px; border:1px solid rgba(239,68,68,0.45); border-radius:10px; color: var(--accent-ruby);">No se pudo cargar el Centro de Control.</div>';
            }
            if (intelligenceTopTableBody) {
                intelligenceTopTableBody.innerHTML = `<tr><td colspan="8" style="text-align:center; padding: 1rem; color: var(--accent-ruby);">Error cargando datos: ${error.message}</td></tr>`;
            }
            if (botTrafficLightHeader) {
                botTrafficLightHeader.innerHTML = '<strong>Semáforo Global:</strong> <span style="color: var(--accent-ruby); font-weight:700;">ERROR</span> · no se pudo calcular estado';
            }
            if (botTrafficLightSummary) {
                botTrafficLightSummary.innerHTML = '<div style="padding:10px; border:1px solid rgba(239,68,68,0.45); border-radius:10px; color: var(--accent-ruby);">Sin datos de semáforo.</div>';
            }
            if (botTrafficLightList) {
                botTrafficLightList.innerHTML = `<div style="color: var(--accent-ruby);">Error calculando semáforo: ${error.message}</div>`;
            }
        }
    }


    // --- DELEGATED BOT MODAL LOGIC ---


    // --- DELEGATED BOT MODAL LOGIC ---
    // Using delegation because these elements may be injected dynamically
    document.addEventListener('click', async (e) => {
        const createBtn = e.target.closest('#createBotBtn');
        const closeBtn = e.target.closest('[data-action="close-modal"]') || e.target.closest('#closeModal');
        const confirmBtn = e.target.closest('#confirmCreateBot');
        const saveVaultBtn = e.target.closest('#confirmSaveVaultBot');
        const analyzeBtn = e.target.closest('#analyzeBotBtn');
        const advisorApplyBtn = e.target.closest('.advisor-apply-btn');
        const advisorCreateBtn = e.target.closest('.advisor-create-btn');
        const advisorAutoBtn = e.target.closest('.advisor-auto-btn');
        const assetAdvisorApplyBtn = e.target.closest('.asset-advisor-apply');
        const assetAdvisorCreateBtn = e.target.closest('.asset-advisor-create');
        const assetAdvisorAutoBtn = e.target.closest('.asset-advisor-auto');
        const applyTestRecommendation = e.target.closest('.apply-test-recommendation');
        const startTestBotBtn = e.target.closest('.start-test-bot');
        const validateTestBotBtn = e.target.closest('.validate-test-bot');
        const activateProdBotBtn = e.target.closest('.activate-prod-bot');

        if (createBtn) {
            const modal = document.getElementById('createBotModal');
            if (modal) {
                modal.style.display = 'flex';
                // Force refocus/re-render to be sure
                const idInput = document.getElementById('newBotId');
                if (idInput) idInput.value = `Bot-${Math.floor(Math.random() * 1000)}`;
                autoPopulateGridLimits(false);
            }
        }

        if (closeBtn) {
            window.closeCreateBotModal();
        }

        if (confirmBtn) {
            const executor = document.getElementById('newBotExecutor')?.value || 'paper';
            const presetId = document.getElementById('newBotPreset')?.value || '';
            const strategy = document.getElementById('newBotStrategy')?.value || 'ema_cross';
            const botConfig = {
                id: document.getElementById('newBotId')?.value,
                symbol: document.getElementById('newBotSymbol')?.value,
                strategy: strategy,
                fast_ema: parseInt(document.getElementById('newBotFastEma')?.value || 9),
                slow_ema: parseInt(document.getElementById('newBotSlowEma')?.value || 21),
                upper_limit: parseFloat(document.getElementById('newBotUpperLimit')?.value || 70000),
                lower_limit: parseFloat(document.getElementById('newBotLowerLimit')?.value || 60000),
                num_grids: parseInt(document.getElementById('newBotNumGrids')?.value || 10),
                capital_allocation: parseFloat(document.getElementById('newBotAllocation')?.value || 0),
                executor: executor,
                risk_config: { max_drawdown: 0.05 }
            };

            if (strategy === 'paired_balanced') {
                botConfig.allow_short = true;
                botConfig.pair_symbol_a = botConfig.symbol;
                botConfig.pair_symbol_b = document.getElementById('newBotPairSymbolB')?.value || 'ETH/USDT';
                botConfig.pair_entry_z = parseFloat(document.getElementById('newBotPairEntryZ')?.value || 1.4);
                botConfig.pair_exit_z = parseFloat(document.getElementById('newBotPairExitZ')?.value || 0.25);
                botConfig.pair_stop_loss_pct = parseFloat(document.getElementById('newBotPairStopLossPct')?.value || 0.015);
                botConfig.pair_take_profit_pct = parseFloat(document.getElementById('newBotPairTakeProfitPct')?.value || 0.01);
                botConfig.pair_profit_lock_pct = parseFloat(document.getElementById('newBotPairProfitLockPct')?.value || 0.004);
                botConfig.pair_min_correlation = parseFloat(document.getElementById('newBotPairMinCorr')?.value || 0.35);
                botConfig.pair_lookback = 120;
                botConfig.pair_min_hold_sec = 90;
                botConfig.pair_rebalance_sec = 30;
            }

            if (executor === 'hyperliquid') {
                const ok = confirm(`⚠️ ADVERTENCIA: Este bot usará FONDOS REALES en Hyperliquid Mainnet.\n\nPar: ${botConfig.symbol}\nEstrategia: ${botConfig.strategy}\n\n¿Confirmas el lanzamiento?`);
                if (!ok) return;
            }

            try {
                let response;

                if (presetId) {
                    response = await fetch(`/api/bot-presets/${presetId}/create`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            id: botConfig.id,
                            overrides: {
                                symbol: botConfig.symbol,
                                executor: botConfig.executor,
                                fast_ema: botConfig.fast_ema,
                                slow_ema: botConfig.slow_ema,
                                upper_limit: botConfig.upper_limit,
                                lower_limit: botConfig.lower_limit,
                                num_grids: botConfig.num_grids,
                                capital_allocation: botConfig.capital_allocation,
                            }
                        })
                    });
                } else {
                    response = await fetch('/api/bots', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(botConfig)
                    });
                }

                if (response.ok) {
                    const modal = document.getElementById('createBotModal');
                    if (modal) modal.style.display = 'none';
                    fetchBots();
                } else {
                    const error = await response.json();
                    alert('Error creating bot: ' + error.detail);
                }
            } catch (error) {
                console.error('Network error creating bot:', error);
            }
        }

        if (saveVaultBtn) {
            const presetId = document.getElementById('newBotPreset')?.value || '';
            if (!presetId) {
                alert('Selecciona primero un preset para guardar en Cápsula.');
                return;
            }

            const strategy = document.getElementById('newBotStrategy')?.value || 'ema_cross';
            const botConfig = {
                id: document.getElementById('newBotId')?.value,
                symbol: document.getElementById('newBotSymbol')?.value,
                strategy: strategy,
                fast_ema: parseInt(document.getElementById('newBotFastEma')?.value || 9),
                slow_ema: parseInt(document.getElementById('newBotSlowEma')?.value || 21),
                upper_limit: parseFloat(document.getElementById('newBotUpperLimit')?.value || 70000),
                lower_limit: parseFloat(document.getElementById('newBotLowerLimit')?.value || 60000),
                num_grids: parseInt(document.getElementById('newBotNumGrids')?.value || 10),
                capital_allocation: parseFloat(document.getElementById('newBotAllocation')?.value || 0),
                executor: document.getElementById('newBotExecutor')?.value || 'paper',
            };

            if (strategy === 'paired_balanced') {
                botConfig.allow_short = true;
                botConfig.pair_symbol_a = botConfig.symbol;
                botConfig.pair_symbol_b = document.getElementById('newBotPairSymbolB')?.value || 'ETH/USDT';
                botConfig.pair_entry_z = parseFloat(document.getElementById('newBotPairEntryZ')?.value || 1.4);
                botConfig.pair_exit_z = parseFloat(document.getElementById('newBotPairExitZ')?.value || 0.25);
                botConfig.pair_stop_loss_pct = parseFloat(document.getElementById('newBotPairStopLossPct')?.value || 0.015);
                botConfig.pair_take_profit_pct = parseFloat(document.getElementById('newBotPairTakeProfitPct')?.value || 0.01);
                botConfig.pair_profit_lock_pct = parseFloat(document.getElementById('newBotPairProfitLockPct')?.value || 0.004);
                botConfig.pair_min_correlation = parseFloat(document.getElementById('newBotPairMinCorr')?.value || 0.35);
                botConfig.pair_lookback = 120;
                botConfig.pair_min_hold_sec = 90;
                botConfig.pair_rebalance_sec = 30;
            }

            try {
                const response = await fetch(`/api/bot-presets/${presetId}/save`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        id: botConfig.id,
                        overrides: {
                            symbol: botConfig.symbol,
                            executor: botConfig.executor,
                            fast_ema: botConfig.fast_ema,
                            slow_ema: botConfig.slow_ema,
                            upper_limit: botConfig.upper_limit,
                            lower_limit: botConfig.lower_limit,
                            num_grids: botConfig.num_grids,
                            capital_allocation: botConfig.capital_allocation,
                        }
                    })
                });

                if (response.ok) {
                    const modal = document.getElementById('createBotModal');
                    if (modal) modal.style.display = 'none';
                    fetchBots();
                } else {
                    const error = await response.json();
                    alert('Error guardando en cápsula: ' + (error.detail || 'Error desconocido'));
                }
            } catch (error) {
                console.error('Network error saving bot to vault:', error);
            }
        }

        if (analyzeBtn) {
            const symbol = document.getElementById('newBotSymbol')?.value || 'BTC/USDT';
            const allocation = parseFloat(document.getElementById('newBotAllocation')?.value || 500);
            analyzeBtn.disabled = true;
            analyzeBtn.textContent = 'ANALIZANDO...';

            try {
                const response = await fetch('/api/bot-advisor/analyze', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ symbol, allocation })
                });
                if (!response.ok) {
                    const err = await response.json();
                    alert('Error de análisis: ' + (err.detail || 'Error desconocido'));
                } else {
                    const data = await response.json();
                    renderAdvisorResults(data);
                }
            } catch (error) {
                console.error('Advisor analyze error:', error);
                alert('No se pudo completar el análisis en este momento.');
            } finally {
                analyzeBtn.disabled = false;
                analyzeBtn.textContent = 'ANALIZAR Y RECOMENDAR (CORTO/MEDIO/LARGO)';
            }
        }

        if (advisorApplyBtn) {
            const horizon = advisorApplyBtn.dataset.horizon;
            const rec = advisorMap[horizon];
            if (!rec) return;
            const useExistingConfig = rec.recommended_action === 'tune_existing' || rec.recommended_action === 'reduce_risk';
            const configToApply = useExistingConfig ? rec.edited_config : rec.new_bot_config;
            applyConfigToCreateForm(configToApply);
        }

        if (advisorCreateBtn) {
            const horizon = advisorCreateBtn.dataset.horizon;
            const rec = advisorMap[horizon];
            if (!rec) return;

            const configToCreate = rec.new_bot_config || rec.edited_config;
            if (!configToCreate) return;

            const baseId = document.getElementById('newBotId')?.value?.trim() || `Bot-${horizon}`;
            const uniqueId = `${baseId}-${Math.floor(Math.random() * 10000)}`;

            const payload = {
                ...configToCreate,
                id: uniqueId
            };

            try {
                const response = await fetch('/api/bots', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                if (!response.ok) {
                    const err = await response.json();
                    alert('No se pudo crear el bot: ' + (err.detail || 'Error desconocido'));
                } else {
                    fetchBots();
                    alert(`Bot creado: ${uniqueId}`);
                }
            } catch (error) {
                console.error('Advisor create bot error:', error);
            }
        }

        if (advisorAutoBtn) {
            const horizon = advisorAutoBtn.dataset.horizon;
            const symbol = document.getElementById('newBotSymbol')?.value || 'BTC/USDT';
            const allocation = parseFloat(document.getElementById('newBotAllocation')?.value || 500);

            advisorAutoBtn.disabled = true;
            const prevText = advisorAutoBtn.textContent;
            advisorAutoBtn.textContent = 'EJECUTANDO...';

            try {
                const response = await fetch('/api/bot-advisor/execute', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ horizon, symbol, allocation, force_new: true })
                });

                if (!response.ok) {
                    const err = await response.json();
                    alert('No se pudo auto-ejecutar: ' + (err.detail || 'Error desconocido'));
                } else {
                    const data = await response.json();
                    fetchBots();
                    alert(data.message || 'Auto-ejecución completada');
                }
            } catch (error) {
                console.error('Advisor auto execute error:', error);
                alert('Error de red al auto-ejecutar recomendación.');
            } finally {
                advisorAutoBtn.disabled = false;
                advisorAutoBtn.textContent = prevText;
            }
        }

        if (assetAdvisorApplyBtn) {
            const horizon = assetAdvisorApplyBtn.dataset.horizon;
            const rec = assetAdvisorMap[horizon];
            if (!rec) return;
            const configToApply = rec.new_bot_config || rec.edited_config;
            if (!configToApply) return;

            const symbol = asset30dSymbol?.value || configToApply.symbol || 'BTC/USDT';
            const patched = { ...configToApply, symbol, executor: 'paper' };
            applyConfigToCreateForm(patched);

            const modal = document.getElementById('createBotModal');
            if (modal) modal.style.display = 'flex';
        }

        if (assetAdvisorCreateBtn) {
            const horizon = assetAdvisorCreateBtn.dataset.horizon;
            const rec = assetAdvisorMap[horizon];
            if (!rec) return;

            const configToCreate = rec.new_bot_config || rec.edited_config;
            if (!configToCreate) return;

            const symbol = asset30dSymbol?.value || configToCreate.symbol || 'BTC/USDT';
            const baseId = symbol.replace(/[^A-Za-z0-9]+/g, '-');
            const uniqueId = `Asset-${baseId}-${horizon}-${Math.floor(Math.random() * 10000)}`;
            const payload = { ...configToCreate, id: uniqueId, symbol, executor: 'paper' };

            try {
                const response = await fetch('/api/bots', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                if (!response.ok) {
                    const err = await response.json();
                    alert('No se pudo crear el bot: ' + (err.detail || 'Error desconocido'));
                } else {
                    resetBotFilters();
                    openTab('bots');
                    alert(`Bot creado: ${uniqueId}`);
                }
            } catch (error) {
                console.error('Asset advisor create bot error:', error);
            }
        }

        if (assetAdvisorAutoBtn) {
            const horizon = assetAdvisorAutoBtn.dataset.horizon;
            const symbol = asset30dSymbol?.value || 'BTC/USDT';
            const allocation = parseFloat(asset30dAllocation?.value || 500);

            assetAdvisorAutoBtn.disabled = true;
            const prevText = assetAdvisorAutoBtn.textContent;
            assetAdvisorAutoBtn.textContent = 'EJECUTANDO...';

            try {
                const response = await fetch('/api/bot-advisor/execute', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ horizon, symbol, allocation, force_new: true })
                });

                if (!response.ok) {
                    const err = await response.json();
                    alert('No se pudo auto-ejecutar: ' + (err.detail || 'Error desconocido'));
                } else {
                    const data = await response.json();
                    resetBotFilters();
                    openTab('bots');
                    alert(data.message || 'Auto-ejecucion completada');
                }
            } catch (error) {
                console.error('Asset advisor auto execute error:', error);
                alert('Error de red al auto-ejecutar recomendacion.');
            } finally {
                assetAdvisorAutoBtn.disabled = false;
                assetAdvisorAutoBtn.textContent = prevText;
            }
        }


        if (applyTestRecommendation) {
            const botId = applyTestRecommendation.dataset.botId;
            if (!botId) return;

            let parsedPayload = {};
            try {
                parsedPayload = JSON.parse(applyTestRecommendation.dataset.payload || '{}');
            } catch (_) {
                parsedPayload = {};
            }

            if (!Object.keys(parsedPayload).length) {
                alert('No hay parámetros recomendados para aplicar en este bot.');
                return;
            }

            try {
                const response = await fetch(`/api/bots/${botId}`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(parsedPayload)
                });
                if (!response.ok) {
                    const err = await response.json();
                    throw new Error(err.detail || 'No se pudo aplicar recomendación');
                }
                fetchBots();
                fetchTestInsights();
                alert(`Ajuste aplicado a ${botId}`);
            } catch (error) {
                console.error('Error applying test recommendation:', error);
                alert('No se pudo aplicar recomendación: ' + error.message);
            }
        }

        if (startTestBotBtn) {
            const botId = startTestBotBtn.dataset.botId;
            if (!botId) return;
            try {
                const response = await fetch(`/api/bots/${botId}/start`, { method: 'POST' });
                if (!response.ok) {
                    const err = await response.json();
                    throw new Error(err.detail || 'No se pudo iniciar bot');
                }
                fetchBots();
                fetchTestInsights();
            } catch (error) {
                console.error('Error starting bot from test insight:', error);
                alert('No se pudo iniciar bot: ' + error.message);
            }
        }

        if (validateTestBotBtn) {
            const botId = validateTestBotBtn.dataset.botId;
            if (!botId) return;
            try {
                const response = await fetch(`/api/monitoring/recommendations/${botId}/why-not-running`);
                if (!response.ok) {
                    const err = await response.json();
                    throw new Error(err.detail || 'No se pudo validar bot');
                }
                const data = await response.json();
                const reasons = data.reasons || [];
                const actions = (data.suggested_actions || []).join(' | ') || 'sin acciones sugeridas';
                if (reasons.length === 1 && reasons[0] === 'no_blocking_issue_detected') {
                    await activateProductionForBot(botId);
                } else {
                    const reasonText = reasons.join(', ') || 'sin bloqueos';
                    alert(`Validacion ${botId}\nRazones: ${reasonText}\nAcciones: ${actions}`);
                }
            } catch (error) {
                console.error('Error validating bot:', error);
                alert('No se pudo validar bot: ' + error.message);
            }
        }

        if (activateProdBotBtn) {
            const botId = activateProdBotBtn.dataset.botId;
            if (!botId) return;
            try {
                await activateProductionForBot(botId);
            } catch (error) {
                console.error('Error activating production bot:', error);
                alert('No se pudo activar en producción: ' + error.message);
            }
        }
    });

    if (refreshMainnetVisualBtn) {
        refreshMainnetVisualBtn.addEventListener('click', loadMainnetVisualControl);
    }


    if (saveHyperliquidSettingsBtn) {
        saveHyperliquidSettingsBtn.addEventListener('click', saveHyperliquidSettings);
    }

    if (refreshRuntimeOpsBtn) {
        refreshRuntimeOpsBtn.addEventListener('click', loadRuntimeOpsStatus);
    }

    if (refreshTakeProfitAdaptiveBtn) {
        refreshTakeProfitAdaptiveBtn.addEventListener('click', loadTakeProfitAdaptiveStatus);
    }

    if (startRuntimeOpsBtn) {
        startRuntimeOpsBtn.addEventListener('click', startRuntimeOps);
    }

    if (stopRuntimeOpsBtn) {
        stopRuntimeOpsBtn.addEventListener('click', stopRuntimeOps);
    }

    if (toggleRuntimeOpsOverviewBtn) {
        toggleRuntimeOpsOverviewBtn.addEventListener('click', toggleRuntimeOpsOverview);
    }

    if (refreshTestInsights) {
        refreshTestInsights.addEventListener('click', fetchTestInsights);
    }

    if (refreshIntelligenceTop) {
        refreshIntelligenceTop.addEventListener('click', fetchTestInsights);
    }

    if (generateBotFromTextBtn) {
        generateBotFromTextBtn.addEventListener('click', generateBotParamsFromPrompt);
    }

    if (testInsightsWindow) {
        testInsightsWindow.addEventListener('change', fetchTestInsights);
    }

    if (testInsightsMinTrades) {
        testInsightsMinTrades.addEventListener('change', fetchTestInsights);
    }

    if (asset30dAnalyzeBtn) {
        asset30dAnalyzeBtn.addEventListener('click', runAsset30dAnalysis);
    }

    if (asset30dRecommendBtn) {
        asset30dRecommendBtn.addEventListener('click', runAsset30dRecommendation);
    }

    if (microScalpCreateBtn) {
        microScalpCreateBtn.addEventListener('click', createMicroScalpBot);
    }

    // Delegated Change listener for Executor dropdown
    document.addEventListener('change', (e) => {
        if (e.target.id === 'newBotExecutor') {
            const isLive = e.target.value === 'hyperliquid';
            const warning = document.getElementById('executorWarning');
            const symbolInput = document.getElementById('newBotSymbol');

            if (warning) warning.style.display = isLive ? 'block' : 'none';
            if (symbolInput) {
                if (isLive && symbolInput.value === 'BTC/USDT') {
                    symbolInput.value = 'BTC/USDC:USDC';
                } else if (!isLive && symbolInput.value === 'BTC/USDC:USDC') {
                    symbolInput.value = 'BTC/USDT';
                }
                autoPopulateGridLimits(true);
            }
        }

        if (e.target.id === 'newBotStrategy') {
            const strategy = e.target.value;
            const emaParams = document.getElementById('emaParams');
            const gridParams = document.getElementById('gridParams');
            const pairParams = document.getElementById('pairParams');

            if (emaParams && gridParams && pairParams) {
                if (strategy === 'grid_trading') {
                    emaParams.style.display = 'none';
                    gridParams.style.display = 'block';
                    pairParams.style.display = 'none';
                } else if (strategy === 'ema_cross') {
                    emaParams.style.display = 'block';
                    gridParams.style.display = 'none';
                    pairParams.style.display = 'none';
                } else if (strategy === 'paired_balanced') {
                    emaParams.style.display = 'none';
                    gridParams.style.display = 'none';
                    pairParams.style.display = 'block';
                } else {
                    emaParams.style.display = 'none';
                    gridParams.style.display = 'none';
                    pairParams.style.display = 'none';
                }
                if (strategy === 'grid_trading') {
                    autoPopulateGridLimits(false);
                }
            }
        }

        if (e.target.id === 'newBotSymbol') {
            autoPopulateGridLimits(true);
        }

        if (e.target.id === 'newBotPreset') {
            const presetId = e.target.value;
            const selectedPreset = botPresets.find((preset) => preset.id === presetId);
            renderPresetQuickDoc(selectedPreset || null);
            if (selectedPreset) {
                applyPresetToCreateForm(selectedPreset);
            }
        }
    });


    // --- BOT ACTIONS (PLAY, PAUSE, DELETE, ARCHIVE, RESTORE) ---
    const handleBotActions = async (e) => {
        const actionIcon = e.target.closest('.bot-action');
        const editIcon = e.target.closest('.edit-bot-btn');
        const deleteIcon = e.target.closest('.delete-bot-btn');
        const archiveIcon = e.target.closest('.archive-bot-btn');
        const restoreIcon = e.target.closest('.restore-bot-btn');
        const restoreStartIcon = e.target.closest('.restore-start-bot-btn');

        if (!actionIcon && !editIcon && !deleteIcon && !archiveIcon && !restoreIcon && !restoreStartIcon) {
            return;
        }

        if (actionIcon) {
            if (actionIcon.disabled) return;
            const botId = actionIcon.dataset.id;
            const isCurrentlyRunning = actionIcon.dataset.running === 'true';
            const endpoint = isCurrentlyRunning ? `/api/bots/${botId}/stop` : `/api/bots/${botId}/start`;

            actionIcon.style.opacity = '0.5';
            actionIcon.disabled = true; // Prevent spam clicks

            try {
                const response = await fetch(endpoint, { method: 'POST' });
                if (!response.ok) {
                    const err = await response.json();
                    alert('Action failed: ' + err.detail);
                }
                fetchBots();
            } catch (error) {
                console.error('Bot action error:', error);
            } finally {
                actionIcon.style.opacity = '1';
                actionIcon.disabled = false;
            }
        }

        if (editIcon) {
            const botId = editIcon.dataset.id;
            try {
                const response = await fetch('/api/bots');
                if (!response.ok) {
                    throw new Error('No se pudo cargar la lista de bots');
                }

                const bots = await response.json();
                const bot = bots.find((item) => item.id === botId);

                if (!bot) {
                    alert(`No se encontró el bot ${botId}`);
                    return;
                }

                showEditBotModal(bot);
            } catch (error) {
                console.error('Edit bot error:', error);
                alert('Error al abrir la edición del bot.');
            }
        }

        if (archiveIcon) {
            const botId = archiveIcon.dataset.id;
            showCustomConfirm(
                'Archive Bot',
                `Are you sure you want to stop and archive "${botId}"? It can be restored later from the Vault.`,
                async () => {
                    try {
                        const response = await fetch(`/api/bots/${botId}/archive`, { method: 'POST' });
                        if (response.ok) fetchBots();
                        else {
                            const err = await response.json();
                            alert('Archive failed: ' + err.detail);
                        }
                    } catch (error) {
                        console.error('Archive bot error:', error);
                    }
                }
            );
        }

        if (restoreIcon) {
            const botId = restoreIcon.dataset.id;
            try {
                const response = await fetch(`/api/bots/${botId}/restore`, { method: 'POST' });
                if (response.ok) fetchBots();
            } catch (error) {
                console.error('Restore bot error:', error);
            }
        }

        if (restoreStartIcon) {
            const botId = restoreStartIcon.dataset.id;
            try {
                const restoreResponse = await fetch(`/api/bots/${botId}/restore`, { method: 'POST' });
                if (!restoreResponse.ok) {
                    const err = await restoreResponse.json();
                    alert('Restore failed: ' + (err.detail || 'Unknown error'));
                    return;
                }

                const startResponse = await fetch(`/api/bots/${botId}/start`, { method: 'POST' });
                if (!startResponse.ok) {
                    const err = await startResponse.json();
                    alert('Start failed: ' + (err.detail || 'Unknown error'));
                    return;
                }

                fetchBots();
            } catch (error) {
                console.error('Restore + start bot error:', error);
            }
        }

        if (deleteIcon) {
            const botId = deleteIcon.dataset.id;
            showCustomConfirm(
                'Delete Bot',
                `Permanently delete "${botId}"? This action cannot be undone and all data will be lost.`,
                async () => {
                    try {
                        const response = await fetch(`/api/bots/${botId}`, { method: 'DELETE' });
                        if (response.ok) fetchBots();
                        else {
                            const err = await response.json();
                            alert('Delete failed: ' + err.detail);
                        }
                    } catch (error) {
                        console.error('Delete bot error:', error);
                    }
                }
            );
        }
    };

    // Document-level delegation keeps actions working even after dynamic table rerenders.
    document.addEventListener('click', handleBotActions);

    [botFilterSearch, botFilterStrategy, botFilterStatus].forEach((control) => {
        if (!control) return;
        control.addEventListener('input', fetchBots);
        control.addEventListener('change', fetchBots);
    });

    // -- Live Stats Fetch --
    async function fetchStats() {
        try {
            const res = await fetch('/api/stats');
            const s = await res.json();
            dashboardState.stats = s;

            const pnlEl = document.getElementById('statTotalPnl');
            const feesEl = document.getElementById('statTotalFees');
            const winRateEl = document.getElementById('statWinRate');
            const winRateBar = document.getElementById('statWinRateBar');
            const openPosEl = document.getElementById('statOpenPositions');
            const openOrdEl = document.getElementById('statOpenOrders');
            const winLossEl = document.getElementById('statWinLoss');
            const volEl = document.getElementById('statTotalVolume');
            const netPnl = (typeof s.net_pnl === 'number') ? s.net_pnl : (s.total_pnl - s.total_fees);

            if (pnlEl) {
                pnlEl.textContent = `${netPnl >= 0 ? '+' : ''}$${netPnl.toFixed(2)}`;
                pnlEl.style.color = netPnl >= 0 ? 'var(--accent-emerald)' : 'var(--accent-ruby)';
            }
            if (feesEl) feesEl.textContent = `$${s.total_fees.toFixed(4)}`;
            if (winRateEl) winRateEl.textContent = `${s.win_rate}%`;
            if (winRateBar) winRateBar.style.width = `${s.win_rate}%`;
            if (openPosEl) openPosEl.textContent = s.open_positions;
            if (openOrdEl) openOrdEl.textContent = `Órdenes en log: ${s.open_orders + s.total_trades}`;
            if (winLossEl) winLossEl.textContent = `${s.wins} wins / ${s.losses} losses`;
            if (volEl) volEl.textContent = `Volumen: $${(s.total_volume).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;

            refreshDerivedVisuals();
        } catch (e) {
            console.error('fetchStats error:', e);
        }
    }


    // --- REFINEMENTS: SPARKLINES & PREVIEWS ---

    function drawSparkline(canvasId, data, color = '#38bdf8') {
        const canvas = typeof canvasId === 'string' ? document.getElementById(canvasId) : canvasId;
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        const width = canvas.width;
        const height = canvas.height;

        ctx.clearRect(0, 0, width, height);
        if (data.length < 2) return;

        const min = Math.min(...data);
        const max = Math.max(...data);
        const range = max - min || 1;

        ctx.beginPath();
        ctx.strokeStyle = color;
        ctx.lineWidth = 2;
        ctx.lineJoin = 'round';

        data.forEach((val, i) => {
            const x = (i / (data.length - 1)) * width;
            const y = height - ((val - min) / range) * height;
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        });

        ctx.stroke();

        // Fill area
        ctx.lineTo(width, height);
        ctx.lineTo(0, height);
        const gradient = ctx.createLinearGradient(0, 0, 0, height);
        gradient.addColorStop(0, color + '33');
        gradient.addColorStop(1, 'transparent');
        ctx.fillStyle = gradient;
        ctx.fill();
    }

    function showPreview(e, title, data, stats, bot = null) {
        if (!previewPopup) return;

        previewTitle.textContent = title;
        previewStats.textContent = stats;

        // Populate Config
        const configList = document.getElementById('previewConfigList');
        if (configList && bot && bot.config) {
            let configHtml = `• Symbol: ${bot.config.symbol || 'N/A'}<br>`;
            configHtml += `• Allocation: $${bot.config.allocation || 0}<br>`;

            if (bot.strategy.toLowerCase().includes('ema_cross')) {
                configHtml += `• Fast/Slow EMA: ${bot.config.fast_ema || 9}/${bot.config.slow_ema || 21}`;
            } else if (bot.strategy.toLowerCase().includes('grid_trading')) {
                configHtml += `• Grids: ${bot.config.num_grids || 10} (${bot.config.lower_limit}-${bot.config.upper_limit})`;
            } else if (bot.strategy.toLowerCase().includes('dynamic_reinvest')) {
                configHtml += `• TP Pct: ${((bot.config.take_profit_pct || 0.02) * 100).toFixed(1)}%`;
            }
            configList.innerHTML = configHtml;
        }

        // Setup Edit Button
        const editBtn = document.getElementById('previewEditBtn');
        if (editBtn && bot) {
            editBtn.onclick = (event) => {
                event.stopPropagation();
                showEditBotModal(bot);
                hidePreview();
            };
        }

        previewPopup.style.display = 'block';
        updatePreviewPosition(e);
        drawSparkline(previewCanvas, data);
        if (window.lucide) lucide.createIcons();
    }

    function updatePreviewPosition(e) {
        if (!previewPopup) return;
        const x = e.clientX + 20;
        const y = e.clientY + 20;

        if (x + 250 > window.innerWidth) previewPopup.style.left = (e.clientX - 270) + 'px';
        else previewPopup.style.left = x + 'px';

        if (y + 150 > window.innerHeight) previewPopup.style.top = (e.clientY - 170) + 'px';
        else previewPopup.style.top = y + 'px';
    }

    function hidePreview() {
        if (previewPopup) previewPopup.style.display = 'none';
    }

    // Global mousemove for floating popup refinement
    document.addEventListener('mousemove', (e) => {
        if (previewPopup && previewPopup.style.display === 'block') {
            const isOverInteractive = e.target.closest('.trade-entry') || e.target.closest('tr') || e.target.closest('.preview-popup');
            if (!isOverInteractive) {
                hidePreview();
            }
        }
    });

    if (previewPopup) {
        previewPopup.addEventListener('mouseleave', () => {
            hidePreview();
        });
    }

    // View Options Logic
    document.querySelectorAll('.view-options-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            if (btn.dataset.target === 'bots') {
                renderFieldOptions();
                fieldSelectorModal.style.display = 'flex';
            }
        });
    });

    function renderFieldOptions() {
        fieldOptions.innerHTML = allBotFields.map(field => `
            <label style="display: flex; align-items: center; gap: 10px; cursor: pointer;">
                <input type="checkbox" value="${field}" ${botVisibleFields.includes(field) ? 'checked' : ''} style="accent-color: var(--accent-blue);">
                <span>${field}</span>
            </label>
        `).join('');
    }

    if (closeFieldModal) {
        closeFieldModal.addEventListener('click', () => fieldSelectorModal.style.display = 'none');
    }

    if (saveFields) {
        saveFields.addEventListener('click', () => {
            const selected = Array.from(fieldOptions.querySelectorAll('input:checked')).map(input => input.value);
            botVisibleFields = selected;
            updateTableVisibility();
            fieldSelectorModal.style.display = 'none';
        });
    }

    // --- PERIODIC UPDATES & REAL-TIME SIMULATION ---

    function getModelConfidence(stats, trades) {
        if (!stats) return 0;

        const winRate = Number(stats.win_rate) || 0;
        const totalTrades = Number(stats.total_trades) || 0;
        const sampleFactor = Math.min(totalTrades / 100, 1);
        const activityFactor = Math.min((trades?.length || 0) / 50, 1);

        const confidence = (winRate * 0.7) + (sampleFactor * 100 * 0.2) + (activityFactor * 100 * 0.1);
        return Math.max(0, Math.min(100, Math.round(confidence)));
    }

    function updateModelConfidenceUI(value) {
        const confidenceBar = document.getElementById('aiModelConfidenceBar');
        const confidenceValue = document.getElementById('aiModelConfidenceValue');

        if (confidenceBar) confidenceBar.style.width = `${value}%`;
        if (confidenceValue) confidenceValue.textContent = `${value}%`;
    }

    function updatePerformanceCharts() {
        const sortedTrades = [...(dashboardState.trades || [])]
            .sort((a, b) => new Date(a.time) - new Date(b.time));

        let cumulativePnl = 0;
        const pnlSeries = sortedTrades.map((trade) => {
            cumulativePnl += Number(trade.pnl) || 0;
            return cumulativePnl;
        });
        const pnlLabels = sortedTrades.map((trade) => new Date(trade.time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }));

        if (performanceChart) {
            performanceChart.data.labels = pnlLabels;
            performanceChart.data.datasets[0].data = pnlSeries;
            performanceChart.update('none');
        }

        const cumulativeNotionalSeries = sortedTrades.reduce((acc, trade, idx) => {
            const prev = idx > 0 ? acc[idx - 1] : 0;
            const notional = (Number(trade.price) || 0) * (Number(trade.amount) || 0);
            acc.push(prev + notional);
            return acc;
        }, []);

        if (portfolioSparkline) {
            portfolioSparkline.data.labels = cumulativeNotionalSeries.map((_, idx) => idx + 1);
            portfolioSparkline.data.datasets[0].data = cumulativeNotionalSeries;
            portfolioSparkline.update('none');
        }

        if (pnlSparkline) {
            pnlSparkline.data.labels = pnlSeries.map((_, idx) => idx + 1);
            pnlSparkline.data.datasets[0].data = pnlSeries;
            pnlSparkline.update('none');
        }
    }

    function buildAIMarketSummary() {
        const stats = dashboardState.stats;
        const positions = dashboardState.positions || [];
        const trades = dashboardState.trades || [];

        if (!stats) {
            return 'Sin métricas disponibles todavía. Esperando datos reales del backend.';
        }

        const netPnl = typeof stats.net_pnl === 'number' ? stats.net_pnl : ((stats.total_pnl || 0) - (stats.total_fees || 0));
        const latestTrade = trades.length > 0 ? trades[0] : null;
        const latestTradeText = latestTrade
            ? `Última ejecución: ${latestTrade.side?.toUpperCase()} ${latestTrade.symbol} por ${latestTrade.bot_id}.`
            : 'Sin ejecuciones recientes en el log visible.';

        return `Rendimiento real: ${stats.total_trades || 0} operaciones, win rate ${stats.win_rate || 0}%, PnL neto ${netPnl >= 0 ? '+' : ''}$${netPnl.toFixed(2)} y ${positions.length} posiciones abiertas. ${latestTradeText}`;
    }

    async function updateAIMarketAnalysis() {
        const aiSummary = document.getElementById('aiMarketSummary');
        if (!aiSummary) return;

        try {
            const summary = buildAIMarketSummary();
            aiSummary.innerHTML = `<i data-lucide="info" style="width:14px; height:14px; vertical-align:middle; margin-right:5px;"></i> ${summary}`;

            const confidence = getModelConfidence(dashboardState.stats, dashboardState.trades);
            updateModelConfidenceUI(confidence);

            if (window.lucide) lucide.createIcons();
        } catch (error) {
            console.error('AI Analysis error:', error);
        }
    }

    function refreshDerivedVisuals() {
        const hasPerformanceWidget = !!document.getElementById('performanceChart');
        const hasAiWidget = !!document.getElementById('aiMarketSummary');
        if (hasPerformanceWidget) {
            updatePerformanceCharts();
        }
        if (hasAiWidget) {
            updateAIMarketAnalysis();
        }
    }

    // Initial AI analysis and periodic refresh (only when widget exists)
    if (document.getElementById('aiMarketSummary')) {
        updateAIMarketAnalysis();
        setInterval(updateAIMarketAnalysis, 30000);
    }

    function showEditBotModal(bot) {
        const modal = document.getElementById('editBotModal');
        if (!modal) return;

        // Populate basic info
        document.getElementById('editBotId').value = bot.id;
        document.getElementById('editBotSymbol').value = bot.config?.symbol || 'N/A';
        document.getElementById('editBotStrategy').value = bot.strategy || 'N/A';
        document.getElementById('editBotAllocation').value = bot.config?.allocation || 0;

        // Reset all param containers
        document.getElementById('editEmaParams').style.display = 'none';
        document.getElementById('editGridParams').style.display = 'none';
        document.getElementById('editReinvestParams').style.display = 'none';

        // Show relevant fields based on strategy
        const strategy = bot.strategy.toLowerCase();
        if (strategy.includes('ema_cross')) {
            document.getElementById('editEmaParams').style.display = 'block';
            document.getElementById('editBotFastEma').value = bot.config?.fast_ema || 9;
            document.getElementById('editBotSlowEma').value = bot.config?.slow_ema || 21;
        } else if (strategy.includes('grid_trading')) {
            document.getElementById('editGridParams').style.display = 'block';
            document.getElementById('editBotUpperLimit').value = bot.config?.upper_limit || 70000;
            document.getElementById('editBotLowerLimit').value = bot.config?.lower_limit || 60000;
            document.getElementById('editBotNumGrids').value = bot.config?.num_grids || 10;
        } else if (strategy.includes('dynamic_reinvest')) {
            document.getElementById('editReinvestParams').style.display = 'block';
            document.getElementById('editBotTpPct').value = bot.config?.take_profit_pct || 0.02;
        }

        modal.style.display = 'flex';
    }

    async function handleEditBotSubmit() {
        const botId = document.getElementById('editBotId').value;
        const strategy = document.getElementById('editBotStrategy').value.toLowerCase();

        const newConfig = {
            allocation: parseFloat(document.getElementById('editBotAllocation').value)
        };

        if (strategy.includes('ema_cross')) {
            newConfig.fast_ema = parseInt(document.getElementById('editBotFastEma').value);
            newConfig.slow_ema = parseInt(document.getElementById('editBotSlowEma').value);
        } else if (strategy.includes('grid_trading')) {
            newConfig.upper_limit = parseFloat(document.getElementById('editBotUpperLimit').value);
            newConfig.lower_limit = parseFloat(document.getElementById('editBotLowerLimit').value);
            newConfig.num_grids = parseInt(document.getElementById('editBotNumGrids').value);
        } else if (strategy.includes('dynamic_reinvest')) {
            newConfig.take_profit_pct = parseFloat(document.getElementById('editBotTpPct').value);
        }

        try {
            const res = await fetch(`/api/bots/${botId}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(newConfig)
            });

            if (res.ok) {
                document.getElementById('editBotModal').style.display = 'none';
                fetchBots(); // Refresh table
            } else {
                const err = await res.json();
                alert('Error updating bot: ' + (err.detail || 'Unknown error'));
            }
        } catch (error) {
            console.error('Update error:', error);
            alert('Error connecting to server.');
        }
    }

    const confirmEditBot = document.getElementById('confirmEditBot');
    if (confirmEditBot) {
        confirmEditBot.addEventListener('click', handleEditBotSubmit);
    }

    // Initial load and periodic refresh
    fetchBots();
    loadBotPresets();
    fetchTrades();
    fetchStats();
    fetchTestInsights();
    loadMainnetVisualControl();
    loadHyperliquidSettings();
    loadRuntimeOpsStatus();
    loadTakeProfitAdaptiveStatus();
    setInterval(fetchBots, 5000);
    setInterval(fetchTrades, 10000);
    setInterval(fetchStats, 10000);
    setInterval(fetchTestInsights, 20000);
    setInterval(loadMainnetVisualControl, 15000);
    setInterval(loadTakeProfitAdaptiveStatus, 20000);
});
