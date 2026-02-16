// Dashboard Application Logic

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
    const topNav = document.querySelector('.top-nav');
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

    let botVisibleFields = ['Bot Name', 'Strategy', 'Status', 'Allocation', 'PnL', 'Actions'];
    const allBotFields = ['Bot ID', 'Bot Name', 'Strategy', 'Status', 'Allocation', 'PnL', 'Uptime', 'Win Rate', 'Actions'];

    // Sidebar/Nav Toggle Logic for Mobile (Overlay)
    if (menuToggle && topNav && sidebarOverlay) {
        const toggleMenuMobile = () => {
            topNav.classList.toggle('active');
            sidebarOverlay.classList.toggle('active');
        };

        menuToggle.addEventListener('click', toggleMenuMobile);
        sidebarOverlay.addEventListener('click', toggleMenuMobile);
    }

    // Strategy Parameter Visibility
    const newBotStrategy = document.getElementById('newBotStrategy');
    const emaParams = document.getElementById('emaParams');
    if (newBotStrategy && emaParams) {
        newBotStrategy.addEventListener('change', () => {
            emaParams.style.display = newBotStrategy.value === 'ema_cross' ? 'block' : 'none';
        });
    }

    // Comparison Logic
    const runComparisonBtn = document.getElementById('runComparisonBtn');
    if (runComparisonBtn) {
        runComparisonBtn.addEventListener('click', async () => {
            const symA = document.getElementById('compareSymbolA').value;
            const symB = document.getElementById('compareSymbolB').value;

            runComparisonBtn.innerText = 'ANALYZING...';
            runComparisonBtn.disabled = true;

            try {
                // We'll use a public market data API if available, or just mock it for now
                // since we don't have a specific comparison endpoint yet.
                // However, our backend has fetch_ticker. We could expose a comparison API.
                // For now, let's try to fetch both independently if possible.

                const [resA, resB] = await Promise.all([
                    fetch(`/api/backtest/run`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ symbol: symA, timeframe: '1h', strategy: 'ema_cross', limit: 1 })
                    }),
                    fetch(`/api/backtest/run`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ symbol: symB, timeframe: '1h', strategy: 'ema_cross', limit: 1 })
                    })
                ]);

                if (resA.ok && resB.ok) {
                    const dataA = await resA.json();
                    const dataB = await resB.json();

                    document.getElementById('comparePriceA').innerText = `$${(40000 + Math.random() * 1000).toFixed(2)}`; // Mocking since backtest result might not have price easily
                    document.getElementById('comparePriceB').innerText = `$${(2500 + Math.random() * 100).toFixed(2)}`;

                    alert('Comparison complete. Metrics updated.');
                }
            } catch (error) {
                console.error('Comparison error:', error);
            } finally {
                runComparisonBtn.innerText = 'EXECUTE SIDE-BY-SIDE ANALYSIS';
                runComparisonBtn.disabled = false;
            }
        });
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
                section.classList.toggle('active', section.id === targetId);
            });

            // Update Header Title & Subtitle
            if (sectionTitle) {
                const titleMap = {
                    'overview': 'Market Overview',
                    'bots': 'Bot Management',
                    'vault': 'Bot Vault',
                    'strategies': 'Strategy Configuration',
                    'comparison': 'Independent Comparison',
                    'backtesting': 'Historical Simulation',
                    'settings': 'Platform Settings'
                };
                const subtitleMap = {
                    'overview': 'Real-time institutional trading performance and monitoring.',
                    'bots': 'Deploy, monitor, and manage your algorithmic trading fleet.',
                    'vault': 'Previously configured bots saved for later reuse.',
                    'strategies': 'Configure and fine-tune your trading algorithms.',
                    'comparison': 'Compare two assets side-by-side and launch bots directly.',
                    'backtesting': 'Run historical simulations to validate your strategies.',
                    'settings': 'Global configuration and platform preferences.'
                };
                sectionTitle.innerText = titleMap[targetId] || 'Dashboard';
                if (sectionSubtitle) sectionSubtitle.innerText = subtitleMap[targetId] || '';
            }

            if (window.lucide) lucide.createIcons();

            // Close menu on mobile after navigation
            if (topNav && topNav.classList.contains('active')) {
                topNav.classList.remove('active');
                sidebarOverlay.classList.remove('active');
            }
        });
    });

    // Backtesting UI Logic
    const runBtBtn = document.getElementById('runBacktestBtn');
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

    // --- CHART INITIALIZATION ---
    let performanceChart;
    let backtestChart;
    let portfolioSparkline;
    let pnlSparkline;

    function initCharts() {
        const perfCtx = document.getElementById('performanceChart')?.getContext('2d');
        if (perfCtx) {
            performanceChart = new Chart(perfCtx, {
                type: 'line',
                data: {
                    labels: Array.from({ length: 24 }, (_, i) => `${i}:00`),
                    datasets: [{
                        label: 'Portfolio Value',
                        data: Array.from({ length: 24 }, () => 2500000 + Math.random() * 50000),
                        borderColor: '#38bdf8',
                        backgroundColor: 'rgba(56, 189, 248, 0.1)',
                        fill: true,
                        tension: 0.4,
                        borderWidth: 2,
                        pointRadius: 0,
                        pointHoverRadius: 5
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { display: false } },
                    scales: {
                        x: { grid: { display: false }, ticks: { color: 'rgba(255,255,255,0.5)', font: { size: 10 } } },
                        y: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: 'rgba(255,255,255,0.5)', font: { size: 10 }, callback: (val) => '$' + (val / 1000000).toFixed(1) + 'M' } }
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
                    labels: Array.from({ length: 10 }, (_, i) => i),
                    datasets: [{
                        data: Array.from({ length: 10 }, () => Math.random() * 100),
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
                    labels: Array.from({ length: 10 }, (_, i) => i),
                    datasets: [{
                        data: Array.from({ length: 10 }, () => Math.random() * 100),
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

            const activeBots = bots.filter(b => !b.is_archived);
            const archivedBots = bots.filter(b => b.is_archived);

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
                <td style="padding: 1rem; border-bottom: 1px solid rgba(255,255,255,0.05);">$${bot.config?.allocation || bot.capital_allocation || 0}</td>
                <td style="padding: 1rem; border-bottom: 1px solid rgba(255,255,255,0.05);">${bot.status}</td>
                <td style="padding: 1rem; border-bottom: 1px solid rgba(255,255,255,0.05); text-align: right;">
                    <button class="glass restore-bot-btn" data-id="${bot.id}" style="padding: 5px; color: var(--accent-emerald); cursor: pointer; border: none;" title="Restore">
                        <i data-lucide="refresh-cw" style="width: 16px; height: 16px;"></i>
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
            botTableBody.innerHTML = '<tr><td colspan="7" style="text-align: center; padding: 2rem; color: var(--text-muted);">No bots active. Create one to start trading.</td></tr>';
            return;
        }

        botTableBody.innerHTML = bots.map(bot => `
            <tr class="bot-row" data-id="${bot.id}">
                <td style="padding: 1rem; border-bottom: 1px solid rgba(255,255,255,0.05);">${bot.id}</td>
                <td style="padding: 1rem; border-bottom: 1px solid rgba(255,255,255,0.05); font-weight: 500;">${bot.id.split('_')[0].toUpperCase()}</td>
                <td style="padding: 1rem; border-bottom: 1px solid rgba(255,255,255,0.05);"><span class="strategy-badge">${bot.strategy}</span></td>
                <td style="padding: 1rem; border-bottom: 1px solid rgba(255,255,255,0.05);">
                    <div style="display: flex; align-items: center; gap: 0.5rem;">
                        <div style="width: 8px; height: 8px; border-radius: 50%; background: ${bot.status === 'running' ? 'var(--accent-emerald)' : 'var(--accent-ruby)'};"></div>
                        ${bot.status}
                    </div>
                </td>
                <td style="padding: 1rem; border-bottom: 1px solid rgba(255,255,255,0.05);">$${bot.config?.allocation || 0}</td>
                <td style="padding: 1rem; border-bottom: 1px solid rgba(255,255,255,0.05); color: var(--accent-emerald); font-weight: 600;">+$0.00</td>
                <td style="padding: 1rem; border-bottom: 1px solid rgba(255,255,255,0.05);">99.9%</td>
                <td style="padding: 1rem; border-bottom: 1px solid rgba(255,255,255,0.05);">68%</td>
                <td style="padding: 1rem; border-bottom: 1px solid rgba(255,255,255,0.05); text-align: right;">
                    <button class="glass bot-action" data-id="${bot.id}" data-lucide="${bot.status === 'running' ? 'pause-circle' : 'play-circle'}" style="padding: 5px; color: ${bot.status === 'running' ? 'var(--accent-ruby)' : 'var(--accent-emerald)'}; cursor: pointer; border: none;" title="${bot.status === 'running' ? 'Stop Bot' : 'Start Bot'}">
                        <i data-lucide="${bot.status === 'running' ? 'pause-circle' : 'play-circle'}" style="width: 16px; height: 16px;"></i>
                    </button>
                    <button class="glass archive-bot-btn" data-id="${bot.id}" style="padding: 5px; color: var(--accent-blue); cursor: pointer; border: none;" title="Archive to Vault">
                        <i data-lucide="archive" style="width: 16px; height: 16px;"></i>
                    </button>
                    <button class="glass delete-bot-btn" data-id="${bot.id}" style="padding: 5px; color: var(--accent-ruby); cursor: pointer; border: none;" title="Delete">
                        <i data-lucide="trash-2" style="width: 16px; height: 16px;"></i>
                    </button>
                </td>
            </tr>
        `).join('');

        updateTableVisibility();
        if (window.lucide) lucide.createIcons();

        // Attach hover events to bot rows
        botTableBody.querySelectorAll('.bot-row').forEach(row => {
            row.addEventListener('mouseenter', (e) => {
                const botId = row.cells[0].textContent;
                const mockData = Array.from({ length: 20 }, () => Math.random() * 50 + 100);
                showPreview(e, `Bot Performance: ${botId}`, mockData, `Efficiency: 94% | Uptime: 99.9%`);
            });
            row.addEventListener('mouseleave', () => {
                if (typeof hidePreview === 'function') hidePreview();
                else if (previewPopup) previewPopup.style.display = 'none';
            });
            row.addEventListener('mousemove', (e) => {
                if (previewPopup && previewPopup.style.display === 'block') {
                    updatePreviewPosition(e);
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

            updateTradeFeed(trades);
        } catch (error) {
            console.error('Error fetching trades:', error);
        }
    }

    function updateTradeFeed(trades) {
        const sidePanel = document.getElementById('recentTradesContent');
        if (!sidePanel) return;

        if (trades.length === 0) {
            sidePanel.innerHTML = '<div style="color: var(--text-muted); font-size: 0.8rem;">No trades recorded yet.</div>';
            return;
        }

        sidePanel.innerHTML = trades.map(trade => `
            <div class="trade-entry" data-id="${trade.id}">
                <div class="trade-info">
                    <div class="trade-symbol">${trade.symbol}</div>
                    <div class="trade-details">${trade.side.toUpperCase()} @ ${trade.price.toLocaleString()}</div>
                </div>
                <div class="trade-stats">
                    <div class="trade-amount ${trade.side}">
                        ${trade.amount}
                    </div>
                    <div class="trade-time">
                        ${new Date(trade.time).toLocaleTimeString()}
                    </div>
                </div>
            </div>
        `).join('');

        // Attach hover events to new elements
        sidePanel.querySelectorAll('.trade-entry').forEach(entry => {
            entry.addEventListener('mouseenter', (e) => {
                const symbol = entry.querySelector('.trade-symbol').textContent;
                const mockData = Array.from({ length: 20 }, () => Math.random() * 100 + 50000);
                showPreview(e, `${symbol} Trend`, mockData, `Volatility: 1.2% | Volume: 4.5M`);
            });
            entry.addEventListener('mouseleave', () => {
                if (typeof hidePreview === 'function') hidePreview();
                else if (previewPopup) previewPopup.style.display = 'none';
            });
            entry.addEventListener('mousemove', (e) => {
                if (previewPopup && previewPopup.style.display === 'block') {
                    updatePreviewPosition(e);
                }
            });
            entry.addEventListener('click', () => showTradeExplanation(entry.dataset.id));
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


    // Create New Bot Modal Logic
    const createBotBtn = document.getElementById('createBotBtn');
    const createBotModal = document.getElementById('createBotModal');
    const closeModal = document.getElementById('closeModal');
    const confirmCreateBot = document.getElementById('confirmCreateBot');

    if (createBotBtn) {
        createBotBtn.addEventListener('click', () => {
            createBotModal.style.display = 'flex';
            document.getElementById('newBotId').value = `Bot-${Math.floor(Math.random() * 1000)}`;
        });
    }

    if (closeModal) {
        closeModal.addEventListener('click', () => {
            createBotModal.style.display = 'none';
        });
    }

    if (confirmCreateBot) {
        confirmCreateBot.addEventListener('click', async () => {
            const botConfig = {
                id: document.getElementById('newBotId').value,
                symbol: document.getElementById('newBotSymbol').value,
                strategy: document.getElementById('newBotStrategy').value,
                fast_ema: parseInt(document.getElementById('newBotFastEma').value),
                slow_ema: parseInt(document.getElementById('newBotSlowEma').value),
                capital_allocation: parseFloat(document.getElementById('newBotAllocation').value),
                risk_config: { max_drawdown: 0.05 }
            };

            try {
                const response = await fetch('/api/bots', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(botConfig)
                });

                if (response.ok) {
                    createBotModal.style.display = 'none';
                    fetchBots();
                } else {
                    const error = await response.json();
                    alert('Error creating bot: ' + error.detail);
                }
            } catch (error) {
                console.error('Network error creating bot:', error);
            }
        });
    }

    // Bot Action Delegation (Play, Pause, Delete, Archive, Restore)
    const handleBotActions = async (e) => {
        // Prevent event bubbling to avoid multiple triggers if nested
        e.stopPropagation();

        const actionIcon = e.target.closest('.bot-action');
        const deleteIcon = e.target.closest('.delete-bot-btn');
        const archiveIcon = e.target.closest('.archive-bot-btn');
        const restoreIcon = e.target.closest('.restore-bot-btn');

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

    // Mock live data for stats (keeping visual flair)
    setInterval(() => {
        const pnlValue = document.querySelector('.stat-card:nth-child(2) .stat-value');
        if (pnlValue) {
            const current = parseFloat(pnlValue.textContent.replace('+$', '').replace(',', ''));
            const change = (Math.random() - 0.4) * 10;
            const newVal = current + change;
            pnlValue.textContent = (newVal >= 0 ? '+$' : '-$') + Math.abs(newVal).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
            pnlValue.style.color = newVal >= 0 ? 'var(--accent-emerald)' : 'var(--accent-ruby)';
        }
    }, 3000);

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

    function showPreview(e, title, data, stats) {
        if (!previewPopup) return;

        previewTitle.textContent = title;
        previewStats.textContent = stats;

        previewPopup.style.display = 'block';
        updatePreviewPosition(e);
        drawSparkline(previewCanvas, data);
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
            const isOverInteractive = e.target.closest('.trade-entry') || e.target.closest('tr');
            if (!isOverInteractive) {
                hidePreview();
            } else {
                updatePreviewPosition(e);
            }
        }
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

    async function updateAIMarketAnalysis() {
        const aiSummary = document.getElementById('aiMarketSummary');
        if (!aiSummary) return;

        try {
            const analyses = [
                "Market sentiment is currently bullish on BTC/USDT. Bots are optimizing for long positions.",
                "Volatility is increasing in the 1h timeframe. Risk limits have been adjusted automatically.",
                "Local LLM suggests a potential reversal at $68,500. Monitoring RSI levels across all active bots.",
                "Execution efficiency is up 4.2% this hour. Smart routing is active on 8 bots."
            ];
            const randomAnalysis = analyses[Math.floor(Math.random() * analyses.length)];
            aiSummary.innerHTML = `<i data-lucide="info" style="width:14px; height:14px; vertical-align:middle; margin-right:5px;"></i> ${randomAnalysis}`;
            if (window.lucide) lucide.createIcons();
        } catch (error) {
            console.error('AI Analysis error:', error);
        }
    }

    function simulateRealTimeData() {
        if (!performanceChart) return;

        const lastVal = performanceChart.data.datasets[0].data.slice(-1)[0];
        const newVal = lastVal + (Math.random() - 0.45) * 5000;

        performanceChart.data.labels.shift();
        performanceChart.data.labels.push(new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }));

        performanceChart.data.datasets[0].data.shift();
        performanceChart.data.datasets[0].data.push(newVal);
        performanceChart.update('none');

        [portfolioSparkline, pnlSparkline].forEach(chart => {
            if (!chart) return;
            chart.data.datasets[0].data.shift();
            chart.data.datasets[0].data.push(Math.random() * 100);
            chart.update('none');
        });
    }

    // Initial AI analysis and periodic refresh
    updateAIMarketAnalysis();
    setInterval(updateAIMarketAnalysis, 30000);
    setInterval(simulateRealTimeData, 5000);

    // Initial load and periodic refresh
    fetchBots();
    fetchTrades();
    setInterval(fetchBots, 5000);
    setInterval(fetchTrades, 10000);
});
