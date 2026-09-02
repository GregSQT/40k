// frontend/src/components/TurnPhaseTracker.tsx
import type React from "react";
import TooltipWrapper from "./TooltipWrapper";

interface TurnPhaseTrackerProps {
  currentTurn: number;
  currentPhase: string;
  phases: string[]; // Required - tour_de_jeu.md compliance: no config wrappers
  maxTurns: number; // Required - tour_de_jeu.md compliance: direct data flow
  current_player?: number; // Current player (1 or 2) for P1/P2 buttons
  className?: string;
  onTurnClick?: (turn: number) => void; // Optional callback for turn button clicks (replay mode)
  onPhaseClick?: (phase: string) => void; // Optional callback for phase button clicks (replay mode)
  onPlayerClick?: (player: number) => void; // Optional callback for player button clicks (replay mode)
  onEndPhaseClick?: (player: number) => void; // End current phase for active player
  showPileIn?: boolean; // Affiche le bouton « Pile-in » (sous-phase pile_in en cours)
  pileInPlayer?: number; // Joueur (1/2) qui doit faire le pile-in → couleur du bouton
  onEndPileIn?: () => void; // Termine la sous-phase pile-in et passe à la suivante
  showFightAtk?: boolean; // Affiche le bouton « ATK » (sous-phase d'attaque fight, hors pile_in)
  fightAtkPlayer?: number; // Joueur (1/2) qui doit faire attaquer une unité → libellé + couleur
  onFightAtk?: () => void; // Active la 1ère unité éligible du joueur concerné
  onSkipFight?: () => void; // Skippe toutes les attaques (2 joueurs) → consolidation directe
  // Mode sandbox
  sandboxMode?: boolean;
  onSandboxToggle?: () => void;
  sandboxFreeMove?: boolean;
  onSandboxFreeMoveToggle?: (val: boolean) => void;
  onJumpToPhase?: (phase: string) => void;
}

