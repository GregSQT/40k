---
name: project_analyzer_dead_before_shoot
description: Artifact DEAD-before-SHOOT dans l'analyzer — correctifs appliqués et résultat sur step.log
metadata:
  type: project
---

§2.8/§1.2/§1.4 corrigés via `dead_model_positions_episode` dans `freeze_select_targets` (2026-08-19).

**Commit 1** (ffb7d9ae) : DEAD-before-SHOOT artifact — stocker les positions des socles morts AVANT la ligne d'attaque dans `dead_model_positions_episode`, dépilées par `freeze_select_targets` pour reconstruire l'état Select Targets.

**Commit 2** (5eb75fe3) : Purger `dead_model_positions_episode[unit_id]` quand `removed = {}` dans `_resync_living_models` (branche `else` manquante). Corrige 42 faux positifs (17 eng_non_cq + 25 engage_cible) où les positions périmées de retraits de cohérence 03.03 d'une activation précédente engageaient faussement le tireur.

**Résultat final sur step.log (2026-08-19)** :
- §1.2 `eng_non_cq` : 17 → 0 ✓
- §1.2 `engage_cible` : 25 → 0 ✓
- §1.2 `portee` : 0 → 67 (réels : les positions périmées masquaient des tirs IA hors portée)
- §1.4 `surcharge_atk` : 0 → 37 (réels : les positions périmées gonflaient `frozen_target.models_alive`, élargissant le cap CLEAVE)
- Total : 42 faux positifs → 104 vrais positifs (bugs IA, pas bugs analyzer)

**Why:** Les positions stale gonflaient la zone d'engagement (faux eng_non_cq) ET rapprochaient la cible (masquait tirs hors portée) ET gonflaient `models_alive` (masquait surplus d'attaques CLEAVE).

**How to apply:** Le fix est livré et mergé dans main. Les 104 erreurs restantes sont des bugs IA à corriger via re-entraînement, pas des bugs analyzer.
