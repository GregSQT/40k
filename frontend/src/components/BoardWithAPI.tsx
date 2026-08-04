// frontend/src/components/BoardWithAPI.tsx
import type React from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useLocation } from "react-router-dom";
import leaderEvolutionConfig from "../../../config/endless_duty/leader_evolution.json";
import meleeEvolutionConfig from "../../../config/endless_duty/melee_evolution.json";
import rangeEvolutionConfig from "../../../config/endless_duty/range_evolution.json";
import endlessDutyScenarioConfig from "../../../config/scenario_endless_duty.json";
import unitRulesConfig from "../../../config/unit_rules.json";
import "../App.css";
import { clearAuthSession, getAuthSession } from "../auth/authStorage";
import {
  type ManualOrderGroup,
  type ManualOrderRequest,
  type UseEngineAPIBlinkBoardProps,
  useEngineAPI,
} from "../hooks/useEngineAPI";
import { useGameConfig } from "../hooks/useGameConfig";
import { useGameLog } from "../hooks/useGameLog";
import type { GamePhase, GameState, PlayerId, TargetPreview, Unit } from "../types";
import type { DeploymentState } from "../types/game";
import { getIconDiameterRatio } from "../utils/unitBaseDisplay";
import BoardPvp, { type BoardDisplayMode, type MeasureModeState } from "./BoardPvp";
import { ErrorBoundary } from "./ErrorBoundary";
import { GameLog } from "./GameLog";
import {
  GameLogWithIllustration,
  type IllustrationBadges,
  useUnitIllustrationPreload,
} from "./GameLogWithIllustration";
import { HelperPanel } from "./HelperPanel";
import { SettingsMenu } from "./SettingsMenu";
import SharedLayout from "./SharedLayout";
import SnapshotRewind, { type SnapshotJump } from "./SnapshotRewind";
import TooltipWrapper from "./TooltipWrapper";
import { TurnPhaseTracker } from "./TurnPhaseTracker";
import { HALO_GLOW, UnitStatusTable } from "./UnitStatusTable";

/** En-tête de colonne du roster picker (Faction / Roster / Description). */
const pickerColHeaderStyle: React.CSSProperties = {
  fontWeight: 700,
  fontSize: "12px",
  opacity: 0.85,
  marginBottom: "6px",
  paddingBottom: "3px",
  borderBottom: "1px solid rgba(255,255,255,0.25)",
  textTransform: "uppercase",
  letterSpacing: "0.5px",
};

/** "WolfGuardTerminator" → "Wolf Guard Terminator" (camelCase → mots espacés). */
function prettifyUnitType(t: string | null): string {
  if (!t) return "";
  return t
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/([A-Z]+)([A-Z][a-z])/g, "$1 $2")
    .trim();
}

/** Clé stable d'un groupe (le group_id change à chaque activation) pour mémoriser l'ordre. */
function manualOrderGroupKey(g: ManualOrderGroup): string {
  return `${g.unit_type ?? "?"}|${g.role ?? "?"}|${g.is_character ? "C" : "N"}`;
}

/**
 * Bucket de contrainte d'allocation (40k 05.03), priorité croissante :
 * 0 = non-CHARACTER blessé, 1 = non-CHARACTER sain, 2 = CHARACTER blessé, 3 = CHARACTER sain.
 * Un ordre est légal ssi les buckets sont non décroissants ; le réordonnancement par
 * drag & drop n'est autorisé qu'à l'intérieur d'un même bucket.
 */
function manualOrderBucket(g: ManualOrderGroup): number {
  return (g.is_character ? 2 : 0) + (g.has_wounded ? 0 : 1);
}

/** Vrai si la séquence respecte la contrainte de bucket (non décroissant). */
function isManualOrderLegal(groups: ManualOrderGroup[]): boolean {
  for (let i = 1; i < groups.length; i++) {
    if (manualOrderBucket(groups[i]) < manualOrderBucket(groups[i - 1])) return false;
  }
  return true;
}

/** Déplace l'élément `from` vers la position `to` (copie). */
function moveItem<T>(arr: T[], from: number, to: number): T[] {
  const next = arr.slice();
  const [moved] = next.splice(from, 1);
  next.splice(to, 0, moved);
  return next;
}

/** Préférence d'ordre mémorisée entre activations (tir/combat séparés), par clé de type. */
const manualOrderPreference: { shoot: string[]; fight: string[] } = { shoot: [], fight: [] };

/**
 * Ordre par défaut : contrainte de bucket d'abord, puis préférence mémorisée (si demandée),
 * puis group_id pour la stabilité.
 */
function defaultManualOrder(
  groups: ManualOrderGroup[],
  kind: "shoot" | "fight",
  usePreference: boolean
): ManualOrderGroup[] {
  const pref = manualOrderPreference[kind];
  const prefIndex = (g: ManualOrderGroup) => {
    const i = pref.indexOf(manualOrderGroupKey(g));
    return i < 0 ? Number.MAX_SAFE_INTEGER : i;
  };
  return [...groups].sort(
    (a, b) =>
      manualOrderBucket(a) - manualOrderBucket(b) ||
      (usePreference ? prefIndex(a) - prefIndex(b) : 0) ||
      a.group_id - b.group_id
  );
}

/**
 * Déclaration de l'ordre d'allocation des pertes (règles 40k 05.03) : le défenseur
 * ordonne les groupes (cible hétérogène / CHARACTER). Même layout que le menu d'arme
 * (panneau flottant déplaçable + table). Contraintes garanties par construction (seules
 * les lignes valides au coup suivant sont cliquables) : non-CHARACTER avant CHARACTER ;
 * groupe blessé avant sain (par classe). Le backend revalide.
 */
