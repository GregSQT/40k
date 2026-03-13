// frontend/src/components/TurnPhaseTracker.tsx
import type React from "react";
import { useLayoutEffect, useRef } from "react";
import type { TutorialSpotlightPosition } from "../contexts/TutorialContext";
import {
  TUTORIAL_STEP_TITLE_1_14_PHASE_MOUVEMENT,
  TUTORIAL_STEP_TITLE_PHASE_MOUVEMENT,
  TUTORIAL_STEP_TITLE_PHASE_TIR,
  TUTORIAL_STEP_TITLE_PHASES,
  TUTORIAL_STEP_TITLE_ROUNDS,
  TUTORIAL_STEP_TITLE_TURNS,
} from "../contexts/TutorialContext";
import TooltipWrapper from "./TooltipWrapper";

function rectFromEl(el: HTMLElement | null, pad: number): TutorialSpotlightPosition | null {
  if (!el) return null;
  const r = el.getBoundingClientRect();
  if (r.width < 2 || r.height < 2) return null;
  return {
    shape: "rect",
    left: r.left - pad,
    top: r.top - pad,
    width: r.width + pad * 2,
    height: r.height + pad * 2,
  };
}

/** Le TurnPhaseTracker est dans le panneau droit : rect.left doit être > 40% viewport. */
function isTurnPhaseTrackerRect(rect: TutorialSpotlightPosition): boolean {
  if (rect.shape !== "rect") return true;
  const viewportWidth = typeof window !== "undefined" ? window.innerWidth : 1920;
  return rect.left > viewportWidth * 0.4;
}

interface TurnPhaseTrackerProps {
  currentTurn: number;
  currentPhase: string;
  phases: string[]; // Required - AI_TURN.md compliance: no config wrappers
  maxTurns: number; // Required - AI_TURN.md compliance: direct data flow
  current_player?: number; // Current player (1 or 2) for P1/P2 buttons
  className?: string;
  onTurnClick?: (turn: number) => void; // Optional callback for turn button clicks (replay mode)
  onPhaseClick?: (phase: string) => void; // Optional callback for phase button clicks (replay mode)
  onPlayerClick?: (player: number) => void; // Optional callback for player button clicks (replay mode)
  onEndPhaseClick?: (player: number) => void; // End current phase for active player
  /** Titre de l'étape tutoriel en cours (Rounds / Tours / Phases) pour halos. */
  tutorialStepTitle?: string | null;
  /** Callback pour rapporter les rects viewport des zones à mettre en halo. */
  onTutorialRects?: (pos: TutorialSpotlightPosition[] | null) => void;
}

