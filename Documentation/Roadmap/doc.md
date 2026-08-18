# Hygiène documentaire — Tâches ouvertes

---

## `obs_size` justification {#obs-size}

La valeur vraie de `obs_size` à HEAD est **16671** (les 6 profils de la config ArmageddonAgent la portent ; 16659 → 16671 à la livraison de P3-4 le 2026-08-17).
La `justification` du champ raconte encore la lignée 20780 → 20727 (un appendice P3-4 a été ajouté à la fin sans réconcilier le total) — à réécrire.

**Le gel est levé** (run terminé) : plus rien n'interdit d'y toucher.

---

## Notes vitesse entraînement périmées {#vitesse}

Deux profils de la config ArmageddonAgent annoncent encore `0.1 s/ep -> 36k ep / hour`. Le run réel du 2026-08-11 donne **4 h 01 pour 10 000 épisodes** (≈ 2 500 ép./h) — facteur ~14 d'écart.

**À faire** : re-dériver chaque note de coût d'évaluation des 6 profils depuis la mesure réelle. Aussi : `36_000` codé en dur dans `test_schedule_decay_fraction.py` (seuil conservé car plus sévère des deux).

Aussi : `Documentation/AI_TRAINING.md` annonce « ~5 h 30 pour 200 000 épisodes » — faux d'un ordre de grandeur.

---

## Ancres de ligne périmées docs V11 {#ancres}

**Traitement au fil de l'eau** (décision 2026-08-10) — tout doc modifié voit ses ancres de ligne corrigées dans la même livraison.

Sept symboles dont les numéros de ligne cités par les docs V11 ont dérivé de plusieurs centaines à plusieurs milliers de lignes :

- `def _select_allocation_model` (`engine/phase_handlers/shared_utils.py`)
- `def fight_pile_in_plan` (`engine/phase_handlers/shared_utils.py`)
- `def squad_consolidate_plan` (`engine/phase_handlers/shared_utils.py`)
- `def charge_build_valid_plan` (`engine/phase_handlers/shared_utils.py`)
- `def _auto_select_cc_weapon_for_fig` (`engine/phase_handlers/shared_utils.py`)
- `def _auto_declared_order` (`engine/phase_handlers/shared_utils.py`)
- `def compute_candidate_footprint` (`engine/phase_handlers/shared_utils.py`)

**Convention** : citer `def <symbole>` ou un `grep` reproductible, jamais un numéro de ligne. `scripts/check_doc_references.py` la fait respecter sur l'index, les fichiers sujets et les contrats permanents.

---

## Dette d'ancres G1/G2/G4 de V11_tranches §1bis {#dette-tranches}

Le recensement G1/G2/G4 de `Documentation/Implémentation/1_Agent/V11_tranches.md` §1bis est en fiabilité dégradée. **Interdiction d'ouvrir un chantier depuis une ligne non ✅ de ce recensement sans la re-vérifier contre le code d'abord** — c'est ainsi qu'est né le plan T7 faux.

---

## §0.19 — T2→T5 revérifiés par lecture seule {#reverif-t2-t5}

`Documentation/Implémentation/1_Agent/V11_agent_rework.md` §0.19 le déclare lui-même : les ✅ de T2→T5 ne sont revérifiés que par LECTURE (aucune exécution), et la conformité littérale de T2 est indécidable. Dette de spec assumée, continue — distincte de la dette d'ancres G1/G2/G4 ci-dessus, qui porte sur le recensement de `V11_tranches.md` §1bis.

---

## Bandeaux périmés V11_agent_rework §0bis {#bandeaux-0bis}

Bandeaux et chiffres périmés listés dans `Documentation/Implémentation/1_Agent/V11_agent_rework.md` §0bis — signalés et volontairement non corrigés depuis le 2026-07-20. Assumé tant qu'aucune livraison ne rouvre ces sections ; traitement au fil de l'eau, comme les ancres.
