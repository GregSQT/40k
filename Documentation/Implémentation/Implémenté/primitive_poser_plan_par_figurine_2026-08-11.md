# Une primitive commune « poser un plan par figurine » — livré le 2026-08-11

## Le défaut

Poser une figurine issue d'un plan exige TOUJOURS deux gestes, dans cet ordre :

1. **résoudre le niveau EFFECTIF** (§13.06) — le niveau porté par le plan est celui de la VUE au
   moment du drop, un simple *hint* : une figurine dont le socle ne tient pas entièrement sur un
   plancher de ce niveau est au **sol**, pas « illégale » ;
2. **écrire** la position.

Cet enchaînement était réécrit à l'identique par chaque écrivain et chaque aperçu, chacun relisant
à la main `BASE_SHAPE` / `BASE_SIZE` / `orientation` / `terrain_areas` avant d'appeler
`resolve_model_floor_level`. L'invariant « le niveau écrit est un niveau résolu » tenait donc par
la **discipline de ses appelants**, jamais par construction — et `update_model_position` acceptait
n'importe quel entier ≥ 0.

Ce n'était pas théorique : c'est ce défaut qui a produit le 500 « figurine marquée à l'étage mais
hors empreinte de plancher » du 2026-08-11 (commit `2c587997`), où `floor_height_at` levait très
loin de l'écriture fautive et où le `catch` de l'effet client faisait disparaître **tout** le calque
de ligne de vue (cône, blink, couvert).

Une seconde faille, trouvée en cartographiant les sites : **`commit_move` n'appliquait aucune
résolution**. Elle vivait chez son appelant `commit_move_plan` (mouvement). Ses six autres
appelants — charge, pile-in, consolidation, gym (×2), plan rigide — écrivaient donc le niveau
**brut** du plan.

## La forme livrée

Deux primitives dans `engine/phase_handlers/shared_utils.py`, à côté de `update_model_position` :

| Primitive | Rôle |
|---|---|
| `resolve_model_effective_level(game_state, model, col, row, requested_level, orientation=None)` | **résout** — source unique de la dérivation, pour les aperçus comme pour les écrivains |
| `place_model_at_effective_level(game_state, model_id, col, row, level, orientation=None)` | **résout puis écrit**, et renvoie le niveau écrit |

L'`orientation` sert **d'abord** à résoudre (elle oriente l'empreinte, donc décide si le socle tient
sur le plancher), **puis** est écrite. `None` = orientation inchangée, et la résolution utilise alors
celle déjà portée par la figurine — exactement la sémantique de `plan_entry_model_orientation`,
qui reste la source unique de cette résolution côté plan.

**Les six sites annoncés, plus deux jumeaux trouvés au grep**, passent par l'une des deux :

- `deployment_handlers` — niveau effectif des sœurs (collision intra-escouade), aperçu de plan,
  et le commit par-figurine (seul des trois à écrire) ;
- `movement_handlers` — aperçu de plan, niveau de départ du mover, niveau effectif des sœurs
  (jumeau exact du site de déploiement, non annoncé au départ) ;
- `shooting_handlers` — branche `models` de `_apply_preview_placement` ;
- `shared_utils.commit_move` — **la résolution y descend**, donc elle vaut pour ses sept appelants.
  La pré-résolution que `commit_move_plan` appliquait juste avant son appel disparaît.

### Divergences de sémantique tranchées, pas uniformisées en silence

- **Orientation lue.** `deployment_handlers` lisait `model.get("orientation", 0)` (défaut face nord)
  là où `movement`/`shooting` passent par `plan_entry_model_orientation`, qui lève sur absence.
  `_build_models_for_unit` pose **toujours** `orientation` dans `models_cache` : le défaut `0` était
  un repli anti-erreur (T1), pas un comportement métier. Tranché sur le `require_key` — un cache sans
  orientation est corrompu, il doit lever.
