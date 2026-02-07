// frontend/src/components/UnitStatusTable.tsx
import { memo, useMemo, useState } from 'react';
import type { Unit, UnitId } from '../types/game';

interface UnitStatusTableProps {
  units: Unit[];
  player: 1 | 2;
  selectedUnitId: UnitId | null;
  clickedUnitId?: UnitId | null;
  onSelectUnit: (unitId: UnitId) => void;
  gameMode?: 'pvp' | 'debug' | 'pve' | 'training';
  isReplay?: boolean;
  victoryPoints?: number;
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
    <div style={{ marginBottom: '2px' }}>
      {/* Unit Attributes Table */}
      <table style={{ width: '100%', borderCollapse: 'collapse', tableLayout: 'fixed' }}>
        <colgroup>
          <col style={{ width: '40px' }} />
          <col style={{ width: '40px' }} />
          <col style={{ width: 'auto' }} />
          <col style={{ width: '70px' }} />
          <col style={{ width: '70px' }} />
          <col style={{ width: '70px' }} />
          <col style={{ width: '70px' }} />
          <col style={{ width: '70px' }} />
          <col style={{ width: '70px' }} />
          <col style={{ width: '70px' }} />
        </colgroup>
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
            <td className="unit-status-cell unit-status-cell--number" style={{ textAlign: 'center', fontWeight: 'bold', padding: '4px 8px', backgroundColor: '#222', borderRight: '1px solid #333', fontSize: '12px' }}>
              {unit.id}
            </td>
          
            {/* Name */}
            <td className="unit-status-cell unit-status-cell--type" style={{ fontWeight: 'bold', textAlign: 'left', padding: '4px 8px', backgroundColor: '#222', fontSize: '12px' }}>
              {unitName}
            </td>
          
            {/* HP */}
            <td className="unit-status-cell unit-status-cell--hp" style={{ textAlign: 'center', padding: '4px 8px', backgroundColor: '#222', fontSize: '12px' }}>
              {currentHP}/{unit.HP_MAX}
            </td>
          
            {/* M (Movement) */}
            <td className="unit-status-cell unit-status-cell--stat" style={{ textAlign: 'center', padding: '4px 8px', backgroundColor: '#222', borderRight: '1px solid #333', fontSize: '12px' }}>
              {unit.MOVE}
            </td>
          
            {/* T (Toughness) */}
            <td className="unit-status-cell unit-status-cell--stat" style={{ textAlign: 'center', padding: '4px 8px', backgroundColor: '#222', fontSize: '12px' }}>
              {unit.T || '-'}
            </td>
          
            {/* SV (Save Value) */}
            <td className="unit-status-cell unit-status-cell--stat" style={{ textAlign: 'center', padding: '4px 8px', backgroundColor: '#222', fontSize: '12px' }}>
              {unit.ARMOR_SAVE ? `${unit.ARMOR_SAVE}+` : '-'}
            </td>
          
            {/* LD (Leadership) */}
            <td className="unit-status-cell unit-status-cell--stat" style={{ textAlign: 'center', padding: '4px 8px', backgroundColor: '#222', fontSize: '12px' }}>
              {unit.LD || '-'}
            </td>
          
            {/* OC (Objective Control) */}
            <td className="unit-status-cell unit-status-cell--stat" style={{ textAlign: 'center', padding: '4px 8px', backgroundColor: '#222', fontSize: '12px' }}>
              {unit.OC || '-'}
            </td>
          
            {/* VALUE */}
            <td className="unit-status-cell unit-status-cell--stat" style={{ textAlign: 'center', padding: '4px 8px', backgroundColor: '#222', fontSize: '12px' }}>
              {unit.VALUE || '-'}
            </td>
          </tr>
        </tbody>
      </table>

