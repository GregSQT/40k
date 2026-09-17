/**
 * Helpers partagés des scénarios Playwright Couche C (smoke.spec.ts, move_drop.spec.ts).
 */
import { expect } from "@playwright/test";

export type Page = import("@playwright/test").Page;

export const BACKEND = process.env.PW_BASE_URL ?? "http://localhost:5001";
export const GAME_URL = "/game?mode=pvp_test";

/**
 * Lit l'état de partie côté backend, en direct, AVEC les deux en-têtes qu'il exige.
 *
 * POURQUOI CE HELPER EXISTE (mesuré le 2026-09-09). Trois appels de ce fichier posaient le cookie
 * de session sans l'en-tête anti-CSRF `X-W40K-Client`, qu'exige toute requête authentifiée par
 * cookie (`CSRF_HEADER_NAME` dans services/api_server.py). Ils recevaient donc 401 — et les tests
 * enchaînaient sur un `if (status !== 200) return;` qui les faisait passer POUR VERTS sans avoir
 * rien vérifié. Les deux invariants de parité front/back de ce fichier, ceux qui justifient à eux
 * seuls l'existence de la couche E2E, n'avaient jamais comparé quoi que ce soit.
 *
 * Le statut est ASSERTÉ ici plutôt que rendu à l'appelant : un état de partie illisible est une
 * panne du harnais, jamais une raison de rendre un test vert.
 */
export async function lireEtatDePartie(page: Page): Promise<Record<string, unknown>> {
  const cookies = await page.context().cookies();
  const sessionCookie = cookies.find((c) => c.name === "w40k_session");
  expect(
    sessionCookie,
    "aucun cookie de session : le global-setup n'a pas fait son travail"
  ).toBeDefined();

  const resp = await page.request.get(`${BACKEND}/api/game/state`, {
    headers: {
      Cookie: `w40k_session=${sessionCookie!.value}`,
      "X-W40K-Client": "playwright",
    },
  });
  expect(
    resp.status(),
    `/api/game/state a répondu ${resp.status()} : sans état de partie, ce test ne peut RIEN vérifier`
  ).toBe(200);

  // La réponse est ENVELOPPÉE : `{ success, game_state: {...}, game_log_history: [...] }`.
  // Les tests lisaient `state.move_activation_pool` au niveau RACINE, où cette clé n'existe pas :
  // ils obtenaient `undefined`, le `?? []` en faisait un pool vide, et la comparaison
  // « les cercles verts sont un sous-ensemble du pool » devenait vraie par construction —
  // tout ensemble contient l'ensemble vide. Combiné au 401 silencieux, cela faisait DEUX raisons
  // indépendantes pour ces tests de passer sans rien vérifier.
  const enveloppe = (await resp.json()) as Record<string, unknown>;
  const etat = enveloppe.game_state as Record<string, unknown> | undefined;
  expect(etat, "la réponse ne porte pas de `game_state` : contrat d'API changé ?").toBeDefined();
  return etat!;
}

/**
 * Amène la partie jusqu'à la phase `move`, PAR L'INTERFACE.
 *
 * POURQUOI CE HELPER EXISTE (mesuré le 2026-09-09). Les deux tests de parité front/back
 * s'intitulent « en phase move » et ne faisaient rien pour y arriver : la partie servie démarre en
 * phase `command`, où `move_activation_pool` est VIDE — légitimement. Ils comparaient donc l'ensemble
 * vide, ce qui est vrai par construction, et passaient sans rien vérifier.
 *
 * PAR L'INTERFACE et non par l'API : ces tests sont la seule vérification automatisée que
 * l'affichage correspond à ce que le moteur autorise. Y arriver en cliquant « End Phase » teste au
 * passage que ce chemin-là fonctionne ; y arriver par un appel direct testerait la parité d'un état
 * que l'utilisateur n'a peut-être aucun moyen d'atteindre.
 *
 * La boucle est BORNÉE et son épuisement est un échec : une phase qui n'avance pas est une panne,
 * pas une raison de comparer des ensembles vides.
 */
export async function fermerLesDecisionsEnAttente(page: Page): Promise<void> {
  // Le jeu OUVRE des modales au démarrage, et leur fond intercepte tous les clics — Playwright
  // le disait sans qu'on l'écoute : « <div role="presentation"> … intercepts pointer events ».
  // La capture d'échec du 2026-09-09 les montre : la décision Waaagh! de la phase command (08.04,
  // ORKS, boutons « Skip » / « Call the Waaagh! ») et le dialogue d'enregistrement du replay
  // (« Le replay nécessite l'enregistrement de la partie, qui n'est pas activé », Cancel/Activate).
  //
  // Y répondre fait PARTIE du parcours utilisateur : une partie ne quitte pas la phase command
  // tant que la décision de faction n'est pas prise. On choisit les réponses NEUTRES — passer la
  // Waaagh!, ne pas activer l'enregistrement — pour ne rien changer à ce que les tests mesurent.
  for (const libelle of ["Skip", "Cancel"]) {
    const bouton = page.getByRole("button", { name: libelle, exact: true });
    if (await bouton.isVisible().catch(() => false)) {
      await bouton.click();
      await page.waitForTimeout(300);
    }
  }
}

export async function amenerEnPhaseMove(page: Page): Promise<void> {
  const finDePhase = page.locator('[data-testid="end-phase-btn"]');
  await finDePhase.waitFor({ timeout: 30_000 });

  for (let essai = 0; essai < 4; essai += 1) {
    await fermerLesDecisionsEnAttente(page);
    const etat = await lireEtatDePartie(page);
    if (etat.phase === "move") return;
    await finDePhase.click();
    // Laisser l'aller-retour serveur puis le rendu PIXI se faire avant de relire la phase.
    await page.waitForTimeout(600);
  }

  const etatFinal = await lireEtatDePartie(page);
  expect(
    etatFinal.phase,
    "la phase n'atteint pas `move` après 4 clics sur « End Phase » : le bouton ou le moteur est en panne"
  ).toBe("move");
}
