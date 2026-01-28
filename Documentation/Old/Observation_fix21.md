# Observation_fix21 — Version optimale définitive (fusion Fix1 + Fix2 + Fix3)

**Objectif :** Corriger le pic de performance (~3,6 s) dans `build_observation` (section enemies) en pré-calculant la LoS une fois pour les paires (alliés × six_enemies), sans modifier la sémantique des features ni la forme du vecteur d’observation.

**Public :** (1) développeur qui applique le correctif ; (2) prompt/agent qui exécutera les modifications — ce document sert de cahier des charges et de plan d’exécution unique.

**Références :**
- [Observation_tuning.md](Documentation/Observation_tuning.md) — analyse de performance, root cause
- [AI_OBSERVATION.md](Documentation/AI_OBSERVATION.md) — référence canonique (313 floats, 22 features/enemy)
- `engine/observation_builder.py` — implémentation

---

## 1. Audit de l’observation (vs AI_OBSERVATION.md et code)

### 1.1 Alignement doc / code

| Section              | AI_OBSERVATION.md   | Code (observation_builder.py) | Statut |
|----------------------|---------------------|--------------------------------|--------|
| Global context       | [0:15] 15 floats    | [0:16] 16 floats               | OK (objectifs inclus). |
| Active unit          | [15:37] 22 floats   | [16:38] 22 floats               | OK. |
| Directional terrain  | [37:69] 32 floats   | [38:70] 32 floats               | OK. |
| Allied units         | [69:141] 72 floats  | [70:142] 72 floats              | OK. |
| Enemy units          | [141:273] 132 (6×22)| [142:274] 132 (6×22)            | OK (base_idx=142). |
| Valid targets        | [273:313] 40 (5×8)  | [274:314] 40 (5×8)              | OK. |
| **TOTAL**            | **313 floats**      | `obs_size` config               | Référence : 313. |

**Conclusion :** L’implémentation est alignée sur AI_OBSERVATION.md (313 floats, 22 features par ennemi). Les indices dans le code utilisent base_idx=142 pour la section enemies ; ne pas se baser sur les anciennes plages [122:260] ou 23 features.

### 1.2 Hot path identifié (Observation_tuning.md + code)

| Étape | Fichier / fonction | Rôle |
|-------|--------------------|------|
| 1 | `observation_builder.build_observation()` | Point d’entrée ; timings t0–t7. |
| 2 | `_get_valid_targets` → `_sort_valid_targets` → `_get_six_reference_enemies` | Rapide (LoS déjà géré pour l’unité active en shoot). |
| 3 | **`_encode_enemy_units(..., base_idx=142, six_enemies=six_enemies)`** | **Goulot : ~3,6 s** dans le cas pathologique. |

Dans `_encode_enemy_units`, pour **chaque** des 6 ennemis :

- **Feature 14 — visibility_to_allies**  
  Boucle sur tous les alliés vivants ; pour chaque `(ally, enemy)` :  
  `_check_los_cached(ally, enemy, game_state)`.  
  Les alliés n’ont en général **pas** de `los_cache` (seule l’unité active en phase shoot en a un).  
  → Fallback systématique vers `_has_line_of_sight` → raycast complet (murs, hex path).  
  **Seule la feature 14 utilise la LoS** dans cette boucle.

- **Feature 15 — combined_friendly_threat**  
  Même boucle sur les alliés avec `_calculate_danger_probability(enemy, ally)` uniquement (pas d’appel LoS ; déjà mis en cache par `_danger_probability_cache`).

- **Feature 16 — melee_charge_preference**  
  Pour chaque allié avec CC+RNG à portée de charge : pathfinding + `get_best_weapon_for_target` + `calculate_ttk_with_weapon` (coût secondaire).

**Résultat :** Environ **6 × N_allies** appels LoS sans cache → 30–60 raycasts complets par `build_observation` quand N_allies = 5–10, d’où ~3,6 s.

### 1.3 Où est construit le los_cache aujourd’hui ?

- **Phase shoot :** à l’activation d’une unité, `build_unit_los_cache(game_state, unit_id)` est appelé pour **cette** unité uniquement (`shooting_handlers.py`).
- **Observation :** `build_observation` est appelé à chaque step pour l’unité qui **va** jouer ; les **alliés** utilisés dans `_encode_enemy_units` ne sont en général pas l’unité active en shoot, donc n’ont pas de `los_cache`. Le fallback LoS dans `_check_los_cached` est la règle pour presque tous les (ally, enemy).

---

## 2. Plan d’optimisation (priorisé)

