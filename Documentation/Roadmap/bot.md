# Bot — Tâches ouvertes

---

## Étape 8 — Mesure reference bots renforcés {#etape8}

✅ Run `x1_long --new` terminé (2026-08-20), 4 critères pipeline VERTS.
✅ Reference bots renforcés : scoring 5D multi-critères (poids hardcodés, isolés de `bot_movement_weights.json`), charge denial conditionnelle à l'objectif, plan RETREAT renommé CONTEST.

✅ `bot_ranking.py` sur 9 bots × 4 scénarios × 20 ep (2026-08-20) — scores reference bots (bot-vs-bot, 1 280 ep chacun) :
- `reference_balanced` : **0,168**
- `reference_denial` : **0,155**
- `reference_reactive` : **0,139** ← min
- `benchmark_floor` posé à **0,049** (`min − 0,09`) dans `x1_long/callback_params/model_gating_min_benchmark_floor`

Ligne de base agent (à battre en J3) : `combined = 0,7433`, pire bot `racer = 0,630`.
⛔ **À REJOUER** (2026-08-21) : cette ligne a été prise sur `robust_0.8721`, qui ne charge plus depuis l'ajout de `charge_pair_net` (`d5ddffb5`). L'étalon du panel est ré-épinglé sur `robust_0.8463` (`bots_refonte_panel.md` §12.15) : aucun relevé pris sur lui ne se compare à ces chiffres.

🕳 **C.4 — Protocole jamais exécuté / benchmarks saturés (2026-08-21)**

Le protocole C.4 (`Bot_refactor.md` §C.4) exige d'évaluer ≥ 3 modèles de forces différentes contre les 3 reference bots et de mesurer la corrélation de rang + l'amplitude de chaque benchmark.

Ce protocole n'a jamais été exécuté. L'agent courant gagne à 100 % contre les trois bots `reference_*` : l'amplitude entre modèles est 0 sur ces benchmarks, quelle que soit la force du modèle testé. Par le critère écrit du doc (amplitude < incertitude d'échantillon ±5,0 pts → « le benchmark ne mesure rien »), les trois benchmarks `reference_*` **ne mesurent rien** dans leur état actuel.

Même sort que `standoff` (amplitude 0,05, supprimé le 2026-08-11). Décision de garder ou remplacer les bots `reference_*` revient à l'utilisateur.

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
