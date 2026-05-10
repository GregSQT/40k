# CoreAgent — Training Logs

| Run | Épisodes | Winrate fin / peak | Score robuste | Observations | Changements appliqués |
|-----|----------|--------------------|---------------|--------------|----------------------|
| run_20260510-102947 | ~10k | 39% / 52% | ❌ | Exemple fictif (config pré-fix). | — |
| run_20260510-105020 | 10k | tier2 0.387→**0.477**→0.425 | ⚠️ | Peak eval 3 (6k ep) puis redescend légèrement. win_rate_100ep 42%/60% (forgetting plus visible sur fenêtre courte). VPdiff empire en fin. EV=0.71 correct. approx_kl ~5e-5 (updates très timides, target_kl jamais atteint). Entropie décroissante. | `ent_coef.start` 0.02 → 0.04 |
