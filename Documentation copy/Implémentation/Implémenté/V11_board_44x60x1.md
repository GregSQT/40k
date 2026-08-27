# Board 44x60x1 — banc d'itération rapide, même plateau physique

**Statut :** ✅ IMPLÉMENTÉ (2026-07-27) — plateau, conversion du terrain et des rosters, retrait
de `25x21`. Le scénario Armageddon tourne à x1 de bout en bout, PvP et PvE de test aussi.
Résidus fermés le 2026-07-28 : topologies précalculées retirées (§5), mode tutoriel supprimé (§5),
double définition de la zone d'engagement mesurée sans effet (§2 bis), icônes converties (§2).

**But :** mesurer une TENDANCE d'entraînement (obs, hyperparamètres, santé PPO) en quelques
heures au lieu de ~60, sans changer de plateau physique. Le modèle produit est jetable : la
géométrie de socle n'existe pas à x1 (voir §4).

---

## 1. Pourquoi 44x60x1 et pas 25x21

`board/25x21` est un **autre plateau** (25×21 pouces), pas le 44×60 en basse résolution. Y jouer
un scénario 44×60 fausse toute la géométrie tactique : 74 figurines sur 525 hexes, et des portées
de 24" sur un plateau qui en fait 25 de large. La tendance mesurée n'y serait pas transposable.

`44x60x1` est le **même plateau physique** que `44x60x5` et `44x60x10`, à 1 hex = 1 pouce :
2640 hexes au lieu de 66 000, mêmes distances en pouces, mêmes portées relatives.

---

## 2. Conversion au CHARGEMENT, pas de données dupliquées

`board_ref` déclare la résolution **native** des fichiers partagés d'un scénario (murs, terrain).
Le plateau actif vient de `W40K_BOARD_PATH` (ou `--resolution`). Quand le second est plus
grossier que le premier, `game_state` convertit les coordonnées à la lecture :

- `_board_ref_downscale_ratio()` — rapport `ish_source / ish_actif`, lu dans les deux
  `board_config.json`. Rapport non entier, ou plateaux qui ne se correspondent pas après
  réduction ⇒ **erreur explicite**, jamais une conversion approximative. Résolutions identiques
  ⇒ rapport 1, donc PvP et x5 strictement inchangés.
- `_downscale_terrain_data()` — convertit exactement `terrain[].vertices`,
  `terrain[].floors[].vertices`, `walls[].segments`, `walls[].hexes`,
  `deployment_zones[].vertices`, `icons[].center`. `height_inches` reste en pouces.
  `icons[].size` est une taille en pixels, mise à l'échelle du rayon d'hex (× rapport).
- `hex_utils.downscale_cell()` — la conversion d'une coordonnée. **Diviser col et row séparément
  est faux** : en odd-q les colonnes impaires sont décalées d'une demi-hauteur d'hex, et une
  division par axe ignore ce décalage — mesuré sur `terrain-mc1`, elle déplace **28 % des points
  d'une case**. La conversion passe donc par le centre projeté (`_hex_projected`, la projection
  déjà utilisée par la rasterisation des polygones et par le rendu) et retient la cellule
  grossière dont le centre est le plus proche.

Toutes ces coordonnées sont des **indices de cellule**, y compris les sommets de polygone :
`_objective_polygon_hexes` projette ses sommets avec `_hex_projected` avant de tester
l'appartenance. Il n'y a donc pas deux règles de conversion à distinguer.

