// frontend/src/components/SharedLayout.tsx
import type React from "react";
import { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { getAuthSession } from "../auth/authStorage";
import { ErrorBoundary } from "./ErrorBoundary";
import TooltipWrapper from "./TooltipWrapper";

interface SharedLayoutProps {
  children: React.ReactNode; // Left column content (GameBoard, ReplayViewer, etc.)
  rightColumnContent: React.ReactNode; // Right column content (varies by page)
  className?: string;
  onOpenSettings?: () => void;
  /** Bascule le mode mesure (règle) : seule action qui le désactive quand il est actif. */
  onToggleMeasureMode?: () => void;
  /** Règle « allumée » : entre deux lignes (armed) ou pendant une mesure. */
  measureModeActive?: boolean;
}

interface NavigationProps {
  onOpenSettings?: () => void;
  onToggleMeasureMode?: () => void;
  measureModeActive?: boolean;
}

/** Logo règle (assets : `frontend/public/icons/Action_Logo/Ruler.png`). */
function RulerMenuIcon({ active }: { active: boolean }) {
  return (
    <img
      src="/icons/Action_Logo/Ruler.png"
      alt=""
      width={20}
      height={20}
      draggable={false}
      aria-hidden
      style={{
        display: "block",
        opacity: active ? 1 : 0.78,
        objectFit: "contain",
      }}
    />
  );
}

const BOARD_OPTIONS = [
  { key: "x1", label: "25×21" },
  { key: "x5", label: "180×156" },
  { key: "x10", label: "360×312" },
] as const;

type BoardKey = (typeof BOARD_OPTIONS)[number]["key"];

function MapIcon() {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 20 20"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden
    >
      <title>Map</title>
      <polygon
        points="1,3 7,1 13,3 19,1 19,17 13,19 7,17 1,19"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
        fill="none"
      />
      <line x1="7" y1="1" x2="7" y2="17" stroke="currentColor" strokeWidth="1.5" />
      <line x1="13" y1="3" x2="13" y2="19" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  );
}

