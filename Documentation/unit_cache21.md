# Unité cache unique (units_cache) — Prompt et plan d’implémentation

Document fusionné à partir de unit_cache2.md, enrichi avec les apports de unit_cache1.md et unit_cache3.md.

---

## 1. Prompt (objectif)

**Objectif :** Remplacer les deux caches `position_cache` et `last_unit_positions` par un seul cache dans `game_state` : **`units_cache`**.

**Spécification du nouveau cache :**
- **Clé :** `game_state["units_cache"]`
- **Type :** `Dict[str, Dict]` — dictionnaire `unit_id (str) → données unité`
- **Données par unité (vivante uniquement) :** `col`, `row`, `HP_CUR`, `player`
- **Rôle :** Unique source de vérité pour la position et les HP des unités vivantes. Toute lecture ou mise à jour de position / HP / statut vivant doit s’appuyer sur ce cache (ou sur une copie de snapshot documentée).

**Caches à supprimer / remplacer :**
1. **`position_cache`** — dans `game_state`, construit en phase shooting, contient uniquement les ennemis : `unit_id → { "id", "col", "row" }`. Utilisé pour LoS et pool de cibles.
2. **`last_unit_positions`** — présent à trois endroits : `engine/w40k_core.py` (env, mis à jour en fin de step), `engine/observation_builder.py` (instance, jamais mis à jour par l’env), `engine/reward_calculator.py` (instance, jamais mis à jour). Format : `unit_id → (col, row)`. Utilisé pour la feature `movement_direction` (obs) et la récompense associée.

**Contraintes :**
- Pas de fallback / valeur par défaut pour masquer une erreur ; utiliser `require_key` ou lever une erreur explicite si une clé attendue est absente.
- Conformité AI_TURN.md et règles du projet (coordonnées normalisées, pas de workaround).
- Les unités mortes ne doivent pas figurer dans `units_cache` (retrait à la mort).

---

## 2. Structure de données

### 2.1 `units_cache` (état courant)

```python
game_state["units_cache"]: Dict[str, Dict[str, Any]]
# unit_id (str) → {
#     "col": int,      # coordonnée normalisée
#     "row": int,       # coordonnée normalisée
#     "HP_CUR": int,    # > 0 pour toute entrée (vivant uniquement)
#     "player": int,    # 1 ou 2
# }
```

- Une entrée existe **uniquement** pour les unités vivantes (`HP_CUR > 0`).
- À chaque changement de position ou de HP (mouvement, tir, charge, combat, fuite, mort), le cache est mis à jour ou l’entrée est supprimée (mort).

### 2.2 Snapshot « étape précédente » pour obs / reward

Pour la feature **movement_direction** (observation) et la récompense basée sur le mouvement, il faut les **positions au début de l’étape** (avant l’action du step).

**Option A — `prev_col` / `prev_row` dans le même cache :**  
Étendre chaque entrée de `units_cache` avec `prev_col` et `prev_row`. En **fin** de step (après traitement de l’action, avant construction de l’observation/reward), pour chaque entrée : `entry["prev_col"], entry["prev_row"] = entry["col"], entry["row"]`. Ainsi un seul cache suffit ; « position précédente » = position au début du step actuel. Recommandé si on préfère éviter un second dictionnaire.

**Option B (recommandée pour ce plan) — Snapshot séparé `units_cache_prev` :**
- **Clé :** `game_state["units_cache_prev"]`
- **Type :** même structure que `units_cache` (snapshot au début du step).
- **Sémantique :** au **début** de chaque `step()` (avant traitement de l’action), copier `game_state["units_cache"]` dans `game_state["units_cache_prev"]`. En fin de step, `units_cache` est mis à jour (état après action). Ainsi observation et reward utilisent `units_cache_prev` pour « précédent » et `units_cache` pour « courant ».
- Le plan ci-dessous et le snippet en A.4 retiennent **Option B** pour cohérence. Option A reste possible si on préfère un seul cache.
- **Note :** Une copie en **fin** de step (état courant → `units_cache_prev` pour le step suivant) est équivalente si appliquée de façon cohérente.

---

## 3. Plan d’implémentation (ordre recommandé)

### Phase 0 — Prérequis et conventions

