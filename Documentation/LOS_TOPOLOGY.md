# LoS Topology (précalcul)

Ce document décrit le système de topologie LoS précalculée pour l’optimisation des vérifications de ligne de vue.

---

## Vue d’ensemble

Le script `scripts/los_topology_builder.py` génère des fichiers `.npy` contenant le ratio de visibilité (0–1) pour chaque paire d’hexes du plateau. Le moteur utilise ces fichiers pour des lookups O(1) au lieu de recalculer la LoS (~1000× plus rapide).

**Emplacement** : `config/board/{cols}x{rows}/los_topology_{cols}x{rows}-{XX}.npy`

**Index** : `arr[from_row * cols + from_col, to_row * cols + to_col]`

---

## Ensemble de murs (cohérence moteur)

La topologie doit utiliser **exactement le même ensemble de murs** que le moteur (`engine/w40k_core.py`). Deux sources sont fusionnées :

### 1. Murs de terrain (`walls-XX.json`)

Fichier : `config/board/{cols}x{rows}/walls-XX.json` (ou `config/agents/_walls/` en fallback).

Structure :
```json
{
  "wall_id": "walls-01",
  "wall_hexes": [[col, row], ...]
}
```

### 2. Hexes de bordure (board boundary)

**Catégorie séparée** : hexes structurels, pas des murs de terrain.

En grille hex **pointy-top offset**, la dernière ligne n’a pas d’hexes pour les colonnes impaires. Ces positions sont traitées comme des murs pour :

- Bloquer le mouvement
- Bloquer la LoS (cohérence avec le moteur)

**Calcul** (identique à `w40k_core.py`) :
```python
bottom_row = rows - 1
for col in range(cols):
    if col % 2 == 1:
        wall_hexes.add((col, bottom_row))
```

Exemple 25×21 : `(1,20), (3,20), (5,20), ..., (23,20)` — 12 hexes.

---

## Usage

```bash
python scripts/los_topology_builder.py 25x21
python scripts/los_topology_builder.py --cols 25 --rows 21
```

Le script :

1. Charge les murs de `walls-XX.json`
2. Ajoute les hexes de bordure (bottom_row)
3. Calcule la topologie via `_compute_los_visibility_ratio` (même logique que le moteur)
4. Sauvegarde `los_topology_{cols}x{rows}-{XX}.npy`

---

## Intégration moteur

- **Chargement** : au reset, si le scénario a `wall_ref` (ex. `walls-01.json`), le moteur charge la topologie correspondante.
- **Lookup** : `_get_los_visibility_state` utilise `game_state["los_topology"]` quand disponible.
- **Cohérence** : la topologie inclut les bottom_row ; les résultats sont identiques au calcul en jeu.

---

## Références

- `engine/w40k_core.py` : `base_wall_hexes` (lignes 327–330)
- `engine/phase_handlers/shooting_handlers.py` : `_get_los_visibility_state`, `_compute_los_visibility_ratio`
- `Documentation/AI_TURN.md` : règles LoS, seuils `los_visibility_min_ratio`, `cover_ratio`
