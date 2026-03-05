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
  if (requestedMode === "replay") {
    return <Navigate to="/replay" replace />;
  }
  const allowedModes = authSession.permissions.game_modes;
  const isRequestedModeAllowed =
    allowedModes.includes(requestedMode) ||
    ((requestedMode === "pvp_test" || requestedMode === "pve_test") && allowedModes.includes("test"));
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