function BoardResolutionPicker() {
  const [open, setOpen] = useState(false);
  const [defaultBoard, setDefaultBoard] = useState<BoardKey>("x5");
  const ref = useRef<HTMLDivElement>(null);

  const params = new URLSearchParams(window.location.search);
  const current = (params.get("board") as BoardKey | null) ?? defaultBoard;

  useEffect(() => {
    fetch("/api/config/defaults")
      .then((r) => r.json())
      .then((data: { success?: boolean; defaults?: { test_board?: string } }) => {
        if (data.success && data.defaults?.test_board) {
          setDefaultBoard(data.defaults.test_board as BoardKey);
        }
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const select = (key: BoardKey) => {
    setOpen(false);
    const p = new URLSearchParams(window.location.search);
    p.set("board", key);
    window.location.href = `${window.location.pathname}?${p.toString()}`;
  };

  const currentLabel = BOARD_OPTIONS.find((o) => o.key === current)?.label ?? current;

  return (
    <div ref={ref} style={{ position: "relative" }}>
      <TooltipWrapper text="Résolution du plateau">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="settings-button"
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: "5px",
            background: "transparent",
            border: "none",
            cursor: "pointer",
            color: open ? "#93c5fd" : "#9ca3af",
            padding: "4px",
          }}
        >
          <span style={{ fontSize: "11px", fontWeight: 500, letterSpacing: "0.02em" }}>
            {currentLabel}
          </span>
          <MapIcon />
        </button>
      </TooltipWrapper>
      {open && (
        <div
          style={{
            position: "absolute",
            top: "calc(100% + 4px)",
            right: 0,
            background: "#1f2937",
            border: "1px solid #374151",
            borderRadius: "6px",
            padding: "4px 0",
            minWidth: "120px",
            zIndex: 100,
            boxShadow: "0 4px 12px rgba(0,0,0,0.5)",
          }}
        >
          {BOARD_OPTIONS.map((opt) => (
            <button
              key={opt.key}
              type="button"
              onClick={() => select(opt.key)}
              style={{
                display: "block",
                width: "100%",
                textAlign: "left",
                padding: "6px 14px",
                background: "transparent",
                border: "none",
                cursor: "pointer",
                color: current === opt.key ? "#93c5fd" : "#d1d5db",
                fontSize: "13px",
                fontWeight: current === opt.key ? 600 : 400,
              }}
            >
              {opt.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

const Navigation: React.FC<NavigationProps> = ({
  onOpenSettings,
  onToggleMeasureMode,
  measureModeActive = false,
}) => {
  const measureRulerButtonRef = useRef<HTMLButtonElement>(null);

  /** Retire le focus du bouton règle quand le mode mesure se termine (évite le cadre :focus-visible). */
  useEffect(() => {
    if (!measureModeActive) {
      measureRulerButtonRef.current?.blur();
    }
  }, [measureModeActive]);

  const location = useLocation();
  const authSession = getAuthSession();
  const tutorialCompleted = authSession?.tutorial_completed ?? true;

  const getButtonClass = (path: string) => {
    const isPvPTestMode =
      location.pathname === "/game" && location.search.includes("mode=pvp_test");
    const isPvEMode = location.pathname === "/game" && location.search.includes("mode=pve");
    const isEndlessDutyMode =
      location.pathname === "/game" && location.search.includes("mode=endless_duty");
    const isPvETestMode =
      location.pathname === "/game" && location.search.includes("mode=pve_test");
    const isTutorialMode =
      location.pathname === "/game" && location.search.includes("mode=tutorial");

    // Handle Tutorial mode
    if (path === "/game?mode=tutorial") {
      return `nav-button ${isTutorialMode ? "nav-button--active" : "nav-button--inactive"}`;
    }

    // Handle PvE mode detection via query parameter
    if (path === "/game?mode=pve") {
      return `nav-button ${isPvEMode ? "nav-button--active" : "nav-button--inactive"}`;
    }

    // Handle Endless Duty mode detection via query parameter
    if (path === "/game?mode=endless_duty") {
      return `nav-button ${isEndlessDutyMode ? "nav-button--active" : "nav-button--inactive"}`;
    }

    // Handle PvE test mode detection via query parameter
    if (path === "/game?mode=pve_test") {
      return `nav-button ${isPvETestMode ? "nav-button--active" : "nav-button--inactive"}`;
    }

    // Handle PvP Test mode detection via query parameter
    if (path === "/game?mode=pvp_test") {
      return `nav-button ${isPvPTestMode ? "nav-button--active" : "nav-button--inactive"}`;
    }

    // Handle PvP mode - only active when on /game without explicit mode.
    if (path === "/game") {
      const isPvPMode =
        location.pathname === "/game" &&
        !isPvPTestMode &&
        !isPvEMode &&
        !isEndlessDutyMode &&
        !isPvETestMode &&
        !isTutorialMode;
      return `nav-button ${isPvPMode ? "nav-button--active" : "nav-button--inactive"}`;
    }

    // Handle standard path matching for Replay and other routes
    return `nav-button ${location.pathname === path ? "nav-button--active" : "nav-button--inactive"}`;
  };

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        width: "100%",
      }}
    >
      <nav className="navigation">
        {!tutorialCompleted && (
          <button
            type="button"
            onClick={() => (window.location.href = "/game?mode=tutorial")}
            className={getButtonClass("/game?mode=tutorial")}
          >
            Tutorial
          </button>
        )}
        {tutorialCompleted && (
          <>
            <button
              type="button"
              onClick={() => (window.location.href = "/game")}
              className={getButtonClass("/game")}
            >
              PvP
            </button>
            <button
              type="button"
              onClick={() => (window.location.href = "/game?mode=pve")}
              className={getButtonClass("/game?mode=pve")}
            >
              PvE
            </button>
            <button
              type="button"
              onClick={() => (window.location.href = "/game?mode=endless_duty")}
              className={getButtonClass("/game?mode=endless_duty")}
            >
              Endless Duty
            </button>
            <button
              type="button"
              onClick={() => (window.location.href = "/game?mode=tutorial")}
              className={getButtonClass("/game?mode=tutorial")}
            >
              Tutorial
            </button>
            <button
              type="button"
              onClick={() => (window.location.href = "/game?mode=pvp_test")}
              className={getButtonClass("/game?mode=pvp_test")}
            >
              PvP Test
            </button>
            <button
              type="button"
              onClick={() => (window.location.href = "/game?mode=pve_test")}
              className={getButtonClass("/game?mode=pve_test")}
            >
              PvE Test
            </button>
            <button
              type="button"
              onClick={() => (window.location.href = "/game?mode=replay")}
              className={getButtonClass("/replay")}
            >
              Replay
            </button>
          </>
        )}
      </nav>

      {onOpenSettings && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "6px",
          }}
        >
          {(location.search.includes("mode=pvp_test") ||
            location.search.includes("mode=pve_test")) && (
            <BoardResolutionPicker />
          )}
          {onToggleMeasureMode && (
            <TooltipWrapper
              text={
                measureModeActive
                  ? "2e clic gauche : fin de la ligne courante (tu peux en tracer une autre). Clic droit : jonction. Icône règle : désactiver le mode mesure."
                  : "Activer la mesure sur le plateau : 1er clic = départ, clic droit = jonction, 2e clic = fin de ligne ; recliquer l’icône pour quitter."
              }
            >
              <button
                ref={measureRulerButtonRef}
                type="button"
                onClick={onToggleMeasureMode}
                className="settings-button"
                aria-pressed={measureModeActive}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  justifyContent: "center",
                  background: "transparent",
                  border: "none",
                  cursor: "pointer",
                  color: measureModeActive ? "#93c5fd" : "#9ca3af",
                  padding: "4px",
                }}
              >
                <RulerMenuIcon active={measureModeActive} />
              </button>
            </TooltipWrapper>
          )}
          <TooltipWrapper text="Paramètres">
            <button
              type="button"
              onClick={onOpenSettings}
              className="settings-button"
              style={{
                background: "transparent",
                border: "none",
                cursor: "pointer",
                fontSize: "20px",
                color: "#9ca3af",
                padding: "4px",
              }}
            >
              ⚙️
            </button>
          </TooltipWrapper>
        </div>
      )}
    </div>
  );
};

export const SharedLayout: React.FC<SharedLayoutProps> = ({
  children,
  rightColumnContent,
  className,
  onOpenSettings,
  onToggleMeasureMode,
  measureModeActive,
}) => {
  return (
    <div
      className={`game-controller ${className || ""}`}
      style={{ background: "#222", height: "100vh" }}
    >
      <main className="main-content">
        <div className="game-area" style={{ display: "flex", gap: "16px" }}>
          <div className="game-board-section">
            <ErrorBoundary fallback={<div>Failed to load game board</div>}>
              {children}
            </ErrorBoundary>
          </div>

          <div
            className="unit-status-tables"
            style={{ paddingTop: "0px", marginTop: "0px", gap: "4px" }}
          >
            <Navigation
              onOpenSettings={onOpenSettings}
              onToggleMeasureMode={onToggleMeasureMode}
              measureModeActive={measureModeActive}
            />
            {rightColumnContent}
          </div>
        </div>
      </main>
    </div>
  );
};

export default SharedLayout;
