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
    return parsedSession;
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
