# Tir / LoS — Forme de la preview (plateau ×10)

**Date de décision (contexte chat) :** 23 avril 2026. **Dernière mise à jour :** 23 avril 2026 (bords alpha + statut « on garde »).

## Objectif utilisateur

- Réduire l’aspect **dentelé / crénelé** de la zone de ligne de vue (LoS) affichée en jeu.
- Éviter la lecture « pastilles hex empilées » ou « triangles » issus de l’enveloppe de disques par hex.
- **Aucun fallback silencieux** : union hex lissée via `appendLosPreviewSmoothHexUnionFillOrThrow` → `throw` si polygone impossible (pas de repli disque).

## Où c’est rendu

| Contexte | Fichier | Mécanisme |
|----------|---------|-----------|
| Survol move (icône de destination) — overlay Pixi au-dessus du plateau | `frontend/src/components/BoardPvp.tsx` | `hoverOverlayRef` (`PIXI.Container`, zIndex ~40), après WASM + `buildShootingLosPreviewFromVisibleHexes` |
| Phase tir / `movePreview` — surcouche dans le rendu plateau | `frontend/src/components/BoardDisplay.tsx` | `drawBoard` : palette « shooting » (`attackCells` / `coverCells`) |

Logique métier LoS (hex visibles, couvert / clair) : `frontend/src/utils/losPreviewHelpers.ts`, WASM `frontend/wasm-los/src/lib.rs` + `frontend/src/utils/wasmLos.ts`.

## Symptôme observé

- Remplissage **cercle par hex** (`drawCircle` au rayon hex) : bord extérieur = enveloppe d’arcs → **fort crénelage**.

## Historique des tentatives (condensé)

1. Union hex + Chaikin + contours feutrés → rollback utilisateur.  
2. Union + fallback disques → retiré (exigence sans repli).  
3. **`smoothHexLosUnionFill.ts`** : union Chaikin, `throw` si échec ; option flou (`configureLosPreviewOverlaySoftEdges`) d’abord retirée du chemin actif, puis **réactivée** pour adoucir le crénelage des bords semi-transparents (voir implémentation actuelle).  
4. **Enveloppe polaire** (`losPolarEnvelopeFill.ts`, puis supprimé) : secteurs depuis le centre ; **+ masque** union hex pour respect LoS dans les goulots ; **+ traits radiaux** demandés puis retirés (lignes internes non souhaitées).  
5. Retour utilisateur : traits à l’intérieur indésirables, bord « triangle » / polaire + masque **pas** perçu comme droit → **rendu actuel = uniquement union hex lissée** (deux calques : tout visible puis couverture), sans polaire ni traits.  
6. **Bords alpha** : le léger `BlurFilter` sur le conteneur LoS améliore le lissage raster mais le contour n’est **pas** aussi « net » qu’un remplissage sans filtre — **décision produit (avril 2026) : on garde ce compromis pour l’instant**, sans autre changement prévu tant que la forme reste correcte.

## Implémentation actuelle

- **`frontend/src/utils/losPolarMaskedByVisibleUnion.ts`** — fonction **`mountLosPolarClippedByVisibleUnion`** (nom historique conservé) : appelle **`appendLosPreviewSmoothHexUnionFillOrThrow`** pour l’ensemble des hex visibles puis pour la couche couverture ; à la fin, **`configureLosPreviewOverlaySoftEdges(root, renderer)`** (paramètre optionnel `renderer` : `app.renderer` depuis **`BoardDisplay.tsx`** et **`BoardPvp.tsx`** pour un `filterArea` cohérent avec le canvas). **Aucun** remplissage polaire, **aucun** masque polaire, **aucun** trait interne.
- **`frontend/src/utils/smoothHexLosUnionFill.ts`** : Chaikin (6 passes, plafond sommets 180k), trous `beginHole` si besoin ; constantes du flou léger : `LOS_PREVIEW_OVERLAY_BLUR_STRENGTH` / `QUALITY` / `RESOLUTION` (voir fichier pour ajuster si on rouvre le sujet netteté vs. crénelage).

### Fichiers supprimés / non utilisés

- `frontend/src/utils/losPolarEnvelopeFill.ts` : **supprimé** (expérimentation polaire terminée).

## Notes

- Le bord suit le **contour lissé de l’union d’hex** (fidèle à la grille), pas des droites euclidiennes rayonnant depuis l’unité — autre compromis visuel si on reouvre le sujet « lignes depuis le centre ».
- **Netteté** : le filtre d’adoucissement sur le conteneur évite un bord trop « pixelisé » sur l’alpha au prix d’un contour un peu moins tranché ; documenté comme choix volontaire temporaire (cf. historique §6).
- Ne pas confondre avec `Documentation/TODO/10x_move_preview_form.md` (disque move masqué).
