# Hygiène documentaire — Tâches ouvertes

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
