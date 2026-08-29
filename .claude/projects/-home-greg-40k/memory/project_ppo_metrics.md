---
name: project_ppo_metrics
description: Phase 3 distributed training — cold-start reward bias fixed (2026-08-29)
metadata:
  type: project
---

Phase 3 cold-start bug FIXED (2026-08-29).

**Root cause:** Au rollout 1 avec `--new` (ret_var=1.0), workers normalisaient raw_reward=±150 → clip à ±10, puis learner rescalait par _scale=sqrt(1)/sqrt(22500)=0.0067 → ±0.067 dans le buffer au lieu de ±1.0 (15× trop petit). Les retours GAE de win-episode devenaient NÉGATIFS → value function apprenait le mauvais signe.

**Fix:** Workers retournent maintenant `raw_rewards_seq` (brut, non normalisé) + `bootstrap_seq` (gamma*V_terminal pour les épisodes tronqués, 0.0 sinon). Le learner normalise les rewards avec `new_ret_var` APRÈS la mise à jour de VecNormalize : `clip(raw/sqrt(new_ret_var)) = ±1.0`.

**Fichiers modifiés (Phase 3 uniquement) :**
- `ai/maskable_subproc_vec_env.py` : +raw_rewards_seq, +bootstrap_seq dans le dict retourné par le worker
- `ai/patched_ppo.py` : une seule passe GAE post-update (plus de double compute_returns_and_advantage), normalisation correcte des rewards
- `ai/training_callbacks.py` : diag/ metrics maintenant écrits explicitement vers MetricsTracker.writer (TF)
- `tests/unit/ai/test_phase3_distributed_rollout.py` : 5 nouveaux tests, 27 verts

**Pourquoi:** Pour relancer un run `--new`, ce fix est indispensable. Sans lui l'agent n'apprend pas à gagner.