Trois entrées converties, aucune laissée de côté : `_read_terrain_file()` (traversé par les trois
lecteurs de terrain — murs, zones de déploiement, aires), les murs partagés (`wall_ref`), et les
`wall_hexes` écrits directement dans un scénario. Cette dernière n'est convertie que si le
scénario déclare sa résolution d'origine — `board_ref`, ou appartenance à
`config/board/<board>/scenario/` (`_has_declared_source_board`) ; sans déclaration il n'y a pas
d'échelle source. Les murs partagés (`wall_ref`) sont convertis **avant**
rasterisation, pour que `hex_line` trace la ligne dans la grille cible — réduire des hexes déjà
rasterisés donnerait une ligne à trous. Le rapport fait partie de la clé du cache de murs :
`W40K_BOARD_PATH` change en cours de processus (l'API PvP le fait par requête).

Le `board_config.json` du plateau source est mémoïsé sur `(chemin, mtime_ns)` : le rapport est
demandé 4 fois par reset (murs, murs denses, aires, zones), soit autant de relectures et de
parses JSON par épisode sans ce cache.

**Pourquoi pas des fichiers terrain dédiés x1** : une copie par résolution diverge de l'original
au premier changement, sans que rien ne le signale. Même raisonnement que pour les rosters
(lot 3).

---

## 2 bis. Coordonnées de roster (lot 3)

Les positions de figurines d'un roster sont écrites dans la résolution déclarée par le
`board_ref` du scénario, exactement comme son terrain — **aucun roster dupliqué par
résolution**. Les 4 rosters d'entraînement (SM/Orks × agent/adversaire) restent la seule source.

Réduire chaque figurine séparément ne suffit pas : dans un roster x5 les figurines d'une escouade
sont espacées de 4 à 8 subhex, soit **moins d'un hex** après réduction — elles s'écraseraient
toutes sur la même case. `_downscale_fixed_unit` place donc chaque figurine sur sa case réduite
si elle est libre, sinon sur la case libre la plus proche, dans un rayon borné par
`unit_model_cohesion_range` (03.03) : au-delà, la figurine ne serait plus dans sa propre
escouade. Aucune case libre dans ce rayon ⇒ **erreur explicite**.

Trois points de contrat :

- l'invariant **ancre == `models[0]`** (dont dépend `build_units_cache`) est maintenu ;
- les cases retenues sont réservées, sauf celle de l'ancre — c'est l'appelant qui valide et
  réserve l'empreinte de l'ancre. À résolution native rien ne réserve les cases **par figurine**
  (seule l'empreinte de l'ancre l'est), ce qui est sans conséquence là où les figurines sont
  espacées mais ferait se superposer deux escouades voisines ici ;
- la conversion renvoie une **copie** : `unit_data` peut venir d'un scénario mémoïsé, le muter
  ferait convertir deux fois au chargement suivant.

**Limite refusée explicitement** : le placement converti raisonne PAR CASE (une figurine = une
case). Sur un plateau à empreintes multi-hex, ne réserver que la case centrale laisserait deux
socles se chevaucher sans signal — la conversion lève donc une erreur si le plateau cible a
`inches_to_subhex > 1`. Aucune paire de plateaux du dépôt n'atteint ce cas (les données sont en
x5, la seule cible plus grossière est x1, où une figurine tient dans une case) ; livrer un
placement par empreinte que rien ne pourrait exercer serait plus risqué que le refus.

Mesure sur le scénario Armageddon à x1, **20 seeds** (le roster d'agent est tiré entre SM et
Orks à chaque chargement, les deux compositions sont donc couvertes) : 222 escouades,
**0 en violation de cohérence** (03.03), **0 chevauchement** de figurines.

`change_roster` n'est pas concerné : l'API le refuse hors déploiement actif
(`change_roster_requires_active_deployment`), donc les positions viennent de la phase de
déploiement et non du roster.

### Le socle est normalisé en `round`/1 à x1

À `inches_to_subhex == 1` une figurine tient dans UNE case — c'est la définition de cette
résolution (`_compute_deploy_footprint` ne rend qu'un hex, `is_micro_board` est faux). La FORME du
socle n'y a donc plus de sens géométrique : `_scale_socle()` (autorité unique, unité et figurines)
renvoie `round`/1.

Ne pas normaliser casse le moteur de deux façons **opposées**, selon le type de taille laissé :

| Taille laissée à x1 | Symptôme |
|---|---|
| scalaire `1` avec `BASE_SHAPE = "oval"` | `hex_utils._socle_edge_primitives` indexe `size[0]` sur un int → `TypeError: 'int' object is not subscriptable` dès qu'une distance bord-à-bord est calculée (Carnifex, WarTrakk, LandSpeeder) |
| paire `[1, 1]` avec `BASE_SHAPE = "oval"` | `is_single_hex = (ez <= 1 or base_size == 1)` devient faux → l'unité passe sur le chemin **multi-hex** du pool de move, qui évalue l'engagement ennemi depuis les SOCLES, alors que `validate_move_plan` le lit dans le set dilaté `enemy_adjacent_hexes_player_N`. Les deux définitions ne coïncident pas : `ValueError: execute_squad_move a échoué … incohérence masque/exécution`, et les workers `SubprocVecEnv` meurent |

Le premier symptôme préexistait (il touchait aussi l'ancien x1 sur 25x21, jamais atteint faute de
socle ovale dans ses scénarios). Le second a été **introduit puis corrigé pendant ce chantier** :
un premier correctif produisait `[1, 1]`, ce qui déplaçait le défaut au lieu de le fermer. Mesuré :
4 épisodes sur 10 mouraient à x1 à travers la pile d'entraînement complète (bots inclus), 12 sur 12
passent après normalisation ; x5 inchangé.

Ce que la normalisation NE traite pas : les deux définitions de « dans la zone d'engagement
ennemie » restent distinctes — dilatation hex du set `enemy_adjacent_hexes_player_N` d'un côté,
distance bord-à-bord de socles (`entries_in_engagement_zone`, métrique `engagement` de
`game_config.json`) dans le pool d'ancre multi-hex de l'autre. Ce n'est PAS un risque
d'incohérence masque/exécution : le seul site où cette incohérence est fatale
(`execute_squad_move` → `validate_move_plan`, chemin gym-only) reçoit un masque déjà érodé par
`erode_move_pool_by_squad_block`, qui rejoue le prédicat de cellule de `validate_move_plan` —
même helper `build_move_blocked_cells_by_level`, donc même set dilaté — sur TOUTES les figurines
du bloc. L'inclusion `masque ⊆ exécutable` tient donc par construction (T6-g/T6-h), quoi que le
pool d'ancre ait filtré en amont ; le prédicat de socle n'y est qu'un filtre supplémentaire, qui
peut retirer des destinations mais jamais en offrir que la validation refuserait.

Mesuré (2026-07-28), les deux définitions ne divergent nulle part où le moteur peut aller. Dès
`base_size > 1` (ennemi socle 6, x5, `ez` = 10 subhex) la dilatation est INCLUSE dans la zone de
socles — 469 cases contre 691, aucune case interdite par la seule dilatation — donc le prédicat
effectif est le bord-à-bord de socles, conforme à 03.04, et l'érosion ne retranche rien de plus.
À `base_size == 1` les deux côtés retombent sur la dilatation (chemin `is_single_hex`), donc
cohérents entre eux ; et à x1, où la normalisation du socle rend ce cas universel, les deux
ensembles sont IDENTIQUES (19 cases contre 19, différence symétrique vide à `ez` = 2). Le cas
« socle 1 à x5 », seul à faire diverger dilatation et règle (36 cases trop permissives, 6 trop
strictes), n'est atteignable par aucun roster : le plus petit `BASE_SIZE` du dépôt vaut 10 (1"),
soit 5 subhex à x5. Unifier les deux définitions coûterait le cache global
`enemy_adjacent_hexes_player_N` (O(1), partagé par quatre phases) sans corriger aucun
comportement observable — non fait, délibérément.

Verrou : `tests/unit/engine/test_socle_normalized_at_x1.py` construit la configuration
(socle non-rond + ennemi à portée d'EZ) et vérifie qu'aucune destination du pool ne tombe dans la
zone d'engagement. Contre-épreuve par mutation : **6 destinations sur 506** y tombent sans la
normalisation. `test_move_mask_is_executable.py` a été étendu aux deux résolutions, mais reste vert
sous la même mutation (trajectoires aléatoires, motif §0.11) — sa docstring le dit désormais, pour
ne pas laisser croire qu'il couvre ce cas.

## 3. Ce que contient le plateau

`config/board/44x60x1/board_config.json`, et rien d'autre côté terrain : murs, terrain et
objectifs restent ceux du `44x60x5`, convertis au chargement. Seule exception,
`walls/tutorial_walls-01.json`, rescapé du board supprimé (§5) — ses coordonnées sont en pouces,
donc déjà à l'échelle de ce plateau.

| Champ | Valeur | Raison |
|---|---|---|
| `cols` × `rows` | 44 × 60 | 1 hex = 1 pouce |
| `inches_to_subhex` | 1 | |
| `hex_radius` | 13.9 | = 2.78 × 5 → canevas de largeur identique au x5 |
| `margin` | 5 | idem (1 × 5) |
| `chunk_size` | 8 | 44 colonnes, la valeur x5 (64) n'a plus de sens |

`config/primary_objective/44x60/Objectives_Control.json` : copie du fichier 220x300 — ces
fichiers ne portent **aucune coordonnée**, uniquement des règles de score. Le loader les cherche
sous `primary_objective/{cols}x{rows}/`.

`--resolution 1` pointe désormais `board/44x60x1` (`ai/train.py`).

⚠️ **`--resolution 10` échoue maintenant explicitement** sur les scénarios de la banque : leurs
données sont déclarées en x5 et la conversion ne va que vers le PLUS GROSSIER — remonter en x10
demanderait d'inventer de l'information. Avant ce chantier l'option « marchait » en silence, en
posant du terrain x5 sur un plateau 360×312, donc à la mauvaise échelle. Le message d'erreur nomme
les deux résolutions. Le texte d'aide de l'option le dit.

---

## 4. Ce que le banc x1 ne mesure pas

`inches_to_subhex = 1` ⇒ `is_micro_board = False` ⇒ **une figurine occupe un hex, pas d'empreinte**.
Tout ce qui dépend du socle multi-hex (pile-in et consolidation par figurine, occlusion
partielle, engagement au socle) n'est pas exercé. Le win-rate absolu et la difficulté
d'exploration ne se transposent pas non plus ; la tendance (KL, entropie, explained variance,
value loss, oubli catastrophique) si.

L'observation, elle, est invariante en résolution : la grille égocentrique fait 32 cellules pour
une demi-étendue égale au budget d'Advance en subhex, soit ~1,1 pouce par cellule à x1 comme à
x5 ; les distances sont normalisées par `inches_to_subhex` et les positions par les dimensions
du plateau.

---

## 5. Retrait de `25x21`

Le board `25x21` et ses dossiers annexes (`config/deployment/25x21`,
`config/primary_objective/25x21`) sont supprimés. Ce qu'il portait a été repointé, jamais perdu :

| Élément | Devenu |
|---|---|
| `scenario_pve_test.json`, `scenario_attached_unit_test.json` | portés dans `config/board/44x60x5/scenario/` — leurs coordonnées étaient en POUCES (`inches_to_subhex: 1`), donc converties en subhex x5 par la transformation inverse de `downscale_cell` |
| `scenario_pvp_test.json` | le plateau x5 avait déjà le sien |
| `tutorial_walls-01.json` | conservé dans `config/board/44x60x1/walls/` (coordonnées en pouces, valides telles quelles sur 44×60) |
| option PvP « x1 » | `board/44x60x1`, scénarios lus dans le dossier x5 et convertis |
| `--resolution 1` | `board/44x60x1` |
| topologies `.npz` | plus aucune dans le dépôt — voir plus bas |

**Un scénario de test n'a plus besoin d'exister par résolution.** L'API distingue désormais le
plateau JOUÉ (`BOARD_PATH_MAP`) du dossier qui PORTE les scénarios (`TEST_SCENARIO_BOARD_MAP`,
toujours x5) ; le moteur convertit. La condition d'applicabilité de la conversion est passée de
« le scénario déclare `board_ref` » à « le scénario déclare sa résolution d'origine », c'est-à-dire
`board_ref` **ou** l'appartenance à `config/board/<board>/scenario/` — les deux déclarations que
`_resolve_board_dir` accepte déjà (`_has_declared_source_board`, prédicat unique).

`/api/config/board` lisait murs et terrain dans le dossier du plateau joué. Sur un plateau réduit
ce dossier n'a ni `walls/` ni `terrain/` : l'endpoint lit maintenant les fichiers à leur source et
les convertit avec la même fonction que le moteur. Il refait aussi les deux contrôles du moteur —
rapport entier, et dimensions qui se réduisent bien sur le plateau joué — sans quoi une entrée de
table pointant un autre plateau physique déplacerait murs et terrain en silence. Le rapport est
calculé depuis le `board_spec` déjà chargé et non depuis `W40K_BOARD_PATH`, dont l'override est
déjà refermé à cet endroit de la requête.

Vérifié : à `board_path=x1` l'endpoint rend 44×60, 222 murs dans les bornes, 5 zones d'objectif,
5 icônes, 2 zones de déploiement — les mêmes nombres que le moteur ; à `x5_44x60`, 992 murs, soit
la valeur native inchangée.

Deux options de l'écran de test, `x5` → `board/180x156` et `x10` → `board/360x312`, pointaient des
dossiers **inexistants** : elles échouaient à la sélection. Retirées de l'API et de l'interface.
Conséquence à ne pas manquer : trois sites lisaient `defaults.test_board` avec un littéral de
repli `"x5"`, devenu une clé sans entrée — donc un `KeyError` en attente. Remplacés par
`require_key` + validation d'appartenance à la table (règle 6 : erreur explicite, pas de défaut).

`config/primary_objective/25x21/Endless_Duty-01json` a disparu avec le dossier. Aucune perte :
son contenu était **identique** à `Objectives_Control.json` (même `id`, mêmes règles de score),
conservé sous `config/primary_objective/44x60/`. À noter, son nom était malformé — pas de point
avant `json` — donc le glob `*.json` du loader ne l'avait jamais vu.

### Topologies précalculées : supprimées (2026-07-28)

`25x21` était le seul board à embarquer des `topology_*.npz`, et `scripts/los_topology_builder.py`
n'existe plus : plus rien ne pouvait alimenter `los_topology`, `pathfinding_topology` ni
`wall_edge_topology`, dont les branches moteur étaient donc inatteignables. Le mécanisme entier
est retiré — chargeur `_load_topology_cached` et son cache (`w40k_core`), branches de lecture
(`observation_builder`, `combat_utils`, `shooting_handlers`), clés exclues du JSON client
(`api_server`) et clés statiques de snapshot (`game_snapshots`), plus `Documentation/LOS_TOPOLOGY.md`.
Les chemins à la demande qui servaient déjà (`compute_los_visibility`, `compute_los_state`, BFS de
`calculate_pathfinding_distance`) sont désormais les seuls, donc zéro changement de comportement.
`_has_los_from_topology` est renommé `_has_los_on_demand` : son nom disait le contraire de ce
qu'il faisait.

### Les scénarios de tutoriel : mode supprimé (2026-07-28)

`config/tutorial/scenario_etape*.json` ne se chargeaient plus — pas de `board_ref` et hors d'un
dossier `config/board/<board>/scenario/`, donc `wall_ref` non résoluble (contrainte V11 T4), défaut
antérieur à ce chantier. Le mode tutoriel étant obsolète, il a été retiré en entier plutôt que
réparé : `config/tutorial/`, les crochets moteur (`tutorial_fight_no_death_unit_ids`, script P2 de
`pve_controller`, clés `_tutorial_force_*`), le mode `tutorial` de l'API et son endpoint
`/api/auth/tutorial-complete`, la colonne `users.tutorial_completed` et la redirection de premier
login, et côté front `TutorialProvider` / `TutorialOverlay` / `tutorialUiRules` /
`tutorialScenarioRuntime` avec tous leurs points d'accroche (BoardWithAPI, BoardPvp,
UnitStatusTable, GameLog, TurnPhaseTracker, SharedLayout, Routes).

Les **guides de mode** (popups d'intro PvE/PvP, réglage Settings › Guides) partaient de la même
infrastructure : ils sont supprimés avec elle, décision explicite de l'utilisateur — sans quoi
l'overlay entier devait être conservé pour eux seuls. `tutorial_walls-01.json` reste dans
`config/board/44x60x1/walls/`. `Documentation/Old/Tutorial.md` garde la spec, avec un bandeau
disant que la fonctionnalité n'existe plus.

Vérifié après retrait : `tsc` et `biome` verts sur le front, `pyright` vert sur les fichiers
moteur/API touchés, `scripts/pvp_smoke_test.py` à **27 PASS / 0 FAIL**.


---

## 6. Vérifications

`tests/unit/engine/test_board_downscale.py` (18 cas) : rapport 1 à résolutions égales, rapport 5
de x5 vers x1, refus explicite d'un plateau physiquement différent (`44x60x10`, dont le ÷10 donne
36×31), conformité à un
**oracle géométrique indépendant** (balayage de tout le plateau grossier, ce qui valide aussi la
fenêtre de recherche de `downscale_cell`) avec contrôle que le résultat diffère bien de la
division naïve, conversion des seuls champs de coordonnées, `height_inches` préservé, source non
mutée, identité à rapport 1, segment plus court qu'un hex conservé comme une case, et
bout-en-bout sur `terrain-mc1` (murs et zones dans les bornes à x1, coordonnées natives
préservées à x5).

Le même fichier couvre les coordonnées de roster : figurines d'une escouade sur des cases
distinctes, invariant ancre == `models[0]`, absence de chevauchement entre deux escouades
voisines, déterminisme de la conversion, cohérence d'escouade (03.03) tenue sur 4 seeds du vrai
scénario, refus d'un plateau à empreintes multi-hex, et socle non-rond normalisé en `round`/1
après conversion du roster.

`tests/unit/engine/test_socle_normalized_at_x1.py` (7 cas) verrouille la normalisation elle-même
sur les trois socles non-ronds du dépôt (WarTrakk, Carnifex, LandSpeeder) : forme et taille à x1,
une seule case occupée, paire préservée à x5, et l'invariant « aucune destination du pool dans la
zone d'engagement ennemie ». Contre-épreuve par mutation : 6 destinations sur 506 la violent sans
la normalisation.

Chargement réel du scénario Armageddon, `deployment_type` forcé à `active` :

| | x5 (220×300) | x1 (44×60) |
|---|---|---|
| murs | 992 | 222 |
| bornes col/row | 7–213 / 32–267 | 1–43 / 6–53 |
| objectifs | 5 (10 538 hexes) | 5 (421 hexes) |
| pools de déploiement | 16 104 / 16 472 | 581 / 647 |

Les surfaces suivent le rapport ÷25 attendu (10 538/25 = 421,5), les longueurs ÷5.

Épisode complet joué au moteur nu (actions masquées aléatoires, même scénario, même seed) :

| | x5 (220×300) | x1 (44×60) |
|---|---|---|
| durée d'un épisode | 10,65 s (122 steps) | **2,17 s** (125 steps) |
| par step | 87 ms | **17 ms** |

Soit **~5× plus rapide** sur le temps moteur. Ce chiffre ne couvre pas les mises à jour PPO ni
les wrappers d'entraînement : le gain observé sur un vrai run sera plus faible.
