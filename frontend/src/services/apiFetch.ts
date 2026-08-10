import { clearAuthSession, getAuthSession } from "../auth/authStorage";

/**
 * Client HTTP unique pour toute l'API backend.
 *
 * Le backend ferme l'intégralité de `/api/*` par défaut (`before_request` global) : tout
 * appel doit porter `Authorization: Bearer <token>`. Passer par ce helper est la seule
 * garantie que ce header ne soit pas oublié — ajouter le header à la main sur chaque
 * `fetch` rouvrirait la faille au premier appel ajouté ensuite.
 *
 * `/api/auth/login` n'a pas de token à envoyer — c'est l'appel qui l'obtient : il reste en
 * `fetch` direct dans la page d'authentification.
 */

/** Préfixe de toutes les routes backend. Déclaré ici, au même endroit que le client qui
 * les appelle, plutôt que redéclaré dans chaque module appelant. */
export const API_BASE = "/api";

const UNAUTHORIZED_EVENT = "w40k:session-expired";

/**
 * Émis quand le backend rejette la session (401). L'application écoute cet événement pour
 * renvoyer l'utilisateur sur l'écran de login, sans que chaque appelant ait à gérer le cas.
 */
export const onSessionExpired = (handler: () => void): (() => void) => {
  window.addEventListener(UNAUTHORIZED_EVENT, handler);
  return () => window.removeEventListener(UNAUTHORIZED_EVENT, handler);
};

/** Session absente et session rejetée par le serveur sont la même panne côté utilisateur :
 * les deux passent par ici, pour un unique canal de traitement (retour au login). */
const rejectSession = (): Response => {
  clearAuthSession();
  window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
  return new Response(JSON.stringify({ success: false, error: "Session expirée" }), {
    status: 401,
    headers: { "Content-Type": "application/json" },
  });
};

/**
 * Déconnexion : révoque la session CÔTÉ SERVEUR avant de l'oublier côté navigateur.
 *
 * Effacer le `localStorage` seul ne déconnecte rien — le token reste valide jusqu'à son
 * expiration (sept jours), et quiconque en a une copie continue d'accéder à l'API. C'est
 * l'appel serveur qui déconnecte ; l'effacement local n'en est que la conséquence visible.
 *
 * L'effacement local a lieu même si l'appel serveur échoue : l'utilisateur a demandé à
 * partir, le laisser connecté sur un poste qu'il quitte serait pire que de laisser une
 * session vivante côté serveur. L'échec est remonté en console, pas masqué.
 *
 * La sortie passe par `rejectSession()`, le canal UNIQUE du module : déconnexion volontaire
 * et session rejetée par le serveur aboutissent au même endroit. Effacer le storage sans
 * émettre l'événement obligerait chaque appelant à rediriger lui-même, et il existerait deux
 * chemins « fin de session → écran de login » à garder synchronisés.
 */
export const logoutSession = async (): Promise<void> => {
  try {
    const response = await apiFetch(`${API_BASE}/auth/logout`, { method: "POST" });
    if (!response.ok) {
      console.error(`Logout serveur refusé (HTTP ${response.status}) : session non révoquée`);
    }
  } catch (error) {
    console.error("Logout serveur injoignable : session non révoquée", error);
  } finally {
    rejectSession();
  }
};

export const apiFetch = async (input: string, init?: RequestInit): Promise<Response> => {
  const session = getAuthSession();
  if (!session) {
    return rejectSession();
  }

  const headers = new Headers(init?.headers);
  headers.set("Authorization", `Bearer ${session.token}`);

  const response = await fetch(input, { ...init, headers });

  if (response.status === 401) {
    return rejectSession();
  }

  return response;
};
