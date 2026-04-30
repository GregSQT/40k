/**
 * Mutualise la classification des clics d’activation (tir / CC) pour aligner
 * le front sur les payloads ``left_click`` / ``right_click`` du moteur.
 */

export type ActivationPointerPhase = "shoot" | "fight";

/** Sous-ensemble de ``game_state`` API utilisé pour classify les clics. */
export interface ActivationPointerGameState {
  current_player: number;
  phase?: string;
  units: Array<{ id: string | number; player: number; ATTACK_LEFT?: number }>;
  active_shooting_unit?: string | null;
  active_fight_unit?: string | null;
  shoot_activation_pool?: string[];
  fight_subphase?: string | null;
  charging_activation_pool?: string[];
  active_alternating_activation_pool?: string[];
  non_active_alternating_activation_pool?: string[];
}

/** Pool d’activation CC courant (même logique que ``getEligibleUnitIds`` / phase fight). */
export function getFightActivationPoolUnitIds(gs: ActivationPointerGameState): number[] {
  if (gs.phase !== "fight") {
    return [];
  }
  const subphase = gs.fight_subphase;
  const parsePool = (pool: string[] | undefined): number[] => {
    if (!pool?.length) return [];
    return pool.map((id) => parseInt(id, 10)).filter((id) => !Number.isNaN(id));
  };
  if (subphase === "charging") {
    return parsePool(gs.charging_activation_pool);
  }
  if (subphase === "alternating_non_active" || subphase === "cleanup_non_active") {
    return parsePool(gs.non_active_alternating_activation_pool);
  }
  if (subphase === "alternating_active" || subphase === "cleanup_active") {
    return parsePool(gs.active_alternating_activation_pool);
  }
  return [];
}

/**
 * ``clickTarget`` attendu par le moteur : ``enemy`` (shoot) vs ``target`` (fight CC).
 */
export function determineActivationClickTarget(
  phase: ActivationPointerPhase,
  unitId: number,
  gameState: ActivationPointerGameState
): string {
  const unit = gameState.units.find((u) => parseInt(String(u.id), 10) === unitId);
  if (!unit) {
    return "elsewhere";
  }

  const currentPlayer = gameState.current_player;

  if (phase === "shoot") {
    const activeShooterId = gameState.active_shooting_unit
      ? parseInt(String(gameState.active_shooting_unit), 10)
      : null;
    if (unit.player === currentPlayer) {
      if (unitId === activeShooterId) {
        return "active_unit";
      }
      const shootPool = gameState.shoot_activation_pool || [];
      const unitIdStr = unitId.toString();
      if (shootPool.includes(unitIdStr)) {
        return "friendly_unit";
      }
      return "friendly";
    }
    return "enemy";
  }

  // fight — ennemi / allié relatif au **combattant actif**, pas au ``current_player`` (propriétaire du tour).
  // Sinon, en alternance (ex. P2 actif alors que ``current_player`` vaut 1), un clic sur une unité P1
  // est classé « friendly » au lieu de « target » et le moteur ne résout pas l’attaque CC.
  let activeFighterId: number | null = null;
  if (gameState.active_fight_unit != null && String(gameState.active_fight_unit).trim() !== "") {
    const parsed = parseInt(String(gameState.active_fight_unit), 10);
    if (Number.isFinite(parsed)) {
      activeFighterId = parsed;
    }
  }

  const poolIds = getFightActivationPoolUnitIds(gameState);
  if (poolIds.includes(unitId)) {
    return "friendly_unit";
  }

  if (activeFighterId != null && unitId === activeFighterId) {
    return "active_unit";
  }

  const attackerUnit =
    activeFighterId != null
      ? gameState.units.find((u) => parseInt(String(u.id), 10) === activeFighterId)
      : undefined;
  if (attackerUnit != null && unit.player !== attackerUnit.player) {
    return "target";
  }

  if (unit.player === currentPlayer) {
    return "friendly";
  }
  return "target";
}

export function buildActivationPointerPayload(
  phase: ActivationPointerPhase,
  clickedUnitId: number,
  clickType: "left" | "right",
  gs: ActivationPointerGameState,
  selectedUnitId: number | null
): Record<string, unknown> {
  const clickTarget = determineActivationClickTarget(phase, clickedUnitId, gs);
  const activeStr =
    phase === "shoot"
      ? gs.active_shooting_unit || (selectedUnitId != null ? String(selectedUnitId) : "")
      : gs.active_fight_unit || (selectedUnitId != null ? String(selectedUnitId) : "");
  return {
    action: clickType === "left" ? "left_click" : "right_click",
    unitId: activeStr || (selectedUnitId != null ? String(selectedUnitId) : ""),
    targetId: String(clickedUnitId),
    clickTarget,
  };
}

/** UI plateau : sélection de cible CC (mode et/ou surbrillance d’attaque). */
export function isFightAttackSelectionUiOpen(
  mode: string,
  attackPreview: { unitId: number; col: number; row: number } | null | undefined
): boolean {
  return mode === "attackPreview" || attackPreview != null;
}

/**
 * Première valeur d’``active_fight_unit`` utilisable (ignore ``""`` / absent).
 * Important : ``""`` n’est pas nullish pour ``??`` — sans ce repli, un merge API
 * partiel peut masquer l’ID encore présent dans l’état React et bloquer les clics.
 */
function pickNonEmptyActiveFightId(
  a: string | null | undefined,
  b: string | null | undefined
): string | null {
  const norm = (v: string | null | undefined): string | null => {
    if (v == null) return null;
    const s = String(v).trim();
    return s === "" ? null : s;
  };
  return norm(a) ?? norm(b) ?? null;
}

/**
 * ``active_fight_unit`` : préfère l’état ``preferred`` (ex. ref post-merge), puis ``base`` (ex. React).
 */
export function getActiveFightUnitIdString(
  preferred: ActivationPointerGameState | null | undefined,
  base: ActivationPointerGameState
): string | null {
  return pickNonEmptyActiveFightId(preferred?.active_fight_unit, base.active_fight_unit);
}

/** ``ATTACK_LEFT`` moteur pour l’unité indiquée (undefined si inconnu). */
export function getFightAttackerAttackLeft(
  gs: ActivationPointerGameState,
  attackerUnitId: number
): number | undefined {
  const u = gs.units?.find((x) => parseInt(String(x.id), 10) === attackerUnitId);
  if (u == null || typeof u.ATTACK_LEFT !== "number") {
    return undefined;
  }
  return u.ATTACK_LEFT;
}
