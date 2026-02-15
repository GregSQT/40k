# Profilage et optimisation du moteur W40KEngine

> **Objectif** : Identifier et accélérer les chemins chauds dans `W40KEngine.step()` pour réduire le temps d'entraînement.

---

## 1. Profiler avec py-spy (recommandé)

### Installation

```bash
pip install py-spy
```

### Profiler le processus principal

```bash
# Lancer l'entraînement en arrière-plan
python ai/train.py --agent SpaceMarine_Infantry_Troop_RangedSwarm --scenario bot --new &

# Attendre que l'entraînement démarre (quelques secondes), puis :
py-spy top --pid $(pgrep -f "train.py.*SpaceMarine") --duration 30
```

### Profiler un worker SubprocVecEnv

Les workers sont les processus qui exécutent `W40KEngine.step()`. Pour les profiler :

```bash
# Lister les processus Python
ps aux | grep python

# py-spy sur un worker (remplacer PID par le PID d'un processus enfant)
py-spy top --pid <PID_WORKER> --duration 30
```

### Exporter un flamegraph

```bash
py-spy record -o profile.svg --pid <PID> --duration 60
# Ouvrir profile.svg dans un navigateur
```

### Interpréter les résultats

- **Fonctions en haut du tableau** = les plus coûteuses en temps CPU
- Chercher : `get_action_mask_and_eligible_units`, `_build_observation`, `build_observation`, `_process_semantic_action`, `has_line_of_sight`, `calculate_pathfinding_distance`, `shooting_build_valid_target_pool`

---

## 2. Profiler avec cProfile

### Script de profilage intégré

Créer `scripts/profile_engine.py` :

```python
#!/usr/bin/env python3
"""Profile W40KEngine.step() with cProfile."""
import cProfile
import pstats
import io
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai.training_utils import setup_imports, get_agent_scenario_file
from ai.unit_registry import UnitRegistry
from config_loader import get_config_loader

def main():
    W40KEngine, _ = setup_imports()
    cfg = get_config_loader()
    unit_registry = UnitRegistry()
    scenario_file = get_agent_scenario_file(cfg, "SpaceMarine_Infantry_Troop_RangedSwarm", "default", "bot")
    
    env = W40KEngine(
        rewards_config="SpaceMarine_Infantry_Troop_RangedSwarm",
        training_config_name="default",
        controlled_agent="SpaceMarine_Infantry_Troop_RangedSwarm",
        scenario_file=scenario_file,
        unit_registry=unit_registry,
        quiet=True,
        gym_training_mode=True,
    )
    obs, _ = env.reset()
    
    profiler = cProfile.Profile()
    profiler.enable()
    for _ in range(500):  # 500 steps pour des stats plus stables
        action = env.action_space.sample()
        obs, reward, term, trunc, info = env.step(action)
        if term or trunc:
            obs, _ = env.reset()
    profiler.disable()
    
    s = io.StringIO()
    ps = pstats.Stats(profiler, stream=s).sort_stats(pstats.SortKey.CUMULATIVE)
    ps.print_stats(40)  # Top 40 functions
    print(s.getvalue())

if __name__ == "__main__":
    main()
```

Exécuter : `python scripts/profile_engine.py`

---

## 3. Points chauds identifiés (à vérifier)

D'après l'analyse du code, les candidats les plus probables :

| Fonction | Fichier | Pourquoi |
|----------|---------|----------|
| `get_action_mask_and_eligible_units` | action_decoder.py | Appelée **2 fois par step** : état avant action (convert_gym_action) + état après action (_build_observation). États différents → pas de redondance évidente. |
| `_build_mask_for_units` (shoot phase) | action_decoder.py | Appelle `shooting_build_valid_target_pool` |
| `shooting_build_valid_target_pool` | shooting_handlers.py | Calcul des cibles valides, LoS, etc. |
| `build_observation` | observation_builder.py | Construction de l'obs (323 floats) |
| `has_line_of_sight` | combat_utils.py | Appelée pour chaque paire unit-cible |
| `calculate_pathfinding_distance` | combat_utils.py | A* ou Dijkstra sur la grille hex |
| `_process_semantic_action` | w40k_core.py | Délègue aux phase_handlers |

