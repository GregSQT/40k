# LoS & Positions — Source Unique de Vérité

> Doc d'implémentation. Objectif : unifier l'invalidation des caches de Ligne de Vue (LoS) et de
> position derrière **un seul point de passage** pour tout déplacement d'unité, afin de garantir un
> comportement fiable (jamais de LoS périmée) **et** de rendre possible le réchauffage incrémental
> (calcul étalé pendant la phase de mouvement plutôt que concentré à la transition move→tir).

## 1. Contexte & problème

La LoS est la **source de vérité** partagée par : phase de tir (éligibilité + validation cible),
observation RL, reward, exposition au déploiement. Une LoS périmée = bug de type
« tir à travers un mur » ou « ne voit pas une cible visible ».

Aujourd'hui il existe **plusieurs caches LoS** avec des stratégies d'invalidation **hétérogènes** :

| Cache | Clé | Invalidation | Portée |
|---|---|---|---|
| `_unit_los_pair_cache` | `(shooter_id, target_id)` | **Versioning global** : jeté en entier dès que `_unit_move_version` change ([shooting_handlers.py:3906-3910](../../engine/phase_handlers/shooting_handlers.py#L3906)) | LoS complète (`compute_unit_los`) — **le cache réellement utilisé** |
| `los_cache` (global) | `(shooter_id, target_id)` | Ciblée via `_invalidate_los_cache_for_moved_unit`, **et** vidé en entier à `shooting_phase_start` ([shooting_handlers.py:1051](../../engine/phase_handlers/shooting_handlers.py#L1051)) | Mémo court terme |
| `unit["los_cache"]` | `target_id` | Par unité, versionnée `_los_cache_version` ([shooting_handlers.py:1285](../../engine/phase_handlers/shooting_handlers.py#L1285)) | Construit à l'activation |
| `hex_los_cache` | `((c,r),(c,r))` | Ciblée par position | Géométrie footprint |
| `_hex_los_state_cache` | `((c,r),(c,r))` | **Jamais** (terrain statique) | Géométrie murs |

### Conséquences

1. **Incohérence d'invalidation** : le pair-cache (celui qui compte) est jeté **globalement**, alors
   qu'il existe déjà une infra d'invalidation **ciblée** (`_invalidate_los_cache_for_moved_unit`) pour
   les autres caches. Deux philosophies coexistent.
2. **Coût de transition move→tir** : après un tour où les deux camps ont bougé, le versioning global a
   tout jeté → au build du pool de tir, **toutes** les paires tireur→ennemi sont recalculées à froid.
   Mesuré : `los_clear_and_pool_s ≈ 1,5 s` (pool exact), contre `0,007 s` sans test LoS.
3. **Impossibilité de réchauffer** : réchauffer la LoS d'une unité juste après son déplacement est
   inutile tant que le déplacement **suivant** (`version++`) jette tout le pair-cache.

## 2. Objectif

- **Une seule source de vérité** pour les positions (units_cache) et la LoS (`compute_unit_los`).
- **Une seule stratégie d'invalidation** : ciblée, déclenchée par **un unique choke-point** que
  traverse tout déplacement d'unité.
- Débloquer le **réchauffage incrémental** : après le move d'une unité, recalculer ses paires
  `(unité → ennemis)` pendant que le joueur enchaîne (temps mort) → transition move→tir quasi
  instantanée, même en pool exact.

## 3. Familles de mouvement à router (audit de couverture)

Tout chemin qui change une position d'unité doit passer par le choke-point. Inventaire :

| # | Famille | Point de passage | Invalidation actuelle | État |
|---|---|---|---|---|
| 1 | Move / Advance / Fall back | `translate_squad_to_destination` [movement_handlers.py:1068](../../engine/phase_handlers/movement_handlers.py#L1068) + `version++` @1104 + `_invalidate…` @1103 | Ciblée (los_cache) + version | ✅ |
| 2 | Move after shooting | [shooting_handlers.py:4580](../../engine/phase_handlers/shooting_handlers.py#L4580) + @4596/4597 | Ciblée + version | ✅ |
| 3 | Charge | `translate_squad` [charge_handlers.py:2771](../../engine/phase_handlers/charge_handlers.py#L2771) + `version++` @2805 ; aussi `commit_move("charge")` [w40k_core.py:4949](../../engine/w40k_core.py#L4949) | **Pas** d'invalidation ciblée (marquée OBSOLETE @2794) → **version globale seule** | ⚠️ à rebrancher |
| 4 | Pile-in | translate `_fight_apply_pile_in_move` [fight_handlers.py:883](../../engine/phase_handlers/fight_handlers.py#L883) + `_invalidate…` @941 ; `commit_move("pile_in")` @3912 | Translate : ciblée **mais AUCUN `version++`** (zéro bump dans tout fight_handlers) → pair-cache **jamais** invalidé sur ce chemin. Plan : via `commit_move` ✓ | ⚠️⚠️ **trou avéré** (chemin translate) |
| 5 | Consolidation | `commit_move("consolidation")` [fight_handlers.py:5005](../../engine/phase_handlers/fight_handlers.py#L5005) ; **aussi** translate `_fight_apply_pile_in_move` @1553/1650 | Plan : via `commit_move` ✓ ; translate : **même trou que le pile-in** (pas de `version++`) | ⚠️⚠️ **trou avéré** (chemin translate) |
| 6 | Reactive move | `update_units_cache_position` [shared_utils.py:2317](../../engine/phase_handlers/shared_utils.py#L2317) + `refresh_all_positional_caches_after_reactive_move` [:2027](../../engine/phase_handlers/shared_utils.py#L2027) | Vide `los_cache` global + tous `unit["los_cache"]` + `hex_los_cache` ciblé, **mais pas** `_unit_los_pair_cache` ; **aucun `version++`** dans ce chemin | ⚠️⚠️ **trou avéré** (voir constat 1) |
| 7 | Deployment | `update_units_cache_position` [deployment_handlers.py:699](../../engine/phase_handlers/deployment_handlers.py#L699) | — (l'exposure déploiement passe des dicts coordonnées-seules à `compute_unit_los`, qui **bypassent le pair-cache** — docstring @3900) | ✅ risque réduit (bypass confirmé) |
| 8 | Ingress / Réserves stratégiques / Disembark | **Non implémenté** (confirmé : aucun writer de position hors handlers inventoriés ; hits « reserve/disembark » purement lexicaux) | — | ✅ clos (inexistant) |

**Points bas niveau communs** (traversés par plusieurs familles) :
- [`update_units_cache_position`](../../engine/phase_handlers/shared_utils.py#L1027) — pose ancre/col/row.
- [`translate_squad_to_destination`](../../engine/phase_handlers/shared_utils.py#L2720) — translation rigide du squad (appelle `update_units_cache_position`).
- [`update_model_position`](../../engine/phase_handlers/shared_utils.py#L2791) — déplacement figurine (appelle `update_units_cache_position`).
- [`commit_move`](../../engine/phase_handlers/shared_utils.py#L3780) — plan-based : fait déjà `version++` @3826 + `_invalidate…` @3823.

> ⚠️ `update_units_cache_position` est aussi appelé par le **move-LoS-preview**
> ([shooting_handlers.py:1556](../../engine/phase_handlers/shooting_handlers.py#L1556)) en lecture
> seule : le choke-point doit distinguer un **commit** (invalide + réchauffe) d'un **preview**
> (ne touche à rien).

## 3bis. Audit exhaustif (résultats)

> Réalisé par recensement complet des appelants de `update_units_cache_position`,
> `translate_squad_to_destination`, `update_model_position`, `commit_move` et des `_unit_move_version += 1`.

### Constat structurel : deux mécanismes de commit coexistent

Il n'existe **pas** de chemin unique. Deux implémentations de déplacement cohabitent :

- **`commit_move` (plan-based)** [shared_utils.py:3780](../../engine/phase_handlers/shared_utils.py#L3780) —
  **modèle correct** : `update_model_position` par figurine → `_invalidate_los_cache_for_moved_unit`
  (ciblé, @3823) → `version++` (@3826).
- **`translate_squad_to_destination` (direct)** [shared_utils.py:2720](../../engine/phase_handlers/shared_utils.py#L2720)
  + `update_units_cache_position` — le **caller** repose `version++`/invalidation à la main.

**Move**, **Charge** et **Pile-in** possèdent *chacun* les deux implémentations (translate direct **et**
`commit_move`), et `version++` est dupliqué sur **5 sites**. C'est précisément le désordre que la source
unique doit supprimer.

### Tableau exhaustif des points d'écriture de position

| Site | Famille | `version++` | Invalidation ciblée | Pair-cache invalidé |
|---|---|---|---|---|
| [movement_handlers.py:1068](../../engine/phase_handlers/movement_handlers.py#L1068) (translate) + 1103/1104 | Move / Advance / Fall back | ✓ @1104 | ✓ @1103 | via version |
| [movement_handlers.py:2965](../../engine/phase_handlers/movement_handlers.py#L2965) (`commit_move`) | Move (plan) | ✓ | ✓ | via version |
| [shooting_handlers.py:4580](../../engine/phase_handlers/shooting_handlers.py#L4580) + 4596/4597 | Move after shooting | ✓ @4597 | ✓ @4596 | via version |
| [charge_handlers.py:2771](../../engine/phase_handlers/charge_handlers.py#L2771) (translate) + 2805 | Charge (translate) | ✓ @2805 | **✗** (OBSOLETE @2794) | **version seule** |
| [charge_handlers.py:5086](../../engine/phase_handlers/charge_handlers.py#L5086) (`commit_move`) + 5094 | Charge (plan) | ✓ **×2** (bump dans `commit_move` @3826 **puis** re-bump @5094 — double incrément, symptôme de la dispersion) | ✓ | via version |
| [fight_handlers.py:883](../../engine/phase_handlers/fight_handlers.py#L883) (`_fight_apply_pile_in_move`, translate) + 941 | Pile-in **et Consolidation** (translate) — appelé @3442/3459 (pile-in auto IA) et @1553/1650 (consolidation) | **✗** (aucun `_unit_move_version += 1` dans tout fight_handlers) | ✓ @941 | **NON** ⚠️⚠️ |
| [fight_handlers.py:3912](../../engine/phase_handlers/fight_handlers.py#L3912) / [5001](../../engine/phase_handlers/fight_handlers.py#L5005) (`commit_move`) | Pile-in / Consolidation (plan) | ✓ | ✓ | via version |
| [shared_utils.py:2317](../../engine/phase_handlers/shared_utils.py#L2317) (`update_units_cache_position`) | **Reactive move** | **✗** | **✗** (vide `los_cache` global + tous `unit["los_cache"]`, pas le pair-cache) | **NON** ⚠️⚠️ |
| [deployment_handlers.py:699](../../engine/phase_handlers/deployment_handlers.py#L699) / [550](../../engine/phase_handlers/deployment_handlers.py#L550) | Deployment | ✗ | ✗ | non (avant la phase de tir) |
| [shooting_handlers.py:1556](../../engine/phase_handlers/shooting_handlers.py#L1556) (`update_units_cache_position`) | **Move-LoS-preview** | ✗ | ✗ | Sans objet : `gs` est une **deepcopy** (@1530-1537) — voir constat 4 |
| [shared_utils.py:2852](../../engine/phase_handlers/shared_utils.py#L2852) (`destroy_model`) | Destruction figurine | ✗ | ✗ | non (voir §constats) |

### Constats critiques

1. **Reactive move — le vrai piège (⚠️ risque n°1), et le trou existe DÉJÀ.** Il déplace une unité sans
   `version++` **ni** invalidation du pair-cache. Il est déclenché **après** le mouvement principal
   ([movement_handlers.py:3371](../../engine/phase_handlers/movement_handlers.py#L3371),
   [shooting_handlers.py:4600](../../engine/phase_handlers/shooting_handlers.py#L4600)).
   **« Correct par accident » est faux dans le flux move_after_shooting** — l'ordre réel est :
   `_invalidate` @4596 → `version++` @4597 → `build_unit_los_cache` @4598 → `maybe_resolve_reactive_move`
   @4600. Or `build_unit_los_cache` appelle `compute_unit_los` pour chaque ennemi et **repeuple le
   pair-cache avec les positions PRÉ-reactive**, à la version courante. Le reactive ne bumpant pas, ces
   paires restent **périmées dès aujourd'hui** jusqu'au prochain `version++`. En phase de move (pas de
   build entre le bump et le reactive), c'est correct par accident. Avec l'invalidation ciblée, le trou
   se généralise : **le reactive DEVRA invalider ses propres paires explicitement.**
   Piège secondaire : `refresh_all_positional_caches_after_reactive_move` fait `unit["los_cache"] = {}`
   **sans** reset de `_los_cache_version` → le skip-rebuild de `build_unit_los_cache` (@1285-1292 :
   version identique **et** clé présente) gèle un los_cache **vide** pour toute unité déjà buildée à
   cette version (bénin pour le mover qui a déjà tiré, mais fragile — à corriger au passage).

2. **Charge-translate** [charge_handlers.py:2771](../../engine/phase_handlers/charge_handlers.py#L2771) :
   `version++` présent mais invalidation ciblée marquée OBSOLETE → repose sur le versioning global →
   **cassera en ciblé** si non rebranché.

3. **Deployment** : ni `version++` ni invalidation. Sans conséquence pour la LoS de **tir** (antérieur à
   la phase). Risque réduit pour l'exposure : les dicts coordonnées-seules du déploiement **bypassent le
   pair-cache** (docstring `compute_unit_los` @3900-3901 : « Coordinate-only dicts (e.g. deployment
   exposure) have no id and bypass the cache »).

4. **Move-LoS-preview** [shooting_handlers.py:1556](../../engine/phase_handlers/shooting_handlers.py#L1556) :
   **CLOS — `gs` EST une copie.** `gs = copy.deepcopy(game_state, _preview_share_memo)` (@1530-1537) ;
   seuls `config` et `weapon_damage_table` (lecture seule) sont partagés par référence. Le preview est
   donc sûr par construction ; `commit=False` ne sert qu'à éviter un **réchauffage inutile** (coût) dans
   la copie, pas la correction.

4bis. **Pile-in / Consolidation translate — trou avéré (manqué au premier audit).**
   `_fight_apply_pile_in_move` [fight_handlers.py:883](../../engine/phase_handlers/fight_handlers.py#L883)
   fait l'invalidation ciblée (@941) mais **aucun `version++`** — fight_handlers ne contient **aucun**
   `_unit_move_version += 1`. Le pair-cache n'est donc **jamais** invalidé sur ce chemin (pile-in auto IA
   @3442/3459, consolidation @1553/1650). Fight étant la dernière phase du tour, les paires restent
   périmées pour **l'observation/reward RL** jusqu'au premier move du tour suivant. Pire que
   charge-translate (qui bumpe au moins la version globale).

5. **`destroy_model`** [shared_utils.py:2852](../../engine/phase_handlers/shared_utils.py#L2852) : la mort
   d'une figurine réduit le footprint de son unité → les paires **où cette unité est tireur/cible** changent.
   Les unités ne bloquent **pas** la LoS d'autrui (seul le terrain le fait) → les paires *entre tierces
   unités* restent valides. Impact réel faible (visibilité binaire `can_see`), mais **les paires de l'unité
   amputée devraient être invalidées** ; ce n'est pas le cas aujourd'hui (non bumpé).

### Conclusion de l'audit

Le **versioning global masque quatre trous** : **deux sont déjà actifs aujourd'hui** (reactive dans le
flux move_after_shooting, **fight-translate pile-in/consolidation**) et deux sont « corrects par
accident » (charge-translate, reactive en phase move) parce que *tout* est jeté au mouvement suivant.
**Passer à l'invalidation ciblée sans les traiter = régression directe** (LoS périmée). Le refactor
(étape 2 du plan) **doit donc obligatoirement** :

- router **reactive** + **charge-translate** + **fight-translate (pile-in/consolidation)** +
  **destroy_model** par le choke-point (invalidation ciblée explicite de leurs paires) ;
- **exclure** le move-LoS-preview (`commit=False` — copie confirmée, exclusion = perf seulement) ;
- unifier les deux mécanismes (translate direct vs `commit_move`) pour Move / Charge / Pile-in /
  Consolidation, afin qu'il ne reste qu'**un** point de commit par famille ;
- supprimer le **double bump** du charge-plan (`commit_move` @3826 **puis** @5094).

Questions ouvertes : **toutes closes**. `gs` du preview = **deepcopy confirmée** (@1530-1537) ;
**Ingress / réserves stratégiques / disembark : non implémenté** (aucun writer de position hors des
handlers inventoriés).

## 4. Architecture cible

### 4.1 Le choke-point unique

Deux options :

- **(a) Bas niveau — `update_units_cache_position`** : point profond traversé par la plupart des
  chemins. Y centraliser `version++` + invalidation ciblée du pair-cache + hook de réchauffage, avec un
  paramètre `commit: bool` (True = vrai déplacement, False = preview).
  **⚠️ FAILLE (constatée dans le code) : cette fonction ne bouge que l'ANCRE.** `update_model_position`
  ne la propage *« que si la figurine est l'ancre courante »* ([shared_utils.py:2797](../../engine/phase_handlers/shared_utils.py#L2797)).
  Un plan `commit_move` qui déplace des figurines **sans déplacer l'ancre** (cas typique du pile-in
  par-figurine) ne traverse **jamais** ce choke-point, alors que le footprint — donc la LoS — a changé.
  Même problème pour `destroy_model` (n'y passe que si l'ancre est recalculée, alors que le footprint
  change à **chaque** mort). La LoS dépend des **footprints par-figurine**, pas de l'ancre : (a) telle
  quelle est **insuffisante**.
- **(a′) Bas niveau corrigé — écriture per-model** : le vrai point bas commun est le couple
  `update_model_position` **+** `update_units_cache_position` (toute écriture de position dans
  models_cache/units_cache déclenche l'invalidation, dédupliquée par unité au sein d'un commit).
- **(b) Plan-based — `commit_move`** : forcer tous les chemins directs (reactive, move_after_shooting,
  charge-translate, fight-translate) à y passer. Plus gros refactor, plus de chemins à réécrire — mais
  couvre nativement le per-figurine.

**Décision : (a′) — point bas per-model.** Tranché sur la base du code :

- Il n'existe que **deux** écrivains de position : `update_model_position` [shared_utils.py:2791](../../engine/phase_handlers/shared_utils.py#L2791)
  (par figurine — recalcule **déjà** le footprint complet à chaque appel, `_recompute_squad_occupied_hexes` @2815,
  même hors ancre) et `update_units_cache_position` [shared_utils.py:1027](../../engine/phase_handlers/shared_utils.py#L1027)
  (pose l'ancre). **Tout** chemin traverse l'un des deux : plans/par-figurine (`commit_move` → `update_model_position`
  en boucle @3810), translate rigide (→ `update_units_cache_position` @2755), reactive/move_after_shooting/deployment
  (→ `update_units_cache_position` direct).
- (a′) accroche l'invalidation dans ces **deux** points → couvre nativement le pile-in par-figurine, **zéro chemin à
  réécrire**, surface = 2 fonctions.
- (b) est rejeté : reactive et move_after_shooting **n'ont pas de plan** → il faudrait en synthétiser et réécrire
  4 sites ; et `destroy_model` (une mort change le footprint) **n'est pas un « move »** → (b) ne le couvre pas non plus.
- **Coût de (a′)** : 3 cas locaux — (i) **dédup** : `commit_move` encadre déjà ses N écritures figurine par **un seul**
  invalidate+bump (@3823-3826) → neutraliser le hook bas niveau pendant qu'un batch commit est ouvert (flag garde),
  sinon N bumps par plan ; (ii) **preview** : passer `commit=False` à l'appel @1556 (perf seule — deepcopy prouvée,
  constat 4) ; (iii) **destroy_model** : appel d'invalidation explicite requis **quelle que soit** l'option (coût égal).

### 4.2 Invalidation ciblée du pair-cache

Rendre `_unit_los_pair_cache` **persistant** (ne plus le jeter sur `version++`) et supprimer
seulement les entrées `(s, t)` où `s == moved` ou `t == moved`, dans le choke-point — exactement
comme le fait déjà [`_invalidate_los_cache_for_moved_unit`](../../engine/phase_handlers/shooting_handlers.py#L1870)
pour `los_cache`. Étendre cette fonction (ou le choke-point) au pair-cache.

### 4.3 Réchauffage incrémental (optionnel, activable)

Après le commit d'un déplacement d'unité `U` :
- recalculer `compute_unit_los(U, ennemi)` pour chaque ennemi (ce qui repeuple le pair-cache) ;
- ne le faire que hors preview, et idéalement en tâche différée pour ne pas rallonger la réponse
  HTTP du déplacement (mais le joueur est en train de sélectionner l'unité suivante → temps mort).

Résultat attendu : à `shooting_build_activation_pool`, toutes les paires sont chaudes →
`los_clear_and_pool_s` s'effondre même en pool exact.

## 5. Plan d'implémentation (étapes ordonnées)

1. **Audit de couverture** : ✅ **FAIT** (§3bis). Liste close. Résultat : 4 trous (reactive,
   charge-translate, **fight-translate pile-in/consolidation**, destroy_model), preview = deepcopy
   (hors sujet correction), ingress/réserves/disembark inexistant.
2. **Choke-point** : ✅ **tranché = (a′) per-model** (§4.1). Accrocher invalidation + bump + hook de réchauffage
   dans `update_model_position` **et** `update_units_cache_position`, avec garde de batch (pas de N bumps par plan)
   et paramètre `commit: bool`. Router tous les points de §3/§3bis, ajouter l'appel explicite pour `destroy_model`,
   puis **supprimer** les `version++` / invalidations dispersés (dont le double bump charge-plan @3826/@5094) au
   profit du point unique.
3. **Pair-cache ciblé** : rendre `_unit_los_pair_cache` persistant + invalidation ciblée dans le
   choke-point. Retirer le jet-sur-version de `compute_unit_los`.
4. **Réchauffage** : brancher le recalcul `(U → ennemis)` post-commit (hors preview).
5. **Bascule défaut** : une fois validé, envisager de repasser le pool de tir en **mode exact par
   défaut** (voir `shoot_pool_require_los_target`), le coût de transition étant désormais amorti.

## 6. Risques & garde-fous

- **Risque n°1 — LoS périmée** : si un seul chemin de déplacement contourne le choke-point, le
  pair-cache ciblé garde une entrée fausse → « tir à travers un mur ». C'est **le** risque. Mitigation :
  option (a) au point le plus bas + audit §5.1 exhaustif + assertion optionnelle en mode debug
  comparant pair-cache ciblé vs recalcul direct.
- **Test de non-régression obligatoire — harness scripté** (le projet n'a pas de pytest : validation
  par script + `--step` + replay). Deux pièces :

  **(1) Invariant runtime réutilisable** — `assert_los_pair_cache_consistent(game_state)` dans
  `engine/phase_handlers/shared_utils.py` (ou un module `engine/debug/los_invariant.py`) :
  ```python
  def assert_los_pair_cache_consistent(game_state):
      """Compare pair-cache (cache) vs source de vérité recalculée. Zéro divergence tolérée."""
      from engine.phase_handlers.shooting_handlers import compute_unit_los, _compute_unit_los_uncached
      units = game_state["units_cache"]
      for s in units.values():
          for t in units.values():
              if s.get("id") is None or t.get("id") is None:  # coord-only dicts bypass le cache
                  continue
              if s["player"] == t["player"]:                   # seules les paires inter-camps comptent
                  continue
              cached = compute_unit_los(game_state, s, t)       # passe par _unit_los_pair_cache
              fresh  = _compute_unit_los_uncached(game_state, s, t)
              if cached != fresh:
                  raise AssertionError(
                      f"LoS pair-cache stale: ({s['id']}->{t['id']}) "
                      f"ver={game_state['_unit_move_version']} cached={cached} fresh={fresh}")
  ```
  Appelée en **mode debug uniquement** (flag `game_state.get('_debug_los_invariant')`) **après chaque
  écriture de position** post-refactor : fin de move, charge, reactive [movement_handlers.py:3371](../../engine/phase_handlers/movement_handlers.py#L3371),
  move_after_shooting [shooting_handlers.py:4600](../../engine/phase_handlers/shooting_handlers.py#L4600),
  pile-in/consolidation ([fight_handlers.py:3442](../../engine/phase_handlers/fight_handlers.py#L3442) /
  [1553](../../engine/phase_handlers/fight_handlers.py#L1553)), `destroy_model`
  [shared_utils.py:2852](../../engine/phase_handlers/shared_utils.py#L2852).

  **(2) Scénario driver** — `scripts/los_cache_invariant_test.py` :
  1. Construire un `W40KEngine` déterministe, **un mur entre deux unités ennemies** (terrain obscuring).
  2. Activer `game_state['_debug_los_invariant'] = True`.
  3. Exercer **chaque famille** dans un tour complet et appeler l'invariant après chacune :
     move standard, advance, fall back, charge (translate **et** plan), reactive, pile-in, consolidation,
     move_after_shooting, puis tuer une figurine non-ancre (`destroy_model`).
  4. **Assertions comportementales** en plus de l'invariant cache==recompute : après qu'un tireur finit
     **derrière le mur**, `compute_unit_los(gs, tireur, cible)['can_see'] is False` ; après qu'il en sort,
     `is True`. (L'invariant seul ne détecte qu'une incohérence cache ; ces assertions détectent une LoS
     fausse *cohérente*.)
  5. Sortie : `OK` + nb de paires vérifiées, ou `AssertionError` avec `(s,t, cached, fresh, version)`.
  Lancement : `python3 scripts/los_cache_invariant_test.py` (exit code ≠ 0 si divergence).
- **Preview** : garantir que le move-LoS-preview n'invalide/réchauffe jamais (paramètre `commit=False`).
- **Perf du réchauffage** : ne pas rallonger la réponse HTTP du déplacement ; si nécessaire, différer.

## 7. État actuel du mitigation (contexte)

En attendant ce refactor, le pool de tir dispose d'un flag `shoot_pool_require_los_target`
(option menu « Pool tir : transition rapide », **défaut = rapide**) :
- **rapide** (défaut) : le pool n'exige pas de LoS au build (cible résolue à l'activation) →
  transition `≈ 0,08 s`.
- **exact** : test cible + LoS au build → `≈ 1,5 s` (le coût que ce refactor vise à amortir).

Le variant d'éligibilité `_unit_can_see_any` (early-exit, sans couvert) est déjà en place mais
n'apporte que ~7 % : le goulot est le **volume de raycasting**, pas le couvert — ce que seul le
réchauffage incrémental (donc ce refactor) peut réellement résoudre.

## 8. Références code

- Cache pair : [`compute_unit_los`](../../engine/phase_handlers/shooting_handlers.py#L3880) / `_unit_los_pair_cache`.
- Invalidation ciblée existante : [`_invalidate_los_cache_for_moved_unit`](../../engine/phase_handlers/shooting_handlers.py#L1870).
- Choke-point candidat : [`update_units_cache_position`](../../engine/phase_handlers/shared_utils.py#L1027).
- Build pool tir : [`shooting_build_activation_pool`](../../engine/phase_handlers/shooting_handlers.py#L1924) / [`_has_valid_shooting_targets`](../../engine/phase_handlers/shooting_handlers.py#L2115).
- Transition instrumentée : `SHOOT_PHASE_START` dans [shooting_handlers.py](../../engine/phase_handlers/shooting_handlers.py#L1067) (perf_timing.log).
