// frontend/src/components/UnitStatusTable.tsx
import { memo, useMemo, useState } from 'react';
import type { Unit, UnitId } from '../types/game';

interface UnitStatusTableProps {
  units: Unit[];
  player: 0 | 1;
  selectedUnitId: UnitId | null;
  clickedUnitId?: UnitId | null;
  onSelectUnit: (unitId: UnitId) => void;
  gameMode?: 'pvp' | 'pve' | 'training';
  onCollapseChange?: (collapsed: boolean) => void;
}

interface UnitRowProps {
  unit: Unit;
  isSelected: boolean;
  isClicked: boolean;
  onSelect: (unitId: UnitId) => void;
  isUnitExpanded: boolean;
  onToggleUnitExpand: (unitId: UnitId) => void;
  isRangedExpanded: boolean;
  onToggleRangedExpand: (unitId: UnitId) => void;
  isMeleeExpanded: boolean;
  onToggleMeleeExpand: (unitId: UnitId) => void;
}

const UnitRow = memo<UnitRowProps>(({ 
  unit, 
  isSelected, 
  isClicked, 
  onSelect,
  isUnitExpanded,
  onToggleUnitExpand,
  isRangedExpanded,
  onToggleRangedExpand,
  isMeleeExpanded,
  onToggleMeleeExpand
}) => {
  if (!unit.HP_MAX) {
    throw new Error(`Unit ${unit.id} missing required HP_MAX field`);
  }
  const currentHP = unit.HP_CUR ?? unit.HP_MAX;
  
  const rngWeapons = unit.RNG_WEAPONS || [];
  const ccWeapons = unit.CC_WEAPONS || [];
  
  const unitName = unit.name || unit.type || `Unit ${unit.id}`;
  
  return (
    <div style={{ marginBottom: '12px' }}>
      {/* Unit Attributes Table */}
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <tbody>
          <tr 
            className={`unit-status-row ${isSelected ? 'unit-status-row--selected' : ''} ${isClicked ? 'unit-status-row--clicked' : ''}`}
            onClick={() => onSelect(unit.id)}
            style={{ 
              cursor: 'pointer',
              backgroundColor: isSelected ? 'rgba(100, 150, 255, 0.15)' : isClicked ? 'rgba(255, 200, 100, 0.1)' : 'transparent',
              borderTop: '2px solid rgba(255, 255, 255, 0.2)',
              borderBottom: '1px solid rgba(255, 255, 255, 0.1)'
            }}
          >
            {/* Expand/Collapse Button for Unit */}
            <td className="unit-status-cell unit-status-cell--expand" style={{ textAlign: 'center', padding: '4px 8px', backgroundColor: '#222' }}>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onToggleUnitExpand(unit.id);
                }}
                style={{
                  background: 'rgba(70, 130, 200, 0.2)',
                  border: '1px solid rgba(70, 130, 200, 0.4)',
                  color: '#4682c8',
                  fontSize: '14px',
                  fontWeight: 'bold',
                  cursor: 'pointer',
                  padding: '2px 6px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  minWidth: '24px',
                  minHeight: '24px',
                  borderRadius: '3px',
                  transition: 'all 0.2s ease',
                  margin: '0 auto'
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = 'rgba(70, 130, 200, 0.4)';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = 'rgba(70, 130, 200, 0.2)';
                }}
                aria-label={isUnitExpanded ? 'Collapse unit' : 'Expand unit'}
              >
                {isUnitExpanded ? '−' : '+'}
              </button>
            </td>
            
            {/* ID */}
            <td className="unit-status-cell unit-status-cell--number" style={{ textAlign: 'center', fontWeight: 'bold', padding: '4px 8px', backgroundColor: '#222', borderRight: '1px solid #333' }}>
              {unit.id}
            </td>
          
            {/* Name */}
            <td className="unit-status-cell unit-status-cell--type" style={{ fontWeight: 'bold', textAlign: 'left', padding: '4px 8px' }}>
              {unitName}
            </td>
          
            {/* VALUE */}
            <td className="unit-status-cell unit-status-cell--stat" style={{ textAlign: 'center', padding: '4px 8px' }}>
              {unit.VALUE !== undefined && unit.VALUE !== null ? unit.VALUE : '-'}
            </td>
          
            {/* HP */}
            <td className="unit-status-cell unit-status-cell--hp" style={{ textAlign: 'center', padding: '4px 8px' }}>
              {currentHP}/{unit.HP_MAX}
            </td>
          
            {/* M (Movement) */}
            <td className="unit-status-cell unit-status-cell--stat" style={{ textAlign: 'center', padding: '4px 8px', borderRight: '1px solid #333' }}>
              {unit.MOVE}
            </td>
          
            {/* T (Toughness) */}
            <td className="unit-status-cell unit-status-cell--stat" style={{ textAlign: 'center', padding: '4px 8px' }}>
              {unit.T || '-'}
            </td>
          
            {/* SV (Save Value) */}
            <td className="unit-status-cell unit-status-cell--stat" style={{ textAlign: 'center', padding: '4px 8px' }}>
              {unit.ARMOR_SAVE ? `${unit.ARMOR_SAVE}+` : '-'}
            </td>
          
            {/* LD (Leadership) */}
            <td className="unit-status-cell unit-status-cell--stat" style={{ textAlign: 'center', padding: '4px 8px' }}>
              {unit.LD !== undefined && unit.LD !== null ? unit.LD : '-'}
            </td>
          
            {/* OC (Objective Control) */}
            <td className="unit-status-cell unit-status-cell--stat" style={{ textAlign: 'center', padding: '4px 8px' }}>
              {unit.OC !== undefined && unit.OC !== null ? unit.OC : '-'}
            </td>
          </tr>
        </tbody>
      </table>

      {/* Weapons Tables - Separate and Independent */}
      {isUnitExpanded && (
        <div style={{ marginTop: '4px', marginLeft: '16px' }}>
          {/* RANGE WEAPON(S) Table */}
          {rngWeapons.length > 0 && (
            <table style={{ width: 'calc(100% - 16px)', borderCollapse: 'collapse', marginBottom: '4px' }}>
              <thead>
                <tr 
                  className="unit-status-row unit-status-row--section-header"
                  style={{ 
                    backgroundColor: 'rgba(100, 150, 200, 0.15)',
                    fontWeight: 'bold',
                    fontSize: '0.9em'
                  }}
                >
                  <th 
                    colSpan={7} 
                    className="unit-status-cell" 
                    style={{ 
                      backgroundColor: 'rgba(50, 150, 200, 0.2)', 
                      color: '#ffffff', 
                      textAlign: 'left',
                      padding: '4px 8px',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '8px'
                    }}
                  >
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        onToggleRangedExpand(unit.id);
                      }}
                      style={{
                        background: 'rgba(100, 150, 200, 0.3)',
                        border: '1px solid rgba(100, 150, 200, 0.5)',
                        color: '#6496c8',
                        fontSize: '12px',
                        fontWeight: 'bold',
                        cursor: 'pointer',
                        padding: '2px 5px',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        minWidth: '20px',
                        minHeight: '20px',
                        borderRadius: '3px',
                        transition: 'all 0.2s ease'
                      }}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.background = 'rgba(100, 150, 200, 0.5)';
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.background = 'rgba(100, 150, 200, 0.3)';
                      }}
                      aria-label={isRangedExpanded ? 'Collapse ranged weapons' : 'Expand ranged weapons'}
                    >
                      {isRangedExpanded ? '−' : '+'}
                    </button>
                    RANGE WEAPON(S)
                  </th>
                </tr>
                {isRangedExpanded && (
                  <tr 
                    className="unit-status-row unit-status-row--sub-header"
                    style={{ 
                      backgroundColor: 'rgba(100, 150, 200, 0.08)',
                      fontSize: '0.85em'
                    }}
                  >
                    <th className="unit-status-cell" style={{ textAlign: 'center', padding: '4px 8px', color: '#aee6ff', fontWeight: 'bold' }}>Name</th>
                    <th className="unit-status-cell" style={{ textAlign: 'center', padding: '4px 8px', color: '#aee6ff', fontWeight: 'bold' }}>Rng</th>
                    <th className="unit-status-cell" style={{ textAlign: 'center', padding: '4px 8px', color: '#aee6ff', fontWeight: 'bold' }}>A</th>
                    <th className="unit-status-cell" style={{ textAlign: 'center', padding: '4px 8px', color: '#aee6ff', fontWeight: 'bold' }}>BS</th>
                    <th className="unit-status-cell" style={{ textAlign: 'center', padding: '4px 8px', color: '#aee6ff', fontWeight: 'bold' }}>S</th>
                    <th className="unit-status-cell" style={{ textAlign: 'center', padding: '4px 8px', color: '#aee6ff', fontWeight: 'bold' }}>AP</th>
                    <th className="unit-status-cell" style={{ textAlign: 'center', padding: '4px 8px', color: '#aee6ff', fontWeight: 'bold' }}>DMG</th>
                  </tr>
                )}
              </thead>
              {isRangedExpanded && (
                <tbody>
                  {rngWeapons.map((weapon, idx) => (
                    <tr 
                      key={`rng-${idx}`}
                      className="unit-status-row unit-status-row--weapon"
                      style={{ 
                        backgroundColor: idx % 2 === 0 ? 'rgba(0, 0, 0, 0.1)' : 'transparent'
                      }}
                    >
                      <td className="unit-status-cell" style={{ padding: '4px 8px', textAlign: 'left' }}>
                        {weapon.display_name}
                        {idx === (unit.selectedRngWeaponIndex ?? 0) && (
                          <span style={{ marginLeft: '8px', color: '#64c8ff', fontSize: '0.9em' }}>●</span>
                        )}
                      </td>
                      <td className="unit-status-cell" style={{ textAlign: 'center', padding: '4px 8px' }}>
                        {weapon.RNG ? `${weapon.RNG}\"` : '/'}
                      </td>
                      <td className="unit-status-cell" style={{ textAlign: 'center', padding: '4px 8px' }}>
                        {weapon.NB || 0}
                      </td>
                      <td className="unit-status-cell" style={{ textAlign: 'center', padding: '4px 8px' }}>
                        {weapon.ATK ? `${weapon.ATK}+` : '-'}
                      </td>
                      <td className="unit-status-cell" style={{ textAlign: 'center', padding: '4px 8px' }}>
                        {weapon.STR || '-'}
                      </td>
                      <td className="unit-status-cell" style={{ textAlign: 'center', padding: '4px 8px' }}>
                        {weapon.AP || '-'}
                      </td>
                      <td className="unit-status-cell" style={{ textAlign: 'center', padding: '4px 8px' }}>
                        {weapon.DMG || '-'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              )}
            </table>
          )}
          
          {/* MELEE WEAPON(S) Table */}
          {ccWeapons.length > 0 && (
            <table style={{ width: 'calc(100% - 16px)', borderCollapse: 'collapse' }}>
              <thead>
                <tr 
                  className="unit-status-row unit-status-row--section-header"
                  style={{ 
                    backgroundColor: 'rgba(200, 100, 150, 0.15)',
                    fontWeight: 'bold',
                    fontSize: '0.9em'
                  }}
                >
                  <th 
                    colSpan={7} 
                    className="unit-status-cell" 
                    style={{ 
                      backgroundColor: 'rgba(200, 50, 50, 0.2)', 
                      color: '#ffffff', 
                      textAlign: 'left',
                      padding: '4px 8px',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '8px'
                    }}
                  >
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        onToggleMeleeExpand(unit.id);
                      }}
                      style={{
                        background: 'rgba(200, 100, 150, 0.3)',
                        border: '1px solid rgba(200, 100, 150, 0.5)',
                        color: '#c86496',
                        fontSize: '12px',
                        fontWeight: 'bold',
                        cursor: 'pointer',
                        padding: '2px 5px',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        minWidth: '20px',
                        minHeight: '20px',
                        borderRadius: '3px',
                        transition: 'all 0.2s ease'
                      }}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.background = 'rgba(200, 100, 150, 0.5)';
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.background = 'rgba(200, 100, 150, 0.3)';
                      }}
                      aria-label={isMeleeExpanded ? 'Collapse melee weapons' : 'Expand melee weapons'}
                    >
                      {isMeleeExpanded ? '−' : '+'}
                    </button>
                    MELEE WEAPON(S)
                  </th>
                </tr>
                {isMeleeExpanded && (
                  <tr 
                    className="unit-status-row unit-status-row--sub-header"
                    style={{ 
                      backgroundColor: 'rgba(200, 100, 150, 0.08)',
                      fontSize: '0.85em'
                    }}
                  >
                    <th className="unit-status-cell" style={{ textAlign: 'center', padding: '4px 8px', color: '#aee6ff', fontWeight: 'bold' }}>Name</th>
                    <th className="unit-status-cell" style={{ textAlign: 'center', padding: '4px 8px', color: '#aee6ff', fontWeight: 'bold' }}>Rng</th>
                    <th className="unit-status-cell" style={{ textAlign: 'center', padding: '4px 8px', color: '#aee6ff', fontWeight: 'bold' }}>A</th>
                    <th className="unit-status-cell" style={{ textAlign: 'center', padding: '4px 8px', color: '#aee6ff', fontWeight: 'bold' }}>CC</th>
                    <th className="unit-status-cell" style={{ textAlign: 'center', padding: '4px 8px', color: '#aee6ff', fontWeight: 'bold' }}>S</th>
                    <th className="unit-status-cell" style={{ textAlign: 'center', padding: '4px 8px', color: '#aee6ff', fontWeight: 'bold' }}>AP</th>
                    <th className="unit-status-cell" style={{ textAlign: 'center', padding: '4px 8px', color: '#aee6ff', fontWeight: 'bold' }}>DMG</th>
                  </tr>
                )}
              </thead>
              {isMeleeExpanded && (
                <tbody>
                  {ccWeapons.map((weapon, idx) => (
                    <tr 
                      key={`cc-${idx}`}
                      className="unit-status-row unit-status-row--weapon"
                      style={{ 
                        backgroundColor: idx % 2 === 0 ? 'rgba(0, 0, 0, 0.1)' : 'transparent'
                      }}
                    >
                      <td className="unit-status-cell" style={{ padding: '4px 8px', textAlign: 'left' }}>
                        {weapon.display_name}
                        {idx === (unit.selectedCcWeaponIndex ?? 0) && (
                          <span style={{ marginLeft: '8px', color: '#ff96c8', fontSize: '0.9em' }}>●</span>
                        )}
                      </td>
                      <td className="unit-status-cell" style={{ textAlign: 'center', padding: '4px 8px' }}>
                        /
                      </td>
                      <td className="unit-status-cell" style={{ textAlign: 'center', padding: '4px 8px' }}>
                        {weapon.NB || 0}
                      </td>
                      <td className="unit-status-cell" style={{ textAlign: 'center', padding: '4px 8px' }}>
                        {weapon.ATK ? `${weapon.ATK}+` : '-'}
                      </td>
                      <td className="unit-status-cell" style={{ textAlign: 'center', padding: '4px 8px' }}>
                        {weapon.STR || '-'}
                      </td>
                      <td className="unit-status-cell" style={{ textAlign: 'center', padding: '4px 8px' }}>
                        {weapon.AP || '-'}
                      </td>
                      <td className="unit-status-cell" style={{ textAlign: 'center', padding: '4px 8px' }}>
                        {weapon.DMG || '-'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              )}
            </table>
          )}
        </div>
      )}
    </div>
  );
});

