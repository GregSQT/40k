# Bug — `squad_fight` : mismatch masque/commit en phase fight

Découvert le 2026-07-16 pendant V11 T6. Antérieur à T6 (vérifié par remisage git : se reproduit
avec `engine/w40k_core.py` restauré à HEAD).

## ✅ CORRIGÉ le 2026-07-16 — mais PAS comme le prompt ci-dessous le supposait

**Verdict : ce n'est PAS le masque qui mentait, c'est le COMMIT gym qui divergeait du PvP.**
Le prompt (conservé tel quel plus bas, pour mémoire) partait de l'hypothèse inverse et demandait
d'aligner le masque sur le commit ; l'investigation a établi le contraire.

- **Masque** (`_squad_is_in_fight`, shared_utils ~L6696) : « a chargé ce tour OU est en ER ».
  **CONFORME** à la règle 12.04 (« It made a charge move this turn ») et au flux PvP V11, dont
  le prédicat `fight_v11_is_eligible_to_fight` (fight_handlers ~L2856) porte le commentaire
  explicite « **Indépendant de la présence de cibles** (cas overrun : a chargé, cible détruite) ».
- **Commit** (`_process_squad_action`, branche `squad_fight`) : cherchait sa cible dans le
  **mapping de slots ennemis GELÉ du tir** (`get_enemy_slot_mapping`, top-5 figé à l'init) scoré
  par menace globale (`get_best_enemy_score_for_unit`), **sans aucun filtre de zone
  d'engagement**, et levait `ValueError` si ce mapping ne contenait plus de vivant.
- **Preuve** (instrumentation de la repro, seed 1) : squad 3 avait chargé, ses deux ennemis
  ('2' et '4') étaient morts, `in_er=False`, `enemy_slots=[None]×5`. Action **légale** (12.04),
  commit en échec.
- **Bug latent au passage** : sans filtre ER, le commit pouvait frapper un ennemi hors zone
  d'engagement — violation de 12.05.

**Fix (gym uniquement, `engine/w40k_core.py`)** : le commit adopte le prédicat du flux PvP
(`_fight_build_valid_target_pool` + `_ai_select_fight_target`, cf. `_fight_v11_resolve_attacks`),
pile-in AVANT la sélection de cible (ordre V11 : 12.02 puis 12.04), et pool vide = fight « à vide »
(0 attaque) comme en PvP, via le MÊME moteur d'allocation (0 intent déclaré → summary vide,
`done=True` — aucun dict fabriqué à la main).

**La garde `ValueError` a été SUPPRIMÉE**, contrairement à ce que demandait le prompt. Elle
interdisait un cas conforme aux règles (12.04 + overrun 12.06) et déjà accepté par le PvP : la
maintenir aurait durci le gym par rapport au PvP, ce que la règle projet proscrit. Les gardes
légitimes restent (`KeyError` escouade absente/introuvable, `RuntimeError` allocation non terminée).

**Neutralité PvP : totale** — `fight_handlers` n'est pas touché (vérifié : `git status` vide).

**Tests** : `tests/unit/engine/test_squad_fight_target_parity.py` (5 tests ; 2 vérifiés comme
échouant sur l'ancien code avec l'erreur exacte). Suite `tests/unit/` verte (1287), repro verte
sur seeds 1/2/3, `scripts/smoke_t5_bare.py` → `(A) OK | (B) OK`.

**Non traité, documenté ailleurs** :
- l'**overrun 12.06** (pile-in de réengagement) n'est pas implémenté côté gym — il n'existe qu'en
  modèle par-ancre, condamné → `A_faire/overrun.md` ;
- le masque ignore `engaged_at_fight_step_start` (12.04 « or it was engaged at the start of this
  step ») car le gym n'entre pas dans la machine V11 — mesuré :
  `(fight_subphase='pile_in', snapshot_present=False, nb_selected_to_fight=0)`. Dette V11 T6.

---

---

## PROMPT À DONNER À L'AGENT

