# Replay — implémentation & registre d'état

> **But.** Source unique sur le replay (rejeu d'un `step.log` d'entraînement/PvP dans l'UI).
> Deux parties : (1) **pipeline & contrat** (comment le log devient une partie rejouable),
> (2) **registre d'état** des chantiers replay ouverts. Le code + git portent le détail ;
> ce doc porte le *contrat* et le *statut franc* (ce qui est vraiment clos vs en l'air).
>
> Faits vérifiés par lecture directe le **2026-07-23**. Toute ligne citée est à revérifier
> avant de s'y fier (le code bouge plus vite que ce doc).

---

## 1. Pipeline

```
step.log ──parse──> ReplayData ──state N──> BoardReplay ──props──> BoardPvp / UnitRenderer
(moteur)  replayParser.ts   (épisodes,      (ghost, éligibilité,   (rendu PIXI par
                             actions, states) current_player)        figurine)
```

- **Producteur** : moteur (`engine/w40k_core.py`) via `ai/step_logger.py` — mêmes helpers gym↔PvP.
- **Parseur** : `frontend/src/utils/replayParser.ts` → `ReplayData` (épisodes → `actions[]` + `states[]`).
- **Vue** : `frontend/src/components/BoardReplay.tsx` reconstruit un `GameState` par index d'action
  et le passe à `BoardPvp` (même composant que le PvP live) → `UnitRenderer`.

Indexation (`BoardReplay.getCurrentGameState`) : index `0` = état initial ; index `N` = `states[N-1]`
(état **après** l'action `N-1`). `units_cache` est reconstruit à chaque état par `buildUnitsCache`.

---

## 2. Contrat `step.log` (segments & tags)

Le parseur est **strict** : un segment/tag attendu mais absent lève une erreur (pas de fallback).
C'est voulu — une donnée manquante doit crier, pas être masquée.

### 2.1 Positions par figurine (per-figurine)
- `[MODELS: uid#idx@(col,row) …]` — positions par socle de l'unité **qui agit** (et du déploiement,
  ligne `Starting position`).
- `[TARGET_MODELS: uid#idx@(col,row) …]` — survivants de la **cible** après pertes (tir/combat).

Parsés par `extractModelsSegment` → posés sur l'unité via `occupied_hexes_by_model`
(`replayParser.ts` `applyModels` + `initial_models`). Présent → `BoardPvp`/`UnitRenderer` dessinent
**un socle par figurine** ; absent → fallback un socle à l'ancre.

### 2.2 Métadonnées fight
Chaque ligne `FIGHT : … FOUGHT …` porte **uniquement** `[FIGHT_SUBPHASE:…]` (sous-phase V11
pile_in/fight/consolidate ; parsé, requis). **Aucun pool n'est loggué** : le cercle vert en replay
cible la seule unité active, qui est déjà l'**attaquant** de la ligne (`Unit X FOUGHT …`). Le parser
en dérive `fight_eligible_units = [attacker_id]`.

> **Historique.** Avant : `[CHARGING_POOL] [ACTIVE_ALT_POOL] [NON_ACTIVE_ALT_POOL]` (pools V10, vides)
> → pool vide en replay → pas de cercle vert. Un jet intermédiaire a loggué le pool V11 complet
> (`[FIGHT_ELIGIBLE:…]`), mais il éclairait **toutes** les unités activables. Choix produit retenu :
> **seule l'unité activée** est cerclée → on ne loggue plus de pool, on dérive de l'attaquant.

---

## 3. Rendu & éligibilité (cercle vert)

Le « cercle vert autour des figs » = anneau d'**éligibilité** (`UnitRenderer.renderGreenActivationCircle`,
appelé par figurine si `isEligible && !figGhost`). L'éligibilité vient de `BoardPvp`
(`isEligibleForRenderingBase`, ~`BoardPvp.tsx:10062`) :

**Règle produit : le cercle vert cible UNIQUEMENT l'unité active** (celle qui joue l'action courante),
dans **toutes** les phases. `BoardReplay` restreint donc `eligibleUnitIds = [replayActiveUnitId]`
(id selon le type d'action : `shooter_id` pour shoot, `attacker_id` pour fight, `unit_id` sinon ;
`[]` si aucune action). Voir `replayActiveUnitId` dans `BoardReplay.tsx`.

