# Unités hors table — tous les chemins géométriques

Découvert le 2026-08-04 pendant le chantier 04c (le bot fait arriver ses réserves).
**Partiellement corrigé — 3 sites sur ~30 fermés.** Bloque l'activation des variantes de rosters
à réserves stratégiques (cf. §Ce qui attend cette correction).

> **Périmètre** : `engine/`, tout code qui ÉNUMÈRE des unités pour en MESURER une géométrie.
> Ne concerne pas `ai/` : le chantier 04c y est terminé et testé.
>
> **Principe** : le prédicat existe déjà et est correct (`entry_is_on_battlefield`), il n'est
> simplement pas appelé partout. Aucune règle à réécrire. Aucun fallback, aucune valeur par
> défaut masquant une erreur.
>
> **Statut (2026-08-04)** : root cause établie et PROUVÉE par exécution. Périmètre recensé mais
> non trié. Décision d'architecture NON prise (cf. §La question à trancher).

---

## Le défaut

Le code qui énumère les unités pour mesurer une distance ne filtre pas celles qui sont **hors
table**. Signature :

```
ValueError: Cannot compute distance between empty sets   (engine/hex_utils.py:158)
```

Une unité hors table est **vivante** (`is_unit_alive` → True), présente dans `units_cache`, à la
position sentinelle `(-1,-1)`, avec `occupied_hexes` **vide** et `deployed_on_turn is None`.
Tout filtre écrit sur « vivante » la laisse donc passer. C'est le motif.

### ⚠️ Ce n'est PAS un bug des réserves stratégiques

C'est le contresens à ne pas faire, et il coûterait la moitié des sites. **MESURÉ** : avec
`W40K_BOARD_PATH=board/44x60x1`, un `reset()` sur un roster **sans aucune** `strategic_reserves`
plante déjà, avant tout déploiement :

```
CRASH AU RESET : Cannot compute distance between empty sets
  engine/phase_handlers/shared_utils.py:3161, in _coherency_flags_footprint
```

La cause est `deployment_type: "active"`, qui laisse **toutes** les unités hors table au reset.
Les réserses (20.01) ne font qu'allonger la durée pendant laquelle une unité est dans cet état —
elles ont rendu le défaut visible, elles ne l'ont pas créé. Et il frappe `validate_squad_coherency`,
un sous-système sans aucun rapport avec le tir.

### Deux familles distinctes, ne pas traiter que la première

| Famille | Symptôme | Gravité |
|---|---|---|
| **DISTANCE** | empreinte vide → `min_distance_between_sets` **lève** | bruyant, donc traité en premier |
| **ENGAGEMENT** | `_cache_entry_footprint` se rabat sur l'ancre `(-1,-1)` : l'unité hors table devient un **fantôme à une position réelle** | pas de crash, **verdict FAUX** — plus dangereux |

Le repli d'ancre de la famille ENGAGEMENT est `engine/spatial_relations.py:131` et
`_cache_entry_footprint` (shooting_handlers). État de la mesure sur cette famille :

- à **x5 / euclidien** : non reproduit. `_is_adjacent_to_enemy_within_cc_range` rend `False` aux
  5 positions testées, y compris `(0,0)`. `engagement_zone = 10`.
- à **x1 / hex** : l'arithmétique la rend probable (distance hex `(-1,-1)→(0,0)` = 1, EZ = 2),
  mais le crash de coherency ci-dessus empêche d'y arriver. **À trancher par la mesure**, pas
  par le raisonnement.

## Reproduction déterministe, gratuite

```
tests/unit/engine/test_roster_downscale_coherency.py::test_every_squad_is_coherent_right_after_reset[1]
```

Rouge sur `main` aujourd'hui, même signature. Vérifié dans un worktree propre : **antérieur au
chantier 04c**, arrivé avec le merge du chantier 04.

## Recensement — le bon grep

Ne **pas** greper `entry_is_on_battlefield` : les appels **existants** ne peuvent pas révéler les
**manquants**. C'est l'erreur de méthode qui a fait sous-estimer ce chantier d'un facteur 10.

Greper les boucles `for x, y in units_cache.items()` qui font de la géométrie
(`occupied_hexes`, `min_distance_between_sets`, `ranged_edge_distance`, `socle_from_cache_entry`,
`engagement_zone`) **sans** filtre hors-table dans les lignes qui suivent. Rend ~30 candidats :

