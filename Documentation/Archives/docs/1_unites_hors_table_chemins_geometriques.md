> **⛔ ABSORBÉ le 2026-08-27 par `Documentation/Reference/moteur/geometrie_et_distances.md`** (consolidation Reference) — conservé comme source historique, ne plus maintenir ni citer.

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

## Second passage (2026-08-05) — ce que le premier n'avait pas vu

Un chantier mené en parallèle sur la même classe de défaut a convergé sur la **même architecture**
(prédicat descendu, primitives, énumérations partagées) : cette partie-là a été abandonnée au
profit des primitives ci-dessus, qui vont plus loin. Restent quatre défauts que le premier passage
ne couvrait pas, plus les verrous.

### La fuite inter-épisodes — la plus lourde

Les objets `unit` **survivent d'un épisode à l'autre** (mesuré : 10/10 réutilisés). Le reset
remettait la sentinelle sans remettre `deployed_on_turn`, et ne restaurait ni
`in_strategic_reserves` ni `reserves_repositioned`. Deux conséquences :

- l'observation bâtit son `on_battlefield` sur `deployed_on_turn` : dès l'épisode 2, elle déclarait
  « posées » des escouades à la sentinelle (`[HEAVY]` 24.16 lit le même champ) ;
- surtout, **un roster `strategic_reserves: true` ne se comportait comme tel qu'au PREMIER épisode
  de chaque worker**. En entraînement, la fonctionnalité du chantier 04 était donc inerte.

Corrigé dans la boucle de `reset` qui restaure déjà `col`/`row` depuis `self.config["units"]` —
donc pour **tous** les modes de déploiement — avec la sémantique de `create_unit` (une config de
scénario écrite à la main ne porte aucune de ces clés).

### La divergence masque/exécution sur la charge

`charge_check_eligibility` est la source **unique** que le masque interroge pour ouvrir un slot de
charge ET que le commit `squad_charge` re-vérifie. Son test des 12" est une distance de **grille
brute** sur `_squad_model_positions` : la sentinelle y répond « à portée » pour tout chargeur
proche de l'origine du plateau. Le masque ouvrait donc un slot que `charge_build_valid_plan`
refusait ensuite, et l'activation partait en `charge_fail`. Les deux fonctions sont désormais
gardées.

### L'asymétrie d'éligibilité, et une garde qu'aucun test ne peut tenir

`_fight_v11_grouped_step_eligible` n'avait pas la garde que porte son jumeau
`fight_v11_eligible_unit_ids`. Elle a été ajoutée — mais **sans effet observable**, et c'est
mesuré : `fight_v11_is_pile_in_eligible` et `fight_v11_is_consolidation_eligible` rendent déjà
`False` pour une unité à la sentinelle. Aucun test ne peut la faire virer au rouge ; inutile d'en
chercher un. Elle reste parce que ce `False` vient d'un **effet de bord géométrique** (empreinte
vide) et non d'une règle.

### Du code mort, corrigé et testé pour rien

`_has_los_to_enemies_within_range` existait **en double** (`fight_handlers`, `shooting_handlers`)
et n'avait **aucun appelant**, ni Python ni frontend. Les deux copies sont supprimées. C'est le
piège « corrigé mais jamais atteint » : un premier verrou « miroir tir/mêlée » avait été écrit
dessus, donnant une couverture de façade ; il a été repointé sur
`_friendly_engagement_blocks_ranged_shot` (4 appelants de production).

### Les verrous ajoutés

| Fichier | Ce qu'il verrouille |
|---|---|
| `tests/unit/engine/test_reserves_full_episode.py` | épisode complet, 6 graines, réserves des **deux côtés** ; invariant `col >= 0` ⟺ `deployed_on_turn is not None` à travers un reset ; survie de la déclaration de réserves à l'épisode 2 ; parité masque/commit de la charge |
| `tests/unit/engine/test_fight_off_table_enumeration.py` | `enemy_entries_on_battlefield` **et ses 7 consommateurs appelables**, sur un état construit — la primitive du premier passage n'était verrouillée que par son contrat, pas par ses consommateurs |
| `tests/unit/ai/test_evaluation_bots.py` | les 3 énumérations des bots, que le premier passage a corrigées sans verrou |

