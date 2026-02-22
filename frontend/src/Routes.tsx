// frontend/src/Routes.tsx

import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { getAuthSession } from "./auth/authStorage";
import { BoardWithAPI } from "./components/BoardWithAPI";
import { BoardReplay } from "./components/BoardReplay";
import AuthPage from "./pages/AuthPage";

const RootRedirect = () => {
  const authSession = getAuthSession();
  if (!authSession) {
    return <Navigate to="/auth" replace />;
  }
  return <Navigate to="/game?mode=pve" replace />;
};

const ProtectedGameRoute = () => {
  const location = useLocation();
  const authSession = getAuthSession();

  if (!authSession) {
    return <Navigate to="/auth" replace />;
  }

  const modeFromQuery = new URLSearchParams(location.search).get("mode");
  const requestedMode = modeFromQuery ?? "pve";
  const allowedModes = authSession.permissions.game_modes;
  // Allow *_old modes when old client-side session permissions are stale.
  // Backend remains the source of truth and will reject unauthorized starts.
  const isRequestedModeAllowed =
    allowedModes.includes(requestedMode) ||
    (requestedMode === "pvp_old" && allowedModes.includes("pvp")) ||
    (requestedMode === "pve_old" && allowedModes.includes("pve"));
  if (!isRequestedModeAllowed) {
    const fallbackMode = allowedModes.includes("pve")
      ? "pve"
      : allowedModes.includes("pve_old")
        ? "pve_old"
        : allowedModes[0];
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
