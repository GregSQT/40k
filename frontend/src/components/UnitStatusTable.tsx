// frontend/src/components/UnitStatusTable.tsx
import React, { memo, useMemo } from 'react';
import { Unit, UnitId } from '../types/game';

interface UnitStatusTableProps {
  units: Unit[];
  player: 0 | 1;
  selectedUnitId: UnitId | null;
  clickedUnitId?: UnitId | null;
  onSelectUnit: (unitId: UnitId) => void;
}

interface UnitRowProps {
  unit: Unit;
  isSelected: boolean;
  isClicked: boolean;
  onSelect: (unitId: UnitId) => void;
}

const UnitRow = memo<UnitRowProps>(({ unit, isSelected, isClicked, onSelect }) => {
  const currentHP = unit.CUR_HP ?? unit.HP_MAX;
  const hpPercentage = (currentHP / unit.HP_MAX) * 100;
  
  return (
    <tr 
      className={`unit-status-row ${isSelected ? 'unit-status-row--selected' : ''} ${isClicked ? 'unit-status-row--clicked' : ''}`}
      onClick={() => {
        console.log('🖱️ Table row clicked for unit:', unit.id);
        console.log('🖱️ About to call onSelect...');
        onSelect(unit.id);
        console.log('🖱️ onSelect call completed');
      }}
      style={{ cursor: 'pointer' }}
    >
      {/* Unit Number */}
      <td className="unit-status-cell unit-status-cell--number">
        {unit.id}
      </td>
      
      {/* Unit Type */}
      <td className="unit-status-cell unit-status-cell--type">
        {unit.type}
      </td>
      
      {/* Current HP with HP Bar */}
      <td className="unit-status-cell unit-status-cell--hp">
        <div className="unit-status-hp-container">
          <span className="unit-status-hp-text">{currentHP}/{unit.HP_MAX}</span>
          <div className="unit-status-hp-bar">
            <div 
              className="unit-status-hp-bar-fill"
              style={{
                width: `${hpPercentage}%`,
                backgroundColor: hpPercentage > 60 ? '#36e36b' : 
                                hpPercentage > 30 ? '#ff9900' : '#ff4444'
              }}
            />
          </div>
        </div>
      </td>
      
      {/* MOVE */}
      <td className="unit-status-cell unit-status-cell--stat">
        {unit.MOVE}
      </td>
      
      {/* T (Toughness) */}
      <td className="unit-status-cell unit-status-cell--stat">
        {unit.T}
      </td>
      
      {/* ARMOR_SAVE */}
      <td className="unit-status-cell unit-status-cell--stat">
        {unit.ARMOR_SAVE}+
      </td>
      
      {/* RNG_RNG (Range) */}
      <td className="unit-status-cell unit-status-cell--stat">
        {unit.RNG_RNG}"
      </td>
      
      {/* RNG_NB (Number of Ranged Attacks) */}
      <td className="unit-status-cell unit-status-cell--stat">
        {unit.RNG_NB}
      </td>
      
      {/* RNG_ATK (Ranged Attack) */}
      <td className="unit-status-cell unit-status-cell--stat">
        {unit.RNG_ATK}+
      </td>
      
      {/* RNG_STR (Ranged Strength) */}
      <td className="unit-status-cell unit-status-cell--stat">
        {unit.RNG_STR}
      </td>
      
      {/* RNG_AP (Ranged AP) */}
      <td className="unit-status-cell unit-status-cell--stat">
        -{unit.RNG_AP}
      </td>
      
      {/* RNG_DMG (Ranged Damage) */}
      <td className="unit-status-cell unit-status-cell--stat">
        {unit.RNG_DMG}
      </td>
      
      {/* CC_NB (Number of Close Combat Attacks) */}
      <td className="unit-status-cell unit-status-cell--stat">
        {unit.CC_NB}
      </td>
      
      {/* CC_ATK (Close Combat Attack) */}
      <td className="unit-status-cell unit-status-cell--stat">
        {unit.CC_ATK}+
      </td>
      
      {/* CC_STR (Close Combat Strength) */}
      <td className="unit-status-cell unit-status-cell--stat">
        {unit.CC_STR}
      </td>
      
      {/* CC_AP (Close Combat AP) */}
      <td className="unit-status-cell unit-status-cell--stat">
        -{unit.CC_AP}
      </td>
      
      {/* CC_DMG (Close Combat Damage) */}
      <td className="unit-status-cell unit-status-cell--stat">
        {unit.CC_DMG}
      </td>
    </tr>
  );
});

UnitRow.displayName = 'UnitRow';

export const UnitStatusTable = memo<UnitStatusTableProps>(({
  units,
  player,
  selectedUnitId,
  clickedUnitId,
  onSelectUnit
}) => {
  // Filter units for this player and exclude dead units
  const playerUnits = useMemo(() => {
    return units.filter(unit => 
      unit.player === player && 
      (unit.CUR_HP ?? unit.HP_MAX) > 0
    );
  }, [units, player]);

  if (playerUnits.length === 0) {
    return (
      <div className="unit-status-table-container">
        <div className="unit-status-table-empty">
          {player === 0 ? "Player 1" : "Player 2"}: No units remaining
        </div>
      </div>
    );
  }

  return (
    <div className="unit-status-table-container">
      <div className="unit-status-table-wrapper">
        <table className="unit-status-table">
          <thead>
            <tr className="unit-status-player-row">
              <th className={`unit-status-player-header ${player === 1 ? 'unit-status-player-header--red' : ''}`} colSpan={17}>
                {player === 0 ? "Player 1" : "Player 2"}
              </th>
            </tr>
            <tr className="unit-status-header-group">
              <th className="unit-status-header-group-cell" colSpan={6}></th>
              <th className="unit-status-header-group-cell" colSpan={6}>RANGE WEAPON</th>
              <th className="unit-status-header-group-cell" colSpan={5}>MELEE WEAPON</th>
            </tr>
            <tr className="unit-status-header">
              <th className="unit-status-header-cell">ID</th>
              <th className="unit-status-header-cell">Type</th>
              <th className="unit-status-header-cell">HP</th>
              <th className="unit-status-header-cell" title="Movement">M</th>
              <th className="unit-status-header-cell" title="Toughness">T</th>
              <th className="unit-status-header-cell" title="Armor Save">SV</th>
              <th className="unit-status-header-cell" title="Range">RNG</th>
              <th className="unit-status-header-cell" title="Number of Ranged Attacks">A</th>
              <th className="unit-status-header-cell" title="Ranged Attack">BS</th>
              <th className="unit-status-header-cell" title="Strength">S</th>
              <th className="unit-status-header-cell" title="Armor Penetration">AP</th>
              <th className="unit-status-header-cell" title="Damage">D</th>
              <th className="unit-status-header-cell" title="Number of Close Combat Attacks">A</th>
              <th className="unit-status-header-cell" title="Close Combat Attack">CC</th>
              <th className="unit-status-header-cell" title="Strength">S</th>
              <th className="unit-status-header-cell" title="Armor Penetration">AP</th>
              <th className="unit-status-header-cell" title="Damage">D</th>
            </tr>
          </thead>
          <tbody>
            {playerUnits.map(unit => (
              <UnitRow
                key={unit.id}
                unit={unit}
                isSelected={selectedUnitId === unit.id}
                isClicked={clickedUnitId === unit.id && selectedUnitId !== unit.id}
                onSelect={onSelectUnit}
              />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
});

UnitStatusTable.displayName = 'UnitStatusTable';