Deux leçons de méthode, payées comptant :

- **Une trajectoire ne verrouille pas.** La 1ʳᵉ version du test d'épisode jouait `legal[0]` : une
  graine = une trajectoire, et le fichier certifiait un critère qu'il n'exerçait pas. L'action est
  désormais **tirée** parmi les légales, et la couverture des 4 phases de mesure est vérifiée sur
  l'**union** des graines — par graine, une partie sans phase de charge reste une partie valide.
- **Ce qui n'est atteint par aucune trajectoire doit être CONSTRUIT.** Les filtres de la phase de
  combat n'étaient atteints par aucune graine ; c'est la mutualisation qui les a rendus testables,
  pas un test plus malin.

## Activation des variantes — FAIT le 2026-08-05

Les 4 variantes `training/` sont **dans le tirage** : sorties de `variants/` (le glob de
`training_random` n'est pas récursif) et les 2 refs adverses ajoutées à `opponent_roster_ref`.
Mesuré sur 60 resets du scénario réel : **4 rosters distincts par camp**, contre 2 avant.

L'activation n'était **pas** un changement de config. Elle a ouvert un trou moteur qui rendait le
vrai run impossible, et deux tests qui ne mesuraient plus ce qu'ils annonçaient.

### Le trou : les zones de déploiement étaient enfermées dans une phase

`game_state["deployment_state"]` n'est écrit **que** si un joueur déploie en `active`. Il portait
`deployment_pools`, or deux lecteurs en ont besoin **hors** phase de déploiement :
`ObservationBuilder.squad_grid_anchor` (ancre d'une escouade hors table) et
`_opponent_deployment_zone_cells` (clause 20.04 « pas dans la zone adverse avant le 3e round »).
En mode `fixed`, une unité en réserves 20.01 est hors table **dès le reset** : les deux levaient
`Required key 'deployment_state'`, et le reset entier avec.

Ce n'était pas un cas de test : les 7 profils d'entraînement tirent `fixed` dans **20 à 70 %** des
épisodes (`active_ratio` 0.3 → 0.8).

Correction : les zones sont une donnée de **scénario**, publiées à la racine
(`game_state["deployment_pools"]`) dans **tous** les modes ; `deployment_state` ne garde que la
comptabilité mutable de la phase. Les 8 lecteurs sont repointés sur la source unique, frontend
compris (`DeploymentPools` sort de `DeploymentState` dans `types/game.ts`).

Vérification : en mode `fixed`, sur 8 graines, **13 unités en réserves sur 13 arrivent** (tours 2
et 3, positions variées sur la bande de bord) — le chemin 20.04 est réellement exécuté, pas
seulement « sans levée ».

### Deux tests qui certifiaient un critère qu'ils n'exerçaient plus

- **Mapping de slots faux depuis toujours, révélé maintenant.** Trois tests de
  `test_deployment_observation_contract.py` reconstruisaient les lignes alliées de l'obs **sans**
  le filtre « sur le champ de bataille » que l'obs applique. Tant que les unités non posées se
  triaient APRÈS les posées, le préfixe coïncidait par chance. Une unité en réserves reste hors
  table tout l'épisode, sort en tête du tri, et tout le mapping se décale : liste du test
  `['1','2','4','5']` contre liste de l'obs `['2']`. Le test lisait la position de l'unité 2
  (posée, col=215) en croyant lire celle de l'unité 1 (hors table) — d'où un `col_rel = 90.0`
  attribué à une unité sans position. **Il n'y avait aucun défaut d'observation** : `col_rel` est
  gardé par `deployed_on_turn` depuis §0.40 point 4. Le helper `_obs_ally_rows` porte désormais le
  contrat de l'obs en un point.
- **Un test qui appelait hors du chemin qu'il annonce.** `get_fighting_models` documente son
  contrat chez l'**appelant** : son unique appelant de production ne le sollicite que sur une
  escouade dont il a vérifié `on_battlefield`.
  `test_get_fighting_models_does_not_raise_on_the_observation_path` l'appelait sur **toutes** les
  escouades — un surensemble du chemin d'observation. Il restait vert seulement tant qu'aucune
  unité n'était hors table hors déploiement. Le filtre de production y est maintenant appliqué,
  et le test **exige** d'avoir rencontré au moins une escouade hors table (sinon il ne prouve
  rien sur ce cas).

Trois autres oracles de test mesuraient une géométrie sur des unités hors table
(`test_board_downscale` comptait la sentinelle comme une superposition,
`test_squad_obs_objective_geometry` comparait deux origines différentes,
`test_deployed_units_still_report_engagement_after_deployment` réimplémentait une énumération sans
filtre au lieu d'appeler `enemy_entries_on_battlefield`).

### Ce qui reste une décision utilisateur

Le **holdout** (`scenario_bot-01..04`) n'est pas touché : ses rosters sont référencés
**explicitement**, il n'y a pas de tirage. Couvrir les variantes demanderait 4 scénarios de plus
(`scenario_bot-05..08`), donc le double d'évaluations à chaque point de mesure **et** une rupture
de série — les courbes d'avant/après cesseraient d'être comparables.

Deux faits VÉRIFIÉS le 2026-08-05, à connaître avant de chiffrer ce chantier — ils ne se
devinent pas et coûtent cher à re-dériver :

1. **Les rosters adverses à réserves du holdout N'EXISTENT PAS.** Seules les deux variantes
   *agent* ont été livrées par 04c (`rosters/500pts/holdout_regular/variants/`) ; côté
   `_p2_rosters`, les variantes ne couvrent que `training/`. Or un bot ne DÉCIDE jamais une mise
   en réserves — c'est un choix de LISTE (cf. la docstring de
   `TacticalBot.select_placement_action`, `ai/evaluation_bots.py`). Sans ces deux fichiers, le
   holdout ne peut mesurer que « l'agent utilise ses réserves », jamais « l'agent encaisse une
   arrivée ». Le travail est donc de 4 scénarios **plus 2 rosters à créer**.
2. **La rupture de série est STRUCTURELLE, pas un choix.** Les scénarios du holdout sont ramassés
   par `glob("scenario_*.json")` (`ai/training_utils.py`, collecte par dossier) : tout fichier
   déposé dans `holdout_regular/` entre automatiquement dans l'évaluation, donc dans le score
   combiné et dans le seuil de gating. Il n'existe aucun moyen d'« ajouter à côté » sans toucher
   à l'agrégation. Trois issues, à trancher AVANT de créer quoi que ce soit : déposer les
   scénarios à réserves dans le split `holdout_hard/` (déjà reconnu, énuméré séparément) ;
   restreindre explicitement le score de référence aux 4 scénarios d'origine ; ou assumer la
   rupture et re-baseliner en la datant.

⚠️ `TacticalBot` sait faire arriver ses réserves (sa politique de pose couvre le déploiement
initial ET l'ingress 20.04), mais au « premier slot ouvert », donc de façon DÉTERMINISTE. Un
holdout à réserves mesurerait l'agent face à une arrivée prévisible — acceptable pour un mètre
étalon gelé, mais ce n'est pas une mesure de robustesse face à une arrivée variée.

Second arbitrage, indépendant du coût : l'agent passe de 2 à 4 rosters par camp, ce qui élargit la
distribution d'entraînement alors que la stratégie actée est une **spécialisation sur 2 rosters**
pour la démo.

## Ne pas oublier

`tests/unit/engine/test_strategic_reserves_20.py` est pointé sur une fixture à rosters pinnés
(`scenarios/training/reserves_20_fixture1.json`). Depuis l'activation, ce pin n'est plus une
précaution : c'est ce qui tient le fichier debout — 16 de ses tests supposent que toutes les
unités démarrent posées. Même chose pour `test_bot_ingress_reserves.py`, repointé sur cette même
fixture : il mesure la **décision** du bot de mettre en réserves, il lui faut donc une liste qui
n'en déclare aucune.

`_filter_training_roster_candidates` (`engine/game_state.py`) ne filtre rien aujourd'hui :
`roster_pool_schedule.enabled` est `false` sur les 7 profils — vérifié par la mesure du tirage
(4/4), pas seulement par lecture du JSON. À signaler si on l'active un jour : sa regex
`(elite|swarm|troop)_(\d+)$` écarterait **tous** les rosters Armageddon actuels, y compris les 2
d'origine, et lèverait « zero eligible training rosters ».
