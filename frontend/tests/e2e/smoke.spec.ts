/**
 * T12 — Scénarios Playwright Couche C.
 *
 * Prérequis :
 *   - Backend spawné sur PW_BASE_URL (défaut http://localhost:5001), sans reloader.
 *   - Frontend spawné sur PW_FRONTEND_URL (défaut http://localhost:5175),
 *     avec VITE_TEST_HOOKS=1 pour window.__W40K_TEST__.
 *   - global-setup.ts a injecté le cookie de session et le localStorage.
 *
 * Les tests utilisent le mode pvp_test (roster fix, plateau x1).
 */
import { expect, test } from "@playwright/test";

const BACKEND = process.env.PW_BASE_URL ?? "http://localhost:5001";
const GAME_URL = "/game?mode=pvp_test";

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
async function lireEtatDePartie(
  page: import("@playwright/test").Page
): Promise<Record<string, unknown>> {
  const cookies = await page.context().cookies();
  const sessionCookie = cookies.find((c) => c.name === "w40k_session");
  expect(sessionCookie, "aucun cookie de session : le global-setup n'a pas fait son travail")
    .toBeDefined();

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
async function fermerLesDecisionsEnAttente(page: import("@playwright/test").Page): Promise<void> {
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

async function amenerEnPhaseMove(page: import("@playwright/test").Page): Promise<void> {
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

// ---------------------------------------------------------------------------
// T12-1 — Smoke : board affiché, canvas non vide
// ---------------------------------------------------------------------------

test.describe("T12-1 — Smoke test PvP", () => {
  test("naviguer vers /game?mode=pvp_test affiche le canvas", async ({ page }) => {
    // Surveille les erreurs console
    const consoleErrors: string[] = [];
    page.on("console", (msg) => {
      if (msg.type() === "error") consoleErrors.push(msg.text());
    });

    await page.goto(GAME_URL);

    // Le canvas PIXI est présent dans le DOM une fois le board initialisé
    const canvas = page.locator("canvas").first();
    await expect(canvas).toBeVisible({ timeout: 30_000 });

    // Le canvas a des dimensions non nulles
    const box = await canvas.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.width).toBeGreaterThan(100);
    expect(box!.height).toBeGreaterThan(100);

    // Aucune erreur console non attendue (PIXI WebGL → canvas 2D est toléré en headless)
    const criticalErrors = consoleErrors.filter(
      (e) => !e.includes("WebGL") && !e.includes("OffscreenCanvas") && !e.includes("ResizeObserver")
    );
    expect(criticalErrors).toHaveLength(0);
  });

  test("l'API backend répond en JSON sur /api/game/state", async ({ page, request }) => {
    // Récupère le cookie de session du contexte du test
    const cookies = await page.context().cookies();
    const sessionCookie = cookies.find((c) => c.name === "w40k_session");
    expect(sessionCookie).toBeDefined();

    const resp = await request.get(`${BACKEND}/api/game/state`, {
      headers: {
        Cookie: `w40k_session=${sessionCookie!.value}`,
        // Le backend EXIGE cet en-tête sur toute requête authentifiée par cookie
        // (`CSRF_HEADER_NAME` dans services/api_server.py) : sans lui, il répond 401 avec
        // « Missing X-W40K-Client header on cookie-authenticated request ». Le front le pose
        // dans `apiFetch`, mais ce test-ci parle au backend en direct, hors du client.
        // Mesuré le 2026-09-09, à la première exécution réelle de cette couche : c'est le
        // 401 qui faisait échouer ce test, pas l'état de la partie.
        "X-W40K-Client": "playwright",
      },
    });
    // La partie peut ne pas encore être démarrée (404) ou déjà active (200)
    expect([200, 404]).toContain(resp.status());
  });
});

// ---------------------------------------------------------------------------
// T12-2 — Phase buttons rendus dans le TurnPhaseTracker
// ---------------------------------------------------------------------------

test.describe("T12-2 — TurnPhaseTracker DOM", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto(GAME_URL);
    // Attendre que le board soit prêt (TurnPhaseTracker présente les boutons de phase)
    await page.locator('[data-testid="phase-btn-move"]').waitFor({ timeout: 30_000 });
  });

  test("les boutons de phase command/move/shoot/charge/fight sont présents", async ({ page }) => {
    for (const phase of ["command", "move", "shoot", "charge", "fight"]) {
      await expect(page.locator(`[data-testid="phase-btn-${phase}"]`)).toBeVisible();
    }
  });

  test("les boutons de tour Round 1..N sont présents", async ({ page }) => {
    const turn1 = page.locator('[data-testid="turn-btn-1"]');
    await expect(turn1).toBeVisible();
  });

  test("les boutons P1 et P2 sont présents", async ({ page }) => {
    await expect(page.locator('[data-testid="player-btn-1"]')).toBeVisible();
    await expect(page.locator('[data-testid="player-btn-2"]')).toBeVisible();
  });
});

