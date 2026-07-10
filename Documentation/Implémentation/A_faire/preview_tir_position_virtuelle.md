# Preview de tir depuis une position virtuelle — découpler la position de l'état

> Doc d'implémentation. Objectif : supprimer le `deepcopy(game_state)` de la preview de tir en
> faisant de la position du tireur un **paramètre** des fonctions de LoS/ciblage, plutôt qu'un état
> global à simuler. Bénéfice : latence de la transition move → tir indépendante du coût de la
> preview, un seul chemin de calcul entre preview et moteur, et un cache de LoS utilisable par les
> deux.

## 1. Le besoin

Pendant la phase de mouvement, quand le joueur promène le ghost d'une escouade, l'UI affiche pour
chaque hex survolé : les cibles tirables depuis cet hex (blink), et les badges couvert / caché /
détection des ennemis. Ces données viennent du backend, via l'action
`preview_shoot_from_position` ([api_server.py:2379](../../../services/api_server.py#L2379)).

La question posée est simple, et purement géométrique :

> Depuis l'hex `(c, r)`, quelles unités ennemies ce tireur peut-il viser, et avec quel couvert ?

Sa réponse ne dépend que de quatre entrées : l'empreinte du tireur à `(c, r)`, les empreintes des
cibles, les murs, le terrain. C'est une **fonction pure**.

## 2. Le problème

`compute_unit_los` ([shooting_handlers.py:4046](../../../engine/phase_handlers/shooting_handlers.py#L4046)),
`build_unit_los_cache` ([shooting_handlers.py:1254](../../../engine/phase_handlers/shooting_handlers.py#L1254))
et `weapon_availability_check` ([shooting_handlers.py:528](../../../engine/phase_handlers/shooting_handlers.py#L528))
ne prennent pas une position en paramètre. Elles prennent `game_state` et vont lire la position dans
`unit["col"] / unit["row"]` et `units_cache`.

Pour poser la question « et si le tireur était là-bas ? », la seule façon disponible est donc de
**fabriquer un monde entier où il est là-bas** :

```python
gs = copy.deepcopy(game_state, _preview_share_memo)   # shooting_handlers.py:1538
set_unit_coordinates(u, dest_col, dest_row)
update_units_cache_position(gs, unit_id_str, ...)
build_unit_los_cache(gs, unit_id_str, ...)
```

De ce choix découle toute une chaîne de compensations :

1. On copie l'état réel → il faut le **geler** pendant la copie → la requête prend
   `_ENGINE_STATE_LOCK` ([api_server.py:1167](../../../services/api_server.py#L1167)).
2. Le lock est pris par le décorateur `@with_engine_state_lock` pour **toute** la requête
   ([api_server.py:2090](../../../services/api_server.py#L2090)), pas seulement pour la copie → le
   POST suivant (commit du move, `end_phase`) **attend la fin de la preview**.
3. Le clic attend → on ajoute un débounce côté client
   ([BoardPvp.tsx:120](../../../frontend/src/components/BoardPvp.tsx#L120)) pour réduire la
   probabilité qu'une preview soit en vol au moment du clic.
4. Le débounce est un compromis entre fraîcheur des badges et latence du clic. Réglé trop bas
   (120 ms, sous l'intervalle de survol de 160-240 ms), une requête part pour presque chaque hex
   traversé → il y en a presque toujours une en vol → **la transition move → tir « redevient trop
   longue »**. C'est exactement ce qui s'est produit au commit `c339f01f`.

Aucune de ces couches ne corrige la précédente : elles s'empilent.

### 2.1 Le cache de paires ne sert pas la preview

`compute_unit_los` mémoïse chaque résultat dans `game_state["_unit_los_pair_cache"]`, clé
`(shooter_id, target_id)`, avec invalidation ciblée par `_touch_unit_los`
([shared_utils.py:1144](../../../engine/phase_handlers/shared_utils.py#L1144)). Ce cache est correct
et efficace **pour l'état réel**.

Mais la clé ne porte **pas la position**. Elle ne peut donc pas distinguer « LoS depuis la position
actuelle » de « LoS depuis l'hex survolé ». La preview travaille sur un clone : elle alimente le
pair-cache **du clone**, puis jette le clone.

Vérifié par mesure : après 12 appels à `preview_shoot_valid_targets_from_position`,
`len(game_state["_unit_los_pair_cache"]) == 0`. Le cache réel n'est jamais touché. Chaque hex
survolé repaie l'intégralité des LoS du tireur, et rien de ce travail ne réchauffe l'état réel pour
la transition qui suit immédiatement.

Un cache dédié existe, `_move_los_preview_cache`, keyé par destination
([shooting_handlers.py:1505](../../../engine/phase_handlers/shooting_handlers.py#L1505)) — c'est un
troisième cache, qui absorbe les re-survols mais jamais le premier passage sur un hex.

### 2.2 Deux chemins de calcul = risque de divergence

Le docstring de `preview_shoot_valid_targets_from_position`
([shooting_handlers.py:1473](../../../engine/phase_handlers/shooting_handlers.py#L1473)) documente
qu'une implémentation antérieure de la preview « pouvait marquer des cibles valides alors que le
pool moteur les exclut ». Ce bug n'existe que parce qu'il y a deux chemins pour répondre à la même
question. Le `deepcopy` est la rustine qui les fait converger : il fait tourner le vrai code sur un
faux monde.

## 3. Mesures (headless, moteur réel, `scenario_pvp_test.json`, 19 unités P1)

| Poste | Coût |
|---|---|
| `deepcopy(game_state)` (`config` / `weapon_damage_table` partagés par référence) | **83 ms** |
| `preview_shoot_valid_targets_from_position` complet | 153 – 227 ms |
| `preview_shoot_from_position` sur plateau chargé (commentaire du code, non re-mesuré) | 300 – 900 ms |
| commit du dernier `move` | 184 ms |
| `end_phase` (skips seuls, sans activation) | 59 ms |
| `advance_phase` → `shooting_phase_start` | 146 ms (264 ms si toutes les unités ont *advance*) |
| sérialisation de la réponse (534 Ko) | 4 ms |

Répartition interne de `shooting_phase_start` avec 19 unités *advanced* (cProfile, 264 ms total) :
201 ms dans `weapon_availability_check`, dont **176 ms dans `_compute_unit_los_uncached`**.

> **Note** : ces 176 ms sont des *misses légitimes*. Ce sont les paires des unités qui viennent de
> bouger, invalidées par `_touch_unit_los`. Elles sont ensuite réutilisées à l'activation, car
> `build_unit_los_cache` passe par `compute_unit_los`
> ([shooting_handlers.py:1345](../../../engine/phase_handlers/shooting_handlers.py#L1345)). Il n'y a
> **rien à gagner** en supprimant ce calcul : il n'est pas jeté. Ce qui est vidé à
> [shooting_handlers.py:1050](../../../engine/phase_handlers/shooting_handlers.py#L1050), c'est
> `game_state["los_cache"]` (ancien cache hex-keyé), pas le pair-cache.

Latence perçue à la transition = (preview éventuellement en vol) + move commit + `advance_phase`,
soit **0,4 s à 1,2 s**, dont la part dominante et la plus variable est la preview.

## 4. La solution

Faire de la position un **paramètre**, pas un état à simuler.

```python
# Aujourd'hui — la position est lue dans l'état ; pour la changer il faut copier l'état.
compute_unit_los(game_state, shooter, target)

# Cible — la position est une entrée ; preview et moteur appellent la même fonction.
compute_unit_los(shooter_footprint, target_footprint, walls, terrain)
```

Conséquences directes :

- **Plus de `deepcopy`** : la preview calcule l'empreinte du tireur à l'hex survolé et appelle la
  fonction. −83 ms par preview, et plus aucune mutation à protéger.
- **Plus de lock à tenir** : le calcul devient read-only sur des données immuables (murs, terrain) et
  des empreintes passées en argument. La transition move → tir n'attend plus rien.
- **Plus de débounce à régler finement** : il ne sert plus qu'à économiser du CPU, plus à protéger la
  latence du clic. Son réglage cesse d'être un arbitrage entre deux bugs.
- **Un seul chemin de calcul** : la divergence preview / moteur documentée en §2.2 devient
  structurellement impossible.
- **Un cache qui sert les deux** : la clé devient `(position_tireur, target_id)` au lieu de
  `(shooter_id, target_id)`. Le survol d'un hex réchauffe le cache pour le cas où l'unité s'y pose
  réellement — le travail de la preview cesse d'être jeté. Les trois caches actuels
  (`_unit_los_pair_cache`, `_move_los_preview_cache`, `unit["los_cache"]`) peuvent converger.

### Ce qu'il ne faut PAS faire

- **Sortir le calcul du lock en gardant le `deepcopy`** (snapshot sous lock, calcul hors lock).
  Ramènerait le blocage de ~900 ms à ~83 ms, mais c'est une couche de compensation de plus : le
  `deepcopy` reste, les trois caches restent, les deux chemins restent.
- **Supprimer le `deepcopy` par mutation/restauration de l'état réel** (muter la position, calculer,
  restaurer). Une exception en cours de preview laisserait l'état réel corrompu. C'est un workaround
  masquant une erreur : proscrit (CLAUDE.md).

## 5. Coût & risques

`compute_unit_los` est la source unique de vérité, appelée depuis le ciblage tir, l'observation RL,
le reward, le déploiement et la preview. Changer sa signature touche tous ces appelants. Ce n'est pas
un chantier d'une session.

Étapes proposées, chacune validable indépendamment :

1. Inventorier les appelants de `compute_unit_los` / `_compute_unit_los_uncached` et classer ceux qui
   disposent déjà d'une empreinte de ceux qui n'ont qu'un `unit`.
2. Introduire `compute_los_between_footprints(shooter_fp, target_fp, walls, terrain)` comme cœur pur,
   et réécrire `compute_unit_los(game_state, shooter, target)` comme un adaptateur mince qui résout
   les empreintes puis délègue. **Aucun appelant ne change à cette étape** ; les tests moteur de
   ciblage doivent rester verts.
3. Recléer le pair-cache sur `(shooter_footprint_key, target_id)`.
4. Réécrire `preview_shoot_valid_targets_from_position` sur le cœur pur : suppression du `deepcopy`.
5. Retirer `@with_engine_state_lock` des routes de preview, désormais read-only.
6. Supprimer `_move_los_preview_cache`, devenu redondant.

Prérequis avant de démarrer : suite de tests moteur verte sur le ciblage (le §2.2 montre que la
divergence preview / moteur est une régression déjà survenue).

## 6. Mitigation en place (temporaire)

`MOVE_PREVIEW_SHOOT_DEBOUNCE_MS` est ramené de 120 à **180 ms**
([BoardPvp.tsx:120](../../../frontend/src/components/BoardPvp.tsx#L120)). Au-dessus de l'intervalle
entre deux hex d'un survol normal (160-240 ms mesurés), la requête ne part que quand le curseur se
pose réellement : il n'y a donc quasiment jamais de preview en vol au moment du clic.

C'est un pansement, réversible en une ligne. Il réduit la **probabilité** de l'attente, pas son
amplitude. Il ne remplace pas le chantier décrit en §4.
