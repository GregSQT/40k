# Observation de la phase de déploiement — LES 5 POINTS CORRIGÉS — ✅ DOCUMENT CLOS (2026-07-29)

> ✅ **CE DOCUMENT EST INTÉGRALEMENT CLOS.** Les cinq défauts qu'il recense sont livrés et
> verrouillés par test. Il est archivé dans `Implémenté/` et ne porte plus aucune part ouverte ;
> l'orchestration correspondante est descendue en §0hist de
> [`V11_agent_rework.md`](../../Chantiers/v11/V11_agent_rework.md) sous son numéro §0.40.

> **Origine** : extrait de [`V11_audit_observation.md`](V11_audit_observation.md) §11
> (archivé le 2026-07-28). C'était le seul point **actionnable** restant de cet audit ; il est
> sorti ici pour ne pas rester noyé en fin d'un document d'archive.
> **Constats re-vérifiés dans le code le 2026-07-28** — le point 3 d'origine était inexact, il est
> reformulé ci-dessous.
> **Points 1 et 2 corrigés le 2026-07-28** (commits `0e0551e8` et `2893bbcb`), **point 4 corrigé le
> 2026-07-29** — il a été découvert en vérifiant le correctif du point 2 : le vecteur d'observation
> mesurait lui aussi depuis la sentinelle hors plateau. **Point 5 corrigé le 2026-07-29** — trouvé
> en re-vérifiant le point 4 : une unité pas encore mise en place se déclarait **engagée au
> contact** (règle 03.04). **Point 3 corrigé le 2026-07-29** — le dernier : les 5 slots sont
> désormais décrits par l'effet de l'hexe qu'ils poseraient. C'est le seul des cinq qui change
> `obs_size` (**20768 → 20828**), donc le seul qui impose un retrain `--new`.

## Contexte

Le déploiement consomme le **même** pipeline d'observation que le jeu
(`build_squad_observation` + `build_squad_grid`, cf. [w40k_core.py](../../../engine/w40k_core.py)
`_build_observation`), alors que la décision qu'il porte n'a rien à voir : il ne s'agit pas de
bouger/tirer/charger une escouade en place, mais de **choisir où poser une unité qui n'est pas
encore sur le plateau**. Résultat : l'agent déploie quasiment à l'aveugle.

L'espace d'action du déploiement = **5 slots** (`DEPLOY_SLOT_BASE = 4`, `DEPLOY_SLOT_COUNT = 5`,
[macro_intents.py](../../../engine/macro_intents.py)).

## Les défauts (vérifiés)

### 1. ✅ CORRIGÉ (2026-07-28, `0e0551e8`) — l'obs décrit l'unité sur laquelle le masque agit

**Le défaut** : `_build_observation` construisait l'obs pour `next(iter(units_cache.keys()))` — la
première clé du cache d'unités, tous joueurs confondus, déployées comme non déployées — alors que
le masque ouvre les slots 4-8 pour `eligible_units[0]`, issu de
`deployment_state["deployable_units"][current_deployer]`. Rien ne garantissait que les deux
désignent la même unité : l'agent décrivait A et posait B (motif D1). **Vérifié en test** : dès le
2ᵉ step de déploiement, l'obs décrivait l'unité `1` (joueur 1) pendant que le masque agissait sur
`101` (joueur 2).

**Ce que le code fait maintenant** : `ActionDecoder.get_deployment_active_unit(game_state)` est le
point d'entrée unique — même dérivation que le masque
(`_get_eligible_units_for_current_phase`, pool du déployeur courant filtré vivant), sans
reconstruire les hexes valides (le poste coûteux du masque). La branche `deployment` de
`_build_observation` l'appelle, exactement comme la branche `pending_agent_decision` juste
au-dessus prend l'unité de la décision.

**Cas dégénéré (pool vide)** : `get_deployment_active_unit` **lève**, il ne rend pas d'obs nulle.
Une obs de zéros décrirait un plateau vide à un agent à qui l'on demande quand même d'agir, et le
masque correspondant serait tout-faux — donc injouable. Le `_zero_obs()` précédent masquait cet
état incohérent au lieu de le signaler.

**Verrou** : `tests/unit/engine/test_deployment_observation_contract.py` — à chaque état de
déploiement, l'unité passée à `build_squad_observation` (espionnée, donc littéralement celle
décrite) est celle du masque, appartient au joueur qui déploie, et n'est pas déjà posée.

