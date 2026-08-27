# Ligne de vue — caches LoS et point d'invalidation unique

> **Objet** : référence de conception des caches de Ligne de Vue (LoS) du moteur et de leur
> invalidation par **un point de passage unique** (`_touch_unit_los`), garantissant qu'aucune LoS
> périmée n'est jamais servie et rendant possible le réchauffage incrémental.
> **Source absorbée** : `LoS_unique_source_of_truth.md` (part dans `Documentation/Archives/docs/`
> avec un bandeau retour).
> L'état des chantiers fait foi dans [Documentation/Roadmap/](../../Roadmap/), jamais ici.

## 1. Contexte & problème

La LoS est la **source de vérité** partagée par : phase de tir (éligibilité + validation cible),
observation RL, reward, exposition au déploiement. Une LoS périmée = bug de type
« tir à travers un mur » ou « ne voit pas une cible visible ».

Caches LoS en présence (l'invalidation était **hétérogène** avant le refactor ; elle est désormais
centralisée — voir §4.1bis) :

| Cache | Clé | Invalidation | Portée |
|---|---|---|---|
| `_unit_los_pair_cache` | `(shooter_id, target_id)` | **Ciblée** par `_touch_unit_los` (dict pur persistant — D3 ; historiquement : jeté en entier à chaque bump de `_unit_move_version`) | LoS complète (`compute_unit_los`) — **le cache réellement utilisé** |
| `los_cache` (global) | `(shooter_id, target_id)` | Ciblée via `_invalidate_los_cache_for_moved_unit`, **et** vidé en entier dans `shooting_phase_start` ([shooting_handlers.py](../../../engine/phase_handlers/shooting_handlers.py)) | Mémo court terme |
| `unit["los_cache"]` | `target_id` | Par unité, versionnée `_los_cache_version` (construit par `build_unit_los_cache`, [shooting_handlers.py](../../../engine/phase_handlers/shooting_handlers.py)) | Construit à l'activation |
| `hex_los_cache` | `((c,r),(c,r))` | Ciblée par position | Géométrie footprint |
| `_hex_los_state_cache` | `((c,r),(c,r))` | **Jamais** (terrain statique) | Géométrie murs |

### Conséquences (constatées à l'audit, avant refactor)

1. **Incohérence d'invalidation** : le pair-cache (celui qui compte) était jeté **globalement**,
   alors qu'il existait déjà une infra d'invalidation **ciblée**
   (`_invalidate_los_cache_for_moved_unit`) pour les autres caches. Deux philosophies coexistaient.
2. **Coût de transition move→tir** : après un tour où les deux camps ont bougé, le versioning global
   avait tout jeté → au build du pool de tir, **toutes** les paires tireur→ennemi étaient recalculées
   à froid. Mesuré à l'audit : `los_clear_and_pool_s ≈ 1,5 s` (pool exact), contre `0,007 s` sans
   test LoS.
3. **Impossibilité de réchauffer** : réchauffer la LoS d'une unité juste après son déplacement était
   inutile tant que le déplacement **suivant** (`version++`) jetait tout le pair-cache.

## 2. Objectif

- **Une seule source de vérité** pour les positions (units_cache) et la LoS (`compute_unit_los`).
- **Une seule stratégie d'invalidation** : ciblée, déclenchée par **un unique choke-point** que
  traverse tout déplacement d'unité.
- Débloquer le **réchauffage incrémental** : après le move d'une unité, recalculer ses paires
  `(unité → ennemis)` pendant que le joueur enchaîne (temps mort) → transition move→tir quasi
  instantanée, même en pool exact.

## 3. Familles de mouvement à router (audit de couverture)

Tout chemin qui change une position d'unité doit passer par le choke-point. Inventaire — les
colonnes « Invalidation à l'audit » et « État » décrivent la situation **pré-refactor** qui a fondé
la conception ; les trous listés sont **corrigés** depuis (§5) :

