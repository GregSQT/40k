import { clearAuthSession, getAuthSession } from "../auth/authStorage";

/**
 * Client HTTP unique pour toute l'API backend.
 *
 * Le backend ferme l'intégralité de `/api/*` par défaut (`before_request` global). Depuis F13,
 * la session du navigateur est portée par un cookie `HttpOnly` que le navigateur joint tout
 * seul : il n'y a plus de token à attacher ici, et il n'y en a plus non plus à voler dans le
 * `localStorage` (cf. `auth/authStorage.ts`).
 *
 * Ce que ce helper attache à la place, c'est l'en-tête anti-CSRF. Un cookie part avec TOUTE
 * requête vers l'origine, y compris déclenchée par un autre site ; le backend n'accepte une
 * authentification par cookie que si cet en-tête est présent, ce qu'un `<form>` cross-site ne
 * peut pas faire. Passer par ce helper reste donc la seule garantie que rien ne soit oublié —
 * un `fetch` écrit à la main recevrait 401.
 *
 * `/api/auth/login` n'a pas de session à présenter — c'est l'appel qui l'obtient : il reste en
 * `fetch` direct dans la page d'authentification.
 */

/** Préfixe de toutes les routes backend. Déclaré ici, au même endroit que le client qui
 * les appelle, plutôt que redéclaré dans chaque module appelant. */
export const API_BASE = "/api";

/**
 * En-tête anti-CSRF exigé par le backend sur toute requête authentifiée PAR COOKIE
 * (`CSRF_HEADER_NAME` dans `services/api_server.py` — les deux valeurs doivent rester égales).
 *
 * Ce n'est pas un secret : sa seule présence prouve que la requête vient de code JavaScript de
 * notre origine. Un formulaire cross-site ne peut poser aucun en-tête personnalisé, et un
 * `fetch` cross-site qui en pose déclenche un préflight que la liste d'origines du backend
 * refuse.
 */
const CSRF_HEADER = "X-W40K-Client";

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
  // Le contexte local ne PROUVE plus la session — le cookie `HttpOnly` seul l'authentifie, et
  // JavaScript ne peut pas le lire. Son absence reste néanmoins concluante dans un sens : elle
  // signifie qu'aucun login n'a eu lieu sur ce navigateur, donc qu'il n'y a pas de cookie non
  // plus. Court-circuiter ici évite un aller-retour réseau garanti 401.
  const session = getAuthSession();
  if (!session) {
    return rejectSession();
  }

  const headers = new Headers(init?.headers);
  headers.set(CSRF_HEADER, "web");

  // `same-origin` est déjà le défaut de `fetch`, mais il est écrit : c'est lui qui joint le
  // cookie de session, et le supprimer déconnecterait silencieusement toute l'application.
  const response = await fetch(input, { ...init, headers, credentials: "same-origin" });

  if (response.status === 401) {
    return rejectSession();
  }

  return response;
};