```
[MODE NUIT]
Projet : Warhammer 40K, engine Python + React/TS/PIXI. Style : réponds en français, direct,
tutoiement. Lis les fichiers avant d'affirmer (jamais "devrait/probablement" sur le code).
Le jeu doit être 100% conforme à Documentation/40k_rules. Chaque affirmation doit être vérifiée
dans le code et/ou les règles. N'assume jamais rien. Pas de fallback, de valeur par défaut
masquant une erreur, ni de workaround : corrige la root cause.

Corrige le bug décrit dans Documentation/Implémentation/Implémenté/bug_squad_fight_mask_mismatch.md.

Repro exacte (déterministe, ~30 s) :

    source /home/greg/40k/.venv/bin/activate && python3 - <<'EOF'
    import sys, json, tempfile, pathlib; sys.path.insert(0,'.')
    import numpy as np
    from ai.unit_registry import UnitRegistry
    from engine.w40k_core import W40KEngine
    sys.path.insert(0,'scripts'); from smoke_t5_bare import MELEE_SCENARIO
    with tempfile.TemporaryDirectory() as td:
        sp = pathlib.Path(td)/"m.json"; sp.write_text(json.dumps(MELEE_SCENARIO))
        eng = W40KEngine(rewards_config="CoreAgent", training_config_name="x1_debug",
                         controlled_agent="CoreAgent", scenario_file=str(sp),
                         unit_registry=UnitRegistry(), quiet=True, gym_training_mode=True)
        eng.reset(seed=1)
        for i in range(400):
            if eng.game_state.get("game_over"): break
            m = eng.get_action_mask()
            if not m.any(): break
            eng.step(int(np.random.default_rng(1*777+i).choice(np.flatnonzero(m))))
    EOF

    → ValueError: squad_fight: aucune cible pour squad 3 — mask aurait dû l'empêcher
      (engine/w40k_core.py, dans _process_squad_action, branche squad_fight)

Le message d'erreur du moteur dit lui-même le diagnostic : le MASQUE a proposé l'action
`squad_fight` (24=charge/25=fight, cf. engine/macro_intents.py) alors que le COMMIT ne trouve
aucune cible valide. Deux prédicats divergent — c'est EXACTEMENT la famille du bug corrigé en
V11 T5 (`_get_valid_deployment_hexes` testait le chevauchement par CELLULES quand
`deploy_unit` le testait par CLEARANCE euclidien continu) : lire la tranche T5 de
Documentation/Implémentation/V11_agent_rework.md avant de commencer, le patron de fix y est.

Attendu :
- identifier les DEUX prédicats (celui du masque dans engine/action_decoder.py, celui du
  commit dans _process_squad_action / fight_handlers) et expliquer où ils divergent ;
- corriger en MIROIR STRICT (le masque doit utiliser le même prédicat que le commit), sans
  fallback ni workaround, et sans relâcher la garde du commit (l'erreur explicite doit rester) ;
- neutralité PvP à vérifier : `_process_squad_action` est gym-only (son seul appelant est
  step()), mais fight_handlers est PARTAGÉ PvP/gym — tout changement côté fight_handlers doit
  être neutre pour le flux PvP manuel (règle projet : le flux gym copie le flux PvP, jamais le
  durcir/diverger) ;
- ajouter un test qui reproduit la panne (il doit échouer sur l'ancien code) et verrouille le
  fix : tests/unit/engine/ — s'inspirer de test_deployment_clearance_parity.py, qui teste
  exactement cette parité masque↔commit pour le déploiement ;
- critère de sortie : `python3 -m pytest tests/unit/ -q` vert (baseline 1274 collectés au
  2026-07-16, aucune suppression), la repro ci-dessus passe, et `python3 scripts/smoke_t5_bare.py`
  reste `(A) OK | (B) OK`.

Ne modifie PAS : config/users.db, ai/models/**/*.zip.
```

---

## Contexte technique (relevé pendant T6, non exhaustif)

- **Site de l'erreur** : `engine/w40k_core.py`, `_process_squad_action`, branche `squad_fight` —
  la garde `raise ValueError("squad_fight: aucune cible pour squad {id} — mask aurait dû
  l'empêcher")`. La garde est SAINE (erreur explicite, pas de fallback) : c'est le masque qui
  ment, pas elle. **Ne pas la supprimer.**
- **Antériorité prouvée** : `git stash push engine/w40k_core.py` puis repro → l'erreur persiste.
  Aucun rapport avec les modifications T6 (journalisation).
- **Pourquoi les smokes ne l'attrapent pas** : `scripts/smoke_t5_bare.py` tire ses actions avec
  `np.random.default_rng(seed * 99991 + steps)`. La repro ci-dessus utilise `seed*777+i` →
  séquence d'actions différente. Le bug ne se déclenche que sur certaines séquences : seul
  `seed=1` échoue, `seed=2` et `seed=3` passent. **Un smoke vert ne prouve pas son absence.**
- **Piste à vérifier** (NON confirmée — l'agent doit l'établir lui-même) : le pool
  d'éligibilité fight et le scoring de cible du décodeur
  (`get_best_enemy_score_for_unit`, boucle de `squad_fight`, w40k_core ~L4999-5011 selon
  V11_agent_rework.md §9.4) peuvent diverger de la sélection de cible du commit — p. ex. une
  cible morte/retirée entre la construction du masque et le commit, ou un désaccord sur
  l'engagement (ER) après une consolidation/pile-in.
- **Impact** : bloque un épisode d'entraînement (exception non rattrapée). En PvP, à évaluer :
  `_process_squad_action` est gym-only, mais si le prédicat fautif vit dans `fight_handlers`,
  le PvP peut exposer une variante du même écart.

## Lien

Tranche V11 T6 : `Documentation/Implémentation/V11_agent_rework.md` (section T6-c et suivantes).