| Fichier | Sites |
|---|---|
| `fight_handlers.py` | 11 |
| `shared_utils.py` | 8 |
| `charge_handlers.py` | 5 |
| `movement_handlers.py` | 2 |
| `spatial_relations.py` | 2 |
| `observation_builder.py` | 2 |
| `shooting_handlers.py` | 2 (restants) |

Trier les faux positifs (boucles sur des alliés déjà posés) fait partie du travail.

### Piège à ne pas redécouvrir

`entry.get("occupied_hexes", {ancre})` **ne protège pas**. La clé est **PRÉSENTE et VIDE** hors
table, donc le défaut du `.get` ne se déclenche jamais et l'ensemble vide passe.

Deux autres pièges mesurés :

- `shooting_phase_start` **ne fait pas** le choix d'arme complet si l'unité n'est ni adjacente ni
  en advance : il prend la première arme portée sans regarder personne. Un test qui met une unité
  en réserves et appelle `shooting_phase_start` reste **VERT avec le défaut**. Il faut
  `units_advanced` ou le contact pour atteindre `weapon_availability_check`.
- Le crash dépend de la **géométrie** : la sentinelle `(-1,-1)` est à ~274 subhex de la zone de
  déploiement de `scenario_training_armageddon` (portées d'armes 120-240), donc hors portée, donc
  pas de crash. Dans l'épisode qui plantait réellement, le tireur était à ~153. **Un test doit
  CONSTRUIRE un tireur à portée du fantôme**, sinon il est vert vacant.

## La question à trancher

Le correctif va-t-il **aux ~30 sites d'énumération**, ou à **UN point d'étranglement**
(`min_distance_between_sets` qui refuse explicitement, `_cache_entry_footprint` /
`spatial_relations.py:131` qui cessent de se rabattre sur l'ancre, ou un helper d'énumération
d'ennemis partagé) ? **Décider et ARGUMENTER le choix.**

Trois correctifs par-site existent déjà (chantier 04c, `shooting_handlers.py`) :
`_build_weapon_availability_enemy_precheck` (côté cible), `shooting_phase_start` (côté tireur),
`_unit_has_firable_target`, plus le filtre de `_select_move_after_shooting_destination_for_ai`.
**Les remettre en cause fait partie du travail** — si la racine est traitée, ils deviennent
redondants et doivent sauter.

## Ce qui n'est pas verrouillé

Les correctifs 04c dans `shooting_handlers.py` **n'ont pas de verrou**. Vérifié en retirant
chaque filtre : les tests
`test_strategic_reserves_20.py::test_shooting_phase_start_runs_with_a_reserve_{enemy,shooter}`
restent **VERTS**. Ce sont des tests de non-régression, pas des verrous — c'est écrit en clair
dans le fichier. Raison : voir le piège « géométrie » ci-dessus.

## Ce qui attend cette correction

Le chantier 04c a livré 6 variantes de rosters avec réserves stratégiques, rangées dans des
sous-dossiers `variants/` :

- `config/agents/ArmageddonAgent/rosters/500pts/training/variants/`
- `config/agents/ArmageddonAgent/rosters/500pts/holdout_regular/variants/`
- `config/agents/_p2_rosters/500pts/training/variants/`

Elles sont **hors du tirage** : le glob de `training_random` (`engine/game_state.py`,
`_resolve_roster_ref`) n'est **pas récursif**. C'est volontaire — les câbler a fait rougir
8 tests sur les trous décrits ici.

**Ne pas les activer avant que ce chantier soit fini.** Le jour où il l'est :

1. déplacer les 4 variantes `training/` d'un cran vers le haut (hors de `variants/`) ;
2. ajouter les 2 refs adverses à `opponent_roster_ref` dans
   `config/agents/ArmageddonAgent/scenarios/training/scenario_training_armageddon.json` ;
3. pour le holdout, créer les scénarios correspondants (`scenario_bot-05..08`) — ses rosters sont
   référencés **explicitement**, il n'y a pas de tirage. ⚠️ Ça double le coût d'évaluation et
   change la composition du holdout : **décision utilisateur**.

Tant que rien n'est activé, la ventilation `bot_eval/roster/*` livrée par 04c ne publiera jamais
de courbe « avec réserves ».

## Ne pas oublier

`tests/unit/engine/test_strategic_reserves_20.py` a été repointé sur une fixture à rosters pinnés
(`scenarios/training/reserves_20_fixture.json`) précisément pour être indépendant du contenu du
dossier `training/`. Ne pas le repointer sur `scenario_training_armageddon.json` en activant les
variantes : 16 de ses tests supposent que toutes les unités démarrent posées.