- **Clé d’unité :** toujours `str(unit["id"])` dans `units_cache`.
- **Coordonnées :** utiliser `normalize_coordinates(col, row)` (combat_utils) avant toute écriture dans le cache ; utiliser `get_unit_coordinates(unit)` pour lire depuis un dict unit, ou lire `units_cache[uid]["col"]`, `units_cache[uid]["row"]` déjà normalisés.
- **Cohérence :** à chaque modification de `unit["col"]` / `unit["row"]` ou `unit["HP_CUR"]` dans le moteur, mettre à jour (ou retirer) l’entrée correspondante dans `units_cache`.

---

### Phase A — Création et maintenance de `units_cache`

#### A.1 Module central de cache

- **Fichier à créer ou étendre :** par exemple `engine/phase_handlers/shared_utils.py` ou un module dédié `engine/unit_cache.py`.
- **Fonctions obligatoires :**
  - **`build_units_cache(game_state: Dict[str, Any]) -> None`**  
    Reconstruit `game_state["units_cache"]` à partir de `game_state["units"]` : pour chaque unité avec `HP_CUR > 0`, ajouter une entrée `unit_id → { "col", "row", "HP_CUR", "player" }`. Utiliser `get_unit_coordinates` / `normalize_coordinates` pour (col, row). Ne pas y mettre les unités mortes.
  - **`update_units_cache_unit(game_state: Dict[str, Any], unit_id: str, col: int, row: int, hp_cur: int, player: int) -> None`**  
    Met à jour ou insère une entrée pour `unit_id`. Si `hp_cur <= 0`, appeler plutôt `remove_from_units_cache`.
  - **`remove_from_units_cache(game_state: Dict[str, Any], unit_id: str) -> None`**  
    Supprime l’entrée `unit_id` de `game_state["units_cache"]` (unité morte).
- **Fonctions d’accès recommandées** (pour lecture cohérente et testabilité) :
  - **`get_unit_from_cache(unit_id: str, game_state: Dict[str, Any]) -> Optional[Dict[str, Any]]`** : retourne l’entrée cache pour `unit_id` ou `None` si absent (unité morte ou inconnue).
  - **`is_unit_alive(unit_id: str, game_state: Dict[str, Any]) -> bool`** : `unit_id in game_state.get("units_cache", {})`.
  - **`get_unit_position_from_cache(unit_id: str, game_state: Dict[str, Any]) -> Optional[Tuple[int, int]]`** : `(col, row)` si vivant, sinon `None`.
- **Fonctions de convenance optionnelles (API position / HP séparée)** : pour des call sites plus clairs après `set_unit_coordinates` ou après dégâts, sans changer le contrat principal (`update_units_cache_unit` reste la mise à jour complète) :
  - **`update_units_cache_position(game_state, unit_id, col, row) -> None`** : met à jour uniquement col/row de l’entrée (si présente) ; peut déléguer à `update_units_cache_unit` en reprenant hp_cur et player depuis l’entrée existante.
  - **`update_units_cache_hp(game_state, unit_id, new_hp_cur) -> None`** : met à jour HP_CUR ; si `new_hp_cur <= 0`, supprimer l’entrée du cache (équivalent à `remove_from_units_cache`). Utile après application de dégâts (tir, combat).
- **Règles :** pas de fallback ; si `game_state["units_cache"]` est absent alors qu’il doit exister, lever une erreur explicite (ou documenter les seuls moments où il est encore non initialisé, ex. avant la première construction).

#### A.2 Construction initiale — Décision unique (reset only)

**Décision (à appliquer partout) :**
- **Construire `units_cache` une seule fois au reset** (après chargement de `game_state["units"]`).
- **Ne pas reconstruire** en début de phase shooting ni en début de phase fight : le cache est tenu à jour **uniquement par mises à jour incrémentales** (position, HP, mort) à chaque action.
- En **shooting_phase_start** et **fight_phase_start** : ne plus appeler `build_position_cache` ; **vérifier** que `units_cache` existe (ex. `require_key(game_state, "units_cache")` ou `if "units_cache" not in game_state: raise KeyError(...)`). Si une phase peut être entamée sans reset (ex. reprise), appeler `build_units_cache(game_state)` une seule fois lorsque `units_cache` est absent.

