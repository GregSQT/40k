// frontend/src/components/GameLog.tsx
import React from 'react';

export interface GameLogEvent {
  id: string;
  timestamp: Date;
  type: 'turn_change' | 'phase_change' | 'move' | 'shoot' | 'charge' | 'combat' | 'death' | 'move_cancel' | 'charge_cancel';
  message: string;
  turnNumber?: number;
  phase?: string;
  player?: number;
  unitType?: string;
  unitId?: number;
  startHex?: string;
  endHex?: string;
  targetUnitType?: string;
  targetUnitId?: number;
  shootDetails?: {
    shotNumber: number;
    attackRoll: number;
    strengthRoll: number;
    hitResult: 'HIT' | 'MISS';
    strengthResult: 'SUCCESS' | 'FAILED';
    hitTarget?: number;
    woundTarget?: number;
    saveTarget?: number;
    saveRoll?: number;
    saveSuccess?: boolean;
    damageDealt?: number;
  }[];
}

interface GameLogProps {
  events: GameLogEvent[];
  maxEvents?: number;
  getElapsedTime: (timestamp: Date) => string;
}

export const GameLog: React.FC<GameLogProps> = ({ events, maxEvents = 5, getElapsedTime }) => {
  // Display all events (newest first) - maxEvents now controls visual height via CSS
  const displayedEvents = [...events];

  const getEventIcon = (type: GameLogEvent['type']): string => {
    switch (type) {
      case 'turn_change': return '🔄';
      case 'phase_change': return '⏭️';
      case 'move': return '👟';
      case 'shoot': return '🎯';
      case 'charge': return '⚡';
      case 'combat': return '⚔️';
      case 'death': return '💀';
      case 'move_cancel': return '❌';
      case 'charge_cancel': return '❌';
      default: return '📝';
    }
  };

  const getEventTypeClass = (event: GameLogEvent): string => {
    switch (event.type) {
      case 'turn_change': return 'game-log-entry--turn';
      case 'phase_change': return 'game-log-entry--phase';
      case 'move': return 'game-log-entry--move';
      case 'shoot': 
        // Orange for failed shots, red for successful damage
        if (event.shootDetails && event.shootDetails[0]?.damageDealt === 0) {
          return 'game-log-entry--shoot-failed';
        }
        return 'game-log-entry--shoot';
      case 'charge': return 'game-log-entry--charge';
      case 'combat':
        // Orange for failed combat, red for successful damage
        if (event.shootDetails && event.shootDetails[0]?.damageDealt === 0) {
          return 'game-log-entry--combat-failed';
        }
        return 'game-log-entry--combat';
      case 'death': return 'game-log-entry--death';
      case 'move_cancel': 
      case 'charge_cancel': return 'game-log-entry--cancel';
      default: return 'game-log-entry--default';
    }
  };

  const formatTime = (timestamp: Date): string => {
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
          <div className="game-log__events">
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
                    {formatTime(event.timestamp)}
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
                    {(event.type === 'shoot' || event.type === 'combat') && event.shootDetails && (
                      <span className="game-log-entry__shoot-inline">
                        {event.shootDetails.map((shot, index) => {
                          let shotText = ` - Shot ${shot.shotNumber}: Hit (${shot.hitTarget || 3}+) ${shot.attackRoll}: ${shot.hitResult === 'HIT' ? 'Success!' : 'Failed!'}`;
                          
                          if (shot.hitResult === 'HIT' && shot.strengthRoll) {
                            shotText += ` - Wound (${shot.woundTarget || 4}+) ${shot.strengthRoll}: ${shot.strengthResult === 'SUCCESS' ? 'Success!' : 'Failed!'}`;
                          }
                          
                          if (shot.hitResult === 'HIT' && shot.strengthResult === 'SUCCESS' && shot.saveRoll) {
                            shotText += ` - Armor (${shot.saveTarget || 4}+) ${shot.saveRoll}: ${shot.saveSuccess ? 'Success!' : 'Failed!'} : -${shot.damageDealt || 0} HP`;
                          }
                          
                          return (
                            <span key={index} className="game-log-shot-inline">
                              {shotText}
                            </span>
                          );
                        })}
                      </span>
                    )}
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