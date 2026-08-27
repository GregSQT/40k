# compute_footprint_placement_mask — Documentation technique

## Vue d'ensemble

Trois fonctions dans `engine/hex_utils.py` forment le socle des optimisations de placement multi-hex :

| Fonction | Ligne | Statut |
|---|---|---|
| `precompute_footprint_offsets` | ~939 | Utilisée (advance filter, movement BFS) |
| `compute_footprint_placement_mask` | ~874 | **Définie, jamais utilisée** |
| `_build_multi_hex_vectorized` | movement_handlers.py ~986 | Utilisée (movement BFS multi-hex uniquement) |

---

## `precompute_footprint_offsets`

### Ce que ça fait

Calcule une fois les offsets relatifs du socle d'une unité pour les colonnes paires et impaires.

Sur une grille hex offset odd-q, les 6 voisins d'un hex dépendent de la parité de la colonne. Les offsets du socle ne sont donc pas les mêmes selon que l'ancre est en colonne paire ou impaire.

```python
offsets_even, offsets_odd = precompute_footprint_offsets(base_shape, base_size, orientation)

# Reconstruction du footprint à n'importe quelle position (c, r) :
offsets = offsets_even if c % 2 == 0 else offsets_odd
footprint = {(c + dc, r + dr) for dc, dr in offsets}
```

### Complexité

- Appel unique : O(scan_radius²) — calcule deux footprints de référence
- Reconstruction par ancre : O(|footprint|) — juste des additions entières
- Remplacement de `compute_candidate_footprint(c, r, unit, game_state)` qui fait :
  - lecture du game_state
  - nested loop `_footprint_round` O(scan_r²) par appel
  - allocation d'un `set` Python par appel

### Utilisé dans

- `shooting_handlers.py` — advance filter `_forbidden_zone` (fix récent)
- `movement_handlers.py` — entrée de `_build_multi_hex_vectorized`

---

## `compute_footprint_placement_mask`

### Ce que ça fait

Construit un `bytearray` de taille `board_cols × board_rows` indexé `col + row * board_cols`.

Une ancre `(c, r)` vaut `1` (invalide) si le socle centré dessus :
- sort des limites du plateau, OU
- chevauche un hex de `obstacles`

### Principe : Minkowski inverse

Au lieu de tester chaque ancre contre tous les obstacles (O(anchors × obstacles)), on inverse :
pour chaque obstacle, on marque toutes les ancres qui le couvriraient.

```
Pour chaque hex obstacle (fc, fr) :
  Pour chaque offset (dc, dr) du socle :
    L'ancre (fc - dc, fr - dr) placerait le socle sur (fc, fr)
    → marquer bad[fc-dc + (fr-dr)*board_cols] = 1
```

Complexité construction : `O(|obstacles| × |offsets|)`
Complexité lookup : `O(1)` → `bad[c + r * board_cols]`

### Gestion de la parité

Les offsets dépendent de la parité de la colonne de l'ancre (pas de l'obstacle). La fonction prend `offsets_even` et `offsets_odd` séparément et, pour chaque obstacle, teste les deux ensembles en filtrant sur la parité de `nc = fc - dc`.

```python
for fc, fr in obstacles:
    for dc, dr in offsets_even:
        nc = fc - dc
        if (nc & 1) != 0:   # ancre serait impaire → skip offsets_even
            continue
        ...
    for dc, dr in offsets_odd:
        nc = fc - dc
        if (nc & 1) != 1:   # ancre serait paire → skip offsets_odd
            continue
        ...
```

### Statut actuel

**Jamais utilisée dans le codebase.** Tentée sur `_fight_bfs_reachable_anchors_consolidation` (mai 2026) — revertée car contre-productive : la construction du masque itère sur les 360×312 = 112K cellules du plateau, ce qui coûte plus cher que les ~1740 checks `is_footprint_placement_valid` qu'elle remplace (ratio visité/total = 1.5%). La mask n'est rentable que si le BFS visite une fraction significative du plateau.

Le movement BFS multi-hex utilise `_build_multi_hex_vectorized` (numpy) qui a sa propre logique interne et n'a pas besoin de la mask.

---

## `_build_multi_hex_vectorized`

### Ce que ça fait

BFS multi-hex complet pour le mouvement, implémenté en numpy. Remplace le BFS Python set-based pour les unités multi-hex.

Utilise `precompute_footprint_offsets` en entrée pour les kernels numpy. Gère :
- bounds + walls + enemy_occupied (traversée)
- engagement zone (ez ≤ 1 et ez > 1)
- valid destinations (pas occupied_set)

### Remarque sur scipy

La fonction contient ce commentaire explicite :
> `scipy.ndimage.binary_dilation` a provoqué des segfaults sur certains environnements (extensions natives / `origin`), donc pas de chemin SciPy ici.

Les dilations utilisent des boucles numpy sur slices (`out[c_dst:c_dst+...] |= src[...]`), pas scipy.

---

## Où `compute_footprint_placement_mask` pourrait être appliquée

### Charge BFS (`charge_handlers.py`)

Actuellement : `compute_candidate_footprint(anchor)` + `is_footprint_placement_valid(fp)` par ancre visitée dans le BFS.

Avec la mask : `bad[c + r * board_cols]` O(1) par ancre.

**Gain estimé** : `bfs_candidate_fp_s + bfs_placement_s` ≈ 0.028s sur un `bfs_loop_s` de 0.12s → ~23% sur la boucle BFS charge.

**Limite** : le BFS visite encore 40K hexes. La mask aide sur le check par ancre, pas sur le nombre d'hexes visités.

### Consolidation BFS (`fight_handlers.py` — `_fight_bfs_reachable_anchors_consolidation`)

Actuellement : `compute_fp_s = 0.044s` sur un total BFS de 0.076s → ~58% du coût.

Avec la mask : ce coût tombe à O(1) par ancre.

**Gain estimé** : ~50% sur le BFS consolidation.

### Pile-in BFS (`fight_handlers.py`)

Même pattern que consolidation. Gain similaire attendu.

### Advance filter

Déjà optimisé avec `precompute_footprint_offsets` (check O(|offsets|) avec early exit via `any()`). La mask donnerait un gain marginal supplémentaire (O(1) vs O(|offsets|)).

---

## Pourquoi le movement BFS n'utilise pas la mask

`_build_multi_hex_vectorized` opère entièrement sur des tableaux numpy — la notion de `bytearray` mask n'est pas nécessaire car le BFS numpy fait déjà les checks par opérations bulk sur arrays. Les deux approches sont équivalentes mais dans des paradigmes différents :

- `compute_footprint_placement_mask` → paradigme bytearray Python, lookup O(1) dans une boucle Python
- `_build_multi_hex_vectorized` → paradigme numpy, opérations sur tenseurs entiers

Pour les BFS qui restent en Python pur (charge, consolidation, pile-in), la mask bytearray est l'optimisation naturelle.

---

## Résumé des priorités d'intégration

| Cible | Effort | Gain estimé | Risque |
|---|---|---|---|
| Consolidation BFS | Revertée | −0% (overhead mask > économie) | — |
| Pile-in BFS | Faible | ~50% du BFS | Faible |
| Charge BFS (placement check) | Moyen | ~23% du BFS loop | Faible |
| Advance filter | Marginal | <5% | Nul |

Note : pour charge, le gain dominant viendrait d'une réduction du nombre d'hexes visités (40K → moins), pas de la mask elle-même. Voir la suggestion de heuristique de priorité de cible charge dans les TODO.
