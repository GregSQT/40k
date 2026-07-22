# Replay per-figurine

## Objectif
Le mode replay doit montrer **exactement** ce qui s'est passé en training/eval :
chaque **figurine** d'une escouade individuellement, pas un seul socle par escouade.

## Constat (root cause)
- Le moteur EST par-figurine ; `step.log` porte déjà `[MODELS: <unit>#<mid>@(col,row) ...]`
  sur **chaque ligne d'action** = positions des figurines de l'unité qui agit.
- Le rendu frontend multi-figurines existe déjà (BoardPvp/UnitRenderer bouclent sur
  `occupied_hexes_by_model`) — **zéro code de rendu à écrire**.
- Ce qui manque uniquement côté replay :
  1. Les lignes `Starting position` ne portent que l'ancre (pas de `[MODELS:]`).
  2. Les pertes sur la **cible** d'un tir/combat ne sont pas dans `[MODELS:]`
     (qui ne couvre que l'unité active).
  3. Le parser front (`frontend/src/utils/replayParser.ts`) ignore `[MODELS:]` et
     `buildUnitsCache` (BoardReplay) n'écrit pas `occupied_hexes_by_model`.

## Décisions d'archi
- Segment cible → **`[TARGET_MODELS:]` séparé**, PAS fusionné dans `[MODELS:]` :
  le regex analyzer `\[MODELS:` ne matche pas `[TARGET_MODELS:` → analyzer isolé,
  aucun risque de perturber son état per-fig (aliveness/résurrection).
- Rejeté : choke-point unique `destroy_model` (pas d'accès au step_logger + lignes
  séparées fausseraient l'indexation action/état du parser replay).
- Hazardous/perils : l'auto-dégât est déjà couvert par le `[MODELS:]` de l'unité →
  seuls **tir** et **combat** (dégât infligé à une AUTRE unité) ont besoin du segment cible.

## Tâches (4 fichiers) — FAIT (reste validation runtime navigateur par l'utilisateur)
Note : tout le dégât tir+combat passe par le SEUL builder `_build_shot_details` (`targetId`
dispo), donc un seul point pour le segment cible ; L5077 (move/charge/advance) non concerné.
`format_models_segment` a reçu un param `label` pour produire `[TARGET_MODELS:]`.

### Backend Python
- [x] `engine/w40k_core.py` L1439 : segment `[MODELS:]` initial injecté dans `episode_units`.
- [x] `ai/step_logger.py` L253 : `[MODELS:]` émis sur les lignes `Starting position`.
- [x] `engine/w40k_core.py` `_build_shot_details` + `_flush_squad_action_logs_to_step_logger` :
      `details["target_models_segment"]` = survivants par-fig de la cible post-pertes, EMIS
      uniquement sur le DERNIER jet visant chaque cible (règle 40K : pertes retirées en bloc APRÈS
      les attaques). Emettre sur chaque jet ferait chuter les socles dès le 1er jet, avant les
      dégâts → non conforme. Déféré : HP descend jet par jet, socles tombent à la fin de la salve.
- [x] `ai/step_logger.py` L100 : `[TARGET_MODELS:]` émis quand présent.

### Frontend TS
- [x] `frontend/src/utils/replayParser.ts` : helpers `extractModelsSegment` + `pushAction`,
      `initial_models` (déploiement), `applyModels` en phase 2 → `occupied_hexes_by_model`
      par unité snapshoté dans chaque état + l'état initial.
- [x] `frontend/src/components/BoardReplay.tsx` `buildUnitsCache` : écrit
      `occupied_hexes_by_model` dans le cache. Rendu (BoardPvp/UnitRenderer) inchangé.

### Validation
- Backend : eval `--step` OK — 64/64 `Starting position` avec `[MODELS:]`, 520 `[TARGET_MODELS:]`
  sur tir/combat, segment cible rétrécit sur pertes (ex. cible 104 : 6→4→3 figs intra-épisode).
- Analyzer : **zéro régression** (96 erreurs identiques avant/après : 2.1=53 / 2.2=18 / 2.3=23).
- Frontend : `tsc --noEmit` 0 erreur, `eslint` 0 erreur.
- **Reste** : confirmation visuelle en replay navigateur (non automatisable ici).

## Limite différée — PV partiel des figurines multi-PV en escouade
Le segment `[MODELS:]` ne loggue que la **position** (`mid@(col,row)`), jamais le PV par socle.
- Escouade 1 PV (Boyz, Intercessors) : fidèle (vivante/morte = présente/absente du segment).
- Figurine seule multi-PV (véhicule, perso) : fidèle (PV = PV d'unité, déjà suivi).
- **Escouade de plusieurs figurines à plusieurs PV chacune** (ex. 3 Nobz à 2 PV) : une figurine
  peut être blessée sans mourir ; le segment la liste toujours mais ne dit pas 1/2 PV → le socle
  entamé n'est pas distinguable. PV agrégé de l'escouade correct, mais pas le PV par socle.

### Limite de granularité (conforme aux règles, non bloquant)
Le retrait des socles cible est ATOMIQUE en fin de salve (le log ne dit pas quelle figurine meurt
à quel jet). C'est CONFORME aux règles 40K (les pertes se retirent après résolution des attaques,
pas jet par jet) — ce n'est donc pas une perte de fidélité, juste l'absence de sous-étape par-jet
qui n'existe pas dans les règles.

**Non présent dans les rosters actuels** (tout est 1 PV ou mono-figurine) → non bloquant.
**À faire si un jour un roster introduit une escouade multi-figurine multi-PV** :
ajouter le PV par-fig au segment (`mid@(col,row):hp`) côté logger + parser + **analyzer**
(le format `[MODELS:]` est lu par `ai/analyzer_perfig.py` → compat à assurer).