**Références de lignes (indications approximatives ; si le code a changé, retrouver l’emplacement par grep : `build_units_cache`, `set_unit_coordinates`, `last_unit_positions`) :**
- **`engine/w40k_core.py` — `reset()`** : les unités sont chargées/initialisées (positions, HP, etc.) dans la boucle vers **l.463–497**. Insérer **`build_units_cache(game_state)`** juste après cette boucle. Initialiser aussi `game_state["units_cache_prev"]` (ex. copie depuis `units_cache`, ou dict vide pour le premier step).

#### A.3 Mise à jour incrémentale (position / HP / mort)

Pour chaque endroit qui modifie la position ou les HP d’une unité, ou qui enlève une unité (mort), appeler les helpers du cache :

1. **Mouvement (MOVE, FLED, ADVANCE, CHARGE)**  
   Après toute mise à jour de `unit["col"]`, `unit["row"]` :  
   `update_units_cache_unit(game_state, unit_id, col, row, unit["HP_CUR"], unit["player"])` (ou `update_units_cache_position` si implémentée).
2. **Tir — cible touchée / morte**  
   Après réduction de HP ou mort de la cible : mise à jour de l’entrée si encore vivante ; si `HP_CUR <= 0` : `remove_from_units_cache(game_state, target_id)` (ou `update_units_cache_hp(game_state, target_id, 0)`) et suppression de la cible du `los_cache` / pools comme aujourd’hui.
3. **Combat (fight)**  
   Idem : après modification de HP ou mort, mettre à jour `units_cache` ou retirer l’unité.
4. **Fuite (FLED)**  
   Position mise à jour puis `update_units_cache_unit` ; si l’unité est « retirée » du plateau (selon les règles), possiblement `remove_from_units_cache` selon la règle métier.
5. **Toute autre action qui déplace ou tue une unité**  
   Même principe : synchroniser `game_state["units"]` et `game_state["units_cache"]`.

**Recherche exhaustive :** faire un grep sur les assignations à `unit["col"]`, `unit["row"]`, `unit["HP_CUR"]` et sur les suppressions / marquages de mort d’unité, et ajouter l’appel au helper correspondant juste après.

**Emplacements précis (référence code actuel ; numéros de lignes approximatifs, confirmer par grep si besoin) :**
- **Position :** après tout appel à `set_unit_coordinates(unit, col, row)` — `movement_handlers.py`, `charge_handlers.py`, `shooting_handlers.py` (advance, vers **l.4106–4107** dans `_handle_advance_action`) : appeler `update_units_cache_position` ou `update_units_cache_unit`.
- **Position (init) :** dans `w40k_core.py` après chargement des units au reset (après la boucle vers **l.463–497**) : appeler `build_units_cache(game_state)`.
- **HP / mort (tir) :** dans le contrôleur de tir (shooting_handlers), après modification de `target["HP_CUR"]` : `update_units_cache_hp` ; si mort : `remove_from_units_cache(game_state, target_id)`.
- **HP / mort (combat) :** dans fight_handlers, après dégâts en mêlée : idem.
- **Fin de step (w40k_core) :** supprimer la boucle qui met à jour **`self.last_unit_positions`** (actuellement vers **l.967–974**). Ne plus utiliser `self.last_unit_positions`.

Fichiers concernés :
- `engine/phase_handlers/movement_handlers.py`
- `engine/phase_handlers/shooting_handlers.py` (ex. après dégâts, mort cible, advance)
- `engine/phase_handlers/charge_handlers.py`
- `engine/phase_handlers/fight_handlers.py`
- `engine/w40k_core.py` (reset, et tout endroit qui modifie unités)

#### A.4 Snapshot « étape précédente » pour obs/reward (Option B)

- **`engine/w40k_core.py` — `step()`**  
  Au tout début du step (avant traitement de l’action), après les checks de terminaison / turn limit, copier `game_state["units_cache"]` dans `game_state["units_cache_prev"]`. Exemple de copie (au minimum col, row, HP_CUR, player pour chaque unit_id) :

```python
game_state["units_cache_prev"] = {
    uid: {"col": d["col"], "row": d["row"], "HP_CUR": d["HP_CUR"], "player": d["player"]}
    for uid, d in game_state.get("units_cache", {}).items()
}
```

