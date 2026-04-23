# Tir / LoS — Forme de la preview (plateau ×10)

**Date de décision (contexte chat) :** 23 avril 2026.

## Objectif utilisateur

- Réduire l’aspect **dentelé / crénelé** de la zone de ligne de vue (LoS) affichée en jeu.
- Éviter la lecture « pastilles hex empilées » ou « triangles » issus de l’enveloppe de disques par hex.
- **Aucun fallback silencieux** vers un rendu disque-par-disque si la géométrie union échoue : erreur explicite (`throw`).

## Où c’est rendu

| Contexte | Fichier | Mécanisme |
|----------|---------|-----------|
| Survol move (icône de destination) — overlay Pixi au-dessus du plateau | `frontend/src/components/BoardPvp.tsx` | `hoverOverlayRef` (zIndex ~40), alimenté après `computeVisibleHexes` (WASM) + `buildShootingLosPreviewFromVisibleHexes` |
| Phase tir / `movePreview` — surcouche dans le rendu plateau | `frontend/src/components/BoardDisplay.tsx` | `drawBoard` : palette « shooting » (`attackCells` / `coverCells`) |

Logique métier LoS (hex visibles, couvert / clair) : `frontend/src/utils/losPreviewHelpers.ts`, WASM `frontend/wasm-los/src/lib.rs` + `frontend/src/utils/wasmLos.ts`.

## Symptôme observé

- Remplissage **cercle par hex** (`drawCircle` au rayon hex) : bord extérieur = enveloppe d’arcs → **fort crénelage**.
- Une tentative d’**union hex + Chaikin** sans autre soin : bord encore très « grille » au zoom, ou peu de différence selon le chemin d’exécution (voir ci-dessous).

## Historique des tentatives

1. **Union hex + Chaikin + contours feutrés** (plusieurs `lineStyle` sur le polygone lissé, type halo charge)  
   - Retour utilisateur : échec visuel → **rollback**.

2. **Union hex + Chaikin, remplissage uniquement** (sans contours), avec **fallback** `drawGroup` (cercles) si `tryBuildHexUnionMaskPolygons` retournait `null`  
   - Souvent **aucun changement perçu** : en phase **tir** avec `enforceBackendTargetsOnly`, `appendShootingPreviewCells` remplit surtout une **ligne** `getHexLine` vers les cibles backend, pas la grande zone WASM sur `BoardDisplay` ; sur le survol move, le fallback masquait aussi le gain.

3. Exigence **« AUCUN FALLBACK »**  
   - Nouveau module avec **`appendLosPreviewSmoothHexUnionFillOrThrow`** : échec union / boucles → `throw` (pas de repli disque).

4. **Amélioration perçue mais « artificielle »**  
   - Augmentation des passes **Chaikin** (6) et du plafond de sommets (180k).  
   - **`configureLosPreviewOverlaySoftEdges`** : léger `BlurFilter` Pixi + `filterArea` plein renderer + `roundPixels = false` (même famille d’idée que le flou alpha du **masque** move preview, voir `10x_move_preview_form.md`).  
   - Effet : bords plus doux, mais aspect **un peu flou / filtré** que l’on sent comme post-traitement.

## Décision retenue

- **Conserver l’implémentation actuelle comme plan B** (acceptable, lisible, sans fallback disque).
- Reconnaître explicitement que le rendu reste **partiellement artificiel** (blur global + séparation couvert/clair toujours ancrée sur la **partition hex** des données — la limite entre deux bleus peut rester « en marches » même si adoucie).

### Plan B (implémentation actuelle — à garder)

- Fichier : `frontend/src/utils/smoothHexLosUnionFill.ts`
  - `LOS_PREVIEW_SMOOTH_HEX_UNION_CHAIKIN_ITERATIONS` = **6**
  - Plafond Chaikin : **180_000** sommets après une passe
  - `appendLosPreviewSmoothHexUnionFillOrThrow` : `tryBuildHexUnionMaskPolygons` → `smoothMaskLoopsForRender` → remplissage avec trous (`beginHole`) comme le masque move
  - `configureLosPreviewOverlaySoftEdges` : `BlurFilter` (force ~1.55, qualité 3, résolution 2), `filterArea`, `roundPixels = false`
- Branché depuis **`BoardPvp.tsx`** (après les deux remplissages sur `hoverOverlayRef`) et **`BoardDisplay.tsx`** (sur le `Graphics` `los-preview-smooth-union`).

### Pistes plan A (non implémenté — pour une itération future)

- **Disque euclidien + masque** dans une `RenderTexture`, calqué sur `renderMoveAdvanceDestPoolCircleLayer` (disque + masque union lissée + éventuel flou **alpha** du masque uniquement), avec rayon dérivé de la portée LoS — bord extérieur « naturel » au prix du coût et du câblage.
- **Une seule teinte** sur le plateau pour la zone LoS (couvert / clair uniquement sur les unités / UI liste), pour supprimer la frontière interne dentelée entre deux unions.
- **Champ de visibilité continu** (shader / SDF / texture de ratios) si on veut une frontière physiquement lisse au sens du ratio d’empreinte, au-delà du maillage hex discret.

## Notes de maintenance

- Si `tryBuildHexUnionMaskPolygons` lève trop souvent en prod, la cause est une **topologie de bord** non gérée (à traiter dans `hexUnionBoundaryPolygon.ts`, pas en réintroduisant un fallback disque sans décision produit).
- Ne pas confondre avec le pipeline **move preview** documenté dans `Documentation/TODO/10x_move_preview_form.md` : autre objectif (disque move masqué), autres constantes (`MOVE_ADVANCE_MASK_*`).
