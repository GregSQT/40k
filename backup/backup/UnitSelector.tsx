// components/UnitSelector.tsx
import React, { memo, useMemo } from 'react';
import { Unit, UnitId, GameState } from '../types/game';

interface UnitSelectorProps {
  units: Unit[];
  currentPlayer: GameState['currentPlayer'];
  selectedUnitId: UnitId | null;
  onSelect: (id: UnitId) => void;
  unitsMoved: UnitId[];
  unitsCharged: UnitId[];
  unitsAttacked: UnitId[];
  phase: GameState['phase'];
}

interface UnitButtonProps {
  unit: Unit;
  isSelected: boolean;
  isDisabled: boolean;
  isEligible: boolean;
  onClick: () => void;
  statusText: string;
}

const UnitButton = memo<UnitButtonProps>(({
  unit,
  isSelected,
  isDisabled,
  isEligible,
  onClick,
  statusText,
}) => {
  const currentHP = unit.CUR_HP ?? unit.HP_MAX;
  const hpPercentage = (currentHP / unit.HP_MAX) * 100;
  
  return (
    <button
      onClick={onClick}
      disabled={isDisabled}
      className={`unit-selector__button ${
        isSelected ? 'unit-selector__button--selected' : ''
      } ${
        isEligible ? 'unit-selector__button--eligible' : ''
      }`}
      title={`${unit.name} - ${unit.type} (${currentHP}/${unit.HP_MAX} HP) - ${statusText}`}
      aria-label={`Select ${unit.name}, ${unit.type}, ${currentHP} out of ${unit.HP_MAX} health points, ${statusText}`}
    >
      <div className="unit-selector__button-header">
        <span className="unit-selector__button-name">{unit.name}</span>
        <div className="unit-selector__button-hp">
          <div 
            className="unit-selector__button-hp-bar"
            style={{
              width: '100%',
              height: '3px',
              backgroundColor: '#333',
              borderRadius: '2px',
              overflow: 'hidden',
            }}
          >
            <div
              style={{
                width: `${hpPercentage}%`,
                height: '100%',
                backgroundColor: hpPercentage > 60 ? '#36e36b' : hpPercentage > 30 ? '#ff9900' : '#ff4444',
                transition: 'width 0.3s ease',
              }}
            />
          </div>
          <span className="unit-selector__button-hp-text">
            {currentHP}/{unit.HP_MAX}
          </span>
        </div>
      </div>
      
      <div className="unit-selector__button-footer">
        <span className="unit-selector__button-type">{unit.type}</span>
        <span className="unit-selector__button-status">{statusText}</span>
      </div>
    </button>
  );
});

UnitButton.displayName = 'UnitButton';

export const UnitSelector = memo<UnitSelectorProps>(({
  units,
  currentPlayer,
  selectedUnitId,
  onSelect,
  unitsMoved,
  unitsCharged,
  unitsAttacked,
  phase,
}) => {
  const { eligibleUnits, ineligibleUnits } = useMemo(() => {
    const playerUnits = units.filter(unit => unit.player === currentPlayer);
    
    const getUnitEligibility = (unit: Unit) => {
      const hasActed = {
        move: unitsMoved.includes(unit.id),
        shoot: unitsMoved.includes(unit.id),
        charge: unitsCharged.includes(unit.id),
        combat: unitsAttacked.includes(unit.id),
      };

      const isAdjacent = (u1: Unit, u2: Unit) => 
        Math.max(Math.abs(u1.col - u2.col), Math.abs(u1.row - u2.row)) === 1;

      const isInRange = (u1: Unit, u2: Unit, range: number) =>
        Math.max(Math.abs(u1.col - u2.col), Math.abs(u1.row - u2.row)) <= range;

      const enemies = units.filter(u => u.player !== currentPlayer);

      switch (phase) {
        case 'move':
          return {
            eligible: !hasActed.move,
            reason: hasActed.move ? 'Already moved' : 'Can move',
          };

        case 'shoot':
          if (hasActed.shoot) {
            return { eligible: false, reason: 'Already shot' };
          }
          const canShoot = enemies.some(enemy => isInRange(unit, enemy, unit.RNG_RNG));
          return {
            eligible: canShoot,
            reason: canShoot ? 'Can shoot' : 'No enemies in range',
          };

        case 'charge':
          if (hasActed.charge) {
            return { eligible: false, reason: 'Already charged' };
          }
          const hasAdjacentEnemy = enemies.some(enemy => isAdjacent(unit, enemy));
          if (hasAdjacentEnemy) {
            return { eligible: false, reason: 'Enemy adjacent' };
          }
          const canCharge = enemies.some(enemy => isInRange(unit, enemy, unit.MOVE));
          return {
            eligible: canCharge,
            reason: canCharge ? 'Can charge' : 'No enemies in charge range',
          };

        case 'combat':
          if (hasActed.combat) {
            return { eligible: false, reason: 'Already attacked' };
          }
          const canAttack = enemies.some(enemy => isAdjacent(unit, enemy));
          return {
            eligible: canAttack,
            reason: canAttack ? 'Can attack' : 'No adjacent enemies',
          };

        default:
          return { eligible: false, reason: 'Unknown phase' };
      }
    };

    const eligible: Array<Unit & { reason: string }> = [];
    const ineligible: Array<Unit & { reason: string }> = [];

    playerUnits.forEach(unit => {
      const { eligible: isEligible, reason } = getUnitEligibility(unit);
      const unitWithReason = { ...unit, reason };
      
      if (isEligible) {
        eligible.push(unitWithReason);
      } else {
        ineligible.push(unitWithReason);
      }
    });

    return {
      eligibleUnits: eligible,
      ineligibleUnits: ineligible,
    };
  }, [units, currentPlayer, phase, unitsMoved, unitsCharged, unitsAttacked]);

  const handleUnitClick = (unitId: UnitId) => {
    console.log('[UnitSelector] Unit clicked:', unitId, { phase, unitsMoved, unitsCharged });
    onSelect(unitId);
  };

  const totalUnits = eligibleUnits.length + ineligibleUnits.length;

  if (totalUnits === 0) {
    return (
      <div className="unit-selector">
        <div className="unit-selector__title">No Units Available</div>
        <div className="unit-selector__empty">
          You have no units to control.
        </div>
      </div>
    );
  }

  return (
    <div className="unit-selector">
      <div className="unit-selector__title">
        Select Unit ({eligibleUnits.length}/{totalUnits} available)
      </div>
      
      {eligibleUnits.length > 0 && (
        <div className="unit-selector__section">
          <div className="unit-selector__section-title">Available Units</div>
          {eligibleUnits.map(unit => (
            <UnitButton
              key={unit.id}
              unit={unit}
              isSelected={unit.id === selectedUnitId}
              isDisabled={false}
              isEligible={true}
              onClick={() => handleUnitClick(unit.id)}
              statusText={unit.reason}
            />
          ))}
        </div>
      )}

      {ineligibleUnits.length > 0 && (
        <details className="unit-selector__section unit-selector__section--collapsed">
          <summary className="unit-selector__section-title">
            Unavailable Units ({ineligibleUnits.length})
          </summary>
          {ineligibleUnits.map(unit => (
            <UnitButton
              key={unit.id}
              unit={unit}
              isSelected={false}
              isDisabled={true}
              isEligible={false}
              onClick={() => {}} // No-op for disabled units
              statusText={unit.reason}
            />
          ))}
        </details>
      )}
    </div>
  );
});

UnitSelector.displayName = 'UnitSelector';