### 2. ✅ CORRIGÉ (2026-07-28, `2893bbcb`) — la grille est ancrée sur la zone de déploiement

**Le défaut** : une unité non déployée porte `deployed_on_turn is None`, marqueur écrit sous la
forme `col < 0` (`create_unit`, [game_state.py](../../../engine/game_state.py)). `build_squad_grid`
centrait la fenêtre égocentrique sur ce `(-1,-1)`. **Mesuré** sur le board 220×300 : la zone du
joueur 1 s'étend des lignes 151 à 299, la fenêtre (demi-étendue 90) montrait le coin `(0,0)` —
**0 %** de la zone de déploiement visible (25 % pour le joueur 2), et le canal SELF peint sur
l'ancre bidon. L'agent ne voyait pas le terrain où il allait se poser.

**Ce que le code fait maintenant** : `ObservationBuilder.squad_grid_anchor(game_state, squad_id)`
(statique, publique donc testable) rend l'ancre de la grille. Escouade posée → son `col/row`,
inchangé. Escouade **pas encore posée** → un hex de sa **zone de déploiement**, lue telle quelle
dans `game_state["deployment_pools"]` — la MÊME collection d'hexes que celle où le décodeur
choisit l'hexe (`_get_valid_deployment_hexes`), donc aucune géométrie recalculée. L'ancre est l'hex
du pool le plus proche du barycentre (calculé en coordonnées de rendu `_hex_center`, pas en
`(col,row)` brut : la grille hexagonale décale d'une demi-ligne une colonne sur deux), ce qui la
garde **dans** la zone même quand celle-ci est concave. Elle lève si le pool manque : une unité
hors plateau sans zone où la poser est un état incohérent.

La **géométrie** de la grille (`engine/spatial_grid`, source unique partagée avec le masque et le
décodeur) est **inchangée** — seul le point d'ancrage bouge. L'ancre est mémoïsée par joueur
(`_grid_deployment_zone_anchor`, pool statique sur la partie) et **purgée au reset** comme les
autres caches d'obs, sinon l'agent déploierait en regardant la zone de l'épisode précédent.

**Résultat mesuré** : 96 % (joueur 1) et 78 % (joueur 2) des hexes de la zone tombent désormais
dans la fenêtre, contre 0 % et 25 % avant.

**Limite assumée** (géométrie, pas ancrage) : la demi-étendue de la grille vaut le budget Advance
maximal de l'escouade, alors que la zone de déploiement est plus large qu'elle — les hexes de
**flanc extrêmes** (les stratégies 7 et 8) restent hors champ. Les élargir supposerait de changer
la géométrie partagée avec le masque et le décodeur ; c'est le point 3 qui décrit ces hexes
directement, sans toucher à la grille.

**Verrous** (mêmes fichiers de test) : ancre sur le plateau ET dans le pool ; ≥ 50 % de la zone
visible ; canal MURS de la grille produite **égal** à une rasterisation depuis cette ancre (verrou
du câblage, pas seulement de la fonction d'ancrage) ; canal SELF vide avant la pose ; ancre
inchangée pour une escouade posée.

### 3. ✅ CORRIGÉ (2026-07-29) — chaque slot ouvert décrit l'hexe qu'il poserait

**Ce qui était écrit et qui était FAUX** : « les 5 actions = les 5 premiers hexes valides triés ».
En réalité les 5 slots sont **5 stratégies tactiques** évaluées sur **tous** les hexes valides
(~14 000 au premier step) :

| Action | Stratégie |
|---|---|
| 4 | front agressif |
| 5 | pression sur objectif |
| 6 | sûr / cohésion |
| 7 | flanc gauche |
| 8 | flanc droit |

**Le défaut réel** : l'observation ne décrivait **aucun** de ces hexes. Depuis les points 1, 2 et 4
l'agent sait quelle unité il pose, voit le terrain de sa zone et mesure tout depuis elle — mais la
sémantique des cinq slots restait à deviner : ni position, ni distance aux objectifs, ni couvert,
ni exposition, au moment précis où il choisit son point d'entrée dans la partie. Le décodeur, lui,
calculait déjà tout cela dans son cache de scoring.

**Ce que le code fait maintenant.** Un bloc `deploy_cand_cont` (5, 8) / `deploy_cand_bin` (5, 4) —
**60 scalaires** — décrit, par slot, **l'hexe que sa stratégie poserait** :

| Champ | Ce qu'il porte |
|---|---|
| `col_rel` / `row_rel` | position de l'hexe candidat dans la projection `_hex_center`, **relativement à `squad_grid_anchor`** — le repère unique §0.32 T-I, celui de la grille et des directions d'objectif. C'est ce qui situe un candidat de flanc extrême, qui tombe **hors** de la fenêtre égocentrique (limite assumée du point 2) |
| `objective_distance` | hex le plus proche d'un **centre** d'objectif |
| `enemy_distance` | référence ennemie la plus proche (unités posées, sinon ancres de la zone ennemie) |
| `ally_distance` | allié **déjà posé** le plus proche — masqué par `has_deployed_ally` |
| `los_exposure` | nombre d'ennemis **déjà posés** qui voient cet hexe (06.01) |
| `potential_los_exposure` | nombre d'ancres de la zone ennemie qui le voient — la menace à venir |
| `ally_col_count` | alliés posés sur la même colonne (étalement horizontal) |
| `has_deployed_ally` | masque d'`ally_distance` : sans lui, 0 voudrait dire à la fois « collé à un allié » et « aucun allié posé » |
| `on_objective` / `in_cover` | 14.02 et 13.08, lus dans `_grid_static_hex_arrays` — le **même** ensemble que les canaux « objectifs » et « couvert » de la grille |
| `present` | le slot est **ouvert par le masque** (dernier champ, convention §0.37) |

**Trois points de conception, chacun verrouillé par test.**

1. **Un candidat se décrit par son EFFET, jamais par son index.** Le masque n'ouvre que
   `min(5, n_hexes)` slots. La règle vit désormais dans `open_deploy_slot_count`, **source unique**
   appelée par les deux sites de masque et par le constructeur de candidats — elle était écrite en
   trois `min(5, n)` littéraux. Quand il reste moins de 5 hexes valides, ce sont les stratégies
   d'**indices bas** qui survivent : le lien slot ↔ stratégie n'est pas stable, et un réseau qui
   aurait appris « le slot 7 va à gauche » se tromperait précisément là. Un slot **fermé** est une
   ligne de zéros, `present` compris — jamais un candidat plausible.
2. **Source unique, pas une seconde géométrie.** `ActionDecoder.deployment_slot_candidates` rend
   l'hexe **et le plan de formation validé** ; `_select_deployment_hex_for_action` y lit ce qu'il
   commite et l'observation y lit ce qu'elle décrit. Écrire une seconde géométrie aurait laissé
   l'agent choisir un slot d'après un hexe que le commit n'aurait pas posé (motif D1).
3. **Garde à DEUX conditions.** (a) la phase est `deployment` — même patron que
   `is_charge_phase` pour `charge_reachable_max_roll` — **et** (b) l'escouade observée n'est **pas
   encore posée** (`deployed_on_turn`, la même source que le bit `deploy_not_on_board`). La
   seconde n'est pas une précaution : une unité déjà sur le champ de bataille ne choisit plus où
   se déployer. Elle rend la garde plus STRICTE (l'unité que le masque déploie n'est jamais posée,
   verrouillé par le point 1) et évite d'interroger le décodeur pour toutes les escouades déjà en
   place — l'interroger LEVAIT sur un `game_state` dont la phase vaut « deployment » sans que
   personne n'ait à se déployer, cas que les tests d'observation construisent en injectant les
   6 phases à la main. Le bloc reste nul, enfin, pour une escouade qui n'est pas celle sur
   laquelle le masque ouvre les slots 4-8 — décrire à une autre escouade cinq candidats
   qu'aucune de ses actions ne pose serait le défaut du point 1 rejoué une couche plus loin.

**Perf — mesurée.** Décrire cinq stratégies au lieu d'en évaluer une exigeait cinq passes de
scoring sur toute la zone : **871 ms** par step de déploiement en appelant simplement cinq fois
l'ancienne sélection scalaire. La sélection a donc été **vectorisée** : les colonnes de score
(distances, expositions, étalement) sont calculées **une fois** pour les cinq stratégies, qui n'en
diffèrent que par l'ordre du tri lexicographique (`np.lexsort`). Mesure finale sur le board x5,
3 épisodes, 33 steps de déploiement : **285 ms → 345 ms** par step, soit **+59 ms (+21 %)**.
La **parité de choix est exacte** avec l'implémentation scalaire — vérifiée hexe par hexe sur
33 états × 5 stratégies (le tri numpy reproduit `max()` sur tuples, départage par index croissant
compris).

**Nouveau cache** : `_deployment_slot_candidates`, ajouté à l'inventaire d'`AI_OBSERVATION.md`
et à `test_obs_caches_die_with_the_episode.py`. Son tampon est l'état des unités posées, qui
recommence **identique** au début de chaque épisode : la purge au `reset` est obligatoire, le
tampon seul ne suffirait pas.

**Trou trouvé en vérifiant ce point** : `_deployment_scoring_cache` — celui dont ce bloc LIT les
expositions LoS — n'était purgé **nulle part**. `reset_episode_caches` ne voit que les caches
d'instance du décodeur, pas ceux posés dans le `game_state` ; et son garde-fou (« le jeu d'hexes
valides a-t-il changé ? ») ne mord pas au cas critique : un épisode interrompu **avant la 1re pose**
laisse un cache dont le jeu d'hexes coïncide exactement avec celui du nouvel épisode — servi tel
quel, il porterait les expositions calculées sur les **murs du terrain précédent**. Purgé, inscrit à
l'inventaire (six → **huit** caches), rouge sous mutation de la purge. Sans le point 3 il n'aurait
faussé qu'un choix d'heuristique ; avec lui, il serait devenu une **observation** fausse.

**`obs_size` 20768 → 20828** (5 profils de config alignés, `justification` incluse ; le moteur lève
à l'init si config ≠ code). `TOTAL_ACTION_SIZE` reste **1107**.

**Verrous** (`tests/unit/engine/test_deployment_candidate_observation.py`, 10 tests, chacun rouge
sous mutation de son propre volet) : le slot `i` décrit l'hexe que
`_select_deployment_hex_for_action(4 + i)` choisirait — cache purgé avant l'interrogation, pour que
le décodeur **recalcule** au lieu de relire ce que l'observation vient d'écrire ; les positions sont
mesurées depuis l'ancre de zone et **diffèrent** de celles qu'aurait produites la sentinelle
(leçon §0bis : un bloc non vide ne prouve pas qu'il regarde au bon endroit) ; distances,
`on_objective` et `in_cover` sont recalculés depuis le `game_state` brut ; les bits `present` sont
**exactement** les slots que le masque ouvre, y compris sous troncature forcée à 3 hexes valides ;
le bloc est nul hors déploiement et pour une autre escouade ; et la distance hex vectorisée rend
**exactement** `calculate_hex_distance`.

✅ **Ce qui restait hors périmètre de ce document est LIVRÉ le 2026-08-07** (architecture de la
policy, pas contrat d'observation) : les ids `4-11` tombent toujours dans la plage des cellules de
move (`MOVE_CELL_BASE = 0`), mais leurs logits sortent désormais de `deploy_query_net`, jumelle de
`choice_query_net`, qui score les embeddings de ce bloc — et non plus de la **conv 1×1 de la
carte**, aux cellules `(0, 4..11)`. La policy distingue les deux familles par le bit
`phase_deployment` de `global_bin`, seul signal qui les sépare. Détail en
[`V11_agent_rework.md`](../../Chantiers/v11/V11_agent_rework.md#s0.44) **§0.44** (élément `L1` du lot §0.48).

### 4. ✅ CORRIGÉ (2026-07-29) — le vecteur mesure depuis la zone, comme la grille

**Le défaut** (trouvé le 2026-07-28 en vérifiant le correctif du point 2, il n'était identifié
nulle part). Le point 2 ne visait que la **grille** ; le **vecteur** souffrait exactement du même
défaut.

`build_squad_observation` prenait son origine de mesure dans
`anchor_x, anchor_y = _hex_center(centroid_col, centroid_row)` — le **centroïde de l'escouade
active**, qui vaut `(-1,-1)` pour une escouade pas encore posée (vérifié :
`squad_cache[uid]["centroid_col"/"centroid_row"] == -1.0`). Tout ce que l'observation exprime
« depuis moi » était donc mesuré depuis le coin hors plateau :

- `objective_distance_0..4` et `objective_dir_cos/sin_0..4` (contexte global) ;
- `col_rel` / `row_rel` de **toutes** les entités alliées et ennemies (leur position relative est
  donnée par rapport à `(-1,-1)`, pas par rapport à l'endroit où l'unité va se poser).

**Mesure avant correctif** (scénario d'entraînement Armageddon, 1ʳᵉ unité du joueur 1, 220×300) :

| | obj 0 | obj 1 | obj 2 | obj 3 | obj 4 |
|---|---|---|---|---|---|
| distances vues par l'agent, AVANT (depuis `(-1,-1)`) | **38,3** | 146,4 | 142,1 | 221,3 | 255,0 |
| distances vues APRÈS = réelles depuis sa zone (147, 249) | 178,9 | 166,3 | 70,4 | 69,4 | **11,3** |

L'**ordre était inversé** : l'agent voyait comme objectif le plus proche (38,3) celui qui est en
réalité le plus lointain (178,9), et ne voyait pas que l'objectif 4 est à 11,3 de sa zone. Les
trois actions de zone (`zone_intent`) s'appuient sur ces mêmes nombres.

**Ce que le code fait maintenant.** L'origine de mesure d'une escouade **non posée** est
`ObservationBuilder.squad_grid_anchor` — exactement celle de la grille (point 2). Ce n'est pas un
repère de plus : c'est ce qui **rétablit** l'invariant déjà écrit au-dessus de ce calcul (§0.32
T-I, « un seul repère pour tout ce que l'observation exprime *depuis moi* »). Sans cela, le
vecteur et la grille auraient décrit deux régions différentes du plateau. Escouade posée →
centroïde, **inchangé**.

**Le point de conception, tranché.** Déplacer l'origine sans rien d'autre aurait empilé toutes les
unités **non posées** — l'active comprise — à une distance absurde au nord-ouest : leurs figurines
sont à la sentinelle, et c'est seulement parce que l'origine ÉTAIT cette même sentinelle que la
valeur sortait à 0 par coïncidence. Donc, pour toute entité pas encore posée :

- `col_rel` / `row_rel` restent **exactement 0** — le bit `deploy_not_on_board`, écrit depuis la
  même source `deployed_on_turn`, porte déjà l'information « pas sur le board » ;
- `self_models_cont` de l'escouade active reste **nul** : par convention elle EST au point de
  mesure, ce que disait déjà la valeur produite avant le correctif ;
- `edge_distance` (distance de **socle à socle**, pas dérivée de l'origine) reste **0** quand
  l'observatrice n'est pas posée : aucun socle n'existe côté attaquant, et 0 est déjà la valeur
  que porte l'entité active, pour qui cette feature n'est jamais écrite. Aucune décision ne s'y
  appuie pendant le déploiement — le masque n'y ouvre que les slots 4-8.

Autrement dit, l'observation ne prétend jamais qu'une unité hors plateau est quelque part ; elle
dit seulement, depuis la zone où l'unité va se poser, où sont les objectifs et les unités déjà
posées.

**Périmètre réel du changement** : les réserves (règle 20) ne sont pas modélisées
(`deployment_handlers`, commentaire de `deployed_on_turn`), donc hors phase de déploiement aucune
unité vivante n'a `deployed_on_turn is None` — l'effet est **strictement borné au déploiement**.
`obs_size` inchangé (20768).

**Verrous** (chacun rouge sous mutation de son propre volet) : distances objectifs == celles
calculées depuis l'ancre de zone, avec contrôle que le scénario distingue bien les deux origines
(l'objectif le plus proche n'est pas le même) ; `col_rel`/`row_rel` == figurine la plus proche
mesurée depuis l'ancre pour les entités posées, **exactement 0** pour les non posées ;
`self_models_cont` nul avant la pose ; et non-régression : une fois le déploiement fini, l'origine
est de nouveau le centroïde.

### 5. ✅ CORRIGÉ (2026-07-29) — une unité pas encore mise en place n'est pas sur le champ de bataille

**Le défaut** (trouvé en re-vérifiant le correctif du point 4, qui ne le couvrait pas). Le point 4
a réparé les grandeurs mesurées **depuis** l'escouade ; restaient celles qui affirment une
**relation** à l'ennemi. Mesuré pendant le déploiement, sur l'escouade active pas encore posée :

| Feature | Valeur observée | Ce que ça affirme |
|---|---|---|
| `engaged` | **1** | elle est au contact de l'ennemi |
| `n_in_enemy_ez` | **6** | ses 6 figurines sont dans la zone d'engagement ennemie |
| `n_fight_eligible` | **6** | ses 6 figurines peuvent combattre |
| `n_models_engaging` | **6** | ses 6 figurines peuvent frapper telle cible |
| `los_can_see` | **1** sur les 6 slots ennemis | elle voit tout le monde — y compris les 3 ennemis pas encore posés |

**La cause** : toutes les unités non posées partagent la sentinelle `(-1,-1)`, donc leurs
empreintes se recouvrent et la primitive d'engagement les déclare mutuellement engagées. La
primitive moteur n'est pas en cause : on lui donnait des empreintes fantômes.

**La règle** — [`03 Moving.pdf`](../../40k_rules/03 Moving.pdf), 03.04 : « A model's engagement
range is **the area of the battlefield** within 2" horizontally and 5" vertically of it ». Une
unité pas encore mise en place n'est pas sur le champ de bataille : elle n'a pas d'engagement
range et n'entre dans celle de personne. Ce n'est donc pas un défaut d'observation « esthétique »,
c'est une affirmation **contraire à la règle**.

**Ce que le code fait maintenant** : le filtre est chez l'**appelant**, en un point — un
dictionnaire `on_battlefield` construit une fois par observation (coût mesuré : **1,9 µs**, 0,08 %
du temps d'une observation). Les escouades non posées sortent du calcul d'engagement, des deux
côtés ; l'active exclue rend `active_relevant_enemies` vide, donc `n_in_enemy_ez` et
`n_relayed_ez` tombent avec, sans garde supplémentaire. Trois gardes explicites complètent :
`get_fighting_models` n'est pas appelé pour une escouade hors table, `n_models_engaging` exige que
les deux escouades y soient, et la LoS non plus n'est pas calculée (06.01 trace une vue entre
figurines **sur** le champ de bataille) — ce qui économise au passage 28 appels LoS fantômes par
step de déploiement.

**`coherent` n'est PAS neutralisé**, et c'est délibéré : 03.03 conditionne le test de cohérence à
« **if that unit is on the battlefield**, it is in coherency » — la règle ne déclare pas
incohérente une unité hors table, elle ne lui applique pas le test. Et `0` signifierait « escouade
éparpillée », une pathologie : un mensonge pire que le silence. La neutralisation à zéro n'est la
bonne réponse que pour les features dont `0` veut dire « rien à affirmer ».

**Verrous** : un **test-inventaire** énumère les features géométriques (`engaged`, `los_can_see`,
`cover_vs_observer`, `charge_reachable_max_roll`, `col_rel`, `row_rel`, `edge_distance`,
`n_fight_eligible`, `n_in_enemy_ez`, `n_relayed_ez`, `n_models_engaging`) et exige qu'elles soient
toutes nulles pour **toute** entité non posée, à chaque step du déploiement — c'est lui qui a
trouvé `n_models_engaging`, oublié à la première passe. Deux tests l'encadrent : un ennemi posé
en `(0,0)` — la zone du joueur 2 contient cet hex et l'engagement range vaut 10 subhex, donc le
cas est atteignable — ne doit PAS engager une unité restée à la sentinelle ; et après déploiement,
l'engagement lu par l'obs doit de nouveau égaler celui de la primitive moteur, pour qu'une
neutralisation trop large ne puisse pas passer inaperçue.

## Périmètre / séquencement

- Les points **1** et **2** sont **corrigés** (2026-07-28) : ils ne changent **pas** `obs_size`
  (`SQUAD_OBS_SIZE_TARGET` = **20768**, verrouillé par test), donc ils n'invalident aucun modèle.
  Ils changent le CONTENU de l'observation de déploiement : un agent entraîné avant eux a appris
  sur une obs fausse à cet endroit, la comparaison de win-rate déploiement avant/après n'a pas de
  sens.
- Le point **3** est **livré** (2026-07-29). C'est le seul des cinq qui étend le contrat
  d'observation : `obs_size` **20768 → 20828** (les 5 profils de la config d'agent portent la
  nouvelle valeur, le moteur lève à l'init si config ≠ code). **Retrain `--new` obligatoire.**
  `TOTAL_ACTION_SIZE` reste **1107** : l'espace d'action n'est pas touché.
- **Ce document n'a plus aucune part ouverte** : il est clos et classé dans `Implémenté/`.
- Traité **séparément** de la refonte du vecteur de jeu (livrée, cf.
  [`V11_entity_encoder_pointer.md`](V11_entity_encoder_pointer.md) et
  [`AI_OBSERVATION.md`](../../AI_OBSERVATION.md)).
