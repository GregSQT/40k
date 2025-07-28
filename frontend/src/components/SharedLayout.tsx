// frontend/src/components/SharedLayout.tsx
import React from 'react';
import { useLocation } from 'react-router-dom';
import { ErrorBoundary } from './ErrorBoundary';

interface SharedLayoutProps {
  children: React.ReactNode; // Left column content (GameBoard, ReplayViewer, etc.)
  rightColumnContent: React.ReactNode; // Right column content (varies by page)
  className?: string;
}

const Navigation: React.FC = () => {
  const location = useLocation();
  
  const getButtonStyle = (path: string) => ({
    padding: '10px 18px',
    backgroundColor: location.pathname === path ? '#1e40af' : '#64748b',
    color: 'white',
    border: 'none',
    borderRadius: '4px',
    marginRight: '8px',
    cursor: 'pointer',
    fontWeight: location.pathname === path ? 'bold' : 'normal'
  });

  return (
    <nav style={{ display: 'flex', gap: '8px', marginBottom: '4px', paddingTop: '0px', marginTop: '0px', justifyContent: 'flex-end' }}>
      <button onClick={() => window.location.href = '/game'} style={getButtonStyle('/game')}>PvP</button>
      <button onClick={() => window.location.href = '/pve'} style={getButtonStyle('/pve')}>PvE</button>
      <button onClick={() => window.location.href = '/replay'} style={getButtonStyle('/replay')}>Replay</button>
    </nav>
  );
};

export const SharedLayout: React.FC<SharedLayoutProps> = ({
  children,
  rightColumnContent,
  className,
}) => {
  return (
    <div className={`game-controller ${className || ''}`} style={{ background: '#222', minHeight: '100vh' }}>
      <main className="main-content">
        <div className="game-area" style={{ display: 'flex', gap: '16px' }}>
          <div className="game-board-section">
            <ErrorBoundary fallback={<div>Failed to load game board</div>}>
              {children}
            </ErrorBoundary>
          </div>

          <div className="unit-status-tables" style={{ paddingTop: '0px', marginTop: '0px', gap: '12px' }}>
            <Navigation />
            {rightColumnContent}
          </div>
        </div>
      </main>
    </div>
  );
};

export default SharedLayout;