### 2.1 Option A — Cache LoS dédié à l’observation (recommandé en premier)

**Idée :** Construire **une fois** par `build_observation` un cache LoS pour les paires (ally_id, enemy_id) utiles (alliés vivants × six_enemies). Dans `_encode_enemy_units`, pour la **feature 14 uniquement** (visibility_to_allies), remplacer les appels à `_check_los_cached(ally, enemy, game_state)` par une lecture dans ce cache.

**Précision importante :** La feature 15 (combined_friendly_threat) ne dépend pas de la LoS ; elle reste calculée par `_calculate_danger_probability(enemy, ally)`. Seule la feature 14 utilise le cache LoS.

**Implémentation (meilleur des trois fixes) :**

1. **Nouvelle méthode dédiée** (séparation des responsabilités, testable) :  
   `_build_los_cache_for_observation(self, active_unit, game_state, six_enemies) -> Dict[Tuple[str, str], bool]`  
   - Récupère la liste des alliés vivants (même critère que dans `_encode_enemy_units` : `player == active_unit["player"]`, `HP_CUR > 0`).  
   - Pour chaque paire `(ally, enemy)` avec `enemy` dans `six_enemies` :  
     - **Si** l’ally a déjà un `los_cache` et `enemy["id"]` dedans : utiliser `ally["los_cache"][enemy["id"]]` et stocker dans le dict de retour (évite un raycast redondant).  
     - **Sinon** : appeler `_has_line_of_sight(game_state, ally, enemy)` (via `shooting_handlers._has_line_of_sight`) et stocker le résultat.  
   - Clés du dict : `(ally["id"], enemy["id"])` (types stables `str`).

2. **Dans `build_observation`** : après `six_enemies = self._get_six_reference_enemies(...)`, appeler `los_cache_obs = self._build_los_cache_for_observation(active_unit, game_state, six_enemies)` et passer `los_cache_obs` à `_encode_enemy_units(..., los_cache_obs=los_cache_obs)`.

3. **Dans `_encode_enemy_units`** : ajouter le paramètre optionnel `los_cache_obs: Optional[Dict[Tuple[str, str], bool]] = None`. Pour la **feature 14 (visibility_to_allies)** uniquement : si `los_cache_obs` est fourni, utiliser `los_cache_obs.get((ally["id"], enemy["id"]), False)` au lieu de `_check_los_cached(ally, enemy, game_state)`. Si `los_cache_obs` est `None` (appel hors `build_observation`), conserver le comportement actuel (`_check_los_cached`) pour rétrocompatibilité.

**Avantages :**  
- Un seul calcul LoS par paire (ally, enemy) ; réutilisation du `los_cache` existant sur un allié quand il est déjà rempli.  
- Aucun effet de bord sur les unités (dict local, pas de modification de `unit["los_cache"]`).  
- Feature 15 inchangée (danger prob uniquement).

### 2.2 Option B — Cache LoS sur les alliés (non retenu)

Construire un `los_cache` sur chaque unité alliée pour les 6 ennemis. Rejeté : effet de bord sur les unités, risque de conflit avec le cycle de vie AI_TURN (nettoyage des caches). Option A (dict local) donne le même gain sans ces inconvénients.

### 2.3 Option C — Alléger les features coûteuses (complémentaire, après A)

- **Feature 14** : une fois Option A en place, le coût LoS disparaît.
- **Feature 15** : déjà partiellement caché (`_danger_probability_cache`) ; vérifier que toutes les paires (enemy, ally) utilisent le cache.
- **Feature 16 (melee_charge_preference)** : si besoin après mesure, limiter le nombre d’alliés considérés (ex. 3 les plus proches) ou mettre en cache pathfinding/TTK par (ally_id, enemy_id) pour la durée de l’obs.

À traiter **après** Option A et mesure du nouveau `enemies_s`.

### 2.4 Ordre d’exécution recommandé

1. **Phase 1 — Correctif principal** : Implémenter Option A (méthode `_build_los_cache_for_observation` + utilisation dans `_encode_enemy_units` pour la feature 14). Mesurer : BUILD_OBS_TIMING `enemies_s` (objectif : réduction majeure, typiquement ~10× ou < 0,1 s).
2. **Phase 2 — Nettoyage** : Supprimer ou conditionner les logs temporaires BUILD_OBS_TIMING / LOS DEBUG une fois la root cause corrigée et les perfs validées.
3. **Phase 3 — Optionnel** : Si besoin, Option C (feature 16).

---

## 3. Plan pour le prompt / agent qui réalisera le correctif

