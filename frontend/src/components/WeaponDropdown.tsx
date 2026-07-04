import type React from "react";
import { Fragment, useCallback, useEffect, useRef, useState } from "react";
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
  /** Menu PERMANENT : cibles cliquées (une ligne par profil éligible). */
  openTargets?: string[];
  /** weapons_for_target par cible : profils éligibles avec m (max) et x (courant). */
  targetData?: Record<string, Array<{ code: string; weapon: WeaponOption["weapon"]; m: number; x: number }>>;
  /** Libellé d'une cible (id + type) pour la sous-ligne. */
  targetLabel?: (targetId: string) => string;
  /** Fixe le nombre de tirs (x) du profil `code` sur la cible `targetId`. */
  onSetQty?: (code: string, count: number, targetId: string) => void;
  /** Sous-groupe actif (ligne surlignée → voile jaune/vert sur le plateau). */
  activeCode?: string;
  activeTargetId?: string;
  /** Clic sur une sous-ligne → active ce sous-groupe (profil × cible). */
  onActivateSubgroup?: (code: string, targetId: string) => void;
}

/** Palette stable des sous-groupes (profil × cible) — couleur de la ligne (voile PIXI en 5c-3). */
const SUBGROUP_COLORS = [
  "#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4",
  "#42d4f4", "#f032e6", "#bfef45", "#fabed4", "#469990",
];

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
  openTargets,
  targetData,
  targetLabel,
  onSetQty,
  activeCode,
  activeTargetId,
  onActivateSubgroup,
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
      {openTargets && targetData ? (
        (() => {
          // Couleur stable par sous-groupe (profil × cible), ordre profils puis cibles.
          const subgroupColor = (code: string, tid: string): string => {
            let idx = 0;
            for (const wo of weapons) {
              const c = wo.weapon.code ?? "";
              for (const t of openTargets) {
                if (!(targetData[t] ?? []).some((e) => e.code === c)) continue;
                if (c === code && t === tid) return SUBGROUP_COLORS[idx % SUBGROUP_COLORS.length];
                idx++;
              }
            }
            return "#888";
          };
          // Profils ayant au moins 1 tir attribué (toutes cibles ouvertes confondues).
          const assignedCodes = new Set<string>();
          for (const t of openTargets)
            for (const e of targetData[t] ?? []) if (e.x > 0) assignedCodes.add(e.code);
          // Un profil combo est grisé si un profil FRÈRE (même COMBI_WEAPON) est déjà utilisé
          // (l'arme physique ne tire qu'un profil).
          const siblingBlocked = (code: string, combi?: string): boolean => {
            if (!combi || assignedCodes.has(code)) return false;
            return weapons.some(
              (wo) => wo.weapon.COMBI_WEAPON === combi && (wo.weapon.code ?? "") !== code && assignedCodes.has(wo.weapon.code ?? "")
            );
          };
          return (
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
                {weapons.map((wo) => {
                  const w = wo.weapon;
                  const code = w.code ?? "";
                  const carrier = (w as { carrier_name?: string }).carrier_name;
                  const blocked = siblingBlocked(code, w.COMBI_WEAPON);
                  const lines = openTargets
                    .map((tid) => {
                      const e = (targetData[tid] ?? []).find((x) => x.code === code);
                      return e ? { tid, m: e.m, x: e.x } : null;
                    })
                    .filter((v): v is { tid: string; m: number; x: number } => v !== null)
                    // Lignes affectables (x=0) uniquement pour la cible active ; les tirs
                    // déjà affectés (x>0) restent visibles pour toutes les cibles.
                    .filter((ln) => ln.x > 0 || ln.tid === activeTargetId);
                  return (
                    <Fragment key={code || w.display_name}>
                      <tr
                        style={{
                          backgroundColor: "rgba(20,83,45,0.55)", // vert foncé : ligne de profil
                          ...(blocked ? { opacity: 0.35 } : {}),
                        }}
                      >
                        <td>
                          {w.COMBI_WEAPON && (
                            <TooltipWrapper text="Combi weapon">
                              <span className="combi-badge">C</span>
                            </TooltipWrapper>
                          )}
                          <span>{w.display_name}</span>
                          {carrier && (
                            <span style={{ opacity: 0.6, fontSize: 11 }}> — {carrier}</span>
                          )}
                          {w.WEAPON_RULES?.map((rule) => (
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
                        <td>{w.RNG ? `${w.RNG / inchesToSubhex}"` : "-"}</td>
                        <td>{w.NB}</td>
                        <td>{w.ATK}+</td>
                        <td>{w.STR}</td>
                        <td>{w.AP}</td>
                        <td>{w.DMG}</td>
                      </tr>
                      {lines.map((ln) => {
                        return (
                        <tr
                          key={`${code}:${ln.tid}`}
                          onClick={() => onActivateSubgroup?.(code, ln.tid)}
                          // Attribuée (x>0) : grisée. Le sous-groupe actif est signalé par les
                          // voiles jaune/vert sur le plateau (pas de surbrillance dans le menu).
                          style={{ cursor: "pointer", ...(ln.x > 0 ? { opacity: 0.5 } : {}) }}
                        >
                          <td colSpan={7} style={{ paddingLeft: 18 }}>
                            <span
                              style={{
                                display: "inline-block",
                                width: 10,
                                height: 10,
                                borderRadius: "50%",
                                background: subgroupColor(code, ln.tid),
                                marginRight: 6,
                              }}
                            />
                            <span>{targetLabel ? targetLabel(ln.tid) : `#${ln.tid}`}</span>
                            <span style={{ marginLeft: 10, whiteSpace: "nowrap" }}>
                              <button
                                type="button"
                                disabled={ln.x <= 0}
                                onClick={() => onSetQty?.(code, ln.x - 1, ln.tid)}
                              >
                                −
                              </button>
                              <span style={{ margin: "0 6px", fontWeight: 700 }}>
                                {ln.x}/{ln.m}
                              </span>
                              <button
                                type="button"
                                disabled={ln.x >= ln.m}
                                onClick={() => onSetQty?.(code, ln.x + 1, ln.tid)}
                              >
                                +
                              </button>
                              <button
                                type="button"
                                style={{ marginLeft: 6 }}
                                disabled={ln.x >= ln.m}
                                onClick={() => onSetQty?.(code, ln.m, ln.tid)}
                              >
                                Max
                              </button>
                            </span>
                          </td>
                        </tr>
                        );
                      })}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          );
        })()
      ) : (
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
      )}
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
