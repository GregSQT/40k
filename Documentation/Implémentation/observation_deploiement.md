# Observation de la phase de déploiement — points 1, 2 et 4 corrigés, point 3 ouvert

> **Origine** : extrait de [`V11_audit_observation.md`](../Implémenté/V11_audit_observation.md) §11
> (archivé le 2026-07-28). C'était le seul point **actionnable** restant de cet audit ; il est
> sorti ici pour ne pas rester noyé en fin d'un document d'archive.
> **Constats re-vérifiés dans le code le 2026-07-28** — le point 3 d'origine était inexact, il est
> reformulé ci-dessous.
> **Points 1 et 2 corrigés le 2026-07-28** (commits `0e0551e8` et `2893bbcb`), **point 4 corrigé le
> 2026-07-29** — il a été découvert en vérifiant le correctif du point 2 : le vecteur d'observation
> mesurait lui aussi depuis la sentinelle hors plateau. **Le point 3 est le seul reste.**

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
dans `deployment_state["deployment_pools"]` — la MÊME collection d'hexes que celle où le décodeur
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

### 3. ⚠️ Les hexes candidats ne sont pas décrits (reformulé — l'énoncé d'origine était faux)

**Ce qui était écrit et qui est FAUX** : « les 5 actions = les 5 premiers hexes valides triés ».
En réalité les 5 slots sont **5 stratégies tactiques** évaluées sur **tous** les hexes valides
(`_select_deployment_hex_for_action`, [action_decoder.py](../../../engine/action_decoder.py)) :

| Action | Stratégie |
|---|---|
| 4 | front agressif |
| 5 | pression sur objectif |
| 6 | sûr / cohésion |
| 7 | flanc gauche |
| 8 | flanc droit |

**Ce qui reste vrai, et qui est le vrai défaut** :
- l'observation ne décrit **aucun** des hexes que ces stratégies vont choisir (position, distance
  aux objectifs, couvert, exposition LoS aux ennemis déjà posés) — alors que le décodeur, lui,
  calcule déjà tout ça dans son cache de scoring (`_get_or_build_deployment_scoring_cache` :
  `los_exposure_by_hex`, `potential_los_exposure_by_hex`, `ally_col_counts`, centres d'objectifs) ;
- le masque n'ouvre que `min(5, num_hexes)` slots : quand il reste moins de 5 hexes valides, ce
  sont les **stratégies d'indices bas** qui survivent, pas les plus pertinentes — le lien
  slot ↔ stratégie n'est plus stable en fin de déploiement ;
- le choix final de l'hexe reste une **heuristique du moteur**, pas une décision de l'agent.

→ **Piste** : exposer par slot le résumé déjà calculé par le cache de scoring (l'hexe que la
stratégie N sélectionnerait, et ses caractéristiques). Aucune nouvelle géométrie à écrire — c'est
une lecture du cache existant, donc source unique préservée.

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

## Périmètre / séquencement

- Les points **1** et **2** sont **corrigés** (2026-07-28) : ils ne changent **pas** `obs_size`
  (`SQUAD_OBS_SIZE_TARGET` = **20768**, verrouillé par test), donc ils n'invalident aucun modèle.
  Ils changent le CONTENU de l'observation de déploiement : un agent entraîné avant eux a appris
  sur une obs fausse à cet endroit, la comparaison de win-rate déploiement avant/après n'a pas de
  sens.
- Le point **3** est le seul reste : extension de contrat d'observation (change `obs_size` →
  retrain `--new`). Les points 1, 2 et 4 sont livrés et ne changent PAS `obs_size`.
- Traité **séparément** de la refonte du vecteur de jeu (livrée, cf.
  [`V11_entity_encoder_pointer.md`](../V11_entity_encoder_pointer.md) et
  [`AI_OBSERVATION.md`](../../AI_OBSERVATION.md)).
