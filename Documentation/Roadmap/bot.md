# Bot — Tâches ouvertes

---

## ✅ R0a — Réparation reference_* (couche déplacement/intention) {#r0a-references} — FERMÉ SANS FRANCHISSEMENT le 2026-08-22

> **DÉCISION 2026-08-22 — les `reference_*` sont ABANDONNÉS comme étalons de force.**
>
> R0a et R0a-bis ont bien réparé ces bots : gains réels et mesurés, de +0,08 à +0,14 par bot en
> R0a puis +0,061 / +0,039 / +0,018 en R0a-bis. **Les mesures bot-contre-bot ci-dessous restent
> valides** — ce n'est pas la réparation qui a échoué, c'est la cible qui était trop basse. Trois
> bots scriptés à 0,30 bot-contre-bot restent des adversaires que l'agent bat à 1,00 : il aurait
> fallu la fourchette [0,40 ; 0,60], et deux vagues de correctifs ont montré que les leviers de
> poids et d'intention sont épuisés bien avant. Continuer, c'était une refonte du ciblage pour un
> instrument qui resature de toute façon — deux précédents mesurés dans ce dépôt (« tactical joue
> pour gagner », désaturation de tactical re-mangée en deux semaines).
>
> **`benchmark_floor` est RETIRÉ**, pas « en attente de re-pose » : `x1_long`
> `callback_params.model_gating_min_benchmark_floor` passe de 0,90 à **0,0** (valeur d'arrêt du
> mécanisme, cf. `training_callbacks`), et `--etape` le désarme de toute façon pour la durée d'un
> run de curriculum. Ce qui sélectionne désormais est le **plancher dur de 0,55 contre le champion
> le plus récent** (cible affichée 0,60, mesure sur 300 épisodes, erreur-type 2,9 points) —
> [bot.md#league](#league). L'étalon de force non saturable reste l'échelle de checkpoints figés
> ([#r0b-echelle](#r0b-echelle)).
>
> Les `reference_*` gardent leur rôle de **couverture par style et de détection de régression**
> dans le panel ; ils ne portent plus aucun gate. Aucune action n'est en attente sur ce chantier.

✅ **Code livré 2026-08-21** — `ai/benchmark_bots.py` + 17 tests verts.
§3.1 assignation réclamante, §3.2 tenue, §3.3 anti-empilement, §3.4 géométrie par aire.

✅ **Mesure §3.6 faite 2026-08-21** (6 ép., seed 42, board/44x60x1, holdout, 432 ép./bot) :
balanced **0,248** (avant 0,172), denial **0,269** (avant 0,151), reactive **0,264** (avant 0,120).
Gain réel de +0,08 à +0,14 par bot, mais **critère [0,40 ; 0,60] NON franchi** — les trois
restent sous 0,40. Pas de dérive des doctrine : classement à somme constante, le gain
reference_* (+0,316) est exactement le transfert des sept autres (−0,336).

⛔ **`benchmark_floor` NON reposé** : la re-pose est conditionnelle au franchissement de la
fourchette. Il reste à **0,90** ; le gate est donc toujours désaligné, comme avant la réparation.
*(État au 2026-08-21. Périmé : le gate a été RETIRÉ le 2026-08-22, cf. l'encadré de tête.)*

✅ **§3.5 livré 2026-08-22** — balayage des 3 constantes d'intention (10 ép., seed 42,
board/44x60x1, holdout). Baseline AVANT COMPLÈTE (20 ép.) : balanced **0,245** / denial **0,258**
/ reactive **0,262**. Tests un par un :

| Constante | Valeur testée | balanced | denial | reactive | Verdict |
|---|---|---|---|---|---|
| `_ELECT_INTENT_SCALE` | ×20 | 0,247 | 0,263 | 0,271 | nul — ×12 retenu |
| `_VALUE_LOSS_THRESHOLD` | 1,0 | 0,242 | 0,263 | 0,271 | bruit — 3,0 retenu |
| `_VP_LEAD` | 4,0 | 0,247 | 0,260 | 0,269 | nul — 8,0 retenu |

**3 runs, max atteint 0,271 < 0,35 → condition d'abandon remplie.** Les constantes d'intention
sont inertes : le problème est dans la stratégie de ciblage/mouvement des reference bots.

⛔ **R0a fermé sans franchir [0,40 ; 0,60].** La fourchette n'est pas atteinte. La refonte du
ciblage qui aurait pu l'atteindre n'est PAS ouverte : les `reference_*` sont abandonnés comme
étalons et `benchmark_floor` est retiré (encadré de tête, 2026-08-22).

✅ **R0a-bis livré 2026-08-22** — 3 défauts de 1er ordre corrigés + calibration poids.

✅ **Correctif B livré 2026-08-22** — `_swing_score_fn` et `_denial_score_fn` migrent vers le pattern `_score_kill_now` (bonus 1000 pour kill confirmé). L'ancien critère P(kill)×VALUE+damage préférait les cibles haute-VALUE non-tuables aux cibles tuables — les bots n'éliminaient personne. 2 tests rouge/vert. Mesure d'impact à faire (scripts/bot_ranking.py --bots reference_balanced,reference_denial,reference_reactive).

**Phase 0 — distribution d'intentions** (6 ép., seed 42, board/44x60x1, holdout, APRÈS fix 2) :
balanced SCORE 64 % / KILL 16 % / PRESERVE 5 % ; reactive SCORE 82 % / CONTEST 13 % / KILL 5 %.
Hypothèse « KILL dominait par aveuglement à la portée » : CONFIRMÉE — le correctif fix 2
ramène SCORE dominant (82 %) contre une domination KILL antérieure.

**Phase 1 — 3 fixes dans `ai/benchmark_bots.py`** (+ 15 tests rouges/verts) :

- **Fix 1** — seuil d'échange de charge : `_MELEE_TRADE_FLOOR = 0,5` (motif `AlphaStrikeBot`) ;
  aucune charge si dégâts mêlée < dégâts tir × 0,5.
- **Fix 2** — élection d'intention bornée par portée : `s_kill`/`s_survive` dans `_elect_intent`
  et transition KILL de `_update_plan` ne comptent que les ennemis à distance ≤ portée + MOVE.
- **Fix 3** — contestation avec rabais d'hexes : le terme `-w_contest × distance_pleine` est
  remplacé par le rabais `_CONTEST_PULL_ENEMY = 2,0` / `_CONTEST_PULL_NEUTRAL = 1,0` incorporé
  dans la carte avant `np.minimum.reduce` (motif `_objective_terms` de `bot_doctrines`).

**Mesure intermédiaire Phase 1** (6 ép., seed 42, holdout) :
balanced **0,317** (avant 0,248), denial **0,280** (avant 0,269), reactive **0,238** (avant 0,264).
Balanced +0,069 ; denial +0,011 ; reactive −0,026 (fix 2 rend KILL plus strict, régression dans
le bruit de 6 ép.).

**Phase 2 — calibration poids** (un terme par run, doctrine en contrôle) :

| Run | Terme modifié | balanced | denial | reactive | Retenu |
|---|---|---|---|---|---|
| Run 1 | `_W_BALANCED_SCORE[4]` 2,5→3,5 | 0,329 | 0,275 | 0,234 | oui (marginal, non nuisible) |
| Run 2 | `_W_DENIAL[0]` 0,9→1,4 | 0,315 | 0,312 | 0,243 | oui (+0,037 denial) |
| Run 3 | `_W_REACTIVE_SCORE[4]` 2,5→3,5 | 0,312 | 0,315 | 0,248 | revert (bruit) |
| Run 4 | `_W_REACTIVE_CONTEST[1]` −0,1→+0,1 | 0,312 | 0,315 | 0,243 | revert (nul) |

Valeurs retenues : `_W_BALANCED_SCORE[4]` = 3,5 (date 2026-08-22, run 1 +0,012) ;
`_W_DENIAL[0]` = 1,4 (date 2026-08-22, run 2 +0,037).

**Mesure finale 20 ép.** (seed 42, board/44x60x1, holdout, 1 440 ép./bot, 2026-08-22) :
balanced **0,306** (avant R0a-bis : 0,245), denial **0,297** (avant : 0,258),
reactive **0,280** (avant : 0,262).
Gains cumulés R0a-bis : balanced +0,061 / denial +0,039 / reactive +0,018.
**Critère [0,40 ; 0,60] NON franchi.** Dérive doctrine 20 ép. : attrition 0,678 / scorer 0,665 /
decapitation 0,655 / racer 0,635 / alpha 0,590 / endgame 0,453 / tactical 0,386.

⛔ **`benchmark_floor` NON reposé** — la re-pose reste conditionnelle au franchissement de
la fourchette. Il reste à **0,90** (inerte).
*(État au 2026-08-22 avant décision. Le gate a été RETIRÉ le même jour — `x1_long` à 0,0 —
et remplacé par le plancher de 0,55 contre le champion le plus récent : encadré de tête.)*

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
- `benchmark_floor` posé à **0,049** (`min − 0,09`) dans `x1_long/callback_params/model_gating_min_benchmark_floor` — remis à **0,90** le 2026-08-20 (commit `e504d46b`) : le 0,049 venait d'un score bot-contre-bot alors que le gate lit le win-rate AGENT. ⚠️ **Fin de l'histoire, 2026-08-22 : le gate est RETIRÉ (0,0), la re-pose n'aura pas lieu** — les `reference_*` sont abandonnés comme étalons ([#r0a-references](#r0a-references))

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

**À cadrer — jamais ouvert.** Relevé du chantier panel (fossile, reliquat de `Bot_refactor.md` §7). Règle actée à respecter au cadrage : **un seul levier par run** — mêler récompense et adversaires rend les effets indémêlables ; le profil comportemental par adversaire (D.4, livré et câblé dans `BotEvalCallback._run_evaluation`) doit d'abord nommer les fautes que la récompense ne punit pas.

État du code (2026-08-24) : `_can_unit_kill_target_in_one_phase` utilise `expected_damage()` (P(hit)×P(wound)×P(sv)) — le proxy `NB×DMG` y est soldé. `_get_unit_threat` reste `NB×DMG` par design (cible inconnue à ce stade). Aucun autre défaut structurel préidentifié : le levier R3 se tranche sur les courbes D.4 de R1.

→ `Documentation/Implémentation/Bot_refactor.md` §7

---

## Tranches 2-3 benchmark — PFSP, league, exploiters {#league}

**Schedule P0→P10 + exploiters : CODE ET TESTS LIVRÉS le 2026-08-22.** Les runs restent à
jouer (~200 h pour P1→P10, ~60 h pour trois exploiters), un par commande `--etape`.

Livré : `config/agents/ArmageddonAgent/curriculum.json` (14 étapes P0..P10 + E1..E3),
`ai/curriculum.py`, `--etape` dans `ai/train.py`, `opponent_mix.pool` (liste pondérée
d'adversaires figés) à la place de `snapshot_model_path`.

Trois écarts assumés par rapport au contenu prévu :

- **Pas de sampler PFSP ni de cache LRU.** Le pool est réalisé par la répartition des
  ENVIRONNEMENTS : chaque worker reçoit un membre et le charge une fois. Un tirage par épisode
  aurait imposé de garder les treize membres du plus gros pool vivants dans chacun des
  quarante-huit processus ; la répartition par-env donne les mêmes proportions pour l'empreinte
  mémoire d'aujourd'hui (un `_frozen_model` par processus).
- **Pas de `policy.yml`.** Le schéma vit dans `curriculum.json`, à côté des autres configs
  d'agent.
- **Un seul gate de promotion**, pas quatre : plancher dur de 0,55 sur le score contre le
  champion le plus récent (cible affichée 0,60, mesure sur 300 épisodes, erreur-type 2,9
  points). `benchmark_floor` est désarmé pendant une étape — il compare le pire score aux bots
  de référence, saturés à 1,00, donc il ne sépare rien. La monotonie du pool est journalisée en
  DIAGNOSTIC et non en gate : les learners démarrent `--new`, donc deux étapes voisines sont
  des runs indépendants et peuvent se départager dans le désordre sans anomalie.

→ `Documentation/Implémentation/Bot_refactor.md` §0bis (décisions datées) et §7
