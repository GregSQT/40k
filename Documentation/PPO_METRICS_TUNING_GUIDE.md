# Guide de tuning PPO - Métriques et paramètres

> **Usage** : Identifier le problème via les métriques, puis appliquer les corrections ciblées.

---

## Tableau des métriques

| Métrique | Ce que cela mesure | Pourquoi c'est important | Ce qu'il faut vérifier | Paramètres à modifier |
|----------|-------------------|---------------------------|------------------------|------------------------|
| **episode_reward_smooth** | Récompense moyenne par épisode (lissée) | Indique si l'agent maximise les récompenses configurées | Augmentation progressive et stable | Voir section Problèmes courants |
| **win_rate_100ep** | Taux de victoire sur 100 épisodes | Performance directe vs adversaire d'entraînement | Augmentation progressive | Lié à episode_reward ; si stagne → ent_coef, récompenses |
| **bot_eval_combined** | Win rate pondéré vs Random + Greedy + Defensive | **Métrique principale** – compétence réelle | > 0.55 (Phase 2), > 0.70 (Phase 3) | Si stagne ou chute → voir section Problèmes courants |
| **loss_mean** | Erreur moyenne (policy + value) | Perte trop haute ou instable = problème d'entraînement | **Tendance** : diminution progressive, pas d'oscillations brutales | learning_rate ↓ si oscille ; vf_coef ↓ si loss > 0.5 ; n_steps ↓ si instable |
| **explained_variance** | Part de la variance des returns expliquée par le value model | Qualité des prédictions de valeur | Augmentation progressive ; **cible 0.3–0.5** (pas 0.70) | learning_rate ↓ si < 0.2 ; n_steps ↑ si < 0.3 ; net_arch ↑ si reste < 0.2 |
| **clip_fraction** | Proportion des gradients clippés | Trop haut = mises à jour trop agressives ; trop bas = politique trop conservatrice | Modéré : **0.10–0.30** | learning_rate ↓ si > 0.25 ; clip_range ↑ si > 0.30 |
| **approx_kl** | Divergence entre ancienne et nouvelle politique | Trop haut = instabilité ; trop bas = apprentissage lent | Modéré : **autour de 0.01** | learning_rate ↓ si > 0.02 ; target_kl si trop bas (0.02–0.03) ou null pour désactiver early stop |
| **entropy_loss** | Diversité des actions (exploration) | Haut = exploration ; bas = exploitation | Diminution progressive vers 0, mais pas trop vite | **ent_coef ↑** si diminue trop vite (plateau) |
| **gradient_norm** | Norme des gradients | Pics = instabilité ; trop bas = apprentissage faible | Modéré, sans pics extrêmes | learning_rate ↓ si > 0.5 ; n_steps ↓ si pics |
| **immediate_reward_ratio** | Ratio récompenses immédiates / total | Équilibre court terme vs long terme | **Cible 0.5–0.7** | gamma ↓ si > 0.9 (myopie) ; récompenses : augmenter win/lose si < 0.3 |
| **reward_victory_gap** | Écart mean_reward(gagné) − mean_reward(perdu) | Alignement récompense–victoire | **20–90** = bon ; **< 10** = problème ; **> 90** = voir si apprentissage lent | win/lose ↑ ou ↓ selon cas |

---

## Problèmes courants et actions

### 1. Plateau (bot_eval stagne, win_rate plat)

**Métriques** : bot_eval_combined ~0.45–0.55, win_rate plat, episode_reward oscillant sans tendance.

| Action | Paramètre | Modification |
|--------|-----------|--------------|
| 1 | ent_coef | 0.08 → 0.10 ou 0.12 |
| 2 | learning_rate (final) | 0.00005 → 0.00008 (si decay) |
| 3 | target_kl | 0.02 → 0.03 ou null |
| 4 | net_arch | [320,320] → [512,512] (si 1–3 insuffisants) |

**Ordre** : tester 1–2–3 d’abord ; ajouter 4 seulement si pas d’amélioration.

---

### 2. Effondrement (bot_eval chute après un pic)

**Métriques** : bot_eval_combined monte puis chute fortement ; episode_reward peut continuer à monter.

| Action | Paramètre | Modification |
|--------|-----------|--------------|
| 1 | learning_rate | Réduire (ex. 0.00015 → 0.0001) ou activer decay |
| 2 | learning_rate (final) | Relever le plancher (ex. 0.00008 au lieu de 0.00005) |
| 3 | ent_coef | Augmenter pour garder de l’exploration |
| 4 | Récompenses | Vérifier que win/lose dominent (ex. ±40) |

---

### 3. Instabilité (oscillations, collapse)

**Métriques** : loss_mean oscille ; clip_fraction > 0.25 ; gradient_norm avec pics.