| # | Famille | Point de passage | Invalidation à l'audit | État à l'audit |
|---|---|---|---|---|
| 1 | Move / Advance / Fall back | `translate_squad_to_destination` appelée depuis [movement_handlers.py](../../../engine/phase_handlers/movement_handlers.py) | Ciblée (los_cache) + version, posées à la main par le caller | ✅ |
| 2 | Move after shooting | Translate depuis [shooting_handlers.py](../../../engine/phase_handlers/shooting_handlers.py) | Ciblée + version, posées à la main | ✅ |
| 3 | Charge | `translate_squad_to_destination` depuis [charge_handlers.py](../../../engine/phase_handlers/charge_handlers.py) ; aussi `commit_move` type `"charge"` depuis [w40k_core.py](../../../engine/w40k_core.py) | **Pas** d'invalidation ciblée sur le translate (marquée OBSOLETE) → **version globale seule** | ⚠️ à rebrancher |
| 4 | Pile-in | À l'audit : translate `_fight_apply_pile_in_move` (symbole supprimé depuis — le pile-in passe aujourd'hui par `commit_move` type `"pile_in"`, voir `_fight_v11_auto_pile_in` dans [fight_handlers.py](../../../engine/phase_handlers/fight_handlers.py)) | Translate : ciblée **mais aucun `version++`** dans fight_handlers → pair-cache **jamais** invalidé sur ce chemin | ⚠️⚠️ **trou avéré** (chemin translate) |
| 5 | Consolidation | Même situation que le pile-in ; aujourd'hui `commit_move` type `"consolidation"` ([fight_handlers.py](../../../engine/phase_handlers/fight_handlers.py)) | Même trou que le pile-in (pas de `version++`) | ⚠️⚠️ **trou avéré** (chemin translate) |
| 6 | Reactive move | À l'audit : `update_units_cache_position` + `refresh_all_positional_caches_after_reactive_move` ([shared_utils.py](../../../engine/phase_handlers/shared_utils.py)) ; aujourd'hui `maybe_resolve_reactive_move` applique le déplacement via `translate_squad_to_destination` | Vidait `los_cache` global + tous `unit["los_cache"]` + `hex_los_cache` ciblé, **mais pas** `_unit_los_pair_cache` ; **aucun `version++`** | ⚠️⚠️ **trou avéré** (voir constat 1) |
| 7 | Deployment | À l'audit : `update_units_cache_position` ; aujourd'hui commit par-figurine `_apply_deploy_plan` ([deployment_handlers.py](../../../engine/phase_handlers/deployment_handlers.py)) → `place_model_at_effective_level` | — (l'exposure déploiement passe des dicts coordonnées-seules à `compute_unit_los`, qui **bypassent le pair-cache** — docstring de `compute_unit_los`) | ✅ risque réduit (bypass confirmé) |
| 8 | Ingress / Réserves stratégiques / Disembark | **Non implémenté** (confirmé : aucun writer de position hors handlers inventoriés ; hits « reserve/disembark » purement lexicaux) | — | ✅ clos (inexistant) |

**Points bas niveau communs** (traversés par plusieurs familles), tous dans
[shared_utils.py](../../../engine/phase_handlers/shared_utils.py) :
- `update_units_cache_position` — pose ancre/col/row.
- `translate_squad_to_destination` — translation rigide du squad (appelle `update_units_cache_position`).
- `update_model_position` — déplacement figurine (appelle `update_units_cache_position`).
- `commit_move` — plan-based ; à l'audit, il faisait lui-même `version++` + invalidation ciblée
  (aujourd'hui : batch D1 autour de ses écritures per-model).

> ⚠️ `update_units_cache_position` est aussi appelée par le **move-LoS-preview**
> ([shooting_handlers.py](../../../engine/phase_handlers/shooting_handlers.py)) en lecture
> seule : le choke-point doit distinguer un **commit** (invalide + réchauffe) d'un **preview**
> (ne touche à rien) — résolu par le constat 4 (le preview opère sur une deepcopy).

## 3bis. Audit exhaustif (résultats)

> Réalisé par recensement complet des appelants de `update_units_cache_position`,
> `translate_squad_to_destination`, `update_model_position`, `commit_move` et des
> `_unit_move_version += 1`. **Photographie pré-refactor** : elle justifie les décisions D1–D4 et le
> périmètre de l'étape 2. Vérification post-refactor : il ne reste que **deux**
> `_unit_move_version += 1` dans tout `engine/`, tous deux dans le choke-point
> (`_apply_los_invalidation` et `_los_end_batch`, [shared_utils.py](../../../engine/phase_handlers/shared_utils.py)).

### Constat structurel : deux mécanismes de commit coexistaient

Il n'existait **pas** de chemin unique. Deux implémentations de déplacement cohabitaient :

- **`commit_move` (plan-based)** [shared_utils.py](../../../engine/phase_handlers/shared_utils.py) —
  **modèle correct** : `update_model_position` par figurine → `_invalidate_los_cache_for_moved_unit`
  (ciblé) → `version++`.
- **`translate_squad_to_destination` (direct)** [shared_utils.py](../../../engine/phase_handlers/shared_utils.py)
  + `update_units_cache_position` — le **caller** reposait `version++`/invalidation à la main.

**Move**, **Charge** et **Pile-in** possédaient *chacun* les deux implémentations (translate direct
**et** `commit_move`), et `version++` était dupliqué sur **5 sites**. C'est précisément le désordre
que la source unique a supprimé.

### Tableau exhaustif des points d'écriture de position (état à l'audit)

| Site | Famille | `version++` | Invalidation ciblée | Pair-cache invalidé |
|---|---|---|---|---|
| [movement_handlers.py](../../../engine/phase_handlers/movement_handlers.py) (translate) | Move / Advance / Fall back | ✓ (caller) | ✓ (caller) | via version |
| [movement_handlers.py](../../../engine/phase_handlers/movement_handlers.py) (`commit_move`) | Move (plan) | ✓ | ✓ | via version |
| [shooting_handlers.py](../../../engine/phase_handlers/shooting_handlers.py) (translate) | Move after shooting | ✓ (caller) | ✓ (caller) | via version |
| [charge_handlers.py](../../../engine/phase_handlers/charge_handlers.py) (translate) | Charge (translate) | ✓ | **✗** (marquée OBSOLETE) | **version seule** |
| [charge_handlers.py](../../../engine/phase_handlers/charge_handlers.py) (`commit_move`) | Charge (plan) | ✓ **×2** (bump dans `commit_move` **puis** re-bump dans le handler charge — double incrément, symptôme de la dispersion) | ✓ | via version |
| [fight_handlers.py](../../../engine/phase_handlers/fight_handlers.py) (translate `_fight_apply_pile_in_move` — symbole supprimé depuis) | Pile-in **et Consolidation** (translate) — pile-in auto IA et consolidation | **✗** (aucun `_unit_move_version += 1` dans tout fight_handlers) | ✓ | **NON** ⚠️⚠️ |
| [fight_handlers.py](../../../engine/phase_handlers/fight_handlers.py) (`commit_move`) | Pile-in / Consolidation (plan) | ✓ | ✓ | via version |
| [shared_utils.py](../../../engine/phase_handlers/shared_utils.py) (`update_units_cache_position`) | **Reactive move** | **✗** | **✗** (vidait `los_cache` global + tous `unit["los_cache"]`, pas le pair-cache) | **NON** ⚠️⚠️ |
| [deployment_handlers.py](../../../engine/phase_handlers/deployment_handlers.py) | Deployment | ✗ | ✗ | non (avant la phase de tir) |
| [shooting_handlers.py](../../../engine/phase_handlers/shooting_handlers.py) (`update_units_cache_position`) | **Move-LoS-preview** | ✗ | ✗ | Sans objet : `gs` est une **deepcopy** (`_preview_share_memo`) — voir constat 4 |
| [shared_utils.py](../../../engine/phase_handlers/shared_utils.py) (`destroy_model`) | Destruction figurine | ✗ | ✗ | non (voir constats) |

### Constats critiques

1. **Reactive move — le vrai piège (⚠️ risque n°1), et le trou existait DÉJÀ.** Il déplaçait une
   unité sans `version++` **ni** invalidation du pair-cache. Il est déclenché **après** le mouvement
   principal ([movement_handlers.py](../../../engine/phase_handlers/movement_handlers.py),
   [shooting_handlers.py](../../../engine/phase_handlers/shooting_handlers.py)).
   **« Correct par accident » était faux dans le flux move_after_shooting** — l'ordre réel était :
   invalidation → `version++` → `build_unit_los_cache` → `maybe_resolve_reactive_move`. Or
   `build_unit_los_cache` appelle `compute_unit_los` pour chaque ennemi et **repeuplait le
   pair-cache avec les positions PRÉ-reactive**, à la version courante. Le reactive ne bumpant pas,
   ces paires restaient **périmées** jusqu'au prochain `version++`. En phase de move (pas de build
   entre le bump et le reactive), c'était correct par accident. Avec l'invalidation ciblée, le trou
   se généralisait : **le reactive DEVAIT invalider ses propres paires explicitement** — c'est le
   cas aujourd'hui, son application passe par `translate_squad_to_destination` →
   `_touch_unit_los`.
   Piège secondaire : `refresh_all_positional_caches_after_reactive_move` fait
   `unit["los_cache"] = {}` **sans** reset de `_los_cache_version` → le skip-rebuild de
   `build_unit_los_cache` (version identique **et** clé présente) gelait un los_cache **vide** pour
   toute unité déjà buildée à cette version. Neutralisé depuis : le passage du reactive par le
   choke-point bumpe la version, ce qui ré-arme le rebuild.

2. **Charge-translate** [charge_handlers.py](../../../engine/phase_handlers/charge_handlers.py) :
   `version++` présent mais invalidation ciblée marquée OBSOLETE → reposait sur le versioning
   global → **aurait cassé en ciblé** si non rebranché.

3. **Deployment** : ni `version++` ni invalidation. Sans conséquence pour la LoS de **tir**
   (antérieur à la phase). Risque réduit pour l'exposure : les dicts coordonnées-seules du
   déploiement **bypassent le pair-cache** (docstring de `compute_unit_los`,
   [shooting_handlers.py](../../../engine/phase_handlers/shooting_handlers.py) : « Coordinate-only
   dicts (e.g. deployment exposure) have no id and bypass the cache »).

4. **Move-LoS-preview** [shooting_handlers.py](../../../engine/phase_handlers/shooting_handlers.py) :
   **CLOS — `gs` EST une copie.** `gs = copy.deepcopy(game_state, _preview_share_memo)` ; seuls
   `config` et `weapon_damage_table` (lecture seule) sont partagés par référence. Le preview est
   donc sûr par construction ; exclure le preview de l'invalidation ne servirait qu'à éviter un
   **réchauffage inutile** (coût) dans la copie, pas la correction.

4bis. **Pile-in / Consolidation translate — trou avéré (manqué au premier audit).**
   Le translate fight (`_fight_apply_pile_in_move` à l'époque — symbole supprimé depuis,
   [fight_handlers.py](../../../engine/phase_handlers/fight_handlers.py)) faisait l'invalidation
   ciblée mais **aucun `version++`** — fight_handlers ne contenait **aucun**
   `_unit_move_version += 1`. Le pair-cache n'était donc **jamais** invalidé sur ce chemin (pile-in
   auto IA, consolidation). Fight étant la dernière phase du tour, les paires restaient périmées
   pour **l'observation/reward RL** jusqu'au premier move du tour suivant. Pire que
   charge-translate (qui bumpait au moins la version globale).