| Phase | Source d'éligibilité en replay | Cercle vert |
|---|---|---|
| move / charge / advance / shoot | `eligibleUnitIds = [replayActiveUnitId]` filtré par `current_player` | ✅ unité active seule |
| **fight** (`FOUGHT`) | `gameState.fight_eligible_units = [attacker_id]` (branche fight de BoardPvp, §4.A) | ✅ unité active seule |
| **fight** (`pile_in`/`consolidation`) | classé `phase="move"` → `eligibleUnitIds = [unit_id]` (l'unité qui bouge) | ✅ unité active seule |

`current_player` en replay = `action.player` pour les actions move/shoot/charge/fight
(`BoardReplay.replayCurrentPlayer`), sinon `state.current_player`.

Le rendu per-figurine (occupied_hexes_by_model) ne change pas quelle **unité** est éligible — il
multiplie les socles. Le cercle vert se dessine par figurine, aux mêmes centres que les socles.

**Restriction par-figurine (tir/combat).** Une action de tir/combat ne fait souvent agir qu'une
partie de l'escouade (ex. le Nob et son Kombi Rokkit). Le moteur loggue les figs ayant réellement
tiré/frappé via le segment `[SHOOTER_MODELS: <mid> …]` (émis par `_emit_squad_shoot_log` →
`shooterModels`, source = `attacker_mid` par-modèle, PAS un match par nom d'arme). Chaîne de bout
en bout :

- **Backend** : `shared_utils._emit_squad_shoot_log` (champ `shooterModels`) →
  `w40k_core._build_shot_details` (`shooter_models_segment` via
  `action_log_utils.format_shooter_models_segment`) → `ai/step_logger` l'ajoute à la ligne.
  Le regex analyzer `\[MODELS:` ne matche pas `\[SHOOTER_MODELS:` → aucun impact analyzer.
- **Parser** : `replayParser.extractShooterModelsSegment` → `action.shooter_models` (ids seuls ;
  positions déjà dans `[MODELS:]`).
- **Rendu** : `BoardReplay.replayActiveModelIdsByUnit` → prop `BoardPvp.activeModelIdsByUnit` →
  `UnitRenderer.eligibleModelIds` : le cercle vert n'entoure QUE ces figs (absent → toute
  l'escouade éligible, comportement historique).
- **Cône LoS (tir)** : `restrictShooterCentersToActive` restreint la source du cône aux figs
  tireuses, et `BoardReplay.replayActiveShootRangeByUnit` remplace la portée max d'escouade par la
  portée de l'arme réellement tirée → le cône colle à l'arme de la fig. Une arme SPÉCIALE (ex. Kombi
  Rokkit du Nob, 24") vit sur le type de la figurine porteuse, PAS sur l'unité de base (Boyz, Shoota
  18") : la portée vient donc de `UnitFactory.getRangedWeaponRangeByDisplayName` (scan global de
  TOUTES les classes d'unités par `display_name`, en pouces) × `inches_to_subhex`, pas de
  `unit.RNG_WEAPONS`. Hors replay (props absentes), le PvP live est inchangé.

---

## 4. Registre d'état des chantiers replay

| # | Chantier | État | Prochaine action |
|---|---|---|---|
| A | Cercle vert en **phase fight** | **fait — validé unit + tsc ; visuel browser à confirmer** | Confirmer le cercle vert en fight dans un replay (§4.A) |
| B | Purge legacy pools V10 du `game_state` | **fait moteur (2026-07-23)** ; résidu front `useEngineAPI` | Nettoyer l'auto-play PvP quand validable en live (§4.B) |
| C | `pile_in` / `consolidation` classés en **phase `move`** | **fait (2026-07-23)** | — |
| — | Replay per-figurine (segments MODELS/TARGET_MODELS) | **fait** (commits `81e56c35`, `4ea850c3`) | — |
| — | Détail par-figurine (bouton +) move/advance/charge/reactive | **fait** (`4ea850c3`) | — |

### 4.A — Cercle vert fight ✅ FAIT (2026-07-23)
**Décision produit (finale).** En replay fight, le cercle vert cible **UNIQUEMENT l'unité activée**
(celle qui frappe), pas le pool des unités activables. L'unité active EST l'attaquant de la ligne
`FOUGHT` → on ne loggue aucun pool, le parser pose `fight_eligible_units = [attacker_id]`.

**Implémenté (état final) :**
1. `ai/step_logger.py` (bloc combat) : émet `[FIGHT_SUBPHASE:…]` seul (contrat = fight_subphase requis).
   Aucun pool. 3 tags legacy V10 retirés.
2. `engine/w40k_core.py` : `_pre_action_fight_state` capture `{ fight_subphase }` (pré-action, pour la
   sous-phase où l'action a lieu) ; 2 sites par-attaque posent `attack_details["fight_subphase"]` seul.
3. `frontend/src/utils/replayParser.ts` : parse `FIGHT_SUBPHASE` ; `fightStateFields =
   { fight_subphase, fight_eligible_units: [attacker_id] }`. `parsePoolTag` et le champ pool supprimés.
4. `frontend/src/components/BoardReplay.tsx` : champs pool retirés de l'interface locale.
5. Tests : `test_step_logger.py` (contrat subphase + « émet FIGHT_SUBPHASE seul, aucun pool ») ;
   `replayParser.test.ts` (fight → `fight_eligible_units === [attacker]`).

**Validation (2026-07-23).** pytest step_logger + fight_execution vert ; vitest 4/4 ; tsc propre ;
run réel : 205 lignes FOUGHT, toutes `[FIGHT_SUBPHASE]`, **0 FIGHT_ELIGIBLE**, 0 « Step logging error ».
**Reste :** confirmation visuelle browser.

> Le détail ci-dessous documente le jet intermédiaire (pool complet) conservé pour mémoire des pièges.

#### Jet intermédiaire (pool complet) — abandonné
**Cause racine.** Le pool d'activation V11 = `fight_eligible_units` (`fight_handlers.py`, écrit
`:3499`/`:5468`/`:5627`…). Le PvP live le lit (`BoardPvp.tsx:10096`). Mais `step_logger` logguait
encore les 3 pools V10 (vides) et **jamais** `fight_eligible_units` → pool `[]` en replay → pas de
cercle vert en fight.

**Correction de source vs plan initial (2 pièges découverts).**
- **Champ, pas recalcul.** Le PvP live affiche `game_state["fight_eligible_units"]` (champ maintenu).
  On loggue ce champ, pas `fight_v11_current_pool()` (le `result` combat ne le porte pas toujours).
- **Capture PRÉ-action.** L'action MUTE le pool (`end_activation` retire l'unité active). Le lire au
  drain (post-action) donnerait l'état d'après. Le chemin squad capturait déjà les pools V10 en
  pré-action (`_pre_action_fight_state`, `w40k_core.py` step()) — c'est LÀ qu'il faut poser
  `fight_eligible_units`, pas au point de log.
- **Piège swallow.** `StepLogger.log_action` avale les exceptions du formateur (`print` puis rien).
  Un premier jet qui logguait `fight_eligible_units` au mauvais endroit faisait **throw** le formateur
  → **toutes les lignes FOUGHT disparaissaient silencieusement** (log avec pile_in/consolidation mais
  0 combat). Vérifier `grep "Step logging error"` sur le run.

**Implémenté :**
1. `engine/w40k_core.py` — `_pre_action_fight_state` (step(), chemin squad V11 T6) : capture
   `{ fight_subphase, fight_eligible_units }` (pré-action) au lieu des 3 pools V10 ; injecté au
   formateur via `_build_shot_details` (`details.update(fight_state)`).
2. `engine/w40k_core.py` — 2 sites par-attaque de `_process_semantic_action` (chemin PvE/legacy, hors
   training) : `attack_details["fight_eligible_units"] = list(require_key(self.game_state, …))`
   (pool intact à ce point, avant `end_activation`).
3. `ai/step_logger.py` (bloc combat) : émet `[FIGHT_SUBPHASE:…] [FIGHT_ELIGIBLE:…]` (contrat strict) ;
   3 tags legacy retirés.
4. `frontend/src/utils/replayParser.ts` : parse `FIGHT_ELIGIBLE` → `action.fight_eligible_units` ;
   `fightStateFields = { fight_subphase, fight_eligible_units }` ; 3 champs pools retirés de l'interface.
5. `frontend/src/components/BoardReplay.tsx` : 3 champs pools retirés de l'interface locale.
6. Tests : `tests/unit/ai/test_step_logger.py` (3 cas : contrat subphase, contrat eligible, tag émis) +
   cas fight dans `frontend/src/utils/replayParser.test.ts` (+ bloc `Board:` manquant réparé).

**Sémantique du pool (conforme PvP).** Le vert suit `fight_eligible_units` = pool d'activation V11
(alternance fights-first). Il peut **exclure l'unité qui frappe** (ex. `Unit 5 FOUGHT … [FIGHT_ELIGIBLE:
102,103,104]`) : c'est le comportement PvP, où `BoardPvp.tsx:10107` supprime même le vert sur l'unité
active en cours d'activation. Le vert éclaire les unités sélectionnables pour l'activation suivante.

**Décision de contrat.** Un ancien `step.log` (sans `FIGHT_ELIGIBLE`) n'est plus rejouable →
**régénérer les logs** (conforme : donnée manquante = erreur explicite, pas de fallback).

**Validation (2026-07-23).** `pytest` step_logger + fight_execution vert ; run réel `--step` :
236 lignes FOUGHT, **toutes** avec `[FIGHT_ELIGIBLE:…]` non vide, 0 vide, 0 « Step logging error » ;
`vitest replayParser` 4/4 ; `tsc` propre. **Reste :** confirmer visuellement le cercle vert en fight
dans un replay browser (le `step.log` régénéré le permet).

### 4.B — Purge legacy V10 du `game_state` — ✅ MOTEUR FAIT (2026-07-23), résidu front
**Audit.** Les 3 pools étaient inertes en V11 : machine V10 (`fight_build_activation_pools`,
`_update_fight_subphase`, helpers alternance/consolidation) **morte** (chaîne remontant à des fonctions
sans appelant) ; seul chemin vivant = `end_activation(FIGHT)` dont le `phase_complete` dérivé des pools
vides était déjà **jeté** par le caller squad_fight.

**Fait (moteur) :**
- `generic_handlers.end_activation` : branches FIGHT (retrait pool + `pool_empty`) retirées ; tracking
  `units_fought` + step conservés. `_rebuild_alternating_pools_for_fight` supprimée.
- `fight_handlers` : 8 fonctions V10 mortes supprimées (`fight_build_activation_pools`,
  `_fight_maybe_lazy_rebuild_alternating_pools`, `_fight_post_process_fight_activation_result`,
  `_fight_try_begin_consolidation_after_attacks`, `_handle_fight_consolidation_resolution`,
  `_update_fight_subphase`, `_fight_finish_no_more_targets_after_attack`, `_toggle_fight_alternation`)
  + bloc pool mort dans `_fight_phase_complete` (`fight_phase_end` est vivant → lisait via `require_key`)
  + scrubbing V10 dans `_remove_dead_unit_from_fight_pools` (cross-phase conservé).
- Init pools retiré (`w40k_core`, `_fight_phase_complete`) ; 3 clés retirées de
  `shared_utils._remove_unit_from_all_activation_pools`.
- Tests : `test_fight_activation_pools.py` supprimé (V10) ; 3 tests V10 retirés de `test_fight_execution`
  (+ 1 réécrit sur `shoot_activation_pool`).
- **Front sûr** : `game.ts` (types) et `BoardPvp.tsx` (deps) purgés.
- Validé : grep V10 **vide** côté moteur+front(hors résidu), 97 tests moteur verts, run `--step` OK
  (FOUGHT + pile_in/conso, 0 KeyError/NameError), tsc propre.

**Résidu assumé (front)** : `useEngineAPI.ts` (~L9374-9448 et type L241-243) garde des branches
`fightSubphase === "charging"/alternating_*` **mortes en V11** (sous-phases pile_in/fight/consolidate).
Les nettoyer touche l'**auto-play PvP live** (currentPoolSize/hasMoreEligibleUnits) → non validable en
headless. À reprendre avec un test PvP fight réel, en remplaçant par `fight_eligible_units`
(déjà la source V11 vivante ailleurs dans ce hook).

### 4.C — `pile_in` / `consolidation` classés en phase `move` ✅ FAIT (2026-07-23)
Le moteur loggue déjà ces lignes `FIGHT : … PILED IN/CONSOLIDATED` (phase correcte côté log). Le bug
était **parseur-only** : la phase de l'ÉTAT était déduite par `action.type.includes("fight")`, or
`"pile_in"`/`"consolidation"` ne contiennent pas `"fight"` → classés `move`.

**Implémenté :**
1. `frontend/src/utils/replayParser.ts` : `pile_in`/`consolidation` → `phase="fight"` ; `fightStateFields`
   étendu — `fight_subphase` dérivé du type (`pile_in`/`consolidate`, exact vs moteur, non loggué sur
   ces lignes) et `fight_eligible_units = [unit_id]` (l'unité qui bouge = active).
2. `tests/unit/engine/test_squad_step_logging.py` : test obsolète réaligné (`pile_in` A un formateur,
   présent dans `_STEP_LOG_TYPE_MAP`) + nouveau `test_pile_in_is_logged_as_fight`.
3. Verrou parseur : `replayParser.test.ts` (pile_in → `phase="fight"`, `fight_eligible_units=[unit_id]`).

Validé : pytest squad_step_logging vert, vitest 5/5, tsc propre. Pas de régénération de log (parseur seul).

---

## 5. Fichiers clés

| Rôle | Fichier |
|---|---|
| Log producteur | `engine/w40k_core.py`, `ai/step_logger.py` |
| Pool fight V11 | `engine/phase_handlers/fight_handlers.py` (`fight_v11_current_pool`) |
| Parseur | `frontend/src/utils/replayParser.ts` (+ `.test.ts`) |
| Vue replay | `frontend/src/components/BoardReplay.tsx` |
| Rendu partagé | `frontend/src/components/BoardPvp.tsx`, `UnitRenderer.tsx` |
