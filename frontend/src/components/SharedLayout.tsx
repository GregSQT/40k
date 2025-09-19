// frontend/src/components/SharedLayout.tsx
import React from 'react';
import { useLocation } from 'react-router-dom';
import { ErrorBoundary } from './ErrorBoundary';

interface SharedLayoutProps {
  children: React.ReactNode; // Left column content (GameBoard, ReplayViewer, etc.)
  rightColumnContent: React.ReactNode; // Right column content (varies by page)
  className?: string;
  showHexCoordinates?: boolean;
  onToggleHexCoordinates?: (checked: boolean) => void;
}

interface NavigationProps {
  showHexCoordinates?: boolean;
  onToggleHexCoordinates?: (checked: boolean) => void;
}

const Navigation: React.FC<NavigationProps> = ({ showHexCoordinates, onToggleHexCoordinates }) => {
  const location = useLocation();
  
  const getButtonClass = (path: string) => {
    const isPvEMode = location.pathname === '/game' && location.search.includes('mode=pve');
    
    // Handle PvE mode detection via query parameter
    if (path === '/game?mode=pve') {
      return `nav-button ${isPvEMode ? 'nav-button--active' : 'nav-button--inactive'}`;
    }
    
    // Handle PvP mode - only active when on /game WITHOUT PvE mode
    if (path === '/game') {
      const isPvPMode = location.pathname === '/game' && !isPvEMode;
      return `nav-button ${isPvPMode ? 'nav-button--active' : 'nav-button--inactive'}`;
    }
    
    // Handle standard path matching for Replay and other routes
    return `nav-button ${location.pathname === path ? 'nav-button--active' : 'nav-button--inactive'}`;
  };

  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%' }}>
      <nav className="navigation">
        <button onClick={() => window.location.href = '/game'} className={getButtonClass('/game')}>PvP</button>
        <button onClick={() => window.location.href = '/game?mode=pve'} className={getButtonClass('/game?mode=pve')}>PvE</button>
        <button onClick={() => window.location.href = '/replay'} className={getButtonClass('/replay')}>Replay</button>
      </nav>
      
      {onToggleHexCoordinates && (
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '6px 10px', backgroundColor: '#374151', border: '1px solid #4b5563', borderRadius: '6px' }}>
          <span style={{ fontSize: '12px', fontWeight: '500', color: 'white', whiteSpace: 'nowrap' }}>Hex Coords</span>
          <label style={{ position: 'relative', display: 'inline-flex', alignItems: 'center', cursor: 'pointer' }}>
            <input
              type="checkbox"
              style={{ position: 'absolute', width: '1px', height: '1px', padding: '0', margin: '-1px', overflow: 'hidden', clip: 'rect(0, 0, 0, 0)', whiteSpace: 'nowrap', border: '0' }}
              checked={showHexCoordinates || false}
              onChange={(e) => onToggleHexCoordinates(e.target.checked)}
            />
            <div style={{
              width: '36px', 
              height: '20px', 
              backgroundColor: showHexCoordinates ? '#2563eb' : '#6b7280', 
              borderRadius: '10px', 
              position: 'relative',
              transition: 'background-color 0.2s ease'
            }}>
              <div style={{
                width: '16px',
                height: '16px',
                backgroundColor: 'white',
                borderRadius: '50%',
                position: 'absolute',
                top: '2px',
                left: showHexCoordinates ? '18px' : '2px',
                transition: 'left 0.2s ease'
              }} />
            </div>
          </label>
        </div>
      )}
    </div>
  );
};

export const SharedLayout: React.FC<SharedLayoutProps> = ({
  children,
  rightColumnContent,
  className,
  showHexCoordinates,
  onToggleHexCoordinates,
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
            <Navigation 
              showHexCoordinates={showHexCoordinates}
              onToggleHexCoordinates={onToggleHexCoordinates}
            />
            {rightColumnContent}
          </div>
        </div>
      </main>
    </div>
  );
};

export default SharedLayout;