| Action | Paramètre | Modification |
|--------|-----------|--------------|
| 1 | learning_rate | Réduire de 30–50 % |
| 2 | n_steps | Réduire (ex. 10240 → 5120) |
| 3 | clip_range | 0.2 → 0.15 |
| 4 | target_kl | Remettre une valeur (ex. 0.02) si null |

---

### 4. Pas d’apprentissage (rewards plats)

**Métriques** : episode_reward plat ; explained_variance négative ou très basse.

| Action | Paramètre | Modification |
|--------|-----------|--------------|
| 1 | ent_coef | Augmenter (ex. 0.05 → 0.12) |
| 2 | learning_rate | Augmenter légèrement |
| 3 | Récompenses | Vérifier récompenses intermédiaires et win/lose |
| 4 | net_arch | [320,320] → [512,512] si explained_variance < 0.2 |

---

### 5. Myopie (optimise dégâts, pas la victoire)

**Métriques** : immediate_reward_ratio > 0.9 ; bot_eval bas malgré episode_reward élevé.

| Action | Paramètre | Modification |
|--------|-----------|--------------|
| 1 | Récompenses | Augmenter win/lose (ex. 20 → 40 ou 50) |
| 2 | gamma | Vérifier (0.95 adapté pour 5 tours) |
| 3 | Récompenses | Réduire récompenses intermédiaires trop fortes |

---

### 6. Overfitting à RandomBot

**Métriques** : win_rate ↑ mais bot_eval_combined ↓ ; vs_random élevé, vs_greedy/defensive bas.

| Action | Paramètre | Modification |
|--------|-----------|--------------|
| 1 | bot_training.ratios | Réduire Random (ex. 40% → 20%), augmenter Greedy/Defensive |
| 2 | Récompenses | Vérifier équilibre win/lose vs intermédiaires |

---

### 7. Récompense non alignée avec la victoire

**Métriques** : reward_victory_gap < 10 ; bot_eval bas malgré episode_reward élevé.

| Action | Paramètre | Modification |
|--------|-----------|--------------|
| 1 | Récompenses | Augmenter win/lose (ex. 40 → 50 ou 60) |
| 2 | Récompenses | Réduire récompenses intermédiaires trop fortes (kill_target, base_actions) |
| 3 | Diagnostic | Vérifier immediate_reward_ratio (< 0.9) |

---

### 8. Gap trop élevé (signal trop binaire)

**Métriques** : reward_victory_gap > 90 ; apprentissage lent ou plateau précoce.

Win/lose dominent trop → les récompenses intermédiaires deviennent négligeables. L’agent apprend peu des actions intermédiaires (position, kills, objectifs).

| Action | Paramètre | Modification |
|--------|-----------|--------------|
| 1 | Récompenses | Réduire win/lose (ex. 50 → 40) pour renforcer le signal intermédiaire |
| 2 | Récompenses | Augmenter kill_target, objective_rewards pour guider les actions |
| 3 | Diagnostic | Si bot_eval progresse bien → ne rien changer |

**Règle** : gap > 90 et apprentissage OK → ne pas modifier. Agir seulement si plateau ou apprentissage lent.

---

## Matrice : métrique → paramètres prioritaires

| Problème sur métrique | 1er paramètre | 2e paramètre | 3e paramètre |
|-----------------------|---------------|--------------|--------------|
| episode_reward stagne | ent_coef ↑ | learning_rate ↑ | Récompenses |
| win_rate stagne | ent_coef ↑ | bot_training.ratios | Récompenses |
| bot_eval stagne/chute | ent_coef ↑, lr decay | target_kl | net_arch |
| loss oscille | learning_rate ↓ | n_steps ↓ | vf_coef ↓ |
| explained_variance bas | n_steps ↑ | learning_rate ↓ | net_arch ↑ |
| clip_fraction trop haut | learning_rate ↓ | clip_range ↑ | — |
| approx_kl trop haut | learning_rate ↓ | target_kl | clip_range ↓ |
| entropy chute trop vite | ent_coef ↑ | — | — |
| gradient_norm pics | learning_rate ↓ | n_steps ↓ | — |
| immediate_ratio > 0.9 | win/lose ↑ | gamma ↓ | — |
| reward_victory_gap < 10 | win/lose ↑ | Réduire intermédiaires | immediate_ratio |
| reward_victory_gap > 90 (apprentissage lent) | win/lose ↓ | Augmenter intermédiaires | — |

---

## Règles générales

1. **Un changement à la fois** : pour isoler l’effet de chaque paramètre.
2. **Tendance > valeur absolue** : pour loss_mean et explained_variance.
3. **bot_eval_combined** : métrique principale pour ton setup.
4. **Récompenses** : win/lose doivent dominer (ex. ±40 vs récompenses intermédiaires ~1–3).
