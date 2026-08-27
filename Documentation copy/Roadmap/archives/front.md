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
