# Move Preview Form (x10) — État et historique

## Objectif utilisateur

- Garder une preview **disque euclidien** autour de l'unité (rayon move/advance).
- Supprimer le crénelage visible sur les bords du masque.
- Éviter tout fallback silencieux.

## Symptôme observé

Le bord crénelé visible ne venait pas du cercle principal, mais du **masque d'atteignabilité**.
Quand ce masque était construit à partir de l'union des empreintes (footprint), on voyait une
signature "marches dreadnought" sur le contour.

## Tentatives déjà faites

1. **Fill polygonal direct (sans disque masqué)**
   - Résultat: forme trop hexagonale, ne respecte plus la perception de disque.

2. **Feathered strokes**
   - Résultat: halo parasite / débordements selon orientation des boucles.

3. **Blur sur le fill**
   - Résultat: amélioration faible / instable selon driver.

4. **Supersampling RT du masque (x3) + LINEAR**
   - Résultat: patch bien appliqué, mais pas d'amélioration visuelle significative sur l'environnement utilisateur.

5. **Chaikin additionnel sur géométrie du masque**
   - Résultat: patch bien appliqué (jusqu'à 5 itérations), pas d'effet perçu.

## Cause retenue

Le crénelage "qui suit l'empreinte" est un artefact de **forme**, pas uniquement d'anti-aliasing:
on affichait le masque footprint (où la frontière encode explicitement le rayon de base à chaque
position), donc la frontière visible héritait de cette micro-structure.

## Solution appliquée (actuelle)

Le pipeline de rendu move preview utilise maintenant:

- **Disque euclidien** `drawCircle(unitCx, unitCy, rOuter)` (alpha 0.28),
- masqué par un polygone issu du **pool des centres de destination** (`anchorPool`)
  via `tryBuildHexUnionMaskPolygons` + Chaikin,
- rendu masque en `RenderTexture` puis `diskGfx.mask = maskSprite`.

Conséquence:

- on conserve la lecture "disque de move",
- on supprime la signature crénelée "empreinte dreadnought" sur la frontière affichée.

## Détails implémentation

Fichier: `frontend/src/components/BoardDisplay.tsx`

- Le masque visuel est construit à partir de `anchorPool` (centres atteignables), et non des
  boucles footprint API.
- Les données `precomputedWorldMaskLoops` et `footprintMaskHexPool` sont conservées en entrée pour
  compat/debug, mais n'imposent plus la forme affichée.
- Le log debug expose:
  - `maskKind: "center_pool_polygon"`
  - `ignoredApiLoopsCount`
  - `ignoredFootprintMaskHexPoolSize`
  - `renderPipeline: "disk_euclidean_masked_center_pool_polygon_rt"`

## Notes

- Ce choix est volontairement **visuel-first**: la forme affichée est stabilisée et lisible.
- Si un jour on veut une fidélité footprint exacte ET un bord parfaitement lisse, il faudra un
  pipeline SDF/shader dédié (plus coûteux et plus complexe).