5. **`destroy_model`** [shared_utils.py](../../../engine/phase_handlers/shared_utils.py) : la mort
   d'une figurine réduit le footprint de son unité → les paires **où cette unité est tireur/cible**
   changent. Les unités ne bloquent **pas** la LoS d'autrui (seul le terrain le fait) → les paires
   *entre tierces unités* restent valides. Impact réel faible (visibilité binaire `can_see`), mais
   **les paires de l'unité amputée doivent être invalidées** ; c'est le cas aujourd'hui
   (`destroy_model` appelle `_touch_unit_los`).

### Conclusion de l'audit

Le **versioning global masquait quatre trous** : **deux étaient déjà actifs** (reactive dans le
flux move_after_shooting, **fight-translate pile-in/consolidation**) et deux étaient « corrects par
accident » (charge-translate, reactive en phase move) parce que *tout* était jeté au mouvement
suivant. **Passer à l'invalidation ciblée sans les traiter = régression directe** (LoS périmée).
Le refactor (étape 2 du plan) devait donc obligatoirement :

- router **reactive** + **charge-translate** + **fight-translate (pile-in/consolidation)** +
  **destroy_model** par le choke-point (invalidation ciblée explicite de leurs paires) ;
- **exclure** le move-LoS-preview (copie confirmée, exclusion = perf seulement) ;
- unifier les deux mécanismes (translate direct vs `commit_move`) pour Move / Charge / Pile-in /
  Consolidation, afin qu'il ne reste qu'**un** point de commit par famille ;
