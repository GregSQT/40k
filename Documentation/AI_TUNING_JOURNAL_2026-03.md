# AI_TUNING_JOURNAL_2026-03.md

Journal factuel des campagnes de tuning RL (mars 2026), avec decisions et criteres.

---

## 1) Contraintes non negociables

- Observation courante: **conservee** (obligation metier), aucun rollback autorise.
- Objectif tuning: corriger la **degringolade en fin de run** (drawdown) sans perdre la robustesse holdout.
- KPI de pilotage (ordre):
  1. `0_critical/b_worst_bot_score`
  2. `0_critical/c_holdout_hard_mean`
  3. `0_critical/a_bot_eval_combined`

---

## 2) Changements structurants faits pendant ce cycle

### 2.1 Forcing des unites a regles (config-driven)

- Activation d'un mecanisme de ponderation des scenarios en training selon `unit_rule_forcing`.
- Parametres ajoutables via config training:
  - `unit_rule_forcing.enabled`
  - `unit_rule_forcing.target_controlled_episode_ratio`
  - `unit_rule_forcing.max_scenario_weight`

### 2.2 Instrumentation TensorBoard forcing

- Ajouts de metriques `forcing/*` (exposition episodes, exposition par unite, delta vs debut forcing).

### 2.3 Dashboard `0_critical` enrichi

- Ajout de `0_critical/c_holdout_hard_mean`.
- Renommage/shift alphabetique pour garder l'ordre visuel coherent:
  - `c_win_rate_100ep` -> `d_win_rate_100ep`
  - `d_episode_reward_smooth` -> `e_episode_reward_smooth`
  - `e_loss_mean` -> `f_loss_mean`
  - `f_explained_variance` -> `g_explained_variance`
  - `g_clip_fraction` -> `h_clip_fraction`
  - `h_approx_kl` -> `i_approx_kl`
  - `i_entropy_loss` -> `j_entropy_loss`
  - `j_gradient_norm` -> `k_gradient_norm`
  - `k_value_trade_ratio` -> `l_value_trade_ratio`
  - `l_value_loss_smooth` -> `m_value_loss_smooth`

---

## 3) Campagnes executees

## 3.1 Sweep initial (6 runs, 30k, `default_robust_hard`)

Ratios testes:
- `0.15 / 0.45 / 0.40` (random/greedy/defensive), seeds 22345 + 32345
- `0.10 / 0.40 / 0.50`, seeds 22345 + 32345
- `0.10 / 0.45 / 0.45`, seeds 22345 + 32345

Constat principal:
- Plusieurs runs atteignent un pic eleve puis baissent en fin.
- Le meilleur candidat du lot etait la "recette run 3" (`0.10/0.40/0.50`) mais avec tendance a l'erosion tardive selon seed.

## 3.2 Verification duree 22k

- Test 22k pour verifier l'hypothese "la degradation vient surtout de la fin de training".
- Conclusion qualitative: run plus stable en fin, mais ce n'est pas la correction racine (peut etre un garde-fou temporaire).

## 3.3 Batch nuit 30k "root cause" (8 runs, `default`)

Plan execute:
- BASE x2 seeds
- LRTAIL (`learning_rate.final=2e-5`) x2 seeds
- CLIP (`clip_range=0.10`) x2 seeds
- NEPOCHS (`n_epochs=3`) x2 seeds

Runs:
- `run_20260320-140916` (BASE)
- `run_20260320-155217` (BASE)
- `run_20260320-173622` (LRTAIL)
- `run_20260320-192135` (LRTAIL)
- `run_20260320-210628` (CLIP)
- `run_20260320-225049` (CLIP)
- `run_20260321-003559` (NEPOCHS)
- `run_20260321-022235` (NEPOCHS)

Moyennes par variante (2 seeds):

| Variante | `a_combined` final | `b_worst_bot` final | `c_holdout_hard_mean` final | drawdown `a` | drawdown `b` | drawdown `c` |
|---|---:|---:|---:|---:|---:|---:|
| BASE | 0.5305 | 0.3967 | 0.5233 | -0.1888 | -0.2433 | -0.1777 |
| LRTAIL | 0.5752 | 0.4717 | 0.5467 | -0.1288 | -0.1650 | -0.1380 |
| CLIP | 0.4915 | 0.3800 | 0.4400 | -0.2297 | -0.2800 | -0.2527 |
| **NEPOCHS** | **0.6528** | **0.5400** | **0.6270** | **-0.0322** | **-0.0750** | **-0.0487** |

Conclusion factuelle:
- **`n_epochs=3` est le meilleur correctif de stabilite** sur ce batch.
- `clip_range=0.10` degrade (a eviter tel quel).
- `learning_rate.final=2e-5` ameliore vs baseline mais moins que `n_epochs=3`.

Meilleur run individuel de la campagne:
- `run_20260321-022235` (NEPOCHS + seed 32345)
  - `a_bot_eval_combined` final: `0.6830`
  - `b_worst_bot_score` final: `0.5667`
  - `c_holdout_hard_mean` final: `0.6820`

---

## 4) Decision actuelle

1. Garder l'observation actuelle (contrainte metier).
2. Adopter `model_params.n_epochs=3` comme nouvelle base de stabilite.
3. Continuer les tests incrementaux a partir de cette base (ex: + LRTAIL), 2 seeds minimum.
4. Evaluer les recettes par distribution multi-seed, pas par un run unique.

---

## 5) Points faibles scenario restants

Sur le meilleur run (`run_20260321-022235`), les plus faibles `bot_split/*` finaux sont:
- `hard_bot_04`: `0.46`
- `regular_bot_06`: `0.524`
- `hard_bot_06`: `0.572`

Pistes:
- anti-oubli cible sur cousins de ces matchups
- verification rosters associes (pression defensive + tempo)

---

## 6) Regle de decision pour prochaines campagnes

Pour une recette candidate (>= 2 seeds):

- Priorite 1: moyenne `b_worst_bot_score` finale
- Priorite 2: moyenne `c_holdout_hard_mean` finale
- Priorite 3: moyenne `a_bot_eval_combined` finale
- Garde-fou: drawdown moyen (`last-best`) doit se rapprocher de 0 (moins negatif)

Une recette est retenue si:
- elle bat la baseline sur P1/P2/P3
- et ne montre pas de seed "catastrophe" (worst final trop bas).

