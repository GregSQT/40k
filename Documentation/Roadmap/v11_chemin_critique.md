# V11 — Chemin critique vers la mesure de référence

Sujets : training + moteur + bot. Ordre imposé par décisions 2026-08-07/2026-08-10.
La mesure de référence (`x1_long`, 300 parties/bot) est différée jusqu'à livraison de tout ce bloc.
Dans la direction de l'index : lignes 1–4 = jalon J2, lignes 5–6 = J3, ligne 7 = J4.

---

## P3-5 — Pile-in / consolidation {#p3-5}

🟢 **Prérequis livré le 2026-08-18** : la migration par-figurine du pile-in/overrun auto (`Documentation/Implémentation/Implémenté/pile_in_overrun_par_figurine_2026-08-18.md`). P3-5 s'ouvre dès que le profil P5 est tranché ([#p5](#p5)).

Décision spatiale ⇒ top-K d'hex interdit (§9.0bis).

🔴 Le périmètre décrit en §9.4 pt 5 était FAUX (lu le 2026-08-10, `12 Fights pahse.pdf`) : le MODE de consolidation n'est pas un choix de joueur — 12.08 l'impose par la situation. Décisions réelles : consolider ou non, quelles unités ennemies, destination.
Écart aux règles identifié : le gym ne sait pas consolider vers un objectif.

→ `Documentation/Implémentation/1_Agent/V11_phaseA.md` §9.4 pt 5

---

## P3-6 — Move-after-shooting + reactive move {#p3-6}

→ `Documentation/Implémentation/1_Agent/V11_phaseA.md` §9.4 pt 6

---

## P3-8 — Optionnels à statuer {#p3-8}

Le choix d'arme en mêlée (§0.69) est déjà acté en ordre 3. Reste : split-fire, multi-cibles charge, placement final, stratégies de déploiement.
Mesurer le regret avant de trancher (§9.0bis).

🟢 **Décision 2026-08-10** : le regret se mesure sur la BASE DE DÉVELOPPEMENT en cours (§0.70), pas après la mesure de référence — un écart *relatif* (branché vs heuristique auto) supporte l'imprécision d'un run de 10 000 épisodes.

→ `Documentation/Implémentation/1_Agent/V11_phaseA.md` §9.4 pt 8

---

## P4 — Observation de support {#p4}

Features : LoS/couvert par slot ennemi, portée effective, flags advanced/fell_back.
⚠️ Ordre à ne pas prendre au pied de la lettre : ces features rendent P3-4 et P3-6 apprenables. Livrées APRÈS, elles font échouer le critère P5 pour une raison connue d'avance. Chaque feature part AVEC la tranche qui en dépend ; ce point ne garde que le reliquat.

→ `Documentation/Implémentation/1_Agent/V11_phaseA.md` §9.5

---

## P5 — Validation par tranche {#p5}

🟢 **Tranché le 2026-08-18 — commande de validation :**

```
python3 ai/train.py --agent ArmageddonAgent --training-config x1_long --resolution 1 --test-only --step
```

`--test-only` utilise `eval_episodes` (pas `bot_eval_final`, qui ne s'applique qu'à la fin d'un run d'entraînement). Les **6** profils de la config sont tous à 48 envs ; seul `x1_long` atteint la précision cible :

| profil | `total_episodes` | `bot_eval_final` | `eval_episodes` |
|---|---|---|---|
| `x1_debug` | 96 | 0 | — |
| `x5_debug` | 96 | 1 | — |
| `x1` | 10 000 | 10 | 50 |
| `x1_long` | 50 000 | 300 | **100** |

Erreur-type avec `eval_episodes = 100` : `0,707/√(6 × 100)` ≈ **2,9 pts**. Durée : ~8 min (350 épisodes à 0,72 ép./s, mesuré le 2026-08-18). Aucun profil dédié nécessaire.

→ `Documentation/Implémentation/1_Agent/V11_phaseA.md` §9.6

---

## Mesure de référence {#mesure}

`x1_long` — solde §0.14, §0.67, critère T6 (via §10.6) d'un coup.
Durée mesurée du run x1_long 50 000 épisodes : **5 h 54** (2026-08-18). L'estimation antérieure de ~20 h (fondée sur 4 h 01 pour 10 000 épisodes extrapolée × 5) était fausse — un run neuf joue des parties courtes au début, la pente n'est pas linéaire.

---

## Benchmark floor gate §4.D {#benchmark-gate}

🟢 **Livré le 2026-08-18** — détecteur de non-généralisation sur x1_long.

4 scénarios `scenario_bench-01` à `scenario_bench-04` dans `config/agents/ArmageddonAgent/scenarios/holdout_regular/` (matchups SM/SM, SM/Ork, Ork/SM, Ork/Ork) pour les 3 bots de référence `reference_balanced / reference_denial / reference_reactive`. Ajoutés à `bot_eval_weights` (poids 0,0 — hors combined) et `bot_eval_randomness` (0,0 — déterministes).

Seuil posé après mesure sur le modèle courant : `model_gating_min_benchmark_floor = 0.75` (scores mesurés : 0,99 / 1,00 / 1,00). `model_gating_enabled = true` sur x1_long uniquement.

Le gate rougit si le modèle progresse sur les 7 bots de sélection mais tombe sous 0,75 sur l'un des 3 bots de référence — signal de surapprentissage sur la distribution de sélection.

---

## Self-play §0.59 {#selfplay}

`--append x1_selfplay` — livré, **jamais exécuté** ; le premier run est aussi son premier test d'intégration.

→ `Documentation/Implémentation/1_Agent/V11_agent_rework.md` §0.59