// ---------------------------------------------------------------------------
// T12-3 — Hook window.__W40K_TEST__ exposé en mode VITE_TEST_HOOKS=1
// ---------------------------------------------------------------------------

test.describe("T12-3 — Hook de test (VITE_TEST_HOOKS=1)", () => {
  test("window.__W40K_TEST__ est défini si le front est lancé avec VITE_TEST_HOOKS=1", async ({
    page,
  }) => {
    // NAVIGUER D'ABORD. Ce test interrogeait `window` SANS avoir chargé la moindre page : il
    // lisait donc l'`about:blank` d'avant navigation, où le hook n'a évidemment jamais été posé.
    // Sa garde le faisait alors se skipper — à chaque exécution, depuis toujours (mesuré le
    // 2026-09-09 : bilan systématique « 13 passed, 1 skipped »). Il était le seul test du fichier
    // à ne pas appeler `page.goto`, pendant que ses voisins lisaient ce même hook avec succès.
    await page.goto(GAME_URL);
    await page.locator("canvas").first().waitFor({ timeout: 30_000 });

    // Et pas de `test.skip` ici, contrairement aux autres tests du fichier. Celui-ci a le hook
    // POUR SUJET : se skipper quand son sujet est absent, c'est ne jamais rien vérifier. L'en-tête
    // de ce fichier pose `VITE_TEST_HOOKS=1` comme prérequis ; son absence est donc une panne du
    // harnais, et une panne se signale.
    const hookExists = await page.evaluate(() => {
      const hook = (window as Record<string, unknown>).__W40K_TEST__;
      return hook !== null && typeof hook === "object";
    });
    expect(
      hookExists,
      "window.__W40K_TEST__ absent : le front n'a pas été démarré avec VITE_TEST_HOOKS=1, " +
        "et les tests qui lisent ce hook vont tous se skipper en cascade"
    ).toBe(true);
  });

  test("greenCircleUnitIds est un Set exposé par le hook", async ({ page }) => {
    await page.goto(GAME_URL);
    await page.locator("canvas").first().waitFor({ timeout: 30_000 });

    const isHookEnabled = await page.evaluate(() => {
      return typeof (window as Record<string, unknown>).__W40K_TEST__ !== "undefined";
    });
    if (!isHookEnabled) {
      test.skip(true, "VITE_TEST_HOOKS=1 non activé");
    }

    const hasSet = await page.evaluate(() => {
      const hook = (window as Record<string, unknown>).__W40K_TEST__ as
        | Record<string, unknown>
        | undefined;
      return hook?.greenCircleUnitIds instanceof Set;
    });
    expect(hasSet).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// T12-4 — Cohérence cercles verts vs pool backend
// ---------------------------------------------------------------------------

/**
 * ⚠️ CES DEUX TESTS (T12-4 et T12-6) SONT ROUGES, ET C'EST UN PROGRÈS.
 *
 * Ils passaient depuis leur écriture sans jamais rien comparer — pour trois raisons cumulées,
 * toutes mesurées le 2026-09-09 :
 *   1. l'appel à `/api/game/state` omettait l'en-tête anti-CSRF et recevait 401 ;
 *   2. un `if (status !== 200) return;` faisait alors SORTIR le test sans assertion, donc vert ;
 *   3. le pool était lu au niveau racine, alors que l'API l'enveloppe dans `game_state` — d'où un
 *      `undefined`, un `?? []`, et une inclusion vraie par construction (∅ ⊆ tout).
 *
 * Les trois sont corrigés. Reste le quatrième, qui n'est pas un accident technique mais un défaut
 * de CONCEPTION : le test s'intitule « en phase move » et ne fait jamais avancer la partie
 * jusqu'à cette phase. Mesuré : la partie servie est en phase `command`, tour 1, avec 11 unités
 * et un `move_activation_pool` VIDE — légitimement vide, puisqu'on n'est pas en phase de
 * mouvement. La comparaison n'a donc rien à comparer.
 *
 * Le rendre vert demande de décider COMMENT amener la partie en phase move — par l'interface
 * (cliquer, ce qui teste aussi le chemin utilisateur) ou par l'API (plus direct, mais le test ne
 * prouve alors plus rien sur l'UI. Cette décision n'est pas prise ici : un rouge qui dit la
 * vérité vaut mieux que le vert vide qu'il remplace.
 */
test.describe("T12-4 — Cercles verts == pool backend", () => {
  test("en phase move, les unitIds cerclés sont un sous-ensemble du move_activation_pool", async ({
    page,
  }) => {
    await page.goto(GAME_URL);
    await page.locator("canvas").first().waitFor({ timeout: 30_000 });

    // Attendre les boutons du tracker, PUIS amener réellement la partie en phase move : la
    // présence du bouton `phase-btn-move` ne dit pas qu'on Y EST, seulement qu'il est affiché.
    await page.locator('[data-testid="phase-btn-move"]').waitFor({ timeout: 30_000 });
    await amenerEnPhaseMove(page);

    const isHookEnabled = await page.evaluate(() => {
      return typeof (window as Record<string, unknown>).__W40K_TEST__ !== "undefined";
    });
    if (!isHookEnabled) {
      test.skip(true, "VITE_TEST_HOOKS=1 non activé");
    }

    // Lire les cercles verts rendus via le hook
    const greenIds = await page.evaluate(() => {
      const hook = (window as Record<string, unknown>).__W40K_TEST__ as
        | Record<string, unknown>
        | undefined;
      if (!hook) return [];
      return [...(hook.greenCircleUnitIds as Set<string>)].map(Number);
    });

    // Lire le pool move backend. Le statut est asserté dans le helper : un 401 silencieux
    // faisait passer ce test sans qu'il compare quoi que ce soit.
    const state = await lireEtatDePartie(page);
    const pool: number[] = ((state.move_activation_pool as unknown[]) ?? []).map(Number);

    // Un pool VIDE rendrait l'inclusion vraie par construction — tout ensemble contient
    // l'ensemble vide. Le scénario de test doit donc offrir au moins une unité éligible, sinon
    // ce test est un vert vacant : il passerait quel que soit l'état des cercles.
    expect(
      pool.length,
      "aucune unité éligible en phase move : ce test ne prouverait rien (∅ ⊆ tout)"
    ).toBeGreaterThan(0);

    // Chaque ID cerclé doit être dans le pool
    for (const id of greenIds) {
      expect(pool).toContain(id);
    }
  });
});

// ---------------------------------------------------------------------------
// T12-5 — Régression visuelle : screenshots canoniques (~10 états)
// ---------------------------------------------------------------------------

test.describe("T12-5 — Régression visuelle", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto(GAME_URL);
    await page.locator("canvas").first().waitFor({ timeout: 30_000 });
    // Stabiliser le rendu PIXI (animation frame)
    await page.waitForTimeout(500);
  });

  test("screenshot board initial", async ({ page }) => {
    await expect(page).toHaveScreenshot("board-initial.png", {
      maxDiffPixelRatio: 0.02,
    });
  });
});

// ---------------------------------------------------------------------------
// T12-6 — Preview move hexes == valid_move_destinations_pool
// ---------------------------------------------------------------------------

test.describe("T12-6 — Preview move hexes via hook", () => {
  test("movePreviewHexes est un Set exposé par le hook", async ({ page }) => {
    await page.goto(GAME_URL);
    await page.locator("canvas").first().waitFor({ timeout: 30_000 });

    const isHookEnabled = await page.evaluate(() => {
      return typeof (window as Record<string, unknown>).__W40K_TEST__ !== "undefined";
    });
    if (!isHookEnabled) {
      test.skip(true, "VITE_TEST_HOOKS=1 non activé");
    }

    const hasSet = await page.evaluate(() => {
      const hook = (window as Record<string, unknown>).__W40K_TEST__ as
        | Record<string, unknown>
        | undefined;
      return hook?.movePreviewHexes instanceof Set;
    });
    expect(hasSet).toBe(true);
  });

  test("après clic sur une unité éligible, movePreviewHexes ⊆ valid_move_destinations_pool", async ({
    page,
  }) => {
    await page.goto(GAME_URL);
    await page.locator("canvas").first().waitFor({ timeout: 30_000 });

    const isHookEnabled = await page.evaluate(() => {
      return typeof (window as Record<string, unknown>).__W40K_TEST__ !== "undefined";
    });
    if (!isHookEnabled) {
      test.skip(true, "VITE_TEST_HOOKS=1 non activé");
    }

    // Sans cette étape, la partie est en phase `command` : aucune unité n'est activable, donc
    // aucune prévisualisation à comparer (cf. `amenerEnPhaseMove`).
    await amenerEnPhaseMove(page);

    // Chaque abandon silencieux de ce test était un vert vacant : il sortait sans assertion et
    // comptait comme réussi. Une précondition non remplie est désormais un ÉCHEC — soit le
    // harnais est en panne, soit le scénario ne met pas en scène ce que ce test prétend vérifier.
    const state = await lireEtatDePartie(page);
    const pool: string[] = (state.move_activation_pool as string[]) ?? [];
    expect(pool.length, "aucune unité éligible : rien à activer, donc rien à prévisualiser")
      .toBeGreaterThan(0);

    // Prendre la première unité du pool et récupérer sa position
    const units: Array<{ id: number; col: number; row: number }> =
      (state.units as Array<{ id: number; col: number; row: number }>) ?? [];
    const firstEligible = units.find((u) => pool.includes(String(u.id)));
    expect(firstEligible, "le pool nomme une unité absente de `units` : états incohérents")
      .toBeDefined();

    // Cliquer sur l'unité via hexToScreenCoords (col/row passés depuis Node, pas besoin de __W40K_UNITS__)
    const coords = await page.evaluate(
      ({ col, row }: { col: number; row: number }) => {
        const hook = (window as Record<string, unknown>).__W40K_TEST__ as
          | Record<string, unknown>
          | undefined;
        if (!hook) return null;
        return (hook.hexToScreenCoords as (col: number, row: number) => { x: number; y: number })(
          col,
          row
        );
      },
      { col: firstEligible!.col, row: firstEligible!.row }
    );

    // Sans coordonnées, il n'y a pas de clic — donc pas de prévisualisation à comparer. C'était
    // le troisième abandon muet de ce test ; c'est désormais un échec, car un canvas non
    // dimensionné est une panne du rendu, pas une dispense de vérifier.
    expect(coords, "hexToScreenCoords n'a rien rendu : le hook ou le canvas est en panne")
      .not.toBeNull();
    expect(
      coords!.x !== 0 || coords!.y !== 0,
      "hexToScreenCoords rend (0,0) : le canvas n'est pas encore dimensionné"
    ).toBe(true);

    await page.mouse.click(coords!.x, coords!.y);
    // Attendre que le hook mette à jour movePreviewHexes (rendu PIXI + useEffect)
    await page.waitForTimeout(800);

    const stateAfter = await lireEtatDePartie(page);
    const apiPool: Array<{ col: number; row: number }> =
      (stateAfter.valid_move_destinations_pool as Array<{ col: number; row: number }>) ?? [];

    // Dernier abandon muet du fichier. Un pool de destinations vide après activation d'une unité
    // ÉLIGIBLE est une anomalie du moteur — et il rendrait de toute façon la comparaison vide,
    // donc vraie sans rien prouver.
    expect(
      apiPool.length,
      "aucune destination valide après activation : le moteur n'a rien proposé, la comparaison serait vide"
    ).toBeGreaterThan(0);

    const apiHexKeys = new Set(apiPool.map((h) => `${h.col},${h.row}`));

    // Lire movePreviewHexes depuis le hook
    const hookHexes = await page.evaluate(() => {
      const hook = (window as Record<string, unknown>).__W40K_TEST__ as
        | Record<string, unknown>
        | undefined;
      if (!hook) return [];
      return [...(hook.movePreviewHexes as Set<string>)];
    });

    // Chaque hex peint par le front doit être dans le pool API
    for (const hk of hookHexes) {
      expect(apiHexKeys.has(hk)).toBe(true);
    }
  });
});

// ---------------------------------------------------------------------------
// T12-7 — blinkTargetUnitIds (preview tir)
// ---------------------------------------------------------------------------

test.describe("T12-7 — blinkTargetUnitIds exposé par le hook", () => {
  test("blinkTargetUnitIds est un Set exposé par le hook", async ({ page }) => {
    await page.goto(GAME_URL);
    await page.locator("canvas").first().waitFor({ timeout: 30_000 });

    const isHookEnabled = await page.evaluate(() => {
      return typeof (window as Record<string, unknown>).__W40K_TEST__ !== "undefined";
    });
    if (!isHookEnabled) {
      test.skip(true, "VITE_TEST_HOOKS=1 non activé");
    }

    const hasSet = await page.evaluate(() => {
      const hook = (window as Record<string, unknown>).__W40K_TEST__ as
        | Record<string, unknown>
        | undefined;
      return hook?.blinkTargetUnitIds instanceof Set;
    });
    expect(hasSet).toBe(true);
  });

  test("currentMode est exposé par le hook", async ({ page }) => {
    await page.goto(GAME_URL);
    await page.locator("canvas").first().waitFor({ timeout: 30_000 });

    const isHookEnabled = await page.evaluate(() => {
      return typeof (window as Record<string, unknown>).__W40K_TEST__ !== "undefined";
    });
    if (!isHookEnabled) {
      test.skip(true, "VITE_TEST_HOOKS=1 non activé");
    }

    const currentMode = await page.evaluate(() => {
      const hook = (window as Record<string, unknown>).__W40K_TEST__ as
        | Record<string, unknown>
        | undefined;
      return hook?.currentMode;
    });
    // En phase move, le mode initial est "select"
    expect(typeof currentMode).toBe("string");
    expect(currentMode).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// T12-8 — hexToScreenCoords helper (conversion hex → pixel écran)
// ---------------------------------------------------------------------------

test.describe("T12-8 — hexToScreenCoords helper", () => {
  test("hexToScreenCoords retourne un objet {x, y} non nul quand le board est chargé", async ({
    page,
  }) => {
    await page.goto(GAME_URL);
    await page.locator('[data-testid="board-canvas-container"]').waitFor({ timeout: 30_000 });
    await page.waitForTimeout(500); // laisser PIXI initialiser le canvas

    const isHookEnabled = await page.evaluate(() => {
      return typeof (window as Record<string, unknown>).__W40K_TEST__ !== "undefined";
    });
    if (!isHookEnabled) {
      test.skip(true, "VITE_TEST_HOOKS=1 non activé");
    }

    const coords = await page.evaluate(() => {
      const hook = (window as Record<string, unknown>).__W40K_TEST__ as
        | Record<string, unknown>
        | undefined;
      if (!hook?.hexToScreenCoords) return null;
      return (hook.hexToScreenCoords as (col: number, row: number) => { x: number; y: number })(
        5,
        5
      );
    });

    expect(coords).not.toBeNull();
    // Le canvas est affiché : x et y doivent être > 0
    expect(coords!.x).toBeGreaterThan(0);
    expect(coords!.y).toBeGreaterThan(0);
  });
});
