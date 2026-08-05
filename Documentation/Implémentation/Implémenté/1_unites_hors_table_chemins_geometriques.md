# Unités hors table — tous les chemins géométriques

Découvert le 2026-08-04 pendant le chantier 04c (le bot fait arriver ses réserves).
**CORRIGÉ le 2026-08-05** (branche `worktree-hors-table-geometrie`).

> **Périmètre traité** : `engine/`, tout code qui ÉNUMÈRE des unités pour en MESURER une géométrie,
> **plus `ai/evaluation_bots.py`**. Le doc d'origine écrivait « ne concerne pas `ai/` : le chantier
> 04c y est terminé » — **c'est faux**, et c'est le grep JUMEAU qui l'a montré : les bots
> d'évaluation portaient 6 fois le MÊME motif `.get("occupied_hexes", {ancre})`, sur des boucles
> qui ne filtrent que `is_unit_alive`. Une réserve ennemie y faisait lever
> `min_distance_between_sets`, dans le code qui produit justement les courbes d'éval.
>
> **Ce qui a changé** : le prédicat `entry_is_on_battlefield` existait et était correct, mais il
> n'était appelé qu'à quelques endroits sur ~130. Il est descendu dans la couche basse
> (`engine/spatial_relations.py`) avec trois primitives autour de lui, et les énumérations du
> moteur passent désormais par elles. Aucune règle réécrite, aucun fallback anti-erreur.

---

## Le défaut

Le code qui énumérait les unités pour mesurer une distance ne filtrait pas celles qui sont **hors
table**. Une unité hors table est **vivante** (`is_unit_alive` → True), présente dans
`units_cache`, à la position sentinelle `(-1,-1)`, avec `occupied_hexes` **vide** et
`deployed_on_turn is None`. Tout filtre écrit sur « vivante » la laissait passer.

Ce n'était **pas** un bug des réserves stratégiques. `deployment_type: "active"` laisse **toutes**
les unités hors table au reset — mesuré : 12 sur 12 sur `scenario_training_armageddon` à
`board/44x60x1`. Les réserves (20.01) ne font qu'allonger la durée de cet état.

### Les deux familles, et ce que la mesure a tranché

| Famille | Symptôme | Verdict de la mesure (2026-08-05) |
|---|---|---|
| **DISTANCE** | empreinte vide → `min_distance_between_sets` lève « Cannot compute distance between empty sets » | bruyant, donc déjà partiellement traité par 04c |
| **ENGAGEMENT** | verdict d'engagement FAUX, sans crash | **RÉELLE, et pire que décrit** — voir ci-dessous |

Le doc d'origine laissait la famille ENGAGEMENT ouverte (« à trancher par la mesure ») et la
supposait due au repli d'ancre de `_cache_entry_footprint`. **C'est faux.** L'entrée-cache hors
table a `occupied_hexes_by_model` et `floor_height_by_model` **entièrement peuplés de `(-1,-1)`**,
donc `entry_has_vertical_data` rend True et la mesure part sur le **chemin 3D** — le repli d'ancre
n'est jamais atteint. Mesuré à x1/hex, EZ = 2 :

| paire | verdict moteur AVANT |
|---|---|
| fantôme `(-1,-1)` vs unité réelle en `(0,0)` | **ENGAGÉE** (faux) |
| fantôme vs fantôme | **ENGAGÉE** (faux) |
| fantôme vs unité réelle en `(1,1)` | non engagée (correct) |

Au reset, les 12 unités hors table étaient donc toutes mutuellement « engagées », et ça remontait
jusqu'aux features d'observation IA `engaged` / `in_enemy_ez`.

### Le recensement réel

Le doc annonçait ~30 sites. Le grep du motif `entry.get("occupied_hexes", {ancre})` en donnait
**96**, plus une trentaine d'énumérations `for … in units_cache.items()` faisant de la géométrie.
Le motif `.get` ne protégeait rien : hors table, la clé est **PRÉSENTE et VIDE**, donc le défaut
du `.get` ne se déclenche jamais et l'ensemble vide passe.

## La décision d'architecture

La question ouverte était : ~30 correctifs par-site, ou UN point d'étranglement ?

**Réponse : les deux, à des rôles différents.** Un point d'étranglement ne peut pas décider à la
place de l'appelant — hors table, la conduite juste est de **SAUTER** l'unité dans une
énumération, et c'est une **ERREUR** de la mesurer nommément. Un helper feuille qui rendrait
« distance infinie » serait exactement le fallback interdit par T1.

D'où la règle qui structure tout le correctif :

> **Une MESURE par paire lève ; un PRÉDICAT sur le plateau répond par la RÈGLE ; une ÉNUMÉRATION
> filtre.**

### Les primitives (`engine/spatial_relations.py`)

`entry_is_on_battlefield` a été **déplacé** de `shared_utils` vers `spatial_relations` (couche
basse, qui ne dépend que de `hex_utils`) parce que les primitives de mesure en dépendent
elles-mêmes. `shared_utils` le ré-exporte : les imports existants sont intacts, c'est le même
symbole.

