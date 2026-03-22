export interface AuthPermissions {
  game_modes: string[];
  options: {
    show_advance_warning: boolean;
    auto_weapon_selection: boolean;
  };
}

export interface AuthSession {
  token: string;
  user: {
    id: number;
    login: string;
    profile: string;
  };
  permissions: AuthPermissions;
  default_redirect_mode: string;
  tutorial_completed: boolean;
}

const AUTH_SESSION_STORAGE_KEY = "w40k_auth_session";

export const getAuthSession = (): AuthSession | null => {
  const rawSession = localStorage.getItem(AUTH_SESSION_STORAGE_KEY);
  if (!rawSession) {
    return null;
  }

  try {
    const parsedSession = JSON.parse(rawSession) as AuthSession;
    if (!parsedSession.token || !parsedSession.user || !parsedSession.permissions) {
      return null;
    }
    return {
      ...parsedSession,
      tutorial_completed: parsedSession.tutorial_completed ?? true,
    };
  } catch {
    return null;
  }
};

export const saveAuthSession = (session: AuthSession): void => {
  localStorage.setItem(AUTH_SESSION_STORAGE_KEY, JSON.stringify(session));
};

export const clearAuthSession = (): void => {
  localStorage.removeItem(AUTH_SESSION_STORAGE_KEY);
};

const API_BASE = "/api";

export async function markTutorialComplete(): Promise<void> {
  const session = getAuthSession();
  if (!session?.token) return;

  const res = await fetch(`${API_BASE}/auth/tutorial-complete`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${session.token}`,
      "Content-Type": "application/json",
    },
  });
  if (!res.ok) throw new Error("Failed to mark tutorial complete");

  saveAuthSession({ ...session, tutorial_completed: true, default_redirect_mode: "pve" });
}
