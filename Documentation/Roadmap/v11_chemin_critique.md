# V11 — Chemin critique vers la mesure de référence

Sujets : training + moteur + bot. Ordre imposé par décisions 2026-08-07/2026-08-10.
La mesure de référence (`x1_long`, 300 parties/bot) est différée jusqu'à livraison de tout ce bloc.

---

## P3-5 — Pile-in / consolidation {#p3-5}

**Bloqué en amont** par la migration par-figurine du pile-in auto V11.
→ [moteur.md#pile-in](moteur.md#pile-in)

Décision spatiale ⇒ top-K d'hex interdit (§9.0bis).

🔴 Le périmètre décrit en §9.4 pt 5 était FAUX (lu le 2026-08-10, `12 Fights pahse.pdf`) : le MODE de consolidation n'est pas un choix de joueur — 12.08 l'impose par la situation. Décisions réelles : consolider ou non, quelles unités ennemies, destination.
Écart aux règles identifié : le gym ne sait pas consolider vers un objectif.

→ `1_Agent/V11_phaseA.md` §9.4 pt 5

---

## P3-6 — Move-after-shooting + reactive move {#p3-6}

→ `1_Agent/V11_phaseA.md` §9.4 pt 6

---

## P3-8 — Optionnels à statuer {#p3-8}

Le choix d'arme en mêlée (§0.69) est déjà acté en ordre 3. Reste : split-fire, multi-cibles charge, placement final, stratégies de déploiement.
Mesurer le regret avant de trancher (§9.0bis).

🟢 **Décision 2026-08-10** : le regret se mesure sur la BASE DE DÉVELOPPEMENT en cours (§0.70), pas après la mesure de référence — un écart *relatif* (branché vs heuristique auto) supporte l'imprécision d'un run de 10 000 épisodes.

→ `1_Agent/V11_phaseA.md` §9.4 pt 8

---

## P4 — Observation de support {#p4}

Features : LoS/couvert par slot ennemi, portée effective, flags advanced/fell_back.
⚠️ Ordre à ne pas prendre au pied de la lettre : ces features rendent P3-4 et P3-6 apprenables. Livrées APRÈS, elles font échouer le critère P5 pour une raison connue d'avance. Chaque feature part AVEC la tranche qui en dépend ; ce point ne garde que le reliquat.

→ `1_Agent/V11_phaseA.md` §9.5

---

## P5 — Validation par tranche {#p5}

🔴 **Aucun profil existant ne convient — à trancher avant d'ouvrir P3-5.**

Ce qui est acquis : `n_steps` est un TOTAL divisé par `n_envs` depuis §0.33 ⇒ la mémoire n'écarte plus aucun profil.

Ce qui casse — deux variables distinctes :

| | `total_episodes` (durée d'ENTRAÎNEMENT) | `bot_eval_final` (parties par bot de la MESURE) |
|---|---|---|
| `x1_debug` | 96 | **0** — pas d'évaluation finale |
| `x5_debug` | 96 | **1** (granularité 1/6) |
| `x1` | 10 000 | 10 |
| `x1_long` | 50 000 | 300 |

Erreur-type de l'écart entre deux win-rates `combined` (6 bots) : ≈ `0,707/√(6 × bot_eval_final)` → **2,9 pts** à `bot_eval_final = 100`.

**À faire** : un profil de validation dédié dans `ArmageddonAgent_training_config.json`. Le run `x1` de référence a pris **4 h 01** pour 10 000 épisodes.

→ `1_Agent/V11_phaseA.md` §9.6

---

## Mesure de référence {#mesure}

`x1_long` — solde §0.14, §0.67, critère T6 (via §10.6) d'un coup.
À ce régime mesuré (4 h 01 pour 10 000 épisodes), les **50 000** épisodes du profil valent ≈ **20 h**.

---

## Self-play §0.59 {#selfplay}

`--append x1_selfplay` — livré, **jamais exécuté** ; le premier run est aussi son premier test d'intégration.

→ `1_Agent/V11_agent_rework.md` §0.59
