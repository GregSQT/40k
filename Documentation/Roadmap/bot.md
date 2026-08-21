# Bot — Tâches ouvertes

---

## 🟡 R0a — Réparation reference_* (couche déplacement/intention) {#r0a-references}

✅ **Code livré 2026-08-21** — `ai/benchmark_bots.py` + 17 tests verts.
§3.1 assignation réclamante, §3.2 tenue, §3.3 anti-empilement, §3.4 géométrie par aire.

✅ **Mesure §3.6 faite 2026-08-21** (6 ép., seed 42, board/44x60x1, holdout, 432 ép./bot) :
balanced **0,248** (avant 0,172), denial **0,269** (avant 0,151), reactive **0,264** (avant 0,120).
Gain réel de +0,08 à +0,14 par bot, mais **critère [0,40 ; 0,60] NON franchi** — les trois
restent sous 0,40. Pas de dérive des doctrine : classement à somme constante, le gain
reference_* (+0,316) est exactement le transfert des sept autres (−0,336).

⛔ **`benchmark_floor` NON reposé** : la re-pose est conditionnelle au franchissement de la
fourchette. Il reste à **0,90** ; le gate est donc toujours désaligné, comme avant la réparation.

**Reste : §3.5** — balayage des constantes d'intention (`_VP_LEAD`, ×12 de `_elect_intent`,
`_VALUE_LOSS_THRESHOLD`), un paramètre par run, 20 ép., son verrou « interdit avant 3.1-3.4 »
étant levé. Puis re-mesure §3.6, puis re-pose du gate.

→ `Documentation/Implémentation/A_faire/curriculum_adversaires_etalons.md` §3

---

## ✅ R0b — Échelle de checkpoints figés en éval {#r0b-echelle} — livré 2026-08-21

Étalon de force non saturable : win-rate du modèle courant contre les archives `robust_*`
chargeables (1 compatible au 2026-08-22 — les 5 archives pré-`charge_pair_net` lèvent
`RuntimeError Missing key(s)` au chargement et sont skippées §12.15), publié en
`bot_eval/vs_ckpt_<score>` + agrégats `00_critical/ckpt_min` et `ckpt_mean`. Hors sélection
et hors gate.

**Livrables** : `ai/bot_evaluation.py` (`discover_checkpoint_archives`, `evaluate_against_checkpoints`,
`_NormalizedFrozenModel`) + `ai/bot_registry.py` (`CHECKPOINT_OPPONENT_FAMILY`) +
`ai/metrics_tracker.py` (`log_checkpoint_evaluations`) + hook `--test-only` dans `ai/train.py` +
8 tests unitaires dans `tests/unit/ai/test_checkpoint_evaluation.py`.

**Critère rempli** : `--test-only` découvre les barreaux compatibles (1 au 2026-08-22) et publie
`vs_ckpt_<score>` pour chacun. Archives pré-`charge_pair_net` (commit d5ddffb5) : skip explicite
par tentative de chargement — `RuntimeError Missing key(s)` → message INFO §12.15 ; pkl absent
= second motif de skip.

**Amélioration 2026-08-21** : `evaluate_against_checkpoints` publie désormais `{label}_wins`,
`{label}_losses`, `{label}_draws` en plus du ratio. `log_checkpoint_evaluations` publie tous
les compteurs sous `bot_eval/vs_ckpt_*` et filtre les suffixes `_wins/_losses/_draws` hors du
calcul `ckpt_min/ckpt_mean`. Publication TensorBoard câblée via SummaryWriter dans `--test-only`.
3 tests unitaires ajoutés (commit a145b0cc).

→ `Documentation/Implémentation/A_faire/curriculum_adversaires_etalons.md` §4

---

## Étape 8 — Mesure reference bots renforcés {#etape8}

✅ Run `x1_long --new` terminé (2026-08-20), 4 critères pipeline VERTS.
✅ Reference bots renforcés : scoring 5D multi-critères (poids hardcodés, isolés de `bot_movement_weights.json`), charge denial conditionnelle à l'objectif, plan RETREAT renommé CONTEST.

