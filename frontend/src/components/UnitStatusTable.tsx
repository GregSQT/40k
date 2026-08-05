// frontend/src/components/UnitStatusTable.tsx
import {
  type CSSProperties,
  type Dispatch,
  memo,
  type ReactElement,
  type SetStateAction,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import unitRules from "../../../config/unit_rules.json";
import weaponRules from "../../../config/weapon_rules.json";
import type {
  DeploymentState,
  StrategicReservesPlayerSummary,
  Unit,
  UnitId,
  UnitRule,
  Weapon,
} from "../types/game";
import {
  canDropUnitIntoReserves,
  canSelectReserveUnitForIngress,
  formatStrategicReservesRatio,
  selectReserveUnits,
} from "../utils/strategicReservesUi";
import TooltipWrapper from "./TooltipWrapper";

/** Contour ORANGE du conteneur de réserves — le distingue des lignes d'unités normales. */
const RESERVES_BORDER_COLOR = "#ff8c00";

const UNIT_RULE_DESCRIPTIONS: Record<string, string> = {
  charge_after_advance: "Allows a unit to charge in the same turn it advanced.",
  adaptable_predators: "This unit can shoot and charge in a turn in which it fell back.",
  shoot_after_flee: "Allows a unit to shoot in a turn in which it fell back.",
  charge_after_flee: "Allows a unit to charge in a turn in which it fell back.",
};

const getUnitRuleTooltip = (ruleId: string): string => {
  const configDescription = unitRules[ruleId as keyof typeof unitRules]?.description;
  return configDescription ?? UNIT_RULE_DESCRIPTIONS[ruleId] ?? ruleId;
};

const getWeaponRuleDisplay = (ruleId: string): { displayName: string; tooltipText: string } => {
  const [baseRuleId, parameter] = ruleId.split(":");
  const ruleData = weaponRules[baseRuleId as keyof typeof weaponRules];
  const baseDisplayName = ruleData?.name ?? baseRuleId;
  const displayName = parameter ? `${baseDisplayName}:${parameter}` : baseDisplayName;
  const tooltipText = ruleData?.description ?? ruleId;
  return { displayName, tooltipText };
};

// Rôles d'allocation (règle 19/05) → ruleIds moteur (ROLE_TIER, shared_utils). Détermine la couleur
// du bandeau nom d'une figurine dans la vue multi-profils.
const ROLE_RULE_IDS = ["leader", "support", "sergeant", "special_weapon"] as const;
type ModelRole = (typeof ROLE_RULE_IDS)[number] | null;

function deriveModelRole(rules: UnitRule[] | undefined): ModelRole {
  if (!rules) return null;
  for (const r of rules) {
    if ((ROLE_RULE_IDS as readonly string[]).includes(r.ruleId)) {
      return r.ruleId as ModelRole;
    }
  }
  return null;
}

// Ordre d'affichage imposé des profils : Leader → Support → Sergeant → Special weapon → Base.
const ROLE_DISPLAY_ORDER: Record<string, number> = {
  leader: 0,
  support: 1,
  sergeant: 2,
  special_weapon: 3,
};
function roleDisplayRank(role: ModelRole): number {
  return role ? ROLE_DISPLAY_ORDER[role] : 4;
}

/** Suffixe de classe CSS du rôle (couleurs définies dans App.css : .unit-profile-row--<suffixe>). */
function roleClassSuffix(role: ModelRole): string {
  switch (role) {
    case "leader":
      return "leader";
    case "support":
      return "support";
    case "sergeant":
      return "sergeant";
    case "special_weapon":
      return "special";
    default:
      return "base";
  }
}

/** Profil distinct (par unit_type) d'une escouade multi-profils. ``move``/``ld`` sont hérités de
 * l'unité (le moteur ne les surcharge pas par figurine). */
interface UnitProfile {
  key: string;
  name: string;
  role: ModelRole;
  move?: number;
  t?: number;
  sv?: number;
  invul?: number;
  ld?: number;
  oc?: number;
  value?: number;
  hpMax?: number;
  rng: Weapon[];
  cc: Weapon[];
}

/** Construit un profil par unit_type distinct présent dans ``unit.models`` (ordre d'apparition).
 * Une figurine de base (sans unit_type) retombe sur les stats/armes de l'unité parente. */
function buildUnitProfiles(unit: Unit): UnitProfile[] {
  const models = unit.models ?? [];
  const byKey = new Map<string, UnitProfile>();
  const order: string[] = [];
  for (const m of models) {
    const isBase = !m.unit_type;
    const key = m.unit_type ?? "__base__";
    if (byKey.has(key)) continue;
    order.push(key);
    byKey.set(key, {
      key,
      name:
        (isBase ? unit.DISPLAY_NAME : m.DISPLAY_NAME) ??
        unit.DISPLAY_NAME ??
        unit.name ??
        unit.type ??
        `Unit ${unit.id}`,
      role: deriveModelRole(isBase ? unit.UNIT_RULES : (m.UNIT_RULES ?? unit.UNIT_RULES)),
      move: unit.MOVE,
      t: m.T ?? unit.T,
      sv: m.ARMOR_SAVE ?? unit.ARMOR_SAVE,
      invul: m.INVUL_SAVE ?? unit.INVUL_SAVE,
      ld: unit.LD,
      oc: m.OC ?? unit.OC,
      value: m.VALUE ?? unit.VALUE,
      hpMax: m.HP_MAX ?? unit.HP_MAX,
      rng: m.RNG_WEAPONS ?? unit.RNG_WEAPONS ?? [],
      cc: m.CC_WEAPONS ?? unit.CC_WEAPONS ?? [],
    });
  }
  return order
    .map((k) => byKey.get(k) as UnitProfile)
    .sort((a, b) => roleDisplayRank(a.role) - roleDisplayRank(b.role));
}

/** Clé de profil correspondant à un index de modèle (inspection). */
function profileKeyForModelIndex(unit: Unit, modelIndex: number | null): string | null {
  if (modelIndex === null) return null;
  const m = unit.models?.[modelIndex];
  if (!m) return null;
  return m.unit_type ?? "__base__";
}

const PROFILE_CELL_STYLE: CSSProperties = {
  textAlign: "center",
  padding: "2px 6px",
  fontSize: "11px",
};

// Halo brillant habituel (glow vert) — dérivé de --btn-glow / --btn-glow-soft (App.css), grossi.
export const HALO_GLOW = "0 0 0 3px #86efac, 0 0 20px 7px rgba(134, 239, 172, 0.9)";

/** Mini-table d'armes (RANGE ou MELEE) repliable, pour un profil. */
function ProfileWeaponTable({
  title,
  weapons,
  melee,
  expanded,
  onToggle,
  inchesToSubhex,
}: {
  title: string;
  weapons: Weapon[];
  melee: boolean;
  expanded: boolean;
  onToggle: () => void;
  inchesToSubhex: number;
}): ReactElement | null {
  if (weapons.length === 0) return null;
  // Mêmes valeurs que les tables d'armes existantes (single-profil) : fond de section + bouton.
  const headerBg = melee ? "rgba(200, 50, 50, 0.2)" : "rgba(45, 110, 210, 0.32)";
  const btnBg = melee ? "rgba(200, 100, 150, 0.3)" : "rgba(100, 150, 200, 0.3)";
  const btnBorder = melee ? "rgba(200, 100, 150, 0.5)" : "rgba(100, 150, 200, 0.5)";
  const btnColor = melee ? "#c86496" : "#6496c8";
  const headerTh: CSSProperties = {
    ...PROFILE_CELL_STYLE,
    color: "#aee6ff",
    fontWeight: "bold",
    backgroundColor: headerBg,
  };
  return (
    <table
      style={{
        width: "100%",
        borderCollapse: "collapse",
        marginTop: "3px",
        tableLayout: "fixed",
      }}
    >
      {/* Même colgroup 10 colonnes que la table principale → Rng aligné sous HP.
          Le nom d'arme couvre expand+ID+Name (colSpan 3) ; la dernière colonne (VAL) reste vide. */}
      <colgroup>
        <col style={{ width: "40px" }} />
        <col style={{ width: "40px" }} />
        <col style={{ width: "auto" }} />
        <col style={{ width: "70px" }} />
        <col style={{ width: "70px" }} />
        <col style={{ width: "70px" }} />
        <col style={{ width: "70px" }} />
        <col style={{ width: "70px" }} />
        <col style={{ width: "70px" }} />
        <col style={{ width: "70px" }} />
      </colgroup>
      <thead>
        <tr
          className="unit-status-row unit-status-row--section-header"
          style={{ fontWeight: "bold" }}
        >
          <th
            className="unit-status-cell"
            colSpan={3}
            style={{
              ...PROFILE_CELL_STYLE,
              // Zone d'indentation (56px) transparente à gauche du bouton, couleur ensuite.
              background: `linear-gradient(to right, transparent 56px, ${headerBg} 56px)`,
              color: "#fff",
              textAlign: "left",
              paddingLeft: "56px",
            }}
          >
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onToggle();
              }}
              style={{
                background: btnBg,
                border: `1px solid ${btnBorder}`,
                color: btnColor,
                fontSize: "12px",
                fontWeight: "bold",
                cursor: "pointer",
                padding: "1px 5px",
                minWidth: "20px",
                borderRadius: "3px",
                marginRight: "8px",
                verticalAlign: "middle",
              }}
              aria-label={expanded ? `Collapse ${title}` : `Expand ${title}`}
            >
              {expanded ? "−" : "+"}
            </button>
            <span style={{ fontSize: "11px" }}>{title}</span>
          </th>
          <th className="unit-status-cell" style={headerTh}>
            Rng
          </th>
          <th className="unit-status-cell" style={headerTh}>
            A
          </th>
          <th className="unit-status-cell" style={headerTh}>
            {melee ? "CC" : "BS"}
          </th>
          <th className="unit-status-cell" style={headerTh}>
            S
          </th>
          <th className="unit-status-cell" style={headerTh}>
            AP
          </th>
          <th className="unit-status-cell" style={headerTh}>
            DMG
          </th>
          <th className="unit-status-cell" style={PROFILE_CELL_STYLE} />
        </tr>
      </thead>
      {expanded && (
        <tbody>
          {weapons.map((weapon, idx) => {
            const rowBg = idx === 0 ? "#222" : "#2a2a2a";
            const statCell: CSSProperties = { ...PROFILE_CELL_STYLE, backgroundColor: rowBg };
            return (
              <tr
                key={`${melee ? "cc" : "rng"}-${weapon.display_name}`}
                className="unit-status-row unit-status-row--weapon"
              >
                <td
                  className="unit-status-cell"
                  colSpan={3}
                  style={{
                    ...PROFILE_CELL_STYLE,
                    textAlign: "left",
                    paddingLeft: "64px",
                    // Pas de troncature ellipsis sur le nom d'arme (comme les tables single-profil).
                    overflow: "visible",
                    textOverflow: "clip",
                    whiteSpace: "normal",
                    // Fond de ligne à partir de 56px ; le nom démarre 8px après → pas collé au bord.
                    background: `linear-gradient(to right, transparent 56px, ${rowBg} 56px)`,
                  }}
                >
                  {weapon.display_name}
                  {weapon.WEAPON_RULES?.map((ruleId) => {
                    const { displayName, tooltipText } = getWeaponRuleDisplay(ruleId);
                    return (
                      <span key={ruleId} className="rule-badge-wrapper">
                        <span className="rule-badge">{displayName}</span>
                        <span className="rule-tooltip">{tooltipText}</span>
                      </span>
                    );
                  })}
                </td>
                <td style={statCell}>
                  {!melee && weapon.RNG ? `${weapon.RNG / inchesToSubhex}"` : "/"}
                </td>
                <td style={statCell}>{weapon.NB || 0}</td>
                <td style={statCell}>{weapon.ATK ? `${weapon.ATK}+` : "-"}</td>
                <td style={statCell}>{weapon.STR || "-"}</td>
                <td style={statCell}>{weapon.AP || "-"}</td>
                <td style={statCell}>{weapon.DMG || "-"}</td>
                <td style={PROFILE_CELL_STYLE} />
              </tr>
            );
          })}
        </tbody>
      )}
    </table>
  );
}

