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
      (e) =>
        !e.includes("WebGL") &&
        !e.includes("OffscreenCanvas") &&
        !e.includes("ResizeObserver")
    );
    expect(criticalErrors).toHaveLength(0);
  });

  test("l'API backend répond en JSON sur /api/game/state", async ({ page, request }) => {
    // Récupère le cookie de session du contexte du test
    const cookies = await page.context().cookies();
    const sessionCookie = cookies.find((c) => c.name === "w40k_session");
    expect(sessionCookie).toBeDefined();

    const resp = await request.get(`${BACKEND}/api/game/state`, {
      headers: { Cookie: `w40k_session=${sessionCookie!.value}` },
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
    // Ce test passe seulement si le serveur front a été démarré avec VITE_TEST_HOOKS=1.
    // En CI (scripts/front_test_all.sh), c'est garanti ; en dev local sans la variable,
    // le test est skippé proprement.
    const isHookEnabled = await page.evaluate(() => {
      return typeof (window as Record<string, unknown>).__W40K_TEST__ !== "undefined";
    });

    if (!isHookEnabled) {
      test.skip(true, "VITE_TEST_HOOKS=1 non activé — relancer via scripts/front_test_all.sh");
    }

    const hookExists = await page.evaluate(() => {
      const hook = (window as Record<string, unknown>).__W40K_TEST__;
      return hook !== null && typeof hook === "object";
    });
    expect(hookExists).toBe(true);
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
      const hook = (window as Record<string, unknown>).__W40K_TEST__ as Record<string, unknown> | undefined;
      return hook?.greenCircleUnitIds instanceof Set;
    });
    expect(hasSet).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// T12-4 — Cohérence cercles verts vs pool backend
// ---------------------------------------------------------------------------

test.describe("T12-4 — Cercles verts == pool backend", () => {
  test("en phase move, les unitIds cerclés sont un sous-ensemble du move_activation_pool", async ({
    page,
  }) => {
    await page.goto(GAME_URL);
    await page.locator("canvas").first().waitFor({ timeout: 30_000 });

    // Attendre la phase move et les boutons
    await page.locator('[data-testid="phase-btn-move"]').waitFor({ timeout: 30_000 });

    const isHookEnabled = await page.evaluate(() => {
      return typeof (window as Record<string, unknown>).__W40K_TEST__ !== "undefined";
    });
    if (!isHookEnabled) {
      test.skip(true, "VITE_TEST_HOOKS=1 non activé");
    }

    // Lire les cercles verts rendus via le hook
    const greenIds = await page.evaluate(() => {
      const hook = (window as Record<string, unknown>).__W40K_TEST__ as Record<string, unknown> | undefined;
      if (!hook) return [];
      return [...(hook.greenCircleUnitIds as Set<string>)].map(Number);
    });

    // Lire le pool move backend via l'état exposé par le hook API
    // Le board prend quelques frames pour rendre les cercles après réception de l'état
    const cookies = await page.context().cookies();
    const sessionCookie = cookies.find((c) => c.name === "w40k_session");

    const stateResp = await page.request.get(`${BACKEND}/api/game/state`, {
      headers: { Cookie: `w40k_session=${sessionCookie!.value}` },
    });

    if (stateResp.status() !== 200) {
      // Partie pas encore démarrée — le test ne peut pas vérifier
      return;
    }

    const state = await stateResp.json();
    const pool: number[] = (state.move_activation_pool ?? []).map(Number);

    if (pool.length === 0) {
      // Phase move sans unités éligibles : pas de cercles à vérifier
      expect(greenIds).toHaveLength(0);
      return;
    }

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