Objectif : appliquer le correctif avec un minimum d’ambiguïté, un seul fichier modifié, et des critères de succès vérifiables.

### 3.1 Contexte à fournir au prompt

- **Documents à lire en priorité :**  
  `Documentation/Observation_tuning.md`, `Documentation/AI_OBSERVATION.md`, `Documentation/Observation_fix21.md` (ce document).

- **Fichiers à modifier :**  
  `engine/observation_builder.py` uniquement (Phase 1).  
  À lire pour contexte : `engine/phase_handlers/shooting_handlers.py` (signature de `_has_line_of_sight`).

- **Règles du projet :**  
  Respecter `.cursorrules` (pas de fallback pour masquer une erreur, pas de workaround). Conformité AI_TURN / coding_practices : coordonnées normalisées, pas de valeur par défaut anti-erreur.

### 3.2 Tâches numérotées (ordre strict)

**Tâche 1 — Lire et ancrer**  
- Lire les sections pertinentes de `observation_builder.py` : `build_observation`, `_encode_enemy_units`, `_check_los_cached`, et la construction de `six_enemies`.  
- Repérer : appel à `_encode_enemy_units(..., base_idx=142, six_enemies=six_enemies)` et, dans `_encode_enemy_units`, la boucle sur les alliés pour la **feature 14** (visibility_to_allies) avec `_check_los_cached(ally, enemy, game_state)`.

**Tâche 2 — Ajouter `_build_los_cache_for_observation`**  
- Ajouter une nouvelle méthode dans `ObservationBuilder` :  
  `def _build_los_cache_for_observation(self, active_unit: Dict[str, Any], game_state: Dict[str, Any], six_enemies: List[Tuple[float, Dict[str, Any]]]) -> Dict[Tuple[str, str], bool]:`  
- Implémentation :  
  - Construire la liste des alliés vivants : `player == active_unit["player"]` et `HP_CUR > 0` (même critère que dans `_encode_enemy_units`).  
  - Créer un dict `result: Dict[Tuple[str, str], bool]`.  
  - Pour chaque allié vivant et chaque `(distance, enemy)` dans `six_enemies` :  
    - Clé `key = (ally["id"], enemy["id"])`.  
    - Si `ally` a `"los_cache"` et `enemy["id"]` dans `ally["los_cache"]` : `result[key] = ally["los_cache"][enemy["id"]]`.  
    - Sinon : `result[key] = shooting_handlers._has_line_of_sight(game_state, ally, enemy)`.  
  - Retourner `result`.  
- Type hints et docstring : décrire le rôle (cache LoS pour l’obs, clés (ally_id, enemy_id), réutilisation du los_cache existant si présent).

**Tâche 3 — Utiliser le cache dans `build_observation` et `_encode_enemy_units`**  
- Dans `build_observation`, après l’obtention de `six_enemies`, appeler `los_cache_obs = self._build_los_cache_for_observation(active_unit, game_state, six_enemies)` et passer à `_encode_enemy_units(..., los_cache_obs=los_cache_obs)`.  
- Dans `_encode_enemy_units`, ajouter le paramètre `los_cache_obs: Optional[Dict[Tuple[str, str], bool]] = None`.  
- Dans la boucle des 6 ennemis, pour le calcul de **visibility_to_allies (feature 14)** :  
  - Si `los_cache_obs` est fourni : pour chaque allié, remplacer `_check_los_cached(ally, enemy, game_state)` par `los_cache_obs.get((ally["id"], enemy["id"]), False)`.  
  - Si `los_cache_obs` est `None` : garder `_check_los_cached(ally, enemy, game_state)` (comportement actuel).  
- Ne pas modifier le calcul de la feature 15 (combined_friendly_threat) : il reste basé sur `_calculate_danger_probability(enemy, ally)` uniquement.  
- Mettre à jour la docstring de `_encode_enemy_units` pour mentionner le paramètre `los_cache_obs`.

**Tâche 4 — Cohérence et style**  
- Utiliser les mêmes conventions que le reste du fichier (require_key / erreurs explicites si une clé requise manque).  
- Pas de fallback silencieux : si une paire (ally, enemy) utilisée dans la feature 14 n’est pas dans le cache alors que `los_cache_obs` est fourni, la clé doit normalement être présente (cache construit avec les mêmes listes). En cas d’oubli, préférer une erreur explicite ou un commentaire plutôt qu’un défaut invisible (ex. `False` via `.get(..., False)` est acceptable si le cache est garanti complet pour les paires parcourues).

