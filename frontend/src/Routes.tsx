// frontend/src/Routes.tsx

import { useEffect } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { getAuthSession } from "./auth/authStorage";
import { BoardReplay } from "./components/BoardReplay";
import { BoardWithAPI } from "./components/BoardWithAPI";
import AuthPage from "./pages/AuthPage";
import { onSessionExpired } from "./services/apiFetch";

/**
 * Renvoie sur l'écran de login dès que le backend rejette la session (401).
 * Les routes protégées ne lisent la session qu'au rendu : sans ce watcher, une session
 * invalidée côté serveur laisserait l'utilisateur sur un écran de jeu inerte.
 */
const SessionExpiryWatcher = () => {
  const navigate = useNavigate();
  useEffect(() => onSessionExpired(() => navigate("/auth", { replace: true })), [navigate]);
  return null;
};

const RootRedirect = () => {
  const authSession = getAuthSession();
  if (!authSession) {
    return <Navigate to="/auth" replace />;
  }
  return <Navigate to={`/game?mode=${authSession.default_redirect_mode}`} replace />;
};

const ProtectedGameRoute = () => {
  const location = useLocation();
  const authSession = getAuthSession();

  if (!authSession) {
    return <Navigate to="/auth" replace />;
  }

  const modeFromQuery = new URLSearchParams(location.search).get("mode");
  const requestedMode = modeFromQuery ?? "pve";

  if (requestedMode === "replay") {
    return <Navigate to="/replay" replace />;
  }
  const allowedModes = authSession.permissions.game_modes;
  const isRequestedModeAllowed =
    allowedModes.includes(requestedMode) ||
    (requestedMode === "endless_duty" && allowedModes.includes("pve")) ||
    ((requestedMode === "pvp_test" || requestedMode === "pve_test") &&
      allowedModes.includes("test"));
  if (!isRequestedModeAllowed) {
    const fallbackMode = allowedModes.includes("pve")
      ? "pve"
      : allowedModes.includes("pvp")
        ? "pvp"
        : allowedModes.includes("test")
          ? "pvp_test"
          : null;
    if (!fallbackMode) {
      throw new Error("No authorized game mode configured for current user");
    }
    return <Navigate to={`/game?mode=${fallbackMode}`} replace />;
  }

  return <BoardWithAPI />;
};

const ProtectedReplayRoute = () => {
  const authSession = getAuthSession();
  if (!authSession) {
    return <Navigate to="/auth" replace />;
  }
  return <BoardReplay />;
};

export default function App() {
  return (
    <BrowserRouter>
      <SessionExpiryWatcher />
      <Routes>
        <Route path="/auth" element={<AuthPage />} />
        <Route path="/game" element={<ProtectedGameRoute />} />
        <Route path="/replay" element={<ProtectedReplayRoute />} />
        <Route path="/" element={<RootRedirect />} />
        <Route path="*" element={<RootRedirect />} />
      </Routes>
    </BrowserRouter>
  );
}