UnitRow.displayName = 'UnitRow';

export const UnitStatusTable = memo<UnitStatusTableProps>(({
  units,
  player,
  selectedUnitId,
  clickedUnitId,
  onSelectUnit,
  gameMode = 'pvp',
  onCollapseChange
}) => {
  // Collapse/expand state for entire table
  const [isCollapsed, setIsCollapsed] = useState(false);
  
  // Expanded units state (per unit expand/collapse for weapons)
  const [expandedUnits, setExpandedUnits] = useState<Set<UnitId>>(new Set());
  const [expandedRanged, setExpandedRanged] = useState<Set<UnitId>>(new Set());
  const [expandedMelee, setExpandedMelee] = useState<Set<UnitId>>(new Set());
  
  const toggleUnitExpand = (unitId: UnitId) => {
    setExpandedUnits(prev => {
      const next = new Set(prev);
      const isCurrentlyExpanded = next.has(unitId);
      if (isCurrentlyExpanded) {
        next.delete(unitId);
        // Also collapse weapons when collapsing unit
        setExpandedRanged(prevRng => {
          const nextRng = new Set(prevRng);
          nextRng.delete(unitId);
          return nextRng;
        });
        setExpandedMelee(prevMelee => {
          const nextMelee = new Set(prevMelee);
          nextMelee.delete(unitId);
          return nextMelee;
        });
      } else {
        next.add(unitId);
        // Also expand weapons when expanding unit
        setExpandedRanged(prevRng => {
          const nextRng = new Set(prevRng);
          nextRng.add(unitId);
          return nextRng;
        });
        setExpandedMelee(prevMelee => {
          const nextMelee = new Set(prevMelee);
          nextMelee.add(unitId);
          return nextMelee;
        });
      }
      return next;
    });
  };
  
  const toggleRangedExpand = (unitId: UnitId) => {
    setExpandedRanged(prev => {
      const next = new Set(prev);
      if (next.has(unitId)) {
        next.delete(unitId);
      } else {
        next.add(unitId);
      }
      return next;
    });
  };
  
  const toggleMeleeExpand = (unitId: UnitId) => {
    setExpandedMelee(prev => {
      const next = new Set(prev);
      if (next.has(unitId)) {
        next.delete(unitId);
      } else {
        next.add(unitId);
      }
      return next;
    });
  };
  
  // Filter units for this player and exclude dead units
  const playerUnits = useMemo(() => {
    return units.filter(unit => 
      unit.player === player && 
      (unit.HP_CUR ?? unit.HP_MAX) > 0
    );
  }, [units, player]);

  const getPlayerTypeLabel = (playerNumber: 0 | 1): string => {
    if (gameMode === 'training') {
      return playerNumber === 0 ? 'Player 1 - Bot' : 'Player 2 - AI';
    } else if (gameMode === 'pve') {
      return playerNumber === 0 ? 'Player 1 - Human' : 'Player 2 - AI';
    } else { // pvp
      return playerNumber === 0 ? 'Player 1 - Human' : 'Player 2 - Human';
    }
  };

  if (playerUnits.length === 0) {
    return (
      <div className="unit-status-table-container">
        <div className="unit-status-table-empty">
          {getPlayerTypeLabel(player)}: No units remaining
        </div>
      </div>
    );
  }

  return (
    <div className="unit-status-table-container">
      <div className="unit-status-table-wrapper">
        <table className="unit-status-table" style={{ width: '100%', borderCollapse: 'collapse' }}>
          <colgroup>
            <col />
            <col />
            <col />
            <col />
            <col />
            <col />
            <col />
            <col />
            <col />
            <col />
          </colgroup>
          <thead>
            <tr className="unit-status-player-row">
              <th 
                className={`unit-status-player-header ${player === 1 ? 'unit-status-player-header--red' : ''}`} 
                colSpan={10}
                style={{
                  backgroundColor: player === 1 ? 'rgba(200, 50, 50, 0.2)' : 'rgba(50, 150, 200, 0.2)',
                  padding: '8px',
                  textAlign: 'left',
                  fontWeight: 'bold',
                  border: '1px solid rgba(0, 0, 0, 0.2)',
                  width: '100%'
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <button
                    onClick={() => {
                      const newCollapsed = !isCollapsed;
                      setIsCollapsed(newCollapsed);
                      onCollapseChange?.(newCollapsed);
                    }}
                    style={{
                      background: 'rgba(0, 0, 0, 0.2)',
                      border: '1px solid rgba(0, 0, 0, 0.3)',
                      color: 'inherit',
                      fontSize: '16px',
                      fontWeight: 'bold',
                      cursor: 'pointer',
                      padding: '4px 8px',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      minWidth: '24px',
                      minHeight: '24px',
                      borderRadius: '4px',
                      transition: 'all 0.2s ease'
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.background = 'rgba(0, 0, 0, 0.3)';
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.background = 'rgba(0, 0, 0, 0.2)';
                    }}
                    aria-label={isCollapsed ? 'Expand table' : 'Collapse table'}
                  >
                    {isCollapsed ? '+' : '−'}
                  </button>
                  <span>{getPlayerTypeLabel(player)}</span>
                </div>
              </th>
            </tr>
            {!isCollapsed && (
              <tr className="unit-status-header">
                <th className="unit-status-header-cell" style={{ padding: '6px 8px', textAlign: 'center', backgroundColor: 'rgba(0, 0, 0, 0.05)', border: '1px solid rgba(0, 0, 0, 0.1)' }}></th>
                <th className="unit-status-header-cell" style={{ padding: '6px 8px', textAlign: 'center', backgroundColor: 'rgba(0, 0, 0, 0.05)', border: '1px solid rgba(0, 0, 0, 0.1)', borderRight: '1px solid rgba(0, 0, 0, 0.1)' }}>ID</th>
                <th className="unit-status-header-cell" style={{ padding: '6px 8px', textAlign: 'center', backgroundColor: 'rgba(0, 0, 0, 0.05)', border: '1px solid rgba(0, 0, 0, 0.1)' }}>Name</th>
                <th className="unit-status-header-cell" style={{ padding: '6px 8px', textAlign: 'center', backgroundColor: 'rgba(0, 0, 0, 0.05)', border: '1px solid rgba(0, 0, 0, 0.1)' }}>VALUE</th>
                <th className="unit-status-header-cell" style={{ padding: '6px 8px', textAlign: 'center', backgroundColor: 'rgba(0, 0, 0, 0.05)', border: '1px solid rgba(0, 0, 0, 0.1)' }}>HP</th>
                <th className="unit-status-header-cell" style={{ padding: '6px 8px', textAlign: 'center', backgroundColor: 'rgba(0, 0, 0, 0.05)', border: '1px solid rgba(0, 0, 0, 0.1)', borderRight: '1px solid rgba(0, 0, 0, 0.1)' }} title="Movement">M</th>
                <th className="unit-status-header-cell" style={{ padding: '6px 8px', textAlign: 'center', backgroundColor: 'rgba(0, 0, 0, 0.05)', border: '1px solid rgba(0, 0, 0, 0.1)' }} title="Toughness">T</th>
                <th className="unit-status-header-cell" style={{ padding: '6px 8px', textAlign: 'center', backgroundColor: 'rgba(0, 0, 0, 0.05)', border: '1px solid rgba(0, 0, 0, 0.1)' }} title="Save Value">SV</th>
                <th className="unit-status-header-cell" style={{ padding: '6px 8px', textAlign: 'center', backgroundColor: 'rgba(0, 0, 0, 0.05)', border: '1px solid rgba(0, 0, 0, 0.1)' }} title="Leadership">LD</th>
                <th className="unit-status-header-cell" style={{ padding: '6px 8px', textAlign: 'center', backgroundColor: 'rgba(0, 0, 0, 0.05)', border: '1px solid rgba(0, 0, 0, 0.1)' }} title="Objective Control">OC</th>
              </tr>
            )}
          </thead>
          <tbody>
            {!isCollapsed && playerUnits.map(unit => (
              <UnitRow
                key={unit.id}
                unit={unit}
                isSelected={selectedUnitId === unit.id}
                isClicked={clickedUnitId === unit.id && selectedUnitId !== unit.id}
                onSelect={onSelectUnit}
                isUnitExpanded={expandedUnits.has(unit.id)}
                onToggleUnitExpand={toggleUnitExpand}
                isRangedExpanded={expandedRanged.has(unit.id)}
                onToggleRangedExpand={toggleRangedExpand}
                isMeleeExpanded={expandedMelee.has(unit.id)}
                onToggleMeleeExpand={toggleMeleeExpand}
              />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
});

UnitStatusTable.displayName = 'UnitStatusTable';
