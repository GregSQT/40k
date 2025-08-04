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
  availableHeight?: number;
}

export const GameLog: React.FC<GameLogProps> = ({ events, maxEvents = 5, getElapsedTime, availableHeight = 220 }) => {
  const [visibleRowCount, setVisibleRowCount] = React.useState(4);
  const eventsContainerRef = React.useRef<HTMLDivElement>(null);
  
  // Calculate how many complete rows can fit dynamically
  React.useEffect(() => {
    const ROW_HEIGHT = 52; // Fixed height per log entry
    const maxRows = Math.floor(availableHeight / ROW_HEIGHT);
    const finalRowCount = Math.max(1, maxRows); // Show at least 1 row
    
    console.log(`GameLog DEBUG: availableHeight=${availableHeight}px, maxRows=${maxRows}, finalRowCount=${finalRowCount}`);
    console.log(`GameLog: Setting container height to ${finalRowCount * 52}px`);
    setVisibleRowCount(finalRowCount);
  }, [availableHeight]);

  // Display limited events (newest first) - sort by timestamp descending and limit to calculated rows
  const displayedEvents = [...events]
    .sort((a, b) => b.timestamp.getTime() - a.timestamp.getTime())
    .slice(0, visibleRowCount);

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
        const message = event.message;
        console.log('SHOOT DEBUG:', message);
        // Check message text for damage dealt (look for "-X HP" pattern)
        if (message.includes('HP') && message.includes('-')) {
          console.log('Returning: shoot-damage');
          return 'game-log-entry--shoot-damage'; // Red background for damage dealt
        }
        // Check message text for successful save (look for "Saved!" or "Success!")
        if (message.includes('Saved!') || (message.includes('Success!') && !message.includes('Failed!'))) {
          console.log('Returning: shoot-saved');
          return 'game-log-entry--shoot-saved'; // Orange background for hits with no damage
        }
        // Everything else is a miss or failure
        console.log('Returning: shoot-failed');
        return 'game-log-entry--shoot-failed'; // Yellow background for misses/fails
      case 'charge': return 'game-log-entry--charge';
      case 'combat':
        // Check if any attack dealt damage
        const combatDealtDamage = event.shootDetails?.some(shot => shot.damageDealt && shot.damageDealt > 0);
        if (combatDealtDamage) {
          return 'game-log-entry--combat'; // Red background for damage dealt
        }
        // Check if any attack hit but didn't deal damage
        const combatHit = event.shootDetails?.some(shot => shot.hitResult === 'HIT');
        if (combatHit) {
          return 'game-log-entry--combat-no-damage'; // Gray background for hits without damage
        }
        return 'game-log-entry--combat-failed'; // Orange background for complete misses
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
          <div 
            ref={eventsContainerRef}
            className="game-log__events"
            style={{
              height: `${visibleRowCount * 52}px`, // Exact height for complete rows
              overflow: 'hidden'
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
                          let shotText = ` - Shot ${shot.shotNumber}: Hit (${shot.hitTarget}+) ${shot.attackRoll}: ${shot.hitResult === 'HIT' ? 'Success!' : 'Failed!'}`;
                          
                          // Show wound roll if we have wound target data
                          if (shot.woundTarget && shot.woundTarget > 0) {
                            shotText += ` - Wound (${shot.woundTarget}+) ${shot.strengthRoll}: ${shot.strengthResult === 'SUCCESS' ? 'Success!' : 'Failed!'}`;
                          }
                          
                          // Show save roll if we have save target data  
                          if (shot.saveTarget && shot.saveTarget > 0) {
                            shotText += ` - Armor (${shot.saveTarget}+) ${shot.saveRoll}: ${shot.saveSuccess ? 'Success!' : 'Failed!'} : -${shot.damageDealt} HP`;
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