- supprimer le **double bump** du charge-plan.

Questions ouvertes : **toutes closes**. `gs` du preview = **deepcopy confirmée**
(`_preview_share_memo`) ; **Ingress / réserves stratégiques / disembark : non implémenté** (aucun
writer de position hors des handlers inventoriés).

## 4. Architecture cible

### 4.1 Le choke-point unique

Options examinées :

- **(a) Bas niveau — `update_units_cache_position`** : point profond traversé par la plupart des
  chemins. Y centraliser `version++` + invalidation ciblée du pair-cache + hook de réchauffage.
  **⚠️ FAILLE (constatée dans le code) : cette fonction ne bouge que l'ANCRE.**
  `update_model_position` ne la propage *« que si la figurine est l'ancre courante »*
  ([shared_utils.py](../../../engine/phase_handlers/shared_utils.py)). Un plan `commit_move` qui
  déplace des figurines **sans déplacer l'ancre** (cas typique du pile-in par-figurine) ne traverse
  **jamais** ce choke-point, alors que le footprint — donc la LoS — a changé. Même problème pour
  `destroy_model` (n'y passe que si l'ancre est recalculée, alors que le footprint change à
  **chaque** mort). La LoS dépend des **footprints par-figurine**, pas de l'ancre : (a) telle
  quelle est **insuffisante**.
