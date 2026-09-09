# V11 — Chemin critique vers la mesure de référence

Sujets : training + moteur + bot. Ordre imposé par décisions 2026-08-07/2026-08-10.
La mesure de référence (`x1_long`, 300 parties/bot) est différée jusqu'à livraison de tout ce bloc.
Dans la direction de l'index : lignes 1–4 = jalon J2, lignes 5–6 = J3, ligne 7 = J4.

---

## P3-5 — Pile-in / consolidation {#p3-5}

✅ **Livré le 2026-08-18.**

- `fight_pile_in_plan` : restriction 12.03 BEFORE MOVING — cibles imposées (ennemis engagés) si engagée, sinon ennemis dans `pile_in_target_range` (5").
- `squad_consolidate_plan` : cascade 12.08 complète — Ongoing → Engaging (ennemis à ≤3") → Objective (objectifs à ≤3") → None. Mode Objective : assignation gloutonne dans la zone via `model_reach_predicate`.
- Tests : 5 nouveaux cas dans `test_pile_in_intra_squad_collision.py` (3 modes cascade + 2 restriction 12.03). 19/19 verts.
- Validation holdout : `--test-only --training-config x1_long --step` lancé le 2026-08-18, aucun crash sur 650+ épisodes.

→ `Documentation/Chantiers/v11/decisions_du_joueur.md` §9.4 pt 5

---

## P3-6 — Move-after-shooting + reactive move {#p3-6}

🟡 **Move-after-shooting livré le 2026-09-09 ; reactive_move reste heuristique.**

🔴 Le « constaté implémenté le 2026-08-19 » qui tenait cette place était FAUX : il constatait les effets dans `UNIT_RULE_EFFECT_IDS` et des handlers actifs — soit que la RÈGLE est jouée —, pas que la DÉCISION est rendue à l'agent. `_select_move_after_shooting_destination_for_ai` tranchait encore, et le mode `"auto"` de `reactive_move` tranche toujours.

🟢 **Move-after-shooting (2026-09-09, worktree `move-after-shooting-agent-decision`)** : type `move_after_shooting` dans `AGENT_DECISION_TYPE_IDS` (slot réservé — `obs_size` et `TOTAL_ACTION_SIZE` inchangés, mesuré). L'heuristique est supprimée ; gym et bot PvE reçoivent 3 intentions scorées (Pression = historique en `CHOICE_0`, Retrait, Objectif) plus `declines`, et la réponse passe par le handler du PvP. 16 tests rouge→vert. ⚠️ Le contrat d'entraînement (`training_contract.json`) compare `AGENT_DECISION_TYPE_IDS` : une reprise `--append` sur un modèle antérieur sera refusée, l'ajout étant en fin de vocabulaire et inoffensif pour les ids existants.

🔴 **reactive_move** : `reactive_decision_mode` figé à `"auto"` (`w40k_core.py`, 2 sites), jamais `"state"` hors tests ; le mode auto ne décline jamais et choisit la case la plus proche de l'ennemi qui vient de bouger. Écarté sur MESURE : ses porteurs (`Termagant`, `FenrisianWolf`) sont absents du régime d'entraînement actif (500 pts, `ArmageddonAgent_x1`) — le brancher coûterait un type et ses tests pour zéro gradient. À rouvrir si un roster d'entraînement en porte un.

→ `Documentation/Chantiers/v11/decisions_du_joueur.md` §9.4 pt 6

---

## P3-8 — Optionnels à statuer {#p3-8}

Le choix d'arme en mêlée (§0.69) est déjà acté en ordre 3. Reste : split-fire, multi-cibles charge, placement final, stratégies de déploiement.
Mesurer le regret avant de trancher (§9.0bis).

🟢 **Décision 2026-08-10** : le regret se mesure sur la BASE DE DÉVELOPPEMENT en cours (§0.70), pas après la mesure de référence — un écart *relatif* (branché vs heuristique auto) supporte l'imprécision d'un run de 10 000 épisodes.

🟢 **Stratégies déploiement livrées le 2026-08-19** : `DEPLOY_STRATEGY_COUNT` 5→7 (`centre_hub` slot 9, `safe_rear` slot 10). Regret à mesurer avec `--new`. Reste ouvert : split-fire.

🟢 **Charge multi-cibles livrée le 2026-08-20** : C(20,2)+20 = 210 slots (slots 1045–1254), tête dense `charge_pair_net` dans `pointer_policy`, logique PvP réutilisée (`charge_build_valid_plan` + `charge_target_selection_handler`), `TOTAL_ACTION_SIZE` 1159→1349. Verrous : `test_action_space_mirror::test_charge_pair_slots_count`, `test_pointer_head`. Ré-entraînement `--new` nécessaire.

🟢 **Placement final de charge livré le 2026-08-24** (L10) : `charge_placement` ajouté à `AGENT_DECISION_TYPE_IDS` (slot réservé — `obs_size` 16703 inchangé, pas de ré-entraînement `--new` requis). `charge_build_valid_plan` étendu avec `intent: int = 0` (5 intentions : Serré 0, Objectif 1, Isolation 2, Pénétration 3, Étalé 4). `arm_charge_placement_decision` + `apply_charge_placement_decision` dans `charge_handlers.py` ; `_finish_charge_after_placement` dans `w40k_core.py` ; CHOICE_0 = Serré = comportement historique pour bots/siège muet. 20 tests (rouge→vert).

🟢 **Split-fire livré le 2026-08-24** (P3-8 gym) : 10 `SHOOT_WEAPON_SEL_SLOTS` (1379–1388), `TOTAL_ACTION_SIZE` 1379→1389. Flux 2-step : slot j → `squad_shoot_weapon_sel` (init activation + pending_shoot_weapon_split) → SHOOT_SLOT i → `squad_shoot_split_target` (enregistre assignment → résolution finale). Tête dense `shoot_weapon_sel_net` (K_WEAPONS_RANGED=10 logits) dans `pointer_policy` — **remplacée le 2026-09-09 par la tête pointeur `shoot_weapon_sel_query_net`**, qui score l'ARME de l'emplacement et non son rang. Masque via `_model_can_shoot_target_with_weapon` (sans activation). Ré-entraînement `--new` nécessaire.

→ `Documentation/Chantiers/v11/decisions_du_joueur.md` §9.4 pt 8

---

## P4 — Observation de support {#p4}

✅ **Livré le 2026-08-19** — reliquat `effective_range` ajouté à l'encodeur d'entité (`observation_entities.py::UNIT_CONT_FIELDS`, `observation_builder.py::_encode_unit_entity`) ; LoS/couvert et flags `advanced`/`fled` étaient déjà présents. `obs_size` 16671 → 16703.

→ `Documentation/Chantiers/v11/decisions_du_joueur.md` §9.5

---

## P5 — Validation par tranche {#p5}

🟢 **Tranché le 2026-08-18 — commande de validation :**

```
python3 ai/train.py --agent ArmageddonAgent --training-config x1_long --resolution 1 --test-only --step
```

`--test-only` utilise `eval_episodes` (pas `bot_eval_final`, qui ne s'applique qu'à la fin d'un run d'entraînement). Les **7** profils de la config sont tous à 24 envs ; seul `x1_long` atteint la précision cible :

| profil | `total_episodes` | `bot_eval_final` | `eval_episodes` |
|---|---|---|---|
| `x1_debug` | 96 | 0 | — |
| `x5_debug` | 96 | 1 | — |
| `x1` | 10 000 | 10 | 50 |
| `x1_long` | 100 000 | 300 | **100** |

Erreur-type avec `eval_episodes = 100` : `0,707/√(6 × 100)` ≈ **2,9 pts**. Durée : ~8 min (350 épisodes à 0,72 ép./s, mesuré le 2026-08-18). Aucun profil dédié nécessaire.

→ `Documentation/Chantiers/v11/decisions_du_joueur.md` §9.6

---

## Mesure de référence {#mesure}

`--test-only --step` sur le champion final P10 — solde §0.14, §0.67, critère T6 (via §10.6) d'un coup.
Durée : **~8 min** (100 épisodes × 6 profils, mesuré le 2026-08-18). Un `--new` serait absurde ici : il jetterait le champion P10. Le ~6 h antérieur désignait la durée d'un run `x1_long --new` complet (5 h 54 mesuré le 2026-08-18 sur l'ancienne config 100 000 épisodes — portée à 750 000 depuis) — sans rapport avec la mesure.