- En **fin** de step (après traitement de l’action), la mise à jour de `units_cache` est déjà faite par les handlers (A.3). Supprimer la boucle qui met à jour **`self.last_unit_positions`** (vers **l.967–974** dans w40k_core) ; ne plus utiliser `self.last_unit_positions`.

---

### Phase B — Utilisation de `units_cache` à la place de `position_cache`

#### B.1 LoS et pool de cibles (shooting)

- **`engine/phase_handlers/shooting_handlers.py`**
  - **`build_unit_los_cache(game_state, unit_id)`**  
    Remplacer la lecture de `game_state["position_cache"]` par une itération sur `game_state["units_cache"]` en ne gardant que les unités **ennemies** (comparer `player` au `current_player`). Pour chaque entrée, utiliser `entry["col"]`, `entry["row"]` pour `has_line_of_sight_coords`. Exiger que `units_cache` existe (sinon lever une erreur claire). On peut utiliser `get_unit_position_from_cache` si le helper est implémenté.
  - **`update_los_cache_after_target_death(game_state, dead_target_id)`**  
    Remplacer la suppression dans `position_cache` par `remove_from_units_cache(game_state, dead_target_id)` (si pas déjà fait côté dégâts/mort). Conserver la mise à jour du `los_cache` de l’unité active.
  - **`shooting_phase_start()`**  
    Ne plus appeler `build_position_cache`. **Ne pas** appeler `build_units_cache` ici (décision « reset only », voir A.2) ; **vérifier** que `units_cache` existe (ex. `require_key(game_state, "units_cache")` ou erreur explicite si absent).

#### B.2 build_enemy_adjacent_hexes (shared_utils)

- **`engine/phase_handlers/shared_utils.py` — `build_enemy_adjacent_hexes(game_state, current_player)`**  
  Aujourd’hui la fonction itère sur `game_state["units"]` en filtrant par `player != current_player` et `HP_CUR > 0`. Remplacer par une itération sur **`game_state["units_cache"]`** : pour chaque entrée avec `player != current_player`, utiliser `(col, row)` du cache pour calculer les hex adjacents. Ainsi `units_cache` devient la source de vérité pour « ennemis vivants + position » pour ce calcul.

#### B.3 Fight

- **`engine/phase_handlers/fight_handlers.py`**
  - Remplacer toutes les vérifications `"position_cache" not in game_state` / `KeyError("position_cache must exist...")` par des vérifications sur `game_state["units_cache"]` (ex. `require_key(game_state, "units_cache")` ou équivalent).
  - Là où le code lit des positions ou des cibles « vivantes » à partir d’un cache, utiliser `units_cache` : filtrer par `player` et par présence dans le cache (= vivant).

#### B.4 Autres usages de « position des ennemis » ou « unités vivantes »

- Rechercher dans tout le projet (engine, ai) les usages de `position_cache` et les remplacer par une lecture depuis `units_cache` (avec filtre ennemi si nécessaire).
- Fichiers déjà identifiés : `engine/phase_handlers/shooting_handlers.py`, `engine/phase_handlers/fight_handlers.py`, `engine/phase_handlers/shared_utils.py`. Vérifier aussi `engine/observation_builder.py`, `engine/reward_calculator.py`, `engine/action_decoder.py`, et tout autre module qui itère sur des unités pour position / HP / vivant.

---

### Phase C — Remplacement de `last_unit_positions` par `units_cache` / `units_cache_prev`

#### C.1 Observation — movement_direction

- **`engine/observation_builder.py`**
  - Supprimer `self.last_unit_positions` du `__init__` et de toute la classe.
  - Dans **`_calculate_movement_direction(self, unit, active_unit)`** (ou équivalent) :
    - Lire les positions **précédentes** depuis `game_state["units_cache_prev"]`. Pour cela, la méthode doit recevoir `game_state` en argument (déjà le cas si appelée depuis `build_observation(game_state)`).
    - Si `game_state["units_cache_prev"]` est absent ou vide, ou si `unit_id` n’est pas dans `units_cache_prev`, retourner la valeur neutre (ex. `0.5`) comme aujourd’hui pour « pas de donnée précédente ».
    - Positions courantes : depuis `unit` / `get_unit_coordinates(unit)` ou depuis `game_state["units_cache"]`.
    - Conserver la même logique de calcul (distances, ratio de mouvement, encodage 0.0–1.0).

