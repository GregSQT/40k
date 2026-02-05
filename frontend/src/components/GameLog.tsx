// frontend/src/components/GameLog.tsx
// frontend/src/components/GameLog.tsx
import React from 'react';
import type { BaseLogEntry, ShootDetail } from '../../../shared/gameLogStructure.ts';
import { getEventIcon, getEventTypeClass } from '../../../shared/gameLogStructure.ts';

// Use shared interface as base, add frontend-specific fields
export interface GameLogEvent extends BaseLogEntry {
  id: string;
  timestamp: Date;
  action_name?: string;
  actionName?: string;
  is_ai_action?: boolean;
  reward?: number;
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
              const actionName = event.action_name || event.actionName;
              const hasWaitActionName = actionName && (actionName.toLowerCase() === 'wait' || actionName.toLowerCase() === 'skip');
              
              // 2. Check event type (backend logs wait actions differently - check message instead)
              const isWaitType = false; // 'wait' is not a valid type in BaseLogEntry, check message instead
              
              // 3. Check message content (frontend logs "chose not to move")
              const message = event.message || '';
              const hasWaitMessage = message.toLowerCase().includes('chose not to move') || 
                                    message.toLowerCase().includes('chose not to charge') ||
                                    message.toLowerCase().endsWith(' wait');

              const isWaitAction = hasWaitActionName || isWaitType || hasWaitMessage;
              const waitClass = isWaitAction ? 'game-log-entry--wait' : '';
              const isObjectiveControl = actionName === 'objective_control';
              const objectiveControlClass = isObjectiveControl
                ? (event.player === 1
                    ? 'game-log-entry--objective-control-p1'
                    : event.player === 2
                      ? 'game-log-entry--objective-control-p2'
                      : 'game-log-entry--objective-control-neutral')
                : '';

              // Shooting / combat outcome badge (MISS / SAVED / DMG)
              let outcomeLabel: string | null = null;
              let outcomeClass: 'miss' | 'saved' | 'damage' | null = null;
              const shootDetails: ShootDetail[] | undefined = event.shootDetails;

              if ((event.type === 'shoot' || event.type === 'combat') && Array.isArray(shootDetails) && shootDetails.length > 0) {
                const targetDied = shootDetails.some((shot) => shot.targetDied === true);
                const hasDamage = shootDetails.some((shot) => shot.damageDealt && shot.damageDealt > 0);
                const hasSave = shootDetails.some((shot) => shot.saveSuccess === true);

                if (hasDamage) {
                  // Sum total damage for display
                  const totalDamage = shootDetails.reduce((sum, shot) => sum + (shot.damageDealt || 0), 0);
                  outcomeLabel = totalDamage > 0 ? `DMG ${totalDamage}` : 'DMG';
                  outcomeClass = 'damage';
                } else if (hasSave) {
                  outcomeLabel = 'SAVED';
                  outcomeClass = 'saved';
                } else if (!targetDied) {
                  // No damage and no successful save => pure miss / failed to wound
                  outcomeLabel = 'MISS';
                  outcomeClass = 'miss';
                }
              }

              return (
              <div 
                key={event.id} 
                className={`game-log-entry ${getEventTypeClass(event)} ${waitClass} ${objectiveControlClass}`}
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
                    <span className={`game-log-entry__player ${event.player === 1 ? 'game-log-entry__player--blue' : 'game-log-entry__player--red'}`}>
                      {event.player === 1 ? 'P1' : 'P2'}
                    </span>
                  )}
                  <span className="game-log-entry__message">
                    {event.message}
                  </span>
                  {outcomeLabel && outcomeClass && (
                    <span className={`game-log-entry__outcome game-log-entry__outcome--${outcomeClass}`}>
                      {outcomeLabel}
                    </span>
                  )}
                  {/* NEW: Debug mode reward display for AI actions */}
                  {debugMode && event.is_ai_action && event.reward !== undefined && (
                    <span className="game-log-entry__reward">
                      {' '}
                      <span className="game-log-entry__reward-action">
                        {(event.action_name || '').toLowerCase()}
                      </span>
                      {' '}
                      <span className="game-log-entry__reward-value">
                        {typeof event.reward === 'number' 
                          ? event.reward.toFixed(2) 
                          : String(event.reward)}
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