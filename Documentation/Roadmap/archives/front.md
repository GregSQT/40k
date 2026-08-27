# Archives Front

| Date | Chantier | Détail |
|---|---|---|
| 2026-08-17 | LoS chemin refait à chaque survol | `flattenObscuringZones/TerrainZones` mémoïsés ; `key` getter lazy ; 6,9 ms/appel → ~0 ms |
| 2026-08-17 | `BoardReplay` effet de dessin inévitable | 6 valeurs instables mémoïsées ; `currentState`, `unitsWithGhost`, etc. |
| 2026-08-17 | Corrections code-review + simplify `BoardReplay` | 6 findings /code-review ; `countActionsInPhase` extrait ; `PHASE_NEUTRAL_TYPES` |
| 2026-08-12 | Objectif capturé → couleur correcte | `planBoardRedraw` source unique ; calque périmé ré-attaché corrigé ; doublons surbrillances corrigés ; validé navigateur |
| 2026-08-12 | Clé contrôle objectif (chemin chaud) | 6,40 ms/rendu → 0,001 ms ; 5 zones × 2 116 sous-hex ; 7 tests d'équivalence |
| 2026-08-12 | Trois aplatissements volumineux | `useBoardHexMemos.ts` — `useNormalizedObjectives`, `useEffectiveObjectiveHexes`, `useWallHexKeySet` ; 17 tests |
| 2026-08-12 | Config plateau `BoardPvp` référence stable | `useResolvedBoardConfig` — deux mémos fusionnés ; 8 tests d'identité |
| 2026-08-12 | Résidu front V10 fight supprimé | Deux cascades `useEngineAPI.ts` et 3 champs morts supprimés |
| 2026-08-11/12 | Aperçu tir par figurine pendant placement | `preview_shoot_valid_targets_from_model_positions` ; plan canonique avec niveau/orientation ; encodeur `modelPlan.ts` |
| 2026-08-19 | ✅ Tests front T7+T8–T13 livrés + T11 hook complet (2026-08-19) — 82 tests vitest verts (Couche B), Playwright 14 scénarios (T12-1..T12-8), hook __W40K_TEST__ étendu (movePreviewHexes/blinkTargetUnitIds/currentMode/hexToScreenCoords), data-testid board-viewport+board-canvas-container | front · [front.md#tests](front.md#tests) |
| 2026-08-19 | ✅ buildTargetPreviewStats extraite (2026-08-19) — fonction pure testable hors jsdom, supprime le calcul inline redondant overallProbability/expectedDamage dans useEngineAPI ; 4 nouveaux tests rouge/vert | front · — |
| 2026-08-19 | ✅ Tests review-test-assertions corrigés (2026-08-19) — assertions test HazardWarning et BoardWithAPI nettoyées | front · — |
| 2026-08-19 | ✅ HazardWarningModal + AdvanceWarningModal simplifiés (2026-08-19) — composants nettoyés | front · — |
| 2026-08-19 | ✅ woundTargetFromSTR_T helper + fight blink délégué (2026-08-19) — cascade 4× factorisée en un helper partagé ; fight path blinkingHPBar délègue à calculateCombatOverallProbability | front · — |
| 2026-08-24 | ✅ T7 overlay retrait cohérence PvP (2026-08-24) — endpoint select_coherency_removal câblé, overlay rouge par-figurine, click handler hex→model_id | front · — |
| 2026-08-19 | ~~Scission `bcKey` géométrie/contrôle~~ ✅ livré 2026-08-19 | front · [front.md](front.md) |
| 2026-08-24 | ✅ fix code-review findings front (2026-08-24) — 4 findings : deadlock IA, replay crash, localStorage, chargeSuccess | front · — |