#### C.2 Reward — mouvement

- **`engine/reward_calculator.py`**
  - Supprimer `self.last_unit_positions` (initialisation et toute référence).
  - Dans la fonction qui calcule la récompense liée au mouvement (celle qui utilisait `last_unit_positions`), utiliser `game_state["units_cache_prev"]` et `game_state["units_cache"]` (ou `game_state["units"]`) de la même façon que dans l’observation.

#### C.3 Env (w40k_core)

- **`engine/w40k_core.py`**
  - Supprimer `self.last_unit_positions = {}` dans `__init__`.
  - Dans `step()`, supprimer la boucle qui met à jour `self.last_unit_positions` à la fin du step (remplacée par la mise à jour de `units_cache` et la copie vers `units_cache_prev` en début de step).
  - S’assurer que `reset()` initialise `units_cache` et `units_cache_prev` comme en A.2.

---

### Phase D — Suppression des anciens caches

#### D.1 `position_cache`

- Supprimer **`build_position_cache()`** de `engine/phase_handlers/shooting_handlers.py` (définition et tous les appels).
- Supprimer toute référence à `game_state["position_cache"]` dans le repo (déjà couvert en B.1–B.4).
- Ne plus jamais écrire ni lire `position_cache`.

#### D.2 `last_unit_positions`

- Supprimer `self.last_unit_positions` de `engine/w40k_core.py` (déclaration, mise à jour, tout usage).
- Supprimer `self.last_unit_positions` de `engine/observation_builder.py`.
- Supprimer `self.last_unit_positions` de `engine/reward_calculator.py`.

#### D.3 Scripts et analyse

- **`scripts/check_ai_rules.py`** et **`scripts/check_ai_rules3.py`**  
  Remplacer les références à `build_position_cache` / `position_cache` par les nouvelles règles : `build_units_cache` appelé **au reset uniquement**, pas en phase start (shooting/fight) ; pas de recalcul intempestif.
- **`ai/analyzer.py`**  
  Voir « Note sur l’analyseur » en fin de document.

---

### Phase E — Vérifications et cohérence

#### E.1 Points de cohérence

- **Unité vivante :** partout, une unité est considérée vivante si et seulement si elle est présente dans `units_cache`. Les parcours « unités vivantes » peuvent être remplacés par une itération sur `units_cache` ou par un filtre sur `game_state["units"]` en croisant avec `units_cache` selon les besoins perf.
- **Position :** pour toute logique qui a besoin de la position d’une unité vivante, utiliser en priorité `game_state["units_cache"][unit_id]["col"]` et `["row"]` ou les helpers `get_unit_position_from_cache` / `get_unit_from_cache`.
- **get_unit_by_id / _get_unit_by_id :** ces fonctions continuent de lire dans `game_state["units"]`. Elles restent la référence pour les champs complets de l’unité. Le cache est une vue optimisée (position, HP, player).

#### E.2 Tests et régression

- Vérifier que les phases (movement, shooting, charge, fight) se déroulent sans erreur et que les pools (activation, cibles, LoS) sont cohérents.
- Vérifier que l’observation (notamment movement_direction) et les rewards basés sur le mouvement sont corrects après un ou plusieurs steps.
- Vérifier reset → step → step et que `units_cache_prev` / `units_cache` sont cohérents entre deux steps.
- Ordre recommandé à la mort (HP → 0) : 1) mettre à jour `unit["HP_CUR"]` dans `game_state["units"]`, 2) `update_units_cache_hp` ou `remove_from_units_cache`, 3) mise à jour des los_cache / valid_target_pool / pools d’activation comme aujourd’hui.

#### E.3 Documentation et règles

- **Documentation projet :**  
  Mettre à jour **Documentation/AI_TURN.md**, **Documentation/AI_IMPLEMENTATION.md** (ou équivalent) pour décrire `units_cache` et `units_cache_prev` comme source de vérité pour position et HP des unités vivantes, et le moment de mise à jour / snapshot.
- **Règles Cursor :**  
  Mettre à jour les règles dans `.cursor/rules/` si elles mentionnent `position_cache` ou `last_unit_positions` : ex. `ai_turn_compliance.mdc`, `shooting_compliance.mdc`, `coding_practices.mdc`. Exiger que position / HP / statut vivant soient lus depuis le cache (ou les helpers).