- **(a′) Bas niveau corrigé — écriture per-model** : le vrai point bas commun est le couple
  `update_model_position` **+** `update_units_cache_position` (toute écriture de position dans
  models_cache/units_cache déclenche l'invalidation, dédupliquée par unité au sein d'un commit).
- **(b) Plan-based — `commit_move`** : forcer tous les chemins directs (reactive,
  move_after_shooting, charge-translate, fight-translate) à y passer. Plus gros refactor, plus de
  chemins à réécrire — mais couvre nativement le per-figurine.

**Décision : (a′) — point bas per-model.** Tranché sur la base du code :

- Il n'existe que **deux** écrivains de position : `update_model_position`
  [shared_utils.py](../../../engine/phase_handlers/shared_utils.py) (par figurine — recalcule
  **déjà** le footprint complet à chaque appel via `_recompute_squad_occupied_hexes`, même hors
  ancre) et `update_units_cache_position` (pose l'ancre). **Tout** chemin traverse l'un des deux :
  plans/par-figurine (`commit_move` → `update_model_position` en boucle), translate rigide
  (→ `update_units_cache_position`), reactive/move_after_shooting/deployment.
- (a′) accroche l'invalidation dans ces **deux** points → couvre nativement le pile-in
  par-figurine, **zéro chemin à réécrire**, surface = 2 fonctions.
- (b) est rejeté : reactive et move_after_shooting **n'ont pas de plan** → il faudrait en
  synthétiser et réécrire 4 sites ; et `destroy_model` (une mort change le footprint) **n'est pas
  un « move »** → (b) ne le couvre pas non plus.
- **Coût de (a′)** : 3 cas locaux — (i) **dédup** : `commit_move` encadrait déjà ses N écritures
  figurine par **un seul** invalidate+bump → neutraliser le hook bas niveau pendant qu'un batch
  commit est ouvert (flag garde), sinon N bumps par plan ; (ii) **preview** : sans enjeu de
  correction (deepcopy prouvée, constat 4) ; (iii) **destroy_model** : appel d'invalidation
  explicite requis **quelle que soit** l'option (coût égal).

### 4.1bis Décisions de conception figées (D1–D4)

> Cité par le code : bandeau du choke-point dans
> [shared_utils.py](../../../engine/phase_handlers/shared_utils.py)
> (« LoS invalidation choke-point (a′) — §4.1bis (D1–D4) »).

**Fil conducteur** : un unique helper `_touch_unit_los(game_state, unit_id)` porte **toute** la
logique (invalidation ciblée du pair-cache + `version++` + batch + futur warm). Les deux points bas
(`update_model_position`, `update_units_cache_position`) ne font **que l'appeler**. Tout le reste
du refactor = suppression des `version++`/invalidations dispersés.

**D1 — Batch-guard : dirty-map dans `game_state`.**
`_touch_unit_los` : si un batch est ouvert (`game_state.get("_los_batch") is not None`) →
**accumule** l'unité dans la map `{unit_id: (old_col, old_row)}` (première position d'origine
conservée), rien d'autre ; sinon → invalidation ciblée + `version++` **immédiats**
(`_apply_los_invalidation`). `commit_move`
[shared_utils.py](../../../engine/phase_handlers/shared_utils.py) ouvre le batch
(`_los_begin_batch`) avant sa boucle `update_model_position`, le ferme après (`_los_end_batch`) →
**1 seule** invalidation par unité + **1 seul** `version++` pour tout le plan. Les chemins
translate (1 seul appel `update_units_cache_position`) n'ouvrent pas de batch → touch immédiat
unique. La déduplication par clé rend inoffensif le double-touch (`update_model_position` rappelle
`update_units_cache_position` quand l'ancre bouge). Pas de compteur de profondeur : le batch est
réentrant via le booléen `owned` retourné par `_los_begin_batch` (seul l'ouvreur externe committe).

**D2 — `commit: bool` : NON introduit en étape 2.**
Le move-LoS-preview [shooting_handlers.py](../../../engine/phase_handlers/shooting_handlers.py)
opère sur une **deepcopy** (constat 4) → invalider/bumper sur la copie est **sans effet** sur le
vrai `game_state`. Distinguer `commit` n'apporte **rien à la correction**. Le flag ne servirait
qu'à éviter le coût du **réchauffage** → repoussé en étape 4, renommé `warm=False`, uniquement pour
skip le recompute. **Conséquence : zéro changement de signature en étape 2, aucun appelant à
toucher pour le flag.**

**D3 — Version vs pair-cache : découplage.**
`_unit_los_pair_cache` passe de `(ver, dict)` à un **dict pur** `{(s,t): result}`.
`_touch_unit_los` en supprime les entrées `(s,t)` où `s == unit_id` ou `t == unit_id`
(`_invalidate_pair_cache_for_unit`, même logique que `_invalidate_los_cache_for_moved_unit`
[shooting_handlers.py](../../../engine/phase_handlers/shooting_handlers.py), étendue au
pair-cache). Dans `compute_unit_los` : le bloc versionné `holder=(ver,{})` est retiré →
lecture/écriture directe dans le dict. Le `version++` **centralisé** (dans `_touch_unit_los`)
subsiste pour les **3 autres** consommateurs qui en dépendent réellement, **inchangés** :
`_target_pool_cache`, `_los_cache_version`, `enemy_pos_hash`
([shooting_handlers.py](../../../engine/phase_handlers/shooting_handlers.py)).

**D4 — Réchauffage : étape 4 séparée, flag off par défaut.**
Étapes 2-3 : pair-cache **lazy** (recalcul au prochain besoin) → correction complète sans
réchauffage. Étape 4 : recalcul `(U→ennemis)` post-commit derrière `warm` (off par défaut),
**synchrone d'abord** (simple) ; différé seulement si une mesure montre un allongement HTTP gênant.
Découple correction (obligatoire) et perf (optionnelle).

### 4.2 Invalidation ciblée du pair-cache

Concrétise **D3**. `_unit_los_pair_cache` devient **persistant** (dict pur, plus jeté sur
`version++`) ; seules les entrées `(s, t)` où `s == moved` ou `t == moved` sont supprimées, par
`_touch_unit_los` — en réutilisant la logique de `_invalidate_los_cache_for_moved_unit`
([shooting_handlers.py](../../../engine/phase_handlers/shooting_handlers.py), qui traite déjà
`los_cache`), étendue au pair-cache via `_invalidate_pair_cache_for_unit`.

### 4.3 Réchauffage incrémental (optionnel, activable — flag `warm`, off par défaut)

Après le commit d'un déplacement d'unité `U` (voir **D4**) :
- recalculer `compute_unit_los(U, ennemi)` pour chaque ennemi (ce qui repeuple le pair-cache) ;
- ne le faire que si `warm` est activé et hors preview ; synchrone d'abord, différé seulement si
  mesure montre un allongement HTTP gênant (le joueur sélectionne l'unité suivante → temps mort).

Résultat attendu : à `shooting_build_activation_pool`, toutes les paires sont chaudes →
`los_clear_and_pool_s` s'effondre même en pool exact.

## 5. Plan d'implémentation (étapes ordonnées)

1. **Audit de couverture** : ✅ **FAIT** (§3bis). Liste close. Résultat : 4 trous (reactive,
   charge-translate, **fight-translate pile-in/consolidation**, destroy_model), preview = deepcopy
   (hors sujet correction), ingress/réserves/disembark inexistant.
2. **Choke-point** : ✅ **FAIT** — (a′) per-model + D1–D4. Helper `_touch_unit_los`
   (+ `_apply_los_invalidation`, `_invalidate_pair_cache_for_unit`, `_los_begin_batch`/`_los_end_batch`)
   dans [shared_utils.py](../../../engine/phase_handlers/shared_utils.py), appelé en fin de
   `update_units_cache_position` **et** `update_model_position` ; batch-guard réentrant dans
   `commit_move` ; appel explicite dans `destroy_model`. `version++`/invalidations dispersés
   **supprimés** : movement (translate), shooting (move_after_shooting), fight-translate (**trou
   corrigé**), charge-translate + double bump charge-plan. `commit: bool` **non** introduit (D2).
3. **Pair-cache ciblé** : ✅ **FAIT** (D3) — `_unit_los_pair_cache` en **dict pur** persistant,
   invalidation ciblée dans `_touch_unit_los`, bloc versionné `holder=(ver,{})` retiré de
   `compute_unit_los`. `version++` centralisé conservé pour `_target_pool_cache` /
   `_los_cache_version` / `enemy_pos_hash`.
   → **Validé** par [tests/unit/engine/test_los_pair_cache_invariant.py](../../../tests/unit/engine/test_los_pair_cache_invariant.py) :
   opérations choke-point (translate / commit_move batch / `update_model_position` non-ancre /
   `destroy_model`) avec vérification exhaustive des paires après chacune (compte courant : lancer
   le test — le nombre de paires vérifiées est retourné par `assert_los_pair_cache_consistent`), +
   **contrôle de dents** vert (invalidation désactivée ⇒ péremption bien détectée).
4. **Réchauffage** : ⏳ **NON FAIT** (optionnel, D4) — brancher le recalcul `(U → ennemis)`
   post-commit derrière `warm` (off par défaut, hors preview). Non requis pour la correction.
5. **Bascule défaut** : ⏳ **NON FAIT** — envisager de repasser le pool de tir en **mode exact par
   défaut** (voir `shoot_pool_require_los_target`) une fois le réchauffage (étape 4) livré et
   mesuré.

## 6. Risques & garde-fous

> Cité par le code : docstring de `assert_los_pair_cache_consistent`
> ([shared_utils.py](../../../engine/phase_handlers/shared_utils.py)) — « Garde-fou debug (§6) ».

- **Risque n°1 — LoS périmée** : si un seul chemin de déplacement contourne le choke-point, le
  pair-cache ciblé garde une entrée fausse → « tir à travers un mur ». C'est **le** risque.
  Mitigation : `_touch_unit_los` accroché aux deux points bas (a′, D1) + audit §3bis exhaustif +
  assertion en mode debug comparant pair-cache ciblé vs recalcul direct
  (`assert_los_pair_cache_consistent`, ci-dessous).
- **Test de non-régression obligatoire.** Deux pièces :

  **(1) Invariant runtime réutilisable** — ✅ implémenté : `assert_los_pair_cache_consistent(game_state)`
  dans [shared_utils.py](../../../engine/phase_handlers/shared_utils.py). Itère
  `game_state["unit_by_id"]` (dicts porteurs d'`id`, ceux réellement passés à `compute_unit_los` en
  jeu — **pas** `units_cache` dont les entrées ont `id=None`), ignore les unités absentes du
  `units_cache` (mortes), et compare pour chaque paire inter-camps `compute_unit_los` (servi) vs
  `_compute_unit_los_uncached` (vérité). Lève `AssertionError` avec `(s,t, cached, fresh, version)`
  à la moindre divergence ; retourne le nombre de paires vérifiées.

  **(2) Scénario driver** — ✅ implémenté :
  [tests/unit/engine/test_los_pair_cache_invariant.py](../../../tests/unit/engine/test_los_pair_cache_invariant.py)
  (`test_pair_cache_consistent_across_chokepoint_operations`). Construit un vrai jeu (board
  44x60x5, murs, unités placées via le scénario pointé par la constante `SCENARIO` du test), puis
  exerce **directement** chaque fonction du choke-point sur unités réelles et ré-assère l'invariant
  après chacune :
  - `translate_squad_to_destination` (move / charge / fight-translate) — deltas locaux ;
  - `commit_move` batch (pile-in par-figurine) sur escouades multi-figurines ;
  - `update_model_position` sur figurine **non-ancre** (ancre fixe) ;
  - `destroy_model` (perte de figurine).

  Le pilotage direct des fonctions (plutôt que la boucle de tour) évite la dépendance à une
  politique IA adverse — le scénario PvP exige une allocation manuelle du défenseur, incompatible
  avec un jeu autonome.

  **Contrôle de dents** (crucial) : `test_pair_cache_staleness_is_detectable` désactive
  volontairement `_invalidate_pair_cache_for_unit` et vérifie que l'invariant **détecte** alors une
  valeur périmée servie — sinon un test vert ne prouverait rien.

  Lancement : `python3 -m pytest tests/unit/engine/test_los_pair_cache_invariant.py` (exit ≠ 0 si
  divergence **ou** si le contrôle de dents échoue).

  > Extension possible (non faite) : assertions comportementales « derrière le mur »
  > (`can_see False` → `True`) sur un scénario bot-vs-bot self-play, pour couvrir aussi une LoS
  > fausse *cohérente* et la boucle de tour complète (move_after_shooting, reactive, consolidation
  > en flux réel).
- **Preview** : le move-LoS-preview n'invalide/réchauffe jamais le vrai état — garanti par
  construction (deepcopy, constat 4).
- **Perf du réchauffage** : ne pas rallonger la réponse HTTP du déplacement ; si nécessaire,
  différer.

## 7. Mitigation en place côté pool de tir (contexte)

En attendant le réchauffage (étape 4), le pool de tir dispose d'un flag
`shoot_pool_require_los_target` (option menu « Pool tir : transition rapide », **défaut = rapide**,
lu via `game_state.get("shoot_pool_require_los_target", False)` dans
[shooting_handlers.py](../../../engine/phase_handlers/shooting_handlers.py)) :
- **rapide** (défaut) : le pool n'exige pas de LoS au build (cible résolue à l'activation) →
  transition mesurée à l'audit `≈ 0,08 s`.
- **exact** : test cible + LoS au build → `≈ 1,5 s` à l'audit (le coût que le réchauffage vise à
  amortir).

Le variant d'éligibilité `_unit_can_see_any` (early-exit, sans couvert) est déjà en place mais
n'apporte que ~7 % (mesure d'audit) : le goulot est le **volume de raycasting**, pas le couvert —
ce que seul le réchauffage incrémental peut réellement résoudre.

