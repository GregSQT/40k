// frontend/src/components/BoardWithAPI.tsx
import type React from "react";
import { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import "../App.css";
import { clearAuthSession, getAuthSession } from "../auth/authStorage";
import { useEngineAPI } from "../hooks/useEngineAPI";
import { useGameConfig } from "../hooks/useGameConfig";
import { useGameLog } from "../hooks/useGameLog";
import type { GamePhase, GameState, PlayerId, TargetPreview, Unit } from "../types";
import type { DeploymentState } from "../types/game";
import BoardPvp from "./BoardPvp";
import { ErrorBoundary } from "./ErrorBoundary";
import { GameLog } from "./GameLog";
import { SettingsMenu } from "./SettingsMenu";
import SharedLayout from "./SharedLayout";
import { TurnPhaseTracker } from "./TurnPhaseTracker";
import { UnitStatusTable } from "./UnitStatusTable";

export const BoardWithAPI: React.FC = () => {
  const authSession = getAuthSession();
  if (!authSession) {
    throw new Error("Session utilisateur introuvable dans BoardWithAPI");
  }

  const canUseAdvanceWarning = authSession.permissions.options.show_advance_warning;
  const canUseAutoWeaponSelection = authSession.permissions.options.auto_weapon_selection;

  const apiProps = useEngineAPI();
  const gameLog = useGameLog(apiProps.gameState?.currentTurn ?? 1);

  // Detect game mode from URL
  const location = useLocation();
  const gameMode = location.pathname.includes("/replay")
    ? "training"
    : location.pathname === "/game" && location.search.includes("mode=debug")
      ? "debug"
      : location.pathname === "/game" && location.search.includes("mode=test")
        ? "test"
        : location.pathname === "/game" && location.search.includes("mode=pve")
          ? "pve"
          : "pvp";
  const isAiMode = (() => {
    const playerTypes = apiProps.gameState?.player_types;
    if (!playerTypes) {
      return false;
    }
    return Object.values(playerTypes).some((playerType) => playerType === "ai");
  })();
  const victoryPoints = apiProps.gameState?.victory_points;
  const objectivesOverride = (() => {
    const objectives = apiProps.gameState?.objectives as
      | Array<{ name: string; hexes: Array<{ col: number; row: number } | [number, number]> }>
      | undefined;
    if (!objectives) {
      return undefined;
    }
    return objectives.map((objective) => {
      if (!objective || !objective.name) {
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
  const { gameConfig } = useGameConfig();

  // Track clicked (but not selected) units for blue highlighting
  const [clickedUnitId, setClickedUnitId] = useState<number | null>(null);

  // Track UnitStatusTable collapse states
  const [_player1Collapsed, setPlayer1Collapsed] = useState(false);
  const [_player2Collapsed, setPlayer2Collapsed] = useState(false);
  const [deploymentRosterCollapsed, setDeploymentRosterCollapsed] = useState<Record<PlayerId, boolean>>({
    1: false,
    2: false,
  });
  const [deploymentTooltip, setDeploymentTooltip] = useState<{
    visible: boolean;
    text: string;
    x: number;
    y: number;
  } | null>(null);

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

  // Settings menu state
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const handleOpenSettings = () => setIsSettingsOpen(true);

  // Settings preferences (from localStorage)
  const [settings, setSettings] = useState(() => {
    const showAdvanceWarningStr = localStorage.getItem("showAdvanceWarning");
    const showDebugStr = localStorage.getItem("showDebug");
    const autoSelectWeaponStr = localStorage.getItem("autoSelectWeapon");
    return {
      showAdvanceWarning:
        canUseAdvanceWarning && (showAdvanceWarningStr ? JSON.parse(showAdvanceWarningStr) : true),
      showDebug: showDebugStr ? JSON.parse(showDebugStr) : false,
      autoSelectWeapon:
        canUseAutoWeaponSelection && (autoSelectWeaponStr ? JSON.parse(autoSelectWeaponStr) : true),
    };
  });

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

  const handleToggleAutoSelectWeapon = (value: boolean) => {
    if (!canUseAutoWeaponSelection) {
      return;
    }
    setSettings((prev) => ({ ...prev, autoSelectWeapon: value }));
    localStorage.setItem("autoSelectWeapon", JSON.stringify(value));
  };

  // Calculate available height for GameLog dynamically
  const [logAvailableHeight, setLogAvailableHeight] = useState(220);

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
        return !!unit && isAiUnit(unit) && (unit.HP_CUR ?? unit.HP_MAX) > 0;
      });

    const isAiEnabled = isAiMode;

    // Check if game is over by examining unit health
    const player1Alive = apiProps.gameState.units.some(
      (u) => u.player === 1 && (u.HP_CUR ?? u.HP_MAX) > 0
    );
    const player2Alive = apiProps.gameState.units.some(
      (u) => u.player === 2 && (u.HP_CUR ?? u.HP_MAX) > 0
    );
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
        hasEligibleAIUnits = hasAiUnitsInPool(apiProps.gameState.move_activation_pool, apiProps.gameState);
      }
    } else if (currentPhase === "shoot") {
      hasEligibleAIUnits = apiProps.gameState.shoot_activation_pool
        ? hasAiUnitsInPool(apiProps.gameState.shoot_activation_pool, apiProps.gameState)
        : false;
    } else if (currentPhase === "charge") {
      // Charge phase: Check charge activation pool for AI eligibility
      if (apiProps.gameState.charge_activation_pool) {
        hasEligibleAIUnits = hasAiUnitsInPool(apiProps.gameState.charge_activation_pool, apiProps.gameState);
      }
    } else if (currentPhase === "fight") {
      // Fight phase: Check fight subphase pools for AI eligibility
      // Try both apiProps.fightSubPhase and apiProps.gameState.fight_subphase
      const fightSubphase = apiProps.fightSubPhase || apiProps.gameState?.fight_subphase;

      let fightPool: string[] = [];
      if (fightSubphase === "charging" && apiProps.gameState.charging_activation_pool) {
        fightPool = apiProps.gameState.charging_activation_pool;
      } else if (
        fightSubphase === "alternating_non_active" &&
        apiProps.gameState.non_active_alternating_activation_pool
      ) {
        fightPool = apiProps.gameState.non_active_alternating_activation_pool;
      } else if (
        fightSubphase === "alternating_active" &&
        apiProps.gameState.active_alternating_activation_pool
      ) {
        fightPool = apiProps.gameState.active_alternating_activation_pool;
      } else if (
        fightSubphase === "cleanup_non_active" &&
        apiProps.gameState.non_active_alternating_activation_pool
      ) {
        fightPool = apiProps.gameState.non_active_alternating_activation_pool;
      } else if (
        fightSubphase === "cleanup_active" &&
        apiProps.gameState.active_alternating_activation_pool
      ) {
        fightPool = apiProps.gameState.active_alternating_activation_pool;
      }

      hasEligibleAIUnits = hasAiUnitsInPool(fightPool, apiProps.gameState);
    }

    const current_player = apiProps.gameState?.current_player;
    if (current_player === undefined || current_player === null) {
      throw new Error("Missing current_player in gameState");
    }
    const isAITurn =
      currentPhase === "fight"
        ? hasEligibleAIUnits
        : getPlayerType(current_player) === "ai";

    // Removed duplicate log - now handled below with change detection

    const fightSubphaseForKey = apiProps.fightSubPhase || apiProps.gameState?.fight_subphase || "";
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
            const latestFightSubphase = apiProps.fightSubPhase || latestState.fight_subphase;
            let latestFightPool: string[] = [];
            if (latestFightSubphase === "charging" && latestState.charging_activation_pool) {
              latestFightPool = latestState.charging_activation_pool;
            } else if (
              latestFightSubphase === "alternating_non_active" &&
              latestState.non_active_alternating_activation_pool
            ) {
              latestFightPool = latestState.non_active_alternating_activation_pool;
            } else if (
              latestFightSubphase === "alternating_active" &&
              latestState.active_alternating_activation_pool
            ) {
              latestFightPool = latestState.active_alternating_activation_pool;
            } else if (
              latestFightSubphase === "cleanup_non_active" &&
              latestState.non_active_alternating_activation_pool
            ) {
              latestFightPool = latestState.non_active_alternating_activation_pool;
            } else if (
              latestFightSubphase === "cleanup_active" &&
              latestState.active_alternating_activation_pool
            ) {
              latestFightPool = latestState.active_alternating_activation_pool;
            }
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
    } else if (isAiEnabled && !shouldTriggerAI && hasChanged) {
      // Only log when values change, and only in debug scenarios
      // Suppress the "NOT triggered" warning to reduce console noise
      // Uncomment below if you need to debug AI triggering issues
      // console.log(`⚠️ [BOARD_WITH_API] AI turn NOT triggered. Reasons:`, {
      //   isPvEMode,
      //   isAITurn,
      //   isAIProcessing: isAIProcessingRef.current,
      //   gameNotOver,
      //   hasEligibleAIUnits,
      //   lastProcessedTurn,
      //   turnKey,
      //   turnKeyMatches: lastProcessedTurn === turnKey
      // });
    }
  }, [isAiMode, apiProps, lastProcessedTurn]);

  // Update lastProcessedTurn when phase/turn changes (to track phase transitions)
  useEffect(() => {
    if (!apiProps.gameState) return;
    const fightSubphaseForKey = apiProps.fightSubPhase || apiProps.gameState?.fight_subphase || "";
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

  // Calculate available height for GameLog dynamically
  useEffect(() => {
    // Wait for DOM to be fully rendered before measuring
    setTimeout(() => {
      const turnPhaseTracker = document.querySelector(".turn-phase-tracker-right");
      const allTables = document.querySelectorAll(".unit-status-table-container");
      const gameLogHeader =
        document.querySelector(".game-log__header") ||
        document.querySelector('[class*="game-log"]');

      if (!turnPhaseTracker || allTables.length < 2 || !gameLogHeader) {
        setLogAvailableHeight(220);
        return;
      }

      const player1Table = allTables[0];
      const player2Table = allTables[1];

      // Get actual heights from DOM measurements
      const turnPhaseHeight = turnPhaseTracker.getBoundingClientRect().height;
      const player1Height = player1Table.getBoundingClientRect().height;
      const player2Height = player2Table.getBoundingClientRect().height;
      const gameLogHeaderHeight = gameLogHeader.getBoundingClientRect().height;

      // Calculate available space based purely on actual measurements
      const viewportHeight = window.innerHeight;
      const appContainer = document.querySelector(".app-container") || document.body;
      const appMargins = viewportHeight - appContainer.getBoundingClientRect().height;
      const usedSpace = turnPhaseHeight + player1Height + player2Height + gameLogHeaderHeight;
      const availableForLogEntries = viewportHeight - usedSpace - appMargins;

      const sampleLogEntry = document.querySelector(".game-log-entry");
      if (!sampleLogEntry) {
        setLogAvailableHeight(220);
        return;
      }
      setLogAvailableHeight(availableForLogEntries);
    }, 100); // Wait 100ms for DOM to render
  }, []);

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

    return (
      <div className="deployment-panel deployment-panel--dual">
        {players.map((player) => {
          const deployableIdsRaw = deploymentState.deployable_units?.[String(player)] || [];
          const deployableUnits = deployableIdsRaw
            .map((id) => apiProps.gameState!.units.find((u) => String(u.id) === String(id)))
            .filter((u): u is Unit => Boolean(u));
          const getDeploymentGroupKey = (unit: Unit): string => {
            const displayName = unit.DISPLAY_NAME || unit.name || unit.type || unit.unitType;
            if (!displayName) {
              throw new Error(`Deployment unit ${unit.id} missing display name`);
            }
            const marker = " (";
            const markerIndex = displayName.indexOf(marker);
            if (markerIndex > 0 && displayName.endsWith(")")) {
              return displayName.slice(0, markerIndex).trim();
            }
            return displayName.trim();
          };
          const deployableByType: Record<string, Unit[]> = {};
          deployableUnits.forEach((unit) => {
            const typeKey = getDeploymentGroupKey(unit);
            if (!deployableByType[typeKey]) {
              deployableByType[typeKey] = [];
            }
            deployableByType[typeKey].push(unit);
          });
          Object.values(deployableByType).forEach((unitsOfType) => {
            unitsOfType.sort((a, b) => {
              if (typeof a.VALUE !== "number" || typeof b.VALUE !== "number") {
                throw new Error(
                  `Deployment sorting requires numeric VALUE (units ${a.id}=${String(a.VALUE)}, ${b.id}=${String(b.VALUE)})`
                );
              }
              if (b.VALUE !== a.VALUE) {
                return b.VALUE - a.VALUE;
              }
              const aName = a.DISPLAY_NAME || a.name || a.type || a.unitType || "";
              const bName = b.DISPLAY_NAME || b.name || b.type || b.unitType || "";
              return aName.localeCompare(bName);
            });
          });
          const isCurrentDeployer = player === currentDeployer;
          const isCollapsed = deploymentRosterCollapsed[player];

          return (
            <div key={`deployment-roster-${player}`} className="deployment-panel__roster">
              <div
                className={`deployment-panel__player-banner ${
                  player === 2
                    ? "deployment-panel__player-banner--player2"
                    : "deployment-panel__player-banner--player1"
                }`}
                style={{ display: "flex", alignItems: "center", justifyContent: "flex-start", gap: "8px" }}
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
                  aria-label={isCollapsed ? `Etendre roster player ${player}` : `Reduire roster player ${player}`}
                >
                  {isCollapsed ? "+" : "−"}
                </button>
                <span>
                  Player {player} - Deployment {isCurrentDeployer ? "(Active)" : "(Waiting)"}
                </span>
              </div>

              {!isCollapsed && (
                <div className="deployment-panel__type-list">
                  {Object.keys(deployableByType).length === 0 && (
                    <div className="deployment-panel__empty">Aucune unite deployable restante</div>
                  )}
                  {Object.entries(deployableByType).map(([typeKey, unitsOfType]) => (
                    <div
                      key={`deploy-type-${player}-${typeKey}`}
                      className={`deployment-panel__type-group deployment-panel__type-group--player${player}`}
                    >
                      <div className="deployment-panel__type-label">{typeKey} :</div>
                      <div className="deployment-panel__type-icons">
                        {unitsOfType.map((unit) => {
                          const isSelected = apiProps.selectedUnitId === unit.id;
                          const displayName = unit.DISPLAY_NAME || unit.name || typeKey;
                          const tooltipText = `${displayName} - ID ${unit.id}${isCurrentDeployer ? "" : " (inactive this turn)"}`;
                          return (
                            <button
                              type="button"
                              className="deployment-panel__unit-icon"
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
                                if (!isCurrentDeployer) {
                                  return;
                                }
                                apiProps.onSelectUnit(unit.id);
                                setClickedUnitId(null);
                              }}
                              disabled={!isCurrentDeployer}
                              style={{
                                width: "42px",
                                height: "42px",
                                borderRadius: "6px",
                                border: isSelected
                                  ? "2px solid #7CFF7C"
                                  : `1px solid ${getIconBorderColor(player)}`,
                                background: isSelected ? "rgba(124, 255, 124, 0.2)" : "rgba(0, 0, 0, 0.35)",
                                color: "white",
                                cursor: isCurrentDeployer ? "pointer" : "not-allowed",
                                opacity: isCurrentDeployer ? 1 : 0.55,
                                padding: "0",
                                display: "flex",
                                alignItems: "center",
                                justifyContent: "center",
                                overflow: "hidden",
                                position: "relative",
                              }}
                            >
                              <img
                                src={unit.ICON}
                                alt={displayName}
                                style={{
                                  width: "100%",
                                  height: "100%",
                                  objectFit: "contain",
                                  pointerEvents: "none",
                                }}
                              />
                              <span
                                style={{
                                  position: "absolute",
                                  right: "2px",
                                  bottom: "1px",
                                  fontSize: "9px",
                                  lineHeight: "1",
                                  background: "rgba(0, 0, 0, 0.65)",
                                  padding: "1px 2px",
                                  borderRadius: "3px",
                                }}
                              >
                                {unit.id}
                              </span>
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    );
  })();

  const rightColumnContent = (
    <>
      {gameConfig ? (
        <div className="turn-phase-tracker-right">
          <TurnPhaseTracker
            currentTurn={apiProps.gameState?.currentTurn ?? 1}
            currentPhase={apiProps.gameState?.phase ?? "move"}
            phases={
              apiProps.gameState?.deployment_type === "active"
                ? ["deployment", "move", "shoot", "charge", "fight"]
                : ["move", "shoot", "charge", "fight"]
            }
            current_player={apiProps.gameState?.current_player}
            onEndPhaseClick={apiProps.onEndPhase}
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
      ) : (
        <div className="turn-phase-tracker-right">Loading game configuration...</div>
      )}

      {/* AI Status Display */}
      {isAiMode && (
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
        })()
      )}

      <div className="scoring-panel">
        {(() => {
          const p1Score = victoryPoints ? (victoryPoints[1] ?? victoryPoints["1"] ?? 0) : 0;
          const p2Score = victoryPoints ? (victoryPoints[2] ?? victoryPoints["2"] ?? 0) : 0;
          const total = p1Score + p2Score;
          const p1Percent = total > 0 ? (p1Score / total) * 100 : 50;
          const p2Percent = 100 - p1Percent;
          return (
            <div className="scoring-panel__bar" role="img" aria-label={`Scoring P1 ${p1Score} points, P2 ${p2Score} points`}>
              <div className="scoring-panel__segment scoring-panel__segment--p1" style={{ width: `${p1Percent}%` }} />
              <div className="scoring-panel__segment scoring-panel__segment--p2" style={{ width: `${p2Percent}%` }} />
              <div className="scoring-panel__divider" />
              <div className="scoring-panel__labels">
                <span className="scoring-panel__score">P1: {p1Score}</span>
                <span className="scoring-panel__score">P2: {p2Score}</span>
              </div>
            </div>
          );
        })()}
      </div>

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

      <ErrorBoundary fallback={<div>Failed to load player 1 status</div>}>
        <UnitStatusTable
          units={apiProps.gameState?.units ?? []}
          player={1}
          selectedUnitId={apiProps.selectedUnitId ?? null}
          clickedUnitId={clickedUnitId}
          onSelectUnit={(unitId) => {
            apiProps.onSelectUnit(unitId);
            setClickedUnitId(null);
          }}
          gameMode={gameMode}
          victoryPoints={getVictoryPointsForPlayer(1)}
          onCollapseChange={setPlayer1Collapsed}
        />
      </ErrorBoundary>

      <ErrorBoundary fallback={<div>Failed to load player 2 status</div>}>
        <UnitStatusTable
          units={apiProps.gameState?.units ?? []}
          player={2}
          selectedUnitId={apiProps.selectedUnitId ?? null}
          clickedUnitId={clickedUnitId}
          onSelectUnit={(unitId) => {
            apiProps.onSelectUnit(unitId);
            setClickedUnitId(null);
          }}
          gameMode={gameMode}
          victoryPoints={getVictoryPointsForPlayer(2)}
          onCollapseChange={setPlayer2Collapsed}
        />
      </ErrorBoundary>

      {/* Game Log Component */}
      <ErrorBoundary fallback={<div>Failed to load game log</div>}>
        <GameLog
          events={gameLog.events}
          getElapsedTime={gameLog.getElapsedTime}
          availableHeight={logAvailableHeight}
          currentTurn={apiProps.gameState?.currentTurn ?? 1}
          debugMode={settings.showDebug}
        />
      </ErrorBoundary>
    </>
  );

  return (
    <SharedLayout rightColumnContent={rightColumnContent} onOpenSettings={handleOpenSettings}>
      <BoardPvp
        units={apiProps.units}
        selectedUnitId={apiProps.selectedUnitId}
        showHexCoordinates={settings.showDebug}
        eligibleUnitIds={apiProps.eligibleUnitIds}
        mode={apiProps.mode}
        movePreview={apiProps.movePreview}
        attackPreview={apiProps.attackPreview || null}
        targetPreview={
          apiProps.targetPreview
            ? {
                targetId: apiProps.targetPreview.targetId,
                shooterId: apiProps.targetPreview.shooterId,
                currentBlinkStep: apiProps.targetPreview.currentBlinkStep ?? 0,
                totalBlinkSteps: apiProps.targetPreview.totalBlinkSteps ?? 2,
                blinkTimer: apiProps.targetPreview.blinkTimer ?? null,
                hitProbability: apiProps.targetPreview.hitProbability ?? 0.5,
                woundProbability: apiProps.targetPreview.woundProbability ?? 0.5,
                saveProbability: apiProps.targetPreview.saveProbability ?? 0.5,
                overallProbability: apiProps.targetPreview.overallProbability ?? 0.25,
              }
            : null
        }
        blinkingUnits={apiProps.blinkingUnits}
        blinkingAttackerId={apiProps.blinkingAttackerId}
        isBlinkingActive={apiProps.isBlinkingActive}
        onSelectUnit={apiProps.onSelectUnit}
        onSkipUnit={apiProps.onSkipUnit}
        onStartMovePreview={apiProps.onStartMovePreview}
        onDirectMove={apiProps.onDirectMove}
        onStartAttackPreview={apiProps.onStartAttackPreview}
        onDeployUnit={apiProps.onDeployUnit}
        onConfirmMove={apiProps.onConfirmMove}
        onCancelMove={apiProps.onCancelMove}
        onShoot={apiProps.onShoot}
        onSkipShoot={apiProps.onSkipShoot}
        onStartTargetPreview={apiProps.onStartTargetPreview}
        onCancelTargetPreview={() => {
          const targetPreview = apiProps.targetPreview as TargetPreview | null;
          if (targetPreview?.blinkTimer) {
            clearInterval(targetPreview.blinkTimer);
          }
          // Clear target preview in engine API
        }}
        onFightAttack={apiProps.onFightAttack}
        onActivateFight={apiProps.onActivateFight}
        current_player={apiProps.current_player as PlayerId}
        unitsMoved={apiProps.unitsMoved}
        unitsCharged={apiProps.unitsCharged}
        unitsAttacked={apiProps.unitsAttacked}
        unitsFled={apiProps.unitsFled}
        phase={apiProps.phase as "deployment" | "move" | "shoot" | "charge" | "fight"}
        fightSubPhase={apiProps.fightSubPhase}
        onCharge={apiProps.onCharge}
        onActivateCharge={apiProps.onActivateCharge}
        onChargeEnemyUnit={apiProps.onChargeEnemyUnit}
        onMoveCharger={apiProps.onMoveCharger}
        onCancelCharge={apiProps.onCancelCharge}
        onValidateCharge={apiProps.onValidateCharge}
        onLogChargeRoll={apiProps.onLogChargeRoll}
        gameState={apiProps.gameState as GameState}
        getChargeDestinations={apiProps.getChargeDestinations}
        onAdvance={apiProps.onAdvance}
        onAdvanceMove={apiProps.onAdvanceMove}
        onCancelAdvance={apiProps.onCancelAdvance}
        getAdvanceDestinations={apiProps.getAdvanceDestinations}
        advanceRoll={apiProps.advanceRoll}
        advancingUnitId={apiProps.advancingUnitId}
        advanceWarningPopup={apiProps.advanceWarningPopup}
        onConfirmAdvanceWarning={apiProps.onConfirmAdvanceWarning}
        onCancelAdvanceWarning={apiProps.onCancelAdvanceWarning}
        onSkipAdvanceWarning={apiProps.onSkipAdvanceWarning}
        showAdvanceWarningPopup={settings.showAdvanceWarning}
        autoSelectWeapon={settings.autoSelectWeapon}
        deploymentState={apiProps.gameState?.deployment_state as DeploymentState | undefined}
        objectivesOverride={objectivesOverride}
      />
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
        autoSelectWeapon={settings.autoSelectWeapon}
        canToggleAutoSelectWeapon={canUseAutoWeaponSelection}
        onToggleAutoSelectWeapon={handleToggleAutoSelectWeapon}
      />
    </SharedLayout>
  );
};