- **Scripts de vérification :**  
  `scripts/check_ai_rules.py`, `scripts/check_ai_rules3.py` : remplacer les vérifications sur `build_position_cache` / `position_cache` par `build_units_cache` / `units_cache`.
- **Documentation des règles :**  
  Si le projet contient un fichier du type **Documentation/CHECK_AI_RULES.md** (ou équivalent), le mettre à jour pour refléter les nouveaux noms et contrats.

---

## 4. Liste de fichiers impactés (référence)

| Fichier | Action |
|---------|--------|
| `engine/phase_handlers/shared_utils.py` (ou `engine/unit_cache.py`) | Ajouter build_units_cache, update_units_cache_unit, remove_from_units_cache ; recommandé : get_unit_from_cache, is_unit_alive, get_unit_position_from_cache ; optionnel : update_units_cache_position, update_units_cache_hp. **build_enemy_adjacent_hexes** : itérer sur units_cache au lieu de game_state["units"]. |
| `engine/phase_handlers/shooting_handlers.py` | Remplacer position_cache par units_cache ; supprimer build_position_cache ; ne pas appeler build_units_cache en shooting_phase_start (reset only, A.2) ; vérifier que units_cache existe ; update_los après mort ; build_unit_los_cache lit units_cache ; après advance (vers l.4106–4107) et après dégâts/mort : update_units_cache_* / remove_from_units_cache. |
| `engine/phase_handlers/fight_handlers.py` | Vérifications sur units_cache au lieu de position_cache. |
| `engine/phase_handlers/movement_handlers.py` | Après chaque mouvement (MOVE, FLED), update_units_cache_unit (ou update_units_cache_position). |
| `engine/phase_handlers/charge_handlers.py` | Après chaque déplacement/charge, update_units_cache_unit ; après mort, remove_from_units_cache si applicable. |
| `engine/w40k_core.py` | reset: build_units_cache, init units_cache_prev ; step: début → copie units_cache → units_cache_prev ; fin step: ne plus mettre à jour last_unit_positions ; supprimer self.last_unit_positions. |
| `engine/observation_builder.py` | Supprimer last_unit_positions ; _calculate_movement_direction lit depuis game_state["units_cache_prev"] et game_state["units_cache"] (ou unit courant). |
| `engine/reward_calculator.py` | Supprimer last_unit_positions ; calcul reward mouvement depuis game_state["units_cache_prev"] / units_cache. |
| `scripts/check_ai_rules.py`, `scripts/check_ai_rules3.py` | Remplacer règles position_cache par units_cache. |
| Documentation (AI_TURN.md, AI_IMPLEMENTATION.md, .cursor/rules, CHECK_AI_RULES.md si présent) | Documenter units_cache et units_cache_prev. |

---

## 5. Inventaire des scripts et fichiers utilisant coordonnées et HP_CUR

Cette section recense **tous** les fichiers du projet qui utilisent les coordonnées (col, row, position) et/ou **HP_CUR**, afin que l’implémentation de `units_cache` puisse être cohérente partout (ou que les choix « hors scope » soient explicites).

### 5.1 Moteur (engine/)