✅ `bot_ranking.py` sur 9 bots × 4 scénarios × 20 ep (2026-08-20) — scores reference bots (bot-vs-bot, 1 280 ep chacun) :
- `reference_balanced` : **0,168**
- `reference_denial` : **0,155**
- `reference_reactive` : **0,139** ← min
- `benchmark_floor` posé à **0,049** (`min − 0,09`) dans `x1_long/callback_params/model_gating_min_benchmark_floor` — ⚠️ remis à **0,90** le 2026-08-20 (commit `e504d46b`) : le 0,049 venait d'un score bot-contre-bot alors que le gate lit le win-rate AGENT ; re-pose mesurée prévue en R0a ([#r0a-references](#r0a-references))

✅ Ligne de base agent rejouée sur `robust_0.8463` (2026-08-21, 100 ép./bot, panel 10 bots) :
`combined = 0,8567`, pire bot `attrition = 0,810`, pire scénario `= 0,7800`, zones T2/T5 = 1,81/1,76.
(ancienne ligne sur `robust_0.8721` : `combined = 0,7433`, pire bot `racer = 0,630` — ne charge plus)

🕳 **C.4 — Protocole jamais exécuté / benchmarks saturés (2026-08-21)**

Le protocole C.4 (`Bot_refactor.md` §C.4) exige d'évaluer ≥ 3 modèles de forces différentes contre les 3 reference bots et de mesurer la corrélation de rang + l'amplitude de chaque benchmark.

Ce protocole n'a jamais été exécuté. L'agent courant gagne à 100 % contre les trois bots `reference_*` : l'amplitude entre modèles est 0 sur ces benchmarks, quelle que soit la force du modèle testé. Par le critère écrit du doc (amplitude < incertitude d'échantillon ±5,0 pts → « le benchmark ne mesure rien »), les trois benchmarks `reference_*` **ne mesurent rien** dans leur état actuel.

Même sort que `standoff` (amplitude 0,05, supprimé le 2026-08-11). Décision de garder ou remplacer les bots `reference_*` revient à l'utilisateur.

**→ Tranché le 2026-08-21 : RÉPARATION** ([#r0a-references](#r0a-references)) — le mécanisme (intention d'abord) est gardé, la couche déplacement est réparée ; C.4 sera rejoué après R0a sur les checkpoints chargeables.

→ `Documentation/Implémentation/A_faire/bots_refonte_panel.md` (`Documentation/Implémentation/Bot_refactor.md` §7)

---

## Validation qualitative §10.6 volet 2 {#validation-externe}

**Suspendu** — requis pour la démo (jalon J5), au même titre que le quantitatif. Validation par un joueur externe.

→ `Documentation/Implémentation/1_Agent/V11_eval_strategy.md` §10.6

---

## MCTS à l'inférence §10.7 {#mcts-inference}

**Suspendu** — plan B anti-coups-absurdes, « à ne PAS anticiper » avant la mesure de référence (J3) ; ne s'ouvre que si la démo l'exige. Risque identifié : latence en démo.

Distinct du MCTS adversaire d'entraînement ([infra.md#mcts](infra.md#mcts)).

→ `Documentation/Implémentation/1_Agent/V11_eval_strategy.md` §10.7

---

## Chantier récompense distinct {#recompense}

**À cadrer — jamais ouvert.** Relevé du chantier panel (fossile, reliquat de `Bot_refactor.md` §7). Règle actée à respecter au cadrage : **un seul levier par run** — mêler récompense et adversaires rend les effets indémêlables ; le profil comportemental par adversaire (D.4, livré) doit d'abord nommer les fautes que la récompense ne punit pas.

→ `Documentation/Implémentation/Bot_refactor.md` §7

---

## Tranches 2-3 benchmark — PFSP, league, exploiters {#league}

**Différées** (E→H). Code et tests seulement ; les runs coûtent : ~200 h pour P1→P10, ~60 h pour trois exploiters.

Prérequis d'exécution : `x1_selfplay`, livré mais jamais exécuté.

Contenu : league historique, PFSP, exploiters, schedule P0→P10 (disposition disque, schéma policy.yml, câblage sur `_select_opponent_mode_for_episode`, cache LRU, sampler PFSP, protocole d'exploiter, quatre gates de promotion).

→ `Documentation/Implémentation/Bot_refactor.md` §0bis (décisions datées) et §7
