# Métriques d'entraînement

> **Companion** : [entrainement.md](entrainement.md) — configuration et commandes.

---

## Namespaces

TensorBoard trie les groupes de tags par tri naturel *sensible à la casse* (chiffres et `/` d'abord). Les préfixes numériques imposent l'ordre affiché :

| Namespace | Contenu |
|-----------|---------|
| **`00_critical/`** | Dashboard principal — métriques PPO + évaluation bot + ventilation déploiement |
| **`01_VP/`** | Jeu de points : VP, objectifs tenus, récompenses objectives |
| **`02_combat/`** | Attrition : kills, pertes, charges, value trade |
| **`03_eval/`** | Win-rate par couple (scénario holdout, bot) — un tag par paire |
| **`bot_eval/`** | Agrégats d'évaluation bot : `vs_random`, `vs_greedy`, `vs_defensive`, `combined` |
| **`game_critical/`** | Métriques de jeu brutes (episode_reward, win_rate, episode_length, invalid_action_rate) |
| **`game_tactical/`** | Participation par phase (movement_efficiency, shooting_participation, flee_rate) |
| **`reserves/`** | Usage des réserves stratégiques (§20.01 / §20.04) |
| **`forcing/`** | Exposition aux unités avec `UNIT_RULES` |
| **`perf/`** | Coût de l'évaluation bot (durée, débit) |
| **`seat_aware/`** | Win-rate et épisodes par siège (p1/p2) |

**TensorBoard ne déplie au chargement que les 2 premiers groupes** (constante dans `webfiles.zip → index.js`). `scripts/patch_tensorboard_expand.py` porte cette constante à 3 et recalcule le `_file_hash` d'`index.html`. Redémarrer TensorBoard après le patch (le bundle est lu une seule fois au démarrage). À relancer après chaque `pip install` :

```bash
python3 scripts/patch_tensorboard_expand.py          # applique (idempotent)
python3 scripts/patch_tensorboard_expand.py --check  # vérifie l'état
```

---

## Panel de bots

Source de vérité : `ai/bot_registry.py`.

| Rôle | Bots |
|------|------|
| **Sélection** (pilotent `combined` + `worst_bot`) | random + 5 legacy (greedy, defensive, control, adaptive, value_trade) + 6 doctrine (racer, endgame, alpha, attrition, decapitation, scorer) = **12 bots** |
| **Holdout scellé** (mesuré, n'affecte pas `combined`) | tactical |
| **Benchmarks** (mesurés uniquement, exclus de la sélection) | reference_balanced, reference_denial, reference_reactive |

Les descriptions des bots doctrine sont dans `ai/bot_doctrines.py` (docstrings de classe). Ci-dessous, les trois bots legacy les plus cités dans les diagnostics :

- **RandomBot** — actions aléatoires parmi les actions légales. Référence de compétence minimale.
- **GreedyBot** — tire sur l'ennemi le plus proche. Teste la priorisation des cibles.
- **DefensiveBot** — utilise le couvert, joue prutivement. Teste le positionnement tactique.

### Namespace `03_eval/` — détail par couple

`03_eval/<scénario_holdout>/<NomDeClasseDuBot>` porte le **win-rate de ce bot sur ce scénario**, écrit par `BotEvaluationCallback._log_scenario_scores`. Un tag par couple — l'adversaire est désigné par son nom de classe réel (`DefensiveBot`, `TacticalBot`, …) et non par sa clé interne.

Les agrégats restent disponibles dans `bot_eval/scenario/<slug>/combined` et `/worst_bot_score`.

---

## Dashboard 00_critical

Le namespace **`00_critical/`** regroupe les métriques essentielles pour le tuning PPO. Toutes les métriques sont lissées (cf. section Fenêtres de lissage ci-dessous).

**Organisation** :
- **a–c** : Évaluation bot (combined, worst_bot, holdout_hard)
- **d–f** : Performance training (win_rate, episode_reward, loss_mean)
- **g–j** : Santé PPO (explained_variance, clip_fraction, approx_kl, entropy)
- **m** : Convergence du critic (value_loss)
- **n–o** : Tête d'intent (nb de free steps, dépendance intent↔contrôle)
- **o_robust** : critère de sélection du best robust model
- **p–s** : Ventilation par mode de déploiement
- **t** : Épisodes tronqués par le garde anti-runaway

Les deux dernières colonnes donnent le **seuil de déclenchement** puis le **paramètre à changer et dans quel sens**. Les paramètres vivent dans `config/agents/<Agent>/<Agent>_training_config.json`, sous `model_params` (PPO) ou `callback_params` (évaluation) ; `bot_training.ratios`, `deployment_mode_schedule` et `scenario_sampling` sont au niveau du profil.

| Metric | Target Value | ⬇️ Too low → corriger | ⬆️ Too high → corriger | What It Measures | Critical For |
|--------|--------------|----------------------|------------------------|------------------|--------------|
| **00_critical/0_eval_timeout_episodes** | 0 — **la courbe ne devrait jamais exister** | Impossible : 0 est le plancher et l'état nominal | **≥ 1** : `bot_eval_intermediate` ↓ (300 → 100, moins d'épisodes par éval) **ou** `bot_eval_task_timeout_seconds` ↑ (3600). Si récurrent malgré ça, la cause est la durée des parties (parties dégénérées × coût géodésique), pas l'éval | Nb d'épisodes d'évaluation abandonnés sur timeout de task | Fiabilité de la mesure : émis uniquement quand >0, et ce point d'éval est alors intégralement ignoré (pas de gate, pas de best model, aucune autre métrique écrite) |
| **00_critical/0_gap_p1-p2** | ≈ 0 (parité entre les sièges) | **< −0.10** (meilleur en jouant SECOND) : cas inattendu, vérifier d'abord la récompense d'objectif de fin de tour — un agent avantagé au second siège suggère que le dernier tour rapporte trop | **> +0.10** (meilleur en jouant PREMIER) : `agent_seat_mode` doit rester `random` (le forcer à `p1` supprime la mesure, pas l'écart) ; l'écart se corrige côté **training**, en vérifiant que les deux sièges sont bien joués à parts égales (`seat_aware/episodes_agent_p1` vs `_p2`) avant de toucher aux récompenses | `combined` au siège p1 − `combined` au siège p2 (même pondération que `a_bot_eval_combined`) | Symétrie de jeu. Seule métrique d'ÉVALUATION qui distingue un agent équilibré (0.75/0.75) d'un agent qui ne sait jouer que premier (1.00/0.50) : `a_bot_eval_combined` affiche 0.75 dans les deux cas. Absente si un seul siège est couvert |
| **00_critical/0_gap_sm-ork** | ≈ 0 (parité) | **< −0.15** (Orks dominants) : rééquilibrer le **training** — augmenter le poids des scénarios à roster SM dans `scenario_sampling` du split training | **> +0.15** (SM dominants) : symétrique, augmenter le poids des scénarios à roster Ork. Ne jamais corriger en retirant une faction du pool d'éval | `combined` Space Marines − `combined` Orks (même pondération que `a_bot_eval_combined`) | Spécialisation par roster. Seule métrique qui distingue un agent équilibré (0.43/0.42) d'un agent spécialisé (0.70/0.15). Absente si le pool d'éval ne couvre pas les deux factions |
| **00_critical/a_bot_eval_combined** | >0.49 (BEST actuel: 0.4857) | **< 0.49** : sortie, pas entrée — redresser d'abord `j_entropy_loss`, `h_clip_fraction`, `g_explained_variance`, puis diversifier `bot_training.ratios` | **Saut brutal** : suspecter un pool d'éval affaibli — vérifier `bot_eval_scenario_pool` (`holdout`) et croiser avec `b_worst_bot_score` et `0_gap_sm-ork` | Weighted win rate vs all holdout bots | **PRIMARY GOAL** — sélection du modèle |
| **00_critical/b_worst_bot_score** | >0.35 | **< 0.35** : augmenter la part du bot en échec dans `bot_training.ratios` (ex. `control` 0.35 → 0.45) et sa `randomness` ↓ pour un adversaire plus régulier | **≈ `a_bot_eval_combined`** : pool d'adversaires trop homogène, redistribuer `bot_training.ratios` vers les archétypes absents | Score vs le bot le plus difficile | Robustesse — pas de point faible structurel |
| **00_critical/c_holdout_hard_mean** | >0.10 (structurellement faible) | **≈ 0** : normal et structurel (matchups défavorables par construction) — n'agir que si la courbe **recule** alors que `a_bot_eval_combined` monte : sur-spécialisation sur le pool régulier | **> `a_bot_eval_combined`** : le split holdout hard n'est plus dur — revoir la composition des scénarios `holdout_hard_*` | Score moyen holdout hard (matchup défavorable) | Résilience aux matchups difficiles |
| **00_critical/ckpt_min** | Croissant | **Décroissant** : le modèle le plus fort des checkpoints figés bat davantage l'agent courant — drawdown ou sur-spécialisation | *(sans objet : ce score ne plafonne pas)* | Win-rate de l'agent courant contre le checkpoint le plus difficile (barreau minimal) — écrit par `write_ckpt_scalars`, hors sélection et hors gate | Indicateur de régression : un `ckpt_min` qui recule signifie que l'agent fait pire qu'une version antérieure de lui-même |
| **00_critical/ckpt_mean** | Croissant | **Décroissant** : l'agent courant régresse en moyenne sur l'ensemble des checkpoints figés | *(sans objet)* | Moyenne des win-rates contre tous les checkpoints figés — hors sélection et hors gate | Indicateur global de régression inter-runs |
| **00_critical/d_win_rate** (+ doublon réactif) | >0.50 | **< 0.50** : lire d'abord `j_entropy_loss` (proche de 0 = politique figée → `ent_coef` ↑) et `h_clip_fraction` ; ensuite seulement les récompenses | **> 0.85** : l'adversaire d'entraînement est trop faible, l'écart avec `a_bot_eval_combined` va se creuser — `bot_training.ratios` vers `control` / `adaptive`, `random` ↓ | Win rate lissé sur `perf_window` (500 ép.) | Performance contre l'adversaire d'entraînement |
| **00_critical/e_episode_reward_smooth** | Tendance croissante | **Plate ou décroissante** : récompenses intermédiaires trop faibles. Vérifier d'abord `p_reward_deploy_{active,auto}` : un agrégat plat sous deux séries croissantes, c'est la rampe de déploiement, pas un plafond | **Monte alors que `d_win_rate` stagne** : reward hacking — identifier la composante exploitée dans `01_VP/` et `02_combat/` avant de toucher aux coefficients | Reward d'épisode lissée sur `perf_window` | Signal d'apprentissage |
| **00_critical/f_loss_mean** | Décroissante puis stable, sans oscillations | **Basse et stable** : convergence saine, aucune action | **Oscille** : `learning_rate` ÷2, `n_steps` ↓ ; **stagne haute** : `vf_coef` ↑ (1.0 → 1.5) | `\|policy_loss\| + \|value_loss\|`, moyenné sur les 20 derniers updates | Santé globale de l'apprentissage |
| **00_critical/g_explained_variance** | >0.30 | **< 0.30** : `gamma` ↑ (0.99 → 0.98 si horizon trop long), `policy_kwargs.net_arch` ↑ (512×512 → 1024×512), `n_steps` ↑ | **> 0.95** : critic saturé — aucune action requise | Qualité du critic (R²) | Capacité du value network |
| **00_critical/h_clip_fraction** | 0.10–0.30 | **< 0.05** : politique figée → `clip_range` ↑ (0.2 → 0.25) ou `ent_coef.start` ↑ | **> 0.40** : LR trop élevé → `learning_rate.initial` ÷2, `clip_range` ↓ (0.2 → 0.15) | Part des updates de politique écrêtées | Réglage de `learning_rate` |
| **00_critical/i_approx_kl** | 0.01–0.015 (< 0.02) | **< 0.005** : apprentissage trop lent → `learning_rate.initial` ×1.5 | **> 0.02** : mise à jour trop agressive → `learning_rate.initial` ÷2 et `target_kl` fixé à 0.01–0.015 | Amplitude du changement de politique | Stabilité de la politique |
| **00_critical/j_entropy_loss** | Décroissant → −1.5 à −1.0 vers les 2/3 du run | **< −2.0 après 200 ép.** (très négatif) : trop d'exploration → `ent_coef.start` ÷2 | **> −0.5** (proche de 0) : politique déterministe → `ent_coef.start` / `.end` ↑, `decay_fraction` ↑ ; **si atteint avant 20 ép., restart obligatoire** | Niveau d'exploration — **toujours négatif** (`entropy_loss = −entropy`) | Réglage de `ent_coef` |
| **00_critical/m_value_loss_smooth** | Décroissante puis stable | **Basse et stable** : convergence saine, aucune action | **Croissante** : `learning_rate.initial` ÷2 ; **stagne haute** : `vf_coef` ↑ ou `policy_kwargs.net_arch` ↑ | Value function loss, moyennée sur les 20 derniers updates | Convergence du value network |
| **00_critical/n_intent_zone_steps** | Proche de 5 × nb de tours agent (5 = `MAX_OBJECTIVES`) | **≈ 0 alors que le run tourne** : l'agent solde ses intents dès le premier free step, ou le callback ne transmet plus `intent_value`/`zone_control` — vérifier l'écrivain avant de conclure | **Aucun plafond à corriger** : borné par `MAX_OBJECTIVES` × tours. Une hausse = parties qui s'allongent | Nb moyen de free steps zone-intent par épisode (fenêtre glissante 100 ép.) | Taille de l'échantillon qui alimente `o_intent_control_dependency` — à 0, cette courbe n'est **pas émise** (et non « nulle ») |
| **00_critical/o_intent_control_dependency** | Croissante ; 1.0 = intent entièrement déterminé par l'état | **≈ 0 avec la courbe émise** : l'intent est indépendant de l'état → `ent_coef` ↑, vérifier `combat/intent_shaping_aligned_ratio` vs `..._baseline` | **≈ 1.0** : intent entièrement déterminé — tête dégénérée en règle fixe → croiser avec `combat/intent_{invade,defend,attack}_ratio` : une marginale à ~1.0 confirme le collapse → `ent_coef` ↑ | `I(intent ; contrôle de zone) / H(contrôle)` sur fenêtre 100 ép. | La tête d'intent conditionne-t-elle sa sortie sur le plateau. **Non émise si `H(contrôle) = 0`** |
| **00_critical/o_robust_current_score** | Croissante | **Décroissant** : remonter à sa cause : `a_bot_eval_combined` qui recule (drawdown), `b_worst_bot_score` ou `c_holdout_hard_mean` qui s'effondre. Les coefficients (`robust_drawdown_penalty` 0.5, `robust_penalty_bot`, `robust_penalty_hard`, `robust_window` 5) se règlent une fois pour toutes | **Monte alors que `combined` stagne** : les pénalités ne mordent plus — `robust_penalty_bot` / `robust_penalty_hard` ↑. Toute modification rend la courbe incomparable aux runs précédents | Moyenne mobile de `combined` − pénalités (drawdown, `worst_bot`, holdout hard) | Critère de **décision** (sauvegarde du best robust model), pas de diagnostic |
| **00_critical/p_reward_deploy_{active,auto}** | Les DEUX croissantes | **Une seule série stagne** : déficit réel sur CE mode. `_active` bas → l'agent place mal ses figurines ; `_auto` bas → problème de jeu | **Les deux montent sous un agrégat plat** : rien à corriger — c'est la rampe `deployment_mode_schedule` | Reward ventilée par mode de déploiement | Sépare « l'agent stagne » de « la tâche durcit » |
| **00_critical/q_obj_held_diff_deploy_{active,auto}** | Les DEUX croissantes | Idem `p_` | Idem `p_` | Différence d'objectifs tenus, par mode | Idem sur la condition de victoire |
| **00_critical/r_win_rate_deploy_{active,auto}** | Les DEUX croissantes | Idem `p_` | Idem `p_` | Win rate par mode | Idem sur le verdict |
| **00_critical/s_deploy_active_share** | Suit la rampe du profil (0.3 → 0.8 en fin de run) | **Reste à `active_ratio_start`** : la rampe ne progresse pas — scénario hors split training, ou compteur d'épisodes qui n'avance pas (V11 §0.57 : compteur LOCAL à un env divisé par le total GLOBAL → rampe plate à `n_envs=48`) | **Proche de 1.0** : plus aucun épisode en placement fixe — `active_ratio_end` ↓ | Part réelle d'épisodes en déploiement actif | Variable explicative des trois lignes ci-dessus |
| **00_critical/t_truncated_episodes** | **0, et plat** | **Croissante** : le garde anti-runaway du moteur coupe des épisodes — une BOUCLE, pas une fin de partie. Le diagnostic est écrit ligne à ligne dans `truncations.jsonl` ; le bilan est aussi imprimé en fin de run | *(sans objet : ce compteur ne doit pas monter)* | Cumul des épisodes coupés par `_episode_step_limit` sur les épisodes d'entraînement de CE run. Un point est posé à CHAQUE fin d'épisode y compris normale. Sur un `--append`, le cumul repart de 0 | Un épisode tronqué n'entre dans AUCUNE courbe de jeu (ni reward, ni win rate) mais compte dans `episode_count` |

> **Le shaping zone-intent est DÉBRANCHÉ** (`zone_intent_shaping.enabled: false` dans le fichier de récompenses ; le code et les montants restent en place, un `true` suffit à tout rebrancher). Conséquence de lecture : `combat/intent_shaping_aligned_ratio` et son `_baseline` restent émis et gardent leur sens descriptif, mais l'écart entre les deux ne coûte ni ne rapporte plus rien. Ne pas en tirer de conclusion sur les récompenses tant que le drapeau est à `false`.

> **Deux tags en `o_`** — `o_intent_control_dependency` (diagnostic, écrit par `metrics_tracker`) et `o_robust_current_score` (décision, écrit par `training_callbacks`) partagent la lettre sans partager de sujet. Les lettres `k` et `l` sont libres : `k_gradient_norm` a été **retiré** (redondant avec `h_clip_fraction` + `i_approx_kl`), et `l` n'a jamais été attribué.

### Fenêtres de lissage

Réglées dans le training config de l'agent :

```json
"metrics_smoothing": { "perf_window": 500, "perf_window_fast": 500 }
```

La section vit dans `config/agents/_training_common.json` et chaque profil la reprend par `"metrics_smoothing": null` (idiome d'héritage). Les deux clés sont **obligatoires** : une section absente ou incomplète lève au démarrage du run, jamais de repli silencieux.

Chaque mesure des dashboards `00_critical/`, `01_VP/` et `02_combat/` peut sortir en **deux** exemplaires — le tag nu lissé sur `perf_window` (tendance de fond) et le même tag suffixé **`_<perf_window_fast>ep`** (évolution récente). Le suffixe désigne toujours la fenêtre réelle. Une fenêtre réactive plus longue que la fenêtre de fond lève.

**Le doublon réactif est désactivé** (`perf_window_fast == perf_window`) : les 21 courbes `_250ep` doublaient les trois dashboards sans être lues. Le mécanisme reste disponible — descendre `perf_window_fast` sous `perf_window` le réactive. En dessous de ~4 updates PPO, la courbe bouge parce que l'échantillon change, pas la politique (250 épisodes ≈ 4 updates sur le profil x1).

**Aucun point n'est écrit tant que la fenêtre n'est pas pleine.** Une courbe de fond démarre à l'épisode 500. Sous la fenêtre, le lissage renvoyait la moyenne de tout l'historique — une moyenne cumulative qui converge **en descendant** depuis son échantillon de départ bruité, indiscernable d'un agent qui se dégrade.

### Ventilation par mode de déploiement (`p` à `s`)

`deployment_mode_schedule` fait monter la part d'épisodes joués en déploiement **actif** de 0 % à 80 % sur la durée du run, alors que l'**évaluation impose toujours** un déploiement. La population mesurée change donc en continu.

**Lecture.** Comparer chaque paire `_active` / `_fixed` *entre elles*, jamais à l'agrégat. Deux séries croissantes sous un agrégat plat = la rampe, pas un plafond. Une seule série qui stagne = un vrai déficit, sur ce mode-là.

**Piège d'axe.** La fenêtre de lissage (`perf_window`, 500) compte 500 épisodes **de chaque mode**. Les deux courbes n'ont donc pas le même axe temporel, et `_active` démarre d'autant plus tard que `active_ratio_start` est bas (à 0.3 : ~1 700 épisodes avant que 500 d'entre eux soient actifs).

**Rien n'est émis quand le scheduler est inactif** (profil sans rampe, ou scénario hors split training).

---

## Métriques par domaine

### PPO (train/)

Ces métriques révèlent la santé de l'algorithme PPO lui-même.

#### `train/approx_kl`
**Ce que c'est :** Divergence KL entre l'ancienne et la nouvelle politique (amplitude du changement de politique).

**Interprétation :**
- **< 0.01** : Politique très conservative (peut être trop lente)
- **0.01–0.02** : Mises à jour saines (sweet spot)
- **0.02–0.03** : Changements modérés (acceptable)
- **> 0.03** : Politique changeant trop vite (risque d'instabilité)
- **> 0.05** : Politique divergeant (entraînement probablement raté)

**Déclencheurs :**
- Constamment > 0.03 → Réduire `learning_rate` de 50 %
- Constamment < 0.005 → Augmenter `learning_rate` de 50 %

---

#### `train/clip_fraction`
**Ce que c'est :** Proportion des mises à jour de politique écrêtées par le mécanisme PPO.

**Interprétation :**
- **< 10 %** : Mises à jour trop conservatives
- **10–30 %** : Écrêtage sain (PPO fonctionne correctement)
- **30–50 %** : Écrêtage élevé (politique changeant significativement)
- **> 50 %** : Écrêtage excessif (politique essaie de trop changer)

**Déclencheurs :**
- Constamment < 10 % → Augmenter `clip_range` de 0.2 à 0.25
- Constamment > 50 % → Réduire `learning_rate` et/ou `clip_range`

---

#### `train/entropy_loss`
**Ce que c'est :** Négatif de l'entropie de politique (plus bas = plus déterministe). **Toujours négatif.**

**Interprétation :**
- **−2.0 à −1.5** : Haute exploration (début d'entraînement)
- **−1.5 à −1.0** : Exploration modérée (phase d'apprentissage)
- **−1.0 à −0.5** : Faible exploration (affinage tactique)
- **−0.5 à 0.0** : Très déterministe (proche de la convergence)
- **Proche de 0 tôt** : DANGER — effondrement trop rapide, optimum local

**Déclencheurs :**
- Chute vers 0 dans les 20 premiers épisodes → Augmenter `ent_coef`, relancer
- Reste haute (< −1.5) après 200 épisodes → Réduire `ent_coef`

---

#### `train/explained_variance`
**Ce que c'est :** Dans quelle mesure la fonction de valeur prédit les returns réels (score R²).

**Interprétation :**
- **< 0.50** : Fonction de valeur très mauvaise
- **0.50–0.70** : Apprentissage mais faible
- **0.70–0.85** : Décent (acceptable pour les premières phases)
- **0.85–0.95** : Solide (bon pour les phases finales)
- **> 0.95** : Excellent (quasi-optimal)

**Déclencheurs :**
- Bloquée < 0.60 → Augmenter la taille du réseau : `net_arch` [128,128] → [256,256]
- Bloquée < 0.70 en Phase 2+ → Augmenter `vf_coef` de 0.5 à 1.0

---

#### `train/policy_loss`
**Ce que c'est :** Perte du gradient de politique (à quel point la politique s'améliore).

**Interprétation :**
- Doit **décroître dans le temps** (vers zéro)
- Grandes valeurs : la politique fait des mises à jour importantes
- Proche de zéro : la politique a convergé ou est bloquée
- Oscillante : apprentissage instable

---

#### `train/value_loss`
**Ce que c'est :** Erreur de prédiction de la fonction de valeur.

**Interprétation :**
- Doit **décroître puis se stabiliser**
- Ne décroît pas : la fonction de valeur n'apprend pas
- Augmente : la fonction de valeur se dégrade (politique changeant trop vite)

---

### VP / score (`01_VP/`)

| Métrique | Ce qu'elle mesure | Signal attendu |
|----------|-------------------|----------------|
| **01_VP/a_vp_diff** | VP agent − VP bot (différentiel) | Croissant → agent gagne le jeu de points |
| **01_VP/b_vp_agent** | VP cumulés de l'agent sur l'épisode | Croissant |
| **01_VP/c_vp_bot** | VP cumulés du bot sur l'épisode | Décroissant (ou agent > bot) |
| **01_VP/d_objectives_held_diff** | Objectifs agent − objectifs bot | Positif et croissant |
| **01_VP/e_objectives_held** | Moyenne d'objectifs contrôlés par l'agent, échantillonnée à chaque tour marquant | Croissant |
| **01_VP/f_obj_rewards** | Récompense d'objectif réellement versée sur l'épisode | Croissant avec `e_` |

**Notes techniques :**
- `e_objectives_held` / `d_objectives_held_diff` : échantillonnés par `GameStateManager._sample_objectives_held`, à l'instant exact où les VP sont attribués (4 échantillons sur une partie complète à `start_turn: 2` / `max_turns: 5`). Absentes si l'épisode se termine avant le premier tour marquant.
- `f_obj_rewards` : montant d'objectif réellement versé (`objective_reward_factor × VP marqués` **par construction**). Limite : au round 5 le second joueur marque à la fin de la phase fight alors que le reward se calcule à la frontière command → move.

---

### Combat (`02_combat/`)

| Métrique | Ce qu'elle mesure | Signal attendu |
|----------|-------------------|----------------|
| **02_combat/a_value_trade_ratio** | VALUE détruite ÷ VALUE perdue, cumulées sur la fenêtre | > 1.0 — l'agent détruit plus qu'il ne perd |
| **02_combat/b_kill_rewards** | Récompense kill_target cumulée par épisode (tir + mêlée) | Croissant |
| **02_combat/c_models_killed_ratio** | Figurines ennemies retirées / effectif ennemi de départ | Croissant, borné à 1.0 |
| **02_combat/d_models_lost_ratio** | Figurines alliées retirées / effectif allié de départ | Décroissant |
| **02_combat/e_value_killed_ratio** | VALUE ennemie détruite / VALUE ennemie de départ | Croissant, borné à 1.0 |
| **02_combat/f_value_lost_ratio** | VALUE alliée perdue / VALUE alliée de départ | Décroissant |
| **02_combat/g_shoot_model_kills** | Figurines ennemies détruites en phase de tir | Croissant |
| **02_combat/h_melee_model_kills** | Figurines ennemies détruites en phase de combat (fight) | Croissant |
| **02_combat/i_shoot_value_killed** | VALUE des figurines détruites au tir | Croissant — et plus vite que `g_` si l'agent cible ce qui coûte cher |
| **02_combat/j_melee_value_killed** | VALUE des figurines détruites en mêlée | Idem, côté mêlée |
| **02_combat/k_units_killed_ratio** | Unités ennemies éliminées / unités ennemies de départ | Croissant |
| **02_combat/l_units_lost_ratio** | Unités alliées perdues / unités alliées de départ | Décroissant ou stable |
| **02_combat/m_charge_attempts** | Charges DÉCLARÉES par l'agent (réussies + ratées) par épisode | Croissant si l'agent cherche le corps à corps |
| **02_combat/n_charge_success_rate** | Charges réussies ÷ charges déclarées, cumulées sur la fenêtre | Croissant — l'agent apprend à déclarer de plus près |
| **02_combat/o_charge_attempts_bot** | Idem `m_`, pour l'adversaire | Référence comparative |
| **02_combat/p_charge_success_rate_bot** | Idem `n_`, pour l'adversaire | Référence : le même 40 % est bon ou mauvais selon le scénario |

**Lire `m_` et `n_` ENSEMBLE.** Une mêlée absente (`h_`/`j_` bas) a deux causes opposées : un agent qui ne DÉCLARE pas de charge (`m_` bas, corriger côté récompense) ou un agent qui déclare de trop loin (`m_` haut, `n_` bas, corriger côté politique).

**`a_value_trade_ratio`** se calcule comme le **rapport des deux totaux lissés** (VALUE détruite cumulée sur 500 épisodes ÷ VALUE perdue cumulée). Son dénominateur est un résultat d'épisode : la courbe se tait seulement tant que la fenêtre ne contient aucune perte.

`n_` et `p_` : un épisode sans aucune charge déclarée n'a pas de taux — ni écarté, ni compté 0. Une fenêtre entière sans tentative n'émet aucun point.

**Ce que le couple a révélé.** Jusqu'au 2026-08-01, `charge_build_valid_plan` cherchait ses destinations **au contact du centre ennemi** au lieu de l'engagement range (2", règle 03.04) : **0 charge réussie sur 23 déclarées** sur le modèle de RUN_2, alors que l'agent choisissait la charge 70 % des fois où le masque la proposait. Après correction sans ré-entraînement : 10/15 (66,7 %).

| Tag | Ce qu'il mesure | Attendu |
|---|---|---|
| **game_tactical/movement_efficiency** | Activations de déplacement ÷ occasions (déplacements + attentes en phase move) | Proche de 1.0 |
| **game_detailed/flee_rate** | Replis (`fall_back`) ÷ occasions de déplacement | Faible |
| **game_tactical/shooting_participation** | Activations de tir ÷ occasions (tirs + attentes en phase shoot) | Croissant vers 1.0 |

**La charge n'a pas de taux de participation** : son dénominateur ne compterait pas les occasions de charger mais les fois où le moteur a exposé la phase. Quand le pool de charge est vide, aucun step n'est joué et aucun `wait` n'est journalisé.

Chaque ratio n'est émis **que si son dénominateur est > 0**.

#### Lecture combinée

**Agent focus kills mais perd les objectifs :**
- `02_combat/k_units_killed_ratio` élevé, `01_VP/a_vp_diff` négatif, `01_VP/e_objectives_held` faible
- → Augmenter `objective_reward_factor` dans rewards_config.json.

**Agent passif :**
- `g_shoot_model_kills` + `h_melee_model_kills` faibles, `b_kill_rewards` ≈ 0
- → Vérifier `ent_coef` (trop bas = politique déterministe passive)

**Agent tire mais ne tue pas :**
- `g_shoot_model_kills` ≈ 0 mais `k_units_killed_ratio` > 0 (kills en mêlée seulement)
- Vérifier les `action_logs` de type `shoot`

**Agent qui grignote au lieu de frapper ce qui compte :**
- `g_`/`h_` (nombre de figurines) élevés mais `i_`/`j_` (VALUE) plats : l'agent fauche des figurines bon marché. Le rapport `i_/g_` est la VALUE moyenne par figurine tuée.

#### Notes techniques

- `g_shoot_model_kills` / `h_melee_model_kills` / `i_shoot_value_killed` / `j_melee_value_killed` : comptés en fin d'épisode par `W40KEngine` en une passe sur `action_logs`, **par figurine** (`shootDetails[i]["targetDied"]`) — jamais sur le `target_died` d'en-tête qui vaut `kills > 0` pour tout un groupe. `all_attack_results` ne remonte jamais jusqu'à `step()` dans le pipeline squad V11 et n'est PAS une source utilisable.
- `c_models_killed_ratio` / `d_models_lost_ratio` : les effectifs de DÉPART sont posés par `build_units_cache` au reset (`game_state["model_count_at_start_by_player"]`) et jamais recalculés. Les deux courbes utilisent la MÊME mesure de chaque côté : figurines retirées du plateau (différence des survivants, pas le compte de kills du journal — qui ignore les retraits hors attaque comme le hazard 24.16).
- `enemy_value_destroyed` / `ally_value_lost` (donc `f_`, `g_`, `a_value_trade_ratio`, `e_`, `f_`) se comptent **par figurine** : valeur de départ dans `value_at_start`, survivantes sommées sur `models_cache`.
- Figurines et unités disent deux choses différentes : `c_`/`d_` comptent des figurines (une escouade de 20 entamée bouge la courbe), `k_`/`l_` comptent des escouades entièrement détruites.

---

### Évaluation (`03_eval/`, `bot_eval/`)

| Métrique | Ce que c'est | Cible | Notes |
|----------|--------------|-------|-------|
| **bot_eval/vs_random** | Win rate vs RandomBot | 0.50+ (any learning agent should beat random) | Compétence de base |
| **bot_eval/vs_greedy** | Win rate vs GreedyBot | 0.50–0.70 | Teste la priorisation des cibles |
| **bot_eval/vs_defensive** | Win rate vs DefensiveBot | 0.40–0.60 | Teste le positionnement tactique |
| **bot_eval/combined** | Moyenne pondérée de tous les bots de sélection | > 0.49 (BEST: 0.4857) → >0.55 (Phase 2) → >0.70 (Phase 3) | Métrique principale de succès |

**`03_eval/`** : un tag par couple `(scénario, classe de bot)`. Le nom du scénario (`holdout_regular_bot_01`, etc.) est un fichier de matchup de rosters, pas un adversaire.

---

### Forcing (unit-rule)

Ces métriques ne sont émises que lorsque des unités ont des entrées `UNIT_RULES` configurées.

| Métrique | Ce qu'elle mesure |
|----------|-------------------|
| `forcing/episodes_with_forced_unit_ratio` | Part d'épisodes où le roster contrôlé contient au moins une unité avec `UNIT_RULES` |
| `forcing/forced_unit_instances_mean` | Nombre moyen d'instances d'unités forcées par épisode (joueur contrôlé uniquement) |
| `forcing/episodes_with_forced_unit` | Cumul d'épisodes contenant au moins une unité forcée |
| `forcing/unit_episode_exposure/<unit_slug>` | Ratio d'exposition par unité (épisodes où cette unité est apparue / épisodes tracés) |
| `forcing/unit_instance_mean/<unit_slug>` | Instances moyennes par épisode, par unité |
| `forcing/delta_worst_bot_vs_forcing_start` | `current_worst_bot_score − baseline_worst_bot_score` (baseline = première éval bot après le début de l'exposition) |
| `forcing/delta_combined_vs_forcing_start` | `current_combined − baseline_combined` |

**Interprétation :**
- Exposition monte, `delta_worst_bot` stable ou positif → le forcing améliore ou préserve la robustesse.
- Exposition monte, `delta_worst_bot` négatif durablement → le forcing est trop agressif ou trop étroit ; rééquilibrer la diversité roster/scénario.
- Exposition concentrée sur 1–2 unités → ajuster la génération de scénarios pour couvrir plus d'unités forcées.

---

### Réserves stratégiques (`reserves/`)

Usage des réserves (règles 20.01 / 20.04), un point par épisode. **Six mesures, chacune en deux courbes** — suffixe `_agent` (joueur contrôlé) et `_opponent` (le bot).

| Métrique | Ce qu'elle mesure |
|----------|-------------------|
| `reserves/placed_{agent,opponent}` | Unités mises en réserve au déploiement. 0 et plat sur un scénario sans réserve déclarée : ce n'est pas une panne. Côté bot, la valeur ne vient QUE de la liste (le wrapper lui retire `WAIT` du pool de mise en place) |
| `reserves/deployed_{agent,opponent}` | Unités effectivement arrivées depuis la réserve. Toujours `<= placed_*` |
| `reserves/destroyed_turn3_{agent,opponent}` | Unités détruites par 20.04 (encore en réserve à la fin du 3e round). Monte quand un camp place en réserve sans faire arriver ses unités |
| `reserves/ingress_offers_{agent,opponent}` | Occasions d'arriver **réellement offertes** : couples (unité, tour) où le masque a ouvert au moins un slot d'ingress. C'est le DÉNOMINATEUR des deux courbes suivantes |
| `reserves/ingress_declined_{agent,opponent}` | Occasions offertes et **non saisies**. C'est une DÉCISION (20.03 dit « can », jamais « must ») |
| `reserves/ingress_no_destination_{agent,opponent}` | Tours où le pool d'ingress était **vide** : aucune case ne satisfaisait la bande de 6" du bord, les > 8" de tout ennemi et la fermeture de la zone adverse avant le 3e round |

**Lire l'ensemble, jamais une courbe seule.** `placed` élevé avec `deployed` bas et `destroyed_turn3` qui monte = réserve gaspillée. Le couple `declined` / `no_destination` dit à qui la faute : un `declined` élevé est un choix de l'agent (corrigible par le barème), un `no_destination` élevé est une impasse géométrique du scénario (pénaliser reviendrait à punir un choix qui n'a jamais existé).

---

### Coût d'évaluation (`perf/`)

Un point par évaluation (abscisse = `eval_marker`).

| Métrique | Ce qu'elle mesure |
|----------|-------------------|
| `perf/d_bot_eval_seconds` | Durée mur de l'évaluation |
| `perf/e_bot_eval_episodes_per_second` | Débit : épisodes réellement joués (hors abandons) par seconde. **La** courbe à lire pour régler `bot_eval_freq` |

⚠️ **Une mesure prise sous instrumentation ne règle rien.** La journalisation pas-à-pas (`--step`) et `W40K_PERF_TIMING=1` ralentissent l'évaluation. Ne comparer que des runs de même régime, et ne régler `bot_eval_freq` que sur un run nominal.

---

## Contrat `tactical_data` — aucune courbe muette en silence

`W40KMetricsTracker.log_tactical_metrics` lit **toutes** ses clés en `require_key`. Pas de `if <clé> in tactical_data`, pas de `.get()`, pas de valeur par défaut. Une clé absente **lève**, elle n'éteint pas la courbe.

Les gardes qui subsistent sont **métier** (`> 0`, liste vide) : elles disent qu'il n'y a rien à tracer sur cet épisode, pas que la donnée manque.

Le contrat est vérifié en exécution par `tests/unit/engine/test_reserves_metrics.py::test_the_engine_feeds_every_key_the_tracker_reads` — aucune liste de clés maintenue à la main.

---

## Relations entre métriques

### Corrélations fortes positives

**`explained_variance` ↑ + `ep_rew_mean` ↑** : Meilleure fonction de valeur → meilleures estimations d'avantage → meilleures mises à jour de politique. Si brisé : vérifier la capacité du réseau.

**`approx_kl` ↓ + `entropy_loss` ↓ (moins négatif)** : Politique devenant plus confiante et stable. Progression normale en entraînement réussi.

**Win rate ↑ + `bot_eval/combined` ↑** : Performance en self-play correspond à l'évaluation bot. Bon signe — généralisation, pas sur-ajustement.

### Corrélations fortes négatives

**`entropy_loss` → 0 (déterministe) + Win rate qui cesse de s'améliorer** : Politique effondrée vers le déterminisme trop tôt, bloquée dans un optimum local. Remède : augmenter `ent_coef`, relancer.

**`approx_kl` ↑ + `clip_fraction` ↑** : Politique essayant de changer trop vite trop vite. Mécanisme de sécurité PPO très actif. Remède : réduire `learning_rate`.

### Chaînes causales

**`learning_rate` → `approx_kl` → `clip_fraction`** : LR élevé → grands changements de politique (KL haut) → écrêtage. Point d'intervention : ajuster LR en premier.

**`ent_coef` → `entropy_loss` → Comportement d'exploration** : `ent_coef` élevé maintient la politique stochastique, permet de découvrir de nouvelles tactiques.

**Taille du réseau → `explained_variance` → Qualité de la politique** : Plus grand réseau → meilleures prédictions de valeur → meilleures mises à jour.

### Indicateurs avancés vs décalés

**Avancés (prédisent la performance future) :**
- `explained_variance` à l'épisode 20 : si > 0.60 → 85 % de chance de succès
- `entropy_loss` (10 premiers épisodes) : chute vers 0 → optimum local certain
- Stabilité de `approx_kl` (50 premiers épisodes) : stddev < 0.01 → convergence stable

**Décalés (confirment les tendances passées) :**
- Win rate : reflète la politique apprise 50–100 épisodes avant
- `bot_eval/combined` : n'est évalué que tous les N épisodes

---

## Patterns de diagnostic

### Bons patterns d'apprentissage

#### Phase 1 saine ✅
```
Épisodes 1–50 :
  win_rate:           20% → 30% → 40% → 45%
  explained_var:      0.30 → 0.60 → 0.75 → 0.80
  entropy_loss:       -2.0 → -1.5 → -1.2 → -0.9
  approx_kl:          0.03 → 0.02 → 0.015 → 0.010
  ep_rew_mean:        -8 → 2 → 8 → 15
```
Continuer. Passer en Phase 2 quand win rate > 60 %.

#### Phase 2 saine ✅
```
Épisodes 51–550 :
  win_rate:           45% → 58% → 67%
  vs_random:          0.55 → 0.68 → 0.78
  kill_ratio:         0.8 → 1.1 → 1.35
  explained_var:      0.80 → 0.87 → 0.92
  approx_kl:          0.015 → 0.010 → 0.008
```
Passer en Phase 3 quand win rate > 70 %.

#### Phase 3 saine ✅
```
Épisodes 551–1550 :
  win_rate:           67% → 73% → 77%
  vs_greedy:          0.45 → 0.58 → 0.67
  vs_defensive:       0.30 → 0.42 → 0.53
  combined:           0.45 → 0.56 → 0.66
  explained_var:      0.90 → 0.93 → 0.95
```
Continuer jusqu'à `combined_score` > 0.75.

### Mauvais patterns

#### Plateau ❌
```
Épisodes 20–50 :
  win_rate:       30% → 31% → 32% → 31% (BLOQUÉ)
  explained_var:  0.58 → 0.60 → 0.61 (PAS D'AMÉLIORATION)
  ep_reward:      8.5 → 8.7 → 8.9 → 8.6 (PLAT)
  approx_kl:      0.008 → 0.007 → 0.006 (TROP BAS)
```
Cause : réseau trop petit, récompenses trop éparses, LR trop bas.
Actions : 1) `net_arch` [128,128] → [256,256] ; 2) Ajouter récompenses intermédiaires ; 3) `ent_coef` ↑.

#### Oscillation ❌
```
Épisodes 300–350 :
  win_rate:       55% → 62% → 48% → 70% → 45% (SAUTS VIOLENTS)
  approx_kl:      0.025 → 0.035 → 0.042 (TROP HAUT)
  clip_fraction:  0.45 → 0.52 → 0.55 (TROP D'ÉCRÊTAGE)
```
Cause : LR trop élevé. Actions : 1) `learning_rate` ÷2 ; 2) `clip_range` 0.2 → 0.15 ; 3) `batch_size` ×2.

#### Sur-ajustement à RandomBot ❌
```
Épisodes 800–1000 :
  win_rate (self-play): 78% → 83% (EXCELLENT)
  vs_random:            0.82 → 0.86 (EXCELLENT)
  vs_greedy:            0.45 → 0.38 (EN BAISSE !)
  vs_defensive:         0.28 → 0.20 (EN BAISSE !)
  combined:             0.52 → 0.48 (EN BAISSE !)
```
Cause : surapprentissage de l'adversaire aléatoire. Actions : 1) Plus de scénarios variés ; 2) Réduire la part de `random` dans `bot_training.ratios` ; 3) Augmenter fréquence d'évaluation bot.

#### Effondrement d'entropie ❌
```
Épisodes 5–15 :
  entropy_loss:   -2.0 → -1.0 → -0.3 → -0.05 (EFFONDREMENT TROP RAPIDE)
  win_rate:       22% → 25% → 28% → 28% (BLOQUÉ)
  clip_fraction:  0.05 → 0.02 (AUCUNE EXPLORATION)
```
Cause : politique déterministe trop tôt. **Doit redémarrer** : `ent_coef` 0.01 → 0.10 ou plus.

### Patterns ambigus

#### Haute entropie, faible win rate (interprétation nécessaire)
```
Épisodes 100–150 :
  entropy_loss:   -1.8 → -1.7 → -1.9 (RESTE HAUTE)
  win_rate:       35% → 36% → 34% → 37% (BAS, PLAT)
  explained_var:  0.72 → 0.74 → 0.78 (EN AMÉLIORATION)
```
- **Scenario A (bien)** : la fonction de valeur s'améliore → l'agent apprend → attendre 50 épisodes.
- **Scenario B (mauvais)** : politique trop aléatoire pour exécuter des tactiques cohérentes → réduire `ent_coef`.

Pour distinguer : vérifier que `explained_variance` s'améliore (Scenario A) ou que `episode_length` est très variable (Scenario B).

---

## Guide d'optimisation

### Monitoring quotidien (5 minutes)

1. Ouvrir TensorBoard : `tensorboard --logdir ./tensorboard/` → http://localhost:6006
2. Vérifier **`00_critical/`** — toutes les métriques en tendance correcte ?
3. Vérifier `bot_eval/combined` — objectif primaire.
4. Si drapeau rouge → suivre l'arbre de décision.

```
SI toutes métriques saines ET en amélioration :
    ✅ Continuer l'entraînement, vérifier demain

SI drapeau rouge détecté :
    ⚠️ Arbre de décision ci-dessous

SI cible de phase atteinte :
    ✅ Passer à la phase suivante
```

### Arbre de décision

```
DÉBUT : problème détecté

├─ Le win_rate s'améliore-t-il (même lentement) ?
│  ├─ OUI : continuer, probablement juste lent
│  └─ NON : continuer ci-dessous ↓

├─ explained_variance ?
│  ├─ < 0.60 : RÉSEAU TROP PETIT → net_arch ↑
│  └─ > 0.60 : réseau OK, continuer ↓

├─ approx_kl ?
│  ├─ moy > 0.03 : LR TROP ÉLEVÉ → learning_rate ÷2
│  ├─ moy < 0.005 : LR TROP BAS → learning_rate ×1.5
│  └─ 0.005–0.03 : LR OK, continuer ↓

├─ entropy_loss ?
│  ├─ Proche 0 dans 20 ép : ENTROPIE EFFONDRÉE → restart avec ent_coef 0.10+
│  ├─ Encore < -1.5 après 200 ép : TROP D'EXPLORATION → ent_coef ÷2
│  └─ Décroissance graduelle : OK, continuer ↓

├─ clip_fraction ?
│  ├─ moy > 50% : POLITIQUE CHANGEANT TROP VITE → LR ÷2 + clip_range ↓
│  ├─ moy < 10% : TROP CONSERVATIVE → clip_range 0.2 → 0.25
│  └─ 10–50% : OK, continuer ↓

├─ Variance de episode_reward ?
│  ├─ Haute variance (sauts > 20 pts) : POLITIQUE INSTABLE → batch_size ×2
│  └─ Faible variance : OK, continuer ↓

├─ Self-play vs bot eval ?
│  ├─ Self-play haut, bot eval bas : SURAPPRENTISSAGE → scénarios variés, récompenses
│  └─ Les deux alignés : OK, continuer ↓

└─ Si tout passe mais pas d'amélioration :
    └─ Récompenses trop éparses → ajouter récompenses intermédiaires
```

### Quand intervenir vs attendre

**Intervenir immédiatement (< 10 épisodes) si :**
- `entropy_loss` chute vers 0 dans les 10 premiers épisodes
- `approx_kl` > 0.05 constamment
- `explained_variance` < 0.30 après 20 épisodes
- Win rate < 20 % ET décroissant en Phase 1

**Intervenir bientôt (50 épisodes) si :**
- Win rate plat depuis 50 épisodes
- `explained_variance` bloquée < 0.60 depuis 50 épisodes
- `approx_kl` > 0.03 constamment depuis 50 épisodes
- Évaluation bot en baisse sur 2 évaluations consécutives

**Attendre et surveiller (100 épisodes) si :**
- Win rate s'améliorant lentement (1–2 % per 50 épisodes)
- Métriques légèrement hors de la plage idéale mais stables
- Bruit mais tendance globale positive

**Ne jamais intervenir si :**
- Toutes les métriques dans la plage saine
- Win rate s'améliorant régulièrement
- Début de phase (< 20 épisodes)

---

## Réglage des hyperparamètres

### Guide par symptôme

| Métrique | Cible | Paramètres à modifier |
|----------|-------|------------------------|
| **episode_reward stagne** | Augmentation progressive | `ent_coef` ↑ → learning_rate ↑ → Récompenses |
| **d_win_rate stagne** | Augmentation progressive | `ent_coef` ↑ → `bot_training.ratios` → Récompenses |
| **bot_eval stagne/chute** | >0.49 → >0.55 → >0.70 | `ent_coef` ↑ + lr decay → `target_kl` → `net_arch` |
| **loss oscille** | Décroissante puis stable | `learning_rate` ↓ → `n_steps` ↓ → `vf_coef` ↓ |
| **explained_variance bas** | >0.30 | `n_steps` ↑ → `learning_rate` ↓ → `net_arch` ↑ |
| **clip_fraction trop haut** | 0.10–0.30 | `learning_rate` ↓ → `clip_range` ↑ |
| **approx_kl trop haut** | 0.01–0.02 | `learning_rate` ↓ → `target_kl` → `clip_range` ↓ |
| **entropy chute trop vite** | Décroissante graduellement | `ent_coef` ↑ |
| **gradient_norm pics** | < 10 | `learning_rate` ↓ → `n_steps` ↓ |
| **immediate_ratio > 0.9** | 0.5–0.7 | win/lose ↑ → `gamma` ↓ |
| **reward_victory_gap < 10** | 20–90 | win/lose ↑ → Réduire intermédiaires |
| **reward_victory_gap > 90** (lent) | — | win/lose ↓ → Augmenter intermédiaires |

### Problèmes courants et actions

#### Plateau (bot_eval stagne, win_rate plat)

| Action | Paramètre | Modification |
|--------|-----------|--------------|
| 1 | ent_coef | 0.08 → 0.10 ou 0.12 |
| 2 | learning_rate (final) | 0.00005 → 0.00008 (si decay) |
| 3 | target_kl | 0.02 → 0.03 ou null |
| 4 | net_arch | [320,320] → [512,512] si 1–3 insuffisants |

#### Effondrement (bot_eval chute après un pic)

| Action | Paramètre | Modification |
|--------|-----------|--------------|
| 1 | learning_rate | Réduire ou activer decay |
| 2 | learning_rate (final) | Relever le plancher si besoin |
| 3 | ent_coef | Augmenter |
| 4 | Récompenses | Vérifier que win/lose dominent (±40) |

#### Instabilité (oscillations, collapse)

| Action | Paramètre | Modification |
|--------|-----------|--------------|
| 1 | learning_rate | Réduire 30–50 % |
| 2 | n_steps | 10240 → 5120 |
| 3 | clip_range | 0.2 → 0.15 |
| 4 | target_kl | Remettre 0.02 si null |

#### Pas d'apprentissage (rewards plats)

| Action | Paramètre | Modification |
|--------|-----------|--------------|
| 1 | ent_coef | 0.05 → 0.12 |
| 2 | learning_rate | Augmenter légèrement |
| 3 | Récompenses | Vérifier intermédiaires et win/lose |
| 4 | net_arch | [320,320] → [512,512] si explained_variance < 0.2 |

#### Myopie (optimise dégâts, pas la victoire)

Métriques : `immediate_reward_ratio` > 0.9 ; `bot_eval` bas.

| Action | Paramètre | Modification |
|--------|-----------|--------------|
| 1 | Récompenses | Augmenter win/lose (20 → 40 ou 50) |
| 2 | gamma | Vérifier (0.95 adapté pour 5 tours) |
| 3 | Récompenses | Réduire récompenses intermédiaires trop fortes |

#### Overfitting à RandomBot

Métriques : win_rate ↑ mais bot_eval_combined ↓ ; vs_random élevé.

| Action | Paramètre | Modification |
|--------|-----------|--------------|
| 1 | bot_training.ratios | Réduire Random (40 % → 20 %), augmenter Greedy/Defensive |
| 2 | Récompenses | Équilibre win/lose vs intermédiaires |

#### reward_victory_gap < 10

| Action | Paramètre | Modification |
|--------|-----------|--------------|
| 1 | Récompenses | Augmenter win/lose (40 → 50 ou 60) |
| 2 | Récompenses | Réduire intermédiaires trop fortes |
| 3 | Diagnostic | Vérifier immediate_reward_ratio < 0.9 |

#### Gap trop élevé (signal trop binaire)

Métriques : reward_victory_gap > 90 ; apprentissage lent.

| Action | Paramètre | Modification |
|--------|-----------|--------------|
| 1 | Récompenses | Réduire win/lose (50 → 40) |
| 2 | Récompenses | Augmenter kill_target, objective_rewards |
| 3 | Règle | Si bot_eval progresse bien → ne rien changer |

### Paramètres — effets détaillés

#### Learning Rate (`learning_rate`)

**Relation aux métriques :**
- LR élevé → `approx_kl` haut, `clip_fraction` haut, `episode_reward` instable
- LR bas → `approx_kl` bas, amélioration lente, `clip_fraction` bas

**Trop élevé (> 0.001 en Phase 2+) :**
- `approx_kl` > 0.03 fréquemment, win rate oscille ±15 %, `clip_fraction` > 50 %
- Corriger : réduire de 50 %

**Trop bas (< 0.00005) :**
- `approx_kl` < 0.005, win rate s'améliore < 1 % per 100 épisodes
- Corriger : augmenter de 50 %

**Sweet spots :** Phase 1 : 0.001 | Phase 2 : 0.0003–0.0005 | Phase 3 : 0.0001–0.0003

---

#### Entropy Coefficient (`ent_coef`)

**Relation aux métriques :**
- `ent_coef` élevé → `entropy_loss` reste négatif (< −1.0), exploration haute
- `ent_coef` bas → `entropy_loss` proche de 0, politique déterministe

**Trop élevé (> 0.30) :**
- Politique reste trop aléatoire, win rate s'améliore lentement, `entropy_loss` < −1.5 après 200 ép.
- Corriger : réduire de 50 %

**Trop bas (< 0.005) :**
- Politique déterministe trop tôt (< 50 épisodes), plateau précoce
- Corriger : augmenter à 0.05 ou relancer avec 0.10

**Sweet spots :** Phase 1 : 0.15–0.20 | Phase 2 : 0.05–0.10 | Phase 3 : 0.01–0.05

**Règle critique :** si `entropy_loss` atteint 0 dans les 20 premiers épisodes, relancer obligatoirement.

---

#### Clip Range (`clip_range`)

**Sweet spot :** 0.2 (valeur PPO standard).
- Instable → 0.15 ; Trop lent et stable → 0.25
- Ajuster `learning_rate` en premier, `clip_range` ensuite.

---

#### Network Architecture (`net_arch`)

**Trop petit :** `explained_variance` bloquée < 0.60, win rate plafonne tôt.
**Sweet spots :** Phase 1 : [128,128] ou [256,256] | Phase 2 : [256,256] | Phase 3 : [256,256] ou [320,320]

Changer la taille du réseau requiert un redémarrage (impossible de charger un ancien modèle).

---

#### Batch Size (`batch_size`)

**Sweet spots :** Phase 1 : 32–64 | Phase 2 : 64–128 | Phase 3 : 128

Grand batch = plus stable mais apprentissage plus lent.

---

#### N Steps (`n_steps`)

**Petit `n_steps` :** mises à jour fréquentes, moins d'efficacité d'échantillonnage.
**Grand `n_steps` :** mises à jour rares, meilleure attribution de crédit multi-tours.

**Sweet spots :** Phase 1 : 512–1024 | Phase 2 : 1024–2048 | Phase 3 : 2048–4096

#### Accélération : `n_envs`

| n_envs | Effet |
|--------|--------|
| 1 | Défaut |
| 2, 4, 8 | 2, 4 ou 8 processus CPU en parallèle |

Quand `n_envs > 1`, le système ajuste automatiquement `n_steps` par env pour garder le même total (ex. n_envs=4 → n_steps=2560 par env, 10240 total).

### Règles générales

1. **Un changement à la fois** pour isoler l'effet de chaque paramètre.
2. **Tendance > valeur absolue** pour `loss_mean` et `explained_variance`.
3. **`bot_eval_combined`** : métrique principale de succès.
4. **Récompenses** : win/lose doivent dominer (ex. ±40 vs intermédiaires ~1–3).

### Workflow de training (résumé)

1. **Démarrage** : surveiller `explained_variance` et `gradient_norm`. Si `explained_variance` < 0.3 → augmenter `gamma`. Si `gradient_norm` > 10 → réduire `learning_rate`.
2. **Premiers 100 ép** : ajuster `learning_rate` pour `clip_fraction` 0.1–0.3 ; garder `entropy_loss` dans 0.5–2.0.
3. **Première bot eval (~500 ép)** : si `bot_eval` < 0.4 et `immediate_ratio` > 0.9 → problème de récompenses. Si `bot_eval` < 0.4 et entropy bas → exploration.
4. **Milieu (1000+ ép)** : `d_win_rate` et `episode_reward` doivent monter. Si plateau → `ent_coef` ou curriculum.
5. **Évaluation finale** : cible `bot_eval_combined` > 0.70.

---

## Critères d'arrêt

### Arrêter (SUCCÈS)

**1. Win rate atteint :** `game_critical/win_rate` > 80 % pour 100 épisodes consécutifs.

**2. Excellence bot :** `bot_eval/vs_random` > 0.85, `bot_eval/vs_greedy` > 0.70, `bot_eval/vs_defensive` > 0.60 — TOUS simultanément.

**3. Score combiné :** `bot_eval/combined` > 0.75 ET stable pour 100 épisodes.

**4. Fonction de valeur convergée :** `explained_variance` > 0.95 ET `episode_reward` sans amélioration sur 200 épisodes. (Modèle a extrait le maximum des données d'entraînement courantes.)

### Arrêter (ÉCHEC)

**1. Aucun progrès :** win rate sous la cible de phase après 200 % des épisodes attendus. Diagnostiquer avec la Pattern Library, ajuster les hyperparamètres ou les récompenses, redémarrer.

**2. Oubli catastrophique :** win rate chute > 20 % et ne récupère pas après 100 épisodes. Redémarrer depuis le dernier bon checkpoint, réduire `learning_rate` de 50 %.

**3. Épidémie d'actions invalides :** `game_critical/invalid_action_rate` > 10 % persistant (50+ épisodes). Vérifier les logs de jeu, l'espace d'observation, les pénalités de récompense.

**4. Instabilité d'entraînement :** `approx_kl` > 0.05 pour 50+ updates consécutifs. Réduire `learning_rate` de 75 % ; si toujours instable, redémarrer avec LR plus bas.

### Continuer si TOUT est vrai

- Win rate s'améliorant (même 1–2 % per 50 épisodes)
- Performance bot en hausse ou stable
- `explained_variance` encore en amélioration (< 0.95)
- Aucun critère d'échec atteint

---

## Techniques avancées

### Analyse multi-métriques

**Score de qualité de la fonction de valeur :**
```
VF_Quality = explained_variance * (1 - |value_loss_change_rate|)
```
- > 0.80 : excellent | 0.60–0.80 : bon | < 0.60 : intervention requise

**Indice de stabilité de la politique :**
```
Stability = 1 / (1 + approx_kl_stddev * clip_fraction_stddev)
```
- > 0.80 : très stable | 0.50–0.80 : modérément stable | < 0.50 : réduire `learning_rate`

**Équilibre exploration-exploitation :**
```
Balance = -entropy_loss / max_entropy_theoretical
```
- > 0.70 : encore en exploration | 0.40–0.70 : équilibré | < 0.40 : surtout exploitation

### Analyse des tendances historiques

**Régression linéaire sur le win rate :**
1. Collecter le win_rate des 100 derniers épisodes
2. Ajuster une droite de tendance
3. Projeter 50 épisodes en avant
4. Comparer la projection à la cible de phase

```python
from sklearn.linear_model import LinearRegression

win_rates = metrics['win_rate'][-100:]
episodes = np.arange(100)
model = LinearRegression()
model.fit(episodes.reshape(-1, 1), win_rates)
projected = model.predict([[150]])[0]
```

### Indicateurs prédictifs (épisode 20)

1. **`explained_variance` à Ep 20 :** > 0.60 → 85 % de chance de succès ; < 0.40 → 20 % de chance, envisager redémarrage.
2. **Trajectoire `entropy_loss` :** décroissance graduelle → bonne voie d'exploration ; chute vers 0 → va se bloquer, redémarrer maintenant.
3. **Stabilité `approx_kl` :** stddev < 0.01 → convergera stablement ; stddev > 0.02 → oscillera, réduire LR maintenant.

---

## Études de cas

### Cas 1 : Phase 1 réussie

Config : LR=0.001, ent_coef=0.20, net_arch=[256,256]

```
Épisode 10 :  win_rate 18%, explained_var 0.35, entropy -1.9, kl 0.025 → Normal
Épisode 30 :  win_rate 32%, explained_var 0.68, entropy -1.4, kl 0.018 → Bonne progression
Épisode 50 :  win_rate 47%, explained_var 0.82, entropy -1.0, kl 0.012 → Proche cible
Épisode 70 :  win_rate 61%, vs_random 0.73, combined 0.48 → PASSER EN PHASE 2 ✅
```

Facteurs de succès : `ent_coef` 0.20 initial, `explained_variance` > 0.68 à ep 30 (succès prédit), aucune intervention requise, avancé à 70 épisodes au lieu de 2000.

### Cas 2 : Récupération d'un plateau

Config initiale : LR=0.0005, ent_coef=0.05, net_arch=[128,128]

```
Épisodes 100–200 :
  win_rate:     52% → 53% → 52% (BLOQUÉ)
  explained_var: 0.62 → 0.64 (PLATEAU)
  vs_greedy:    0.38 → 0.39 (PAS D'AMÉLIORATION)
```
Diagnostic : `explained_variance` bloquée < 0.70 → réseau trop petit.
Intervention (épisode 200) : `net_arch` [128,128] → [256,256] (redémarrage requis).

```
Épisode 50 post-restart : win_rate 58%, explained_var 0.78 (GRANDE AMÉLIORATION)
Épisode 150 :             win_rate 68%, explained_var 0.89, vs_greedy 0.66
Épisode 300 :             win_rate 74%, combined 0.63 → PHASE 3 ✅
```

Leçon : capacité du réseau critique pour Phase 2+. `explained_variance` < 0.70 après 100 épisodes = signal fort pour augmenter la taille.

### Cas 3 : Stabilisation d'une oscillation

Config initiale : LR=0.0003, ent_coef=0.10, net_arch=[256,256]

```
Épisodes 400–500 :
  win_rate:      68% → 75% → 62% → 58% (SAUTS VIOLENTS)
  approx_kl:    0.028 → 0.035 → 0.039 (TROP HAUT)
  clip_fraction: 0.48 → 0.55 → 0.58 (TROP D'ÉCRÊTAGE)
```
Diagnostic : `approx_kl` moy > 0.03 → LR trop élevé.
Intervention (épisode 500) : `learning_rate` 0.0003 → 0.00015 ; `clip_range` 0.2 → 0.15 ; `batch_size` 64 → 128.

```
Épisodes 550–650 : win_rate 71% → 77% (STABLE), kl 0.015 → 0.010, clip 0.28 → 0.23
Épisode 900 :      win_rate 79%, vs_defensive 0.58, combined 0.72
Épisode 1200 :     combined 0.78 → ENTRAÎNEMENT TERMINÉ ✅
```

Leçon : Phase 3 requiert LR plus bas pour la stabilité. `approx_kl` est le meilleur avertissement précoce d'instabilité. Plusieurs changements de paramètres peuvent agir ensemble.

---

## Référence rapide

| Symptôme | Cause probable | Première action | Paramètre |
|---------|----------------|-----------------|-----------|
| Win rate bloqué < 40 %, explained_var < 0.60 | Réseau trop petit | Augmenter réseau | `net_arch` [128,128] → [256,256] |
| Win rate oscillant ±15 % | LR trop élevé | Réduire LR 50 % | `learning_rate` ÷2 |
| Entropy proche 0 dans les 20 ép | Exploration effondrée | Relancer avec ent_coef élevé | `ent_coef` 0.10+ |
| approx_kl > 0.03 constamment | LR trop élevé | Réduire LR 50 % | `learning_rate` ÷2 |
| approx_kl < 0.005 constamment | LR trop bas | Augmenter LR 50 % | `learning_rate` ×1.5 |
| clip_fraction > 50 % | Politique changeant trop vite | Réduire LR + clip range | `learning_rate` ÷2, `clip_range` 0.15 |
| clip_fraction < 10 % | Mises à jour trop conservatives | Augmenter clip range | `clip_range` 0.25 |
| Haute variance de reward | Politique instable | Augmenter batch size | `batch_size` ×2 |
| value_loss ne décroît pas | Fonction de valeur défaillante | Augmenter VF coefficient | `vf_coef` 0.5 → 1.0 |
| Self-play bon, bot eval mauvais | Surapprentissage | Scénarios variés | Ajouter scénarios dans agent scenarios/ |
| episode_length en hausse | Trop conservative | Réduire pénalité wait | `wait` −1.0 → −0.5 |
| Entropy haute (< −1.5) tardivement | Trop d'exploration | Réduire ent_coef 50 % | `ent_coef` ÷2 |
| Win rate s'améliorant mais lent | Normal, patience | Attendre 50 épisodes | — |

**Config :** `config/agents/<agent>/<agent>_training_config.json` (model_params, callback_params) et `<agent>_rewards_config.json`.
