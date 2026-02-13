// frontend/src/hooks/useGameActions.ts - AI_TURN.md Compliant Version
import { useCallback } from "react";
import type {
  AttackPreview,
  FightSubPhase,
  GameState,
  MovePreview,
  PlayerId,
  ShootingPhaseState,
  TargetPreview,
  Unit,
  UnitId,
} from "../types/game";
import { cubeDistance, offsetToCube } from "../utils/gameHelpers";

type BoardConfig = Record<string, unknown> | null | undefined;
type GameLog = Record<string, unknown> | null | undefined;

interface UseGameActionsParams {
  gameState: GameState;
  movePreview: MovePreview | null;
  attackPreview: AttackPreview | null;
  shootingPhaseState: ShootingPhaseState;
  boardConfig?: BoardConfig;
  gameLog?: GameLog;
  actions: {
    setMode: (mode: GameState["mode"]) => void;
    setSelectedUnitId: (id: UnitId | null) => void;
    setMovePreview: (preview: MovePreview | null) => void;
    setAttackPreview: (preview: AttackPreview | null) => void;
    addMovedUnit: (unitId: UnitId) => void;
    addChargedUnit: (unitId: UnitId) => void;
    addAttackedUnit: (unitId: UnitId) => void;
    addFledUnit: (unitId: UnitId) => void;
    updateUnit: (unitId: UnitId, updates: Partial<Unit>) => void;
    removeUnit: (unitId: UnitId) => void;
    initializeShootingPhase: () => void;
    updateShootingPhaseState: (updates: Partial<ShootingPhaseState>) => void;
    decrementShotsLeft: (unitId: UnitId) => void;
    setTargetPreview: (preview: TargetPreview | null) => void;
    setFightSubPhase?: (subPhase: FightSubPhase) => void;
    setFightActivePlayer?: (player: PlayerId) => void;
    setUnitChargeRoll?: (unitId: UnitId, roll: number) => void;
    resetUnitChargeRoll?: (unitId: UnitId) => void;
    showChargeRollPopup?: (unitId: UnitId, roll: number, tooLow: boolean) => void;
    resetChargeRolls?: () => void;
  };
}

