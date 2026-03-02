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
    const productionAlertsContent = document.getElementById('productionAlertsContent');
    const refreshProductionAlerts = document.getElementById('refreshProductionAlerts');
    const settingsWalletAddressInput = document.getElementById('settingsWalletAddress');
    const settingsSigningKeyInput = document.getElementById('settingsSigningKey');
    const settingsUseTestnetSelect = document.getElementById('settingsUseTestnet');
    const settingsStatus = document.getElementById('settingsStatus');
    const saveHyperliquidSettingsBtn = document.getElementById('saveHyperliquidSettingsBtn');

    let botPresets = [];
    let advisorMap = {};

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

    let botVisibleFields = ['Bot', 'Estrategia', 'Estado', 'Asignación', 'PnL', 'Acciones'];
    const allBotFields = ['ID Bot', 'Nombre Bot', 'Estrategia', 'Estado', 'Asignación', 'PnL', 'Uptime', 'Tasa Éxito', 'Acciones'];

    // Sidebar/Nav Toggle Logic for Mobile
    if (menuToggle && sidebar) {
        menuToggle.addEventListener('click', () => {
            sidebar.classList.toggle('active');
            if (sidebarOverlay) sidebarOverlay.classList.toggle('active');
        });
    }

    if (sidebarOverlay && sidebar) {
        sidebarOverlay.addEventListener('click', () => {
            sidebar.classList.remove('active');
            sidebarOverlay.classList.remove('active');
        });
    }

    // Strategy Parameter Visibility
    const newBotStrategy = document.getElementById('newBotStrategy');
    const emaParams = document.getElementById('emaParams');
    if (newBotStrategy && emaParams) {
        newBotStrategy.addEventListener('change', () => {
            emaParams.style.display = newBotStrategy.value === 'ema_cross' ? 'block' : 'none';
        });
    }

    // Resizable Dashboard Persistence
    const resizableOverview = document.getElementById('resizableOverview');
    if (resizableOverview) {
        // Load saved dimensions
        const savedWidth = localStorage.getItem('dashboard-overview-width');
        const savedHeight = localStorage.getItem('dashboard-overview-height');

        if (savedWidth) resizableOverview.style.width = savedWidth;
        if (savedHeight) resizableOverview.style.height = savedHeight;

        // Save dimensions on resize
        const resizeObserver = new ResizeObserver(entries => {
            for (let entry of entries) {
                const { width, height } = entry.contentRect;
                localStorage.setItem('dashboard-overview-width', width + 'px');
                localStorage.setItem('dashboard-overview-height', height + 'px');

                // Trigger chart resize if needed
                if (window.performanceChart && typeof window.performanceChart.resize === 'function') {
                    window.performanceChart.resize();
                }
            }
        });
        resizeObserver.observe(resizableOverview);
    }

    // Comparison Logic
    let comparisonInterval = null;
    const compareSymbolAInput = document.getElementById('compareSymbolA');
    const compareSymbolBInput = document.getElementById('compareSymbolB');
    const comparePriceAEl = document.getElementById('comparePriceA');
    const comparePriceBEl = document.getElementById('comparePriceB');
    const compareLastUpdateEl = document.getElementById('compareLastUpdate');

    async function refreshComparisonPrices(showAlert = false) {
        if (!compareSymbolAInput || !compareSymbolBInput || !comparePriceAEl || !comparePriceBEl) return;

        const symA = compareSymbolAInput.value;
        const symB = compareSymbolBInput.value;

        try {
            const response = await fetch('/api/market/compare', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ symbol_a: symA, symbol_b: symB })
            });

            if (!response.ok) {
                const errData = await response.json();
                throw new Error(errData.detail || 'No se pudieron obtener precios reales');
            }

            const data = await response.json();
            comparePriceAEl.innerText = `$${Number(data.price_a || 0).toLocaleString(undefined, { maximumFractionDigits: 6 })}`;
            comparePriceBEl.innerText = `$${Number(data.price_b || 0).toLocaleString(undefined, { maximumFractionDigits: 6 })}`;
            if (compareLastUpdateEl) {
                const ts = data.timestamp ? new Date(data.timestamp) : new Date();
                compareLastUpdateEl.innerText = `Última actualización: ${ts.toLocaleTimeString()}`;
            }

            if (showAlert) {
                alert(`Análisis comparativo actualizado con precios reales (${data.source || 'market'}).`);
            }
        } catch (error) {
            console.error('Comparison error:', error);
            if (showAlert) {
                alert('Error en análisis comparativo: ' + error.message);
            }
        }
    }

    function stopComparisonAutoRefresh() {
        if (comparisonInterval) {
            clearInterval(comparisonInterval);
            comparisonInterval = null;
        }
    }

    function startComparisonAutoRefresh() {
        stopComparisonAutoRefresh();
        refreshComparisonPrices(false);
        comparisonInterval = setInterval(() => {
            refreshComparisonPrices(false);
        }, 15000);
    }

    function renderSettingsStatus(checks, saved = false) {
        if (!settingsStatus || !checks) return;
        const ready = !!checks.ready_for_real_market;
        const authOk = !!checks.mainnet_auth_ok;
        const testnetValue = Number(checks.testnet_account_value || 0);
        const mainnetValue = Number(checks.mainnet_account_value || 0);
        const authError = checks.mainnet_auth_error || checks.selected_env_auth_error || '';
        const title = ready ? '✅ Listo para mercado real' : '⚠️ No listo para mercado real';
        const savedLine = saved ? 'Configuración guardada correctamente. ' : '';

        settingsStatus.innerHTML = [
            `<strong>${title}</strong>`,
            `<div style="margin-top: 6px;">${savedLine}Auth mainnet: ${authOk ? 'OK' : 'ERROR'}</div>`,
            `<div>Saldo testnet: $${testnetValue.toFixed(2)} | Saldo mainnet: $${mainnetValue.toFixed(2)}</div>`,
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
            renderSettingsStatus(data.checks, false);
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
            renderSettingsStatus(data.checks, true);
        } catch (error) {
            console.error('Error saving Hyperliquid settings:', error);
            settingsStatus.textContent = 'Error guardando ajustes: ' + error.message;
            alert('Error guardando ajustes: ' + error.message);
        } finally {
            saveHyperliquidSettingsBtn.disabled = false;
            saveHyperliquidSettingsBtn.textContent = previousText;
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
            const response = await fetch('/api/bots');
            const bots = await response.json();

            const activeBots = bots
                .filter(b => !b.is_archived)
                .sort((a, b) => {
                    const aRunning = a.status === 'running' ? 1 : 0;
                    const bRunning = b.status === 'running' ? 1 : 0;
                    if (aRunning !== bRunning) return bRunning - aRunning;
                    return (a.id || '').localeCompare(b.id || '');
                });
            const archivedBots = bots.filter(b => b.is_archived);

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
                botManagerInfo.textContent = `${activeBots.length} bots · ${runningCount} ACTIVOS · ${waitingCount} EN ESPERA${activeIds ? ` · Activos ahora: ${activeIds}${activeTail}` : ''}`;
            }
            if (vaultManagerInfo) {
                vaultManagerInfo.textContent = `${archivedBots.length} bots archivados en cápsula`;
            }

            updateBotTable(activeBots);
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
                    <button class="glass bot-action" data-id="${bot.id}" data-lucide="${bot.status === 'running' ? 'pause-circle' : 'play-circle'}" style="padding: 5px; color: ${bot.status === 'running' ? 'var(--accent-ruby)' : 'var(--accent-emerald)'}; cursor: pointer; border: none;" title="${bot.status === 'running' ? 'Stop Bot' : 'Start Bot'}">
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
                ? `Editar y usar ${item.recommended_bot_id || 'bot existente'}`
                : item.recommended_action === 'reduce_risk'
                    ? `Reducir riesgo en ${item.recommended_bot_id || 'bot existente'} (prioridad defensiva)`
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
                        <button class="advisor-apply-btn" data-horizon="${item.horizon}" style="padding:7px; border:1px solid var(--accent-blue); color:var(--accent-blue); background:transparent; border-radius:8px; cursor:pointer;">Usar en formulario</button>
                        <button class="advisor-create-btn" data-horizon="${item.horizon}" style="padding:7px; border:1px solid var(--accent-emerald); color:var(--accent-emerald); background:transparent; border-radius:8px; cursor:pointer;">Crear bot ahora</button>
                        <button class="advisor-auto-btn" data-horizon="${item.horizon}" style="padding:7px; border:1px solid #facc15; color:#facc15; background:transparent; border-radius:8px; cursor:pointer;">Auto-ejecutar</button>
                    </div>
                </div>
            `;
        }).join('');
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

    async function fetchProductionAlerts() {
        if (!productionAlertsContent) return;

        try {
            const response = await fetch('/api/production/alerts?limit=12&only_open=true');
            if (!response.ok) return;

            const alerts = await response.json();
            if (!Array.isArray(alerts) || alerts.length === 0) {
                productionAlertsContent.innerHTML = '<div style="color: var(--text-muted);">Sin alertas críticas abiertas. Producción estable.</div>';
                return;
            }

            productionAlertsContent.innerHTML = alerts.map((alert) => {
                const levelColor = alert.level === 'critical'
                    ? 'var(--accent-ruby)'
                    : alert.level === 'warning'
                        ? '#facc15'
                        : 'var(--accent-blue)';

                const createdAt = alert.created_at ? new Date(alert.created_at).toLocaleString() : '-';
                const details = alert.data || {};
                return `
                    <div style="border:1px solid rgba(255,255,255,0.08); border-left:4px solid ${levelColor}; border-radius:10px; padding:10px; margin-bottom:10px; background:rgba(255,255,255,0.02);">
                        <div style="display:flex; justify-content:space-between; gap:8px; align-items:center;">
                            <div style="font-weight:700; color:${levelColor}; text-transform:uppercase; font-size:0.72rem;">${alert.level}</div>
                            <div style="font-size:0.68rem; color:var(--text-muted);">${createdAt}</div>
                        </div>
                        <div style="font-size:0.86rem; font-weight:600; margin-top:4px;">${alert.title || 'Alerta de producción'}</div>
                        <div style="font-size:0.78rem; color:var(--text-secondary); margin-top:3px;">Bot: <strong>${alert.bot_id}</strong> · ${alert.message}</div>
                        <div style="font-size:0.72rem; color:var(--text-muted); margin-top:6px;">
                            WinRate: ${details.win_rate ?? '-'}% · NetPnL: ${details.net_pnl ?? '-'} · Losses consecutivas: ${details.consecutive_losses ?? '-'}
                        </div>
                        <div style="display:flex; justify-content:flex-end; margin-top:8px;">
                            <button class="ack-production-alert" data-id="${alert.id}" style="padding:6px 10px; border:1px solid var(--accent-blue); color:var(--accent-blue); background:transparent; border-radius:8px; cursor:pointer; font-size:0.72rem;">MARCAR REVISADA</button>
                        </div>
                    </div>
                `;
            }).join('');
        } catch (error) {
            console.error('Error fetching production alerts:', error);
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
        const ackProductionAlert = e.target.closest('.ack-production-alert');

        if (createBtn) {
            const modal = document.getElementById('createBotModal');
            if (modal) {
                modal.style.display = 'flex';
                // Force refocus/re-render to be sure
                const idInput = document.getElementById('newBotId');
                if (idInput) idInput.value = `Bot-${Math.floor(Math.random() * 1000)}`;
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

            const useExistingConfig = rec.recommended_action === 'tune_existing' || rec.recommended_action === 'reduce_risk';
            const configToCreate = useExistingConfig ? rec.edited_config : rec.new_bot_config;
            if (!configToCreate) return;

            if (useExistingConfig && rec.recommended_bot_id) {
                try {
                    const response = await fetch(`/api/bots/${rec.recommended_bot_id}`, {
                        method: 'PATCH',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(configToCreate)
                    });
                    if (!response.ok) {
                        const err = await response.json();
                        alert('No se pudo actualizar el bot recomendado: ' + (err.detail || 'Error desconocido'));
                    } else {
                        fetchBots();
                        alert(`Bot actualizado: ${rec.recommended_bot_id}`);
                    }
                } catch (error) {
                    console.error('Advisor update bot error:', error);
                }
                return;
            }

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
                    body: JSON.stringify({ horizon, symbol, allocation })
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

        if (ackProductionAlert) {
            const alertId = ackProductionAlert.dataset.id;
            if (!alertId) return;
            try {
                const response = await fetch(`/api/production/alerts/${alertId}/ack`, { method: 'POST' });
                if (response.ok) {
                    fetchProductionAlerts();
                }
            } catch (error) {
                console.error('Error acknowledging production alert:', error);
            }
        }
    });

    if (refreshProductionAlerts) {
        refreshProductionAlerts.addEventListener('click', async () => {
            try {
                await fetch('/api/production/scan', { method: 'POST' });
            } catch (error) {
                console.error('Error triggering production scan:', error);
            } finally {
                fetchProductionAlerts();
            }
        });
    }

    if (saveHyperliquidSettingsBtn) {
        saveHyperliquidSettingsBtn.addEventListener('click', saveHyperliquidSettings);
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
            }
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
        // Prevent event bubbling to avoid multiple triggers if nested
        e.stopPropagation();

        const actionIcon = e.target.closest('.bot-action');
        const editIcon = e.target.closest('.edit-bot-btn');
        const deleteIcon = e.target.closest('.delete-bot-btn');
        const archiveIcon = e.target.closest('.archive-bot-btn');
        const restoreIcon = e.target.closest('.restore-bot-btn');
        const restoreStartIcon = e.target.closest('.restore-start-bot-btn');

        if (actionIcon) {
            const botId = actionIcon.dataset.id;
            const isCurrentlyRunning = actionIcon.dataset.lucide === 'pause-circle';
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

    if (botTableBody) botTableBody.addEventListener('click', handleBotActions);
    if (vaultTableBody) vaultTableBody.addEventListener('click', handleBotActions);

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

    // -- Open Positions Fetch --
    async function fetchPositions() {
        try {
            const res = await fetch('/api/positions');
            const positions = await res.json();
            dashboardState.positions = Array.isArray(positions) ? positions : [];

            const tbody = document.getElementById('openPositionsTableBody');
            const badge = document.getElementById('openPositionsBadge');

            if (badge) badge.textContent = `${positions.length} abiertas`;

            if (!tbody) return;
            if (positions.length === 0) {
                tbody.innerHTML = '<tr><td colspan="9" style="text-align: center; padding: 2rem; color: var(--text-muted);">No hay posiciones abiertas</td></tr>';
                return;
            }

            tbody.innerHTML = positions.map(p => {
                const upnl = p.unrealized_pnl || 0;
                const upnlColor = upnl >= 0 ? 'var(--accent-emerald)' : 'var(--accent-ruby)';
                const openedAt = new Date(p.opened_at).toLocaleString();
                return `
                <tr style="border-bottom: 1px solid rgba(255,255,255,0.04); transition: background 0.2s;" 
                    onmouseenter="this.style.background='rgba(255,255,255,0.03)'" 
                    onmouseleave="this.style.background=''">
                    <td style="padding: 0.75rem; font-size: 0.83rem; color: var(--accent-blue);">${p.bot_id}</td>
                    <td style="padding: 0.75rem; font-weight: 600;">${p.symbol}</td>
                    <td style="padding: 0.75rem; color: ${p.side === 'long' ? '#60a5fa' : '#f87171'}; font-weight: 700;">${p.side.toUpperCase()}</td>
                    <td style="padding: 0.75rem;">$${(p.entry_price || 0).toLocaleString()}</td>
                    <td style="padding: 0.75rem; color: var(--text-secondary);">$${(p.current_price || p.entry_price || 0).toLocaleString()}</td>
                    <td style="padding: 0.75rem;">${p.quantity}</td>
                    <td style="padding: 0.75rem; font-weight: 600; color: ${upnlColor};">${upnl >= 0 ? '+' : ''}$${upnl.toFixed(4)}</td>
                    <td style="padding: 0.75rem; color: #facc15;">$${(p.fee_paid || 0).toFixed(4)}</td>
                    <td style="padding: 0.75rem; color: var(--text-muted); font-size: 0.75rem;">${openedAt}</td>
                    <td style="padding: 0.75rem; text-align: right;">
                        <button class="glass" onclick="window.closePosition('${p.id}')" style="padding: 4px 8px; font-size: 0.65rem; color: var(--accent-ruby); border-color: var(--accent-ruby); cursor: pointer;">CERRAR</button>
                    </td>
                </tr>`;
            }).join('');

            refreshDerivedVisuals();
        } catch (e) {
            console.error('fetchPositions error:', e);
        }
    }

    window.closePosition = async function (posId) {
        if (!confirm('¿Estás seguro de que deseas cerrar esta posición manualmente? Esta acción solo actualiza el estado local.')) return;
        try {
            const res = await fetch(`/api/positions/${posId}/close`, { method: 'POST' });
            if (res.ok) {
                fetchPositions();
                fetchStats();
            } else {
                alert('Error al cerrar la posición');
            }
        } catch (e) {
            console.error('closePosition error:', e);
        }
    };

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

    previewPopup.addEventListener('mouseleave', () => {
        hidePreview();
    });

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
        updatePerformanceCharts();
        updateAIMarketAnalysis();
    }

    // Initial AI analysis and periodic refresh
    updateAIMarketAnalysis();
    setInterval(updateAIMarketAnalysis, 30000);

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
    fetchPositions();
    fetchProductionAlerts();
    loadHyperliquidSettings();
    setInterval(fetchBots, 5000);
    setInterval(fetchTrades, 10000);
    setInterval(fetchStats, 10000);
    setInterval(fetchPositions, 10000);
    setInterval(fetchProductionAlerts, 15000);
});
