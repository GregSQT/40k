// frontend/src/components/GameLog.tsx
// frontend/src/components/GameLog.tsx
import React from 'react';
import type { BaseLogEntry } from '../../../shared/gameLogStructure.ts';
import { getEventIcon, getEventTypeClass } from '../../../shared/gameLogStructure.ts';

// Use shared interface as base, add frontend-specific fields
export interface GameLogEvent extends BaseLogEntry {
  id: string;
  timestamp: Date;
}
interface GameLogProps {
  events: GameLogEvent[];
  maxEvents?: number;
  getElapsedTime: (timestamp: Date) => string;
  availableHeight?: number;
  useStepNumbers?: boolean;
}

export const GameLog: React.FC<GameLogProps> = ({ events, getElapsedTime, availableHeight = 220, useStepNumbers = false }) => {
  const [visibleRowCount, setVisibleRowCount] = React.useState(4);
  const eventsContainerRef = React.useRef<HTMLDivElement>(null);
  
  // Calculate how many complete rows can fit dynamically
  React.useEffect(() => {
    // Wait for DOM to render, then measure actual log entry height
    const timer = setTimeout(() => {
      const sampleLogEntry = document.querySelector('.game-log-entry');
      if (!sampleLogEntry) {
        setVisibleRowCount(4); // Safe default
        return;
      }
      
      const actualRowHeight = sampleLogEntry.getBoundingClientRect().height;
      const maxRows = Math.floor(availableHeight / actualRowHeight);
      const finalRowCount = Math.max(1, maxRows); // Show at least 1 row
      
      setVisibleRowCount(finalRowCount);
    }, 100);
    
    return () => clearTimeout(timer);
  }, [availableHeight]);

  // Display limited events (newest first) - sort by timestamp descending and limit to calculated rows
  const displayedEvents = [...events]
    .sort((a, b) => b.timestamp.getTime() - a.timestamp.getTime())
    .slice(0, visibleRowCount);

  const formatTime = (timestamp: Date, eventIndex?: number): string => {
    if (useStepNumbers && eventIndex !== undefined) {
      return `#${eventIndex + 1}`;
    }
    return getElapsedTime(timestamp);
  };

  return (
    <div className="game-log">
      <div className="game-log__header">
        <h3 className="game-log__title">Game Log</h3>
        <div className="game-log__count">
          {events.length} events
        </div>
      </div>
      
      <div className="game-log__content">
        {displayedEvents.length === 0 ? (
          <div className="game-log__empty">
            No events yet. Start playing to see the action log!
          </div>
        ) : (
          <div 
            ref={eventsContainerRef}
            className="game-log__events"
            style={{
              maxHeight: `${availableHeight}px`, // Use full available height
              overflow: 'auto'
            }}
          >
            {displayedEvents.map((event) => (
              <div 
                key={event.id} 
                className={`game-log-entry ${getEventTypeClass(event)}`}
              >
                <div className="game-log-entry__single-line">
                  <span className="game-log-entry__icon">
                    {getEventIcon(event.type)}
                  </span>
                  <span className="game-log-entry__time">
                    {formatTime(event.timestamp, events.length - 1 - displayedEvents.findIndex(e => e.id === event.id))}
                  </span>
                  {event.turnNumber && (
                    <span className="game-log-entry__turn">
                      T{event.turnNumber}
                    </span>
                  )}
                  {event.player !== undefined && (
                    <span className={`game-log-entry__player ${event.player === 0 ? 'game-log-entry__player--blue' : 'game-log-entry__player--red'}`}>
                      {event.player === 0 ? 'P1' : 'P2'}
                    </span>
                  )}
                  <span className="game-log-entry__message">
                    {event.message}
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};