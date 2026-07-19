# Perf — `generate_compact_formation` : test de case O(|empreinte|) au lieu de O(1)

Constaté le 2026-07-19 en marge du fix V11 **T6-f** (commit de déploiement par-figurine).
**Non corrigé — helper PvP partagé, gain non nécessaire au déblocage du training.**

Une première passe d'optimisation A ÉTÉ faite dans T6-f (empreinte par translation d'offsets
pré-calculés : 50 ms → 17,4 ms par formation, ×2,9). Ce document couvre ce qui RESTE.

---

## Où va le temps aujourd'hui

`generate_compact_formation` ([deployment_handlers.py:190](../../../engine/phase_handlers/deployment_handlers.py#L190))
place les figurines d'une escouade par une spirale BFS depuis l'ancre : chaque case candidate
est testée par `_legal_socle`, qui balaie l'empreinte du socle et vérifie, cellule par cellule,
les bornes du plateau, l'appartenance à la zone de déploiement, les murs, la clairance verticale
§13.06 et les unités déjà déployées.

cProfile (board x5, escouade de 6 figurines, 5 formations), APRÈS l'optimisation T6-f :

| poste | part | note |
|---|---|---|
| `generate_compact_formation` | 17,4 ms/formation | 0,087 s pour 5 appels |
| ↳ `_legal_socle` | ~77 % | 2 590 appels — balayage d'empreinte par case |
| ↳ `_deploy_pool_set` | ~13 % | reconstruit à CHAQUE appel de la fonction |
| ↳ `_model_fp` | ~18 % de `_legal_socle` | déjà optimisé en T6-f |

Le coût est donc dominé par **2 590 balayages d'empreinte** : pour chaque case de la spirale on
re-teste ~64 cellules contre plusieurs `set`.

## Piste 1 — masque de cases légales pré-calculé (érosion morphologique)

Les prédicats testés par `_legal_socle` sont tous des contraintes **de cellule** et **statiques**
pendant une formation (la zone, les murs, les `_low_clear` et les unités déjà déployées ne
bougent pas). Ils sont donc érodables une fois pour toutes :

1. construire la grille booléenne des cellules acceptables (`pool & ~murs & ~low_clear &
   ~occupé & in_bounds`) ;
2. l'éroder par l'empreinte du socle (deux jeux d'offsets, parité de colonne) ;
3. la spirale ne fait plus qu'une **lecture O(1) à l'ancre**.

Le code a déjà ce modèle, écrit et commenté, dans `ActionDecoder._get_valid_deployment_hexes`
([action_decoder.py](../../../engine/action_decoder.py)) — y compris la démonstration
d'équivalence stricte avec le calcul direct (« `acc[p] = ET sur les offsets de ok_grid[p+off]`
est exactement `np.all(in_pool & no_obstacle)` pour l'ancre p ») et le gain mesuré là-bas
(×31 à ×62).

**Gain ici : non mesuré.** Il porterait sur les ~77 % de `_legal_socle`, mais l'érosion a un
coût fixe (construction + érosion de la grille) qui n'est amorti que si la spirale visite
beaucoup de cases. À MESURER avant d'implémenter : sur une escouade de 6 figurines dont la
1re case est légale, la spirale s'arrête presque tout de suite et l'érosion serait **plus
lente**. C'est le cas nominal du déploiement gym — donc le gain n'est pas acquis.

⚠️ **Ne PAS éroder la marge inter-figurines.** `_legal_socle` impose en plus « 1 hex de marge
des figurines déjà posées » (empreinte + anneau de voisins), qui dépend des sœurs placées
pendant la boucle : c'est un état **dynamique**, non érodable en amont. Il faut le garder en
test direct après la lecture du masque.

## Piste 2 — `_deploy_pool_set` reconstruit à chaque appel

`_deploy_pool_set` ([deployment_handlers.py:124](../../../engine/phase_handlers/deployment_handlers.py#L124))
matérialise le `set` de la zone de déploiement (~16 000 hexes sur board x5) à chaque appel de
`generate_compact_formation`, soit 2,2 ms × 1 par déploiement. Mémoïsable par (joueur, version
de la zone) — la zone ne change pas pendant une phase de déploiement.

Gain plafond ~13 % du résiduel. Piège : la clé de cache doit invalider si la zone est
re-résolue (terrain rechargé, scénario différent) — un cache mal tamponné rendrait une zone
d'un autre scénario, exactement le genre d'erreur silencieuse que le projet proscrit.

## Pourquoi ce n'est pas fait

- **Helper PvP partagé** : `generate_compact_formation` sert le déploiement par escouade du
  front (`deploy_generate_formation`), pas seulement le gym. Une divergence de forme déplace
  des socles à l'écran. Même raison que le revert de
  [`bug_pile_in_bfs_clearance_mismatch.md`](bug_pile_in_bfs_clearance_mismatch.md).
- **Pas sur le chemin critique du training** : après T6-f, le déploiement coûte 1,37 s par
  épisode (contre 1,03 s pour l'ancien code, qui ne plaçait aucune figurine). Le vrai bloqueur
  du training est **T6-g / T6-h**, pas cette perf.

## Comment valider un fix

Le verrou d'équivalence existe déjà :
`tests/unit/engine/test_deployment_per_model_commit.py::test_precomputed_footprint_matches_the_canonical_one`
(empreinte translatée == `compute_candidate_footprint`, aux deux parités de colonne).

Y ajouter un test « même plan avant/après » : `generate_compact_formation` est déterministe, donc
un refactor de perf doit rendre le plan **identique** sur un échantillon d'ancres de la zone —
c'est le critère d'acceptation, pas seulement « ça va plus vite ».
