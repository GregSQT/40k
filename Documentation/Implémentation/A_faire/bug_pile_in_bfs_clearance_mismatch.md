# Bug — pile-in / consolidation : mismatch BFS↔commit (cellules vs clearance)

Découvert le 2026-07-16 en marge du fix `squad_fight` (V11 T6). **Non corrigé — backend PvP,
hors périmètre training.** Un fix a été écrit, mesuré, puis **reverté** : il changeait le
comportement PvP (cf. §Pourquoi reverté).

---

## Le bug

Deux prédicats de placement divergent — **même famille que la rupture déploiement de V11 T5**
(`_get_valid_deployment_hexes` par CELLULES vs `deploy_unit` par CLEARANCE euclidienne) :

- **Pool** : `_fight_bfs_reachable_anchors_consolidation` (fight_handlers ~L1072) filtre les
  ancres avec `is_footprint_placement_valid` + `build_occupied_positions_set` → chevauchement
  testé par **CELLULES**.
- **Commit** : `_fight_apply_pile_in_move` (fight_handlers ~L885) valide avec
  `is_placement_valid_with_clearance` → chevauchement en **CLEARANCE euclidienne CONTINUE**
  (plus stricte, rond↔rond).

Le BFS propose donc des ancres que le commit rejette. Les appelants
(`_fight_v11_auto_pile_in` ~L3419, `_fight_v11_auto_overrun_pile_in` ~L3440) avalent la
`ValueError` par un `except ValueError: pass` commenté « destination devenue invalide entre BFS
et application » — **ce commentaire est faux** : rien ne modifie l'état entre les deux, c'est un
mismatch de prédicats. Résultat : **le pile-in est silencieusement annulé**, sans log ni erreur.

## Mesures (reproductibles)

Sur `scripts/smoke_t5_bare.py::MELEE_SCENARIO`, seeds 1-3, en comparant chaque ancre offerte par
le BFS au prédicat du commit :

