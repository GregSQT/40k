import type React from "react";
import { useCallback, useEffect, useRef, useState } from "react";
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
  /** Affiche les boutons Cancel/Tirer en bas de la fenêtre (flux squad). */
  showActions?: boolean;
  canValidate?: boolean;
  onCancel?: () => void | Promise<void>;
  onFire?: () => void | Promise<void>;
  /** Facteur subhex du board : les portées sont stockées ×inches_to_subhex, reconverties en pouces à l'affichage. */
  inchesToSubhex?: number;
}

export const WeaponDropdown: React.FC<WeaponDropdownProps> = ({
  weapons,
  position,
  onSelectWeapon,
  onClose,
  persistent = false,
  showActions = false,
  canValidate = false,
  onCancel,
  onFire,
  inchesToSubhex = 1,
}) => {
  const dropdownRef = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ x: position.x, y: position.y });
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
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

  const onDragStart = useCallback(
    (e: React.MouseEvent) => {
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
    },
    [pos]
  );

  // Groupes combi dont un profil est déjà déclaré (cible désignée).
  const assignedCombiGroups = new Set<string>(
    weapons
      .filter((w) => w.assigned && w.weapon.COMBI_WEAPON)
      .map((w) => w.weapon.COMBI_WEAPON as string)
  );

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
      <button type="button" className="weapon-dropdown-handle" onMouseDown={onDragStart}>
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
            const isDisabled = !weaponOption.canUse;
            const disabledReason = !weaponOption.canUse ? weaponOption.reason : null;
            // Profil frère d'une combi dont un AUTRE profil est déjà déclaré : texte grisé.
            // Arme déclarée : fond vert foncé. Sinon (aucun déclaré) : affichage normal.
            const combiSiblingDeclared =
              !!weapon.COMBI_WEAPON &&
              !weaponOption.assigned &&
              assignedCombiGroups.has(weapon.COMBI_WEAPON);
            const nameStyle = combiSiblingDeclared ? { color: "#aaa", opacity: 0.75 } : undefined;

            return (
              <tr
                key={weaponOption.index}
                className={[
                  isDisabled ? "disabled" : "",
                  selectedIndex === weaponOption.index ? "selected" : "",
                ]
                  .filter(Boolean)
                  .join(" ")}
                style={
                  weaponOption.assigned ? { backgroundColor: "rgba(20,83,45,0.7)" } : undefined
                }
                onClick={() => {
                  if (!isDisabled) {
                    setSelectedIndex(weaponOption.index);
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
                    <span style={nameStyle}>{weapon.display_name}</span>
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
                <td>{weapon.RNG ? `${weapon.RNG / inchesToSubhex}"` : "-"}</td>
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
      {showActions && (
        <div
          style={{
            display: "flex",
            gap: 8,
            justifyContent: "flex-end",
            padding: "8px",
          }}
        >
          <button
            type="button"
            onClick={() => onCancel?.()}
            style={{
              border: "1px solid rgba(0,0,0,0.35)",
              borderRadius: 6,
              background: "var(--ui-gray-cancel)",
              color: "#fff",
              cursor: "pointer",
              fontSize: 13,
              fontWeight: 700,
              padding: "6px 12px",
            }}
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={!canValidate}
            onClick={() => onFire?.()}
            style={{
              border: "1px solid rgba(0,0,0,0.35)",
              borderRadius: 6,
              background: canValidate ? "var(--ui-green-validate)" : "var(--ui-green-validate-off)",
              color: canValidate ? "#fff" : "rgba(229,231,235,0.5)",
              cursor: canValidate ? "pointer" : "not-allowed",
              fontSize: 13,
              fontWeight: 700,
              padding: "6px 12px",
            }}
          >
            Shoot
          </button>
        </div>
      )}
    </div>
  );
};
