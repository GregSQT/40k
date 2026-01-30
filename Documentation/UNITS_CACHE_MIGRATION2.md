# Migration vers units_cache comme source unique (mort = absent)

## Objectif
Faire de `game_state["units_cache"]` la seule source de verite pour :
- HP (etat vivant/mort)
- positions (col/row)
- eligibilite et fin de phase/tour/episode

Le tableau `game_state["units"]` reste une source statique (unitType, armes, stats de base),
jamais utilisee pour HP/positions ou eligibilite runtime.

## Decision ferme
**Mort = absent du cache.**  
Si une unite est absente de `units_cache`, elle est consideree morte.

Implications :
- `get_hp_from_cache()` retourne `None` si l'unite est absente.
- `is_unit_alive()` signifie "present dans le cache et HP_CUR > 0".
- Aucune logique ne doit traiter une unite absente du cache comme vivante.

## Regles de lecture (cache first)
- HP : `get_hp_from_cache()` / `require_hp_from_cache()`
- Position : `get_unit_position()` / `require_unit_position()`
- Vivant : `is_unit_alive()`
- Interdit : `unit["HP_CUR"]`, `unit["col"]`, `unit["row"]` pour la logique runtime

## Invariants a maintenir
- `units_cache` existe toujours apres `reset()`.
- Tout calcul d'eligibilite s'appuie sur `units_cache`.
- Fin de phase = pool vide (pas de scan sur `game_state["units"]`).
- Fin de tour/episode basee sur pools + cache (pas sur `units`).
- Aucune divergence de position entre modules : position = cache.

---

## Plan de migration (etapes)

### Etape 1 - Infrastructure de lecture (cache first)
Remplacer toutes lectures directes par les helpers :
- HP : `get_hp_from_cache()` / `require_hp_from_cache()`
- Position : `get_unit_position()` / `require_unit_position()`
- Vivant : `is_unit_alive()`

Objectif : aucune lecture runtime d'HP/position ne passe par `game_state["units"]`.

### Etape 2 - Pools d'activation (priorite haute)
Pour chaque phase :
- construire les pools depuis `units_cache` (ids + col/row/HP/player)
- lookup dans `game_state["units"]` uniquement pour champs statiques
- bannir toute eligibilite basee sur `unit["HP_CUR"]` / `unit["col"]`

Phases concernees :
- move
- shoot
- charge
- fight

### Etape 3 - Fin de phase / fin de tour / fin d'episode
Tous les calculs de fin doivent etre bases sur :
- pools d'activation (vides = fin de phase)
- `units_cache` (comptage par player et HP_CUR)

Regles :
- phase complete = pool vide
- fin d'episode = un seul player vivant OU limite de tours

### Etape 4 - Combat, LoS, adjacency
Toutes les boucles qui calculent :
- adjacency (melee range)
- LoS ou range
- cibles valides
doivent lire les positions via `require_unit_position()` (cache), jamais via `unit["col"]/unit["row"]`.

### Etape 5 - Observation / Reward
Refactoriser encodages et scores tactiques pour :
- enumerer les unites depuis `units_cache`
- lookup `game_state["units"]` uniquement pour contenu statique

### Etape 6 - Nettoyage final
- supprimer tout acces runtime a `unit["HP_CUR"]`, `unit["col"]`, `unit["row"]`
- interdire toute fin de phase/episode basee sur `game_state["units"]`

---

## Regles detaillees

### Pattern A - Boucle principale
Avant :
- `for unit in game_state["units"]`

Apres :
- `for unit_id, entry in units_cache.items()`
- `unit = get_unit_by_id(unit_id, game_state)` uniquement si necessaire

### Pattern B - Positions
- remplacer `unit["col"]`, `unit["row"]` par `require_unit_position(unit_id, game_state)`

### Pattern C - HP
- remplacer `unit["HP_CUR"]` par `get_hp_from_cache(unit_id, game_state)`

### Pattern D - Vivant
- remplacer toute logique ad hoc par `is_unit_alive(unit_id, game_state)`

---

## Checklist par module

### Phase handlers
- [ ] Pools construits depuis `units_cache`
- [ ] Adjacency / LoS via `require_unit_position`
- [ ] Eligibilite basee sur cache
- [ ] Fin de phase = pool vide

### Engine core
- [ ] Fin d'episode calculee depuis `units_cache`
- [ ] Pas de scan HP/positions dans `game_state["units"]`

### Observation / Reward
- [ ] Enumeration via `units_cache`
- [ ] Lookup `game_state["units"]` uniquement pour armes/stats statiques

---

## Tests recommandes
1) Run court (debug off) :
- 50 episodes

2) Run moyen :
- 200 a 500 episodes

3) Run long :
- 1000 episodes si besoin de validation robustesse

Verifier :
- pas de boucle de phase sans actions
- pools coherents
- pas de regressions sur LoS / adjacency

---

## Notes de decision

### Source unique = cache (mort = absent)
Si une unite est absente du cache, elle est consideree morte.
Toute logique runtime doit respecter cette regle.

### References
- `Documentation/AI_TURN.md`
- `Documentation/AI_IMPLEMENTATION.md`
- `Documentation/unit_cache21.md`