| Primitive | Rôle | Hors table |
|---|---|---|
| `require_entry_on_battlefield(entry, what)` | garde nommée | **lève** |
| `entry_footprint(entry)` | empreinte d'escouade, source unique (remplace les 96 `.get`) | **lève** |
| `entries_in_engagement_zone(a, b, …)` | mesure EZ par paire | **lève** |
| `unit_within_engagement_zone_footprints(gs, u, …)` | prédicat « engagée ? » sur tout le plateau | **`False`** (20.01) |
| `entries_on_battlefield(cache, exclude_id=…)` | énumération, toutes unités | **écarte** |
| `enemy_entries_on_battlefield(cache, player, exclude_id=…)` | énumération, ennemis | **écarte** |

Le `False` de la 4e ligne n'est pas un repli anti-erreur : c'est un prédicat qui a une réponse de
règle (une unité absente du champ de bataille n'est engagée avec personne), interrogé sur TOUTES
les unités vivantes par le snapshot 12.04 et par l'observation. La MESURE par paire, elle, n'a
aucune réponse juste pour une entrée sans position — elle lève.

Le repli sur l'ancre de `entry_footprint` ne subsiste que pour les entrées **synthétiques posées**
(mover candidat de `move_anchor_violates_engagement_clearance`, fixtures mono-figurine), où il est
exact.

### Effet de bord voulu : le défaut devient bruyant

Faire lever les feuilles a transformé chaque filtre manquant en crash localisable au lieu d'un
verdict faux silencieux. C'est ce qui a permis de trouver les sites : la suite des réserves est
passée de 25 échecs à 0 en suivant les tracebacks un par un.

## Les correctifs par-site du chantier 04c

Les quatre correctifs de 04c ont été **retirés** — pas supprimés, *déplacés* dans l'énumérateur :

- `_build_weapon_availability_enemy_precheck` (côté cible) ;
- `build_unit_los_cache` (côté cible) ;
- `_unit_has_firable_target` (côté cible) ;
- `_select_move_after_shooting_destination_for_ai`.

Des gardes `entry_is_on_battlefield` **restent** dans `shooting_handlers`, `charge_handlers` et
`movement_handlers`, et c'est volontaire : les `*_phase_start` / `*_build_activation_pool` portent
la règle « une unité hors table ne choisit pas son arme, ne tire pas, ne charge pas, ne bouge
pas », côté ACTEUR. Ce ne sont pas des filtres d'énumération d'ennemis.

## Les verrous

`tests/unit/engine/test_off_table_geometry.py`. Ils portent sur les deux familles, et chacun est
construit pour ne pas être **vert vacant** :

- contrat des primitives (lève / rend `False` / écarte), avec le test symétrique qui prouve que la
  primitive rend bien quelque chose sur une entrée normale ;
- famille ENGAGEMENT par le chemin de production, avec une unité réelle **amenée en `(1,1)`** ;
- famille DISTANCE par le chemin de production, avec le tireur amené au coin du plateau.

⚠️ **Le piège à ne pas redécouvrir** est géométrique : la sentinelle `(-1,-1)` est à ~274 subhex de
la zone de déploiement de la fixture, donc hors de toute portée d'arme (120-240). Un test qui met
une unité en réserves *sans rien d'autre* reste **VERT avec le défaut**, parce que le fantôme
n'est jamais mesuré. Il faut CONSTRUIRE la géométrie. Second piège du même ordre :
`shooting_phase_start` ne fait le choix d'arme complet que si l'unité est en advance ou au
contact — sinon le précheck d'ennemis n'est jamais atteint.

C'est exactement pourquoi les tests
`test_strategic_reserves_20.py::test_shooting_phase_start_runs_with_a_reserve_{enemy,shooter}` de
04c ne valaient pas verrou : ils restaient verts quand on retirait les filtres.

## Ce qui attend encore

Le chantier 04c a livré 6 variantes de rosters avec réserves stratégiques, rangées dans des
sous-dossiers `variants/` :

- `config/agents/ArmageddonAgent/rosters/500pts/training/variants/`
- `config/agents/ArmageddonAgent/rosters/500pts/holdout_regular/variants/`
- `config/agents/_p2_rosters/500pts/training/variants/`

Elles sont **hors du tirage** : le glob de `training_random` (`engine/game_state.py`,
`_resolve_roster_ref`) n'est pas récursif. Le blocage technique est levé ; l'activation reste une
**décision utilisateur** :

1. déplacer les 4 variantes `training/` d'un cran vers le haut (hors de `variants/`) ;
2. ajouter les 2 refs adverses à `opponent_roster_ref` dans
   `config/agents/ArmageddonAgent/scenarios/training/scenario_training_armageddon.json` ;
3. pour le holdout, créer les scénarios correspondants (`scenario_bot-05..08`) — ses rosters sont
   référencés **explicitement**, il n'y a pas de tirage. ⚠️ Ça double le coût d'évaluation et
   change la composition du holdout.

Tant que rien n'est activé, la ventilation `bot_eval/roster/*` livrée par 04c ne publiera jamais
de courbe « avec réserves ».

## Ne pas oublier

`tests/unit/engine/test_strategic_reserves_20.py` est pointé sur une fixture à rosters pinnés
(`scenarios/training/reserves_20_fixture.json`) pour être indépendant du contenu du dossier
`training/`. Ne pas le repointer sur `scenario_training_armageddon.json` en activant les
variantes : 16 de ses tests supposent que toutes les unités démarrent posées.