## 8. Références code

- Cache pair : `compute_unit_los` / `_unit_los_pair_cache`
  ([shooting_handlers.py](../../../engine/phase_handlers/shooting_handlers.py)).
- Choke-point : `_touch_unit_los`, `_apply_los_invalidation`, `_invalidate_pair_cache_for_unit`,
  `_los_begin_batch` / `_los_end_batch`, `assert_los_pair_cache_consistent`
  ([shared_utils.py](../../../engine/phase_handlers/shared_utils.py)).
- Invalidation ciblée des autres caches : `_invalidate_los_cache_for_moved_unit`
  ([shooting_handlers.py](../../../engine/phase_handlers/shooting_handlers.py)).
- Écrivains de position : `update_model_position`, `update_units_cache_position`,
  `translate_squad_to_destination`, `commit_move`, `destroy_model`
  ([shared_utils.py](../../../engine/phase_handlers/shared_utils.py)).
- Build pool tir : `shooting_build_activation_pool` / `_has_valid_shooting_targets`
  ([shooting_handlers.py](../../../engine/phase_handlers/shooting_handlers.py)).
- Transition instrumentée : lignes `SHOOT_PHASE_START` émises par `shooting_phase_start`
  ([shooting_handlers.py](../../../engine/phase_handlers/shooting_handlers.py)) dans
  perf_timing.log.
