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
  currentTurn?: number;
  debugMode?: boolean;
}

export const GameLog: React.FC<GameLogProps> = ({ events, getElapsedTime, availableHeight = 220, useStepNumbers = false, debugMode = false }) => {
  const eventsContainerRef = React.useRef<HTMLDivElement>(null);

  // TEMPORARY DEBUG - Removed to reduce console flooding
  // React.useEffect(() => {
  //   console.log('🔍 GAMELOG DEBUG:', {
  //     debugMode,
  //     eventsCount: events.length,
  //     firstEvent: events[0],
  //     hasRewardInFirst: events[0] && 'reward' in events[0],
  //     hasActionNameInFirst: events[0] && 'action_name' in events[0],
  //     hasIsAiActionInFirst: events[0] && 'is_ai_action' in events[0],
  //     rewardValue: events[0] && (events[0] as any).reward,
  //     actionName: events[0] && (events[0] as any).action_name,
  //     isAiAction: events[0] && (events[0] as any).is_ai_action
  //   });
  // }, [debugMode, events.length]);

  // Display all events (newest first) - sort by timestamp descending, no limit
  const displayedEvents = [...events]
    .sort((a, b) => b.timestamp.getTime() - a.timestamp.getTime());

  const formatTime = (timestamp: Date, eventIndex?: number): string => {
    if (useStepNumbers && eventIndex !== undefined) {
      return `#${eventIndex + 1}`;
    }
    return getElapsedTime(timestamp);
  };

  // Keep newest entry visible when new events arrive
  React.useEffect(() => {
    if (eventsContainerRef.current) {
      eventsContainerRef.current.scrollTop = 0;
    }
  }, [events.length]);

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
            {displayedEvents.map((event) => {
              // Check if this is a wait/skip action
              // Multiple detection methods:
              // 1. Check action_name field
              const actionName = (event as any).action_name || (event as any).actionName;
              const hasWaitActionName = actionName && (actionName.toLowerCase() === 'wait' || actionName.toLowerCase() === 'skip');
              
              // 2. Check event type (backend logs wait actions as type "wait")
              const isWaitType = (event as any).type === 'wait';
              
              // 3. Check message content (frontend logs "chose not to move")
              const message = event.message || '';
              const hasWaitMessage = message.toLowerCase().includes('chose not to move') || 
                                    message.toLowerCase().includes('chose not to charge') ||
                                    message.toLowerCase().endsWith(' wait');
              
              const isWaitAction = hasWaitActionName || isWaitType || hasWaitMessage;
              const waitClass = isWaitAction ? 'game-log-entry--wait' : '';
              
              return (
              <div 
                key={event.id} 
                className={`game-log-entry ${getEventTypeClass(event)} ${waitClass}`}
              >
                <div className="game-log-entry__single-line">
                  <span className={`game-log-entry__icon game-log-entry__icon--${event.type}`}>
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
                  {/* NEW: Debug mode reward display for AI actions */}
                  {debugMode && (event as any).is_ai_action && (event as any).reward !== undefined && (
                    <span className="game-log-entry__reward">
                      {' '}
                      <span className="game-log-entry__reward-action">
                        {((event as any).action_name || '').toLowerCase()}
                      </span>
                      {' '}
                      <span className="game-log-entry__reward-value">
                        {typeof (event as any).reward === 'number' 
                          ? (event as any).reward.toFixed(2) 
                          : (event as any).reward}
                      </span>
                    </span>
                  )}
                </div>
              </div>
            );
            })}
          </div>
        )}
      </div>
    </div>
  );
};