| Fichier | Usage coordonnées / HP_CUR | Impact units_cache |
|---------|----------------------------|--------------------|
| `engine/w40k_core.py` | `last_unit_positions`, `get_unit_coordinates`, reset/step positions | **Direct** : remplacer par units_cache / units_cache_prev. |
| `engine/phase_handlers/shooting_handlers.py` | `position_cache`, `build_position_cache`, LoS, HP_CUR (pools, dégâts) | **Direct** : remplacer position_cache par units_cache ; garder HP_CUR cohérent avec cache. |
| `engine/phase_handlers/fight_handlers.py` | `position_cache`, `get_unit_by_id`, HP_CUR (cibles, dégâts) | **Direct** : vérifier units_cache ; cohérence HP. |
| `engine/phase_handlers/movement_handlers.py` | Positions (col, row), HP_CUR (unités vivantes, occupation) | **Direct** : update_units_cache_unit après chaque mouvement. |
| `engine/phase_handlers/charge_handlers.py` | Positions, HP_CUR (ennemis, cibles charge, pools) | **Direct** : update_units_cache_unit / remove après charge/mort. |
| `engine/phase_handlers/shared_utils.py` | HP_CUR (threat, validation), **build_enemy_adjacent_hexes**, coordonnées via unit | **Direct** : helpers cache ; **build_enemy_adjacent_hexes** basé sur units_cache. |
| `engine/phase_handlers/generic_handlers.py` | Passage game_state / unités (col, row, HP) selon phases | Vérifier si lecture position/HP ; aligner sur units_cache si besoin. |
| `engine/observation_builder.py` | `last_unit_positions`, `get_unit_coordinates`, positions unités | **Direct** : remplacer par units_cache_prev / units_cache. |
| `engine/reward_calculator.py` | `last_unit_positions`, positions, HP pour reward mouvement | **Direct** : remplacer par units_cache_prev / units_cache. |
| `engine/action_decoder.py` | Masques d’actions, unités (position, HP pour validité) | Vérifier si lecture position/HP ; s’appuyer sur units_cache si pertinent. |
| `engine/combat_utils.py` | `get_unit_coordinates`, distances hex, LoS (coords) | Pas de cache propre ; appelé avec (col, row) ; source peut devenir units_cache. |
| `engine/game_state.py` | Structure game_state, unités (col, row, HP_CUR) | Documenter présence de units_cache dans l’état. |
| `engine/ai/weapon_selector.py` | Unités / cibles (position, HP pour sélection) | Vérifier si lecture position/HP ; cohérence avec units_cache. |
| `engine/pve_controller.py` | game_state, build_observation | Indirect ; pas de lecture directe position_cache/last_unit_positions. |

### 5.2 IA et entraînement (ai/)

| Fichier | Usage coordonnées / HP_CUR | Impact units_cache |
|---------|----------------------------|--------------------|
| `ai/analyzer.py` | **`unit_positions`** local (id → (col, row)), `unit_hp`, LoS/adjacence/distance, `_position_cache_set` / `_position_cache_remove` | **Hors scope direct** : relecture de step.log ; structure locale. Voir « Note sur l’analyseur » en fin de document. |
| `ai/target_selector.py` | Unités, cibles (position, HP) | Vérifier si utilise game_state ; si oui, préférer units_cache pour « vivant » / position. |
| `ai/evaluation_bots.py` | game_state, unités | Indirect ; vérifier si accès position/HP. |
| `ai/game_replay_logger.py` | Logs, positions / actions | Pas de cache engine ; format log peut rester inchangé. |
| `ai/reward_mapper.py` | Récompenses, possiblement HP/position | Vérifier si lit position/HP depuis game_state. |
| `ai/env_wrappers.py` | `obs_builder.build_observation(game_state)` | Indirect ; pas de position_cache/last_unit_positions. |
| `ai/training_to_delete/gym_interface.py` | Obs, game_state | Idem ; à garder en tête si réactivé. |

### 5.3 Scripts (scripts/)

| Fichier | Usage coordonnées / HP_CUR | Impact units_cache |
|---------|----------------------------|--------------------|
| `scripts/check_ai_rules.py` | Vérification normalisation col/row, règles **position_cache** / build_position_cache | **Direct** : remplacer règles position_cache par units_cache / build_units_cache. |
| `scripts/check_ai_rules3.py` | Idem | **Direct** : idem. |
| `scripts/audit_shooting_phase.py` | Vérification HP_CUR > 0 (règles de tir) | Pas de cache ; s’assurer que la règle « vivant » reste alignée avec units_cache (présence dans le cache). |
| `scripts/test_cursor_rules.py` | Exemples de règles (col/row) | Pas de changement cache ; tests de règles. |
| `scripts/backup_select.py` | Référence à reward_calculator | Indirect. |

### 5.4 Check et diagnostics (check/, check/Old/)

| Fichier | Usage coordonnées / HP_CUR | Impact units_cache |
|---------|----------------------------|--------------------|
| `check/analyze_step_log_old.py` | Relecture logs, positions / unités | Similaire à analyzer ; structure locale ; option alignement format. |
| `check/episode.py` | — | Aucun usage repéré (col/row/HP_CUR). |
| `check/Old/*` (divers) | col, row, HP_CUR selon scripts (replay, tests, pathfinding) | Données de test ou replay ; pas de game_state cache. Voir section 5 du document unit_cache2 pour le détail. |