function ManualOrderPicker({
  request,
  onSubmit,
}: {
  request: ManualOrderRequest;
  onSubmit: (order: number[]) => void;
}) {
  // L'état est réinitialisé par remount (key sur le call-site) à chaque nouvelle requête.
  // Mortal wounds (hazard) : mêmes contraintes d'ordre que le tir (06.02 ≡ 05.03) → ordre
  // mappé sur "shoot" ; seul l'affichage change (pas d'arme, pas de save).
  const kind: "shoot" | "fight" = request.kind === "fight" ? "fight" : "shoot";
  const isMortal = request.damage_type === "mortal";
  // Ordre complet pré-rempli (contrainte + préférence mémorisée) ; réordonnable par DnD.
  const [orderedGroups, setOrderedGroups] = useState<ManualOrderGroup[]>(() =>
    defaultManualOrder(request.groups, kind, true)
  );
  const [dragIdx, setDragIdx] = useState<number | null>(null);
  const [pos, setPos] = useState({ x: 360, y: 140 });
  const dragOffset = useRef<{ x: number; y: number } | null>(null);

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

  // Cible du drop : autorisée uniquement si le réordonnancement reste légal (même bucket).
  const dropAllowed = (target: number) =>
    dragIdx !== null && isManualOrderLegal(moveItem(orderedGroups, dragIdx, target));

  const onRowDrop = (target: number) => {
    if (dragIdx === null) return;
    const next = moveItem(orderedGroups, dragIdx, target);
    if (isManualOrderLegal(next)) setOrderedGroups(next);
    setDragIdx(null);
  };

  const handleSubmit = () => {
    manualOrderPreference[kind] = orderedGroups.map(manualOrderGroupKey);
    onSubmit(orderedGroups.map((g) => g.group_id));
  };

  // Type du profil principal de la cible (1er groupe non-CHARACTER, sinon 1er groupe).
  const targetGroup = request.groups.find((g) => !g.is_character) ?? request.groups[0];
  const targetLabel = targetGroup
    ? prettifyUnitType(targetGroup.unit_type) || (targetGroup.is_character ? "CHARACTER" : "")
    : "";
  const weaponNames =
    request.weapon_names && request.weapon_names.length > 0
      ? request.weapon_names
      : [request.weapon_name || "Arme"];

  return (
    <div
      className="weapon-dropdown"
      style={{ position: "fixed", left: `${pos.x}px`, top: `${pos.y}px`, zIndex: 100000 }}
    >
      <button type="button" className="weapon-dropdown-handle" onMouseDown={onDragStart}>
        ⠿ ORDRE D'ALLOCATION — Unité {request.target_unit_id}
        {targetLabel ? ` — ${targetLabel}` : ""}
      </button>
      <div className="weapon-dropdown-subtitle">
        <div className="alloc-saves">
          {request.wounds_to_save} {isMortal ? "mortal wound" : "save"}
          {request.wounds_to_save > 1 ? "s" : ""}
          {!isMortal && (
            <span className="alloc-stats">
              {" "}
              · PA {request.weapon_ap} · Dég {request.weapon_damage}
            </span>
          )}
        </div>
        <div className="alloc-weapons">
          {isMortal ? <div>Mortal Wounds</div> : weaponNames.map((n) => <div key={n}>{n}</div>)}
        </div>
      </div>
      <table className="weapon-table">
        <thead>
          <tr>
            <th>#</th>
            <th>Unit</th>
            <th>W</th>
            {!isMortal && <th>Sv</th>}
            {!isMortal && <th>Inv</th>}
            <th>Nb</th>
            <th>Type</th>
          </tr>
        </thead>
        <tbody>
          {orderedGroups.map((g, i) => {
            const isDragging = dragIdx === i;
            const canDrop = dragIdx !== null && dragIdx !== i && dropAllowed(i);
            return (
              <tr
                key={g.group_id}
                className={["selected", isDragging ? "dragging" : "", canDrop ? "drop-target" : ""]
                  .filter(Boolean)
                  .join(" ")}
                draggable
                onDragStart={() => setDragIdx(i)}
                onDragOver={(e) => {
                  if (canDrop) e.preventDefault();
                }}
                onDrop={() => onRowDrop(i)}
                onDragEnd={() => setDragIdx(null)}
                title="Glisser pour réordonner (à l'intérieur de la même catégorie)"
              >
                <td>⠿ {i + 1}</td>
                <td>{prettifyUnitType(g.unit_type) || (g.is_character ? "CHARACTER" : "Figs")}</td>
                <td>{g.W}</td>
                {!isMortal && <td>{g.Sv}+</td>}
                {!isMortal && <td>{g.InSv < 7 ? `${g.InSv}+` : "-"}</td>}
                <td>{g.model_ids.length}</td>
                <td>
                  {g.is_character ? "CHAR " : ""}
                  {g.has_wounded ? "⚠ blessé" : ""}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <div className="weapon-dropdown-actions">
        <button
          type="button"
          style={{ backgroundColor: "#1b5e20", color: "#fff" }}
          onClick={() => setOrderedGroups(defaultManualOrder(request.groups, kind, false))}
        >
          Reset
        </button>
        <button
          type="button"
          style={{ backgroundColor: "#4caf50", color: "#fff" }}
          disabled={orderedGroups.length === 0}
          onClick={handleSubmit}
        >
          Validate
        </button>
      </div>
    </div>
  );
}

type RuleChoicePrompt = {
  trigger: "on_deploy" | "turn_start" | "player_turn_start" | "phase_start" | "activation_start";
  phase?: "command" | "move" | "shoot" | "charge" | "fight";
  player: number;
  unit_id: string;
  rule_id: string;
  display_name: string;
  usage: "or" | "unique";
  options: Array<{
    display_rule_id: string;
    technical_rule_id: string;
    label: string;
  }>;
};

type EndlessDutySlotProfiles = {
  leader: string | null;
  melee: string | null;
  range: string | null;
};

type EndlessDutyPickState = {
  package: string | null;
  melee: string | null;
  ranged: string | null;
  secondary: string | null;
  special: string | null;
};

type EndlessDutySlotPicks = {
  leader: EndlessDutyPickState | null;
  melee: EndlessDutyPickState | null;
  range: EndlessDutyPickState | null;
};

type EvolutionCatalogConfig = {
  loadouts?: Array<{
    id?: string;
    profile?: string;
    picks?: Record<string, unknown>;
  }>;
  catalog?: Record<
    string,
    {
      base?: number;
      rows?: Array<{ slot?: string; pick?: string; cost?: number; implemented?: boolean }>;
      packages?: Array<{ id?: string; cost?: number; implemented?: boolean }>;
    }
  >;
};

function getProfileOptions(config: EvolutionCatalogConfig): string[] {
  if (!config.catalog || typeof config.catalog !== "object") {
    return [];
  }
  return Object.keys(config.catalog).sort((a, b) => a.localeCompare(b));
}

type PickOption = {
  id: string;
  cost: number;
  label: string;
};

type ProfilePickMenuData = {
  baseCost: number;
  primaryPackages: PickOption[];
  primaryMelee: PickOption[];
  ranged: PickOption[];
  secondary: PickOption[];
  special: PickOption[];
};

function buildPickMenusByProfile(config: EvolutionCatalogConfig): Map<string, ProfilePickMenuData> {
  const result = new Map<string, ProfilePickMenuData>();
  const catalog = config.catalog ?? {};
  for (const [profile, profileCatalog] of Object.entries(catalog)) {
    if (!profileCatalog) {
      continue;
    }
    if (profileCatalog.base == null)
      throw new Error(`Evolution catalog profile '${profile}': missing 'base' cost`);
    const baseCost = Number(profileCatalog.base);
    if (!Array.isArray(profileCatalog.rows))
      throw new Error(`Evolution catalog profile '${profile}': missing 'rows'`);
    const rows = profileCatalog.rows;
    if (!Array.isArray(profileCatalog.packages))
      throw new Error(`Evolution catalog profile '${profile}': missing 'packages'`);
    const packages = profileCatalog.packages;
    const data: ProfilePickMenuData = {
      baseCost,
      primaryPackages: [],
      primaryMelee: [],
      ranged: [],
      secondary: [],
      special: [],
    };
    for (const pkg of packages) {
      if (pkg.implemented === false) {
        continue;
      }
      if (typeof pkg.id !== "string") {
        continue;
      }
      if (pkg.cost == null) throw new Error(`Evolution package '${pkg.id}': missing cost`);
      const cost = Number(pkg.cost);
      data.primaryPackages.push({
        id: pkg.id,
        cost,
        label: `${pkg.id} (+${cost})`,
      });
    }
    for (const row of rows) {
      if (row.implemented === false) {
        continue;
      }
      if (typeof row.slot !== "string" || typeof row.pick !== "string") {
        continue;
      }
      if (row.cost == null)
        throw new Error(`Evolution row '${row.pick}' slot '${row.slot}': missing cost`);
      const cost = Number(row.cost);
      const option: PickOption = {
        id: row.pick,
        cost,
        label: `${row.pick} (+${cost})`,
      };
      if (row.slot === "melee") {
        data.primaryMelee.push(option);
      } else if (row.slot === "ranged") {
        data.ranged.push(option);
      } else if (row.slot === "secondary") {
        data.secondary.push(option);
      } else if (row.slot === "equipment" || row.slot === "special") {
        data.special.push(option);
      }
    }
    result.set(profile, data);
  }
  return result;
}

function buildDefaultPicksByProfile(
  config: EvolutionCatalogConfig
): Map<string, EndlessDutyPickState> {
  const defaults = new Map<string, EndlessDutyPickState>();
  if (!Array.isArray(config.loadouts)) throw new Error("Evolution config missing 'loadouts' array");
  const loadouts = config.loadouts;
  for (const loadout of loadouts) {
    const profile = typeof loadout.profile === "string" ? loadout.profile : null;
    if (!profile || defaults.has(profile)) {
      continue;
    }
    const picks = loadout.picks ?? {};
    defaults.set(profile, {
      package: typeof picks.package === "string" && picks.package !== "none" ? picks.package : null,
      melee: typeof picks.melee === "string" && picks.melee !== "none" ? picks.melee : null,
      ranged: typeof picks.ranged === "string" && picks.ranged !== "none" ? picks.ranged : null,
      secondary:
        typeof picks.secondary === "string" && picks.secondary !== "none" ? picks.secondary : null,
      special:
        typeof picks.special === "string" && picks.special !== "none"
          ? picks.special
          : typeof picks.equipment === "string" && picks.equipment !== "none"
            ? picks.equipment
            : null,
    });
  }
  return defaults;
}

const RETREAT_ALERT_STORAGE_KEY = "retreatAlertEnabled";

export const BoardWithAPI: React.FC = () => {
  const authSession = getAuthSession();
  if (!authSession) {
    throw new Error("Session utilisateur introuvable dans BoardWithAPI");
  }

  const canUseAdvanceWarning = authSession.permissions.options.show_advance_warning;
  const canUseAutoWeaponSelection = authSession.permissions.options.auto_weapon_selection;

  // Étages (multi-niveaux) : niveau d'affichage courant, remonté ici (au-dessus de useEngineAPI)
  // pour que le déploiement/move à l'étage puisse lire le niveau ciblé. Le bouton d'étage vit dans
  // BoardPvp (props ci-dessous). Ref synchronisée = lecture stable dans les callbacks du hook.
  const [currentLevel, setCurrentLevel] = useState(0);
  const currentLevelRef = useRef(0);
  currentLevelRef.current = currentLevel;
  const apiProps = useEngineAPI({
    currentLevelRef,
  });
  const gameLog = useGameLog(apiProps.gameState?.currentTurn ?? 1);

  // Chargement d'un save-point / d'une partie : époque de reset pour réaligner les états frontend
  // accumulés (ghosts de figs mortes) et tronquer le Game Log au moment chargé.
  const [loadEpoch, setLoadEpoch] = useState(0);
  const applyLoadedState = useCallback((_data: { save?: { ts?: string } } | null) => {
    // Le Game Log du point/partie chargé est réhydraté par useGameLog (event gameLogHydrate émis
    // par le hook API depuis game_log_history) ; ici on ne fait que réaligner les états frontend.
    setLoadEpoch((e) => e + 1);
  }, []);
  const handleLoadSave = useCallback(
    async (
      id: string,
      mode: "view" | "resume" = "resume",
      divergence?: { fork: "fork" | "overwrite"; backup_name?: string }
    ) => {
      const data = await apiProps.saveLoad(id, mode, divergence);
      // Divergence non tranchée : aucun commit côté moteur → ne pas réaligner les états frontend.
      if ((data as { needs_decision?: boolean })?.needs_decision) return data;
      applyLoadedState(data as { save?: { ts?: string } });
      return data;
    },
    [apiProps.saveLoad, applyLoadedState]
  );
  const handleLoadParty = useCallback(
    async (
      name: string,
      mode: "view" | "resume" = "resume",
      divergence?: { fork: "fork" | "overwrite"; backup_name?: string }
    ) => {
      const data = await apiProps.loadParty(name, mode, divergence);
      if ((data as { needs_decision?: boolean })?.needs_decision) return data;
      applyLoadedState(data as { save?: { ts?: string } });
      return data;
    },
    [apiProps.loadParty, applyLoadedState]
  );

  // Game Log affiché : les events du hook (réhydratés au Load/rewind depuis game_log_history, ou
  // accumulés en live). GameLog trie lui-même par timestamp décroissant.
  const gameLogEventsFiltered = gameLog.events;

  // Desperate Escape : on mémorise l'instant d'ouverture du popup hazard pour ignorer le
  // clic-fond (qui l'annule) pendant ~400 ms. Sinon, sur un DOUBLE-clic d'activation, le 1er
  // clic ouvre le popup et le 2e tombe sur le fond et le referme aussitôt → l'utilisateur croit
  // que le popup ne se déclenche pas en double-clic.
  const hazardPopupOpenedAtRef = useRef<number>(0);
  useEffect(() => {
    if (apiProps.hazardWarningPopup) {
      hazardPopupOpenedAtRef.current = performance.now();
    }
  }, [apiProps.hazardWarningPopup]);

  // Detect game mode from URL
  const location = useLocation();
  const gameMode = location.pathname.includes("/replay")
    ? "training"
    : location.pathname === "/game" && location.search.includes("mode=endless_duty")
      ? "endless_duty"
      : location.pathname === "/game" && location.search.includes("mode=pvp_test")
        ? "pvp_test"
        : location.pathname === "/game" && location.search.includes("mode=pve_test")
          ? "pve"
          : location.pathname === "/game" && location.search.includes("mode=pve")
            ? "pve"
            : "pvp";
  // Snapshots temporels (rewind / playback par phase) — PvP / PvP test uniquement.
  const isSnapshotMode = gameMode === "pvp" || gameMode === "pvp_test";
  const [snapshotJump, setSnapshotJump] = useState<SnapshotJump | null>(null);
  const [snapshotViewActive, setSnapshotViewActive] = useState(false);
  // Popup « tu vas modifier la partie » : ouvert quand un clic board est tenté pendant l'aperçu.
  const [snapshotConfirmModify, setSnapshotConfirmModify] = useState(false);
  // Aperçu (view) actif → bloque les actions côté moteur (état affiché ≠ live).
  useEffect(() => {
    apiProps.setViewActive(snapshotViewActive);
  }, [snapshotViewActive, apiProps.setViewActive]);
  // Tentative d'action board pendant l'aperçu → ouvre le popup de confirmation (Resume).
  useEffect(() => {
    apiProps.setViewActionAttemptHandler(() => setSnapshotConfirmModify(true));
    return () => apiProps.setViewActionAttemptHandler(null);
  }, [apiProps.setViewActionAttemptHandler]);
  const [snapshotPersistEnabled, setSnapshotPersistEnabled] = useState(
    () => localStorage.getItem("snapshotPersistEnabled") === "true"
  );
  const [snapshotPersistDir, setSnapshotPersistDir] = useState(
    () => localStorage.getItem("snapshotPersistDir") ?? "logs"
  );
  // Le répertoire doit être choisi avant toute save (Save bloqué tant que false).
  const [saveDirSelected, setSaveDirSelected] = useState(
    () => localStorage.getItem("saveDirSelected") === "true"
  );
  // Popup au lancement d'une partie PvP sans répertoire configuré : invite à en choisir un pour que
  // l'enregistrement/replay démarre dès le game_start (sinon rien n'est enregistré).
  const [launchDirPromptOpen, setLaunchDirPromptOpen] = useState(false);
  const isAiMode = (() => {
    const playerTypes = apiProps.gameState?.player_types;
    if (!playerTypes) {
      return false;
    }
    // AI orchestration: PvE (P2 contrôlé par IA).
    if (gameMode !== "pve" && gameMode !== "endless_duty") {
      return false;
    }
    return Object.values(playerTypes).some((playerType) => playerType === "ai");
  })();
  const victoryPoints = apiProps.gameState?.victory_points;
  const commandPoints = apiProps.gameState?.command_points;
  const objectivesOverride = (() => {
    const objectives = apiProps.gameState?.objectives as
      | Array<{ name: string; hexes: Array<{ col: number; row: number } | [number, number]> }>
      | undefined;
    if (!objectives) {
      return undefined;
    }
    return objectives.map((objective) => {
      if (!objective?.name) {
        throw new Error("Objective missing required name field");
      }
      if (!objective.hexes) {
        throw new Error(`Objective ${objective.name} missing required hexes`);
      }
      const normalizedHexes = objective.hexes.map((hex) => {
        if (Array.isArray(hex)) {
          if (hex.length !== 2) {
            throw new Error(
              `Objective ${objective.name} has invalid hex tuple: ${JSON.stringify(hex)}`
            );
          }
          return { col: hex[0], row: hex[1] };
        }
        if (typeof hex === "object" && hex !== null && "col" in hex && "row" in hex) {
          return { col: (hex as { col: number }).col, row: (hex as { row: number }).row };
        }
        throw new Error(
          `Objective ${objective.name} has invalid hex format: ${JSON.stringify(hex)}`
        );
      });
      return {
        name: objective.name,
        hexes: normalizedHexes,
      };
    });
  })();

  // Get board configuration for line of sight calculations
  const { gameConfig, boardConfig } = useGameConfig();
  // MOVE/portées sont stockés ×inches_to_subhex par le moteur : facteur pour reconvertir en pouces à l'affichage.
  const inchesToSubhex =
    (boardConfig as unknown as { inches_to_subhex?: number } | null)?.inches_to_subhex ?? 1;

  // Track clicked (but not selected) units for blue highlighting
  const [clickedUnitId, setClickedUnitId] = useState<number | null>(null);
  /** Inspection par-figurine (UnitStatusTable) : profil du modèle survolé / épinglé sur le plateau.
   * ``hover`` = transitoire (survol figurine, toutes phases), ``pinned`` = persistant (clic en mode idle).
   * Effectif affiché = hover ?? pinned. modelId = ``<unitId>#<idx>`` émis par UnitRenderer. */
  const [hoverInspectModel, setHoverInspectModel] = useState<{
    unitId: string;
    modelId: string;
  } | null>(null);
  const [pinnedInspectModel, setPinnedInspectModel] = useState<{
    unitId: string;
    modelId: string;
  } | null>(null);
  useEffect(() => {
    const onInspect = (e: Event): void => {
      const detail = (e as CustomEvent<{ unitId: unknown; modelId: unknown; kind: string }>).detail;
      if (!detail || typeof detail.modelId !== "string") return;
      const entry = { unitId: String(detail.unitId), modelId: detail.modelId };
      if (detail.kind === "hover") {
        setHoverInspectModel(entry);
      } else if (detail.kind === "hoverEnd") {
        setHoverInspectModel((prev) => (prev && prev.modelId === entry.modelId ? null : prev));
      } else if (detail.kind === "click") {
        setPinnedInspectModel((prev) => (prev && prev.modelId === entry.modelId ? null : entry));
      }
    };
    window.addEventListener("boardModelInspect", onInspect);
    return () => window.removeEventListener("boardModelInspect", onInspect);
  }, []);
  const effectiveInspectModel = hoverInspectModel ?? pinnedInspectModel;
  /** Message du bouton « Check pile-in » : raison du blocage de la validation (null = masqué). */
  const [pileInCheckMsg, setPileInCheckMsg] = useState<string | null>(null);
  const [chargeCheckMsg, setChargeCheckMsg] = useState<string | null>(null);
  /** TEST : override manuel de la distance de charge (remplace le jet 2D6). "" = jet normal. */
  const [chargeRollOverride, setChargeRollOverride] = useState<string>(
    () => localStorage.getItem("chargeRollOverride") ?? ""
  );
  const [illustrationPreviewUnitId, setIllustrationPreviewUnitId] = useState<Unit["id"] | null>(
    null
  );
  // Unité "épinglée" via clic sur une unité non-activable : affiche durablement son illustration + logos
  const [displaySelectedUnitId, setDisplaySelectedUnitId] = useState<Unit["id"] | null>(null);
  // Track UnitStatusTable collapse states
  const [, setPlayer1Collapsed] = useState(false);
  const [, setPlayer2Collapsed] = useState(false);
  const [deploymentRosterCollapsed, setDeploymentRosterCollapsed] = useState<
    Record<PlayerId, boolean>
  >({
    1: false,
    2: false,
  });
  // À chaque changement de déployeur courant : déplier le roster actif, replier l'autre.
  // Pattern « previous value » (React) — réinitialise pendant le rendu, sans effet ni double rendu.
  // Le toggle manuel reste prioritaire jusqu'au prochain changement de déployeur.
  const [lastDeployer, setLastDeployer] = useState<PlayerId | null>(null);
  const currentDeployerForCollapse =
    apiProps.gameState?.phase === "deployment" &&
    apiProps.gameState?.deployment_type === "active" &&
    apiProps.gameState?.deployment_state
      ? (Number(apiProps.gameState.deployment_state.current_deployer) as PlayerId)
      : null;
  if (currentDeployerForCollapse !== lastDeployer) {
    setLastDeployer(currentDeployerForCollapse);
    if (currentDeployerForCollapse !== null) {
      setDeploymentRosterCollapsed({
        1: currentDeployerForCollapse !== 1,
        2: currentDeployerForCollapse !== 2,
      });
    }
  }
  const [deploymentTooltip, setDeploymentTooltip] = useState<{
    visible: boolean;
    text: string;
    x: number;
    y: number;
  } | null>(null);
  const [rosterPickerPlayer, setRosterPickerPlayer] = useState<PlayerId | null>(null);
  const [rosterPickerArmies, setRosterPickerArmies] = useState<
    Array<{
      file: string;
      name: string;
      display_name: string;
      faction: string;
      faction_display_name: string;
      description: string;
    }>
  >([]);
  const [rosterPickerSelectedFaction, setRosterPickerSelectedFaction] = useState<string>("");
  const [rosterPickerHoveredDescription, setRosterPickerHoveredDescription] = useState<string>("");
  const [rosterPickerLoading, setRosterPickerLoading] = useState(false);
  const [rosterPickerError, setRosterPickerError] = useState<string | null>(null);
  const [ruleChoiceHoveredDescription, setRuleChoiceHoveredDescription] = useState<string>("");
  const [ruleChoiceFocusedUnitId, setRuleChoiceFocusedUnitId] = useState<string | null>(null);
  const [ruleChoicePopupPosition, setRuleChoicePopupPosition] = useState({ x: 140, y: 120 });
  const [isDraggingRuleChoicePopup, setIsDraggingRuleChoicePopup] = useState(false);
  const ruleChoiceDragOffsetRef = useRef({ x: 0, y: 0 });
  const [rosterPickerPosition, setRosterPickerPosition] = useState({ x: 140, y: 80 });
  const [isDraggingRosterPicker, setIsDraggingRosterPicker] = useState(false);
  const rosterPickerDragOffsetRef = useRef({ x: 0, y: 0 });
  const [showGameOverPopup, setShowGameOverPopup] = useState(false);
  const [isEndlessDutyModalOpen, setIsEndlessDutyModalOpen] = useState(false);
  const [endlessDutyFormError, setEndlessDutyFormError] = useState<string | null>(null);
  const [isSubmittingEndlessDuty, setIsSubmittingEndlessDuty] = useState(false);
  const [endlessDutyDraft, setEndlessDutyDraft] = useState<EndlessDutySlotProfiles>({
    leader: null,
    melee: null,
    range: null,
  });
  const [endlessDutyDraftPicks, setEndlessDutyDraftPicks] = useState<EndlessDutySlotPicks>({
    leader: null,
    melee: null,
    range: null,
  });
  const isRosterSetupMode = gameMode === "pvp_test" || gameMode === "pvp" || gameMode === "pve";
  const [testDeploymentStarted, setTestDeploymentStarted] = useState(!isRosterSetupMode);

  const endlessDutyProfileOptions = useMemo(
    () => ({
      leader: getProfileOptions(leaderEvolutionConfig as EvolutionCatalogConfig),
      melee: getProfileOptions(meleeEvolutionConfig as EvolutionCatalogConfig),
      range: getProfileOptions(rangeEvolutionConfig as EvolutionCatalogConfig),
    }),
    []
  );

  const endlessDutyUnlockRules = useMemo(() => {
    const endlessCfg = (
      endlessDutyScenarioConfig as { endless_duty?: { wave_unlock_rules?: Record<string, number> } }
    ).endless_duty;
    if (!endlessCfg?.wave_unlock_rules)
      throw new Error("endless_duty scenario missing wave_unlock_rules");
    const waveUnlockRules = endlessCfg.wave_unlock_rules;
    if (waveUnlockRules.leader == null) throw new Error("wave_unlock_rules missing 'leader'");
    if (waveUnlockRules.melee == null) throw new Error("wave_unlock_rules missing 'melee'");
    if (waveUnlockRules.range == null) throw new Error("wave_unlock_rules missing 'range'");
    return {
      leader: Number(waveUnlockRules.leader),
      melee: Number(waveUnlockRules.melee),
      range: Number(waveUnlockRules.range),
    };
  }, []);
  const endlessDutyPickMenus = useMemo(
    () => ({
      leader: buildPickMenusByProfile(leaderEvolutionConfig as EvolutionCatalogConfig),
      melee: buildPickMenusByProfile(meleeEvolutionConfig as EvolutionCatalogConfig),
      range: buildPickMenusByProfile(rangeEvolutionConfig as EvolutionCatalogConfig),
    }),
    []
  );
  const endlessDutyDefaultPicks = useMemo(
    () => ({
      leader: buildDefaultPicksByProfile(leaderEvolutionConfig as EvolutionCatalogConfig),
      melee: buildDefaultPicksByProfile(meleeEvolutionConfig as EvolutionCatalogConfig),
      range: buildDefaultPicksByProfile(rangeEvolutionConfig as EvolutionCatalogConfig),
    }),
    []
  );
  const getDefaultPicksForProfile = useCallback(
    (slot: keyof EndlessDutySlotProfiles, profile: string | null): EndlessDutyPickState | null => {
      if (!profile) {
        return null;
      }
      const defaults = endlessDutyDefaultPicks[slot].get(profile);
      return defaults ? { ...defaults } : null;
    },
    [endlessDutyDefaultPicks]
  );

  useEffect(() => {
    if (gameMode !== "endless_duty") {
      setIsEndlessDutyModalOpen(false);
      setEndlessDutyFormError(null);
      return;
    }
    if (!apiProps.endlessDutyState?.inter_wave_pending) {
      setIsEndlessDutyModalOpen(false);
      setEndlessDutyFormError(null);
      return;
    }
    const slotProfiles = apiProps.endlessDutyState.slot_profiles;
    const slotPicks = apiProps.endlessDutyState.slot_picks;
    const resolvedPicks: EndlessDutySlotPicks = {
      leader:
        slotProfiles.leader == null
          ? null
          : ((slotPicks?.leader as EndlessDutyPickState | null) ??
            getDefaultPicksForProfile("leader", slotProfiles.leader)),
      melee:
        slotProfiles.melee == null
          ? null
          : ((slotPicks?.melee as EndlessDutyPickState | null) ??
            getDefaultPicksForProfile("melee", slotProfiles.melee)),
      range:
        slotProfiles.range == null
          ? null
          : ((slotPicks?.range as EndlessDutyPickState | null) ??
            getDefaultPicksForProfile("range", slotProfiles.range)),
    };
    setEndlessDutyDraft({
      leader: slotProfiles.leader ?? null,
      melee: slotProfiles.melee ?? null,
      range: slotProfiles.range ?? null,
    });
    setEndlessDutyDraftPicks(resolvedPicks);
    setIsEndlessDutyModalOpen(true);
    setEndlessDutyFormError(null);
  }, [gameMode, apiProps.endlessDutyState, getDefaultPicksForProfile]);

  useEffect(() => {
    if (gameMode !== "endless_duty") {
      return;
    }
    if (!apiProps.fetchEndlessDutyStatus) {
      return;
    }
    void apiProps.fetchEndlessDutyStatus().catch(() => {
      // The regular game loop will refresh state on next action.
    });
  }, [gameMode, apiProps.fetchEndlessDutyStatus]);

  const handleEndlessDutyDraftChange = useCallback(
    (slot: keyof EndlessDutySlotProfiles, profile: string | null) => {
      setEndlessDutyDraft((prev) => ({ ...prev, [slot]: profile }));
      setEndlessDutyDraftPicks((prev) => {
        if (profile == null) {
          return { ...prev, [slot]: null };
        }
        return { ...prev, [slot]: getDefaultPicksForProfile(slot, profile) };
      });
      setEndlessDutyFormError(null);
    },
    [getDefaultPicksForProfile]
  );
  const handleEndlessDutyPickChange = useCallback(
    (
      slot: keyof EndlessDutySlotProfiles,
      pickKey: keyof EndlessDutyPickState,
      pickValue: string | null
    ) => {
      setEndlessDutyDraftPicks((prev) => {
        const current = prev[slot];
        if (!current) {
          return prev;
        }
        return {
          ...prev,
          [slot]: { ...current, [pickKey]: pickValue },
        };
      });
      setEndlessDutyFormError(null);
    },
    []
  );

  const handleEndlessDutyCommit = useCallback(async () => {
    if (gameMode !== "endless_duty") {
      return;
    }
    setIsSubmittingEndlessDuty(true);
    setEndlessDutyFormError(null);
    try {
      await apiProps.commitEndlessDuty(endlessDutyDraft, endlessDutyDraftPicks);
      setIsEndlessDutyModalOpen(false);
    } catch (error) {
      setEndlessDutyFormError(
        error instanceof Error ? error.message : "Commit requisition impossible"
      );
    } finally {
      setIsSubmittingEndlessDuty(false);
    }
  }, [gameMode, apiProps.commitEndlessDuty, endlessDutyDraft, endlessDutyDraftPicks]);

  const closeRosterPicker = () => {
    setRosterPickerPlayer(null);
    setRosterPickerSelectedFaction("");
    setRosterPickerHoveredDescription("");
    setRosterPickerError(null);
  };

  const openRosterPicker = async (player: PlayerId) => {
    if (!apiProps.listArmies) {
      throw new Error("listArmies API is not available");
    }
    setRosterPickerPlayer(player);
    setRosterPickerLoading(true);
    setRosterPickerError(null);
    try {
      const armies = await apiProps.listArmies();
      setRosterPickerArmies(armies);
      const availableFactions = Array.from(new Set(armies.map((army) => army.faction))).sort();
      if (availableFactions.length === 0) throw new Error("No factions available in army list");
      setRosterPickerSelectedFaction(availableFactions[0]);
    } catch (err) {
      setRosterPickerError(err instanceof Error ? err.message : "Failed to load armies");
    } finally {
      setRosterPickerLoading(false);
    }
  };

  const rosterPickerFactions = useMemo(() => {
    return Array.from(new Set(rosterPickerArmies.map((army) => army.faction))).sort();
  }, [rosterPickerArmies]);

  const rosterPickerFactionDisplayNameById = useMemo(() => {
    const labels: Record<string, string> = {};
    for (const army of rosterPickerArmies) {
      if (labels[army.faction] && labels[army.faction] !== army.faction_display_name) {
        throw new Error(
          `Conflicting faction_display_name for faction '${army.faction}': ` +
            `'${labels[army.faction]}' vs '${army.faction_display_name}'`
        );
      }
      labels[army.faction] = army.faction_display_name;
    }
    return labels;
  }, [rosterPickerArmies]);

  const effectiveRosterPickerFaction = useMemo(() => {
    if (rosterPickerSelectedFaction && rosterPickerFactions.includes(rosterPickerSelectedFaction)) {
      return rosterPickerSelectedFaction;
    }
    return rosterPickerFactions[0] ?? "";
  }, [rosterPickerSelectedFaction, rosterPickerFactions]);

  const filteredRosterPickerArmies = useMemo(() => {
    if (!effectiveRosterPickerFaction) {
      return rosterPickerArmies;
    }
    return rosterPickerArmies.filter((army) => army.faction === effectiveRosterPickerFaction);
  }, [rosterPickerArmies, effectiveRosterPickerFaction]);

  const handleSelectRoster = async (armyFile: string) => {
    if (!apiProps.changeRoster) {
      throw new Error("changeRoster API is not available");
    }
    if (rosterPickerPlayer === null) {
      throw new Error("No roster picker player selected");
    }
    try {
      const targetPlayer = isRosterSetupMode ? rosterPickerPlayer : undefined;
      await apiProps.changeRoster(armyFile, targetPlayer);
      closeRosterPicker();
    } catch (err) {
      setRosterPickerError(err instanceof Error ? err.message : "Failed to change roster");
    }
  };

  const isGameOver = apiProps.gameState?.game_over === true;
  const activeRuleChoicePrompt = (apiProps.ruleChoicePrompt as RuleChoicePrompt | null) ?? null;
  const pendingRuleChoiceQueue = (
    (apiProps.gameState as (GameState & { pending_rule_choice_queue?: RuleChoicePrompt[] }) | null)
      ?.pending_rule_choice_queue ?? []
  ).filter((entry): entry is RuleChoicePrompt => {
    return (
      typeof entry?.unit_id === "string" &&
      typeof entry?.display_name === "string" &&
      Array.isArray(entry?.options)
    );
  });
  const ruleChoicePrompts = (() => {
    const map = new Map<string, RuleChoicePrompt>();
    if (activeRuleChoicePrompt) {
      map.set(
        `${activeRuleChoicePrompt.unit_id}:${activeRuleChoicePrompt.rule_id}`,
        activeRuleChoicePrompt
      );
    }
    for (const queueEntry of pendingRuleChoiceQueue) {
      map.set(`${queueEntry.unit_id}:${queueEntry.rule_id}`, queueEntry);
    }
    return Array.from(map.values());
  })();
  const focusedRuleChoicePrompt =
    (ruleChoiceFocusedUnitId
      ? ruleChoicePrompts.find((prompt) => prompt.unit_id === ruleChoiceFocusedUnitId)
      : null) ?? activeRuleChoicePrompt;
  const ruleDescriptionById = useMemo(() => {
    const rawConfig = unitRulesConfig as Record<string, unknown>;
    const descriptions: Record<string, string> = {};
    for (const [entryKey, entryValue] of Object.entries(rawConfig)) {
      if (typeof entryValue !== "object" || entryValue === null) {
        throw new Error(`Invalid unit_rules.json entry '${entryKey}': expected an object`);
      }
      const record = entryValue as Record<string, unknown>;
      const id = record.id;
      const description = record.description;
      if (typeof id !== "string" || id.trim() === "") {
        throw new Error(`Invalid unit_rules.json entry '${entryKey}': missing non-empty 'id'`);
      }
      if (typeof description !== "string" || description.trim() === "") {
        throw new Error(
          `Invalid unit_rules.json entry '${entryKey}': missing non-empty 'description'`
        );
      }
      descriptions[id] = description;
    }
    return descriptions;
  }, []);
  const getRuleDescription = (ruleId: string): string => {
    const description = ruleDescriptionById[ruleId];
    if (typeof description !== "string" || description.trim() === "") {
      throw new Error(`Missing description for rule id '${ruleId}' in config/unit_rules.json`);
    }
    return description;
  };

  useEffect(() => {
    if (!activeRuleChoicePrompt) {
      setRuleChoiceFocusedUnitId(null);
      setRuleChoiceHoveredDescription("");
      return;
    }
    setRuleChoiceFocusedUnitId(activeRuleChoicePrompt.unit_id);
  }, [activeRuleChoicePrompt]);

  useEffect(() => {
    if (!isDraggingRuleChoicePopup) {
      return;
    }
    const onMouseMove = (event: MouseEvent) => {
      setRuleChoicePopupPosition({
        x: event.clientX - ruleChoiceDragOffsetRef.current.x,
        y: event.clientY - ruleChoiceDragOffsetRef.current.y,
      });
    };
    const onMouseUp = () => {
      setIsDraggingRuleChoicePopup(false);
    };
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
    return () => {
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
    };
  }, [isDraggingRuleChoicePopup]);

  useEffect(() => {
    if (!isDraggingRosterPicker) {
      return;
    }
    const onMouseMove = (event: MouseEvent) => {
      setRosterPickerPosition({
        x: event.clientX - rosterPickerDragOffsetRef.current.x,
        y: event.clientY - rosterPickerDragOffsetRef.current.y,
      });
    };
    const onMouseUp = () => {
      setIsDraggingRosterPicker(false);
    };
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
    return () => {
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
    };
  }, [isDraggingRosterPicker]);

  useEffect(() => {
    if (isGameOver) {
      setShowGameOverPopup(true);
    }
  }, [isGameOver]);

  useEffect(() => {
    const isActiveSetupDeployment =
      isRosterSetupMode &&
      apiProps.gameState?.phase === "deployment" &&
      apiProps.gameState?.deployment_type === "active";
    if (isActiveSetupDeployment) {
      setTestDeploymentStarted(false);
    }
  }, [isRosterSetupMode, apiProps.gameState?.phase, apiProps.gameState?.deployment_type]);

  const getVictoryPointsForPlayer = (player: 1 | 2): number | undefined => {
    if (!apiProps.gameState) {
      return undefined;
    }
    if (!victoryPoints) {
      throw new Error("victory_points missing from game_state");
    }
    const numericValue = victoryPoints[player];
    if (numericValue !== undefined) {
      return numericValue;
    }
    const stringValue = victoryPoints[String(player)];
    if (stringValue === undefined) {
      throw new Error(`victory_points missing for player ${player}`);
    }
    return stringValue;
  };

  // Jumeau EXACT de `getVictoryPointsForPlayer` : même compteur de partie, même sérialisation
  // (JSON n'a pas de clé entière — l'API normalise, d'où la double lecture), même refus de
  // repli sur 0. Un `?? 0` afficherait « 0 CP » pour un état incomplet, indiscernable du vrai 0.
  const getCommandPointsForPlayer = (player: 1 | 2): number | undefined => {
    if (!apiProps.gameState) {
      return undefined;
    }
    if (!commandPoints) {
      throw new Error("command_points missing from game_state");
    }
    const numericValue = commandPoints[player];
    if (numericValue !== undefined) {
      return numericValue;
    }
    const stringValue = commandPoints[String(player)];
    if (stringValue === undefined) {
      throw new Error(`command_points missing for player ${player}`);
    }
    return stringValue;
  };

  // Settings menu state
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const handleOpenSettings = () => setIsSettingsOpen(true);

  const [measureMode, setMeasureMode] = useState<MeasureModeState>({ kind: "off" });
  const handleToggleMeasureMode = useCallback(() => {
    setMeasureMode((prev) => (prev.kind === "off" ? { kind: "armed" } : { kind: "off" }));
  }, []);
  const handleMeasureHexCommit = useCallback((col: number, row: number) => {
    setMeasureMode((prev) => {
      if (prev.kind === "armed") {
        return { kind: "measuring", originCol: col, originRow: row, junctions: [] };
      }
      if (prev.kind === "measuring") {
        return { kind: "armed" };
      }
      return prev;
    });
  }, []);
  const handleMeasureJunctionCommit = useCallback((col: number, row: number) => {
    setMeasureMode((prev) => {
      if (prev.kind !== "measuring") return prev;
      return { ...prev, junctions: [...prev.junctions, { col, row }] };
    });
  }, []);
  const measureModeActive = measureMode.kind !== "off";
  const [hideIndicators, setHideIndicators] = useState(false);
  const handleToggleHideIndicators = useCallback(() => setHideIndicators((v) => !v), []);
  /** Panneau d'aide contextuelle au-dessus du tracker de phase (bouton « ? »). */
  const [showHelper, setShowHelper] = useState(false);
  const handleToggleHelper = useCallback(() => setShowHelper((v) => !v), []);

  const [showReplay, setShowReplay] = useState(true);
  const handleToggleReplay = useCallback(() => setShowReplay((v) => !v), []);

  // Rollback non destructif (mode view) sur un tour/phase cliqué dans le tracker.
  const snapshotJumpTo = useCallback((turn: number, phase: string | null) => {
    setShowReplay(true);
    setSnapshotJump((prev) => ({ turn, phase, nonce: (prev?.nonce ?? 0) + 1 }));
  }, []);
  /** Cercles de portée autour de la figurine activée (bouton cible de la barre d'outils). */
  const [showRangeRings, setShowRangeRings] = useState(false);
  const handleToggleRangeRings = useCallback(() => setShowRangeRings((v) => !v), []);
  const [advanceWarningDontRemind, setAdvanceWarningDontRemind] = useState(false);

  // Settings preferences (from localStorage)
  const [settings, setSettings] = useState(() => {
    const showAdvanceWarningStr = localStorage.getItem("showAdvanceWarning");
    const showDebugStr = localStorage.getItem("showDebug");
    const showDebugLoSStr = localStorage.getItem("showDebugLoS");
    const autoSelectWeaponStr = localStorage.getItem("autoSelectWeapon");
    const hpBarPerModelStr = localStorage.getItem("hpBarPerModel");
    const hpBarBlinkEnlargedStr = localStorage.getItem("hpBarBlinkEnlarged");
    const showWoundProbabilityStr = localStorage.getItem("showWoundProbability");
    // Mode d'affichage du board. Migration de l'ancien booléen "fitBoardToScreen" : true → "fit".
    const boardDisplayModeStr = localStorage.getItem("boardDisplayMode");
    const legacyFitBoardToScreenStr = localStorage.getItem("fitBoardToScreen");
    // Migration one-shot : ancienne clé "hiddenBadgePerModel" → "statusBadgePerModel" (générique).
    const statusBadgePerModelStr =
      localStorage.getItem("statusBadgePerModel") ?? localStorage.getItem("hiddenBadgePerModel");
    const retreatAlertEnabledStr = localStorage.getItem(RETREAT_ALERT_STORAGE_KEY);
    const battleShockTestEnabledStr = localStorage.getItem("battleShockTestEnabled");
    const deployIconBaseSizeBoundedStr = localStorage.getItem("deployIconBaseSizeBounded");
    const shootPoolFastModeStr = localStorage.getItem("shootPoolFastMode");
    const logShowCoordsStr = localStorage.getItem("logShowCoords");
    const logShowTypeStr = localStorage.getItem("logShowType");
    const dynamicCoverStatusStr = localStorage.getItem("dynamicCoverStatus");
    const replayContainerEnabledStr = localStorage.getItem("replayContainerEnabled");
    const autoSaveEnabledStr = localStorage.getItem("autoSaveEnabled");
    const autoSaveGranularityStr = localStorage.getItem("autoSaveGranularity");
    return {
      showAdvanceWarning:
        canUseAdvanceWarning && (showAdvanceWarningStr ? JSON.parse(showAdvanceWarningStr) : true),
      showDebug: showDebugStr ? JSON.parse(showDebugStr) : false,
      showDebugLoS: showDebugLoSStr ? JSON.parse(showDebugLoSStr) : false,
      shootPoolFastMode: shootPoolFastModeStr ? JSON.parse(shootPoolFastModeStr) : true,
      autoSelectWeapon:
        canUseAutoWeaponSelection && (autoSelectWeaponStr ? JSON.parse(autoSelectWeaponStr) : true),
      hpBarPerModel: hpBarPerModelStr ? JSON.parse(hpBarPerModelStr) : false,
      hpBarBlinkEnlarged: hpBarBlinkEnlargedStr ? JSON.parse(hpBarBlinkEnlargedStr) : false,
      showWoundProbability: showWoundProbabilityStr ? JSON.parse(showWoundProbabilityStr) : false,
      boardDisplayMode: (boardDisplayModeStr
        ? JSON.parse(boardDisplayModeStr)
        : legacyFitBoardToScreenStr && JSON.parse(legacyFitBoardToScreenStr)
          ? "fit"
          : "full") as BoardDisplayMode,
      statusBadgePerModel: statusBadgePerModelStr ? JSON.parse(statusBadgePerModelStr) : false,
      retreatAlertEnabled: retreatAlertEnabledStr ? JSON.parse(retreatAlertEnabledStr) : true,
      battleShockTestEnabled: battleShockTestEnabledStr
        ? JSON.parse(battleShockTestEnabledStr)
        : false,
      deployIconBaseSizeBounded: deployIconBaseSizeBoundedStr
        ? JSON.parse(deployIconBaseSizeBoundedStr)
        : true,
      logShowCoords: logShowCoordsStr ? JSON.parse(logShowCoordsStr) : false,
      logShowType: logShowTypeStr ? JSON.parse(logShowTypeStr) : true,
      dynamicCoverStatus: dynamicCoverStatusStr ? JSON.parse(dynamicCoverStatusStr) : true,
      replayContainerEnabled: replayContainerEnabledStr
        ? JSON.parse(replayContainerEnabledStr)
        : true,
      autoSaveEnabled: autoSaveEnabledStr ? JSON.parse(autoSaveEnabledStr) : false,
      autoSaveGranularity: (autoSaveGranularityStr === "turn" ? "turn" : "phase") as
        | "phase"
        | "turn",
    };
  });

  const updateRetreatAlertSetting = useCallback((value: boolean) => {
    localStorage.setItem(RETREAT_ALERT_STORAGE_KEY, JSON.stringify(value));
    setSettings((prev) => ({ ...prev, retreatAlertEnabled: value }));
  }, []);

  const handleToggleAdvanceWarning = (value: boolean) => {
    if (!canUseAdvanceWarning) {
      return;
    }
    setSettings((prev) => ({ ...prev, showAdvanceWarning: value }));
    localStorage.setItem("showAdvanceWarning", JSON.stringify(value));
  };

  const handleToggleDebug = (value: boolean) => {
    setSettings((prev) => ({ ...prev, showDebug: value }));
    localStorage.setItem("showDebug", JSON.stringify(value));
  };

  const handleToggleReplayContainer = (value: boolean) => {
    setSettings((prev) => ({ ...prev, replayContainerEnabled: value }));
    localStorage.setItem("replayContainerEnabled", JSON.stringify(value));
  };

  const handleToggleAutoSave = (value: boolean) => {
    setSettings((prev) => ({ ...prev, autoSaveEnabled: value }));
    localStorage.setItem("autoSaveEnabled", JSON.stringify(value));
    apiProps.setAutosaveConfig(value, settings.autoSaveGranularity).catch(console.error);
  };

  const handleSetAutoSaveGranularity = (value: "phase" | "turn") => {
    setSettings((prev) => ({ ...prev, autoSaveGranularity: value }));
    localStorage.setItem("autoSaveGranularity", value);
    apiProps.setAutosaveConfig(settings.autoSaveEnabled, value).catch(console.error);
  };

  const handleDeleteSaves = useCallback(async () => {
    await apiProps.deleteSaves();
  }, [apiProps.deleteSaves]);

  // Le serveur est la source de vérité de la config des saves (persistée dans logs/save_config.json) :
  // au montage on LIT la config et on aligne l'UI dessus. Aucun push au montage — seuls les toggles
  // de l'utilisateur écrivent vers le serveur (évite qu'un localStorage périmé écrase la config).
  // biome-ignore lint/correctness/useExhaustiveDependencies: lecture initiale au montage/entrée en PvP
  useEffect(() => {
    // Attendre l'API réelle : le stub (gameState null) renverrait une config toute à false et
    // écraserait l'UI (toggles off, Save grisé) à chaque remontage.
    if (!isSnapshotMode || apiProps.gameState == null) return;
    apiProps
      .fetchSaveConfig()
      .then((cfg) => {
        setSnapshotPersistEnabled(cfg.persist_enabled);
        setSaveDirSelected(cfg.dir_set);
        if (cfg.dir_set) setSnapshotPersistDir(cfg.directory);
        // Répertoire obligatoire dès le start : sans répertoire, on invite à en configurer un pour
        // que la partie soit enregistrée depuis le game_start.
        if (!cfg.dir_set) setLaunchDirPromptOpen(true);
        setSettings((prev) => ({
          ...prev,
          autoSaveEnabled: cfg.autosave_enabled,
          autoSaveGranularity: cfg.granularity,
        }));
      })
      .catch(console.error);
  }, [isSnapshotMode, apiProps.gameState == null]);

  // Popup de lancement : choisir un répertoire de save puis relancer la partie pour enregistrer
  // depuis le game_start. Annulation du sélecteur natif → on laisse le popup ouvert.
  const handleConfigureSaveDirAtLaunch = async () => {
    try {
      const path = await apiProps.pickDirectory();
      if (!path) return;
      await apiProps.snapshotSetPersist(true, path);
      setSnapshotPersistEnabled(true);
      setSnapshotPersistDir(path);
      setSaveDirSelected(true);
      localStorage.setItem("snapshotPersistEnabled", "true");
      localStorage.setItem("snapshotPersistDir", path);
      localStorage.setItem("saveDirSelected", "true");
      setLaunchDirPromptOpen(false);
      window.location.reload();
    } catch (e) {
      console.error(e);
    }
  };

  const handleToggleBattleShockTest = (value: boolean) => {
    setSettings((prev) => ({ ...prev, battleShockTestEnabled: value }));
    localStorage.setItem("battleShockTestEnabled", JSON.stringify(value));
  };

  const handleToggleDebugLoS = (value: boolean) => {
    setSettings((prev) => ({ ...prev, showDebugLoS: value }));
    localStorage.setItem("showDebugLoS", JSON.stringify(value));
  };

  const handleToggleShootPoolFastMode = (value: boolean) => {
    setSettings((prev) => ({ ...prev, shootPoolFastMode: value }));
    localStorage.setItem("shootPoolFastMode", JSON.stringify(value));
  };

  const handleToggleAutoSelectWeapon = (value: boolean) => {
    if (!canUseAutoWeaponSelection) {
      return;
    }
    setSettings((prev) => ({ ...prev, autoSelectWeapon: value }));
    localStorage.setItem("autoSelectWeapon", JSON.stringify(value));
  };

  const handleToggleHpBarPerModel = (value: boolean) => {
    setSettings((prev) => ({ ...prev, hpBarPerModel: value }));
    localStorage.setItem("hpBarPerModel", JSON.stringify(value));
  };

  const handleToggleHpBarBlinkEnlarged = (value: boolean) => {
    setSettings((prev) => ({ ...prev, hpBarBlinkEnlarged: value }));
    localStorage.setItem("hpBarBlinkEnlarged", JSON.stringify(value));
  };

  const handleToggleShowWoundProbability = (value: boolean) => {
    setSettings((prev) => ({ ...prev, showWoundProbability: value }));
    localStorage.setItem("showWoundProbability", JSON.stringify(value));
  };

  const handleSetBoardDisplayMode = (value: BoardDisplayMode) => {
    setSettings((prev) => ({ ...prev, boardDisplayMode: value }));
    localStorage.setItem("boardDisplayMode", JSON.stringify(value));
  };

  const handleToggleStatusBadgePerModel = (value: boolean) => {
    setSettings((prev) => ({ ...prev, statusBadgePerModel: value }));
    localStorage.setItem("statusBadgePerModel", JSON.stringify(value));
  };

  const handleToggleDynamicCoverStatus = (value: boolean) => {
    setSettings((prev) => ({ ...prev, dynamicCoverStatus: value }));
    localStorage.setItem("dynamicCoverStatus", JSON.stringify(value));
  };

  const handleToggleLogShowCoords = (value: boolean) => {
    setSettings((prev) => ({ ...prev, logShowCoords: value }));
    localStorage.setItem("logShowCoords", JSON.stringify(value));
  };

  const handleToggleLogShowType = (value: boolean) => {
    setSettings((prev) => ({ ...prev, logShowType: value }));
    localStorage.setItem("logShowType", JSON.stringify(value));
  };

  const handleToggleDeployIconBaseSizeBounded = (value: boolean) => {
    setSettings((prev) => ({ ...prev, deployIconBaseSizeBounded: value }));
    localStorage.setItem("deployIconBaseSizeBounded", JSON.stringify(value));
  };

  const handleToggleRetreatAlert = (value: boolean) => {
    updateRetreatAlertSetting(value);
  };

  useEffect(() => {
    if (apiProps.advanceWarningPopup) {
      setAdvanceWarningDontRemind(false);
    }
  }, [apiProps.advanceWarningPopup]);

  // Track AI processing with ref to avoid re-render loops
  const isAIProcessingRef = useRef(false);
  const [aiError, setAiError] = useState<string | null>(null);
  const [lastProcessedTurn, setLastProcessedTurn] = useState<string>("");

  // Track previous values to prevent console flooding during animations
  const prevAICheckRef = useRef<{
    currentPhase: string;
    current_player: number;
    isAITurn: boolean;
    shouldTriggerAI: boolean;
    turnKey: string;
  } | null>(null);

  const clearAIError = () => setAiError(null);

  // AI Turn Processing Effect - Trigger AI when it's AI player's turn and has eligible units
  useEffect(() => {
    if (!apiProps.gameState) return;

    const playerTypes = apiProps.gameState.player_types;
    if (!playerTypes) {
      throw new Error("Missing player_types in gameState for AI turn orchestration");
    }
    const getPlayerType = (playerId: number): "human" | "ai" => {
      const playerType = playerTypes[String(playerId)];
      if (!playerType) {
        throw new Error(`Missing player type for player ${playerId}`);
      }
      return playerType;
    };
    const isAiUnit = (unit: Unit): boolean => getPlayerType(unit.player) === "ai";
    const hasAiUnitsInPool = (pool: Array<string | number>, state: { units: Unit[] }): boolean =>
      pool.some((unitId) => {
        const unit = state.units.find((u: Unit) => String(u.id) === String(unitId));
        return !!unit && isAiUnit(unit) && unit.HP_CUR > 0;
      });

    const isAiEnabled = isAiMode;

    // Check if game is over by examining unit health
    const player1Alive = apiProps.gameState.units.some((u) => u.player === 1 && u.HP_CUR > 0);
    const player2Alive = apiProps.gameState.units.some((u) => u.player === 2 && u.HP_CUR > 0);
    const gameNotOver = player1Alive && player2Alive;

    // CRITICAL: Check if AI has eligible units in current phase
    // Use simple heuristic instead of missing activation pools
    const currentPhase = apiProps.gameState.phase as GamePhase;
    let hasEligibleAIUnits = false;

    if (currentPhase === "deployment") {
      const deploymentState = apiProps.gameState?.deployment_state;
      if (!deploymentState) {
        hasEligibleAIUnits = false;
      } else {
        const deployer = deploymentState.current_deployer;
        const pool = deploymentState.deployable_units?.[String(deployer)] || [];
        hasEligibleAIUnits = getPlayerType(deployer) === "ai" && pool.length > 0;
      }
    } else if (currentPhase === "move") {
      // Move phase: Check move activation pool for AI eligibility
      if (apiProps.gameState.move_activation_pool) {
        hasEligibleAIUnits = hasAiUnitsInPool(
          apiProps.gameState.move_activation_pool,
          apiProps.gameState
        );
      }
    } else if (currentPhase === "shoot") {
      hasEligibleAIUnits = apiProps.gameState.shoot_activation_pool
        ? hasAiUnitsInPool(apiProps.gameState.shoot_activation_pool, apiProps.gameState)
        : false;
    } else if (currentPhase === "charge") {
      // Charge phase: Check charge activation pool for AI eligibility
      if (apiProps.gameState.charge_activation_pool) {
        hasEligibleAIUnits = hasAiUnitsInPool(
          apiProps.gameState.charge_activation_pool,
          apiProps.gameState
        );
      }
    } else if (currentPhase === "fight") {
      // Fight phase V11 : pool actionnable unique exposé par le moteur (fight_eligible_units).
      const fightPool: string[] = (apiProps.gameState?.fight_eligible_units ?? []).map((id) =>
        String(id)
      );

      hasEligibleAIUnits = hasAiUnitsInPool(fightPool, apiProps.gameState);
    }

    const current_player = apiProps.gameState?.current_player;
    if (current_player === undefined || current_player === null) {
      throw new Error("Missing current_player in gameState");
    }
    const isAITurn =
      currentPhase === "fight" ? hasEligibleAIUnits : getPlayerType(current_player) === "ai";

    // Removed duplicate log - now handled below with change detection

    const fightSubphaseForKey = apiProps.fightSubPhase ?? apiProps.gameState?.fight_subphase ?? "";
    const turnKey = `${apiProps.gameState?.current_player}-${currentPhase}-${fightSubphaseForKey}-${apiProps.gameState?.currentTurn || 1}`;

    // Reset lastProcessedTurn if turn/phase has changed (prevents blocking on failed AI turns)
    // Extract turn/phase from lastProcessedTurn to compare
    if (lastProcessedTurn) {
      const lastParts = lastProcessedTurn.split("-");
      const currentTurn = apiProps.gameState?.currentTurn || 1;
      const lastTurn = lastParts.length >= 4 ? parseInt(lastParts[3], 10) : null;
      const lastPhase = lastParts.length >= 2 ? lastParts[1] : null;

      // If turn or phase changed, reset lastProcessedTurn
      if (lastTurn !== currentTurn || lastPhase !== currentPhase) {
        setLastProcessedTurn("");
      }
    }

    // Allow multiple AI activations in same phase if there are still eligible units
    // Don't use lastProcessedTurn to block - rely on isAIProcessingRef and hasEligibleAIUnits
    // lastProcessedTurn is only used to detect turn/phase changes for reset
    const shouldTriggerAI =
      isAiEnabled && isAITurn && !isAIProcessingRef.current && gameNotOver && hasEligibleAIUnits;

    // Only log when values actually change (prevents console flooding during animations)
    const currentAICheck = {
      currentPhase,
      current_player: apiProps.gameState.current_player,
      isAITurn,
      shouldTriggerAI,
      turnKey,
    };

    const prevCheck = prevAICheckRef.current;
    const hasChanged =
      !prevCheck ||
      prevCheck.currentPhase !== currentAICheck.currentPhase ||
      prevCheck.current_player !== currentAICheck.current_player ||
      prevCheck.isAITurn !== currentAICheck.isAITurn ||
      prevCheck.shouldTriggerAI !== currentAICheck.shouldTriggerAI ||
      prevCheck.turnKey !== currentAICheck.turnKey;

    if (hasChanged) {
      prevAICheckRef.current = currentAICheck;
    }

    if (shouldTriggerAI) {
      isAIProcessingRef.current = true;
      // Don't set lastProcessedTurn here - wait until AI completes successfully

      // Small delay to ensure UI updates are complete
      setTimeout(async () => {
        try {
          const latestState = apiProps.gameState;
          if (!latestState) {
            throw new Error("Missing gameState before AI turn");
          }
          const latestPhase = latestState.phase;
          const latestPlayer = latestState.current_player;
          if (latestPlayer === undefined || latestPlayer === null) {
            throw new Error("Missing current_player before AI turn");
          }
          if (latestPhase !== "fight" && getPlayerType(latestPlayer) !== "ai") {
            return;
          }
          if (latestPhase === "fight") {
            // V11 : pool actionnable unique exposé par le moteur.
            const latestFightPool: string[] = (latestState.fight_eligible_units ?? []).map((id) =>
              String(id)
            );
            const isAITurnNow = hasAiUnitsInPool(latestFightPool, latestState);
            if (!isAITurnNow) {
              return;
            }
          }
          if (apiProps.executeAITurn) {
            await apiProps.executeAITurn();
            // Don't set lastProcessedTurn here - allow multiple activations in same phase
            // lastProcessedTurn will be set when phase actually changes (via useEffect dependency)
          } else {
            console.error(
              "❌ [BOARD_WITH_API] executeAITurn function not available, type:",
              typeof apiProps.executeAITurn
            );
            setAiError("AI function not available");
          }
        } catch (error) {
          console.error("❌ [BOARD_WITH_API] AI turn failed:", error);
          setAiError(error instanceof Error ? error.message : "AI turn failed");
        } finally {
          isAIProcessingRef.current = false;
        }
      }, 1500);
    } else if (isAiEnabled && isAITurn && !hasEligibleAIUnits) {
      // AI turn skipped - no eligible units
    }
  }, [isAiMode, apiProps, lastProcessedTurn]);

  // Update lastProcessedTurn when phase/turn changes (to track phase transitions)
  useEffect(() => {
    if (!apiProps.gameState) return;
    const fightSubphaseForKey = apiProps.fightSubPhase ?? apiProps.gameState?.fight_subphase ?? "";
    const currentTurnKey = `${apiProps.gameState?.current_player}-${apiProps.gameState?.phase}-${fightSubphaseForKey}-${apiProps.gameState?.currentTurn || 1}`;

    // Only update if phase/turn actually changed (not just on every render)
    if (lastProcessedTurn && lastProcessedTurn !== currentTurnKey) {
      // Phase/turn changed - reset to allow new AI activations
      const lastParts = lastProcessedTurn.split("-");
      const currentTurn = apiProps.gameState?.currentTurn || 1;
      const lastTurn = lastParts.length >= 4 ? parseInt(lastParts[3], 10) : null;
      const lastPhase = lastParts.length >= 2 ? lastParts[1] : null;

      if (lastTurn !== currentTurn || lastPhase !== apiProps.gameState?.phase) {
        setLastProcessedTurn("");
      }
    }
  }, [apiProps.gameState, apiProps.fightSubPhase, lastProcessedTurn]);

  // Activer/sélectionner une unité efface l'épinglage (l'unité épinglée n'est plus celle affichée)
  useEffect(() => {
    if (apiProps.selectedUnitId != null) {
      setDisplaySelectedUnitId(null);
    }
  }, [apiProps.selectedUnitId]);

  const illustrationPreviewUnit = useMemo(() => {
    const statusUnits = apiProps.gameState?.units;
    if (!statusUnits) {
      return null;
    }
    // Priorité inspection : figurine survolée/épinglée → illustration dérivée du unit_type du
    // modèle (l'asset /icons/<unit_type>.png existe). On garde l'id du squad (badges/statut) et on
    // ne surcharge que type/NAME pour que getUnitIllustrationSrc résolve l'asset de la figurine.
    if (effectiveInspectModel) {
      const host = statusUnits.find(
        (unit) => String(unit.id) === String(effectiveInspectModel.unitId) && unit.HP_CUR > 0
      );
      if (host) {
        const parts = effectiveInspectModel.modelId.split("#");
        const idx = parts.length === 2 ? Number(parts[1]) : NaN;
        const model = Number.isInteger(idx) && idx >= 0 ? host.models?.[idx] : undefined;
        if (model?.unit_type) {
          // Réutilise getUnitIllustrationSrc/Scale existants : on ne surcharge que le type (asset)
          // et l'ILLUSTRATION_RATIO du modèle (seul paramètre qui pilote l'échelle).
          return {
            ...host,
            NAME: undefined,
            type: model.unit_type,
            ILLUSTRATION_RATIO: model.ILLUSTRATION_RATIO ?? host.ILLUSTRATION_RATIO,
          };
        }
      }
    }
    const effectiveIllustrationUnitId =
      illustrationPreviewUnitId ?? displaySelectedUnitId ?? apiProps.selectedUnitId ?? null;
    if (effectiveIllustrationUnitId === null) {
      return null;
    }
    return (
      statusUnits.find(
        (unit) => String(unit.id) === String(effectiveIllustrationUnitId) && unit.HP_CUR > 0
      ) ?? null
    );
  }, [
    apiProps.gameState?.units,
    apiProps.selectedUnitId,
    illustrationPreviewUnitId,
    displaySelectedUnitId,
    effectiveInspectModel,
  ]);

  // Préchargement des illustrations : au niveau du board, donc actif AUSSI pendant le déploiement
  // PvP, où le panneau lui-même est démonté.
  useUnitIllustrationPreload(apiProps.gameState?.units ?? []);

  if (apiProps.loading) {
    return (
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          height: "600px",
          background: "#1f2937",
          borderRadius: "8px",
          color: "white",
          fontSize: "18px",
        }}
      >
        Starting W40K Engine Game...
      </div>
    );
  }

  if (apiProps.error) {
    return (
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          height: "600px",
          background: "#7f1d1d",
          borderRadius: "8px",
          color: "#fecaca",
          fontSize: "18px",
          padding: "20px",
        }}
      >
        <div>Error: {apiProps.error}</div>
        <button
          type="button"
          onClick={() => window.location.reload()}
          style={{
            marginTop: "10px",
            padding: "10px 20px",
            backgroundColor: "#dc2626",
            color: "white",
            border: "none",
            borderRadius: "4px",
            cursor: "pointer",
          }}
        >
          Retry
        </button>
      </div>
    );
  }

  /** Alignement explicite avec le hook : l’union inférée peut omettre des clés côté serveur TS du workspace. */
  const engineApiBlink = apiProps as UseEngineAPIBlinkBoardProps;

  const deploymentPanel = (() => {
    if (!apiProps.gameState) {
      return null;
    }
    const phase = apiProps.gameState.phase as GamePhase;
    if (phase !== "deployment" || apiProps.gameState.deployment_type !== "active") {
      return null;
    }
    const deploymentState = apiProps.gameState.deployment_state;
    if (!deploymentState) {
      return null;
    }

    const currentDeployer = Number(deploymentState.current_deployer) as PlayerId;
    const players: PlayerId[] = [1, 2];
    const getIconBorderColor = (player: PlayerId): string =>
      player === 2 ? "var(--hp-bar-player2)" : "var(--hp-bar-player1)";

    const isTestDeploymentMode = isRosterSetupMode;
    const isTestSetupLocked = isTestDeploymentMode && !testDeploymentStarted;
    return (
      <div className="deployment-panel deployment-panel--dual">
        {players.map((player) => {
          const deployableIdsRaw = deploymentState.deployable_units?.[String(player)] || [];
          const deployableUnits = deployableIdsRaw
            .map((id) => apiProps.gameState!.units.find((u) => String(u.id) === String(id)))
            .filter((u): u is Unit => Boolean(u));
          // 1 ligne par escouade, triée par unit ID (pas de regroupement par type).
          const deployableSorted = [...deployableUnits].sort((a, b) => Number(a.id) - Number(b.id));
          const isCurrentDeployer = player === currentDeployer;
          const isCollapsed = deploymentRosterCollapsed[player];
          const deployedUnitIds = deploymentState.deployed_units.map((id) => String(id));
          const hasDeployedByPlayer = deployedUnitIds.some((deployedId) => {
            const deployedUnit = apiProps.gameState!.units.find((u) => String(u.id) === deployedId);
            return deployedUnit ? Number(deployedUnit.player) === player : false;
          });
          const canChangeRoster = isTestDeploymentMode
            ? !testDeploymentStarted
            : isCurrentDeployer && !hasDeployedByPlayer;
          const canInteractDeployment = isCurrentDeployer && !isTestSetupLocked;

          return (
            <div
              key={`deployment-roster-${player}`}
              className={`deployment-panel__roster deployment-panel__roster--player${player}`}
            >
              <div
                className={`deployment-panel__player-banner ${
                  player === 2
                    ? "deployment-panel__player-banner--player2"
                    : "deployment-panel__player-banner--player1"
                }`}
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: "8px",
                }}
              >
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "flex-start",
                    gap: "8px",
                  }}
                >
                  <button
                    type="button"
                    className="deployment-panel__toggle"
                    onClick={() =>
                      setDeploymentRosterCollapsed((prev) => ({
                        ...prev,
                        [player]: !prev[player],
                      }))
                    }
                    aria-label={
                      isCollapsed
                        ? `Etendre roster player ${player}`
                        : `Reduire roster player ${player}`
                    }
                  >
                    {isCollapsed ? "+" : "−"}
                  </button>
                  <span>
                    Player {player} - Deployment {isCurrentDeployer ? "(Active)" : "(Waiting)"}
                  </span>
                </div>
                {canChangeRoster && (
                  <button
                    type="button"
                    className={`deployment-panel__change-roster deployment-panel__change-roster--player${player}`}
                    onClick={() => openRosterPicker(player)}
                  >
                    Change Roster
                  </button>
                )}
              </div>

              {!isCollapsed && (
                <div className="deployment-panel__type-list">
                  {deployableSorted.length === 0 && (
                    <div className="deployment-panel__empty">Aucune unite deployable restante</div>
                  )}
                  {/* 1 ligne par escouade, triée par unit ID. */}
                  {deployableSorted.map((unit) => {
                    const isSelected = apiProps.selectedUnitId === unit.id;
                    const displayName =
                      unit.DISPLAY_NAME ||
                      unit.name ||
                      unit.type ||
                      unit.unitType ||
                      String(unit.id);
                    // Nombre de figurines = clés de occupied_hexes_by_model (source du board,
                    // toujours présente même pour une escouade non déployée à (-1,-1)).
                    const ucEntry = (
                      apiProps.gameState!.units_cache as
                        | Record<
                            string,
                            {
                              occupied_hexes_by_model?: Record<string, unknown>;
                              models_meta_by_model?: Record<
                                string,
                                {
                                  ICON?: string;
                                  BASE_SIZE?: number | [number, number];
                                  BASE_SHAPE?: string;
                                  ICON_SCALE?: number;
                                  role?: string | null;
                                }
                              >;
                            }
                          >
                        | undefined
                    )?.[String(unit.id)];
                    // Ordre d'affichage gauche→droite : leader → support → sergeant
                    // → special_weapon → figurine de base. role par figurine exposé
                    // par le backend dans models_meta_by_model.
                    const DEPLOY_ROLE_ORDER: Record<string, number> = {
                      leader: 0,
                      support: 1,
                      sergeant: 2,
                      special_weapon: 3,
                    };
                    const roleRank = (modelId: string): number => {
                      const role = ucEntry?.models_meta_by_model?.[modelId]?.role;
                      return role != null && role in DEPLOY_ROLE_ORDER
                        ? DEPLOY_ROLE_ORDER[role]
                        : 4;
                    };
                    const figModelIds = (
                      ucEntry?.occupied_hexes_by_model
                        ? Object.keys(ucEntry.occupied_hexes_by_model)
                        : [String(unit.id)]
                    ).sort((a, b) => roleRank(a) - roleRank(b));
                    const figCount = figModelIds.length;
                    // Icône par figurine : models_meta_by_model n'est exposé que pour
                    // les escouades hétérogènes ; sinon repli métier sur l'icône d'unité.
                    const iconForModel = (modelId: string): string => {
                      const baseIcon = ucEntry?.models_meta_by_model?.[modelId]?.ICON ?? unit.ICON;
                      return player === 2 ? baseIcon.replace(".webp", "_red.webp") : baseIcon;
                    };
                    // Taille d'icône = même ratio que le board (source unique
                    // getIconDiameterRatio), avec un HEX_RADIUS fictif de calibrage tel que
                    // l'infanterie standard ≈ 36px. Bornes optionnelles 24..60px.
                    const DEPLOY_ICON_HEX_RADIUS = 3;
                    const ICON_SCALE_GLOBAL = 1.2; // = board_config.display.icon_scale
                    const iconPxForModel = (modelId: string): number => {
                      const meta = ucEntry?.models_meta_by_model?.[modelId];
                      const figUnit = {
                        BASE_SIZE: meta?.BASE_SIZE ?? unit.BASE_SIZE,
                        BASE_SHAPE: meta?.BASE_SHAPE ?? unit.BASE_SHAPE,
                        ICON_SCALE: meta?.ICON_SCALE ?? unit.ICON_SCALE,
                      } as Unit;
                      const px = Math.round(
                        getIconDiameterRatio(figUnit, ICON_SCALE_GLOBAL) * DEPLOY_ICON_HEX_RADIUS
                      );
                      return settings.deployIconBaseSizeBounded
                        ? Math.max(24, Math.min(60, px))
                        : px;
                    };
                    const tooltipText = `${displayName} - ID ${unit.id} - ${figCount} fig.${isCurrentDeployer ? "" : " (inactive this turn)"}`;
                    return (
                      <button
                        type="button"
                        className={`deployment-panel__unit-row deployment-panel__unit-row--player${player}`}
                        key={`deploy-unit-${player}-${unit.id}`}
                        onMouseEnter={(e) => {
                          setDeploymentTooltip({
                            visible: true,
                            text: tooltipText,
                            x: e.clientX,
                            y: e.clientY,
                          });
                        }}
                        onMouseMove={(e) => {
                          setDeploymentTooltip((prev) => ({
                            visible: true,
                            text: prev?.text ?? tooltipText,
                            x: e.clientX,
                            y: e.clientY,
                          }));
                        }}
                        onMouseLeave={() => {
                          setDeploymentTooltip(null);
                        }}
                        onClick={() => {
                          if (!canInteractDeployment) {
                            return;
                          }
                          apiProps.onSelectUnit(unit.id);
                          setClickedUnitId(null);
                        }}
                        aria-disabled={!canInteractDeployment}
                        tabIndex={canInteractDeployment ? 0 : -1}
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: "8px",
                          width: "100%",
                          minHeight: "32px",
                          borderRadius: "6px",
                          border: isSelected
                            ? "1px solid transparent"
                            : `1px solid ${getIconBorderColor(player)}`,
                          background: isSelected ? "rgba(8, 40, 22, 0.92)" : "rgba(0, 0, 0, 0.35)",
                          boxShadow: isSelected ? HALO_GLOW : undefined,
                          outline: "none",
                          color: "white",
                          cursor: canInteractDeployment ? "pointer" : "not-allowed",
                          opacity: canInteractDeployment ? 1 : 0.55,
                          padding: "4px 8px",
                          textAlign: "left",
                        }}
                      >
                        <div
                          style={{
                            display: "flex",
                            flexWrap: "wrap",
                            alignItems: "center",
                            gap: "2px",
                            flex: "0 1 auto",
                            minWidth: 0,
                          }}
                        >
                          {figModelIds.map((figModelId) => {
                            const figPx = iconPxForModel(figModelId);
                            return (
                              <img
                                key={`deploy-fig-${player}-${unit.id}-${figModelId}`}
                                src={iconForModel(figModelId)}
                                alt={displayName}
                                style={{
                                  width: `${figPx}px`,
                                  height: `${figPx}px`,
                                  objectFit: "contain",
                                  pointerEvents: "none",
                                  flex: "0 0 auto",
                                }}
                              />
                            );
                          })}
                        </div>
                        <span
                          style={{
                            flex: "1 1 auto",
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                            whiteSpace: "nowrap",
                          }}
                        >
                          {displayName}
                        </span>
                        <span style={{ fontSize: "11px", opacity: 0.85, flex: "0 0 auto" }}>
                          {figCount} fig.
                        </span>
                        <span
                          style={{
                            fontSize: "10px",
                            background: "rgba(0, 0, 0, 0.65)",
                            padding: "1px 4px",
                            borderRadius: "3px",
                            flex: "0 0 auto",
                          }}
                        >
                          #{unit.id}
                        </span>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </div>
    );
  })();

  const unitsById = new Map(
    (apiProps.gameState?.units ?? []).map((unit) => [String(unit.id), unit])
  );
  const getRulePromptUnitLabel = (prompt: RuleChoicePrompt): string => {
    const unit = unitsById.get(prompt.unit_id);
    if (!unit) {
      return `Unite #${prompt.unit_id} - ${prompt.display_name}`;
    }
    return `${unit.DISPLAY_NAME || unit.id} #${unit.id} - ${prompt.display_name}`;
  };
  const getRulePromptPlayerClass = (prompt: RuleChoicePrompt): string => {
    const unit = unitsById.get(prompt.unit_id);
    if (!unit) {
      return "";
    }
    if (unit.player === 1) {
      return "rule-choice-group__unit-btn--player1";
    }
    if (unit.player === 2) {
      return "rule-choice-group__unit-btn--player2";
    }
    return "";
  };
  const getRulePromptDescription = (): string => {
    if (ruleChoiceHoveredDescription) {
      return ruleChoiceHoveredDescription;
    }
    return "";
  };
  const getRuleChoiceMomentLabel = (prompt: RuleChoicePrompt): string => {
    if (prompt.phase === "command") return "Command Phase";
    if (prompt.phase === "move") return "Move Phase";
    if (prompt.phase === "shoot") return "Shoot Phase";
    if (prompt.phase === "charge") return "Charge Phase";
    if (prompt.phase === "fight") return "Fight Phase";
    if (prompt.trigger === "on_deploy") return "On Deploy";
    if (prompt.trigger === "turn_start") return "Turn Start";
    if (prompt.trigger === "player_turn_start") return "Player Turn Start";
    if (prompt.trigger === "phase_start") return "Phase Start";
    if (prompt.trigger === "activation_start") return "Activation Start";
    throw new Error(`Unknown rule choice trigger context: ${JSON.stringify(prompt)}`);
  };
  const onRuleChoiceTitleMouseDown = (event: React.MouseEvent<HTMLButtonElement>) => {
    ruleChoiceDragOffsetRef.current = {
      x: event.clientX - ruleChoicePopupPosition.x,
      y: event.clientY - ruleChoicePopupPosition.y,
    };
    setIsDraggingRuleChoicePopup(true);
  };
  const onRosterPickerTitleMouseDown = (event: React.MouseEvent<HTMLButtonElement>) => {
    rosterPickerDragOffsetRef.current = {
      x: event.clientX - rosterPickerPosition.x,
      y: event.clientY - rosterPickerPosition.y,
    };
    setIsDraggingRosterPicker(true);
  };
  const rosterPickerAboveStart =
    gameMode === "pvp" &&
    apiProps.gameState?.phase === "deployment" &&
    apiProps.gameState?.deployment_type === "active" &&
    !testDeploymentStarted;
  const highlightedRuleChoiceUnitId = (() => {
    if (ruleChoiceFocusedUnitId === null) {
      return null;
    }
    const parsed = parseInt(ruleChoiceFocusedUnitId, 10);
    if (!Number.isFinite(parsed)) {
      return null;
    }
    return parsed;
  })();

  /** Statuts 40K de l'unité illustrée. Passé à `GameLogWithIllustration`, qui l'évalue sur
   *  l'unité RÉELLEMENT affichée (celle du fondu en cours, pas forcément la survolée). */
  const illustrationBadgesFor = (unit: Unit): IllustrationBadges => {
    const moved = ((apiProps.unitsMoved ?? []) as number[]).includes(unit.id);
    const advanced = (apiProps.unitsAdvanced ?? []).includes(unit.id);
    const fellBack = ((apiProps.unitsFled ?? []) as number[]).includes(unit.id);
    // Stationary (09.04) : déjà activée en phase move (sortie de la pool) sans aucun déplacement.
    const stationary =
      !moved &&
      !advanced &&
      !fellBack &&
      !(apiProps.gameState?.move_activation_pool ?? []).includes(String(unit.id));
    return {
      hidden: unit.hidden === true || (unit.hidden_models?.length ?? 0) > 0,
      battleShocked: unit.battle_shocked === true,
      advanced,
      moved,
      charged: ((apiProps.unitsCharged ?? []) as number[]).includes(unit.id),
      fellBack,
      stationary,
    };
  };

  // Zone défilante de la colonne droite : SEUL bloc qui absorbe le manque de place (SharedLayout
  // l'enveloppe dans `.unit-status-tables__scroll`).
  const rightColumnScrollableContent = (
    <>
      <ErrorBoundary fallback={<div>Failed to load player 1 status</div>}>
        <UnitStatusTable
          units={apiProps.gameState?.units ?? []}
          player={1}
          inchesToSubhex={inchesToSubhex}
          playerTypes={apiProps.gameState?.player_types}
          selectedUnitId={highlightedRuleChoiceUnitId ?? apiProps.selectedUnitId ?? null}
          guidedFocusUnitId={activeRuleChoicePrompt ? highlightedRuleChoiceUnitId : null}
          clickedUnitId={clickedUnitId}
          onSelectUnit={(unitId) => {
            apiProps.onSelectUnit(unitId);
            setClickedUnitId(null);
          }}
          gameMode={gameMode}
          victoryPoints={getVictoryPointsForPlayer(1)}
          commandPoints={getCommandPointsForPlayer(1)}
          onCollapseChange={setPlayer1Collapsed}
          detailPreviewUnitId={
            illustrationPreviewUnit?.player === 1 ? illustrationPreviewUnit.id : null
          }
          inspectedModel={effectiveInspectModel}
          phase={apiProps.gameState?.phase}
          deploymentType={apiProps.gameState?.deployment_type}
          deploymentState={apiProps.gameState?.deployment_state as DeploymentState | undefined}
        />
      </ErrorBoundary>

      <ErrorBoundary fallback={<div>Failed to load player 2 status</div>}>
        <UnitStatusTable
          units={apiProps.gameState?.units ?? []}
          player={2}
          inchesToSubhex={inchesToSubhex}
          playerTypes={apiProps.gameState?.player_types}
          selectedUnitId={highlightedRuleChoiceUnitId ?? apiProps.selectedUnitId ?? null}
          guidedFocusUnitId={activeRuleChoicePrompt ? highlightedRuleChoiceUnitId : null}
          clickedUnitId={clickedUnitId}
          onSelectUnit={(unitId) => {
            apiProps.onSelectUnit(unitId);
            setClickedUnitId(null);
          }}
          gameMode={gameMode}
          victoryPoints={getVictoryPointsForPlayer(2)}
          commandPoints={getCommandPointsForPlayer(2)}
          onCollapseChange={setPlayer2Collapsed}
          detailPreviewUnitId={
            illustrationPreviewUnit?.player === 2 ? illustrationPreviewUnit.id : null
          }
          inspectedModel={effectiveInspectModel}
          phase={apiProps.gameState?.phase}
          deploymentType={apiProps.gameState?.deployment_type}
          deploymentState={apiProps.gameState?.deployment_state as DeploymentState | undefined}
        />
      </ErrorBoundary>
    </>
  );

  const rightColumnContent = (
    <>
      {gameConfig ? (
        <>
          {showHelper && (
            <div className="helper-panel-right">
              <HelperPanel
                phase={apiProps.gameState?.phase}
                mode={apiProps.mode}
                fightSubphase={apiProps.gameState?.fight_subphase}
                deploymentStarted={testDeploymentStarted}
                deploymentPlaced={apiProps.deployPlan?.placed}
                moveModelSelected={apiProps.squadMovePlan?.activeModelId != null}
              />
            </div>
          )}
          <div
            className="turn-phase-tracker-right"
            style={snapshotViewActive ? { position: "relative", zIndex: 4001 } : undefined}
          >
            <TurnPhaseTracker
              currentTurn={apiProps.gameState?.currentTurn ?? 1}
              currentPhase={apiProps.gameState?.phase ?? "move"}
              phases={
                apiProps.gameState?.deployment_type === "active"
                  ? ["deployment", "command", "move", "shoot", "charge", "fight"]
                  : ["command", "move", "shoot", "charge", "fight"]
              }
              current_player={apiProps.gameState?.current_player}
              onTurnClick={
                isSnapshotMode && settings.replayContainerEnabled
                  ? (turn: number) => snapshotJumpTo(turn, null)
                  : undefined
              }
              onPhaseClick={
                isSnapshotMode && settings.replayContainerEnabled
                  ? (phase: string) => snapshotJumpTo(apiProps.gameState?.currentTurn ?? 1, phase)
                  : undefined
              }
              onEndPhaseClick={isGameOver ? undefined : apiProps.onEndPhase}
              showPileIn={
                apiProps.gameState?.phase === "fight" &&
                apiProps.gameState?.fight_subphase === "pile_in"
              }
              pileInPlayer={(() => {
                const eligible = apiProps.gameState?.fight_eligible_units;
                if (!eligible || eligible.length === 0) return undefined;
                return apiProps.gameState?.units?.find((u) => String(u.id) === String(eligible[0]))
                  ?.player;
              })()}
              onEndPileIn={isGameOver ? undefined : apiProps.onEndPileIn}
              showFightAtk={
                apiProps.gameState?.phase === "fight" &&
                apiProps.gameState?.fight_subphase !== "pile_in" &&
                (apiProps.gameState?.fight_eligible_units?.length ?? 0) > 0 &&
                apiProps.mode === "select" &&
                !apiProps.gameState?.active_fight_unit
              }
              fightAtkPlayer={(() => {
                const eligible = apiProps.gameState?.fight_eligible_units;
                if (!eligible || eligible.length === 0) return undefined;
                return apiProps.gameState?.units?.find((u) => String(u.id) === String(eligible[0]))
                  ?.player;
              })()}
              onFightAtk={
                isGameOver
                  ? undefined
                  : () => {
                      const eligible = apiProps.gameState?.fight_eligible_units;
                      if (!eligible || eligible.length === 0) return;
                      apiProps.onSelectUnit(Number(eligible[0]));
                    }
              }
              onSkipFight={isGameOver ? undefined : apiProps.onSkipFight}
              maxTurns={(() => {
                if (!gameConfig?.game_rules?.max_turns) {
                  throw new Error(
                    `max_turns not found in game configuration. Config structure: ${JSON.stringify(Object.keys(gameConfig || {}))}. Expected: gameConfig.game_rules.max_turns`
                  );
                }
                return gameConfig.game_rules.max_turns;
              })()}
              className=""
            />
          </div>
        </>
      ) : (
        <div className="turn-phase-tracker-right">Loading game configuration...</div>
      )}

      {/* Snapshots temporels (rewind / playback par phase) — PvP / PvP test. */}
      {isSnapshotMode && (
        <SnapshotRewind
          jump={snapshotJump}
          fetchTimeline={apiProps.fetchTimeline}
          onEnableRecording={async () => {
            // Même flux que l'activation du toggle "Sauvegarde des snapshots sur disque" du menu :
            // sélecteur de répertoire natif, puis persistance + coche de l'option (états UI).
            const path = await apiProps.pickDirectory();
            if (!path) return false;
            setSnapshotPersistEnabled(true);
            localStorage.setItem("snapshotPersistEnabled", "true");
            setSnapshotPersistDir(path);
            localStorage.setItem("snapshotPersistDir", path);
            setSaveDirSelected(true);
            localStorage.setItem("saveDirSelected", "true");
            await apiProps.snapshotSetPersist(true, path);
            return true;
          }}
          reloadLive={apiProps.snapshotReloadLive}
          onViewModeChange={setSnapshotViewActive}
          replayOpen={showReplay && settings.replayContainerEnabled}
          createSave={apiProps.saveGameNow}
          fetchSaveList={apiProps.saveList}
          loadSave={handleLoadSave}
          canSave={saveDirSelected}
          fetchPartyList={apiProps.fetchPartyList}
          loadParty={handleLoadParty}
          confirmModifyOpen={snapshotConfirmModify}
          onCancelConfirmModify={() => setSnapshotConfirmModify(false)}
        />
      )}

      {isSnapshotMode && launchDirPromptOpen && (
        // biome-ignore lint/a11y/noStaticElementInteractions: backdrop modal — clic fond = fermeture
        <div
          role="presentation"
          onClick={() => setLaunchDirPromptOpen(false)}
          onKeyDown={(e) => e.key === "Escape" && setLaunchDirPromptOpen(false)}
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,0.55)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 12000,
          }}
        >
          {/* biome-ignore lint/a11y/noStaticElementInteractions: panneau — stopPropagation intentionnel */}
          <div
            onClick={(e) => e.stopPropagation()}
            onKeyDown={(e) => e.stopPropagation()}
            style={{
              background: "#1f2937",
              border: "1px solid #555",
              borderRadius: "8px",
              padding: "16px",
              minWidth: "340px",
              maxWidth: "440px",
              color: "#fff",
              boxShadow: "0 10px 30px rgba(0,0,0,0.5)",
            }}
          >
            <h3 style={{ marginTop: 0 }}>Répertoire de sauvegarde</h3>
            <p style={{ color: "#9ca3af", marginTop: 0 }}>
              Aucun répertoire de sauvegarde n'est configuré. Choisis-en un maintenant pour que la
              partie soit enregistrée (replay, Save, Select, Load) dès le début. Sans répertoire, la
              partie ne sera pas enregistrée.
            </p>
            <div
              style={{ display: "flex", gap: "8px", justifyContent: "flex-end", marginTop: "14px" }}
            >
              <button
                type="button"
                className="replay-btn replay-btn--nav"
                onClick={() => setLaunchDirPromptOpen(false)}
              >
                Continuer sans enregistrer
              </button>
              <button
                type="button"
                className="replay-btn"
                onClick={handleConfigureSaveDirAtLaunch}
                style={{ background: "#059669", borderColor: "#047857", color: "#fff" }}
              >
                Choisir un répertoire
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Barre d'action charge (V11 multi-cibles) : Cancel + Charger, même emplacement/style que
          move/shoot. Affichée pendant la sélection des cibles (mode chargeTargetSelect). */}
      {apiProps.gameState?.phase === "charge" &&
        apiProps.mode === "chargeTargetSelect" &&
        apiProps.selectedUnitId != null && (
          <div
            className="squad-action-bar"
            style={{
              display: "flex",
              alignItems: "center",
              background: "#1f2937",
              border: "1px solid #555",
              borderRadius: "8px",
              padding: 8,
              marginTop: 0,
              marginBottom: 2,
            }}
          >
            <div style={{ flex: 1, display: "flex", alignItems: "center", gap: 8 }}>
              <button
                type="button"
                onClick={() => {
                  if (!isGameOver) apiProps.onCancelCharge?.();
                }}
                style={{
                  border: "1px solid rgba(0,0,0,0.35)",
                  borderRadius: 6,
                  background: "var(--ui-gray-cancel)",
                  color: "#fff",
                  cursor: "pointer",
                  fontSize: 14,
                  fontWeight: 700,
                  padding: "8px 14px",
                  width: 110,
                  textAlign: "center",
                }}
              >
                Cancel
              </button>
              {(() => {
                const nbTargets = apiProps.chargePreviewTargetIds?.length ?? 0;
                const canCharge = nbTargets > 0;
                return (
                  <button
                    type="button"
                    disabled={!canCharge}
                    onClick={() => {
                      if (!isGameOver && canCharge && apiProps.selectedUnitId != null) {
                        apiProps.onValidateCharge?.(apiProps.selectedUnitId);
                      }
                    }}
                    style={{
                      border: "1px solid rgba(0,0,0,0.35)",
                      borderRadius: 6,
                      background: canCharge ? "#7c3aed" : "#3b0764",
                      color: "#fff",
                      cursor: canCharge ? "pointer" : "not-allowed",
                      fontSize: 14,
                      fontWeight: 700,
                      padding: "8px 14px",
                      minWidth: 110,
                      whiteSpace: "nowrap",
                      textAlign: "center",
                      opacity: 1,
                    }}
                  >
                    {(() => {
                      const suffix =
                        apiProps.chargeRoll != null ? ` (Roll: ${apiProps.chargeRoll})` : "";
                      return canCharge ? `Charger !${suffix}` : `Select target${suffix}`;
                    })()}
                  </button>
                );
              })()}
              <span style={{ color: "#e5e7eb", fontSize: 13, fontWeight: 600, marginLeft: 4 }}>
                {apiProps.chargePreviewTargetIds?.length ?? 0} cible
                {(apiProps.chargePreviewTargetIds?.length ?? 0) > 1 ? "s" : ""} déclarée
                {(apiProps.chargePreviewTargetIds?.length ?? 0) > 1 ? "s" : ""}
              </span>
              {/* To the sky (charge, unités FLY) : -2" sur le jet + traversée murs/figurines (Règles 21.03).
                Déclaré AVANT le choix de cible → re-borne dynamiquement les cibles éligibles. */}
              {(() => {
                const flyUnitId = apiProps.selectedUnitId ?? null;
                if (flyUnitId === null) return null;
                const flyUnit = (apiProps.gameState?.units ?? []).find((u) => u.id === flyUnitId);
                const canFly = !!flyUnit?.UNIT_KEYWORDS?.some(
                  (k) => k.keywordId?.toLowerCase() === "fly"
                );
                if (!canFly) return null;
                const tookToSkies = (apiProps.unitsTookToSkiesCharge ?? []).includes(flyUnitId);
                return (
                  <button
                    type="button"
                    key="charge-to-the-sky"
                    className={tookToSkies ? "btn-active" : undefined}
                    onClick={() => {
                      if (!isGameOver) apiProps.onTakeToSkies?.(flyUnitId);
                    }}
                    style={{
                      border: "1px solid rgba(0,0,0,0.35)",
                      borderRadius: 6,
                      color: "#fff",
                      fontSize: 14,
                      fontWeight: 700,
                      padding: "8px 14px",
                      width: 130,
                      textAlign: "center",
                      marginLeft: "auto",
                      background: "#38bdf8",
                      cursor: "pointer",
                    }}
                  >
                    To the sky
                  </button>
                );
              })()}
            </div>
          </div>
        )}

      {/* Barre d'action charge par-figurine (Slice G) : Cancel + Charger (commit du plan complet).
          Affichée en mode chargeModelMove ; Charger actif quand can_validate (toutes figs posées,
          toutes cibles engagées, cohésion OK). */}
      {apiProps.gameState?.phase === "charge" &&
        apiProps.mode === "chargeModelMove" &&
        apiProps.chargeMovePlan != null && (
          <div
            className="squad-action-bar"
            style={{
              display: "flex",
              alignItems: "center",
              background: "#1f2937",
              border: "1px solid #555",
              borderRadius: "8px",
              padding: 8,
              marginTop: 0,
              marginBottom: 2,
            }}
          >
            <div style={{ flex: 1, display: "flex", alignItems: "center", gap: 8 }}>
              <button
                type="button"
                onClick={() => {
                  if (!isGameOver) apiProps.onCancelChargeModelMove?.();
                }}
                style={{
                  border: "1px solid rgba(0,0,0,0.35)",
                  borderRadius: 6,
                  background: "var(--ui-gray-cancel)",
                  color: "#fff",
                  cursor: "pointer",
                  fontSize: 14,
                  fontWeight: 700,
                  padding: "8px 14px",
                  width: 110,
                  textAlign: "center",
                }}
              >
                Cancel
              </button>
              {(["offensive", "defensive"] as const).map((m) => {
                const active = apiProps.chargeFocusMode === m;
                const label = m === "defensive" ? "Focus déf." : "Focus off.";
                const title =
                  m === "defensive"
                    ? "Focus défensif : engage toutes les cibles déclarées, au plus loin possible"
                    : "Focus offensif : engage toutes les cibles déclarées, au plus près (socle à socle)";
                const colorClass = m === "defensive" ? "charge-focus-def" : "charge-focus-off";
                return (
                  <button
                    type="button"
                    key={m}
                    className={`${colorClass}${active ? " btn-active" : ""}`}
                    onClick={() => {
                      if (!isGameOver) {
                        setChargeCheckMsg(null);
                        void apiProps.onChargeAutoplace?.(m);
                      }
                    }}
                    title={title}
                    style={{
                      border: "1px solid rgba(0,0,0,0.35)",
                      borderRadius: 6,
                      color: "#fff",
                      cursor: "pointer",
                      fontSize: 14,
                      fontWeight: 700,
                      padding: "8px 14px",
                      width: 110,
                      textAlign: "center",
                    }}
                  >
                    {label}
                  </button>
                );
              })}
              {(() => {
                const canValidate = apiProps.chargeMovePlan?.canValidate === true;
                return (
                  <button
                    type="button"
                    className="charge-validate"
                    disabled={!canValidate}
                    onClick={() => {
                      if (!isGameOver && canValidate) apiProps.onCommitChargePlan?.();
                    }}
                    style={{
                      border: "1px solid rgba(0,0,0,0.35)",
                      borderRadius: 6,
                      cursor: canValidate ? "pointer" : "not-allowed",
                      fontSize: 14,
                      fontWeight: 700,
                      padding: "8px 14px",
                      width: 110,
                      textAlign: "center",
                      opacity: 1,
                    }}
                  >
                    Validate
                  </button>
                );
              })()}
              {(() => {
                const plan = apiProps.chargeMovePlan;
                if (!plan) return null;
                const nbUnplaced = plan.unplaced?.length ?? 0;
                const nbSat = plan.satisfiedTargets?.length ?? 0;
                const nbTot = nbSat + (plan.unsatisfiedTargets?.length ?? 0);
                return (
                  <span style={{ color: "#e5e7eb", fontSize: 13, fontWeight: 600, marginLeft: 4 }}>
                    {nbSat}/{nbTot} cible{nbTot > 1 ? "s" : ""} engagée{nbTot > 1 ? "s" : ""}
                    {nbUnplaced > 0
                      ? ` · ${nbUnplaced} fig${nbUnplaced > 1 ? "s" : ""} à placer`
                      : ""}
                  </span>
                );
              })()}
              <button
                type="button"
                onClick={() => {
                  const plan = apiProps.chargeMovePlan;
                  if (!plan) {
                    setChargeCheckMsg(null);
                    return;
                  }
                  if (plan.canValidate) {
                    setChargeCheckMsg("Charge valide ✓ (tu peux valider)");
                    return;
                  }
                  const reasons: string[] = [];
                  const nbUnplaced = plan.unplaced?.length ?? 0;
                  if (nbUnplaced > 0) {
                    reasons.push(`${nbUnplaced} figurine(s) non placée(s)`);
                  }
                  const invalid = Object.entries(plan.perModelValid ?? {})
                    .filter(([, v]) => v === false)
                    .map(([m]) => m);
                  if (invalid.length > 0) {
                    reasons.push(
                      `${invalid.length} figurine(s) hors budget / pas plus près d'une cible (${invalid.join(", ")})`
                    );
                  }
                  if (plan.coherencyOk === false) {
                    reasons.push("cohésion d'unité rompue (figs trop éloignées entre elles)");
                  }
                  const missing = plan.missingTargets ?? [];
                  if (missing.length > 0) {
                    reasons.push(`cible(s) non engagée(s) : ${missing.join(", ")}`);
                  }
                  setChargeCheckMsg(
                    reasons.length > 0
                      ? `Non validable — ${reasons.join(" ; ")}`
                      : "Non validable (raison inconnue)"
                  );
                }}
                style={{
                  border: "1px solid rgba(0,0,0,0.35)",
                  borderRadius: 6,
                  background: "#0ea5e9",
                  color: "#fff",
                  cursor: "pointer",
                  fontSize: 13,
                  fontWeight: 700,
                  padding: "6px 12px",
                  marginLeft: 8,
                }}
              >
                Check charge
              </button>
              {chargeCheckMsg && (
                <span
                  style={{
                    color: chargeCheckMsg.startsWith("Charge valide") ? "#86efac" : "#fca5a5",
                    fontSize: 13,
                    fontWeight: 600,
                    marginLeft: 8,
                  }}
                >
                  {chargeCheckMsg}
                </span>
              )}
            </div>
          </div>
        )}

      {/* Barre d'action pile-in par-figurine (V11 12.04, mode fin type charge) : Cancel + Valider
          (commit du plan complet). Affichée en mode pileInModelMove ; Valider actif quand can_validate. */}
      {apiProps.gameState?.phase === "fight" &&
        apiProps.mode === "pileInModelMove" &&
        apiProps.pileInMovePlan != null && (
          <div
            className="squad-action-bar"
            style={{
              display: "flex",
              alignItems: "center",
              background: "#1f2937",
              border: "1px solid #555",
              borderRadius: "8px",
              padding: 8,
              marginTop: 0,
              marginBottom: 2,
            }}
          >
            <div style={{ flex: 1, display: "flex", alignItems: "center", gap: 8 }}>
              <button
                type="button"
                onClick={() => {
                  if (!isGameOver) apiProps.onCancelPileInModelMove?.();
                }}
                style={{
                  border: "1px solid rgba(0,0,0,0.35)",
                  borderRadius: 6,
                  background: "var(--ui-gray-cancel)",
                  color: "#fff",
                  cursor: "pointer",
                  fontSize: 14,
                  fontWeight: 700,
                  padding: "8px 14px",
                  width: 110,
                  textAlign: "center",
                }}
              >
                Cancel
              </button>
              {(["offensive", "defensive"] as const).map((m) => {
                const active = apiProps.pileInFocusMode === m;
                const label = m === "defensive" ? "Focus déf." : "Focus off.";
                const title =
                  m === "defensive"
                    ? "Focus défensif : max de figs engagées, le plus loin possible de la cible"
                    : "Focus offensif : max de figs engagées, socle-à-socle / au plus près de la cible";
                const colorClass = m === "defensive" ? "pile-in-focus-def" : "pile-in-focus-off";
                return (
                  <button
                    key={m}
                    type="button"
                    className={`${colorClass}${active ? " btn-active" : ""}`}
                    onClick={() => {
                      if (!isGameOver) apiProps.onSetPileInFocus?.(m);
                    }}
                    title={title}
                    style={{
                      border: "1px solid rgba(0,0,0,0.35)",
                      borderRadius: 6,
                      cursor: "pointer",
                      fontSize: 14,
                      fontWeight: 700,
                      padding: "8px 14px",
                      width: 110,
                      textAlign: "center",
                    }}
                  >
                    {label}
                  </button>
                );
              })}
              {(() => {
                const canValidate = apiProps.pileInMovePlan?.canValidate === true;
                return (
                  <button
                    type="button"
                    className="pile-in-validate"
                    disabled={!canValidate}
                    onClick={() => {
                      if (!isGameOver && canValidate) apiProps.onCommitPileInPlan?.();
                    }}
                    style={{
                      border: "1px solid rgba(0,0,0,0.35)",
                      borderRadius: 6,
                      cursor: canValidate ? "pointer" : "not-allowed",
                      fontSize: 14,
                      fontWeight: 700,
                      padding: "8px 14px",
                      width: 140,
                      textAlign: "center",
                      opacity: 1,
                    }}
                  >
                    Validate
                  </button>
                );
              })()}
              {(() => {
                const plan = apiProps.pileInMovePlan;
                if (!plan) return null;
                const nbUnplaced = plan.unplaced?.length ?? 0;
                return (
                  <span style={{ color: "#e5e7eb", fontSize: 13, fontWeight: 600, marginLeft: 4 }}>
                    {nbUnplaced > 0
                      ? `${nbUnplaced} fig${nbUnplaced > 1 ? "s" : ""} déplaçable${nbUnplaced > 1 ? "s" : ""}`
                      : "pile-in prêt"}
                  </span>
                );
              })()}
              <button
                type="button"
                onClick={() => {
                  const plan = apiProps.pileInMovePlan;
                  if (!plan) {
                    setPileInCheckMsg(null);
                    return;
                  }
                  if (plan.canValidate) {
                    setPileInCheckMsg("Pile-in valide ✓ (tu peux valider)");
                    return;
                  }
                  const reasons: string[] = [];
                  const invalid = Object.entries(plan.perModelValid ?? {})
                    .filter(([, v]) => v === false)
                    .map(([m]) => m);
                  if (invalid.length > 0) {
                    reasons.push(
                      `${invalid.length} figurine(s) hors zone de déplacement (${invalid.join(", ")})`
                    );
                  }
                  if (!plan.unitEngaged) {
                    reasons.push("l'unité ne finit pas au contact d'un ennemi (zone d'engagement)");
                  }
                  if (!plan.coherencyOk) {
                    reasons.push("cohésion d'unité rompue (figs trop éloignées entre elles)");
                  }
                  if (!plan.keptEngagements) {
                    reasons.push("un engagement de départ est perdu");
                  }
                  setPileInCheckMsg(
                    reasons.length > 0
                      ? `Non validable — ${reasons.join(" ; ")}`
                      : "Non validable (raison inconnue)"
                  );
                }}
                style={{
                  border: "1px solid rgba(0,0,0,0.35)",
                  borderRadius: 6,
                  background: "#0ea5e9",
                  color: "#fff",
                  cursor: "pointer",
                  fontSize: 13,
                  fontWeight: 700,
                  padding: "6px 12px",
                  marginLeft: 8,
                }}
              >
                Check pile-in
              </button>
              {pileInCheckMsg && (
                <span
                  style={{
                    color: apiProps.pileInMovePlan?.canValidate ? "#86efac" : "#fca5a5",
                    fontSize: 13,
                    fontWeight: 600,
                    marginLeft: 8,
                  }}
                >
                  {pileInCheckMsg}
                </span>
              )}
            </div>
          </div>
        )}

      {/* Barre d'action CONSOLIDATION par-figurine (V11 12.08, miroir pile-in). Cascade 3 modes :
          Engaging = sélection de cibles d'abord ; Objective = sélection d'objectif si >1 candidat ;
          Ongoing = direct. Cancel + Valider (commit) + Terminer la consolidation. */}
      {apiProps.gameState?.phase === "fight" &&
        apiProps.mode === "consolidationModelMove" &&
        apiProps.consolidationMovePlan != null && (
          <div
            className="squad-action-bar"
            style={{
              display: "flex",
              alignItems: "center",
              background: "#1f2937",
              border: "1px solid #555",
              borderRadius: "8px",
              padding: 8,
              marginTop: 0,
              marginBottom: 2,
            }}
          >
            <div
              style={{ flex: 1, display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}
            >
              <button
                type="button"
                onClick={() => {
                  if (!isGameOver) apiProps.onCancelConsolidationModelMove?.();
                }}
                style={{
                  border: "1px solid rgba(0,0,0,0.35)",
                  borderRadius: 6,
                  background: "var(--ui-gray-cancel)",
                  color: "#fff",
                  cursor: "pointer",
                  fontSize: 14,
                  fontWeight: 700,
                  padding: "8px 14px",
                  width: 110,
                  textAlign: "center",
                }}
              >
                Cancel
              </button>
              <span
                style={{ color: "#cbd5e1", fontSize: 13, fontWeight: 700, cursor: "help" }}
                title={[
                  "CONSOLIDATION MOVE 12.08",
                  'Distance max : 3"',
                  "Éligible : phase de Fight et unité ayant été éligible à combattre cette phase.",
                  "Effet : l'unité bouge comme décrit dans Moving (03).",
                  "",
                  "AVANT DE BOUGER — sélection du mode (cascade) :",
                  "• Ongoing : si l'unité est engagée, mode obligatoire ; sélectionne toutes les unités ennemies engagées.",
                  "• Engaging : sinon, si l'unité est à ≤3\" d'unités ennemies, mode obligatoire ; sélectionne ≥1 de ces unités.",
                  "• Objective : sinon, si l'unité est à ≤3\" d'objectifs, mode obligatoire ; sélectionne un de ces objectifs.",
                  "",
                  "PENDANT LE MOUVEMENT :",
                  "• Ongoing : les figurines au contact socle d'un ennemi ne peuvent pas bouger. Chaque figurine déplacée doit finir plus près de l'unité ennemie sélectionnée la plus proche, et engagée avec elle si possible.",
                  "• Engaging : chaque figurine déplacée doit finir plus près de l'unité ennemie sélectionnée la plus proche, et engagée si possible.",
                  "• Objective : chaque figurine déplacée doit finir à portée de l'objectif sélectionné si possible, sinon plus près.",
                  "",
                  "APRÈS LE MOUVEMENT :",
                  "• Ongoing : chaque figurine ayant commencé le move engagée avec une unité ennemie doit toujours l'être.",
                  "• Engaging : l'unité doit être engagée avec toutes les unités ennemies sélectionnées. Toute unité ennemie engagée non sélectionnée pour combattre devient éligible et sélectionnée pour combattre (12.04).",
                  "• Objective : l'unité doit être à portée de l'objectif sélectionné.",
                ].join("\n")}
              >
                {apiProps.consolidationMovePlan.consolidationMode === "ongoing"
                  ? "Ongoing"
                  : apiProps.consolidationMovePlan.consolidationMode === "engaging"
                    ? "Engaging"
                    : apiProps.consolidationMovePlan.consolidationMode === "objective"
                      ? "Objective"
                      : "—"}
              </span>
              {/* Engaging : invite à sélectionner ≥1 ennemi (clic sur l'unité ennemie ≤3"). */}
              {apiProps.consolidationMovePlan.consolidationMode === "engaging" &&
                apiProps.consolidationMovePlan.awaitingTargetSelection && (
                  <span style={{ color: "#fca5a5", fontSize: 13, fontWeight: 600 }}>
                    Sélectionne au moins une unité ennemie à engager (clic).
                  </span>
                )}
              {/* Objective : boutons de sélection de l'objectif si >1 candidat. */}
              {apiProps.consolidationMovePlan.consolidationMode === "objective" &&
                apiProps.consolidationMovePlan.awaitingObjectiveSelection &&
                apiProps.consolidationMovePlan.objectiveCandidates.map((oid) => (
                  <button
                    key={oid}
                    type="button"
                    onClick={() => {
                      if (!isGameOver) apiProps.onConsolidationSelectObjective?.(oid);
                    }}
                    style={{
                      border: "1px solid rgba(0,0,0,0.35)",
                      borderRadius: 6,
                      background: "#0ea5e9",
                      color: "#fff",
                      cursor: "pointer",
                      fontSize: 13,
                      fontWeight: 700,
                      padding: "6px 12px",
                    }}
                  >
                    Objectif {String(oid)}
                  </button>
                ))}
              {/* Focus off./déf. (12.08) : auto-placement ILP. Disponible en ongoing et en engaging
                  (une fois ≥1 cible sélectionnée) ; masqué en objective (cible = zone, non supporté). */}
              {(() => {
                const cm = apiProps.consolidationMovePlan;
                if (!cm) return null;
                const focusable =
                  cm.consolidationMode === "ongoing" ||
                  (cm.consolidationMode === "engaging" && !cm.awaitingTargetSelection);
                if (!focusable) return null;
                return (["offensive", "defensive"] as const).map((m) => {
                  const active = apiProps.consolidationFocusMode === m;
                  const label = m === "defensive" ? "Focus déf." : "Focus off.";
                  const title =
                    m === "defensive"
                      ? "Focus défensif : max de figs engagées, le plus loin possible de la cible"
                      : "Focus offensif : max de figs engagées, socle-à-socle / au plus près de la cible";
                  const colorClass = m === "defensive" ? "pile-in-focus-def" : "pile-in-focus-off";
                  return (
                    <button
                      key={m}
                      type="button"
                      className={`${colorClass}${active ? " btn-active" : ""}`}
                      onClick={() => {
                        if (!isGameOver) apiProps.onSetConsolidationFocus?.(m);
                      }}
                      title={title}
                      style={{
                        border: "1px solid rgba(0,0,0,0.35)",
                        borderRadius: 6,
                        cursor: "pointer",
                        fontSize: 14,
                        fontWeight: 700,
                        padding: "8px 14px",
                        width: 110,
                        textAlign: "center",
                      }}
                    >
                      {label}
                    </button>
                  );
                });
              })()}
              {(() => {
                const canValidate = apiProps.consolidationMovePlan?.canValidate === true;
                return (
                  <button
                    type="button"
                    className="pile-in-validate"
                    disabled={!canValidate}
                    onClick={() => {
                      if (!isGameOver && canValidate) apiProps.onCommitConsolidationPlan?.();
                    }}
                    style={{
                      border: "1px solid rgba(0,0,0,0.35)",
                      borderRadius: 6,
                      cursor: canValidate ? "pointer" : "not-allowed",
                      fontSize: 14,
                      fontWeight: 700,
                      padding: "8px 14px",
                      width: 140,
                      textAlign: "center",
                    }}
                  >
                    Validate
                  </button>
                );
              })()}
              {/* Raison du blocage de Validate (les 3 conditions 12.08). Masqué tant qu'une sélection
                  préalable est en attente (déjà signalée plus haut). */}
              {(() => {
                const cm = apiProps.consolidationMovePlan;
                if (!cm || cm.canValidate) return null;
                if (cm.awaitingTargetSelection || cm.awaitingObjectiveSelection) return null;
                const reasons: string[] = [];
                if (Object.values(cm.perModelValid ?? {}).some((v) => v === false))
                  reasons.push(
                    "une ou plusieurs figurines ne finissent pas plus près de la cible la plus proche"
                  );
                if (cm.coherencyOk === false)
                  reasons.push("l'unité n'est pas en cohésion d'unité (03.03)");
                if (cm.consolidationMode === "engaging" && cm.engagedWithAllSelected === false)
                  reasons.push("l'unité n'est pas engagée avec toutes les cibles sélectionnées");
                if (cm.consolidationMode === "ongoing" && cm.keptEngagements === false)
                  reasons.push("une figurine perdrait un de ses engagements de départ");
                if (cm.consolidationMode === "objective" && cm.withinObjectiveRange === false)
                  reasons.push("l'unité n'est pas à portée de l'objectif");
                if (reasons.length === 0) return null;
                return (
                  <span style={{ color: "#fca5a5", fontSize: 13, fontWeight: 600, marginLeft: 4 }}>
                    Validate impossible : {reasons.join(" ; ")}.
                  </span>
                );
              })()}
              <button
                type="button"
                onClick={() => {
                  if (!isGameOver) apiProps.onEndConsolidation?.();
                }}
                style={{
                  border: "1px solid rgba(0,0,0,0.35)",
                  borderRadius: 6,
                  background: "#374151",
                  color: "#fff",
                  cursor: "pointer",
                  fontSize: 13,
                  fontWeight: 700,
                  padding: "6px 12px",
                  marginLeft: 8,
                }}
              >
                Terminer la consolidation
              </button>
            </div>
          </div>
        )}

      {/* Présentation paresseuse consolidate (sélection libre de l'unité à consolider) : bouton
          « Terminer la consolidation » quand aucune unité n'est active (miroir end_pile_in). */}
      {apiProps.gameState?.phase === "fight" &&
        apiProps.gameState?.fight_subphase === "consolidate" &&
        apiProps.mode === "select" &&
        (apiProps.gameState?.fight_eligible_units?.length ?? 0) > 0 && (
          <div
            className="squad-action-bar"
            style={{
              display: "flex",
              alignItems: "center",
              background: "#1f2937",
              border: "1px solid #555",
              borderRadius: "8px",
              padding: 8,
              marginTop: 0,
              marginBottom: 2,
            }}
          >
            <span style={{ color: "#cbd5e1", fontSize: 13, fontWeight: 700, marginRight: 8 }}>
              Consolidation — choisis une unité ou termine.
            </span>
            <button
              type="button"
              onClick={() => {
                if (!isGameOver) apiProps.onEndConsolidation?.();
              }}
              style={{
                border: "1px solid rgba(0,0,0,0.35)",
                borderRadius: 6,
                background: "#374151",
                color: "#fff",
                cursor: "pointer",
                fontSize: 13,
                fontWeight: 700,
                padding: "6px 12px",
              }}
            >
              Terminer la consolidation
            </button>
          </div>
        )}

      {/* Barre d'action move : Cancel/Validate (moitié gauche) + boutons de mode (moitié droite).
          Affichée dès l'activation (movePreview) et en plan par-figurine (perModelMove). */}
      {settings.battleShockTestEnabled && (
        <div
          className="squad-action-bar"
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "flex-start",
            background: "#1f2937",
            border: "1px solid #555",
            borderRadius: "8px",
            padding: 8,
            marginTop: 0,
            marginBottom: 2,
          }}
        >
          <button
            type="button"
            className={apiProps.battleShockTestMode ? "btn-active" : undefined}
            onClick={() => apiProps.onToggleBattleShockTestMode?.()}
            style={{
              border: "1px solid rgba(0,0,0,0.35)",
              borderRadius: 6,
              color: "#fff",
              fontSize: 14,
              fontWeight: 700,
              padding: "8px 14px",
              textAlign: "center",
              background: apiProps.battleShockTestMode ? "#ca8a04" : "#713f12",
              cursor: "pointer",
            }}
          >
            {apiProps.battleShockTestMode
              ? "Battle-shock test : ON — clic droit sur une unité"
              : "Battle-shock test : OFF"}
          </button>
          {(() => {
            const chargedDisabled = apiProps.gameState?.phase !== "charge";
            return (
              <button
                type="button"
                disabled={chargedDisabled}
                className={apiProps.chargedTestMode ? "btn-active" : undefined}
                onClick={() => apiProps.onToggleChargedTestMode?.()}
                style={{
                  border: "1px solid rgba(0,0,0,0.35)",
                  borderRadius: 6,
                  color: "#fff",
                  fontSize: 14,
                  fontWeight: 700,
                  padding: "8px 14px",
                  marginLeft: 8,
                  textAlign: "center",
                  background: apiProps.chargedTestMode ? "#7c3aed" : "#2e1065",
                  opacity: chargedDisabled ? 0.4 : 1,
                  cursor: chargedDisabled ? "not-allowed" : "pointer",
                }}
              >
                {chargedDisabled
                  ? "A chargé test (phase charge)"
                  : apiProps.chargedTestMode
                    ? "A chargé test : ON — clic droit sur une unité"
                    : "A chargé test : OFF"}
              </button>
            );
          })()}
          {/* TEST : champ override de la distance de charge (remplace le jet 2D6). Vide = jet normal. */}
          <label
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              marginLeft: 8,
              color: "#fff",
              fontSize: 13,
              fontWeight: 700,
              whiteSpace: "nowrap",
            }}
          >
            Charge forcée
            <input
              type="number"
              min={1}
              max={24}
              placeholder="jet"
              value={chargeRollOverride}
              onChange={(e) => {
                const v = e.target.value;
                setChargeRollOverride(v);
                if (v === "") localStorage.removeItem("chargeRollOverride");
                else localStorage.setItem("chargeRollOverride", v);
              }}
              style={{
                width: 56,
                padding: "6px 8px",
                borderRadius: 6,
                border: "1px solid rgba(0,0,0,0.35)",
                background: chargeRollOverride === "" ? "#374151" : "#0e7490",
                color: "#fff",
                fontSize: 14,
                fontWeight: 700,
                textAlign: "center",
              }}
            />
          </label>
        </div>
      )}
      {apiProps.gameState?.phase === "move" &&
        (apiProps.gameState?.active_movement_unit != null || apiProps.squadMovePlan != null) && (
          <div
            className="squad-action-bar"
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              background: "#1f2937",
              border: "1px solid #555",
              borderRadius: "8px",
              padding: 8,
              marginTop: 0,
              marginBottom: 2,
            }}
          >
            {/* Bloc gauche : Cancel (toujours, preview inclus) / Validate (si plan). */}
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              {/* Cancel : toujours affiché dès l'activation (preview inclus). */}
              <button
                type="button"
                onClick={() => {
                  if (!isGameOver) apiProps.onCancelSquadMove?.();
                }}
                style={{
                  border: "1px solid rgba(0,0,0,0.35)",
                  borderRadius: 6,
                  background: "var(--ui-gray-cancel)",
                  color: "#fff",
                  cursor: "pointer",
                  fontSize: 14,
                  fontWeight: 700,
                  padding: "8px 14px",
                  width: 110,
                  textAlign: "center",
                }}
              >
                Cancel
              </button>
              {/* Validate : uniquement quand un plan par-figurine existe. */}
              {apiProps.squadMovePlan && (
                <button
                  type="button"
                  disabled={!apiProps.squadMovePlan.canValidate}
                  onClick={() => {
                    if (!isGameOver) apiProps.onCommitSquadMovePlan?.();
                  }}
                  style={{
                    border: "1px solid rgba(0,0,0,0.35)",
                    borderRadius: 6,
                    background: apiProps.squadMovePlan.canValidate
                      ? "var(--ui-green-validate)"
                      : "var(--ui-green-validate-off)",
                    color: apiProps.squadMovePlan.canValidate ? "#fff" : "rgba(229,231,235,0.5)",
                    cursor: apiProps.squadMovePlan.canValidate ? "pointer" : "not-allowed",
                    fontSize: 14,
                    fontWeight: 700,
                    padding: "8px 14px",
                    width: 110,
                    textAlign: "center",
                    opacity: 1,
                  }}
                >
                  Validate
                </button>
              )}
            </div>
            {/* To the sky (unités FLY) : centré entre les deux blocs (space-between). */}
            {(() => {
              const flyUnitId =
                apiProps.squadMovePlan?.unitId ??
                apiProps.movePreview?.unitId ??
                (apiProps.gameState?.active_movement_unit != null
                  ? parseInt(apiProps.gameState.active_movement_unit, 10)
                  : null);
              if (flyUnitId === null) return null;
              const flyUnit = (apiProps.gameState?.units ?? []).find((u) => u.id === flyUnitId);
              const canFly = !!flyUnit?.UNIT_KEYWORDS?.some(
                (k) => k.keywordId?.toLowerCase() === "fly"
              );
              if (!canFly) return null;
              const advancedFly =
                (apiProps.unitsAdvanced ?? []).includes(flyUnitId) ||
                apiProps.advancingUnitId === flyUnitId;
              // Apparence figée sur l'état du vol seul (l'Advance ne change pas le rendu) ;
              // toggle neutralisé une fois l'unité advancée (figé à la sélection de l'Advance).
              const tookToSkies = (apiProps.unitsTookToSkies ?? []).includes(flyUnitId);
              return (
                <button
                  type="button"
                  key="to-the-sky"
                  className={tookToSkies ? "btn-active" : undefined}
                  onClick={() => {
                    if (!advancedFly && !isGameOver) apiProps.onTakeToSkies?.(flyUnitId);
                  }}
                  style={{
                    border: "1px solid rgba(0,0,0,0.35)",
                    borderRadius: 6,
                    color: "#fff",
                    fontSize: 14,
                    fontWeight: 700,
                    padding: "8px 14px",
                    width: 110,
                    textAlign: "center",
                    background: "#38bdf8",
                    cursor: advancedFly ? "default" : "pointer",
                  }}
                >
                  To the sky
                </button>
              );
            })()}
            {/* Boutons de mode (Move / Advance / Fall-back / Stationary). */}
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                justifyContent: "flex-start",
              }}
            >
              {(() => {
                const advUnitId =
                  apiProps.squadMovePlan?.unitId ??
                  apiProps.movePreview?.unitId ??
                  (apiProps.gameState?.active_movement_unit != null
                    ? parseInt(apiProps.gameState.active_movement_unit, 10)
                    : null);
                if (advUnitId === null) return null;
                const isAdv = apiProps.advancingUnitId === advUnitId;
                const alreadyAdvanced = (apiProps.unitsAdvanced ?? []).includes(advUnitId);
                // V11 : Advance figé = irréversible. Une fois advancé (état moteur units_advanced,
                // ou advance en cours cette activation), le mode reste verrouillé tout le tour.
                const advanced = alreadyAdvanced || isAdv;
                const engaged = apiProps.activeUnitEngaged === advUnitId;
                const canAdvance = !advanced && !engaged;
                // Règle 09 : non engagée → Move (défaut) + Advance ; engagée → Fall-back (défaut) + Stationary.
                // Move/Fall-back = purement visuels (le commit applique flee si engagé). Stationary = action wait.
                // 3 états : "selected" (enfoncé), "relief" (possible), "disabled" (grisé).
                const modeBtn = (
                  label: string,
                  state: "selected" | "relief" | "disabled",
                  accent: { relief: string; dark: string },
                  onClick?: () => void
                ) => (
                  <button
                    type="button"
                    key={label}
                    className={state === "selected" ? "btn-active" : undefined}
                    disabled={state === "disabled"}
                    onClick={() => {
                      if (state !== "disabled" && !isGameOver) onClick?.();
                    }}
                    style={{
                      border: "1px solid rgba(0,0,0,0.35)",
                      borderRadius: 6,
                      color: "#fff",
                      fontSize: 14,
                      fontWeight: 700,
                      padding: "8px 14px",
                      width: 110,
                      textAlign: "center",
                      background: state === "disabled" ? accent.dark : accent.relief,
                      cursor:
                        state === "disabled"
                          ? "not-allowed"
                          : state === "selected"
                            ? "default"
                            : "pointer",
                      opacity: 1,
                    }}
                  >
                    {label}
                  </button>
                );
                const green = {
                  relief: "var(--ui-green-validate)",
                  dark: "var(--ui-green-validate-off)",
                };
                const orange = { relief: "#ea580c", dark: "#431407" };
                const yellow = { relief: "#ca8a04", dark: "#422006" };
                const grey = { relief: "var(--ui-gray-cancel)", dark: "#1f2937" };
                // Advancé → Move grisé (verrouillé). Sinon engagé → grisé, libre → sélectionné.
                const moveState: "selected" | "relief" | "disabled" =
                  engaged || advanced ? "disabled" : "selected";
                const fallbackState: "selected" | "relief" | "disabled" = engaged
                  ? "selected"
                  : "disabled";
                // Advancé → bouton enfoncé (sélectionné, irréversible). Engagé → grisé. Libre → relief.
                const advanceState: "selected" | "relief" | "disabled" = advanced
                  ? "selected"
                  : engaged
                    ? "disabled"
                    : "relief";
                return (
                  <>
                    {modeBtn("Move", moveState, green)}
                    {modeBtn(
                      isAdv && apiProps.advanceRoll != null
                        ? `Advance (Roll: ${apiProps.advanceRoll})`
                        : "Advance",
                      advanceState,
                      orange,
                      () => {
                        if (canAdvance) apiProps.onSetAdvanceMode?.(advUnitId);
                      }
                    )}
                    {modeBtn("Fall-back", fallbackState, yellow)}
                    {modeBtn("Stationary", advanced ? "disabled" : "relief", grey, () =>
                      apiProps.onStationary?.(advUnitId)
                    )}
                  </>
                );
              })()}
            </div>
          </div>
        )}
      {apiProps.gameState?.phase === "deployment" && apiProps.mode === "deploymentMove" && (
        <div
          className="squad-action-bar"
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            background: "#1f2937",
            border: "1px solid #555",
            borderRadius: "8px",
            padding: 8,
            marginTop: 0,
            marginBottom: 2,
          }}
        >
          <button
            type="button"
            onClick={() => {
              if (!isGameOver) apiProps.onCancelDeploy?.();
            }}
            style={{
              border: "1px solid rgba(0,0,0,0.35)",
              borderRadius: 6,
              background: "var(--ui-gray-cancel)",
              color: "#fff",
              cursor: "pointer",
              fontSize: 14,
              fontWeight: 700,
              padding: "8px 14px",
              width: 110,
              textAlign: "center",
            }}
          >
            Annuler
          </button>
          <button
            type="button"
            disabled={!apiProps.deployPlan?.canValidate}
            onClick={() => {
              if (!isGameOver) apiProps.onCommitDeploy?.();
            }}
            style={{
              border: "1px solid rgba(0,0,0,0.35)",
              borderRadius: 6,
              background: apiProps.deployPlan?.canValidate
                ? "var(--ui-green-validate)"
                : "var(--ui-green-validate-off)",
              color: apiProps.deployPlan?.canValidate ? "#fff" : "rgba(229,231,235,0.5)",
              cursor: apiProps.deployPlan?.canValidate ? "pointer" : "not-allowed",
              fontSize: 14,
              fontWeight: 700,
              padding: "8px 14px",
              width: 110,
              textAlign: "center",
            }}
          >
            Valider
          </button>
        </div>
      )}
      {apiProps.mode === "squadModelShoot" && apiProps.squadShootPlan && (
        <div
          className="squad-action-bar"
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            background: "#1f2937",
            border: "1px solid #555",
            borderRadius: "8px",
            padding: 8,
            marginTop: 0,
            marginBottom: 2,
          }}
        >
          <span
            style={{
              color: "#e5e7eb",
              fontSize: 13,
              fontWeight: 600,
              background: "rgba(17,24,39,0.8)",
              borderRadius: 6,
              padding: "6px 10px",
            }}
          >
            {Object.keys(apiProps.squadShootPlan.targets).length}/
            {apiProps.squadShootPlan.models.length} figs assignées
          </span>
          <button
            type="button"
            onClick={() => {
              if (!isGameOver) apiProps.onCancelSquadShoot?.();
            }}
            style={{
              border: "1px solid rgba(0,0,0,0.35)",
              borderRadius: 6,
              background: "var(--ui-gray-cancel)",
              color: "#fff",
              cursor: "pointer",
              fontSize: 14,
              fontWeight: 700,
              padding: "8px 14px",
            }}
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={!apiProps.squadShootPlan.canValidate}
            onClick={() => {
              if (!isGameOver) apiProps.onCommitSquadShoot?.();
            }}
            style={{
              border: "1px solid rgba(0,0,0,0.35)",
              borderRadius: 6,
              background: apiProps.squadShootPlan.canValidate
                ? "var(--ui-green-validate)"
                : "var(--ui-green-validate-off)",
              color: apiProps.squadShootPlan.canValidate ? "#fff" : "rgba(229,231,235,0.5)",
              cursor: apiProps.squadShootPlan.canValidate ? "pointer" : "not-allowed",
              fontSize: 14,
              fontWeight: 700,
              padding: "8px 14px",
            }}
          >
            Shoot
          </button>
        </div>
      )}

      {apiProps.gameState?.phase === "fight" && apiProps.squadFightPlan && (
        <div
          className="squad-action-bar"
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            background: "#1f2937",
            border: "1px solid #555",
            borderRadius: "8px",
            padding: 8,
            marginTop: 0,
            marginBottom: 2,
          }}
        >
          <span
            style={{
              color: "#e5e7eb",
              fontSize: 13,
              fontWeight: 600,
              background: "rgba(17,24,39,0.8)",
              borderRadius: 6,
              padding: "6px 10px",
            }}
          >
            {Object.keys(apiProps.squadFightPlan.targets).length}/{apiProps.fightAssignableCount}{" "}
            figs assignées
          </span>
          <button
            type="button"
            onClick={() => {
              if (!isGameOver) apiProps.onCancelSquadFight?.();
            }}
            style={{
              border: "1px solid rgba(0,0,0,0.35)",
              borderRadius: 6,
              background: "var(--ui-gray-cancel)",
              color: "#fff",
              cursor: "pointer",
              fontSize: 14,
              fontWeight: 700,
              padding: "8px 14px",
            }}
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={!apiProps.squadFightPlan.canValidate}
            onClick={() => {
              if (!isGameOver) apiProps.onCommitSquadFight?.();
            }}
            style={{
              border: "1px solid rgba(0,0,0,0.35)",
              borderRadius: 6,
              background: apiProps.squadFightPlan.canValidate
                ? "var(--ui-green-validate)"
                : "var(--ui-green-validate-off)",
              color: apiProps.squadFightPlan.canValidate ? "#fff" : "rgba(229,231,235,0.5)",
              cursor: apiProps.squadFightPlan.canValidate ? "pointer" : "not-allowed",
              fontSize: 14,
              fontWeight: 700,
              padding: "8px 14px",
            }}
          >
            Fight
          </button>
        </div>
      )}

      {/* AI Status Display */}
      {isAiMode &&
        (() => {
          const currentPlayer = apiProps.gameState?.current_player;
          const currentPlayerType =
            currentPlayer !== undefined && currentPlayer !== null
              ? apiProps.gameState?.player_types?.[String(currentPlayer)]
              : null;
          const isCurrentPlayerAI = currentPlayerType === "ai";
          return (
            <div
              className={`flex items-center gap-2 px-3 py-2 rounded mb-2 ${
                isCurrentPlayerAI
                  ? isAIProcessingRef.current
                    ? "bg-purple-900 border border-purple-700"
                    : "bg-purple-800 border border-purple-600"
                  : "bg-gray-800 border border-gray-600"
              }`}
            >
              <span className="text-sm font-medium text-white">
                {isCurrentPlayerAI ? "🤖 AI Turn" : "👤 Your Turn"}
              </span>
              {isCurrentPlayerAI && isAIProcessingRef.current && (
                <>
                  <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-purple-300"></div>
                  <span className="text-purple-200 text-sm">AI thinking...</span>
                </>
              )}
            </div>
          );
        })()}

      {deploymentPanel}
      {deploymentTooltip?.visible && (
        <div
          className="rule-tooltip unit-icon-tooltip"
          style={{
            left: `${deploymentTooltip.x}px`,
            top: `${deploymentTooltip.y}px`,
          }}
        >
          {deploymentTooltip.text}
        </div>
      )}
      {showGameOverPopup && apiProps.gameState && (
        <div className="deployment-panel__picker-backdrop">
          <div className="deployment-panel__picker">
            <div className="deployment-panel__picker-title">Game Over</div>
            <div className="deployment-panel__picker-content" style={{ display: "block" }}>
              <div className="deployment-panel__picker-tooltip">
                {(() => {
                  const p1 = getVictoryPointsForPlayer(1);
                  const p2 = getVictoryPointsForPlayer(2);
                  const winner = apiProps.gameState?.winner;
                  const winnerText =
                    winner === 1 ? "Winner: Player 1" : winner === 2 ? "Winner: Player 2" : "Draw";
                  return `Final score:\nP1: ${p1}\nP2: ${p2}\n${winnerText}`;
                })()}
              </div>
            </div>
            <div className="deployment-panel__picker-actions">
              <button
                type="button"
                className="deployment-panel__picker-close"
                onClick={() => setShowGameOverPopup(false)}
              >
                OK
              </button>
            </div>
          </div>
        </div>
      )}
      {rosterPickerPlayer !== null &&
        createPortal(
          <div
            className={`deployment-panel__picker-backdrop${
              rosterPickerAboveStart ? " deployment-panel__picker-backdrop--above-start" : ""
            }`}
          >
            {!rosterPickerAboveStart && (
              <button
                type="button"
                className="deployment-panel__picker-dismiss"
                aria-label="Close roster picker"
                onClick={closeRosterPicker}
              />
            )}
            <div
              className={`deployment-panel__picker${
                rosterPickerAboveStart ? " deployment-panel__picker--draggable" : ""
              }`}
              style={
                rosterPickerAboveStart
                  ? { left: `${rosterPickerPosition.x}px`, top: `${rosterPickerPosition.y}px` }
                  : undefined
              }
            >
              {rosterPickerAboveStart ? (
                <button
                  type="button"
                  className="deployment-panel__picker-title deployment-panel__picker-title--draggable"
                  onMouseDown={onRosterPickerTitleMouseDown}
                >
                  {`Change roster - Player ${rosterPickerPlayer}${isDraggingRosterPicker ? " (drag...)" : ""}`}
                </button>
              ) : (
                <div className="deployment-panel__picker-title">
                  Change roster - Player {rosterPickerPlayer}
                </div>
              )}
              {rosterPickerLoading && (
                <div className="deployment-panel__picker-loading">Loading armies...</div>
              )}
              {rosterPickerError && (
                <div className="deployment-panel__picker-error">{rosterPickerError}</div>
              )}
              {!rosterPickerLoading && !rosterPickerError && (
                <div className="deployment-panel__picker-content">
                  <div className="deployment-panel__picker-factions">
                    <div
                      className="deployment-panel__picker-col-header"
                      style={pickerColHeaderStyle}
                    >
                      Faction
                    </div>
                    {rosterPickerFactions.map((faction) => (
                      <button
                        type="button"
                        key={faction}
                        className={`deployment-panel__picker-item ${effectiveRosterPickerFaction === faction ? "deployment-panel__picker-item--active" : ""}`}
                        onClick={() => {
                          setRosterPickerSelectedFaction(faction);
                          setRosterPickerHoveredDescription("");
                        }}
                      >
                        {rosterPickerFactionDisplayNameById[faction]}
                      </button>
                    ))}
                  </div>
                  <div className="deployment-panel__picker-list">
                    <div
                      className="deployment-panel__picker-col-header"
                      style={pickerColHeaderStyle}
                    >
                      Roster
                    </div>
                    {filteredRosterPickerArmies.map((army) => (
                      <button
                        type="button"
                        key={army.file}
                        className="deployment-panel__picker-item"
                        onMouseEnter={() => setRosterPickerHoveredDescription(army.description)}
                        onClick={() => handleSelectRoster(army.file)}
                      >
                        {army.display_name}
                      </button>
                    ))}
                    {filteredRosterPickerArmies.length === 0 && (
                      <div className="deployment-panel__picker-loading">
                        Aucun roster pour cette faction.
                      </div>
                    )}
                  </div>
                  <div className="deployment-panel__picker-tooltip">
                    <div
                      className="deployment-panel__picker-col-header"
                      style={pickerColHeaderStyle}
                    >
                      Description
                    </div>
                    <div style={{ whiteSpace: "pre-wrap" }}>
                      {rosterPickerHoveredDescription ||
                        "Survolez une armee pour voir sa description"}
                    </div>
                  </div>
                </div>
              )}
              <div className="deployment-panel__picker-actions">
                <button
                  type="button"
                  className="deployment-panel__picker-close"
                  onClick={closeRosterPicker}
                >
                  Close
                </button>
              </div>
            </div>
          </div>,
          document.body
        )}
      {activeRuleChoicePrompt && (
        <div className="rule-choice-overlay">
          <div
            className="deployment-panel__picker deployment-panel__picker--draggable deployment-panel__picker--rule-choice"
            style={{
              left: `${ruleChoicePopupPosition.x}px`,
              top: `${ruleChoicePopupPosition.y}px`,
            }}
          >
            <button
              type="button"
              className="deployment-panel__picker-title deployment-panel__picker-title--draggable"
              onMouseDown={onRuleChoiceTitleMouseDown}
            >
              {`Capacity choice - ${getRuleChoiceMomentLabel(activeRuleChoicePrompt)}${isDraggingRuleChoicePopup ? " (drag...)" : ""}`}
            </button>
            <div className="deployment-panel__picker-content deployment-panel__picker-content--rule-choice">
              <div className="deployment-panel__picker-list deployment-panel__picker-list--rule-choice">
                {ruleChoicePrompts.map((prompt) => {
                  const isFocused = focusedRuleChoicePrompt?.unit_id === prompt.unit_id;
                  return (
                    <div key={`${prompt.unit_id}:${prompt.rule_id}`} className="rule-choice-group">
                      <div className="rule-choice-group__row">
                        <div className="rule-choice-group__unit-col">
                          <button
                            type="button"
                            className={`deployment-panel__picker-item rule-choice-group__unit-btn ${getRulePromptPlayerClass(prompt)} ${isFocused ? "deployment-panel__picker-item--active" : ""}`}
                            onMouseEnter={() =>
                              setRuleChoiceHoveredDescription(getRuleDescription(prompt.rule_id))
                            }
                            onMouseLeave={() => setRuleChoiceHoveredDescription("")}
                            onClick={() => {
                              setRuleChoiceFocusedUnitId(prompt.unit_id);
                            }}
                          >
                            {getRulePromptUnitLabel(prompt)}
                          </button>
                        </div>
                        <div className="rule-choice-group__options-col">
                          <div className="rule-choice-group__options">
                            {prompt.options.map((option) => (
                              <TooltipWrapper
                                text={`Selectionner ${option.label}`}
                                key={option.display_rule_id}
                              >
                                <button
                                  type="button"
                                  className="deployment-panel__picker-item rule-choice-group__option"
                                  onMouseEnter={() =>
                                    setRuleChoiceHoveredDescription(
                                      getRuleDescription(option.display_rule_id)
                                    )
                                  }
                                  onMouseLeave={() => setRuleChoiceHoveredDescription("")}
                                  onBlur={() => setRuleChoiceHoveredDescription("")}
                                  onClick={() => {
                                    apiProps.onSelectRuleChoice(prompt, option.display_rule_id);
                                  }}
                                >
                                  {option.label}
                                </button>
                              </TooltipWrapper>
                            ))}
                          </div>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
              <div className="deployment-panel__picker-tooltip deployment-panel__picker-tooltip--rule-choice">
                {focusedRuleChoicePrompt
                  ? getRulePromptDescription()
                  : "Aucun choix de regle actif"}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Déclaration de l'ordre d'allocation des pertes (cible hétérogène / CHARACTER) */}
      {apiProps.manualOrderRequest && (
        <ManualOrderPicker
          key={`${apiProps.manualOrderRequest.attacker_unit_id}:${apiProps.manualOrderRequest.target_unit_id}:${apiProps.manualOrderRequest.groups.map((g) => g.group_id).join("-")}`}
          request={apiProps.manualOrderRequest}
          onSubmit={(o) => apiProps.onDeclareOrder(o)}
        />
      )}

      {/* AI Error Display */}
      {aiError && (
        <div className="bg-red-900 border border-red-700 rounded p-3 mb-2">
          <div className="flex items-center justify-between">
            <div className="text-red-100 text-sm">
              <strong>🤖 AI Error:</strong> {aiError}
            </div>
            <button
              type="button"
              onClick={clearAIError}
              className="text-red-300 hover:text-red-100 ml-2"
            ></button>
          </div>
        </div>
      )}

      {/* Game Log Component — masqué en PvP pendant la phase de déploiement */}
      {!(gameMode === "pvp" && apiProps.gameState?.phase === "deployment") && (
        <ErrorBoundary fallback={<div>Failed to load game log</div>}>
          <GameLogWithIllustration unit={illustrationPreviewUnit} badgesFor={illustrationBadgesFor}>
            <GameLog
              events={gameLogEventsFiltered}
              currentTurn={apiProps.gameState?.currentTurn ?? 1}
              debugMode={settings.showDebug}
              logShowCoords={settings.logShowCoords}
              logShowType={settings.logShowType}
            />
          </GameLogWithIllustration>
        </ErrorBoundary>
      )}
    </>
  );

  const endlessDutyState = apiProps.endlessDutyState;
  const isEndlessDutyInterWave =
    gameMode === "endless_duty" && endlessDutyState?.inter_wave_pending === true;
  const currentWave = endlessDutyState?.wave_index ?? 1;
  const slotUnlockStatus = {
    leader: currentWave >= endlessDutyUnlockRules.leader,
    melee: currentWave >= endlessDutyUnlockRules.melee,
    range: currentWave >= endlessDutyUnlockRules.range,
  };
  const requisitionCapitalTotal = endlessDutyState?.requisition_capital_total ?? 0;
  const resolveSlotCost = (
    slot: keyof EndlessDutySlotProfiles,
    profile: string,
    picks: EndlessDutyPickState | null
  ): number | null => {
    if (!picks) {
      return null;
    }
    const menu = endlessDutyPickMenus[slot].get(profile);
    if (!menu) {
      return null;
    }
    let total = menu.baseCost;
    const findCost = (options: PickOption[], id: string | null): number | null => {
      if (!id) {
        return 0;
      }
      const option = options.find((opt) => opt.id === id);
      return option ? option.cost : null;
    };
    const packageCost = findCost(menu.primaryPackages, picks.package);
    const meleeCost = findCost(menu.primaryMelee, picks.melee);
    const rangedCost = findCost(menu.ranged, picks.ranged);
    const secondaryCost = findCost(menu.secondary, picks.secondary);
    const specialCost = findCost(menu.special, picks.special);
    if (
      packageCost == null ||
      meleeCost == null ||
      rangedCost == null ||
      secondaryCost == null ||
      specialCost == null
    ) {
      return null;
    }
    total += packageCost + meleeCost + rangedCost + secondaryCost + specialCost;
    return total;
  };
  const resolveDraftInvestedTotal = (
    draftProfiles: EndlessDutySlotProfiles,
    draftPicks: EndlessDutySlotPicks
  ): number | null => {
    const slotEntries: Array<keyof EndlessDutySlotProfiles> = ["leader", "melee", "range"];
    let total = 0;
    for (const slot of slotEntries) {
      const profile = draftProfiles[slot];
      if (profile == null) {
        continue;
      }
      const slotCost = resolveSlotCost(slot, profile, draftPicks[slot]);
      if (slotCost == null) {
        return null;
      }
      total += slotCost;
    }
    return total;
  };
  const projectedInvestedTotal = resolveDraftInvestedTotal(endlessDutyDraft, endlessDutyDraftPicks);
  const projectedAvailable =
    projectedInvestedTotal == null ? null : requisitionCapitalTotal - projectedInvestedTotal;
  const isProjectedDraftAffordable = projectedAvailable != null && projectedAvailable >= 0;
  const isOptionDraftAffordable = (
    slot: keyof EndlessDutySlotProfiles,
    profile: string | null,
    picks: EndlessDutyPickState | null
  ): boolean => {
    const candidateProfiles: EndlessDutySlotProfiles = {
      ...endlessDutyDraft,
      [slot]: profile,
    };
    const candidatePicks: EndlessDutySlotPicks = {
      ...endlessDutyDraftPicks,
      [slot]: picks,
    };
    const candidateInvested = resolveDraftInvestedTotal(candidateProfiles, candidatePicks);
    const candidateAvailable =
      candidateInvested == null ? null : requisitionCapitalTotal - candidateInvested;
    return candidateAvailable != null && candidateAvailable >= 0;
  };
  const getProfileLabel = (slot: keyof EndlessDutySlotProfiles, profile: string): string => {
    const defaultPicks = getDefaultPicksForProfile(slot, profile);
    const cost = resolveSlotCost(slot, profile, defaultPicks);
    if (typeof cost !== "number" || Number.isNaN(cost)) {
      return `${profile} (cout inconnu)`;
    }
    return `${profile} (a partir de ${cost})`;
  };
  const getPickMenuForSlot = (slot: keyof EndlessDutySlotProfiles): ProfilePickMenuData | null => {
    const profile = endlessDutyDraft[slot];
    if (!profile) {
      return null;
    }
    return endlessDutyPickMenus[slot].get(profile) ?? null;
  };

  return (
    <>
      <SharedLayout
        rightColumnContent={rightColumnContent}
        rightColumnScrollableContent={rightColumnScrollableContent}
        onOpenSettings={handleOpenSettings}
        onToggleMeasureMode={handleToggleMeasureMode}
        measureModeActive={measureModeActive}
        onToggleHideIndicators={handleToggleHideIndicators}
        hideIndicatorsActive={hideIndicators}
        onToggleRangeRings={handleToggleRangeRings}
        rangeRingsActive={showRangeRings}
        onToggleHelper={handleToggleHelper}
        helperActive={showHelper}
        onToggleReplay={
          isSnapshotMode && settings.replayContainerEnabled ? handleToggleReplay : undefined
        }
        replayActive={showReplay}
      >
        {/*
        In test deployment setup, lock gameplay interactions until Start Game! is clicked.
      */}
        <div
          className="board-column-overlay-anchor"
          style={snapshotViewActive ? { position: "relative", zIndex: 4000 } : undefined}
        >
          <BoardPvp
            units={apiProps.units}
            loadEpoch={loadEpoch}
            currentLevel={currentLevel}
            onCurrentLevelChange={setCurrentLevel}
            selectedUnitId={highlightedRuleChoiceUnitId ?? apiProps.selectedUnitId}
            ruleChoiceHighlightedUnitId={highlightedRuleChoiceUnitId}
            showHexCoordinates={settings.showDebug}
            showLosDebugOverlay={settings.showDebugLoS}
            onUnitIllustrationPreviewChange={setIllustrationPreviewUnitId}
            onUnitDisplaySelectChange={setDisplaySelectedUnitId}
            eligibleUnitIds={apiProps.eligibleUnitIds}
            phaseInitPending={apiProps.phaseInitPending}
            mode={apiProps.mode}
            movePreview={apiProps.movePreview}
            attackPreview={apiProps.attackPreview || null}
            wallHexesOverride={undefined}
            targetPreview={
              apiProps.targetPreview
                ? {
                    targetId: apiProps.targetPreview.targetId,
                    shooterId: apiProps.targetPreview.shooterId,
                    currentBlinkStep: (() => {
                      if (apiProps.targetPreview.currentBlinkStep == null)
                        throw new Error("targetPreview.currentBlinkStep absent");
                      return apiProps.targetPreview.currentBlinkStep;
                    })(),
                    totalBlinkSteps: (() => {
                      if (apiProps.targetPreview.totalBlinkSteps == null)
                        throw new Error("targetPreview.totalBlinkSteps absent");
                      return apiProps.targetPreview.totalBlinkSteps;
                    })(),
                    blinkTimer: apiProps.targetPreview.blinkTimer ?? null,
                    hitProbability: apiProps.targetPreview.hitProbability,
                    woundProbability: apiProps.targetPreview.woundProbability,
                    saveProbability: apiProps.targetPreview.saveProbability,
                    overallProbability: apiProps.targetPreview.overallProbability,
                  }
                : null
            }
            blinkingUnits={engineApiBlink.blinkingUnits}
            blinkingAttackerId={engineApiBlink.blinkingAttackerId}
            blinkingCoverByUnitId={engineApiBlink.blinkingCoverByUnitId}
            blinkingHiddenTooFarByUnitId={engineApiBlink.blinkingHiddenTooFarByUnitId}
            blinkingHiddenDetectionInfoByUnitId={engineApiBlink.blinkingHiddenDetectionInfoByUnitId}
            blinkingLosCountByUnitId={engineApiBlink.blinkingLosCountByUnitId}
            blinkingSquadAliveCount={engineApiBlink.blinkingSquadAliveCount}
            blinkingLosOverviewUnitId={engineApiBlink.blinkingLosOverviewUnitId}
            isBlinkingActive={engineApiBlink.isBlinkingActive}
            blinkVersion={engineApiBlink.blinkVersion}
            onSelectUnit={
              isGameOver ||
              (isRosterSetupMode &&
                apiProps.gameState?.phase === "deployment" &&
                apiProps.gameState?.deployment_type === "active" &&
                !testDeploymentStarted)
                ? () => {}
                : apiProps.onSelectUnit
            }
            battleShockTestMode={settings.battleShockTestEnabled && apiProps.battleShockTestMode}
            onForceBattleShock={apiProps.onForceBattleShock}
            chargedTestMode={settings.battleShockTestEnabled && apiProps.chargedTestMode}
            onForceCharged={apiProps.onForceCharged}
            onSkipUnit={isGameOver ? () => {} : apiProps.onSkipUnit}
            onStartMovePreview={isGameOver ? () => {} : apiProps.onStartMovePreview}
            onDirectMove={isGameOver ? () => {} : apiProps.onDirectMove}
            onBumpMovePreviewOrientation={
              isGameOver ? () => {} : apiProps.onBumpMovePreviewOrientation
            }
            onBumpPerModelOrientation={isGameOver ? () => {} : apiProps.onBumpPerModelOrientation}
            squadMovePlan={apiProps.squadMovePlan}
            fleePreviewUnitId={apiProps.fleePreviewUnitId}
            squadMoveModelPoolRef={apiProps.squadMoveModelPoolRef}
            squadMoveModelMaskLoopsRef={apiProps.squadMoveModelMaskLoopsRef}
            onStartSquadModelMove={isGameOver ? async () => {} : apiProps.onStartSquadModelMove}
            onSelectModelForMove={isGameOver ? async () => {} : apiProps.onSelectModelForMove}
            onReorientActiveModelPool={isGameOver ? () => {} : apiProps.onReorientActiveModelPool}
            onMoveModelInPlan={isGameOver ? () => {} : apiProps.onMoveModelInPlan}
            onResetModelInPlan={isGameOver ? () => {} : apiProps.onResetModelInPlan}
            onCommitSquadMovePlan={isGameOver ? async () => {} : apiProps.onCommitSquadMovePlan}
            onCancelSquadMove={isGameOver ? () => {} : apiProps.onCancelSquadMove}
            deployPlan={apiProps.deployPlan}
            deployPoolRef={apiProps.deployPoolRef}
            deployModelPoolRef={apiProps.deployModelPoolRef}
            deploySquadPoolRef={apiProps.deploySquadPoolRef}
            onDeployDropSquad={isGameOver ? async () => {} : apiProps.onDeployDropSquad}
            onSelectDeployModel={isGameOver ? () => {} : apiProps.onSelectDeployModel}
            onMoveDeployModelInPlan={isGameOver ? () => {} : apiProps.onMoveDeployModelInPlan}
            onSquadMoveDeploy={isGameOver ? () => {} : apiProps.onSquadMoveDeploy}
            onStartSquadFollowDeploy={isGameOver ? () => {} : apiProps.onStartSquadFollowDeploy}
            onFreezeSquadDeploy={isGameOver ? () => {} : apiProps.onFreezeSquadDeploy}
            chargeMovePlan={apiProps.chargeMovePlan}
            chargeModelPoolRef={apiProps.chargeModelPoolRef}
            chargeModelDistancesRef={apiProps.chargeModelDistancesRef}
            chargeModelMaskLoopsRef={apiProps.chargeModelMaskLoopsRef}
            onSelectChargeModel={isGameOver ? () => {} : apiProps.onSelectChargeModel}
            onMoveModelInChargePlan={isGameOver ? () => {} : apiProps.onMoveModelInChargePlan}
            onUnplaceChargeModel={isGameOver ? () => {} : apiProps.onUnplaceChargeModel}
            onCancelChargeModelMove={isGameOver ? async () => {} : apiProps.onCancelChargeModelMove}
            chargeFocusActive={apiProps.chargeFocusActive}
            onChargeFocusTargetClick={
              isGameOver ? async () => {} : apiProps.onChargeFocusTargetClick
            }
            pileInMovePlan={apiProps.pileInMovePlan}
            pileInFocusActive={apiProps.pileInFocusActive}
            pileInFocusTargetId={apiProps.pileInFocusTargetId}
            onPileInFocusTargetClick={
              isGameOver ? async () => {} : apiProps.onPileInFocusTargetClick
            }
            pileInModelPoolRef={apiProps.pileInModelPoolRef}
            pileInModelMaskLoopsRef={apiProps.pileInModelMaskLoopsRef}
            onSelectPileInModel={isGameOver ? () => {} : apiProps.onSelectPileInModel}
            onMovePileInModel={isGameOver ? () => {} : apiProps.onMovePileInModel}
            onUnplacePileInModel={isGameOver ? () => {} : apiProps.onUnplacePileInModel}
            onCancelPileInModelMove={isGameOver ? async () => {} : apiProps.onCancelPileInModelMove}
            consolidationMovePlan={apiProps.consolidationMovePlan}
            consolidationModelPoolRef={apiProps.consolidationModelPoolRef}
            consolidationModelMaskLoopsRef={apiProps.consolidationModelMaskLoopsRef}
            consolidationNewFoes={apiProps.consolidationNewFoes}
            onSelectConsolidationModel={isGameOver ? () => {} : apiProps.onSelectConsolidationModel}
            onMoveConsolidationModel={isGameOver ? () => {} : apiProps.onMoveConsolidationModel}
            onUnplaceConsolidationModel={
              isGameOver ? () => {} : apiProps.onUnplaceConsolidationModel
            }
            onCancelConsolidationModelMove={
              isGameOver ? async () => {} : apiProps.onCancelConsolidationModelMove
            }
            onConsolidationSelectTarget={
              isGameOver ? async () => {} : apiProps.onConsolidationSelectTarget
            }
            onConsolidationSelectObjective={
              isGameOver ? async () => {} : apiProps.onConsolidationSelectObjective
            }
            squadShootPlan={apiProps.squadShootPlan}
            onStartSquadModelShoot={isGameOver ? async () => {} : apiProps.onStartSquadModelShoot}
            onSelectModelForShoot={isGameOver ? async () => {} : apiProps.onSelectModelForShoot}
            onSquadShootLosOverview={isGameOver ? async () => {} : apiProps.onSquadShootLosOverview}
            onAssignShootTarget={isGameOver ? async () => {} : apiProps.onAssignShootTarget}
            onAutoAssignAllModels={isGameOver ? async () => {} : apiProps.onAutoAssignAllModels}
            onUnassignShootModel={isGameOver ? async () => {} : apiProps.onUnassignShootModel}
            onUnassignShootWeapon={isGameOver ? async () => {} : apiProps.onUnassignShootWeapon}
            onCommitSquadShoot={isGameOver ? async () => {} : apiProps.onCommitSquadShoot}
            onCancelSquadShoot={isGameOver ? async () => {} : apiProps.onCancelSquadShoot}
            squadFightPlan={apiProps.squadFightPlan}
            onSelectModelForFight={isGameOver ? () => {} : apiProps.onSelectModelForFight}
            onAssignFightTarget={isGameOver ? async () => {} : apiProps.onAssignFightTarget}
            onAssignFightWeapon={isGameOver ? async () => {} : apiProps.onAssignFightWeapon}
            onCommitSquadFight={isGameOver ? async () => {} : apiProps.onCommitSquadFight}
            onCancelSquadFight={isGameOver ? async () => {} : apiProps.onCancelSquadFight}
            onReportFightAssignable={apiProps.onReportFightAssignable}
            manualAllocation={apiProps.manualAllocation}
            onAllocateModel={isGameOver ? async () => {} : apiProps.onAllocateModel}
            onStartAttackPreview={isGameOver ? () => {} : apiProps.onStartAttackPreview}
            onDeployUnit={
              isGameOver ||
              (isRosterSetupMode &&
                apiProps.gameState?.phase === "deployment" &&
                apiProps.gameState?.deployment_type === "active" &&
                !testDeploymentStarted)
                ? () => {}
                : apiProps.onDeployUnit
            }
            onConfirmMove={isGameOver ? () => {} : apiProps.onConfirmMove}
            onCancelMove={isGameOver ? () => {} : apiProps.onCancelMove}
            onShoot={isGameOver ? () => {} : apiProps.onShoot}
            onSkipShoot={isGameOver ? () => {} : apiProps.onSkipShoot}
            onSkipFight={
              isGameOver
                ? () => {}
                : (unitId: string | number) => {
                    const id = typeof unitId === "string" ? parseInt(unitId, 10) : unitId;
                    void apiProps.onFightPhaseRightClick?.(id);
                  }
            }
            onStartTargetPreview={isGameOver ? () => {} : apiProps.onStartTargetPreview}
            onCancelTargetPreview={() => {
              const targetPreview = apiProps.targetPreview as TargetPreview | null;
              if (targetPreview?.blinkTimer) {
                clearInterval(targetPreview.blinkTimer);
              }
              // Clear target preview in engine API
            }}
            onFightAttack={isGameOver ? () => {} : apiProps.onFightAttack}
            onPileInMove={isGameOver ? () => {} : apiProps.onPileInMove}
            onSkipPileIn={isGameOver ? () => {} : apiProps.onSkipPileIn}
            current_player={apiProps.current_player as PlayerId}
            unitsMoved={apiProps.unitsMoved}
            unitsCharged={apiProps.unitsCharged}
            unitsAttacked={apiProps.unitsAttacked}
            unitsFled={apiProps.unitsFled}
            phase={apiProps.phase as "deployment" | "move" | "shoot" | "charge" | "fight"}
            fightSubPhase={apiProps.fightSubPhase}
            onCharge={isGameOver ? () => {} : apiProps.onCharge}
            onActivateCharge={isGameOver ? () => {} : apiProps.onActivateCharge}
            onChargeEnemyUnit={isGameOver ? () => {} : apiProps.onChargeEnemyUnit}
            onMoveCharger={isGameOver ? () => {} : apiProps.onMoveCharger}
            onCancelCharge={isGameOver ? () => {} : apiProps.onCancelCharge}
            onValidateCharge={isGameOver ? () => {} : apiProps.onValidateCharge}
            onLogChargeRoll={isGameOver ? () => {} : apiProps.onLogChargeRoll}
            chargingUnitId={apiProps.chargingUnitId}
            chargeTargetId={apiProps.chargeTargetId ?? null}
            chargePreviewTargetIds={apiProps.chargePreviewTargetIds}
            chargeRoll={apiProps.chargeRoll}
            chargeSuccess={apiProps.chargeSuccess}
            gameState={apiProps.gameState as GameState}
            getChargeDestinations={apiProps.getChargeDestinations}
            chargePreviewOverlayHexes={apiProps.chargePreviewOverlayHexes ?? []}
            chargeReferenceHex={apiProps.chargeReferenceHex ?? null}
            moveDestPoolRef={apiProps.moveDestPoolRef}
            pendingMoveAfterShooting={apiProps.pendingMoveAfterShooting ?? false}
            activationPendingUnitId={apiProps.activationPendingUnitId ?? null}
            footprintZoneRef={apiProps.footprintZoneRef}
            footprintMaskLoopsRef={apiProps.footprintMaskLoopsRef}
            chargeDestPoolRef={apiProps.chargeDestPoolRef}
            chargeDestDistancesRef={apiProps.chargeDestDistancesRef}
            chargeFootprintZoneRef={apiProps.chargeFootprintZoneRef}
            chargePreviewDisplayMaskLoopsRef={apiProps.chargePreviewDisplayMaskLoopsRef}
            onAdvance={isGameOver ? () => {} : apiProps.onAdvance}
            onAdvanceMove={isGameOver ? () => {} : apiProps.onAdvanceMove}
            onCancelAdvance={isGameOver ? () => {} : apiProps.onCancelAdvance}
            getAdvanceDestinations={apiProps.getAdvanceDestinations}
            availableCellsOverride={apiProps.availableCellsOverride}
            advanceRoll={apiProps.advanceRoll}
            advancingUnitId={apiProps.advancingUnitId}
            advanceWarningPopup={apiProps.advanceWarningPopup}
            onConfirmAdvanceWarning={isGameOver ? () => {} : apiProps.onConfirmAdvanceWarning}
            onCancelAdvanceWarning={isGameOver ? () => {} : apiProps.onCancelAdvanceWarning}
            onSkipAdvanceWarning={isGameOver ? () => {} : apiProps.onSkipAdvanceWarning}
            showAdvanceWarningPopup={false}
            autoSelectWeapon={settings.autoSelectWeapon}
            hpBarPerModel={settings.hpBarPerModel}
            hpBarBlinkEnlarged={settings.hpBarBlinkEnlarged}
            showWoundProbability={settings.showWoundProbability}
            statusBadgePerModel={settings.statusBadgePerModel}
            dynamicCoverStatus={settings.dynamicCoverStatus}
            boardDisplayMode={settings.boardDisplayMode}
            deploymentState={apiProps.gameState?.deployment_state as DeploymentState | undefined}
            objectivesOverride={objectivesOverride}
            measureMode={measureMode}
            onMeasureHexCommit={handleMeasureHexCommit}
            onMeasureJunctionCommit={handleMeasureJunctionCommit}
            hideIndicators={hideIndicators}
            showRangeRings={showRangeRings}
          />
          {isRosterSetupMode &&
            apiProps.gameState?.phase === "deployment" &&
            apiProps.gameState?.deployment_type === "active" &&
            !testDeploymentStarted && (
              <div className="test-start-overlay">
                <div className="test-start-modal">
                  <button
                    type="button"
                    className="test-start-bar__button"
                    onClick={() => {
                      closeRosterPicker();
                      setTestDeploymentStarted(true);
                    }}
                  >
                    Start Deployment
                  </button>
                </div>
              </div>
            )}
        </div>
      </SharedLayout>
      {isEndlessDutyInterWave && isEndlessDutyModalOpen && (
        // biome-ignore lint/a11y/noStaticElementInteractions: backdrop modal — stopPropagation intentionnel
        <div
          role="presentation"
          style={{
            position: "fixed",
            inset: 0,
            backgroundColor: "rgba(0, 0, 0, 0.72)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 12000,
          }}
          onClick={(event) => event.stopPropagation()}
          onKeyDown={(event) => event.stopPropagation()}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="endless-duty-title"
            style={{
              width: "min(720px, calc(100vw - 32px))",
              backgroundColor: "#0b1322",
              border: "2px solid var(--ui-green-border)",
              borderRadius: "10px",
              boxShadow: "0 14px 40px rgba(0,0,0,0.55)",
              padding: "22px 24px 18px 24px",
              color: "#dbeafe",
            }}
            onClick={(event) => event.stopPropagation()}
            onKeyDown={(event) => event.stopPropagation()}
          >
            <h2
              id="endless-duty-title"
              style={{ margin: "0 0 8px 0", color: "#bfdbfe", fontSize: "28px" }}
            >
              Endless Duty - Requisition
            </h2>
            <p style={{ margin: "0 0 12px 0", lineHeight: 1.5, fontSize: "16px" }}>
              Wave {currentWave} cleared. Configurez votre escouade avant la prochaine vague.
            </p>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 1fr 1fr",
                gap: "10px",
                marginBottom: "14px",
              }}
            >
              <div
                style={{
                  background: "rgba(15, 23, 42, 0.8)",
                  border: "1px solid #334155",
                  borderRadius: "6px",
                  padding: "8px 10px",
                }}
              >
                <div style={{ fontSize: "12px", color: "#94a3b8" }}>Capital total</div>
                <div style={{ fontSize: "18px", fontWeight: 700 }}>
                  {endlessDutyState?.requisition_capital_total ?? 0}
                </div>
              </div>
              <div
                style={{
                  background: "rgba(15, 23, 42, 0.8)",
                  border: "1px solid #334155",
                  borderRadius: "6px",
                  padding: "8px 10px",
                }}
              >
                <div style={{ fontSize: "12px", color: "#94a3b8" }}>Investi</div>
                <div style={{ fontSize: "18px", fontWeight: 700 }}>
                  {endlessDutyState?.requisition_invested_total ?? 0}
                </div>
              </div>
              <div
                style={{
                  background: "rgba(15, 23, 42, 0.8)",
                  border: "1px solid #334155",
                  borderRadius: "6px",
                  padding: "8px 10px",
                }}
              >
                <div style={{ fontSize: "12px", color: "#94a3b8" }}>Disponible</div>
                <div style={{ fontSize: "18px", fontWeight: 700 }}>
                  {endlessDutyState?.requisition_available ?? 0}
                </div>
              </div>
            </div>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 1fr",
                gap: "10px",
                marginBottom: "14px",
              }}
            >
              <div
                style={{
                  background: "rgba(15, 23, 42, 0.8)",
                  border: "1px solid #334155",
                  borderRadius: "6px",
                  padding: "8px 10px",
                }}
              >
                <div style={{ fontSize: "12px", color: "#94a3b8" }}>Investi projete</div>
                <div style={{ fontSize: "18px", fontWeight: 700 }}>
                  {projectedInvestedTotal == null ? "-" : projectedInvestedTotal}
                </div>
              </div>
              <div
                style={{
                  background: "rgba(15, 23, 42, 0.8)",
                  border: "1px solid #334155",
                  borderRadius: "6px",
                  padding: "8px 10px",
                }}
              >
                <div style={{ fontSize: "12px", color: "#94a3b8" }}>Disponible projete</div>
                <div
                  style={{
                    fontSize: "18px",
                    fontWeight: 700,
                    color: isProjectedDraftAffordable ? "#86efac" : "#fca5a5",
                  }}
                >
                  {projectedAvailable == null ? "-" : projectedAvailable}
                </div>
              </div>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: "10px" }}>
              <label style={{ display: "grid", gap: "6px" }}>
                <span style={{ fontWeight: 600 }}>
                  Leader (deverrouille wave {endlessDutyUnlockRules.leader})
                </span>
                <select
                  value={endlessDutyDraft.leader ?? ""}
                  disabled={!slotUnlockStatus.leader || isSubmittingEndlessDuty}
                  onChange={(event) =>
                    handleEndlessDutyDraftChange(
                      "leader",
                      event.target.value === "" ? null : event.target.value
                    )
                  }
                  style={{
                    padding: "8px 10px",
                    borderRadius: "6px",
                    border: "1px solid #475569",
                    background: "#0f172a",
                    color: "#e2e8f0",
                  }}
                >
                  <option value="" disabled>
                    Choisir un leader (obligatoire)
                  </option>
                  {endlessDutyProfileOptions.leader.map((profile) => (
                    <option
                      key={`ed-leader-${profile}`}
                      value={profile}
                      disabled={
                        !isOptionDraftAffordable(
                          "leader",
                          profile,
                          getDefaultPicksForProfile("leader", profile)
                        )
                      }
                    >
                      {getProfileLabel("leader", profile)}
                    </option>
                  ))}
                </select>
                {(() => {
                  const menu = getPickMenuForSlot("leader");
                  const picks = endlessDutyDraftPicks.leader;
                  const hasPackage = picks?.package != null;
                  if (!menu || !picks) {
                    return null;
                  }
                  return (
                    <>
                      <select
                        value={picks.package ?? picks.melee ?? ""}
                        disabled={
                          !slotUnlockStatus.leader ||
                          isSubmittingEndlessDuty ||
                          !endlessDutyDraft.leader
                        }
                        onChange={(event) => {
                          const value = event.target.value === "" ? null : event.target.value;
                          if (value && menu.primaryPackages.some((opt) => opt.id === value)) {
                            handleEndlessDutyPickChange("leader", "package", value);
                            handleEndlessDutyPickChange("leader", "melee", null);
                          } else {
                            handleEndlessDutyPickChange("leader", "package", null);
                            handleEndlessDutyPickChange("leader", "melee", value);
                          }
                        }}
                        style={{
                          padding: "8px 10px",
                          borderRadius: "6px",
                          border: "1px solid #475569",
                          background: "#0f172a",
                          color: "#e2e8f0",
                        }}
                      >
                        <option value="">Arme principale (melee ou pack)</option>
                        {menu.primaryPackages.map((option) => (
                          <option key={`ed-leader-package-${option.id}`} value={option.id}>
                            [PACK] {option.label}
                          </option>
                        ))}
                        {menu.primaryMelee.map((option) => (
                          <option key={`ed-leader-melee-${option.id}`} value={option.id}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                      <select
                        value={picks.ranged ?? ""}
                        disabled={
                          !slotUnlockStatus.leader ||
                          isSubmittingEndlessDuty ||
                          !endlessDutyDraft.leader ||
                          hasPackage
                        }
                        onChange={(event) =>
                          handleEndlessDutyPickChange(
                            "leader",
                            "ranged",
                            event.target.value === "" ? null : event.target.value
                          )
                        }
                        style={{
                          padding: "8px 10px",
                          borderRadius: "6px",
                          border: "1px solid #475569",
                          background: "#0f172a",
                          color: "#e2e8f0",
                        }}
                      >
                        <option value="">Arme a distance</option>
                        {menu.ranged.map((option) => (
                          <option key={`ed-leader-ranged-${option.id}`} value={option.id}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                      <select
                        value={picks.secondary ?? ""}
                        disabled={
                          !slotUnlockStatus.leader ||
                          isSubmittingEndlessDuty ||
                          !endlessDutyDraft.leader ||
                          hasPackage
                        }
                        onChange={(event) =>
                          handleEndlessDutyPickChange(
                            "leader",
                            "secondary",
                            event.target.value === "" ? null : event.target.value
                          )
                        }
                        style={{
                          padding: "8px 10px",
                          borderRadius: "6px",
                          border: "1px solid #475569",
                          background: "#0f172a",
                          color: "#e2e8f0",
                        }}
                      >
                        <option value="">Secondaire</option>
                        {menu.secondary.map((option) => (
                          <option key={`ed-leader-secondary-${option.id}`} value={option.id}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                      <select
                        value={picks.special ?? ""}
                        disabled={
                          !slotUnlockStatus.leader ||
                          isSubmittingEndlessDuty ||
                          !endlessDutyDraft.leader ||
                          hasPackage
                        }
                        onChange={(event) =>
                          handleEndlessDutyPickChange(
                            "leader",
                            "special",
                            event.target.value === "" ? null : event.target.value
                          )
                        }
                        style={{
                          padding: "8px 10px",
                          borderRadius: "6px",
                          border: "1px solid #475569",
                          background: "#0f172a",
                          color: "#e2e8f0",
                        }}
                      >
                        <option value="">Special (equipement/special)</option>
                        {menu.special.map((option) => (
                          <option key={`ed-leader-special-${option.id}`} value={option.id}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                    </>
                  );
                })()}
              </label>
              <label style={{ display: "grid", gap: "6px" }}>
                <span style={{ fontWeight: 600 }}>
                  Melee (deverrouille wave {endlessDutyUnlockRules.melee})
                </span>
                <select
                  value={endlessDutyDraft.melee ?? ""}
                  disabled={!slotUnlockStatus.melee || isSubmittingEndlessDuty}
                  onChange={(event) =>
                    handleEndlessDutyDraftChange(
                      "melee",
                      event.target.value === "" ? null : event.target.value
                    )
                  }
                  style={{
                    padding: "8px 10px",
                    borderRadius: "6px",
                    border: "1px solid #475569",
                    background: "#0f172a",
                    color: "#e2e8f0",
                  }}
                >
                  <option value="">Aucun</option>
                  {endlessDutyProfileOptions.melee.map((profile) => (
                    <option
                      key={`ed-melee-${profile}`}
                      value={profile}
                      disabled={
                        !isOptionDraftAffordable(
                          "melee",
                          profile,
                          getDefaultPicksForProfile("melee", profile)
                        )
                      }
                    >
                      {getProfileLabel("melee", profile)}
                    </option>
                  ))}
                </select>
                {(() => {
                  const menu = getPickMenuForSlot("melee");
                  const picks = endlessDutyDraftPicks.melee;
                  const hasPackage = picks?.package != null;
                  if (!menu || !picks) {
                    return null;
                  }
                  return (
                    <>
                      <select
                        value={picks.package ?? picks.melee ?? ""}
                        disabled={
                          !slotUnlockStatus.melee ||
                          isSubmittingEndlessDuty ||
                          !endlessDutyDraft.melee
                        }
                        onChange={(event) => {
                          const value = event.target.value === "" ? null : event.target.value;
                          if (value && menu.primaryPackages.some((opt) => opt.id === value)) {
                            handleEndlessDutyPickChange("melee", "package", value);
                            handleEndlessDutyPickChange("melee", "melee", null);
                          } else {
                            handleEndlessDutyPickChange("melee", "package", null);
                            handleEndlessDutyPickChange("melee", "melee", value);
                          }
                        }}
                        style={{
                          padding: "8px 10px",
                          borderRadius: "6px",
                          border: "1px solid #475569",
                          background: "#0f172a",
                          color: "#e2e8f0",
                        }}
                      >
                        <option value="">Arme principale (melee ou pack)</option>
                        {menu.primaryPackages.map((option) => (
                          <option key={`ed-melee-package-${option.id}`} value={option.id}>
                            [PACK] {option.label}
                          </option>
                        ))}
                        {menu.primaryMelee.map((option) => (
                          <option key={`ed-melee-melee-${option.id}`} value={option.id}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                      <select
                        value={picks.ranged ?? ""}
                        disabled={
                          !slotUnlockStatus.melee ||
                          isSubmittingEndlessDuty ||
                          !endlessDutyDraft.melee ||
                          hasPackage
                        }
                        onChange={(event) =>
                          handleEndlessDutyPickChange(
                            "melee",
                            "ranged",
                            event.target.value === "" ? null : event.target.value
                          )
                        }
                        style={{
                          padding: "8px 10px",
                          borderRadius: "6px",
                          border: "1px solid #475569",
                          background: "#0f172a",
                          color: "#e2e8f0",
                        }}
                      >
                        <option value="">Arme a distance</option>
                        {menu.ranged.map((option) => (
                          <option key={`ed-melee-ranged-${option.id}`} value={option.id}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                      <select
                        value={picks.secondary ?? ""}
                        disabled={
                          !slotUnlockStatus.melee ||
                          isSubmittingEndlessDuty ||
                          !endlessDutyDraft.melee ||
                          hasPackage
                        }
                        onChange={(event) =>
                          handleEndlessDutyPickChange(
                            "melee",
                            "secondary",
                            event.target.value === "" ? null : event.target.value
                          )
                        }
                        style={{
                          padding: "8px 10px",
                          borderRadius: "6px",
                          border: "1px solid #475569",
                          background: "#0f172a",
                          color: "#e2e8f0",
                        }}
                      >
                        <option value="">Secondaire</option>
                        {menu.secondary.map((option) => (
                          <option key={`ed-melee-secondary-${option.id}`} value={option.id}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                      <select
                        value={picks.special ?? ""}
                        disabled={
                          !slotUnlockStatus.melee ||
                          isSubmittingEndlessDuty ||
                          !endlessDutyDraft.melee ||
                          hasPackage
                        }
                        onChange={(event) =>
                          handleEndlessDutyPickChange(
                            "melee",
                            "special",
                            event.target.value === "" ? null : event.target.value
                          )
                        }
                        style={{
                          padding: "8px 10px",
                          borderRadius: "6px",
                          border: "1px solid #475569",
                          background: "#0f172a",
                          color: "#e2e8f0",
                        }}
                      >
                        <option value="">Special (equipement/special)</option>
                        {menu.special.map((option) => (
                          <option key={`ed-melee-special-${option.id}`} value={option.id}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                    </>
                  );
                })()}
              </label>
              <label style={{ display: "grid", gap: "6px" }}>
                <span style={{ fontWeight: 600 }}>
                  Range (deverrouille wave {endlessDutyUnlockRules.range})
                </span>
                <select
                  value={endlessDutyDraft.range ?? ""}
                  disabled={!slotUnlockStatus.range || isSubmittingEndlessDuty}
                  onChange={(event) =>
                    handleEndlessDutyDraftChange(
                      "range",
                      event.target.value === "" ? null : event.target.value
                    )
                  }
                  style={{
                    padding: "8px 10px",
                    borderRadius: "6px",
                    border: "1px solid #475569",
                    background: "#0f172a",
                    color: "#e2e8f0",
                  }}
                >
                  <option value="">Aucun</option>
                  {endlessDutyProfileOptions.range.map((profile) => (
                    <option
                      key={`ed-range-${profile}`}
                      value={profile}
                      disabled={
                        !isOptionDraftAffordable(
                          "range",
                          profile,
                          getDefaultPicksForProfile("range", profile)
                        )
                      }
                    >
                      {getProfileLabel("range", profile)}
                    </option>
                  ))}
                </select>
                {(() => {
                  const menu = getPickMenuForSlot("range");
                  const picks = endlessDutyDraftPicks.range;
                  const hasPackage = picks?.package != null;
                  if (!menu || !picks) {
                    return null;
                  }
                  return (
                    <>
                      <select
                        value={picks.package ?? picks.melee ?? ""}
                        disabled={
                          !slotUnlockStatus.range ||
                          isSubmittingEndlessDuty ||
                          !endlessDutyDraft.range
                        }
                        onChange={(event) => {
                          const value = event.target.value === "" ? null : event.target.value;
                          if (value && menu.primaryPackages.some((opt) => opt.id === value)) {
                            handleEndlessDutyPickChange("range", "package", value);
                            handleEndlessDutyPickChange("range", "melee", null);
                          } else {
                            handleEndlessDutyPickChange("range", "package", null);
                            handleEndlessDutyPickChange("range", "melee", value);
                          }
                        }}
                        style={{
                          padding: "8px 10px",
                          borderRadius: "6px",
                          border: "1px solid #475569",
                          background: "#0f172a",
                          color: "#e2e8f0",
                        }}
                      >
                        <option value="">Arme principale (melee ou pack)</option>
                        {menu.primaryPackages.map((option) => (
                          <option key={`ed-range-package-${option.id}`} value={option.id}>
                            [PACK] {option.label}
                          </option>
                        ))}
                        {menu.primaryMelee.map((option) => (
                          <option key={`ed-range-melee-${option.id}`} value={option.id}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                      <select
                        value={picks.ranged ?? ""}
                        disabled={
                          !slotUnlockStatus.range ||
                          isSubmittingEndlessDuty ||
                          !endlessDutyDraft.range ||
                          hasPackage
                        }
                        onChange={(event) =>
                          handleEndlessDutyPickChange(
                            "range",
                            "ranged",
                            event.target.value === "" ? null : event.target.value
                          )
                        }
                        style={{
                          padding: "8px 10px",
                          borderRadius: "6px",
                          border: "1px solid #475569",
                          background: "#0f172a",
                          color: "#e2e8f0",
                        }}
                      >
                        <option value="">Arme a distance</option>
                        {menu.ranged.map((option) => (
                          <option key={`ed-range-ranged-${option.id}`} value={option.id}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                      <select
                        value={picks.secondary ?? ""}
                        disabled={
                          !slotUnlockStatus.range ||
                          isSubmittingEndlessDuty ||
                          !endlessDutyDraft.range ||
                          hasPackage
                        }
                        onChange={(event) =>
                          handleEndlessDutyPickChange(
                            "range",
                            "secondary",
                            event.target.value === "" ? null : event.target.value
                          )
                        }
                        style={{
                          padding: "8px 10px",
                          borderRadius: "6px",
                          border: "1px solid #475569",
                          background: "#0f172a",
                          color: "#e2e8f0",
                        }}
                      >
                        <option value="">Secondaire</option>
                        {menu.secondary.map((option) => (
                          <option key={`ed-range-secondary-${option.id}`} value={option.id}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                      <select
                        value={picks.special ?? ""}
                        disabled={
                          !slotUnlockStatus.range ||
                          isSubmittingEndlessDuty ||
                          !endlessDutyDraft.range ||
                          hasPackage
                        }
                        onChange={(event) =>
                          handleEndlessDutyPickChange(
                            "range",
                            "special",
                            event.target.value === "" ? null : event.target.value
                          )
                        }
                        style={{
                          padding: "8px 10px",
                          borderRadius: "6px",
                          border: "1px solid #475569",
                          background: "#0f172a",
                          color: "#e2e8f0",
                        }}
                      >
                        <option value="">Special (equipement/special)</option>
                        {menu.special.map((option) => (
                          <option key={`ed-range-special-${option.id}`} value={option.id}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                    </>
                  );
                })()}
              </label>
            </div>
            {!isProjectedDraftAffordable && (
              <div
                style={{
                  marginTop: "12px",
                  padding: "8px 10px",
                  borderRadius: "6px",
                  border: "1px solid #f59e0b",
                  color: "#fde68a",
                  background: "rgba(120, 53, 15, 0.35)",
                  fontSize: "14px",
                }}
              >
                Selection invalide: requisition insuffisante pour ce draft.
              </div>
            )}
            {endlessDutyFormError && (
              <div
                style={{
                  marginTop: "12px",
                  padding: "8px 10px",
                  borderRadius: "6px",
                  border: "1px solid #f87171",
                  color: "#fecaca",
                  background: "rgba(127, 29, 29, 0.35)",
                  fontSize: "14px",
                }}
              >
                {endlessDutyFormError}
              </div>
            )}
            <div
              style={{
                marginTop: "16px",
                display: "flex",
                justifyContent: "flex-end",
                gap: "10px",
              }}
            >
              <button
                type="button"
                onClick={() => {
                  void apiProps.fetchEndlessDutyStatus().catch(() => {});
                }}
                disabled={isSubmittingEndlessDuty}
                style={{
                  padding: "10px 14px",
                  border: "1px solid #64748b",
                  borderRadius: "6px",
                  background: "rgba(30, 41, 59, 0.9)",
                  color: "#e2e8f0",
                  cursor: isSubmittingEndlessDuty ? "not-allowed" : "pointer",
                }}
              >
                Refresh
              </button>
              <button
                type="button"
                onClick={() => {
                  void handleEndlessDutyCommit();
                }}
                disabled={isSubmittingEndlessDuty || !isProjectedDraftAffordable}
                style={{
                  padding: "10px 14px",
                  border: "1px solid rgba(0,0,0,0.35)",
                  borderRadius: "6px",
                  background:
                    isSubmittingEndlessDuty || !isProjectedDraftAffordable
                      ? "var(--ui-green-validate-off)"
                      : "var(--ui-green-validate)",
                  color:
                    isSubmittingEndlessDuty || !isProjectedDraftAffordable
                      ? "rgba(229,231,235,0.5)"
                      : "#fff",
                  cursor:
                    isSubmittingEndlessDuty || !isProjectedDraftAffordable
                      ? "not-allowed"
                      : "pointer",
                  fontWeight: 600,
                }}
              >
                {isSubmittingEndlessDuty ? "Validation..." : "Valider et lancer vague suivante"}
              </button>
            </div>
          </div>
        </div>
      )}
      {apiProps.advanceWarningPopup && settings.showAdvanceWarning && (
        // biome-ignore lint/a11y/noStaticElementInteractions: backdrop modal — stopPropagation intentionnel
        <div
          role="presentation"
          style={{
            position: "fixed",
            inset: 0,
            backgroundColor: "rgba(0, 0, 0, 0.72)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 12000,
          }}
          onClick={() => {
            if (advanceWarningDontRemind) {
              handleToggleAdvanceWarning(false);
            }
            void apiProps.onCancelAdvanceWarning();
          }}
          onKeyDown={() => {
            if (advanceWarningDontRemind) {
              handleToggleAdvanceWarning(false);
            }
            void apiProps.onCancelAdvanceWarning();
          }}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="advance-warning-title"
            style={{
              width: "min(640px, calc(100vw - 32px))",
              backgroundColor: "#06120a",
              border: "2px solid #22c55e",
              borderRadius: "10px",
              boxShadow: "0 14px 40px rgba(0,0,0,0.55)",
              padding: "22px 24px 18px 24px",
              color: "#e5fbe9",
            }}
            onClick={(event) => event.stopPropagation()}
            onKeyDown={(event) => event.stopPropagation()}
          >
            <h2
              id="advance-warning-title"
              style={{ margin: "0 0 12px 0", color: "#86efac", fontSize: "30px" }}
            >
              Advance !
            </h2>
            <p style={{ margin: 0, lineHeight: 1.5, fontSize: "19px" }}>
              Vous êtes sur le point d&apos;effectuer une action Advance. Si vous la validez, cette
              unité ne pourra ni tirer ni charger jusqu&apos;à la fin de ce tour.
            </p>
            <div
              style={{
                marginTop: "20px",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "end",
              }}
            >
              <label
                style={{ display: "flex", alignItems: "center", gap: "10px", cursor: "pointer" }}
              >
                <input
                  type="checkbox"
                  checked={advanceWarningDontRemind}
                  onChange={(event) => setAdvanceWarningDontRemind(event.target.checked)}
                  style={{ width: "18px", height: "18px", cursor: "pointer" }}
                />
                <span style={{ fontSize: "16px", color: "#d1fae5" }}>Ne plus me rappeler</span>
              </label>
              <div style={{ display: "flex", gap: "10px" }}>
                <button
                  type="button"
                  onClick={() => {
                    if (advanceWarningDontRemind) {
                      handleToggleAdvanceWarning(false);
                    }
                    void apiProps.onCancelAdvanceWarning();
                  }}
                  style={{
                    padding: "10px 14px",
                    border: "1px solid #9ca3af",
                    borderRadius: "6px",
                    background: "rgba(31, 41, 55, 0.9)",
                    color: "#f3f4f6",
                    cursor: "pointer",
                    fontSize: "16px",
                  }}
                >
                  Annuler l&apos;advance
                </button>
                <button
                  type="button"
                  onClick={() => {
                    if (advanceWarningDontRemind) {
                      handleToggleAdvanceWarning(false);
                    }
                    void apiProps.onConfirmAdvanceWarning();
                  }}
                  style={{
                    padding: "10px 14px",
                    border: "1px solid #22c55e",
                    borderRadius: "6px",
                    background: "#065f46",
                    color: "#ecfdf5",
                    cursor: "pointer",
                    fontSize: "16px",
                    fontWeight: 600,
                  }}
                >
                  Valider
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
      {apiProps.fleeWarningPopup && (
        // biome-ignore lint/a11y/noStaticElementInteractions: backdrop modal — stopPropagation intentionnel
        <div
          role="presentation"
          style={{
            position: "fixed",
            inset: 0,
            backgroundColor: "rgba(0, 0, 0, 0.72)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 12000,
          }}
          onClick={() => {
            if (apiProps.fleeWarningPopup?.dontRemind) {
              updateRetreatAlertSetting(false);
            }
            void apiProps.onCancelFleeWarning();
          }}
          onKeyDown={() => {
            if (apiProps.fleeWarningPopup?.dontRemind) {
              updateRetreatAlertSetting(false);
            }
            void apiProps.onCancelFleeWarning();
          }}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="retreat-warning-title"
            style={{
              width: "min(640px, calc(100vw - 32px))",
              backgroundColor: "#06120a",
              border: "2px solid #22c55e",
              borderRadius: "10px",
              boxShadow: "0 14px 40px rgba(0,0,0,0.55)",
              padding: "22px 24px 18px 24px",
              color: "#e5fbe9",
            }}
            onClick={(event) => event.stopPropagation()}
            onKeyDown={(event) => event.stopPropagation()}
          >
            <h2
              id="retreat-warning-title"
              style={{ margin: "0 0 12px 0", color: "#86efac", fontSize: "30px" }}
            >
              Retraite !
            </h2>
            <p style={{ margin: 0, lineHeight: 1.5, fontSize: "19px" }}>
              Vous êtes sur le point d'effectuer un mouvement de Retraite. Si vous le validez, cette
              unité ne pourra ni tirer ni charger jusqu&apos; à la fin de ce tour.
            </p>
            <div
              style={{
                marginTop: "20px",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "end",
              }}
            >
              <label
                style={{ display: "flex", alignItems: "center", gap: "10px", cursor: "pointer" }}
              >
                <input
                  type="checkbox"
                  checked={apiProps.fleeWarningPopup.dontRemind}
                  onChange={(event) => apiProps.onToggleFleeWarningDontRemind(event.target.checked)}
                  style={{ width: "18px", height: "18px", cursor: "pointer" }}
                />
                <span style={{ fontSize: "16px", color: "#d1fae5" }}>Ne plus me rappeler</span>
              </label>
              <div style={{ display: "flex", gap: "10px" }}>
                <button
                  type="button"
                  onClick={() => {
                    if (apiProps.fleeWarningPopup?.dontRemind) {
                      updateRetreatAlertSetting(false);
                    }
                    void apiProps.onCancelFleeWarning();
                  }}
                  style={{
                    padding: "10px 14px",
                    border: "1px solid #9ca3af",
                    borderRadius: "6px",
                    background: "rgba(31, 41, 55, 0.9)",
                    color: "#f3f4f6",
                    cursor: "pointer",
                    fontSize: "16px",
                  }}
                >
                  Annuler la retraite
                </button>
                <button
                  type="button"
                  onClick={() => {
                    if (apiProps.fleeWarningPopup?.dontRemind) {
                      updateRetreatAlertSetting(false);
                    }
                    void apiProps.onConfirmFleeWarning();
                  }}
                  style={{
                    padding: "10px 14px",
                    border: "1px solid #22c55e",
                    borderRadius: "6px",
                    background: "#065f46",
                    color: "#ecfdf5",
                    cursor: "pointer",
                    fontSize: "16px",
                    fontWeight: 600,
                  }}
                >
                  Valider
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
      {apiProps.hazardWarningPopup && (
        // biome-ignore lint/a11y/noStaticElementInteractions: backdrop modal — stopPropagation intentionnel
        <div
          role="presentation"
          style={{
            position: "fixed",
            inset: 0,
            backgroundColor: "rgba(0, 0, 0, 0.72)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 12000,
          }}
          onClick={() => {
            // Ignore le 2e clic d'un double-clic d'activation (fenêtre courte après ouverture).
            if (performance.now() - hazardPopupOpenedAtRef.current < 400) return;
            apiProps.onCancelHazardWarning();
          }}
          onKeyDown={() => apiProps.onCancelHazardWarning()}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="hazard-warning-title"
            style={{
              width: "min(420px, calc(100vw - 32px))",
              background: "rgba(20, 20, 20, 0.98)",
              border: "2px solid #4caf50",
              borderRadius: "6px",
              boxShadow: "0 4px 12px rgba(0, 0, 0, 0.5)",
              padding: "16px 18px 14px 18px",
              color: "#fff",
            }}
            onClick={(event) => event.stopPropagation()}
            onKeyDown={(event) => event.stopPropagation()}
          >
            <h2
              id="hazard-warning-title"
              style={{
                margin: "0 0 16px 0",
                color: "#a5d6a7",
                background: "#0b410d",
                fontSize: "16px",
                fontWeight: 700,
                textTransform: "uppercase",
                letterSpacing: "0.5px",
                padding: "6px 10px",
                borderRadius: "4px",
              }}
            >
              ☢️ Desperate Escape !
            </h2>
            <p style={{ margin: 0, lineHeight: 1.5, fontSize: "14px", color: "#c8e6cf" }}>
              Le mouvement Desperate Escape que cette unité va effectuer entraine des{" "}
              <TooltipWrapper text="Roll D6 per model: on a 1-2, that unit suffers 1 (or 3 if it is a MONSTER/VEHICLE) mortal wounds.">
                <span
                  style={{
                    color: "#fde68a",
                    fontWeight: 700,
                    textDecoration: "underline",
                    cursor: "help",
                  }}
                >
                  HAZARD ROLLS
                </span>
              </TooltipWrapper>
              . Continuer ?
            </p>
            <div
              style={{
                marginTop: "20px",
                display: "flex",
                justifyContent: "flex-end",
                gap: "10px",
              }}
            >
              <button
                type="button"
                onClick={() => apiProps.onCancelHazardWarning()}
                style={{
                  padding: "10px 14px",
                  border: "1px solid #41506b",
                  borderRadius: "6px",
                  background: "#0c3d14",
                  color: "#e6e9f0",
                  cursor: "pointer",
                  fontSize: "14px",
                }}
              >
                Annuler
              </button>
              <button
                type="button"
                onClick={() => void apiProps.onConfirmHazardWarning()}
                style={{
                  padding: "10px 14px",
                  border: "1px solid #4caf50",
                  borderRadius: "6px",
                  background: "#1b7a2b",
                  color: "#eafff0",
                  cursor: "pointer",
                  fontSize: "14px",
                  fontWeight: 700,
                }}
              >
                Confirmer
              </button>
            </div>
          </div>
        </div>
      )}
      <SettingsMenu
        isOpen={isSettingsOpen}
        onClose={() => setIsSettingsOpen(false)}
        onLogout={() => {
          clearAuthSession();
          window.location.href = "/auth";
        }}
        showAdvanceWarning={settings.showAdvanceWarning}
        canToggleAdvanceWarning={canUseAdvanceWarning}
        onToggleAdvanceWarning={handleToggleAdvanceWarning}
        showDebug={settings.showDebug}
        onToggleDebug={handleToggleDebug}
        showDebugLoS={settings.showDebugLoS}
        onToggleDebugLoS={handleToggleDebugLoS}
        shootPoolFastMode={settings.shootPoolFastMode}
        onToggleShootPoolFastMode={handleToggleShootPoolFastMode}
        autoSelectWeapon={settings.autoSelectWeapon}
        canToggleAutoSelectWeapon={canUseAutoWeaponSelection}
        onToggleAutoSelectWeapon={handleToggleAutoSelectWeapon}
        hpBarPerModel={settings.hpBarPerModel}
        onToggleHpBarPerModel={handleToggleHpBarPerModel}
        hpBarBlinkEnlarged={settings.hpBarBlinkEnlarged}
        onToggleHpBarBlinkEnlarged={handleToggleHpBarBlinkEnlarged}
        showWoundProbability={settings.showWoundProbability}
        onToggleShowWoundProbability={handleToggleShowWoundProbability}
        boardDisplayMode={settings.boardDisplayMode}
        onSetBoardDisplayMode={handleSetBoardDisplayMode}
        statusBadgePerModel={settings.statusBadgePerModel}
        onToggleStatusBadgePerModel={handleToggleStatusBadgePerModel}
        dynamicCoverStatus={settings.dynamicCoverStatus}
        onToggleDynamicCoverStatus={handleToggleDynamicCoverStatus}
        snapshotPersistEnabled={snapshotPersistEnabled}
        snapshotPersistDir={snapshotPersistDir}
        onPickDirectory={isSnapshotMode ? apiProps.pickDirectory : undefined}
        onToggleSnapshotPersist={
          isSnapshotMode
            ? (v: boolean, directory?: string) => {
                setSnapshotPersistEnabled(v);
                localStorage.setItem("snapshotPersistEnabled", JSON.stringify(v));
                if (directory) {
                  setSnapshotPersistDir(directory);
                  localStorage.setItem("snapshotPersistDir", directory);
                  setSaveDirSelected(true);
                  localStorage.setItem("saveDirSelected", "true");
                }
                apiProps
                  .snapshotSetPersist(v, directory)
                  .catch(() => setSnapshotPersistEnabled(!v));
              }
            : undefined
        }
        retreatAlertEnabled={settings.retreatAlertEnabled}
        onToggleRetreatAlert={handleToggleRetreatAlert}
        battleShockTestEnabled={settings.battleShockTestEnabled}
        onToggleBattleShockTest={handleToggleBattleShockTest}
        deployIconBaseSizeBounded={settings.deployIconBaseSizeBounded}
        onToggleDeployIconBaseSizeBounded={handleToggleDeployIconBaseSizeBounded}
        logShowCoords={settings.logShowCoords}
        onToggleLogShowCoords={handleToggleLogShowCoords}
        logShowType={settings.logShowType}
        onToggleLogShowType={handleToggleLogShowType}
        replayContainerEnabled={settings.replayContainerEnabled}
        onToggleReplayContainer={handleToggleReplayContainer}
        autoSaveEnabled={settings.autoSaveEnabled}
        onToggleAutoSave={handleToggleAutoSave}
        autoSaveGranularity={settings.autoSaveGranularity}
        onSetAutoSaveGranularity={handleSetAutoSaveGranularity}
        onDeleteSaves={handleDeleteSaves}
      />
    </>
  );
};
