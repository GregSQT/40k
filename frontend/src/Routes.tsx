// frontend/src/Routes.tsx

import { BrowserRouter, Routes, Route, Link, Navigate, useLocation } from "react-router-dom";
import HomePage from "./pages/HomePage";
import GamePage from "./pages/GamePage";
import ReplayPage from "./pages/ReplayPage";

function Navigation() {
  const location = useLocation();
  
  const getButtonStyle = (path: string) => ({
    padding: '8px 16px',
    backgroundColor: location.pathname === path ? '#1e40af' : (
      path === '/game' ? '#64748b' : 
      path === '/pve' ? '#64748b' : '#64748b'
    ),
    color: 'white',
    border: 'none',
    borderRadius: '4px',
    marginRight: '8px',
    cursor: 'pointer',
    fontWeight: location.pathname === path ? 'bold' : 'normal'
  });

  return (
    <nav style={{ position: 'fixed', top: '8px', right: '16px', display: 'flex', gap: '8px', zIndex: 1000 }}>
      <button onClick={() => window.location.href = '/game'} style={getButtonStyle('/game')}>PvP</button>
      <button onClick={() => window.location.href = '/pve'} style={getButtonStyle('/pve')}>PvE</button>
      <button onClick={() => window.location.href = '/replay'} style={getButtonStyle('/replay')}>Replay</button>
    </nav>
  );
}

export default function App() {
  return (
    <BrowserRouter>
    <Navigation />
    <Routes>
      {/* Redirect root path directly to game mode */}
      <Route path="/" element={<Navigate to="/game" replace />} />
      <Route path="/home" element={(
        <div style={{ paddingTop: '56px' }}>
          <HomePage />
        </div>
      )} />
      <Route path="/game" element={(
        <div style={{ paddingTop: '56px' }}>
          <GamePage />
        </div>
      )} />
      <Route path="/replay" element={(
        <div style={{ paddingTop: '56px' }}>
          <ReplayPage />
        </div>
      )} />
    </Routes>
  </BrowserRouter>

  );
}