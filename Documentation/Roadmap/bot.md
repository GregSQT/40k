# Bot — Tâches ouvertes

---

## Étape 8 — Run en cours {#etape8}

🔄 **En cours le 2026-08-17** : run `x1_long --new --resolution 1` lancé (modèle précédent incompatible obs P3-4).

**À faire à la fin** : vérifier les critères pipeline ([training.md#run-verif](training.md#run-verif)), puis `--test-only --step` pour rejouer la ligne de base du panel.

⚠️ Les chiffres des §8/§9 du doc de chantier sont à rejouer : échantillons insuffisants + erreur d'arithmétique sur le `combined` (§11.1).

Ligne de base actuelle (à battre) : `combined = 0,7433`, pire bot `racer = 0,630`.

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

## Tranches 2-3 benchmark — PFSP, league, exploiters {#league}

**Différées** (E→H). Code et tests seulement ; les runs coûtent : ~200 h pour P1→P10, ~60 h pour trois exploiters.

Prérequis d'exécution : `x1_selfplay`, livré mais jamais exécuté.

Contenu : league historique, PFSP, exploiters, schedule P0→P10 (disposition disque, schéma policy.yml, câblage sur `_select_opponent_mode_for_episode`, cache LRU, sampler PFSP, protocole d'exploiter, quatre gates de promotion).

→ `Documentation/Implémentation/Bot_refactor.md` §0bis (décisions datées) et §7
