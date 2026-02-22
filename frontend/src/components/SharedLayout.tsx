// frontend/src/components/SharedLayout.tsx
import type React from "react";
import { useLocation } from "react-router-dom";
import { ErrorBoundary } from "./ErrorBoundary";

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

  const getButtonClass = (path: string) => {
    const isDebugMode = location.pathname === "/game" && location.search.includes("mode=debug");
    const isTestMode = location.pathname === "/game" && location.search.includes("mode=test");
    const isPvEMode = location.pathname === "/game" && location.search.includes("mode=pve");
    const isPvEOldMode = location.pathname === "/game" && location.search.includes("mode=pve_old");
    const isPvPOldMode = location.pathname === "/game" && location.search.includes("mode=pvp_old");

    // Handle PvE mode detection via query parameter
    if (path === "/game?mode=pve") {
      return `nav-button ${isPvEMode ? "nav-button--active" : "nav-button--inactive"}`;
    }

    // Handle PvE old mode detection via query parameter
    if (path === "/game?mode=pve_old") {
      return `nav-button ${isPvEOldMode ? "nav-button--active" : "nav-button--inactive"}`;
    }

    // Handle Debug mode detection via query parameter
    if (path === "/game?mode=debug") {
      return `nav-button ${isDebugMode ? "nav-button--active" : "nav-button--inactive"}`;
    }

    // Handle Test mode detection via query parameter
    if (path === "/game?mode=test") {
      return `nav-button ${isTestMode ? "nav-button--active" : "nav-button--inactive"}`;
    }

    // Handle PvP old mode detection via query parameter
    if (path === "/game?mode=pvp_old") {
      return `nav-button ${isPvPOldMode ? "nav-button--active" : "nav-button--inactive"}`;
    }

    // Handle PvP mode - only active when on /game WITHOUT Debug/PvE mode
    if (path === "/game") {
      const isPvPMode =
        location.pathname === "/game" &&
        !isDebugMode &&
        !isTestMode &&
        !isPvEMode &&
        !isPvEOldMode &&
        !isPvPOldMode;
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
        <button
          type="button"
          onClick={() => (window.location.href = "/game")}
          className={getButtonClass("/game")}
        >
          PvP
        </button>
        <button
          type="button"
          onClick={() => (window.location.href = "/game?mode=pvp_old")}
          className={getButtonClass("/game?mode=pvp_old")}
        >
          PvP Old
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
          onClick={() => (window.location.href = "/game?mode=pve_old")}
          className={getButtonClass("/game?mode=pve_old")}
        >
          PvE Old
        </button>
        <button
          type="button"
          onClick={() => (window.location.href = "/game?mode=test")}
          className={getButtonClass("/game?mode=test")}
        >
          Test
        </button>
        <button
          type="button"
          onClick={() => (window.location.href = "/game?mode=debug")}
          className={getButtonClass("/game?mode=debug")}
        >
          Debug
        </button>
        <button
          type="button"
          onClick={() => (window.location.href = "/replay")}
          className={getButtonClass("/replay")}
        >
          Replay
        </button>
      </nav>

      {onOpenSettings && (
        <button
          type="button"
          onClick={onOpenSettings}
          className="settings-button"
          title="Paramètres"
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
