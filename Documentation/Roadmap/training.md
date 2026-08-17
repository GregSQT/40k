# Training — Tâches ouvertes

---

## Run `--new` x1 VÉRIFICATION {#run-verif}

🔜 À lancer (décision 2026-08-11). Ce que ce run doit prouver — pas un progrès, mais que le pipeline tourne avec l'espace de décision modifié (alignement charge 11.02, distance objectif à l'aire) :

- `game_critical/invalid_action_rate` reste à **0**
- `02_combat/n_charge_success_rate` proche de **1.0**
- `02_combat/m_charge_attempts` **non nul**
- Courbes `reserves/*` et `charge_distance/*` **peuplées**

⚠️ `--new` et non `--append` : `--append` réapplique `ent_coef = 0,1` et écrase le modèle canonique.

---

## Note `bot_eval_freq_normal` à réécrire {#note-eval-freq}

La note fonde le réglage sur « 13 min l'unité » (commit `42326ed0`, jamais re-mesuré). L'évaluation finale du run du 2026-08-11 donne ~2 min 55 pour 600 épisodes — facteur ~4,5.

**À faire** : lire `perf/d_bot_eval_seconds` et `perf/e_bot_eval_episodes_per_second` du prochain run nominal (pas `--step` ni `W40K_PERF_TIMING`, qui ralentissent), réécrire la note `bot_eval_freq_normal` de `x1_long` avec ce chiffre.

---

## É9 — Second siège + second scénario {#e9}

**Suspendu** — après entraînement bot satisfaisant. Second scénario écrit par l'utilisateur (décision 2026-08-02).

→ `1_Agent/V11_agent_rework.md` §0.47
