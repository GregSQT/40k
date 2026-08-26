# Hygiène documentaire — Tâches ouvertes

---

## Ancres de ligne périmées docs V11 {#ancres}

**Traitement au fil de l'eau** (décision 2026-08-10) — tout doc modifié voit ses ancres de ligne corrigées dans la même livraison.

**✅ Soldé le 2026-08-25** — sept symboles dont les numéros de ligne avaient dérivé, corrigés dans 4 docs :

| Symbole | Docs corrigés |
|---|---|
| `def _select_allocation_model` | `FIGHT_RESOLVER_CONVERGENCE.md` |
| `def fight_pile_in_plan` | `V11_agent_rework.md`, `pile_in_overrun_par_figurine_2026-08-18.md`, `replis_units_cache_2026-08-05.md` |
| `def squad_consolidate_plan` | `V11_agent_rework.md`, `pile_in_overrun_par_figurine_2026-08-18.md`, `replis_units_cache_2026-08-05.md` |
| `def charge_build_valid_plan` | `replis_units_cache_2026-08-05.md` |
| `def _auto_select_cc_weapon_for_fig` | aucune ancre directe trouvée |
| `def _auto_declared_order` | aucune ancre directe trouvée |
| `def compute_candidate_footprint` | aucune ancre directe trouvée |

**Convention** : citer `def <symbole>` ou un `grep` reproductible, jamais un numéro de ligne. `scripts/check_doc_references.py` la fait respecter sur l'index, les fichiers sujets et les contrats permanents.

**Couverture du script** : `check_doc_references.py` passe 4 (ANCRES) couvre `Documentation/Roadmap/`, les contrats permanents, **et désormais `Documentation/Implémentation/`** (85 fichiers). Les 1237 ancres stales ont été nettoyées le 2026-08-26 — le script repasse au vert sur l'ensemble du corpus.

---

## Dette d'ancres G1/G2/G4 de V11_tranches §1bis {#dette-tranches}

Le recensement G1/G2/G4 de `Documentation/Implémentation/1_Agent/V11_tranches.md` §1bis est en fiabilité dégradée. **Interdiction d'ouvrir un chantier depuis une ligne non ✅ de ce recensement sans la re-vérifier contre le code d'abord** — c'est ainsi qu'est né le plan T7 faux.

---

## §0.19 — T2→T5 revérifiés par lecture seule {#reverif-t2-t5}

`Documentation/Implémentation/1_Agent/V11_agent_rework.md` §0.19 le déclare lui-même : les ✅ de T2→T5 ne sont revérifiés que par LECTURE (aucune exécution), et la conformité littérale de T2 est indécidable. Dette de spec assumée, continue — distincte de la dette d'ancres G1/G2/G4 ci-dessus, qui porte sur le recensement de `V11_tranches.md` §1bis.

---

## Bandeaux périmés V11_agent_rework §0bis {#bandeaux-0bis}

Bandeaux et chiffres périmés listés dans `Documentation/Implémentation/1_Agent/V11_agent_rework.md` §0bis — signalés et volontairement non corrigés depuis le 2026-07-20. Assumé tant qu'aucune livraison ne rouvre ces sections ; traitement au fil de l'eau, comme les ancres.