---

## 4. Optimisations possibles

### 4.1 get_action_mask_and_eligible_units — à vérifier au profilage

**Contexte** : Appelée 2 fois par step : (1) au début de `step()` pour l'état **avant** l'action (convert_gym_action), (2) dans `_build_observation()` pour l'état **après** l'action. Ce sont deux états différents — `step()` ne calcule pas le mask post-action avant d'appeler `_build_observation`.

**Action** : Si le profiler montre cette fonction en tête, analyser les chemins d'appel avant toute optimisation. Ne pas supposer une redondance sans vérification.

### 4.2 Cache pour has_line_of_sight

**Problème** : `hex_los_cache` existe dans game_state mais peut être sous-utilisé ou mal dimensionné.

**Vérifier** : `engine/w40k_core.py` ligne 563 : `"hex_los_cache": {}` est réinitialisé à chaque reset. S'assurer que le cache est bien utilisé dans `has_line_of_sight` et que la clé de cache est efficace (ex. `(hex1, hex2)` ou `(unit_id, target_id)`).

### 4.3 Numba pour les calculs purs

**Candidats** : `calculate_hex_distance` (logique simple, types numériques — bon candidat). `has_line_of_sight` dépend de la structure des données (grille, murs) — vérifier la complexité avant de jit.

```python
# Exemple
from numba import jit

@jit(nopython=True)
def _hex_distance_fast(col1, row1, col2, row2):
    # Logique pure, pas de dict/list Python
    ...
```

**Attention** : Numba ne supporte pas les dict/list Python complexes. Il faut extraire les calculs en fonctions pures avec types simples.

### 4.4 Pré-allouer les tableaux numpy

**Problème** : `np.zeros(13, dtype=bool)` et `np.zeros(obs_size, dtype=np.float32)` créés à chaque appel.

**Solution** : Réutiliser des buffers pré-alloués dans les classes (ex. `self._mask_buffer`, `self._obs_buffer`) et les remplir in-place. Gain souvent modéré (quelques %) mais faible risque.

### 4.5 Réduire les allocations dans build_observation

**Problème** : `build_observation` crée de nouveaux tableaux à chaque step.

**Solution** : Passer un buffer `out` en paramètre et remplir in-place : `np.copyto(out, new_values)` ou écrire directement dans `out`. Gain modéré, implémentation simple.

### 4.6 Lazy evaluation pour valid_target_pool

**Problème** : `shooting_build_valid_target_pool` peut être coûteux. Vérifier si elle est appelée trop souvent (ex. à chaque get_action_mask alors que le pool n'a pas changé).

**Solution** : Mettre en cache `valid_target_pool` par unit_id tant que le game_state pertinent n'a pas changé.

**Attention** : L'invalidation du cache est délicate (positions, HP, morts, etc.). À traiter avec prudence pour éviter des bugs subtils.

### 4.7 Cython pour les chemins critiques

Si Numba n'est pas adapté (trop de structures Python), Cython peut accélérer des boucles tight :

```python
# combat_utils.pyx
def has_line_of_sight_cy(...):
    cdef int i, j
    ...
```

---

## 5. Ordre d'action recommandé

1. **Profiler** avec py-spy sur un worker pendant 30-60 s → identifier le top 5 des fonctions
2. **Vérifier** si `get_action_mask_and_eligible_units` est en tête → analyser les chemins d'appel (4.1)
3. **Vérifier** `has_line_of_sight` / `calculate_pathfinding_distance` → optimiser cache (4.2) ou Numba (4.3)
4. **Vérifier** `build_observation` → pré-allocation (4.4, 4.5)
5. **Mesurer** après chaque changement (temps pour 1000 épisodes)

---

## 6. Métriques de référence

Avant optimisation, noter :

- Temps pour 1000 épisodes (ex. ~4 min)
- `py-spy top` : % CPU des 5 premières fonctions
- Nombre de steps/seconde (affiché dans la barre de progression)

Après optimisation, comparer ces métriques.