export const TurnPhaseTracker: React.FC<TurnPhaseTrackerProps> = ({
  currentTurn,
  currentPhase,
  phases,
  maxTurns,
  current_player,
  className = "",
  onTurnClick,
  onPhaseClick,
  onPlayerClick,
  onEndPhaseClick,
  showPileIn,
  pileInPlayer,
  onEndPileIn,
  showFightAtk,
  fightAtkPlayer,
  onFightAtk,
  onSkipFight,
  sandboxMode = false,
  onSandboxToggle,
  sandboxFreeMove = false,
  onSandboxFreeMoveToggle,
  onJumpToPhase,
}) => {
  // Validate required props (raise errors for missing data)
  if (!phases || phases.length === 0) {
    throw new Error("TurnPhaseTracker: phases array is required and cannot be empty");
  }
  if (!maxTurns || maxTurns <= 0) {
    throw new Error("TurnPhaseTracker: maxTurns must be a positive number");
  }

  // Generate turn numbers array based on provided maxTurns
  const turns = Array.from({ length: maxTurns }, (_, i) => i + 1);

  const getTurnStatus = (turn: number): "passed" | "current" | "upcoming" => {
    // Default to turn 1 if currentTurn is undefined
    const actualCurrentTurn = currentTurn || 1;
    if (turn < actualCurrentTurn) {
      return "passed";
    } else if (turn === actualCurrentTurn) {
      return "current";
    } else {
      return "upcoming";
    }
  };

  const getTurnStyle = (
    status: "passed" | "current" | "upcoming",
    hasClickHandler: boolean
  ): React.CSSProperties => {
    const baseStyle: React.CSSProperties = {
      padding: "4px 8px",
      borderRadius: "4px",
      fontWeight: "medium",
      fontSize: "14px",
      border: "1px solid",
      cursor: hasClickHandler ? "pointer" : "default",
      outline: "none",
    };

    switch (status) {
      case "passed":
        return {
          ...baseStyle,
          backgroundColor: "#6B7280", // grey-500
          color: "#FFFFFF",
          borderColor: "#4B5563", // grey-600
        };
      case "current":
        return {
          ...baseStyle,
          backgroundColor: "#059669", // green-600
          color: "#FFFFFF",
          borderColor: "#047857", // green-700
          fontWeight: "bold",
          boxShadow: "0 4px 6px -1px rgba(0, 0, 0, 0.1)",
        };
      case "upcoming":
        return {
          ...baseStyle,
          backgroundColor: "#BFDBFE", // blue-200
          color: "#1E40AF", // blue-800
          borderColor: "#93C5FD", // blue-300
        };
      default:
        return baseStyle;
    }
  };

  const getPhaseStatus = (phase: string): "passed" | "current" | "upcoming" => {
    const currentPhaseIndex = phases.indexOf(currentPhase);
    const phaseIndex = phases.indexOf(phase);

    if (currentPhaseIndex === -1 || phaseIndex === -1) {
      return "upcoming";
    }

    if (phaseIndex < currentPhaseIndex) {
      return "passed";
    } else if (phaseIndex === currentPhaseIndex) {
      return "current";
    } else {
      return "upcoming";
    }
  };

  const getPhaseBaseColor = (phase: string): { bg: string; text: string; border: string } => {
    switch (phase.toLowerCase()) {
      case "command":
        return {
          bg: "var(--phase-command-bg)",
          text: "#FFFFFF",
          border: "var(--phase-command-border)",
        };
      case "move":
        return { bg: "var(--phase-move-bg)", text: "#FFFFFF", border: "var(--phase-move-border)" };
      case "shoot":
        return {
          bg: "var(--phase-shoot-bg)",
          text: "#FFFFFF",
          border: "var(--phase-shoot-border)",
        };
      case "charge":
        return {
          bg: "var(--phase-charge-bg)",
          text: "#FFFFFF",
          border: "var(--phase-charge-border)",
        };
      case "fight":
        return {
          bg: "var(--phase-fight-bg)",
          text: "#FFFFFF",
          border: "var(--phase-fight-border)",
        };
      default:
        return {
          bg: "var(--phase-default-bg)",
          text: "#FFFFFF",
          border: "var(--phase-default-border)",
        };
    }
  };

  const getPhaseStyle = (
    phase: string,
    status: "passed" | "current" | "upcoming",
    hasClickHandler: boolean
  ): React.CSSProperties => {
    const baseStyle: React.CSSProperties = {
      padding: "4px 8px",
      borderRadius: "4px",
      fontSize: "14px",
      border: "1px solid",
      cursor: hasClickHandler ? "pointer" : "default",
      outline: "none",
    };

    const baseColor = getPhaseBaseColor(phase);

    switch (status) {
      case "passed":
        return {
          ...baseStyle,
          backgroundColor: "#6B7280", // grey-500
          color: "#FFFFFF",
          borderColor: "#4B5563", // grey-600
        };
      case "current":
        return {
          ...baseStyle,
          backgroundColor: baseColor.bg,
          color: baseColor.text,
          borderColor: baseColor.border,
          fontWeight: "bold",
          boxShadow: "0 4px 6px -1px rgba(0, 0, 0, 0.1)",
        };
      case "upcoming":
        return {
          ...baseStyle,
          backgroundColor: baseColor.bg,
          color: baseColor.text,
          borderColor: baseColor.border,
          opacity: 0.7,
        };
      default:
        return baseStyle;
    }
  };

  const formatPhaseName = (phase: string): string => {
    return phase.charAt(0).toUpperCase() + phase.slice(1);
  };

  const getPlayerStyle = (
    player: number,
    isActive: boolean,
    hasClickHandler: boolean
  ): React.CSSProperties => {
    const baseStyle: React.CSSProperties = {
      padding: "4px 8px",
      borderRadius: "4px",
      fontWeight: "medium",
      fontSize: "14px",
      border: "1px solid",
      cursor: hasClickHandler ? "pointer" : "default",
      outline: "none",
    };

    const playerColor =
      player === 1
        ? { bg: "#1D4ED8", border: "#1E3A8A" } // blue-700, blue-900
        : { bg: "#dc2626", border: "#dc2626" }; // red

    if (isActive) {
      return {
        ...baseStyle,
        backgroundColor: playerColor.bg,
        color: "#FFFFFF",
        borderColor: playerColor.border,
        fontWeight: "bold",
        boxShadow: "0 4px 6px -1px rgba(0, 0, 0, 0.1)",
      };
    } else {
      return {
        ...baseStyle,
        backgroundColor: `${playerColor.bg}80`, // Add transparency
        color: "#FFFFFF",
        borderColor: `${playerColor.border}80`,
        opacity: 0.7,
      };
    }
  };

  const getEndPhaseStyle = (
    player: number,
    isEnabled: boolean,
    hasClickHandler: boolean
  ): React.CSSProperties => {
    const baseStyle: React.CSSProperties = {
      padding: "4px 8px",
      borderRadius: "4px",
      fontWeight: "bold",
      fontSize: "13px",
      border: "1px solid",
      cursor: hasClickHandler && isEnabled ? "pointer" : "not-allowed",
      outline: "none",
      color: "#FFFFFF",
      opacity: isEnabled ? 1 : 0.55,
    };

    if (player === 1) {
      return {
        ...baseStyle,
        backgroundColor: "#1D4ED8",
        borderColor: "#1E3A8A",
      };
    }
    return {
      ...baseStyle,
      backgroundColor: "#dc2626",
      borderColor: "#991B1B",
    };
  };

  return (
    <div
      className={className}
      style={{
        background: "#1f2937",
        border: "1px solid #555",
        borderRadius: "8px",
        padding: "8px",
      }}
    >
      <div
        style={{
          display: "flex",
          flexDirection: "row",
          alignItems: "center",
          justifyContent: "space-between",
          width: "100%",
        }}
      >
        <div
          style={{
            display: "flex",
            gap: "2px",
            flex: "0 0 auto",
            justifyContent: "flex-start",
            alignItems: "center",
          }}
        >
          <div
            style={{
              display: "inline-flex",
              gap: "2px",
              alignItems: "center",
              width: "fit-content",
            }}
          >
            <span
              style={{
                padding: "4px 8px",
                borderRadius: "4px",
                fontWeight: "medium",
                fontSize: "15px",
                lineHeight: "1.1",
                border: "1px solid #93C5FD",
                backgroundColor: "#BFDBFE",
                color: "#1E40AF",
              }}
            >
              Round :
            </span>
            {turns.map((turn) => {
              const status = getTurnStatus(turn);
              const style = getTurnStyle(status, !!onTurnClick);

              return (
                <button
                  type="button"
                  key={turn}
                  data-testid={`turn-btn-${turn}`}
                  style={style}
                  disabled={!onTurnClick}
                  onClick={() => onTurnClick?.(turn)}
                >
                  {turn}
                </button>
              );
            })}
          </div>
        </div>
        <div style={{ flex: 1 }} />
        {current_player !== undefined && (
          <div
            style={{ display: "flex", gap: "2px", alignItems: "center", justifyContent: "center" }}
          >
            <button
              type="button"
              data-testid="player-btn-1"
              style={getPlayerStyle(1, current_player === 1, !!onPlayerClick)}
              onClick={() => onPlayerClick?.(1)}
              disabled={!onPlayerClick}
            >
              P1
            </button>
            {onEndPhaseClick && (
              <TooltipWrapper text={`Terminer immédiatement la phase pour P${current_player}`}>
                <button
                  type="button"
                  data-testid="end-phase-btn"
                  style={getEndPhaseStyle(current_player, true, !!onEndPhaseClick)}
                  onClick={() => onEndPhaseClick?.(current_player)}
                  disabled={!onEndPhaseClick}
                >
                  End Phase
                </button>
              </TooltipWrapper>
            )}
            <button
              type="button"
              data-testid="player-btn-2"
              style={getPlayerStyle(2, current_player === 2, !!onPlayerClick)}
              onClick={() => onPlayerClick?.(2)}
              disabled={!onPlayerClick}
            >
              P2
            </button>
          </div>
        )}
        <div style={{ flex: 1 }} />
        <div style={{ display: "flex", gap: "2px", flex: "0 0 auto", justifyContent: "flex-end" }}>
          <div
            style={{
              display: "inline-flex",
              gap: "2px",
              alignItems: "center",
              width: "fit-content",
            }}
          >
            {phases
              .filter((phase) => !(phase === "deployment" && currentPhase !== "deployment"))
              .map((phase) => {
                const status = getPhaseStatus(phase);
                const hasHandler = sandboxMode ? !!onJumpToPhase : !!onPhaseClick;
                const style = getPhaseStyle(phase, status, hasHandler);

                return (
                  <button
                    type="button"
                    key={phase}
                    data-testid={`phase-btn-${phase}`}
                    className="phase-btn"
                    style={
                      sandboxMode && onJumpToPhase
                        ? {
                            ...style,
                            cursor: "pointer",
                            outline: sandboxMode ? "1px dashed #A78BFA" : "none",
                          }
                        : style
                    }
                    disabled={!hasHandler}
                    onClick={() => (sandboxMode ? onJumpToPhase?.(phase) : onPhaseClick?.(phase))}
                  >
                    {formatPhaseName(phase)}
                  </button>
                );
              })}
            {showPileIn && onEndPileIn && (
              <button
                type="button"
                className={`pile-in-end-btn ${(pileInPlayer ?? current_player) === 2 ? "pile-in-end-btn--p2" : "pile-in-end-btn--p1"}`}
                onClick={() => onEndPileIn()}
              >
                Pile-in
                <span aria-hidden="true">→</span>
              </button>
            )}
            {showFightAtk && onFightAtk && (
              <button
                type="button"
                className={`pile-in-end-btn ${(fightAtkPlayer ?? current_player) === 2 ? "pile-in-end-btn--p2" : "pile-in-end-btn--p1"}`}
                onClick={() => onFightAtk()}
              >
                P{fightAtkPlayer ?? current_player} ATK
              </button>
            )}
            {showFightAtk && onSkipFight && (
              <button type="button" className="pile-in-end-btn" onClick={() => onSkipFight()}>
                Skip
                <span aria-hidden="true">→</span>
              </button>
            )}
            {onSandboxToggle && (
              <TooltipWrapper
                text={
                  sandboxMode
                    ? "Quitter le mode sandbox"
                    : "Mode sandbox : repositionnement libre + saut de phase"
                }
              >
                <button
                  type="button"
                  data-testid="sandbox-toggle-btn"
                  style={{
                    padding: "4px 8px",
                    borderRadius: "4px",
                    fontSize: "13px",
                    border: "1px solid",
                    cursor: "pointer",
                    outline: "none",
                    fontWeight: "bold",
                    backgroundColor: sandboxMode ? "#7C3AED" : "#374151",
                    color: "#FFFFFF",
                    borderColor: sandboxMode ? "#5B21B6" : "#4B5563",
                  }}
                  onClick={onSandboxToggle}
                >
                  🧪
                </button>
              </TooltipWrapper>
            )}
          </div>
        </div>
      </div>
      {sandboxMode && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "6px",
            marginTop: "6px",
            paddingTop: "6px",
            borderTop: "1px solid #4B5563",
          }}
        >
          <span style={{ color: "#A78BFA", fontSize: "12px", fontWeight: "bold" }}>SANDBOX</span>
          {onSandboxFreeMoveToggle && (
            <TooltipWrapper
              text={
                sandboxFreeMove
                  ? "Désactiver le déplacement libre"
                  : "Activer le déplacement libre (tout le plateau)"
              }
            >
              <button
                type="button"
                data-testid="sandbox-free-move-btn"
                style={{
                  padding: "2px 8px",
                  borderRadius: "4px",
                  fontSize: "12px",
                  border: "1px solid",
                  cursor: "pointer",
                  outline: "none",
                  backgroundColor: sandboxFreeMove ? "#059669" : "#374151",
                  color: "#FFFFFF",
                  borderColor: sandboxFreeMove ? "#047857" : "#4B5563",
                }}
                onClick={() => onSandboxFreeMoveToggle(!sandboxFreeMove)}
              >
                Free Move {sandboxFreeMove ? "ON" : "OFF"}
              </button>
            </TooltipWrapper>
          )}
          {onJumpToPhase && (
            <span style={{ color: "#9CA3AF", fontSize: "12px" }}>
              Cliquer une phase pour y sauter →
            </span>
          )}
        </div>
      )}
    </div>
  );
};
