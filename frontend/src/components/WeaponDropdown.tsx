import type React from "react";
import { useEffect, useRef, useState, useCallback } from "react";
import weaponRules from "../../../config/weapon_rules.json";
import type { WeaponOption } from "../types/game";
import TooltipWrapper from "./TooltipWrapper";

function weaponColorToCSS(color: number): string {
  return `#${color.toString(16).padStart(6, "0")}`;
}

interface WeaponDropdownProps {
  weapons: WeaponOption[];
  position: { x: number; y: number };
  onSelectWeapon: (index: number) => void;
  onClose: () => void;
  /** Flux squad : le menu reste affiché (pas de fermeture au clic dehors) jusqu'au Validate. */
  persistent?: boolean;
}

export const WeaponDropdown: React.FC<WeaponDropdownProps> = ({
  weapons,
  position,
  onSelectWeapon,
  onClose,
  persistent = false,
}) => {
  const dropdownRef = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ x: position.x, y: position.y });
  const dragOffset = useRef<{ x: number; y: number } | null>(null);

  useEffect(() => {
    if (persistent) return;
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        onClose();
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [onClose, persistent]);

  const onDragStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    dragOffset.current = { x: e.clientX - pos.x, y: e.clientY - pos.y };

    const onMouseMove = (ev: MouseEvent) => {
      if (!dragOffset.current) return;
      setPos({ x: ev.clientX - dragOffset.current.x, y: ev.clientY - dragOffset.current.y });
    };
    const onMouseUp = () => {
      dragOffset.current = null;
      document.removeEventListener("mousemove", onMouseMove);
      document.removeEventListener("mouseup", onMouseUp);
    };
    document.addEventListener("mousemove", onMouseMove);
    document.addEventListener("mouseup", onMouseUp);
  }, [pos]);

  return (
    <div
      ref={dropdownRef}
      className="weapon-dropdown"
      style={{
        position: "absolute",
        left: `${pos.x}px`,
        top: `${pos.y}px`,
      }}
    >
      <button
        type="button"
        className="weapon-dropdown-handle"
        onMouseDown={onDragStart}
      >
        ⠿ WEAPON CHOICE
      </button>
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
            // locked : profil frère d'une combi déjà assignée (une combi ne tire qu'un profil).
            const isDisabled = !weaponOption.canUse || weaponOption.locked === true;
            const disabledReason = !weaponOption.canUse ? weaponOption.reason : null;

            return (
              <tr
                key={weaponOption.index}
                className={isDisabled ? "disabled" : ""}
                onClick={() => {
                  if (!isDisabled) {
                    onSelectWeapon(weaponOption.index);
                  }
                }}
              >
                <td>
                  <TooltipWrapper text={disabledReason}>
                    {weaponOption.color != null && (
                      <span
                        style={{
                          display: "inline-block",
                          width: "10px",
                          height: "10px",
                          borderRadius: "50%",
                          backgroundColor: weaponColorToCSS(weaponOption.color),
                          marginRight: "6px",
                          flexShrink: 0,
                          opacity: isDisabled ? 0.4 : 1,
                        }}
                      />
                    )}
                    {weapon.COMBI_WEAPON && (
                      <TooltipWrapper text="Combi weapon">
                        <span className="combi-badge">C</span>
                      </TooltipWrapper>
                    )}
                    <span
                      style={
                        weaponOption.assigned
                          ? { color: "#888", opacity: 0.6 }
                          : undefined
                      }
                    >
                      {weapon.display_name}
                    </span>
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
                  </TooltipWrapper>
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
