
import { useState, useEffect } from 'react';
import './App.css';



function App() {
  const [bots, setBots] = useState([]);
  const [positions, setPositions] = useState([]);
  const [selectedBot, setSelectedBot] = useState(null);
  const [selectedPosition, setSelectedPosition] = useState(null);
  const [increaseAmount, setIncreaseAmount] = useState(0);
  const [message, setMessage] = useState('');

  useEffect(() => {
    fetch('/api/bots')
      .then(res => res.json())
      .then(setBots);
    fetch('/api/positions')
      .then(res => res.json())
      .then(setPositions);
  }, []);

  const getBotStatus = (bot_id) => {
    const bot = bots.find(b => b.id === bot_id);
    return bot ? bot.status : 'unknown';
  };

  const handleBotDetail = (bot) => {
    setSelectedBot(bot);
    setMessage('');
    setSelectedPosition(null);
  };

  const handleIncrease = (position) => {
    setSelectedPosition(position);
    setIncreaseAmount(0);
    setMessage('');
  };

  const submitIncrease = async () => {
    if (!selectedPosition || !increaseAmount) return;
    setMessage('');
    const res = await fetch(`/api/positions/${selectedPosition.id}/increase-capital`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ amount: Number(increaseAmount) })
    });
    const data = await res.json();
    setMessage(data.message || (data.success ? 'Capital aumentado' : 'Error al aumentar capital'));
    // Refrescar posiciones
    fetch('/api/positions').then(res => res.json()).then(setPositions);
    setSelectedPosition(null);
    setIncreaseAmount(0);
  };

  // Filtrar posiciones por bot seleccionado
  const botPositions = selectedBot ? positions.filter(p => p.bot_id === selectedBot.id) : [];

  return (
    <div className="dashboard">
      <h1>Mis Bots</h1>
      <div className="bot-cards">
        {bots.map(bot => (
          <div className="bot-card" key={bot.id}>
            <div className="bot-header">
              <span className="bot-status" style={{color: bot.status === 'running' ? 'green' : 'red', fontSize: '1.5em'}}>
                {bot.status === 'running' ? '🟢' : '🔴'}
              </span>
              <span className="bot-title"><b>{bot.id}</b></span>
            </div>
            <div className="bot-info">
              <div>Estrategia: <b>{bot.strategy}</b></div>
              <div>Estado: <span style={{color: bot.status === 'running' ? 'green' : 'red'}}>{bot.status}</span></div>
            </div>
            <div className="bot-actions">
              <button className="action-btn" onClick={() => handleBotDetail(bot)}>Ver posiciones</button>
            </div>
          </div>
        ))}
      </div>

      {selectedBot && (
        <div className="bot-detail">
          <div className="bot-detail-header">
            <h2>Posiciones abiertas de <b>{selectedBot.id}</b></h2>
            <button className="close-btn" onClick={() => setSelectedBot(null)}>Cerrar</button>
          </div>
          <table className="positions-table">
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Side</th>
                <th>Entry</th>
                <th>Qty</th>
                <th>Precio</th>
                <th>PnL</th>
                <th>Acciones</th>
              </tr>
            </thead>
            <tbody>
              {botPositions.map(pos => (
                <tr key={pos.id}>
                  <td>{pos.symbol}</td>
                  <td>{pos.side}</td>
                  <td>{pos.entry_price}</td>
                  <td>{pos.quantity}</td>
                  <td>{pos.current_price}</td>
                  <td>{pos.unrealized_pnl}</td>
                  <td>
                    {getBotStatus(pos.bot_id) === 'running' ? (
                      <button className="action-btn" onClick={() => handleIncrease(pos)}>Aumentar capital</button>
                    ) : (
                      <span style={{color:'gray'}}>Solo disponible con bot activo</span>
                    )}
                    {/* Aquí puedes añadir botón para cerrar posición */}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {selectedPosition && (
        <div className="modal">
          <h3>Aumentar capital en posición de <b>{selectedPosition.symbol}</b></h3>
          <input type="number" min="0.01" step="0.01" value={increaseAmount} onChange={e => setIncreaseAmount(e.target.value)} />
          <button className="action-btn" onClick={submitIncrease}>Confirmar</button>
          <button className="close-btn" onClick={() => setSelectedPosition(null)}>Cancelar</button>
        </div>
      )}
      {message && <div className="message">{message}</div>}
    </div>
  );
}

export default App