export const useGameActions = ({
  gameState,
  movePreview,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  attackPreview: _attackPreview,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  shootingPhaseState: _shootingPhaseState,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  boardConfig: _boardConfig,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  gameLog: _gameLog,
  actions,
}: UseGameActionsParams) => {
  // Single source of truth eligibility function
  const isUnitEligible = useCallback(
    (unit: Unit): boolean => {
      const {
        phase,
        current_player,
        unitsMoved = [],
        unitsCharged = [],
        unitsAttacked = [],
        unitsFled = [],
      } = gameState;

      // Universal eligibility checks
      if ((unit.HP_CUR ?? unit.HP_MAX) <= 0) return false;
      if (unit.player !== current_player) return false;

      switch (phase) {
        case "move":
          return !unitsMoved.includes(unit.id);
        case "shoot": {
          // Check basic eligibility first
          if (unitsMoved.includes(unit.id) || unitsFled.includes(unit.id)) return false;

          // Units adjacent to enemies (melee range = 1) cannot shoot
          // This matches backend logic in shooting_handlers.py _has_valid_shooting_targets
          const hasAdjacentEnemy = gameState.units.some(
            (enemy) =>
              enemy.player !== unit.player &&
              (enemy.HP_CUR ?? enemy.HP_MAX) > 0 &&
              cubeDistance(offsetToCube(unit.col, unit.row), offsetToCube(enemy.col, enemy.row)) <=
                1
          );

          return !hasAdjacentEnemy;
        }
        case "charge":
          return !unitsCharged.includes(unit.id) && !unitsFled.includes(unit.id);
        case "fight":
          return !unitsAttacked.includes(unit.id);
        default:
          return false;
      }
    },
    [gameState]
  );

  // Simple unit selection with step counting
  const selectUnit = useCallback(
    (unitId: UnitId | null) => {
      if (unitId === null) {
        actions.setSelectedUnitId(null);
        actions.setMode("select");
        return;
      }

      const unit = gameState.units.find((u) => u.id === unitId);

      // Player validation with fight phase exception
      // Fight phase alternating allows non-active player units to be selected
      const isFightPhaseAlternating =
        gameState.phase === "fight" &&
        (gameState.fight_subphase === "alternating_non_active" ||
          gameState.fight_subphase === "alternating_active" ||
          gameState.fight_subphase === "cleanup_non_active" ||
          gameState.fight_subphase === "cleanup_active");

      const playerCheck = isFightPhaseAlternating
        ? true
        : unit?.player === gameState.current_player;

      if (!unit || !playerCheck || !isUnitEligible(unit)) {
        console.log(
          `[AI_TURN.md] Blocked selection of unit ${unitId}: player=${unit?.player}, current_player=${gameState.current_player}, eligible=${unit ? isUnitEligible(unit) : false}, fight_subphase=${gameState.fight_subphase}`
        );
        return;
      }

      actions.setSelectedUnitId(unitId);
      actions.setMode("select");
    },
    [gameState, isUnitEligible, actions]
  );

  // Simple move with step counting
  const directMove = useCallback(
    (unitId: UnitId, col: number, row: number) => {
      const unit = gameState.units.find((u) => u.id === unitId);
      if (!unit || !isUnitEligible(unit) || gameState.phase !== "move") return;

      actions.updateUnit(unitId, { col, row });
      actions.addMovedUnit(unitId);
      actions.setSelectedUnitId(null);
      actions.setMode("select");
    },
    [gameState, isUnitEligible, actions]
  );

  // Movement preview
  const startMovePreview = useCallback(
    (unitId: UnitId, col: number, row: number) => {
      const unit = gameState.units.find((u) => u.id === unitId);
      if (!unit || !isUnitEligible(unit)) return;

      actions.setMovePreview({ unitId, destCol: col, destRow: row });
      actions.setMode("movePreview");
    },
    [gameState, isUnitEligible, actions]
  );

  const confirmMove = useCallback(() => {
    let movedUnitId: UnitId | null = null;

    if (gameState.mode === "movePreview" && movePreview) {
      const unit = gameState.units.find((u) => u.id === movePreview.unitId);
      if (unit && gameState.phase === "move") {
        // Check for flee detection
        const enemyUnits = gameState.units.filter((u) => u.player !== unit.player);
        const wasAdjacentToEnemy = enemyUnits.some(
          (enemy) =>
            cubeDistance(offsetToCube(unit.col, unit.row), offsetToCube(enemy.col, enemy.row)) === 1
        );

        if (wasAdjacentToEnemy) {
          const willBeAdjacentToEnemy = enemyUnits.some(
            (enemy) =>
              cubeDistance(
                offsetToCube(movePreview.destCol, movePreview.destRow),
                offsetToCube(enemy.col, enemy.row)
              ) === 1
          );

          if (!willBeAdjacentToEnemy) {
            actions.addFledUnit(movePreview.unitId);
          }
        }
      }

      actions.updateUnit(movePreview.unitId, {
        col: movePreview.destCol,
        row: movePreview.destRow,
      });
      movedUnitId = movePreview.unitId;
    }

    if (movedUnitId !== null) {
      actions.addMovedUnit(movedUnitId);
    }

    actions.setMovePreview(null);
    actions.setAttackPreview(null);
    actions.setSelectedUnitId(null);
    actions.setMode("select");
  }, [gameState, movePreview, actions]);

  const cancelMove = useCallback(() => {
    actions.setMovePreview(null);
    actions.setAttackPreview(null);
    actions.setMode("select");
  }, [actions]);

  // Placeholder implementations for other actions
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const handleShoot = useCallback((_shooterId: UnitId, _targetId: UnitId) => {
    // AI_TURN.md compliant shooting implementation
  }, []);

  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const handleFightAttack = useCallback((_attackerId: UnitId, _targetId: UnitId | null) => {
    // AI_TURN.md compliant fight implementation
  }, []);

  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const handleCharge = useCallback((_chargerId: UnitId, _targetId: UnitId) => {
    // AI_TURN.md compliant charge implementation
  }, []);

  const startAttackPreview = useCallback(
    (unitId: UnitId, col: number, row: number) => {
      actions.setAttackPreview({ unitId, col, row });
      actions.setMode("attackPreview");
    },
    [actions]
  );

  // Stub implementations for missing functions
  const handleActivateCharge = useCallback(() => {
    console.log("⚠️ handleActivateCharge called in PvP mode - this should use backend API instead");
  }, []);
  const moveCharger = useCallback(() => {}, []);
  const cancelCharge = useCallback(() => {}, []);
  const validateCharge = useCallback(() => {}, []);
  const getChargeDestinations = useCallback(() => [], []);

  return {
    selectUnit,
    directMove,
    startMovePreview,
    startAttackPreview,
    confirmMove,
    cancelMove,
    handleShoot,
    handleFightAttack,
    handleCharge,
    handleActivateCharge,
    moveCharger,
    cancelCharge,
    validateCharge,
    isUnitEligible,
    getChargeDestinations,
  };
};
