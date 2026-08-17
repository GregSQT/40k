# Hygiène documentaire — Tâches ouvertes

---

## `obs_size` justification {#obs-size}

La valeur vraie à HEAD est **16659** (P3-4 → 16671), portée par les profils de la config ArmageddonAgent.
La `justification` du champ raconte encore la lignée 20780 → 20727 — à réécrire.

**Le gel est levé** (run terminé) : plus rien n'interdit d'y toucher.

---

## Notes vitesse entraînement périmées {#vitesse}

Cinq profils de la config ArmageddonAgent annoncent `0.1 s/ep -> 36k ep / hour`. Le run réel du 2026-08-11 donne **4 h 01 pour 10 000 épisodes** (≈ 2 500 ép./h) — facteur ~14 d'écart.

**À faire** : re-dériver chaque note de coût d'évaluation des 9 profils depuis la mesure réelle. Aussi : `36_000` codé en dur dans `test_schedule_decay_fraction.py` (seuil conservé car plus sévère des deux).

Aussi : `AI_TRAINING.md` annonce « ~5 h 30 pour 200 000 épisodes » — faux d'un ordre de grandeur.

---

## Ancres de ligne périmées docs V11 {#ancres}

**Traitement au fil de l'eau** (décision 2026-08-10) — tout doc modifié voit ses ancres de ligne corrigées dans la même livraison.

Sept symboles dans `engine/phase_handlers/shared_utils.py` dont les numéros ont dérivé de plusieurs centaines à plusieurs milliers de lignes :
`_select_allocation_model`, `fight_pile_in_plan`, `squad_consolidate_plan`, `charge_build_valid_plan`, `_auto_select_cc_weapon_for_fig`, `_auto_declared_order`, `compute_candidate_footprint`.

**Convention** : citer `def <symbole>` ou un `grep` reproductible, jamais un numéro de ligne.
