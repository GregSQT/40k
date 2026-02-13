import type React from "react";
import { useEffect, useRef } from "react";
import weaponRules from "../../../config/weapon_rules.json";
import type { WeaponOption } from "../types/game";

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

    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [onClose]);

  return (
    <div
      ref={dropdownRef}
      className="weapon-dropdown"
      style={{
        position: "absolute",
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
                className={isDisabled ? "disabled" : ""}
                onClick={() => {
                  if (!isDisabled) {
                    onSelectWeapon(weaponOption.index);
                  }
                }}
                title={isDisabled ? weaponOption.reason : undefined}
              >
                <td>
                  {weapon.COMBI_WEAPON && (
                    <span className="combi-badge" title="Combi weapon">
                      C
                    </span>
                  )}
                  {weapon.display_name}
                  {weapon.WEAPON_RULES?.map((rule) => (
                    <span key={rule} className="rule-badge-wrapper">
                      <span className="rule-badge">
                        [{weaponRules[rule as keyof typeof weaponRules]?.name || rule}]
                      </span>
                      <span className="rule-tooltip">
                        {weaponRules[rule as keyof typeof weaponRules]?.description || rule}
                      </span>
                    </span>
                  ))}
                </td>
                <td>{weapon.RNG ? `${weapon.RNG}"` : "-"}</td>
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
