/**
 * Couche C — Pose d'une escouade en « unit move » (movePreview).
 *
 * Invariant : le clic qui pose l'escouade ne fait QUE poser. Il ne sélectionne pas la figurine
 * qui vient d'atterrir sous le curseur.
 *
 * Mécanisme couvert (mesuré le 2026-09-17, Chromium sous charge) : PIXI écoute le pointerdown en
 * capture sur le canvas et confirme la pose via le sprite fantôme ; React bascule en
 * `perModelMove` pendant la même propagation et installe l'écouteur de sélection de figurine
 * (bubble, canvas), qui recevait le MÊME événement et activait la figurine sous le curseur.
 * Une garde temporelle de 300 ms masquait le défaut tant que la transition rendait vite.
 *
 * Signature observable : `move_model_destinations` est la seule requête émise par la sélection
 * d'une figurine en phase move (`handleSelectModelForMove`). Après la pose, elle ne doit pas partir.
 *
 * Prérequis : voir smoke.spec.ts (backend, front avec VITE_TEST_HOOKS=1, global-setup).
 */
import { expect, test } from "@playwright/test";
import { amenerEnPhaseMove, GAME_URL, lireEtatDePartie, type Page } from "./helpers";

type UnitsCache = Record<string, { occupied_hexes_by_model?: Record<string, [number, number]> }>;

async function coordsEcran(
  page: Page,
  col: number,
  row: number
): Promise<{ x: number; y: number }> {
  const c = await page.evaluate(
    ({ col, row }) => {
      const hook = (window as Record<string, unknown>).__W40K_TEST__ as
        | Record<string, unknown>
        | undefined;
      if (!hook) return null;
      return (hook.hexToScreenCoords as (c: number, r: number) => { x: number; y: number })(
        col,
        row
      );
    },
    { col, row }
  );
  expect(c, "hexToScreenCoords n'a rien rendu : le hook ou le canvas est en panne").not.toBeNull();
  expect(c!.x !== 0 || c!.y !== 0, "hexToScreenCoords rend (0,0) : canvas non dimensionné").toBe(
    true
  );
  return c!;
}

async function modeCourant(page: Page): Promise<string | undefined> {
  return page.evaluate(
    () =>
      ((window as Record<string, unknown>).__W40K_TEST__ as Record<string, unknown> | undefined)
        ?.currentMode as string | undefined
  );
}

async function attendreMode(page: Page, attendu: string, quoi: string): Promise<void> {
  await expect
    .poll(() => modeCourant(page), { timeout: 30_000, message: `${quoi} : mode ≠ ${attendu}` })
    .toBe(attendu);
}

test.describe("Pose en unit move (movePreview)", () => {
  test("le clic de pose ne sélectionne pas la figurine sous le curseur", async ({ page }) => {
    // Journal des actions moteur émises par le front : la sélection d'une figurine se voit ici.
    const actions: Array<{ t: number; action: string; modelId?: string }> = [];
    page.on("request", (r) => {
      if (!r.url().includes("/api/game/action") || r.method() !== "POST") return;
      const body = r.postDataJSON?.() as Record<string, unknown> | null;
      if (!body) return;
      actions.push({
        t: Date.now(),
        action: String(body.action),
        modelId: body.model_id as string | undefined,
      });
    });

    await page.goto(GAME_URL);
    await page.locator("canvas").first().waitFor({ timeout: 30_000 });
    const hookPresent = await page.evaluate(
      () => typeof (window as Record<string, unknown>).__W40K_TEST__ !== "undefined"
    );
    expect(hookPresent, "window.__W40K_TEST__ absent : front sans VITE_TEST_HOOKS=1").toBe(true);

    await amenerEnPhaseMove(page);
    const etat = await lireEtatDePartie(page);
    const pool = (etat.move_activation_pool as string[]) ?? [];
    const unitsCache = (etat.units_cache as UnitsCache) ?? {};
    // La plus grosse escouade éligible : c'est sur elle que le rendu de transition est le plus lent,
    // donc que l'ancienne garde de 300 ms cédait. Une fig unique reproduit aussi (elle atterrit
    // sous le curseur), mais avec moins de marge.
    const candidates = pool
      .map((uid) => ({
        uid,
        models: Object.entries(unitsCache[uid]?.occupied_hexes_by_model ?? {}),
      }))
      .filter((c) => c.models.length > 0)
      .sort((a, b) => b.models.length - a.models.length);
    expect(
      candidates.length,
      "aucune unité éligible avec des figurines : rien à poser"
    ).toBeGreaterThan(0);

    let posee = false;
    for (const cand of candidates) {
      const [, pos0] = cand.models[0];
      const origine = await coordsEcran(page, pos0[0], pos0[1]);

      // 1) Simple clic sur une figurine : active l'unité (perModelMove). On attend que le plan soit
      //    posé (mode) avant le double-clic, pour que celui-ci n'ait pas d'activation concurrente.
      await page.mouse.click(origine.x, origine.y);
      await attendreMode(page, "perModelMove", `activation de ${cand.uid}`);
      await page.waitForTimeout(500);

      // 2) Double-clic sur la même figurine : unit move (movePreview, escouade rigide sous le curseur).
      await page.mouse.dblclick(origine.x, origine.y);
      await attendreMode(page, "movePreview", `double-clic sur ${cand.uid}`);

      const apres = await lireEtatDePartie(page);
      const brut = (apres.valid_move_destinations_pool as Array<[number, number]>) ?? [];
      if (brut.length === 0) {
        // Unité activable mais sans destination (encerclée) : situation de jeu, on essaie la suivante.
        continue;
      }
      // Destination la plus éloignée de l'origine : la figurine d'ancre atterrit sous le curseur.
      let dest = brut[0];
      let dmax = -1;
      for (const d of brut) {
        const dd = Math.abs(d[0] - pos0[0]) + Math.abs(d[1] - pos0[1]);
        if (dd > dmax) {
          dmax = dd;
          dest = d;
        }
      }
      const cible = await coordsEcran(page, dest[0], dest[1]);
      await page.mouse.move(cible.x, cible.y, { steps: 12 });
      // Laisser le survol snapper la destination (mousemove → movePreview.dest) avant la pose.
      await page.waitForTimeout(1000);

      // 3) Pose.
      const tPose = Date.now();
      await page.mouse.click(cible.x, cible.y);
      await attendreMode(page, "perModelMove", `pose de ${cand.uid}`);
      // Quand le mode est observé, la propagation du pointerdown de pose est terminée (JS mono-thread) ;
      // une sélection parasite aurait déjà émis sa requête. Marge pour la livraison de l'événement request.
      await page.waitForTimeout(1500);

      const selections = actions.filter(
        (a) => a.t >= tPose && a.action === "move_model_destinations"
      );
      expect(
        selections,
        `le clic de pose a sélectionné une figurine (${selections.map((s) => s.modelId).join(", ")}) ` +
          "au lieu de seulement poser l'escouade"
      ).toEqual([]);
      const poses = actions.filter((a) => a.t >= tPose && a.action === "preview_move_plan");
      expect(
        poses.length,
        "aucun preview_move_plan après la pose : l'escouade n'a pas été posée"
      ).toBeGreaterThan(0);
      posee = true;
      break;
    }
    expect(posee, "aucune unité éligible n'a de destination : rien n'a pu être posé").toBe(true);
  });
});