- **Orientation du plan vs orientation du cache.** Le site de commit du mouvement résout avec
  l'orientation **du plan** (le pivot molette est appliqué juste après ; la lire sur `models_cache`
  faisait tenir l'empreinte au preview puis retomber au sol au commit). Le déploiement, lui, n'a pas
  de 5ᵉ élément : ses plans sont des 4-uplets. La primitive porte les deux cas sans les confondre —
  `orientation=None` n'est pas « face nord », c'est « celle de la figurine ».

## Le garde dur sur `update_model_position`

**Décision : garde dur posé.** Un niveau ≥ 1 dont l'empreinte ne tient pas sur un plancher lève
immédiatement, avec le renvoi vers la primitive. Trois raisons :

1. **Il ferme le sujet.** La primitive rend le bon geste facile ; le garde rend le mauvais
   impossible. Sans lui, le prochain écrivain (réserves, aperçu de charge) refait le 500 de
   `2c587997` sans que rien ne devienne rouge — ce que le backlog annonçait explicitement.
2. **Son coût est nul là où le jeu se joue.** `resolve_model_floor_level` sort immédiatement sous
   `requested_level < 1` : tout le jeu au sol ne paie rien. Le contrôle ne s'exécute que sur une
   écriture d'étage.
3. **Aucun appelant légitime n'en est cassé.** Vérifié : les écritures sans niveau
   (`reposition_unit_to_strategic_reserves`, `-1,-1`) ne l'atteignent pas ; `build_rigid_plan`
   écrit toujours `SQUAD_RIGID_MOVE_DESTINATION_LEVEL` (= sol, trivialement résolu) ; les plans de
   charge / pile-in / consolidation passent maintenant par la résolution de `commit_move`.

Le seul appelant qu'il a fait tomber était un **helper de test**, et il avait raison de tomber :
voir ci-dessous.

### Une seule exception, assumée et commentée

`translate_squad_to_destination` (squad move rigide) écrit `m["level"]` **directement**, sans passer
par `update_model_position`, et lit `terrain_areas` en `get(..., [])`. Il résout déjà correctement —
il ne porte donc pas le défaut de ce chantier. Le migrer vers `resolve_model_effective_level`
changerait son contrat en `require_key`, ce que le moteur garantit en production
(`w40k_core.py` pose toujours la clé) mais que des fixtures de test n'honorent pas. Sujet distinct,
signalé sur place par un commentaire.

## Ce que le garde a trouvé en entrant

`tests/unit/engine/test_charge3d_floors_integration.py` posait ses figurines avec
`sorted(floor_hexes_at_level(...))[len//2]` — **une case quelconque du plancher, souvent au bord**.
Le socle y débordait : les six tests d'engagement 3D mesuraient donc une cible dans un état
qu'aucun chemin de jeu ne produit, et l'un d'eux affirmait `floor_height_by_model == 3.0` sur cette
base. C'est le piège déjà payé au commit `2c587997` (« le test visait des cases de BORD de
plancher »), sur un autre fichier.

Corrigé : la fixture **filtre** les cases par le résolveur (et lève si aucune ne porte le socle,
pour ne pas remplacer un vert vacant par un autre), et le helper `_place` **exige** le niveau
demandé — un placement rabattu au sol y est désormais une erreur, pas un test qui repasse au vert en
mesurant autre chose.

## Verrous (tests/unit/engine/test_place_model_effective_level.py)

Cinq tests sur le vrai moteur et le vrai scénario d'étages. Chaque défaut a été **remis**, le rouge
constaté, puis rétabli :

| Défaut remis | Test devenu rouge |
|---|---|
| garde retiré de `update_model_position` | `test_update_model_position_refuse_un_niveau_non_resolu` — `DID NOT RAISE` |
| résolution retirée de `place_model_at_effective_level` | `test_place_rabat_au_sol...` **et** `test_commit_move_resout...` |
| `commit_move` remis à l'écriture brute | `test_commit_move_resout_le_niveau_pour_tous_ses_appelants` |

La fixture exige qu'existent **à la fois** une case qui porte le socle et une case qui le fait
déborder : sans la seconde, les tests de rabattement seraient vacants.
