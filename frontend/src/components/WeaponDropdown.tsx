import React, { useRef, useEffect } from 'react';
import type { WeaponOption } from '../types/game';
import weaponRules from '../../../config/weapon_rules.json';

interface WeaponDropdownProps {
  weapons: WeaponOption[];
  position: { x: number; y: number };
  onSelectWeapon: (index: number) => void;
  onClose: () => void;
}

export const WeaponDropdown: React.FC<WeaponDropdownProps> = ({
  weapons,
  position,
  onSelectWeapon,
  onClose,
}) => {
  const dropdownRef = useRef<HTMLDivElement>(null);
  
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        onClose();
      }
    };
    
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [onClose]);
  
  return (
    <div 
      ref={dropdownRef}
      className="weapon-dropdown"
      style={{
        position: 'absolute',
        left: `${position.x}px`,
        top: `${position.y}px`,
      }}
    >
      <table className="weapon-table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Range</th>
            <th>A</th>
            <th>BS</th>
            <th>S</th>
            <th>AP</th>
            <th>DMG</th>
          </tr>
        </thead>
        <tbody>
          {weapons.map((weaponOption) => {
            const weapon = weaponOption.weapon;
            const isDisabled = !weaponOption.canUse;
            
            return (
              <tr
                key={weaponOption.index}
                className={isDisabled ? 'disabled' : ''}
                onClick={() => {
                  console.log('🟡 DROPDOWN CLICK:', {
                    weaponName: weapon.display_name,
                    weaponIndex: weaponOption.index,
                    isDisabled
                  });
                  if (!isDisabled) {
                    console.log('🟡 CALLING onSelectWeapon with index:', weaponOption.index);
                    onSelectWeapon(weaponOption.index);
                  }
                }}
                title={isDisabled ? weaponOption.reason : undefined}
              >
                <td>
                  {weapon.display_name}
                  {weapon.WEAPON_RULES?.map(rule => (
                    <span 
                      key={rule}
                      className="rule-badge" 
                      title={weaponRules[rule as keyof typeof weaponRules]?.description || rule}
                    >
                      [{weaponRules[rule as keyof typeof weaponRules]?.name || rule}]
                    </span>
                  ))}
                </td>
                <td>{weapon.RNG ? `${weapon.RNG}"` : '-'}</td>
                <td>{weapon.NB}</td>
                <td>{weapon.ATK}+</td>
                <td>{weapon.STR}</td>
                <td>{weapon.AP}</td>
                <td>{weapon.DMG}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
};