**Tâche 5 — Vérification**  
- S’assurer qu’aucun autre appel à `_encode_enemy_units` (hors `build_observation`) ne passe `los_cache_obs` ; dans ce cas le comportement reste l’ancien.  
- Vérifier que la taille et les plages d’observation ne changent pas (313 floats, section enemies [142:274]).  
- Si le projet a un test ou script de vérification d’observation (shape 313), le relancer.  
- Optionnel : activer `debug_mode` et comparer BUILD_OBS_TIMING avant/après (objectif : `enemies_s` nettement réduit).

### 3.3 Pièges à éviter

- **Indices :** Le code utilise `base_idx=142` et **22** features par ennemi. Ne pas se baser sur les anciennes plages [122:260] ou 23 features de versions antérieures du doc.  
- **Alliés :** Utiliser **exactement** le même critère que dans `_encode_enemy_units` (player, HP_CUR > 0) pour construire la liste des alliés dans `_build_los_cache_for_observation`.  
- **Import :** `_has_line_of_sight` est dans `engine.phase_handlers.shooting_handlers` ; l’observation_builder l’importe déjà ailleurs — éviter les imports circulaires.  
- **Clés du cache :** Types stables pour les clés du dict, ex. `(str, str)` avec `ally["id"]` et `enemy["id"]`.  
- **Feature 15 :** Ne pas utiliser le cache LoS pour la feature 15 (combined_friendly_threat) ; elle ne dépend pas de la LoS.

### 3.4 Ce que le prompt ne doit pas faire

- Ne pas modifier la taille du vecteur d’observation ni les plages documentées dans `AI_OBSERVATION.md` sans accord explicite.  
- Ne pas introduire de valeur par défaut “anti-erreur” (ex. considérer LoS = True si clé absente pour masquer un bug).  
- Ne pas toucher à `shooting_handlers.py` ni aux autres handlers pour la Phase 1 (Option A uniquement dans `observation_builder.py`).  
- Ne pas modifier la sémantique des features (visibility_to_allies reste “combien d’alliés voient cet ennemi”, normalisé comme aujourd’hui).

### 3.5 Critères de succès

- **Fonctionnel :** Les valeurs de la feature 14 (visibility_to_allies) restent les mêmes qu’avant pour les mêmes `game_state` (même sémantique, moins de recalculs).  
- **Performance :** Temps de la section “enemies” (BUILD_OBS_TIMING `enemies_s`) nettement réduit (objectif : réduction majeure, typiquement ~10× ou < 0,1 s dans un cas comparable à episode 58, step 111).  
- **Code :** Un seul fichier modifié (`observation_builder.py`), avec une nouvelle méthode dédiée, type hints et docstrings à jour, pas de régression sur les règles du projet.

### 3.6 Résumé une phrase pour le prompt

“Dans `engine/observation_builder.py`, ajouter la méthode `_build_los_cache_for_observation` qui remplit un dict LoS (ally_id, enemy_id) → bool en réutilisant le `los_cache` des alliés quand il existe, sinon en appelant `_has_line_of_sight` ; l’appeler depuis `build_observation` après `six_enemies` et passer le cache à `_encode_enemy_units` ; dans `_encode_enemy_units`, utiliser ce cache **uniquement pour la feature 14** (visibility_to_allies) à la place de `_check_los_cached`, en conservant le comportement actuel si le cache n’est pas fourni.”

---

## 4. Synthèse et avis

- **Root cause :** Bien identifiée dans Observation_tuning.md : LoS recalculée jusqu’à 6×N_allies fois par obs sans cache. Le correctif par cache dédié (Option A) avec réutilisation du `los_cache` existant est standard et prévisible en gain.  
- **Risques :** Faibles si on se limite à un dict local et à une nouvelle méthode sans modifier le cycle de vie des `los_cache` des unités. Le seul piège serait d’oublier le cas où `_encode_enemy_units` est appelé sans `los_cache_obs` (ex. depuis un test) — d’où le fallback explicite “si los_cache_obs is None, comportement actuel”.  
- **Feature 16 :** Coûteuse (pathfinding + TTK). Si après Option A le step reste au-dessus du seuil souhaité, Option C (plafonner ou cacher) est la prochaine étape logique.  
- **Documentation :** AI_OBSERVATION.md est à jour (313 floats, 22 features/enemy). Ce document (Observation_fix21) sert de base unique pour l’implémentation.

---

**Statut du document :** Version optimale définitive, prêt pour exécution (Phase 1).  
**Prochaine action recommandée :** Utiliser la section 3 (plan pour le prompt) pour rédiger le prompt qui appliquera les tâches 1–5 en respectant .cursorrules.
