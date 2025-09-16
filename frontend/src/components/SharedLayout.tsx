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
  
  const getButtonClass = (path: string) => 
    `nav-button ${location.pathname === path ? 'nav-button--active' : 'nav-button--inactive'}`;

  return (
    <nav className="navigation">
      <button onClick={() => window.location.href = '/game'} className={getButtonClass('/game')}>PvP</button>
      <button onClick={() => window.location.href = '/game?mode=pve'} className={getButtonClass('/game?mode=pve')}>PvE</button>
      <button onClick={() => window.location.href = '/replay'} className={getButtonClass('/replay')}>Replay</button>
    </nav>
  );
};

export const SharedLayout: React.FC<SharedLayoutProps> = ({
  children,
  rightColumnContent,
  className,
}) => {
  return (
    <div className={`game-controller ${className || ''}`} style={{ background: '#222', height: '100vh' }}>
      <main className="main-content">
        <div className="game-area" style={{ display: 'flex', gap: '16px' }}>
          <div className="game-board-section">
            <ErrorBoundary fallback={<div>Failed to load game board</div>}>
              {children}
            </ErrorBoundary>
          </div>

          <div className="unit-status-tables" style={{ paddingTop: '0px', marginTop: '0px', gap: '4px' }}>
            <Navigation />
            {rightColumnContent}
          </div>
        </div>
      </main>
    </div>
  );
};

export default SharedLayout;