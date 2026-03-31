// frontend/src/components/SharedLayout.tsx
import type React from "react";
import { useLocation } from "react-router-dom";
import { getAuthSession } from "../auth/authStorage";
import { ErrorBoundary } from "./ErrorBoundary";
import TooltipWrapper from "./TooltipWrapper";

interface SharedLayoutProps {
  children: React.ReactNode; // Left column content (GameBoard, ReplayViewer, etc.)
  rightColumnContent: React.ReactNode; // Right column content (varies by page)
  className?: string;
  onOpenSettings?: () => void;
}

interface NavigationProps {
  onOpenSettings?: () => void;
}

const Navigation: React.FC<NavigationProps> = ({ onOpenSettings }) => {
  const location = useLocation();
  const authSession = getAuthSession();
  const tutorialCompleted = authSession?.tutorial_completed ?? true;

  const getButtonClass = (path: string) => {
    const isPvPTestMode = location.pathname === "/game" && location.search.includes("mode=pvp_test");
    const isPvEMode = location.pathname === "/game" && location.search.includes("mode=pve");
    const isEndlessDutyMode =
      location.pathname === "/game" && location.search.includes("mode=endless_duty");
    const isPvETestMode = location.pathname === "/game" && location.search.includes("mode=pve_test");
    const isTutorialMode = location.pathname === "/game" && location.search.includes("mode=tutorial");

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
      )}
    </div>
  );
};

export const SharedLayout: React.FC<SharedLayoutProps> = ({
  children,
  rightColumnContent,
  className,
  onOpenSettings,
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
            <Navigation onOpenSettings={onOpenSettings} />
            {rightColumnContent}
          </div>
        </div>
      </main>
    </div>
  );
};

export default SharedLayout;