const PAD = 4;

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
  tutorialStepTitle,
  onTutorialRects,
}) => {
  const turnSectionRef = useRef<HTMLDivElement>(null);
  const p1ButtonRef = useRef<HTMLButtonElement>(null);
  const p2ButtonRef = useRef<HTMLButtonElement>(null);
  const phasesContainerRef = useRef<HTMLDivElement>(null);
  const movePhaseButtonRef = useRef<HTMLButtonElement | null>(null);
  const shootPhaseButtonRef = useRef<HTMLButtonElement | null>(null);

  useLayoutEffect(() => {
    if (!onTutorialRects || !tutorialStepTitle) {
      onTutorialRects?.(null);
      return;
    }
    const measure = () => {
      let rects: TutorialSpotlightPosition[] | null = null;
      if (tutorialStepTitle === TUTORIAL_STEP_TITLE_ROUNDS) {
        const r = rectFromEl(turnSectionRef.current, PAD);
        rects = r && isTurnPhaseTrackerRect(r) ? [r] : null;
      } else if (tutorialStepTitle === TUTORIAL_STEP_TITLE_TURNS) {
        const r1 = rectFromEl(p1ButtonRef.current, PAD);
        const r2 = rectFromEl(p2ButtonRef.current, PAD);
        const out: TutorialSpotlightPosition[] = [];
        if (r1 && isTurnPhaseTrackerRect(r1)) out.push(r1);
        if (r2 && isTurnPhaseTrackerRect(r2)) out.push(r2);
        rects = out.length ? out : null;
      } else if (tutorialStepTitle === TUTORIAL_STEP_TITLE_PHASES) {
        const r = rectFromEl(phasesContainerRef.current, PAD);
        rects = r && isTurnPhaseTrackerRect(r) ? [r] : null;
      } else if (
        tutorialStepTitle === TUTORIAL_STEP_TITLE_PHASE_MOUVEMENT ||
        tutorialStepTitle === TUTORIAL_STEP_TITLE_1_14_PHASE_MOUVEMENT
      ) {
        const r = rectFromEl(movePhaseButtonRef.current, PAD);
        rects = r && isTurnPhaseTrackerRect(r) ? [r] : null;
      } else if (tutorialStepTitle === "2-11") {
        const rTurn = rectFromEl(turnSectionRef.current, PAD);
        const rMove = rectFromEl(movePhaseButtonRef.current, PAD);
        const out: TutorialSpotlightPosition[] = [];
        if (rTurn && isTurnPhaseTrackerRect(rTurn)) out.push(rTurn);
        if (rMove && isTurnPhaseTrackerRect(rMove)) out.push(rMove);
        rects = out.length ? out : null;
      } else if (tutorialStepTitle === TUTORIAL_STEP_TITLE_PHASE_TIR) {
        const rMove = rectFromEl(movePhaseButtonRef.current, PAD);
        const rShoot = rectFromEl(shootPhaseButtonRef.current, PAD);
        const out: TutorialSpotlightPosition[] = [];
        if (rMove && isTurnPhaseTrackerRect(rMove)) out.push(rMove);
        if (rShoot && isTurnPhaseTrackerRect(rShoot)) out.push(rShoot);
        rects = out.length ? out : null;
      }
      onTutorialRects(rects);
    };
    measure();
    let cancelled = false;
    const raf = requestAnimationFrame(() => {
      if (cancelled) return;
      measure();
      requestAnimationFrame(() => {
        if (cancelled) return;
        measure();
        setTimeout(() => {
          if (!cancelled) measure();
        }, 30);
      });
    });
    return () => {
      cancelled = true;
      cancelAnimationFrame(raf);
      onTutorialRects?.(null);
    };
  }, [tutorialStepTitle, onTutorialRects]);

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
        return { bg: "#FCD34D", text: "#FFFFFF", border: "#F59E0B" }; // yellow-300, white, yellow-500
      case "move":
        return { bg: "#15803D", text: "#FFFFFF", border: "#166534" }; // green-700, white, green-800
      case "shoot":
        return { bg: "#1D4ED8", text: "#FFFFFF", border: "#1E40AF" }; // blue-700, white, blue-800
      case "charge":
        return { bg: "#7E22CE", text: "#FFFFFF", border: "#6B21A8" }; // purple-700, white, purple-800
      case "fight":
        return { bg: "#B91C1C", text: "#FFFFFF", border: "#991B1B" }; // red-700, white, red-800
      default:
        return { bg: "#6B7280", text: "#FFFFFF", border: "#4B5563" }; // grey-500, white, grey-600
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
      fontWeight: "medium",
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
          backgroundColor: `${baseColor.bg}80`, // Add transparency
          color: baseColor.text,
          borderColor: `${baseColor.border}80`,
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
          ref={turnSectionRef}
          style={{
            display: "flex",
            gap: "2px",
            flex: 1,
            justifyContent: "flex-start",
            alignItems: "center",
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
            Turn :
          </span>
          {turns.map((turn) => {
            const status = getTurnStatus(turn);
            const style = getTurnStyle(status, !!onTurnClick);

            return (
              <button
                type="button"
                key={turn}
                style={style}
                disabled={!onTurnClick}
                onClick={() => onTurnClick?.(turn)}
              >
                {turn}
              </button>
            );
          })}
        </div>
        {current_player !== undefined && (
          <div
            style={{ display: "flex", gap: "2px", alignItems: "center", justifyContent: "center" }}
          >
            {current_player === 1 && onEndPhaseClick && (
              <TooltipWrapper text="Terminer immédiatement la phase pour P1">
                <button
                  type="button"
                  style={getEndPhaseStyle(1, true, !!onEndPhaseClick)}
                  onClick={() => onEndPhaseClick?.(1)}
                  disabled={!onEndPhaseClick}
                >
                  End Phase
                </button>
              </TooltipWrapper>
            )}
            <button
              ref={p1ButtonRef}
              type="button"
              style={getPlayerStyle(1, current_player === 1, !!onPlayerClick)}
              onClick={() => onPlayerClick?.(1)}
              disabled={!onPlayerClick}
            >
              P1
            </button>
            <button
              ref={p2ButtonRef}
              type="button"
              style={getPlayerStyle(2, current_player === 2, !!onPlayerClick)}
              onClick={() => onPlayerClick?.(2)}
              disabled={!onPlayerClick}
            >
              P2
            </button>
            {current_player === 2 && onEndPhaseClick && (
              <TooltipWrapper text="Terminer immédiatement la phase pour P2">
                <button
                  type="button"
                  style={getEndPhaseStyle(2, true, !!onEndPhaseClick)}
                  onClick={() => onEndPhaseClick?.(2)}
                  disabled={!onEndPhaseClick}
                >
                  End Phase
                </button>
              </TooltipWrapper>
            )}
          </div>
        )}
        <div
          ref={phasesContainerRef}
          style={{ display: "flex", gap: "2px", flex: 1, justifyContent: "flex-end" }}
        >
          {phases
            .filter((phase) => !(phase === "deployment" && currentPhase !== "deployment"))
            .map((phase) => {
              const status = getPhaseStatus(phase);
              const style = getPhaseStyle(phase, status, !!onPhaseClick);
              const isMovePhase = phase === "move";
              const isShootPhase = phase === "shoot";

              return (
                <button
                  ref={isMovePhase ? movePhaseButtonRef : isShootPhase ? shootPhaseButtonRef : undefined}
                  type="button"
                  key={phase}
                  style={style}
                  disabled={!onPhaseClick}
                  onClick={() => onPhaseClick?.(phase)}
                >
                  {formatPhaseName(phase)}
                </button>
              );
            })}
        </div>
      </div>
    </div>
  );
};
