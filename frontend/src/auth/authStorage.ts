/**
 * Contexte utilisateur du navigateur — SANS le token de session (F13).
 *
 * Le token vivait ici, en `localStorage` : lisible par tout script de la page, donc exfiltrable
 * par une seule XSS, pour sept jours d'accès complet. Il est désormais porté par un cookie
 * `HttpOnly` posé par le backend (`SESSION_COOKIE_NAME` dans `services/api_server.py`), que
 * JavaScript ne peut pas lire. Ce module ne conserve plus que ce qui n'est pas un secret :
 * l'identité affichée et les permissions, qui servent au ROUTAGE côté client.
 *
 * Ces permissions ne sont pas une autorisation : le backend les revalide à chaque requête dans
 * sa porte `before_request`. Les falsifier ici ne donne accès à rien, seulement à un écran qui
 * renverra 403.
 *
 * Conséquence assumée : ce contexte peut survivre au cookie (session expirée, révoquée depuis
 * un autre poste). L'application croit alors l'utilisateur connecté jusqu'au premier appel API,
 * qui répond 401 et déclenche le retour au login (`apiFetch`). C'est exactement ce qui se
 * passait déjà avec un token expiré — aucun chemin nouveau.
 */

export interface AuthPermissions {
  game_modes: string[];
  options: {
    show_advance_warning: boolean;
    auto_weapon_selection: boolean;
  };
}

export interface AuthSession {
  user: {
    id: number;
    login: string;
    profile: string;
  };
  permissions: AuthPermissions;
  default_redirect_mode: string;
}

const AUTH_SESSION_STORAGE_KEY = "w40k_auth_session_v2";

/**
 * Clé de l'ancien format, qui CONTENAIT le token.
 *
 * La clé est changée plutôt que réutilisée : relire l'ancienne entrée ferait rentrer un token
 * dans une variable JavaScript, soit précisément ce que F13 ferme. Et la laisser en place
 * laisserait le token dormir dans le `localStorage` des postes déjà connectés, où il reste
 * valide jusqu'à sept jours — la migration doit l'effacer, pas seulement cesser de le lire.
 */
const LEGACY_AUTH_SESSION_STORAGE_KEY = "w40k_auth_session";

const purgeLegacySession = (): void => {
  localStorage.removeItem(LEGACY_AUTH_SESSION_STORAGE_KEY);
};

// À l'import du module, donc avant tout rendu : un poste qui rouvre l'application après la
// migration perd son ancien token même s'il ne se reconnecte jamais.
purgeLegacySession();

export const getAuthSession = (): AuthSession | null => {
  const rawSession = localStorage.getItem(AUTH_SESSION_STORAGE_KEY);
  if (!rawSession) {
    return null;
  }

  try {
    const parsedSession = JSON.parse(rawSession) as AuthSession;
    if (!parsedSession.user || !parsedSession.permissions) {
      return null;
    }
    return parsedSession;
  } catch {
    return null;
  }
};

export const saveAuthSession = (session: AuthSession): void => {
  purgeLegacySession();
  localStorage.setItem(AUTH_SESSION_STORAGE_KEY, JSON.stringify(session));
};

export const clearAuthSession = (): void => {
  localStorage.removeItem(AUTH_SESSION_STORAGE_KEY);
  purgeLegacySession();
};