| Mesure | Valeur |
|---|---|
| Ancres BFS proposées / rejetées par la clearance du commit | **1102 / 72857** (~1,5 %) |
| Idem sur le seul état initial (4 unités) | **38 / 2219** |
| Après fix (BFS aligné sur la clearance) | **0 / 71755** |
| Destinations légitimes perdues par effet de connectivité du BFS | **0** (mesuré sur l'état initial, 4 unités) |
| Perf `smoke_t5_bare.py` avant / après fix | **2m01 → 1m33** (le retrait de `build_occupied_positions_set` coûte plus cher que la clearance ne rapporte) |

Le fix consistait à faire filtrer le BFS par `is_placement_valid_with_clearance` (mêmes
arguments que le commit) et à supprimer les deux `except ValueError: pass` devenus sans objet.
Suite `tests/unit/` verte avec ce fix (1289), smoke `(A) OK | (B) OK`.

## Pourquoi reverté

`fight_handlers` est **partagé PvP/gym**, et le changement n'est **pas neutre pour le PvP** —
appelants VIVANTS du BFS depuis `_fight_v11_manual_step` (flux PvP manuel) :

- `consolidate_autoplace_plan` (~L6395) → `_fight_plan_consolidation_destinations` → le BFS :
  les destinations de consolidation proposées au joueur changent (−19 ancres sur les unités 1 et
  2 du scénario mêlée) ;
- `_fight_v11_auto_overrun_pile_in` (~L6229) → `pile_in_move_destinations_12_03` → le BFS ;
  et sans le `except ValueError`, ce chemin PvP peut lever.

⚠️ **Correction d'une analyse erronée** (2026-07-16) : le revert avait d'abord été justifié par
« la chaîne aboutit à `_fight_v11_pile_in_present`, aperçu **exposé au front** ». C'est **FAUX** :
`_fight_v11_pile_in_present` n'a **aucun appelant** — fonction MORTE depuis le routing du pile-in
par-figurine (cf. mémoire projet du 2026-06-12, qui l'annonçait déjà « devenue morte »). La
conclusion (ne pas toucher) tient par les deux chemins ci-dessus, pas par celui-là.
`_fight_v11_pile_in_present` est un candidat à la suppression (hygiène, à valider).

Décision utilisateur (2026-07-16) : **ne pas changer le backend actuel**. Le périmètre en cours
est l'adaptation du training aux squads / nouvelles règles.

## Notes pour la reprise

- Le bug est **réel côté PvP aussi** : le front propose au joueur des destinations que le commit
  du moteur refuse. À trancher : que se passe-t-il aujourd'hui quand le joueur clique une de ces
  destinations (ValueError remontée à l'API ? pile-in avalé ?) — non vérifié en runtime navigateur.
- Les fixtures de `tests/unit/engine/test_fight_consolidation_bfs.py` construisent des
  `units_cache` **sans `BASE_SHAPE`/`BASE_SIZE`**, alors que le contrat les exige toujours
  (`require_key` dans game_state.py:856, contrat documenté shared_utils.py:680). Tout fix passant
  par la clearance les fera échouer → les compléter (ce n'est pas « adapter le test », c'est
  aligner la fixture sur le contrat).
- ✅ **TRANCHÉ (décision utilisateur, 2026-07-16) : le pile-in de référence est celui du mode
  PvP — le par-figurine** (`pile_in_autoplace_plan`, `_fight_pile_in_model_plan_state`,
  `commit_move(plan, gs, "pile_in")`). Le modèle par ANCRE d'unité (`_fight_apply_pile_in_move`
  → `translate_squad_to_destination`, translation rigide) est **condamné**.

  **Conséquence directe sur ce bug** : le BFS `_fight_bfs_reachable_anchors_consolidation` et son
  commit `_fight_apply_pile_in_move` appartiennent TOUS DEUX au modèle par-ancre condamné. Le fix
  de parité décrit ici corrigerait donc un modèle voué à disparaître. **Ne pas le ressusciter
  tel quel** : la vraie cible est de migrer les chemins par-ancre restants (auto V11 + overrun)
  vers le par-figurine. Le mismatch cellules/clearance disparaîtra avec eux — à vérifier
  toutefois que le chemin par-figurine ne porte pas le même écart (non audité).

  **Trou à combler** : l'overrun 12.06 n'existe QU'EN modèle ancre
  (`_fight_v11_auto_overrun_pile_in`), y compris quand le PvP manuel l'appelle (~L6229). Le PvP
  est donc HYBRIDE : pile-in normal par-figurine, overrun par-ancre. L'overrun par-figurine est
  **à écrire**, pas à copier. Rappel 12.06 (PDF lu) : « Your unit **can** make one additional
  pile-in move, then fights » → le pile-in additionnel est OPTIONNEL (comme 12.02 et l'encart
  « you don't have to pile in »), donc ne pas l'implémenter ne viole aucune règle.

## Même famille, non mesuré

- **Charge** : pool par cellules (charge_handlers L429, L858, L965, L3288, L4009) vs commit par
  clearance (L3143). Structure identique. Écart **non chiffré** : le pipeline squad gym n'emprunte
  pas `valid_charge_destinations_pool` (0 destination observée sur 3 seeds) — c'est un chemin PvP,
  à auditer via une partie PvP.
- **Move** : éligibilité par cellules (movement_handlers L574, L600) vs commit par clearance
  (L1043). Moins grave (test « existe-t-il au moins un hex »), au pire un move proposé puis refusé.

## Autre fallback relevé (même fichier, non corrigé)

`_ai_select_fight_target` (~L1725) : `except Exception: … return valid_targets[0]` — masque toute
erreur de config/registry et fausse silencieusement la sélection de cible (CLAUDE.md : jamais de
fallback couvrant une erreur). Vérifié : **aucune exception n'est levée** sur la suite complète +
smoke, le fallback ne couvre rien de réel aujourd'hui. Retrait neutre en marche normale, mais fait
lever le PvP en cas d'erreur → même arbitrage backend.