      {/* Weapons Tables - Separate and Independent */}
      {isUnitExpanded && (
        <div style={{ marginTop: '4px', marginLeft: '16px' }}>
          {/* RANGE WEAPON(S) Table */}
          {rngWeapons.length > 0 && (
            <table style={{ width: 'calc(100% - 16px)', borderCollapse: 'collapse', marginBottom: '4px', tableLayout: 'fixed' }}>
              <colgroup>
                <col style={{ width: '200px' }} />
                <col style={{ width: '48px' }} />
                <col style={{ width: '48px' }} />
                <col style={{ width: '48px' }} />
                <col style={{ width: '48px' }} />
                <col style={{ width: '48px' }} />
                <col style={{ width: '48px' }} />
              </colgroup>
              <thead>
                <tr 
                  className="unit-status-row unit-status-row--section-header"
                  style={{ 
                    backgroundColor: 'rgba(50, 150, 200, 0.2)',
                    fontWeight: 'bold',
                    fontSize: '0.9em'
                  }}
                >
                  <th 
                    className="unit-status-cell" 
                    style={{ 
                      backgroundColor: 'rgba(50, 150, 200, 0.2)', 
                      color: '#ffffff', 
                      textAlign: 'left',
                      padding: '4px 8px'
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
                        display: 'inline-flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        minWidth: '20px',
                        minHeight: '20px',
                        borderRadius: '3px',
                        transition: 'all 0.2s ease',
                        marginRight: '8px',
                        verticalAlign: 'middle'
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
                    <span style={{ fontSize: '11px' }}>RANGE WEAPON(S)</span>
                  </th>
                  <th className="unit-status-cell" style={{ textAlign: 'center', padding: '4px 8px', color: '#aee6ff', fontWeight: 'bold', fontSize: '11px', backgroundColor: 'rgba(50, 150, 200, 0.2)' }}>Rng</th>
                  <th className="unit-status-cell" style={{ textAlign: 'center', padding: '4px 8px', color: '#aee6ff', fontWeight: 'bold', fontSize: '11px', backgroundColor: 'rgba(50, 150, 200, 0.2)' }}>A</th>
                  <th className="unit-status-cell" style={{ textAlign: 'center', padding: '4px 8px', color: '#aee6ff', fontWeight: 'bold', fontSize: '11px', backgroundColor: 'rgba(50, 150, 200, 0.2)' }}>BS</th>
                  <th className="unit-status-cell" style={{ textAlign: 'center', padding: '4px 8px', color: '#aee6ff', fontWeight: 'bold', fontSize: '11px', backgroundColor: 'rgba(50, 150, 200, 0.2)' }}>S</th>
                  <th className="unit-status-cell" style={{ textAlign: 'center', padding: '4px 8px', color: '#aee6ff', fontWeight: 'bold', fontSize: '11px', backgroundColor: 'rgba(50, 150, 200, 0.2)' }}>AP</th>
                  <th className="unit-status-cell" style={{ textAlign: 'center', padding: '4px 8px', color: '#aee6ff', fontWeight: 'bold', fontSize: '11px', backgroundColor: 'rgba(50, 150, 200, 0.2)' }}>DMG</th>
                </tr>
              </thead>
              {isRangedExpanded && (
                <tbody>
                  {rngWeapons.map((weapon, idx) => (
                    <tr 
                      key={`rng-${idx}`}
                      className="unit-status-row unit-status-row--weapon"
                      style={{ 
                        backgroundColor: idx === 0 ? '#222' : '#2a2a2a'
                      }}
                    >
                      <td className="unit-status-cell" style={{ padding: '4px 8px', textAlign: 'right', fontSize: '12px' }}>
                        {weapon.display_name}
                        {idx === (unit.selectedRngWeaponIndex ?? 0) && (
                          <span style={{ marginLeft: '8px', color: '#64c8ff', fontSize: '0.9em' }}>●</span>
                        )}
                      </td>
                      <td className="unit-status-cell" style={{ textAlign: 'center', padding: '4px 8px', fontSize: '12px' }}>
                        {weapon.RNG ? `${weapon.RNG}"` : '/'}
                      </td>
                      <td className="unit-status-cell" style={{ textAlign: 'center', padding: '4px 8px', fontSize: '12px' }}>
                        {weapon.NB || 0}
                      </td>
                      <td className="unit-status-cell" style={{ textAlign: 'center', padding: '4px 8px', fontSize: '12px' }}>
                        {weapon.ATK ? `${weapon.ATK}+` : '-'}
                      </td>
                      <td className="unit-status-cell" style={{ textAlign: 'center', padding: '4px 8px', fontSize: '12px' }}>
                        {weapon.STR || '-'}
                      </td>
                      <td className="unit-status-cell" style={{ textAlign: 'center', padding: '4px 8px', fontSize: '12px', borderRight: '1px solid #333' }}>
                        {weapon.AP || '-'}
                      </td>
                      <td className="unit-status-cell" style={{ textAlign: 'center', padding: '4px 8px', fontSize: '12px' }}>
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
            <table style={{ width: 'calc(100% - 16px)', borderCollapse: 'collapse', tableLayout: 'fixed' }}>
              <colgroup>
                <col style={{ width: '200px' }} />
                <col style={{ width: '48px' }} />
                <col style={{ width: '48px' }} />
                <col style={{ width: '48px' }} />
                <col style={{ width: '48px' }} />
                <col style={{ width: '48px' }} />
                <col style={{ width: '48px' }} />
              </colgroup>
              <thead>
                <tr 
                  className="unit-status-row unit-status-row--section-header"
                  style={{ 
                    backgroundColor: 'rgba(200, 50, 50, 0.2)',
                    fontWeight: 'bold',
                    fontSize: '0.9em'
                  }}
                >
                  <th 
                    className="unit-status-cell" 
                    style={{ 
                      backgroundColor: 'rgba(200, 50, 50, 0.2)', 
                      color: '#ffffff', 
                      textAlign: 'left',
                      padding: '4px 8px'
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
                        display: 'inline-flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        minWidth: '20px',
                        minHeight: '20px',
                        borderRadius: '3px',
                        transition: 'all 0.2s ease',
                        marginRight: '8px',
                        verticalAlign: 'middle'
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
                    <span style={{ fontSize: '11px' }}>MELEE WEAPON(S)</span>
                  </th>
                  <th className="unit-status-cell" style={{ textAlign: 'center', padding: '4px 8px', color: '#aee6ff', fontWeight: 'bold', fontSize: '11px', backgroundColor: 'rgba(200, 50, 50, 0.2)' }}>Rng</th>
                  <th className="unit-status-cell" style={{ textAlign: 'center', padding: '4px 8px', color: '#aee6ff', fontWeight: 'bold', fontSize: '11px', backgroundColor: 'rgba(200, 50, 50, 0.2)' }}>A</th>
                  <th className="unit-status-cell" style={{ textAlign: 'center', padding: '4px 8px', color: '#aee6ff', fontWeight: 'bold', fontSize: '11px', backgroundColor: 'rgba(200, 50, 50, 0.2)' }}>CC</th>
                  <th className="unit-status-cell" style={{ textAlign: 'center', padding: '4px 8px', color: '#aee6ff', fontWeight: 'bold', fontSize: '11px', backgroundColor: 'rgba(200, 50, 50, 0.2)' }}>S</th>
                  <th className="unit-status-cell" style={{ textAlign: 'center', padding: '4px 8px', color: '#aee6ff', fontWeight: 'bold', fontSize: '11px', backgroundColor: 'rgba(200, 50, 50, 0.2)' }}>AP</th>
                  <th className="unit-status-cell" style={{ textAlign: 'center', padding: '4px 8px', color: '#aee6ff', fontWeight: 'bold', fontSize: '11px', backgroundColor: 'rgba(200, 50, 50, 0.2)' }}>DMG</th>
                </tr>
              </thead>
              {isMeleeExpanded && (
                <tbody>
                  {ccWeapons.map((weapon, idx) => (
                    <tr 
                      key={`cc-${idx}`}
                      className="unit-status-row unit-status-row--weapon"
                      style={{ 
                        backgroundColor: idx === 0 ? '#222' : '#2a2a2a'
                      }}
                    >
                      <td className="unit-status-cell" style={{ padding: '4px 8px', textAlign: 'right', fontSize: '12px' }}>
                        {weapon.display_name}
                        {idx === (unit.selectedCcWeaponIndex ?? 0) && (
                          <span style={{ marginLeft: '8px', color: '#ff96c8', fontSize: '0.9em' }}>●</span>
                        )}
                      </td>
                      <td className="unit-status-cell" style={{ textAlign: 'center', padding: '4px 8px', fontSize: '12px' }}>
                        /
                      </td>
                      <td className="unit-status-cell" style={{ textAlign: 'center', padding: '4px 8px', fontSize: '12px' }}>
                        {weapon.NB || 0}
                      </td>
                      <td className="unit-status-cell" style={{ textAlign: 'center', padding: '4px 8px', fontSize: '12px' }}>
                        {weapon.ATK ? `${weapon.ATK}+` : '-'}
                      </td>
                      <td className="unit-status-cell" style={{ textAlign: 'center', padding: '4px 8px', fontSize: '12px' }}>
                        {weapon.STR || '-'}
                      </td>
                      <td className="unit-status-cell" style={{ textAlign: 'center', padding: '4px 8px', fontSize: '12px', borderRight: '1px solid #333' }}>
                        {weapon.AP || '-'}
                      </td>
                      <td className="unit-status-cell" style={{ textAlign: 'center', padding: '4px 8px', fontSize: '12px' }}>
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
  isReplay = false,
  victoryPoints,
  onCollapseChange
}) => {
  // Collapse/expand state for entire table
  const [isCollapsed, setIsCollapsed] = useState(true);
  
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

  const getPlayerTypeLabel = (playerNumber: 1 | 2): string => {
    if (gameMode === 'training') {
      if (isReplay) {
        return playerNumber === 2 ? 'Player 2 - Bot' : 'Player 1 - AI';
      }
      return playerNumber === 2 ? 'Player 1 - AI' : 'Player 2 - Bot';
    } else if (gameMode === 'debug' || gameMode === 'pve') {
      return playerNumber === 1 ? 'Player 1 - Human' : 'Player 2 - AI';
    } else { // pvp
      return playerNumber === 1 ? 'Player 1 - Human' : 'Player 2 - Human';
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
        {/* Player Header */}
        <div 
          className={`unit-status-player-header ${player === 2 ? 'unit-status-player-header--red' : ''}`}
          style={{
            backgroundColor: player === 2 ? 'var(--hp-bar-player2)' : 'var(--hp-bar-player1)',
            padding: '4px 8px',
            textAlign: 'left',
            fontWeight: 'bold',
            border: '1px solid rgba(0, 0, 0, 0.2)',
            marginBottom: '4px'
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
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
              <span style={{ fontSize: '16px' }}>{getPlayerTypeLabel(player)}</span>
            </div>
            {victoryPoints !== undefined && (
              <span style={{ fontSize: '14px' }}>{`VP : ${victoryPoints}`}</span>
            )}
          </div>
        </div>

        {/* Column Headers */}
        {!isCollapsed && (
          <table style={{ width: '100%', borderCollapse: 'collapse', marginBottom: '2px', tableLayout: 'fixed' }}>
            <colgroup>
              <col style={{ width: '40px' }} />
              <col style={{ width: '40px' }} />
              <col style={{ width: 'auto' }} />
              <col style={{ width: '70px' }} />
              <col style={{ width: '70px' }} />
              <col style={{ width: '70px' }} />
              <col style={{ width: '70px' }} />
              <col style={{ width: '70px' }} />
              <col style={{ width: '70px' }} />
              <col style={{ width: '70px' }} />
            </colgroup>
            <thead>
              <tr className="unit-status-header">
                <th className="unit-status-header-cell" style={{ padding: '6px 8px', textAlign: 'center', backgroundColor: 'rgba(0, 0, 0, 0.05)', border: '1px solid rgba(0, 0, 0, 0.1)', fontSize: '14px' }}></th>
                <th className="unit-status-header-cell" style={{ padding: '6px 8px', textAlign: 'center', backgroundColor: 'rgba(0, 0, 0, 0.05)', border: '1px solid rgba(0, 0, 0, 0.1)', borderRight: '1px solid rgba(0, 0, 0, 0.1)', fontSize: '14px' }}>ID</th>
                <th className="unit-status-header-cell" style={{ padding: '6px 8px', textAlign: 'center', backgroundColor: 'rgba(0, 0, 0, 0.05)', border: '1px solid rgba(0, 0, 0, 0.1)', fontSize: '14px' }}>Name</th>
                <th className="unit-status-header-cell" style={{ padding: '6px 8px', textAlign: 'center', backgroundColor: 'rgba(0, 0, 0, 0.05)', border: '1px solid rgba(0, 0, 0, 0.1)', fontSize: '14px' }}>HP</th>
                <th className="unit-status-header-cell" style={{ padding: '6px 8px', textAlign: 'center', backgroundColor: 'rgba(0, 0, 0, 0.05)', border: '1px solid rgba(0, 0, 0, 0.1)', borderRight: '1px solid rgba(0, 0, 0, 0.1)', fontSize: '14px' }} title="Movement">M</th>
                <th className="unit-status-header-cell" style={{ padding: '6px 8px', textAlign: 'center', backgroundColor: 'rgba(0, 0, 0, 0.05)', border: '1px solid rgba(0, 0, 0, 0.1)', fontSize: '14px' }} title="Toughness">T</th>
                <th className="unit-status-header-cell" style={{ padding: '6px 8px', textAlign: 'center', backgroundColor: 'rgba(0, 0, 0, 0.05)', border: '1px solid rgba(0, 0, 0, 0.1)', fontSize: '14px' }} title="Save Value">SV</th>
                <th className="unit-status-header-cell" style={{ padding: '6px 8px', textAlign: 'center', backgroundColor: 'rgba(0, 0, 0, 0.05)', border: '1px solid rgba(0, 0, 0, 0.1)', fontSize: '14px' }} title="Leadership">LD</th>
                <th className="unit-status-header-cell" style={{ padding: '6px 8px', textAlign: 'center', backgroundColor: 'rgba(0, 0, 0, 0.05)', border: '1px solid rgba(0, 0, 0, 0.1)', fontSize: '14px' }} title="Objective Control">OC</th>
                <th className="unit-status-header-cell" style={{ padding: '6px 8px', textAlign: 'center', backgroundColor: 'rgba(0, 0, 0, 0.05)', border: '1px solid rgba(0, 0, 0, 0.1)', fontSize: '14px' }} title="Unit Value">VAL</th>
              </tr>
            </thead>
          </table>
        )}

        {/* Units List */}
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
      </div>
    </div>
  );
});

UnitStatusTable.displayName = 'UnitStatusTable';