/** Ligne d'unité pour une escouade MULTI-PROFILS : header = nom d'unité seul, puis une
 * sous-catégorie repliable par type de figurine (bandeau nom coloré selon le rôle). Le survol/clic
 * d'une figurine sur le plateau (``inspectedModelIndex``) déplie l'unité + le profil correspondant. */
function MultiProfileUnitRow({
  unit,
  profiles,
  isSelected,
  isClicked,
  onSelect,
  inspectedModelIndex,
  inchesToSubhex,
}: {
  unit: Unit;
  profiles: UnitProfile[];
  isSelected: boolean;
  isClicked: boolean;
  onSelect: (unitId: UnitId) => void;
  inspectedModelIndex: number | null;
  inchesToSubhex: number;
}): ReactElement {
  const [unitManualOpen, setUnitManualOpen] = useState(false);
  const [openProfiles, setOpenProfiles] = useState<Set<string>>(new Set());
  const [openRanged, setOpenRanged] = useState<Set<string>>(new Set());
  const [openMelee, setOpenMelee] = useState<Set<string>>(new Set());

  const inspectedProfileKey = profileKeyForModelIndex(unit, inspectedModelIndex);
  const unitName = unit.DISPLAY_NAME || unit.name || unit.type || `Unit ${unit.id}`;

  // Survol/inspection : ouvre EXCLUSIVEMENT le profil visé et REFERME le précédent survolé.
  // On SEED simplement l'état (setOpenProfiles) au lieu de forcer l'affichage → les boutons +/−
  // restent pleinement autoritaires (peuvent replier même sous inspection).
  const hoverSeedRef = useRef<string | null>(null);
  useEffect(() => {
    const key = inspectedProfileKey;
    const prev = hoverSeedRef.current;
    if (prev === key) return;
    // Survol d'une fig : déplie son profil ET ses armes tir/mêlée (exclusif : referme le précédent).
    const reseed = (s: Set<string>): Set<string> => {
      const next = new Set(s);
      if (prev !== null) next.delete(prev);
      if (key !== null) next.add(key);
      return next;
    };
    setOpenProfiles(reseed);
    setOpenRanged(reseed);
    setOpenMelee(reseed);
    if (key !== null) setUnitManualOpen(true);
    hoverSeedRef.current = key;
  }, [inspectedProfileKey]);

  // Unité sélectionnée : déplier par défaut tous les profils + leurs armes tir/mêlée (additif).
  const profileKeysSig = profiles.map((p) => p.key).join(",");
  useEffect(() => {
    if (!isSelected) return;
    const keys = profileKeysSig ? profileKeysSig.split(",") : [];
    setUnitManualOpen(true);
    setOpenProfiles(new Set(keys));
    setOpenRanged(new Set(keys));
    setOpenMelee(new Set(keys));
  }, [isSelected, profileKeysSig]);

  const unitOpen = unitManualOpen;

  // Fig survolée : son type remonte en tête de la liste des profils (même principe que l'unité
  // mono-type qui remonte en haut de la table au survol).
  const orderedProfiles =
    inspectedProfileKey !== null
      ? [
          ...profiles.filter((p) => p.key === inspectedProfileKey),
          ...profiles.filter((p) => p.key !== inspectedProfileKey),
        ]
      : profiles;

  const toggleSet = (setter: Dispatch<SetStateAction<Set<string>>>, key: string): void => {
    setter((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  };

  const numCell: CSSProperties = {
    textAlign: "center",
    padding: "4px 8px",
    backgroundColor: "#222",
    fontSize: "12px",
  };

  return (
    <div style={{ marginBottom: "2px" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", tableLayout: "fixed" }}>
        <colgroup>
          <col style={{ width: "40px" }} />
          <col style={{ width: "40px" }} />
          <col style={{ width: "auto" }} />
          <col style={{ width: "70px" }} />
          <col style={{ width: "70px" }} />
          <col style={{ width: "70px" }} />
          <col style={{ width: "70px" }} />
          <col style={{ width: "70px" }} />
          <col style={{ width: "70px" }} />
          <col style={{ width: "70px" }} />
        </colgroup>
        <tbody>
          {/* Header d'unité : nom seul (les stats varient par figurine) */}
          <tr
            className={`unit-status-row ${isClicked ? "unit-status-row--clicked" : ""}`}
            onClick={() => onSelect(unit.id)}
            style={{ cursor: "pointer" }}
          >
            <td
              className="unit-status-cell unit-status-cell--expand"
              style={{ ...numCell, textAlign: "center" }}
            >
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  setUnitManualOpen((v) => !v);
                }}
                style={{
                  background: "rgba(70, 130, 200, 0.2)",
                  border: "1px solid rgba(70, 130, 200, 0.4)",
                  color: "#4682c8",
                  fontSize: "14px",
                  fontWeight: "bold",
                  cursor: "pointer",
                  padding: "2px 6px",
                  minWidth: "24px",
                  minHeight: "24px",
                  borderRadius: "3px",
                }}
                aria-label={unitOpen ? "Collapse unit" : "Expand unit"}
              >
                {unitOpen ? "−" : "+"}
              </button>
            </td>
            <td
              className="unit-status-cell unit-status-cell--number"
              style={{ ...numCell, fontWeight: "bold", borderRight: "1px solid #333" }}
            >
              {unit.id}
            </td>
            <td
              className="unit-status-cell unit-status-cell--type"
              style={{ ...numCell, fontWeight: "bold", textAlign: "left" }}
            >
              {unitName}
            </td>
            <td className="unit-status-cell" style={numCell} />
            <td className="unit-status-cell" style={numCell} />
            <td className="unit-status-cell" style={numCell} />
            <td className="unit-status-cell" style={numCell} />
            <td className="unit-status-cell" style={numCell} />
            <td className="unit-status-cell" style={numCell} />
            <td className="unit-status-cell" style={numCell} />
          </tr>

          {/* Une ligne par type de figurine (alignée sur les colonnes), stats visibles si dépliée */}
          {unitOpen &&
            orderedProfiles.map((p) => {
              const profileOpen = openProfiles.has(p.key);
              // Couleur du rôle appliquée sur TOUTE la ligne du profil (classes CSS dans App.css).
              const cellLayout: CSSProperties = {
                textAlign: "center",
                padding: "4px 8px",
                fontSize: "12px",
              };
              // Halo brillant habituel autour de TOUTE la fiche du type inspecté (survol d'une fig).
              const isHalo = p.key === inspectedProfileKey;
              return (
                <tr key={p.key}>
                  <td colSpan={10} style={{ padding: "0 0 3px 0" }}>
                    <div
                      style={{
                        boxShadow: isHalo ? HALO_GLOW : undefined,
                        borderRadius: "3px",
                        // Le halo passe au-dessus des lignes voisines (fonds opaques).
                        position: isHalo ? "relative" : undefined,
                        zIndex: isHalo ? 5 : undefined,
                      }}
                    >
                      {/* Ligne du type : même colgroup 10 colonnes → stats alignées sur l'en-tête */}
                      <table
                        style={{
                          width: "100%",
                          borderCollapse: "collapse",
                          tableLayout: "fixed",
                        }}
                      >
                        <colgroup>
                          <col style={{ width: "40px" }} />
                          <col style={{ width: "40px" }} />
                          <col style={{ width: "auto" }} />
                          <col style={{ width: "70px" }} />
                          <col style={{ width: "70px" }} />
                          <col style={{ width: "70px" }} />
                          <col style={{ width: "70px" }} />
                          <col style={{ width: "70px" }} />
                          <col style={{ width: "70px" }} />
                          <col style={{ width: "70px" }} />
                        </colgroup>
                        <tbody>
                          <tr
                            className={`unit-status-row unit-profile-row unit-profile-row--${roleClassSuffix(p.role)}`}
                          >
                            {/* Cellule tout à gauche : pas de couleur de rôle */}
                            <td
                              className="unit-status-cell"
                              style={{ ...cellLayout, backgroundColor: "transparent" }}
                            />
                            <td
                              className="unit-status-cell"
                              style={{ ...cellLayout, padding: "4px 2px" }}
                            >
                              <button
                                type="button"
                                onClick={() => toggleSet(setOpenProfiles, p.key)}
                                style={{
                                  background: "rgba(0, 0, 0, 0.25)",
                                  border: "1px solid rgba(0, 0, 0, 0.4)",
                                  color: "inherit",
                                  fontSize: "13px",
                                  fontWeight: "bold",
                                  cursor: "pointer",
                                  padding: "0 5px",
                                  minWidth: "20px",
                                  borderRadius: "3px",
                                }}
                                aria-label={profileOpen ? "Collapse profile" : "Expand profile"}
                              >
                                {profileOpen ? "−" : "+"}
                              </button>
                            </td>
                            <td
                              className="unit-status-cell unit-status-cell--type"
                              style={{ ...cellLayout, textAlign: "left", fontWeight: "bold" }}
                            >
                              {p.name}
                            </td>
                            <td className="unit-status-cell" style={cellLayout}>
                              {profileOpen ? (p.hpMax ?? "-") : ""}
                            </td>
                            <td className="unit-status-cell" style={cellLayout}>
                              {profileOpen && p.move != null ? p.move / inchesToSubhex : ""}
                            </td>
                            <td className="unit-status-cell" style={cellLayout}>
                              {profileOpen ? (p.t ?? "-") : ""}
                            </td>
                            <td className="unit-status-cell" style={cellLayout}>
                              {profileOpen ? (p.sv ? `${p.sv}+` : "-") : ""}
                            </td>
                            <td className="unit-status-cell" style={cellLayout}>
                              {profileOpen ? (p.ld ?? "-") : ""}
                            </td>
                            <td className="unit-status-cell" style={cellLayout}>
                              {profileOpen ? (p.oc ?? "-") : ""}
                            </td>
                            <td className="unit-status-cell" style={cellLayout}>
                              {profileOpen ? (p.value ?? "-") : ""}
                            </td>
                          </tr>
                        </tbody>
                      </table>
                      {profileOpen && (p.rng.length > 0 || p.cc.length > 0) && (
                        <>
                          <ProfileWeaponTable
                            title="RANGE WEAPON(S)"
                            weapons={p.rng}
                            melee={false}
                            expanded={openRanged.has(p.key)}
                            onToggle={() => toggleSet(setOpenRanged, p.key)}
                            inchesToSubhex={inchesToSubhex}
                          />
                          <ProfileWeaponTable
                            title="MELEE WEAPON(S)"
                            weapons={p.cc}
                            melee={true}
                            expanded={openMelee.has(p.key)}
                            onToggle={() => toggleSet(setOpenMelee, p.key)}
                            inchesToSubhex={inchesToSubhex}
                          />
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
        </tbody>
      </table>
    </div>
  );
}

/**
 * 20.01/20.04 — dernière ligne du tableau d'un joueur : les escouades TENUES EN RÉSERVES.
 *
 * Public des deux côtés (« place them to one side » : les réserves sont déclarées ouvertement),
 * mais interactif seulement pour son propriétaire, et seulement quand la phase l'autorise :
 *   - phase de déploiement : cliquer le conteneur y DÉPOSE l'unité sélectionnée (20.01) ;
 *   - phase de mouvement : cliquer une escouade du conteneur demande son aire d'arrivée (20.04).
 *
 * Le ratio « 120/250 » est LU (`strategic_reserves` du moteur) ; il n'est jamais recalculé ici —
 * l'afficher autrement que le calcul qui refuse un dépôt, c'est afficher un mensonge.
 */
function StrategicReservesContainer({
  reserveUnits,
  summary,
  canDropSelectedUnit,
  onDropSelectedUnit,
  onSelectReserveUnit,
  canSelectReserveUnit,
}: {
  reserveUnits: Unit[];
  summary: StrategicReservesPlayerSummary | null;
  canDropSelectedUnit: boolean;
  onDropSelectedUnit: () => void;
  onSelectReserveUnit: (unitId: UnitId) => void;
  canSelectReserveUnit: boolean;
}): ReactElement {
  const ratio = formatStrategicReservesRatio(summary);
  return (
    <div
      data-testid="strategic-reserves-container"
      style={{
        marginTop: "4px",
        border: `2px solid ${RESERVES_BORDER_COLOR}`,
        borderRadius: "4px",
        backgroundColor: "#1b1b1b",
        padding: "4px 6px",
        boxShadow: canDropSelectedUnit ? HALO_GLOW : undefined,
      }}
    >
      {/* L'espace vide du conteneur (titre + ratio) EST la cible de dépôt : c'est un vrai bouton,
          pas un div cliquable — les escouades listées dessous en sont déjà, et imbriquer des
          boutons serait du HTML invalide. */}
      <button
        type="button"
        data-testid="strategic-reserves-drop"
        disabled={!canDropSelectedUnit}
        onClick={onDropSelectedUnit}
        style={{
          display: "flex",
          width: "100%",
          alignItems: "center",
          justifyContent: "space-between",
          gap: "8px",
          background: "transparent",
          border: "none",
          padding: 0,
          color: RESERVES_BORDER_COLOR,
          fontWeight: "bold",
          fontSize: "12px",
          cursor: canDropSelectedUnit ? "pointer" : "default",
        }}
      >
        <span>STRATEGIC RESERVES</span>
        {/* Ratio 20.01 (plafond de 50 %), LU du moteur — jamais recalculé ici. */}
        <span data-testid="strategic-reserves-ratio">{ratio}</span>
      </button>
      {reserveUnits.length > 0 && (
        <div style={{ marginTop: "3px" }}>
          {reserveUnits.map((unit) => {
            const unitName = unit.DISPLAY_NAME || unit.name || unit.type || `Unit ${unit.id}`;
            return (
              <button
                key={unit.id}
                type="button"
                data-testid={`strategic-reserves-unit-${unit.id}`}
                disabled={!canSelectReserveUnit}
                onClick={() => onSelectReserveUnit(unit.id)}
                style={{
                  display: "block",
                  width: "100%",
                  textAlign: "left",
                  background: "#222",
                  border: "1px solid #333",
                  borderRadius: "3px",
                  color: "inherit",
                  fontSize: "12px",
                  padding: "3px 6px",
                  marginBottom: "2px",
                  cursor: canSelectReserveUnit ? "pointer" : "default",
                }}
              >
                <span style={{ fontWeight: "bold", marginRight: "6px" }}>{unit.id}</span>
                {unitName}
                <span style={{ float: "right", opacity: 0.8 }}>{unit.VALUE ?? "-"} pts</span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

interface UnitStatusTableProps {
  units: Unit[];
  player: 1 | 2;
  playerTypes?: Record<string, "human" | "ai" | "bot">;
  selectedUnitId: UnitId | null;
  guidedFocusUnitId?: UnitId | null;
  clickedUnitId?: UnitId | null;
  onSelectUnit: (unitId: UnitId) => void;
  gameMode?: "pvp" | "pvp_test" | "pve" | "training" | "endless_duty";
  isReplay?: boolean;
  /** Facteur subhex du board : MOVE/portées sont stockés ×inches_to_subhex, on les reconvertit en pouces pour l'affichage. */
  inchesToSubhex?: number;
  victoryPoints?: number;
  /** Points de commandement du joueur (règle 08.02). Affichés dans le MÊME en-tête que les VP :
   *  un seul endroit à l'écran pour les deux compteurs de partie. */
  commandPoints?: number;
  onCollapseChange?: (collapsed: boolean) => void;
  /** Preview plateau : forcer cette unité et ses armes à être visibles tant que l'illustration est affichée. */
  detailPreviewUnitId?: UnitId | null;
  /** Phase courante : en "deployment" + deployment_type "active", on filtre les unités déployables. */
  phase?: string;
  /** État de déploiement : pour ne montrer que les unités encore déployables du déployeur courant. */
  deploymentState?: DeploymentState | null;
  /** Type de déploiement : le filtrage par escouade ne s'applique qu'en mode "active". */
  deploymentType?: "random" | "fixed" | "active";
  /** Inspection par-figurine (survol/clic plateau) : profil du modèle à afficher dans sa
   * ligne d'unité dépliée. modelId = ``<unitId>#<idx>`` ; idx indexe ``unit.models``. */
  inspectedModel?: { unitId: string; modelId: string } | null;
  /** 20.01 — résumé MOTEUR des réserves de ce joueur : ratio affiché + dépôts que le moteur
   * accepterait. Absent tant qu'aucune partie n'est chargée. */
  strategicReserves?: StrategicReservesPlayerSummary | null;
  /** Joueur dont c'est le tour : le retrait (20.04) n'est offert qu'à lui. */
  currentPlayer?: number;
  /** 20.01 — dépose l'unité sélectionnée en réserves (phase de déploiement uniquement). */
  onDropUnitToReserves?: (unitId: UnitId) => void;
  /** 20.04 — demande l'aire d'arrivée d'une escouade du conteneur (phase de mouvement uniquement). */
  onSelectReserveUnit?: (unitId: UnitId) => void;
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
  showUnitRules: boolean;
  /** Inspection : index du modèle (dans ``unit.models``) à afficher dans la ligne dépliée, ou null. */
  inspectedModelIndex: number | null;
  /** Preview plateau : encadrer la ligne principale + sections armes lorsque l’illustration détail est affichée. */
  isDetailPreviewHighlight?: boolean;
  /** Facteur subhex pour reconvertir MOVE/portées en pouces à l'affichage. */
  inchesToSubhex: number;
}

const UnitRow = memo<UnitRowProps>(
  ({
    unit,
    isSelected,
    isClicked,
    onSelect,
    isUnitExpanded,
    onToggleUnitExpand,
    isRangedExpanded,
    onToggleRangedExpand,
    isMeleeExpanded,
    onToggleMeleeExpand,
    showUnitRules,
    inspectedModelIndex,
    isDetailPreviewHighlight = false,
    inchesToSubhex,
  }) => {
    if (!unit.HP_MAX) {
      throw new Error(`Unit ${unit.id} missing required HP_MAX field`);
    }
    const currentHP = unit.HP_CUR;

    const rngWeapons = unit.RNG_WEAPONS || [];
    const ccWeapons = unit.CC_WEAPONS || [];

    const unitName = unit.DISPLAY_NAME || unit.name || unit.type || `Unit ${unit.id}`;
    const unitRules = unit.UNIT_RULES || [];

    // Escouade multi-profils (≥2 types de figurine distincts) : rendu dédié (header nom seul +
    // sous-catégories repliables par type, bandeau coloré selon le rôle).
    const profiles = buildUnitProfiles(unit);
    if (profiles.length >= 2) {
      return (
        <MultiProfileUnitRow
          unit={unit}
          profiles={profiles}
          isSelected={isSelected}
          isClicked={isClicked}
          onSelect={onSelect}
          inspectedModelIndex={inspectedModelIndex}
          inchesToSubhex={inchesToSubhex}
        />
      );
    }

    // Halo vert aussi bien au survol d'une fig que sur la fiche "detail preview" restée affichée.
    const showGlow = inspectedModelIndex !== null || isDetailPreviewHighlight;
    return (
      <div
        style={{
          marginBottom: "2px",
          // Halo brillant habituel quand une fig de cette unité mono-type est survolée.
          boxShadow: showGlow ? HALO_GLOW : undefined,
          borderRadius: showGlow ? "3px" : undefined,
          // Le halo doit passer AU-DESSUS des lignes voisines (sinon masqué par leurs fonds opaques).
          position: showGlow ? "relative" : undefined,
          zIndex: showGlow ? 5 : undefined,
        }}
      >
        {/* Unit Attributes Table */}
        <table style={{ width: "100%", borderCollapse: "collapse", tableLayout: "fixed" }}>
          <colgroup>
            <col style={{ width: "40px" }} />
            <col style={{ width: "40px" }} />
            <col style={{ width: "auto" }} />
            <col style={{ width: "70px" }} />
            <col style={{ width: "70px" }} />
            <col style={{ width: "70px" }} />
            <col style={{ width: "70px" }} />
            <col style={{ width: "70px" }} />
            <col style={{ width: "70px" }} />
            <col style={{ width: "70px" }} />
          </colgroup>
          <tbody>
            <tr
              className="unit-status-row"
              onClick={() => onSelect(unit.id)}
              style={{ cursor: "pointer" }}
            >
              {/* Expand/Collapse Button for Unit (colonne de gauche) */}
              <td
                className="unit-status-cell unit-status-cell--expand"
                style={{ textAlign: "center", padding: "4px 8px", backgroundColor: "#222" }}
              >
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    onToggleUnitExpand(unit.id);
                  }}
                  style={{
                    background: "rgba(70, 130, 200, 0.2)",
                    border: "1px solid rgba(70, 130, 200, 0.4)",
                    color: "#4682c8",
                    fontSize: "14px",
                    fontWeight: "bold",
                    cursor: "pointer",
                    padding: "2px 6px",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    minWidth: "24px",
                    minHeight: "24px",
                    borderRadius: "3px",
                    transition: "all 0.2s ease",
                    margin: "0 auto",
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.background = "rgba(70, 130, 200, 0.4)";
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.background = "rgba(70, 130, 200, 0.2)";
                  }}
                  aria-label={isUnitExpanded ? "Collapse unit" : "Expand unit"}
                >
                  {isUnitExpanded ? "−" : "+"}
                </button>
              </td>

              {/* ID */}
              <td
                className="unit-status-cell unit-status-cell--number"
                style={{
                  textAlign: "center",
                  fontWeight: "bold",
                  padding: "4px 8px",
                  backgroundColor: "#222",
                  borderRight: "1px solid #333",
                  fontSize: "12px",
                }}
              >
                {unit.id}
              </td>

              {/* Name */}
              <td
                className="unit-status-cell unit-status-cell--type"
                style={{
                  fontWeight: "bold",
                  textAlign: "left",
                  padding: "4px 8px",
                  backgroundColor: "#222",
                  fontSize: "12px",
                  overflow: "visible",
                }}
              >
                <div
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "6px",
                    flexWrap: "nowrap",
                    overflow: "visible",
                    maxWidth: "100%",
                  }}
                >
                  <span
                    style={{
                      display: "inline-block",
                      maxWidth: "100%",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                      verticalAlign: "middle",
                    }}
                  >
                    {unitName}
                  </span>
                  <span
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: "6px",
                      flexShrink: 0,
                      overflow: "visible",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {showUnitRules &&
                      unitRules.map((rule) => {
                        const tooltipText = getUnitRuleTooltip(rule.ruleId);
                        return (
                          <span key={`${unit.id}-${rule.ruleId}`} className="rule-badge-wrapper">
                            <span className="rule-badge">{rule.displayName}</span>
                            <span className="rule-tooltip">{tooltipText}</span>
                          </span>
                        );
                      })}
                  </span>
                </div>
              </td>

              {/* HP */}
              <td
                className="unit-status-cell unit-status-cell--hp"
                style={{
                  textAlign: "center",
                  padding: "4px 8px",
                  backgroundColor: "#222",
                  fontSize: "12px",
                }}
              >
                {currentHP}/{unit.HP_MAX}
              </td>

              {/* M (Movement) */}
              <td
                className="unit-status-cell unit-status-cell--stat"
                style={{
                  textAlign: "center",
                  padding: "4px 8px",
                  backgroundColor: "#222",
                  borderRight: "1px solid #333",
                  fontSize: "12px",
                }}
              >
                {unit.MOVE / inchesToSubhex}
              </td>

              {/* T (Toughness) */}
              <td
                className="unit-status-cell unit-status-cell--stat"
                style={{
                  textAlign: "center",
                  padding: "4px 8px",
                  backgroundColor: "#222",
                  fontSize: "12px",
                }}
              >
                {unit.T || "-"}
              </td>

              {/* SV (Save Value) */}
              <td
                className="unit-status-cell unit-status-cell--stat"
                style={{
                  textAlign: "center",
                  padding: "4px 8px",
                  backgroundColor: "#222",
                  fontSize: "12px",
                }}
              >
                {unit.ARMOR_SAVE ? `${unit.ARMOR_SAVE}+` : "-"}
              </td>

              {/* LD (Leadership) */}
              <td
                className="unit-status-cell unit-status-cell--stat"
                style={{
                  textAlign: "center",
                  padding: "4px 8px",
                  backgroundColor: "#222",
                  fontSize: "12px",
                }}
              >
                {unit.LD || "-"}
              </td>

              {/* OC (Objective Control) */}
              <td
                className="unit-status-cell unit-status-cell--stat"
                style={{
                  textAlign: "center",
                  padding: "4px 8px",
                  backgroundColor: "#222",
                  fontSize: "12px",
                }}
              >
                {unit.OC || "-"}
              </td>

              {/* VALUE */}
              <td
                className="unit-status-cell unit-status-cell--stat"
                style={{
                  textAlign: "center",
                  padding: "4px 8px",
                  backgroundColor: "#222",
                  fontSize: "12px",
                }}
              >
                {unit.VALUE || "-"}
              </td>
            </tr>
          </tbody>
        </table>

        {/* Weapons Tables - Separate and Independent */}
        {isUnitExpanded && (
          <div style={{ marginTop: "4px", marginLeft: "16px" }}>
            {/* RANGE WEAPON(S) Table */}
            {rngWeapons.length > 0 && (
              <table
                style={{
                  width: "calc(100% - 16px)",
                  borderCollapse: "collapse",
                  marginBottom: "4px",
                  tableLayout: "fixed",
                }}
              >
                <colgroup>
                  <col style={{ width: "200px" }} />
                  <col style={{ width: "48px" }} />
                  <col style={{ width: "48px" }} />
                  <col style={{ width: "48px" }} />
                  <col style={{ width: "48px" }} />
                  <col style={{ width: "48px" }} />
                  <col style={{ width: "48px" }} />
                </colgroup>
                <thead>
                  <tr
                    className="unit-status-row unit-status-row--section-header"
                    style={{
                      backgroundColor: "rgba(50, 150, 200, 0.2)",
                      fontWeight: "bold",
                      fontSize: "0.9em",
                    }}
                  >
                    <th
                      className="unit-status-cell"
                      style={{
                        backgroundColor: "rgba(50, 150, 200, 0.2)",
                        color: "#ffffff",
                        textAlign: "left",
                        padding: "4px 8px",
                      }}
                    >
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          onToggleRangedExpand(unit.id);
                        }}
                        style={{
                          background: "rgba(100, 150, 200, 0.3)",
                          border: "1px solid rgba(100, 150, 200, 0.5)",
                          color: "#6496c8",
                          fontSize: "12px",
                          fontWeight: "bold",
                          cursor: "pointer",
                          padding: "2px 5px",
                          display: "inline-flex",
                          alignItems: "center",
                          justifyContent: "center",
                          minWidth: "20px",
                          minHeight: "20px",
                          borderRadius: "3px",
                          transition: "all 0.2s ease",
                          marginRight: "8px",
                          verticalAlign: "middle",
                        }}
                        onMouseEnter={(e) => {
                          e.currentTarget.style.background = "rgba(100, 150, 200, 0.5)";
                        }}
                        onMouseLeave={(e) => {
                          e.currentTarget.style.background = "rgba(100, 150, 200, 0.3)";
                        }}
                        aria-label={
                          isRangedExpanded ? "Collapse ranged weapons" : "Expand ranged weapons"
                        }
                      >
                        {isRangedExpanded ? "−" : "+"}
                      </button>
                      <span style={{ fontSize: "11px" }}>RANGE WEAPON(S)</span>
                    </th>
                    <th
                      className="unit-status-cell"
                      style={{
                        textAlign: "center",
                        padding: "4px 8px",
                        color: "#aee6ff",
                        fontWeight: "bold",
                        fontSize: "11px",
                        backgroundColor: "rgba(50, 150, 200, 0.2)",
                      }}
                    >
                      Rng
                    </th>
                    <th
                      className="unit-status-cell"
                      style={{
                        textAlign: "center",
                        padding: "4px 8px",
                        color: "#aee6ff",
                        fontWeight: "bold",
                        fontSize: "11px",
                        backgroundColor: "rgba(50, 150, 200, 0.2)",
                      }}
                    >
                      A
                    </th>
                    <th
                      className="unit-status-cell"
                      style={{
                        textAlign: "center",
                        padding: "4px 8px",
                        color: "#aee6ff",
                        fontWeight: "bold",
                        fontSize: "11px",
                        backgroundColor: "rgba(50, 150, 200, 0.2)",
                      }}
                    >
                      BS
                    </th>
                    <th
                      className="unit-status-cell"
                      style={{
                        textAlign: "center",
                        padding: "4px 8px",
                        color: "#aee6ff",
                        fontWeight: "bold",
                        fontSize: "11px",
                        backgroundColor: "rgba(50, 150, 200, 0.2)",
                      }}
                    >
                      S
                    </th>
                    <th
                      className="unit-status-cell"
                      style={{
                        textAlign: "center",
                        padding: "4px 8px",
                        color: "#aee6ff",
                        fontWeight: "bold",
                        fontSize: "11px",
                        backgroundColor: "rgba(50, 150, 200, 0.2)",
                      }}
                    >
                      AP
                    </th>
                    <th
                      className="unit-status-cell"
                      style={{
                        textAlign: "center",
                        padding: "4px 8px",
                        color: "#aee6ff",
                        fontWeight: "bold",
                        fontSize: "11px",
                        backgroundColor: "rgba(50, 150, 200, 0.2)",
                      }}
                    >
                      DMG
                    </th>
                  </tr>
                </thead>
                {isRangedExpanded && (
                  <tbody>
                    {rngWeapons.map((weapon, idx) => (
                      <tr
                        key={`rng-${unit.id}-${weapon.display_name}`}
                        className="unit-status-row unit-status-row--weapon"
                        style={{
                          backgroundColor: idx === 0 ? "#222" : "#2a2a2a",
                        }}
                      >
                        <td
                          className="unit-status-cell unit-status-cell--type"
                          style={{
                            padding: "4px 8px",
                            textAlign: "left",
                            fontSize: "12px",
                            overflow: "visible",
                            textOverflow: "clip",
                          }}
                        >
                          {weapon.display_name}
                          {weapon.WEAPON_RULES?.map((ruleId) => {
                            const { displayName, tooltipText } = getWeaponRuleDisplay(ruleId);
                            return (
                              <span key={`${unit.id}-rng-${ruleId}`} className="rule-badge-wrapper">
                                <span className="rule-badge">{displayName}</span>
                                <span className="rule-tooltip">{tooltipText}</span>
                              </span>
                            );
                          })}
                          {idx === (unit.selectedRngWeaponIndex ?? 0) && (
                            <span
                              style={{ marginLeft: "8px", color: "#64c8ff", fontSize: "0.9em" }}
                            >
                              ●
                            </span>
                          )}
                        </td>
                        <td
                          className="unit-status-cell"
                          style={{ textAlign: "center", padding: "4px 8px", fontSize: "12px" }}
                        >
                          {weapon.RNG ? `${weapon.RNG / inchesToSubhex}"` : "/"}
                        </td>
                        <td
                          className="unit-status-cell"
                          style={{ textAlign: "center", padding: "4px 8px", fontSize: "12px" }}
                        >
                          {weapon.NB || 0}
                        </td>
                        <td
                          className="unit-status-cell"
                          style={{ textAlign: "center", padding: "4px 8px", fontSize: "12px" }}
                        >
                          {weapon.ATK ? `${weapon.ATK}+` : "-"}
                        </td>
                        <td
                          className="unit-status-cell"
                          style={{ textAlign: "center", padding: "4px 8px", fontSize: "12px" }}
                        >
                          {weapon.STR || "-"}
                        </td>
                        <td
                          className="unit-status-cell"
                          style={{
                            textAlign: "center",
                            padding: "4px 8px",
                            fontSize: "12px",
                            borderRight: "1px solid #333",
                          }}
                        >
                          {weapon.AP || "-"}
                        </td>
                        <td
                          className="unit-status-cell"
                          style={{ textAlign: "center", padding: "4px 8px", fontSize: "12px" }}
                        >
                          {weapon.DMG || "-"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                )}
              </table>
            )}

            {/* MELEE WEAPON(S) Table */}
            {ccWeapons.length > 0 && (
              <table
                style={{
                  width: "calc(100% - 16px)",
                  borderCollapse: "collapse",
                  tableLayout: "fixed",
                }}
              >
                <colgroup>
                  <col style={{ width: "200px" }} />
                  <col style={{ width: "48px" }} />
                  <col style={{ width: "48px" }} />
                  <col style={{ width: "48px" }} />
                  <col style={{ width: "48px" }} />
                  <col style={{ width: "48px" }} />
                  <col style={{ width: "48px" }} />
                </colgroup>
                <thead>
                  <tr
                    className="unit-status-row unit-status-row--section-header"
                    style={{
                      backgroundColor: "rgba(200, 50, 50, 0.2)",
                      fontWeight: "bold",
                      fontSize: "0.9em",
                    }}
                  >
                    <th
                      className="unit-status-cell"
                      style={{
                        backgroundColor: "rgba(200, 50, 50, 0.2)",
                        color: "#ffffff",
                        textAlign: "left",
                        padding: "4px 8px",
                      }}
                    >
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          onToggleMeleeExpand(unit.id);
                        }}
                        style={{
                          background: "rgba(200, 100, 150, 0.3)",
                          border: "1px solid rgba(200, 100, 150, 0.5)",
                          color: "#c86496",
                          fontSize: "12px",
                          fontWeight: "bold",
                          cursor: "pointer",
                          padding: "2px 5px",
                          display: "inline-flex",
                          alignItems: "center",
                          justifyContent: "center",
                          minWidth: "20px",
                          minHeight: "20px",
                          borderRadius: "3px",
                          transition: "all 0.2s ease",
                          marginRight: "8px",
                          verticalAlign: "middle",
                        }}
                        onMouseEnter={(e) => {
                          e.currentTarget.style.background = "rgba(200, 100, 150, 0.5)";
                        }}
                        onMouseLeave={(e) => {
                          e.currentTarget.style.background = "rgba(200, 100, 150, 0.3)";
                        }}
                        aria-label={
                          isMeleeExpanded ? "Collapse melee weapons" : "Expand melee weapons"
                        }
                      >
                        {isMeleeExpanded ? "−" : "+"}
                      </button>
                      <span style={{ fontSize: "11px" }}>MELEE WEAPON(S)</span>
                    </th>
                    <th
                      className="unit-status-cell"
                      style={{
                        textAlign: "center",
                        padding: "4px 8px",
                        color: "#aee6ff",
                        fontWeight: "bold",
                        fontSize: "11px",
                        backgroundColor: "rgba(200, 50, 50, 0.2)",
                      }}
                    >
                      Rng
                    </th>
                    <th
                      className="unit-status-cell"
                      style={{
                        textAlign: "center",
                        padding: "4px 8px",
                        color: "#aee6ff",
                        fontWeight: "bold",
                        fontSize: "11px",
                        backgroundColor: "rgba(200, 50, 50, 0.2)",
                      }}
                    >
                      A
                    </th>
                    <th
                      className="unit-status-cell"
                      style={{
                        textAlign: "center",
                        padding: "4px 8px",
                        color: "#aee6ff",
                        fontWeight: "bold",
                        fontSize: "11px",
                        backgroundColor: "rgba(200, 50, 50, 0.2)",
                      }}
                    >
                      CC
                    </th>
                    <th
                      className="unit-status-cell"
                      style={{
                        textAlign: "center",
                        padding: "4px 8px",
                        color: "#aee6ff",
                        fontWeight: "bold",
                        fontSize: "11px",
                        backgroundColor: "rgba(200, 50, 50, 0.2)",
                      }}
                    >
                      S
                    </th>
                    <th
                      className="unit-status-cell"
                      style={{
                        textAlign: "center",
                        padding: "4px 8px",
                        color: "#aee6ff",
                        fontWeight: "bold",
                        fontSize: "11px",
                        backgroundColor: "rgba(200, 50, 50, 0.2)",
                      }}
                    >
                      AP
                    </th>
                    <th
                      className="unit-status-cell"
                      style={{
                        textAlign: "center",
                        padding: "4px 8px",
                        color: "#aee6ff",
                        fontWeight: "bold",
                        fontSize: "11px",
                        backgroundColor: "rgba(200, 50, 50, 0.2)",
                      }}
                    >
                      DMG
                    </th>
                  </tr>
                </thead>
                {isMeleeExpanded && (
                  <tbody>
                    {ccWeapons.map((weapon, idx) => (
                      <tr
                        key={`cc-${unit.id}-${weapon.display_name}`}
                        className="unit-status-row unit-status-row--weapon"
                        style={{
                          backgroundColor: idx === 0 ? "#222" : "#2a2a2a",
                        }}
                      >
                        <td
                          className="unit-status-cell unit-status-cell--type"
                          style={{
                            padding: "4px 8px",
                            textAlign: "left",
                            fontSize: "12px",
                            overflow: "visible",
                            textOverflow: "clip",
                          }}
                        >
                          {weapon.display_name}
                          {weapon.WEAPON_RULES?.map((ruleId) => {
                            const { displayName, tooltipText } = getWeaponRuleDisplay(ruleId);
                            return (
                              <span key={`${unit.id}-cc-${ruleId}`} className="rule-badge-wrapper">
                                <span className="rule-badge">{displayName}</span>
                                <span className="rule-tooltip">{tooltipText}</span>
                              </span>
                            );
                          })}
                          {idx === (unit.selectedCcWeaponIndex ?? 0) && (
                            <span
                              style={{ marginLeft: "8px", color: "#ff96c8", fontSize: "0.9em" }}
                            >
                              ●
                            </span>
                          )}
                        </td>
                        <td
                          className="unit-status-cell"
                          style={{ textAlign: "center", padding: "4px 8px", fontSize: "12px" }}
                        >
                          /
                        </td>
                        <td
                          className="unit-status-cell"
                          style={{ textAlign: "center", padding: "4px 8px", fontSize: "12px" }}
                        >
                          {weapon.NB || 0}
                        </td>
                        <td
                          className="unit-status-cell"
                          style={{ textAlign: "center", padding: "4px 8px", fontSize: "12px" }}
                        >
                          {weapon.ATK ? `${weapon.ATK}+` : "-"}
                        </td>
                        <td
                          className="unit-status-cell"
                          style={{ textAlign: "center", padding: "4px 8px", fontSize: "12px" }}
                        >
                          {weapon.STR || "-"}
                        </td>
                        <td
                          className="unit-status-cell"
                          style={{
                            textAlign: "center",
                            padding: "4px 8px",
                            fontSize: "12px",
                            borderRight: "1px solid #333",
                          }}
                        >
                          {weapon.AP || "-"}
                        </td>
                        <td
                          className="unit-status-cell"
                          style={{ textAlign: "center", padding: "4px 8px", fontSize: "12px" }}
                        >
                          {weapon.DMG || "-"}
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
  }
);

UnitRow.displayName = "UnitRow";

export const UnitStatusTable = memo<UnitStatusTableProps>(
  ({
    units,
    player,
    playerTypes,
    selectedUnitId,
    guidedFocusUnitId = null,
    clickedUnitId,
    onSelectUnit,
    gameMode = "pvp",
    isReplay = false,
    inchesToSubhex = 1,
    victoryPoints,
    commandPoints,
    onCollapseChange,
    detailPreviewUnitId = null,
    inspectedModel = null,
    phase,
    strategicReserves = null,
    currentPlayer,
    onDropUnitToReserves,
    onSelectReserveUnit,
  }) => {
    // Collapse/expand state for entire table
    const [isCollapsed, setIsCollapsed] = useState(true);

    // Expanded units state (per unit expand/collapse for weapons)
    const [expandedUnits, setExpandedUnits] = useState<Set<UnitId>>(new Set());
    const [expandedRanged, setExpandedRanged] = useState<Set<UnitId>>(new Set());
    const [expandedMelee, setExpandedMelee] = useState<Set<UnitId>>(new Set());
    // Unité sélectionnée : déplier par défaut ses armes de tir + mêlée (additif, restant repliable).
    useEffect(() => {
      if (selectedUnitId == null) return;
      setExpandedUnits((prev) =>
        prev.has(selectedUnitId) ? prev : new Set(prev).add(selectedUnitId)
      );
      setExpandedRanged((prev) =>
        prev.has(selectedUnitId) ? prev : new Set(prev).add(selectedUnitId)
      );
      setExpandedMelee((prev) =>
        prev.has(selectedUnitId) ? prev : new Set(prev).add(selectedUnitId)
      );
    }, [selectedUnitId]);
    const guidedLayoutSnapshotRef = useRef<{
      isCollapsed: boolean;
      expandedUnits: Set<UnitId>;
      expandedRanged: Set<UnitId>;
      expandedMelee: Set<UnitId>;
    } | null>(null);
    const guidedAppliedRef = useRef(false);

    const toggleUnitExpand = (unitId: UnitId) => {
      setExpandedUnits((prev) => {
        const next = new Set(prev);
        const isCurrentlyExpanded = next.has(unitId);
        if (isCurrentlyExpanded) {
          next.delete(unitId);
          // Also collapse weapons when collapsing unit
          setExpandedRanged((prevRng) => {
            const nextRng = new Set(prevRng);
            nextRng.delete(unitId);
            return nextRng;
          });
          setExpandedMelee((prevMelee) => {
            const nextMelee = new Set(prevMelee);
            nextMelee.delete(unitId);
            return nextMelee;
          });
        } else {
          next.add(unitId);
          // Also expand weapons when expanding unit
          setExpandedRanged((prevRng) => {
            const nextRng = new Set(prevRng);
            nextRng.add(unitId);
            return nextRng;
          });
          setExpandedMelee((prevMelee) => {
            const nextMelee = new Set(prevMelee);
            nextMelee.add(unitId);
            return nextMelee;
          });
        }
        return next;
      });
    };

    const toggleRangedExpand = (unitId: UnitId) => {
      setExpandedRanged((prev) => {
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
      setExpandedMelee((prev) => {
        const next = new Set(prev);
        if (next.has(unitId)) {
          next.delete(unitId);
        } else {
          next.add(unitId);
        }
        return next;
      });
    };

    // Tutoriel : forcer table dépliée et unités ciblées dépliées (voir attributs Intercessor)
    // État dérivé : quand la prop est true, on affiche toujours la table dépliée (évite les soucis de timing)
    const isDetailPreviewInThisTable =
      detailPreviewUnitId !== null &&
      units.some(
        (unit) => unit.player === player && String(unit.id) === String(detailPreviewUnitId)
      );
    // Inspection : si la figurine survolée/épinglée appartient à une unité MULTI-PROFILS de cette
    // table, forcer la table dépliée pour que le profil s'affiche sans clic préalable.
    const isInspectInThisTable =
      inspectedModel != null &&
      units.some(
        (unit) =>
          unit.player === player &&
          String(unit.id) === String(inspectedModel.unitId) &&
          buildUnitProfiles(unit).length >= 2
      );
    const effectiveCollapsed =
      isDetailPreviewInThisTable || isInspectInThisTable ? false : isCollapsed;

    // 20.01 — les escouades EN RÉSERVES quittent la liste normale : elles ne sont plus des unités
    // du champ de bataille, elles vivent dans le conteneur de la dernière ligne. Les laisser aux
    // deux endroits ferait croire qu'elles sont jouables comme les autres. Le tri se fait en UN
    // seul endroit : deux prédicats miroirs (`=== true` / `!== true`) laisseraient une unité
    // apparaître deux fois ou nulle part le jour où l'un des deux bouge.
    const reserveUnits = useMemo(() => selectReserveUnits(units, player), [units, player]);

    // Filter units for this player and exclude dead units ; preview plateau : unité ciblée en tête de liste
    const playerUnits = useMemo(() => {
      const inReserves = new Set(reserveUnits);
      const filtered = units.filter(
        (unit) => unit.player === player && unit.HP_CUR > 0 && !inReserves.has(unit)
      );
      if (detailPreviewUnitId === null) {
        return filtered;
      }
      const previewIndex = filtered.findIndex((u) => String(u.id) === String(detailPreviewUnitId));
      if (previewIndex <= 0) {
        return filtered;
      }
      const previewUnit = filtered[previewIndex];
      const rest = filtered.filter((_, i) => i !== previewIndex);
      return [previewUnit, ...rest];
    }, [units, player, detailPreviewUnitId, reserveUnits]);

    useEffect(() => {
      const targetUnitInThisTable =
        guidedFocusUnitId !== null &&
        playerUnits.some((unit) => String(unit.id) === String(guidedFocusUnitId));

      if (targetUnitInThisTable) {
        if (guidedLayoutSnapshotRef.current === null) {
          guidedLayoutSnapshotRef.current = {
            isCollapsed: effectiveCollapsed,
            expandedUnits: new Set(expandedUnits),
            expandedRanged: new Set(expandedRanged),
            expandedMelee: new Set(expandedMelee),
          };
        }
        if (effectiveCollapsed) {
          setIsCollapsed(false);
          onCollapseChange?.(false);
        }
        setExpandedUnits((prev) => {
          if (prev.has(guidedFocusUnitId)) {
            return prev;
          }
          const next = new Set(prev);
          next.add(guidedFocusUnitId);
          return next;
        });
        setExpandedRanged((prev) => {
          if (prev.has(guidedFocusUnitId)) {
            return prev;
          }
          const next = new Set(prev);
          next.add(guidedFocusUnitId);
          return next;
        });
        setExpandedMelee((prev) => {
          if (prev.has(guidedFocusUnitId)) {
            return prev;
          }
          const next = new Set(prev);
          next.add(guidedFocusUnitId);
          return next;
        });
        guidedAppliedRef.current = true;
        return;
      }

      if (!guidedAppliedRef.current || guidedLayoutSnapshotRef.current === null) {
        return;
      }

      const snapshot = guidedLayoutSnapshotRef.current;
      setIsCollapsed(snapshot.isCollapsed);
      onCollapseChange?.(snapshot.isCollapsed);
      setExpandedUnits(new Set(snapshot.expandedUnits));
      setExpandedRanged(new Set(snapshot.expandedRanged));
      setExpandedMelee(new Set(snapshot.expandedMelee));
      guidedLayoutSnapshotRef.current = null;
      guidedAppliedRef.current = false;
    }, [
      guidedFocusUnitId,
      playerUnits,
      effectiveCollapsed,
      expandedUnits,
      expandedRanged,
      expandedMelee,
      onCollapseChange,
    ]);

    const getPlayerTypeLabel = (playerNumber: 1 | 2): string => {
      if (!playerTypes) {
        throw new Error(
          "UnitStatusTable requires game_state.player_types for player header labels"
        );
      }
      const runtimePlayerType = playerTypes[String(playerNumber)];
      if (runtimePlayerType === "human") {
        return `Player ${playerNumber} - Human`;
      }
      if (runtimePlayerType === "ai") {
        if (gameMode === "training" || isReplay) {
          return `Player ${playerNumber} - AI/Bot`;
        }
        return `Player ${playerNumber} - AI`;
      }
      if (runtimePlayerType === "bot") {
        return `Player ${playerNumber} - Bot`;
      }
      throw new Error(
        `Invalid player type for player ${playerNumber}: ${String(runtimePlayerType)}. ` +
          "Expected 'human', 'ai', or 'bot'."
      );
    };

    // 20.01 — une armée dont TOUT est en réserves n'a plus d'unité sur le champ de bataille mais
    // n'est pas éliminée : le conteneur doit rester affiché, sinon le joueur n'a plus aucun moyen
    // de faire arriver ses escouades.
    // Porte de dépôt (20.01) : calculée AVANT le rendu, car elle décide aussi de l'affichage du
    // conteneur quand la table est repliée.
    const canDropSelectedUnitIntoReserves =
      onDropUnitToReserves !== undefined &&
      canDropUnitIntoReserves({ phase, selectedUnitId, summary: strategicReserves });

    if (playerUnits.length === 0 && reserveUnits.length === 0) {
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
            className={`unit-status-player-header ${player === 2 ? "unit-status-player-header--red" : ""}`}
            style={{
              backgroundColor: player === 2 ? "var(--hp-bar-player2)" : "var(--hp-bar-player1)",
              padding: "4px 8px",
              textAlign: "left",
              fontWeight: "bold",
              border: "1px solid rgba(0, 0, 0, 0.2)",
              marginBottom: "4px",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <button
                  type="button"
                  onClick={() => {
                    const newCollapsed = !isCollapsed;
                    setIsCollapsed(newCollapsed);
                    onCollapseChange?.(newCollapsed);
                  }}
                  style={{
                    background: "rgba(0, 0, 0, 0.2)",
                    border: "1px solid rgba(0, 0, 0, 0.3)",
                    color: "inherit",
                    fontSize: "16px",
                    fontWeight: "bold",
                    cursor: "pointer",
                    padding: "4px 8px",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    minWidth: "24px",
                    minHeight: "24px",
                    borderRadius: "4px",
                    transition: "all 0.2s ease",
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.background = "rgba(0, 0, 0, 0.3)";
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.background = "rgba(0, 0, 0, 0.2)";
                  }}
                  aria-label={effectiveCollapsed ? "Expand table" : "Collapse table"}
                >
                  {effectiveCollapsed ? "+" : "−"}
                </button>
                <span style={{ fontSize: "16px" }}>{getPlayerTypeLabel(player)}</span>
              </div>
              {commandPoints !== undefined && (
                <span style={{ fontSize: "14px" }}>{`CP : ${commandPoints}`}</span>
              )}
              {victoryPoints !== undefined && (
                <span style={{ fontSize: "14px" }}>{`VP : ${victoryPoints}`}</span>
              )}
            </div>
          </div>

          {/* Column Headers */}
          {!effectiveCollapsed && (
            <table
              style={{
                width: "100%",
                borderCollapse: "collapse",
                marginBottom: "2px",
                tableLayout: "fixed",
              }}
            >
              <colgroup>
                <col style={{ width: "40px" }} />
                <col style={{ width: "40px" }} />
                <col style={{ width: "auto" }} />
                <col style={{ width: "70px" }} />
                <col style={{ width: "70px" }} />
                <col style={{ width: "70px" }} />
                <col style={{ width: "70px" }} />
                <col style={{ width: "70px" }} />
                <col style={{ width: "70px" }} />
                <col style={{ width: "70px" }} />
              </colgroup>
              <thead>
                <tr className="unit-status-header">
                  <th
                    className="unit-status-header-cell"
                    style={{
                      padding: "6px 8px",
                      textAlign: "center",
                      backgroundColor: "rgba(0, 0, 0, 0.05)",
                      border: "1px solid rgba(0, 0, 0, 0.1)",
                      fontSize: "14px",
                    }}
                  ></th>
                  <th
                    className="unit-status-header-cell"
                    style={{
                      padding: "6px 8px",
                      textAlign: "center",
                      backgroundColor: "rgba(0, 0, 0, 0.05)",
                      border: "1px solid rgba(0, 0, 0, 0.1)",
                      borderRight: "1px solid rgba(0, 0, 0, 0.1)",
                      fontSize: "14px",
                    }}
                  >
                    ID
                  </th>
                  <th
                    className="unit-status-header-cell"
                    style={{
                      padding: "6px 8px",
                      textAlign: "center",
                      backgroundColor: "rgba(0, 0, 0, 0.05)",
                      border: "1px solid rgba(0, 0, 0, 0.1)",
                      fontSize: "14px",
                    }}
                  >
                    Name
                  </th>
                  <th
                    className="unit-status-header-cell"
                    style={{
                      padding: "6px 8px",
                      textAlign: "center",
                      backgroundColor: "rgba(0, 0, 0, 0.05)",
                      border: "1px solid rgba(0, 0, 0, 0.1)",
                      fontSize: "14px",
                    }}
                  >
                    HP
                  </th>
                  <th
                    className="unit-status-header-cell"
                    style={{
                      padding: "6px 8px",
                      textAlign: "center",
                      backgroundColor: "rgba(0, 0, 0, 0.05)",
                      border: "1px solid rgba(0, 0, 0, 0.1)",
                      borderRight: "1px solid rgba(0, 0, 0, 0.1)",
                      fontSize: "14px",
                    }}
                  >
                    <TooltipWrapper text="Movement">M</TooltipWrapper>
                  </th>
                  <th
                    className="unit-status-header-cell"
                    style={{
                      padding: "6px 8px",
                      textAlign: "center",
                      backgroundColor: "rgba(0, 0, 0, 0.05)",
                      border: "1px solid rgba(0, 0, 0, 0.1)",
                      fontSize: "14px",
                    }}
                  >
                    <TooltipWrapper text="Toughness">T</TooltipWrapper>
                  </th>
                  <th
                    className="unit-status-header-cell"
                    style={{
                      padding: "6px 8px",
                      textAlign: "center",
                      backgroundColor: "rgba(0, 0, 0, 0.05)",
                      border: "1px solid rgba(0, 0, 0, 0.1)",
                      fontSize: "14px",
                    }}
                  >
                    <TooltipWrapper text="Save Value">SV</TooltipWrapper>
                  </th>
                  <th
                    className="unit-status-header-cell"
                    style={{
                      padding: "6px 8px",
                      textAlign: "center",
                      backgroundColor: "rgba(0, 0, 0, 0.05)",
                      border: "1px solid rgba(0, 0, 0, 0.1)",
                      fontSize: "14px",
                    }}
                  >
                    <TooltipWrapper text="Leadership">LD</TooltipWrapper>
                  </th>
                  <th
                    className="unit-status-header-cell"
                    style={{
                      padding: "6px 8px",
                      textAlign: "center",
                      backgroundColor: "rgba(0, 0, 0, 0.05)",
                      border: "1px solid rgba(0, 0, 0, 0.1)",
                      fontSize: "14px",
                    }}
                  >
                    <TooltipWrapper text="Objective Control">OC</TooltipWrapper>
                  </th>
                  <th
                    className="unit-status-header-cell"
                    style={{
                      padding: "6px 8px",
                      textAlign: "center",
                      backgroundColor: "rgba(0, 0, 0, 0.05)",
                      border: "1px solid rgba(0, 0, 0, 0.1)",
                      fontSize: "14px",
                    }}
                  >
                    <TooltipWrapper text="Unit Value">VAL</TooltipWrapper>
                  </th>
                </tr>
              </thead>
            </table>
          )}

          {/* Units List */}
          {!effectiveCollapsed &&
            playerUnits.map((unit) => {
              const isDetailPreviewUnit =
                detailPreviewUnitId !== null && String(unit.id) === String(detailPreviewUnitId);
              // Modèle inspecté sur CETTE unité : idx extrait du model_id ``<unitId>#<idx>``.
              let inspectedModelIndex: number | null = null;
              if (inspectedModel && String(inspectedModel.unitId) === String(unit.id)) {
                const parts = inspectedModel.modelId.split("#");
                const idx = parts.length === 2 ? Number(parts[1]) : NaN;
                if (Number.isInteger(idx) && idx >= 0) {
                  inspectedModelIndex = idx;
                }
              }
              return (
                <UnitRow
                  key={unit.id}
                  inspectedModelIndex={inspectedModelIndex}
                  unit={unit}
                  isSelected={selectedUnitId === unit.id}
                  isClicked={clickedUnitId === unit.id && selectedUnitId !== unit.id}
                  onSelect={onSelectUnit}
                  isUnitExpanded={isDetailPreviewUnit || expandedUnits.has(unit.id)}
                  onToggleUnitExpand={toggleUnitExpand}
                  isRangedExpanded={isDetailPreviewUnit || expandedRanged.has(unit.id)}
                  onToggleRangedExpand={toggleRangedExpand}
                  isMeleeExpanded={isDetailPreviewUnit || expandedMelee.has(unit.id)}
                  onToggleMeleeExpand={toggleMeleeExpand}
                  showUnitRules={!isDetailPreviewInThisTable || isDetailPreviewUnit}
                  isDetailPreviewHighlight={isDetailPreviewUnit}
                  inchesToSubhex={inchesToSubhex}
                />
              );
            })}

          {/* 20.01/20.04 — conteneur de réserves, DERNIÈRE ligne du tableau du joueur.
              Il survit au REPLI de la table dès qu'il porte quelque chose ou qu'un dépôt est
              possible : replier une table est un geste d'encombrement, pas un renoncement à
              jouer, et la table est repliée PAR DÉFAUT — le conteneur serait invisible au moment
              même où le joueur en a besoin (une armée entièrement en réserves n'aurait alors plus
              aucun moyen d'arriver). */}
          {(!effectiveCollapsed || reserveUnits.length > 0 || canDropSelectedUnitIntoReserves) && (
            <StrategicReservesContainer
              reserveUnits={reserveUnits}
              summary={strategicReserves}
              // Les deux portes (phase + acceptation moteur) vivent dans `strategicReservesUi`,
              // où elles sont verrouillées par test — le composant ne fait que les appliquer.
              canDropSelectedUnit={canDropSelectedUnitIntoReserves}
              onDropSelectedUnit={() => {
                if (selectedUnitId !== null) onDropUnitToReserves?.(selectedUnitId);
              }}
              canSelectReserveUnit={
                onSelectReserveUnit !== undefined &&
                canSelectReserveUnitForIngress({ phase, tablePlayer: player, currentPlayer })
              }
              onSelectReserveUnit={(unitId) => onSelectReserveUnit?.(unitId)}
            />
          )}
        </div>
      </div>
    );
  }
);

UnitStatusTable.displayName = "UnitStatusTable";