- Test d'invariant :
  [tests/unit/engine/test_los_pair_cache_invariant.py](../../../tests/unit/engine/test_los_pair_cache_invariant.py).

## Historique et sources

- Document issu de `LoS_unique_source_of_truth.md` (conception + audit exhaustif des écrivains de
  position, 2026) — renommage sans restructuration ; les mesures de performance citées
  (`los_clear_and_pool_s`, ~7 % de `_unit_can_see_any`) datent de cet audit.
- Les tableaux §3 et §3bis photographient l'état **pré-refactor** ; les étapes 1–3 du plan (§5)
  sont livrées, les étapes 4–5 (réchauffage, bascule du défaut) restent ouvertes — l'état des
  chantiers fait foi dans [Documentation/Roadmap/](../../Roadmap/).
- Symboles disparus depuis l'audit : `_fight_apply_pile_in_move` (le pile-in et la consolidation
  passent par `commit_move` types `"pile_in"` / `"consolidation"`) ; le commit de déploiement
  n'écrit plus l'ancre seule mais par-figurine (`_apply_deploy_plan` →
  `place_model_at_effective_level`).

## Correspondance des sources

| Source | Ancien § | Section actuelle |
|---|---|---|
| LoS_unique_source_of_truth.md | §1 Contexte & problème | §1 Contexte & problème |
| LoS_unique_source_of_truth.md | §2 Objectif | §2 Objectif |
| LoS_unique_source_of_truth.md | §3 Familles de mouvement à router | §3 Familles de mouvement à router |
| LoS_unique_source_of_truth.md | §3bis Audit exhaustif (résultats) | §3bis Audit exhaustif (résultats) |
| LoS_unique_source_of_truth.md | §4.1 Le choke-point unique | §4.1 Le choke-point unique |
| LoS_unique_source_of_truth.md | **§4.1bis Décisions de conception figées (D1–D4)** — cité par le bandeau du choke-point dans shared_utils.py | §4.1bis Décisions de conception figées (D1–D4) |
| LoS_unique_source_of_truth.md | §4.2 Invalidation ciblée du pair-cache | §4.2 Invalidation ciblée du pair-cache |
| LoS_unique_source_of_truth.md | §4.3 Réchauffage incrémental | §4.3 Réchauffage incrémental |
| LoS_unique_source_of_truth.md | §5 Plan d'implémentation | §5 Plan d'implémentation |
| LoS_unique_source_of_truth.md | **§6 Risques & garde-fous** — cité par la docstring de `assert_los_pair_cache_consistent` | §6 Risques & garde-fous |
| LoS_unique_source_of_truth.md | §7 État actuel du mitigation | §7 Mitigation en place côté pool de tir |
| LoS_unique_source_of_truth.md | §8 Références code | §8 Références code |