### 5.5 Services (services/)

| Fichier | Usage coordonnées / HP_CUR | Impact units_cache |
|---------|----------------------------|--------------------|
| `services/replay_parser.py` | col, row, HP_CUR (parsing step.log, units, initial_positions) | **Hors scope direct** : relecture de logs ; option : aligner structure parsée sur units_cache pour compatibilité. |
| `services/api_server.py` | col, row (destCol, destRow) dans requêtes mouvement | Pas de cache côté API ; moteur met à jour units_cache. |

### 5.6 Synthèse pour l’agent

- **Impact direct (à modifier pour units_cache)** :  
  `w40k_core`, `shooting_handlers`, `fight_handlers`, `movement_handlers`, `charge_handlers`, `shared_utils` (dont **build_enemy_adjacent_hexes**), `observation_builder`, `reward_calculator`, `check_ai_rules.py`, `check_ai_rules3.py`.
- **À vérifier (lecture position/HP vivant)** :  
  `action_decoder`, `weapon_selector`, `generic_handlers`, `target_selector`, `evaluation_bots`, `reward_mapper` ; scripts check/Old qui utilisent `game_state["units"]` (col, row, HP_CUR).
- **Hors scope direct (structure locale ou replay)** :  
  `ai/analyzer.py` (unit_positions), `services/replay_parser.py` (units/initial_positions). Option : aligner le format de données sur `units_cache` (id → col, row, HP_CUR, player) pour cohérence.

---

## 6. Ordre d’exécution recommandé pour un agent

1. **Phase 0** : Respecter les prérequis et conventions (clé str(id), normalize_coordinates, cohérence).
2. Implémenter les helpers de cache (build, update_units_cache_unit, remove) et, recommandé, les helpers d’accès (get_unit_from_cache, is_unit_alive, get_unit_position_from_cache) ; optionnel : update_units_cache_position, update_units_cache_hp (API séparée pour call sites plus clairs). Intégrer en **reset uniquement** : appeler `build_units_cache(game_state)` après la boucle d’init des unités (vers l.463–497 w40k_core) et initialiser `units_cache_prev`. Ne pas appeler `build_units_cache` en shooting_phase_start ni fight_phase_start (décision A.2).
3. Ajouter la copie `units_cache` → `units_cache_prev` au début de `step()` dans w40k_core (voir snippet A.4).
4. Remplacer tous les usages de `position_cache` par `units_cache` (shooting, fight, LoS, pools) et faire **build_enemy_adjacent_hexes** sur `units_cache`.
5. Ajouter les appels à `update_units_cache_unit` / `remove_from_units_cache` (ou update_units_cache_position / update_units_cache_hp) à chaque mutation de position/HP/mort (movement, shooting, charge, fight, fled) ; s’aider du grep sur `unit["col"]`, `unit["row"]`, `unit["HP_CUR"]`.
6. Adapter observation_builder et reward_calculator pour utiliser `units_cache_prev` / `units_cache` au lieu de `last_unit_positions`.
7. Supprimer `build_position_cache`, `position_cache`, et tous les `last_unit_positions`.
8. Mettre à jour les scripts de vérification et la documentation (AI_TURN.md, AI_IMPLEMENTATION.md, .cursor/rules, check_ai_rules*, CHECK_AI_RULES.md si présent).

Chaque étape peut être validée par des tests ciblés (ex. un step complet, un reset, une phase shooting avec LoS et mort de cible) avant de passer à la suivante.

---

## Note sur l’analyseur (ai/analyzer.py)

L’analyseur conserve son propre **unit_positions** (et _position_cache_set / _position_cache_remove) pour le parsing des logs (step.log). Ce n’est pas le même concept que `position_cache` du moteur. **Aucun changement requis** dans analyzer.py pour ce refactor, sauf si on décide plus tard d’y faire référence à un format « units_cache » exporté dans les logs ; ce n’est pas dans le périmètre obligatoire du plan. Si des références à `game_state["position_cache"]` existent dans l’analyzer, les supprimer et utiliser uniquement le cache local du script.