---

## Benchmark floor gate §4.D {#benchmark-gate}

🟢 **Livré le 2026-08-18** — détecteur de non-généralisation sur x1_long.

4 scénarios `scenario_bench-01` à `scenario_bench-04` dans `config/agents/ArmageddonAgent_x1/scenarios/holdout_regular/` (matchups SM/SM, SM/Ork, Ork/SM, Ork/Ork) pour les 3 bots de référence `reference_balanced / reference_denial / reference_reactive`. Ajoutés à `bot_eval_weights` (poids 0,0 — hors combined) et `bot_eval_randomness` (0,0 — déterministes).

Seuil posé après mesure sur le modèle courant : `model_gating_min_benchmark_floor = 0.90` (scores mesurés : 0,99 / 1,00 / 1,00 → seuil = min − 0,09). `model_gating_enabled = true` sur x1_long uniquement.

Le gate rougit si le modèle progresse sur les 7 bots de sélection mais tombe sous 0,90 sur l'un des 3 bots de référence — signal de surapprentissage sur la distribution de sélection.

⚠️ **RETIRÉ le 2026-08-22** : `model_gating_min_benchmark_floor` est passé à **0,0** sur x1_long. Les scores mesurés ci-dessus le disent déjà — 0,99 / 1,00 / 1,00 dès la première évaluation : le gate n'a jamais eu de marge pour mordre. R0a a tenté de désaturer les `reference_*` et s'est fermé sans y parvenir ; ils sont abandonnés comme étalons. La sélection appartient désormais au plancher dur de 0,55 contre le champion le plus récent d'une étape de curriculum — [bot.md#r0a-references](bot.md#r0a-references) et [bot.md#league](bot.md#league).

---

## Self-play §0.59 {#selfplay}

✅ **Absorbé par `--etape` (décision 2026-08-30).** Le curriculum P0→P10 joue contre des snapshots figés de champions précédents — c'est le levier self-play R2. `SelfPlayWrapper` (adversaire live, poids copiés toutes les `update_frequency` steps) et la config `x1_selfplay` n'apportent rien de distinct ; fermé sans dette.

→ `Documentation/Chantiers/v11/index_v11.md` §0.59
