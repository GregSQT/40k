# Archives Training

| Date | Chantier | Détail |
|---|---|---|
| 2026-09-08 | ✅ **Obs — canaux « zone obscurante » et « exposition »** | (`GRID_CHANNELS` 9→11, porté à **12** depuis par la verticalité du move gym) — **mergé le 2026-09-08** (`dd8a24be`) ; `obs_size` ne bouge pas, la grille étant fournie à part, mais la forme d'entrée du CNN change : **`--new` obligatoire** pour tout modèle antérieur — section conservée ci-dessous : [training.md#canaux-obscurant-exposition](training.md#canaux-obscurant-exposition) |
| 2026-09-08 | ✅ **Obs — `hidden` 13.09 sur toutes les entités + porte de détection** | `los_can_see` = visible ET détectable ; mergé le 2026-09-08, `obs_size` inchangé (16811), aucun `--new` propre — section conservée ci-dessous : [training.md#hidden-detection-obs](training.md#hidden-detection-obs) |
| 2026-09-09 | ✅ **Obs — CONTEXTE des points d'arrêt à deux temps** | sélection d'arme de mêlée (§0.69) et sous-état CIBLE du tir fractionné (P3-8) demandaient un choix dont la moitié déjà fixée — la cible pour l'un, l'arme pour l'autre — n'était PAS observée : deux états ne différant que par elle rendaient des observations identiques (écart mesuré 0.0). `fight_target_selected` par entité + `shoot_weapon_selected` par profil d'arme, plus les assignations déjà faites du tir fractionné (10 activations sur 12 empilaient plusieurs armes sur la même cible, mesuré) — d'abord comptées par `n_weapons_assigned`, champ depuis remplacé par les dix `split_assigned_w<i>` (ligne ci-dessous) ; livré le 2026-09-09. `obs_size` 17091 → **17795** : **`--new` obligatoire** — section conservée ci-dessous : [training.md#contexte-points-arret-obs](training.md#contexte-points-arret-obs) |
| 2026-09-09 | ✅ **Obs — rôle et PV par figurine (retrait de cohérence 03.03)** | `COHERENCY_SLOT_i` désigne la ligne `i` de `self_models_*`, scorée par un produit scalaire nu sans biais de slot : le rôle n'existait qu'agrégé PAR TYPE et les PV courants n'étaient plus observés par figurine depuis §9.4, si bien que 67 paires de figurines de valeur différente sur 67 portaient une ligne identique (mesuré sur 16 épisodes gym, 8 points d'arrêt) — le choix entre le Warboss et un Boy était un tirage au sort. One-hot de rôle + `wounded` + `hp_ratio` par figurine, et `coherency_removal_pending` (obs identique avec/sans le pending, écart 0.0) ; livré le 2026-09-09. `obs_size` 17795 → **17916** : **`--new` obligatoire**, déjà exigé par les lots du même jour — section conservée ci-dessous : [training.md#role-pv-figurine](training.md#role-pv-figurine) |
| 2026-09-09 | ✅ **Obs — seuil et déclenchement du Battle-shock** | `leadership` (Ld le plus bas des figurines vivantes, 01.06) et `battle_shock_test_due` (le prédicat exact de 08.03 : choquée OU à/sous demi-effectif) par entité, +64. **Maillon à part : il ne comble aucun écart d'observation**, et c'est mesuré — sur les 31 compositions de tous les rosters de config/agents/ (agent, adversaire, benchmarks), aucune paire ne partage sa signature observée avec un Ld effectif différent, et le Ld n'a varié dans aucune des 66 escouades suivies sur 6 épisodes gym (11 jets, 3 échecs, Ld 5 à 8 = 17 % à 58 %). Ce qu'il achète est la validité HORS corpus : la table profil → Ld tient en 26 lignes et se périme à la première faction ajoutée, et à force de départ 1 l'appendice 25 mesure les PV, pas les figurines. Livré le 2026-09-09 sur décision de l'utilisateur, contre la recommandation de ne rien ajouter. `obs_size` 18205 → **18269** : **`--new` obligatoire**, déjà exigé par les lots du même jour — section conservée ci-dessous : [training.md#leadership-battle-shock](training.md#leadership-battle-shock) |
| 2026-09-09 | ✅ **Obs — siège premier / second joueur** | `is_my_turn` disait qui a la main, jamais si l'adversaire rejoue APRÈS moi dans ce round : aucun des onze registres ne nommait le joueur (tous égocentriques) et le seul signal restant était un proxy géométrique qui se dégrade quand les unités ont traversé la carte, soit précisément au round 5 — où le premier joueur a déjà marqué son primaire (command phase) quand le second le marquera après sa fight phase. `i_play_first` dans `GLOBAL_BIN_FIELDS`, posé depuis l'OBSERVATEUR et non `current_player` ; sondé sur 217 points d'arrêt du chemin de production, 0 désaccord. Écart de siège mesuré, non encore corrigé : 0,707 contre 0,586. Livré le 2026-09-09. `obs_size` 18204 → **18205** : **`--new` obligatoire**, déjà acquis — aucun `.zip` du disque ne se rechargeait — section conservée ci-dessous : [training.md#siege-premier-joueur-obs](training.md#siege-premier-joueur-obs) |
| 2026-09-09 | ✅ **Obs — candidats de décision DISCERNABLES** | `decision_options_cont` était rempli par le moteur mais lu par AUCUN réseau : cinq types de décision sur neuf présentaient des candidats à embedding identique (écart mesuré 0.0), donc un tirage au sort sous la tête pointeur. Câblage + registre porté à 8 colonnes nommées + les cinq types alimentés ; mergé le 2026-09-09 (`0049f9ab`). `obs_size` 17055 → **17091** : **`--new` obligatoire** — section conservée ci-dessous : [training.md#candidats-decision-discernables](training.md#candidats-decision-discernables) |
| 2026-09-04 | Pool de workers des sondes — persistance réelle | `ExploiterProbeCallback` et `PoolEarlyStoppingCallback` créaient leur pool dans `_on_training_start` et le fermaient dans `_on_training_end`, que SB3 appaire autour de **chaque** `learn()` (sb3-contrib, lignes 448 et 467) : la boucle budgétée en épisodes en enchaînant un par tranche de quatre updates, le pool était recréé et refermé par tranche et chaque sonde repayait le démarrage de ses workers. Remplacé par `_EvalPoolOwnerMixin` — création paresseuse à la première sonde, fermeture par `shutdown_probe_eval_pools` dans le `finally` de la boucle `learn()`. Ce point de fermeture, et non `_close_curriculum_stage`, parce qu'il est le seul à couvrir l'échec et l'interruption, et qu'il libère les 4 workers AVANT l'évaluation finale qui prend les siens. La fermeture sur l'exception qui remonte de `_probe`, livrée le même jour par `126ecf0c`, est conservée telle quelle : elle ferme plus tôt qu'un `finally` traversant `close_all_training_envs`. Mesuré sur harnais identique, 3 sondes à travers des frontières de `learn()` : 2,46/2,04/2,03 s → 2,57/0,02/0,00 s ; en sonde réelle s'y ajoute le chargement de l'archive adverse dans `_worker_ckpt_cache` (9,4 s pour 45 Mo), lui aussi économisé. Le rechargement du modèle P1 ne l'est pas — `_probe` écrit dans un `mkstemp` neuf, le jeton de version change de toute façon. Comptage de processus après fermeture : 0 orphelin. 3 mutations rouges, 66 tests verts | training+infra · — |
| 2026-08-17 | P3-4 Allocation pertes défenseur | `_select_allocation_model` branché sur décision agent ; obs_size 16659→16671 ; 12 tests |
| 2026-08-17 | Nettoyage configs | 6 profils actifs (`x1`/`x1_long`/`x1_debug` + `x5_new`/`x5_long`/`x5_debug`) ; 5 profils supprimés ; 29 tests mis à jour |
| 2026-08-17 | Étape 7 — purge anciens bots | 5 anciens bots supprimés de `bot_training.ratios` et `bot_eval_weights` des 9 profils |
| 2026-08-16 | Coût d'évaluation mesuré | 16 workers optimal (5,75× débit série) ; `bot_eval_final` 600→300 ; notes recalées |
| 2026-08-16 | `torch.compile` et inférence par lot abandonnés | Gains mesurés < 1 % — clé `bot_eval_torch_compile_cpu` retirée des 4 profils |
| 2026-08-11 | Métriques réserves et charge, barème, alignement charge 11.02 | 7 tranches, run `x1_long` du même jour — → `Documentation/Archives/chantiers/metriques_reserves_et_charge_2026-08-11.md` |
| 2026-08-11 | Distances de charge au `step.log` et métriques | 10 courbes `charge_distance/*` (2 camps × 5) depuis les mêmes lignes journal que `m_charge_attempts` |
| 2026-08-11 | Run `--new` ArmageddonAgent x1 | Base de développement, pas la mesure — `run_20260810-111734`, 10 000 épisodes |
| 2026-08-11 | Rampes par-épisode §0.57 | Compteur LOCAL / total GLOBAL — rampe de déploiement figée corrigée |
| 2026-08-20 | Run `x1_long --new` terminé 2026-08-20 — critères pipeline VERTS, `benchmark_floor` posé à 0,049 | training+bot · [bot.md#etape8](bot.md#etape8) |
| 2026-08-19 | **P3-6** Move-after-shooting + reactive move — constaté implémenté 2026-08-19 | training+moteur · [v11_chemin_critique.md#p3-6](v11_chemin_critique.md#p3-6) |
| 2026 | **P3-8** Optionnels — déploiement (08-19), charge multi-cibles (08-20), placement charge (08-24), split-fire (08-24) ; `TOTAL_ACTION_SIZE` 1159→1389 ; ré-entraînement `--new` nécessaire | training · [v11_chemin_critique.md#p3-8](v11_chemin_critique.md#p3-8) |
| 2026-08-19 | **P4** Observation de support — livré 2026-08-19 ; `obs_size` 16671→16703 | training+moteur · [v11_chemin_critique.md#p4](v11_chemin_critique.md#p4) |
| 2026-08-18 | **P5** Validation par tranche — tranché 2026-08-18 | training · [v11_chemin_critique.md#p5](v11_chemin_critique.md#p5) |
| 2026-08-26 | ✅ fix(ppo): `_n_updates` inflaté par n_epochs corrigé (2026-08-26) — incrément déplacé après la boucle epoch (SB3 upstream) ; flush TensorBoard sans seuil (0 perte sur crash) ; test rouge/vert n_epochs=4 | training · — |
| 2026-08-26 | ✅ fix(obs): pollution `_obs_scratch` par clé grid corrigée (findings code-review) — 2026-08-26 | training · — |
| 2026-08-26 | ✅ feat(ppo): `train/time_update` ajouté dans `PatchedMaskablePPO.train()` — 2026-08-26 | training · — |
| 2026-08-25 | ✅ obs slots réservés stratagèmes réactifs (2026-08-25) — slots `charged` UNIT_BIN + `fire_overwatch`/`heroic_intervention` AGENT_DECISION réservés dans l'obs avant R1 ; `fire_overwatch`/`heroic_intervention` sans handler retirés de GRANTABLE, garde GRANTABLE⊆RULE_EFFECT | training+moteur · — |
| 2026-08-18 | ✅ Benchmark floor gate §4.D livré (2026-08-18) — 3 bots de référence (balanced/denial/reactive) sur 4 scénarios holdout_regular ; seuil 0.90 après mesure ; `model_gating_enabled` sur x1_long | training+bot · [v11_chemin_critique.md#benchmark-gate](v11_chemin_critique.md#benchmark-gate) |
| 2026-08-18 | ✅ scenario_bench-01..04 dupliqués supprimés (2026-08-18) — fichiers byte-for-byte identiques aux scenario_bot-01..04, glob fallback ramassait 8 scénarios au lieu de 4, épisodes/scénario divisés par 2 sans contrepartie | training+bot · — |
| 2026-08-24 | ✅ fix combat reward V11 (2026-08-24) — correctif récompense combat gym V11 (worktree-fix-combat-reward-v11) | training · — |
| 2026-08-24 | ✅ fix self_model_encoder dim (2026-08-24) — sortie entity_dim (64) au lieu de model_dim (16) + trunk_dim aligné ; crash reshape [B,20,64] éliminé | training · — |
| 2026-08-19 | ✅ PLACEMENT_WEIGHTS slots 9/10 couverts (2026-08-19) — hotfix training, slots 9 et 10 ajoutés aux poids de placement | training · — |
| 2026-08-19 | ✅ crash results['control'] absent quand min_vs_control=0.0 corrigé (2026-08-19) — résultat dict guard sur clé control ; gate ne crashe plus si critère absent | training+gate · — |
| 2026-08-23 | ✅ fix-selfplay-metrics-validation — validation snapshot_label + déduplique log_selfplay_win (2026-08-23) | training · — |
| 2026-08-23 | ✅ fix-enemy-slot-reserves-oc-fallback — exclure réserves stratégiques ennemies du slot mapping + tests OC fallback (2026-08-23) | training · — |
| 2026-08-23 | ✅ simplify-ai-curriculum-train — dédup et simplifications curriculum/train/test_exploiter (2026-08-23) | training · — |
| 2026-08-23 | ✅ fix-snapshot-label-evaluate-checkpoints — `self_play_snapshot_label` manquant dans `evaluate_against_checkpoints` → crash clôture P1 (2026-08-23) ; verrou rouge/vert | training · — |
| 2026-08-23 | ✅ simplify vec-normalize factory (2026-08-23) — consolider, atleast_2d, drop asarray | training · — |
| 2026-08-23 | ✅ fix vec-normalize non-dict cache bypass (2026-08-23) — VecNormalize chemin non-dict utilisait le cache brut au lieu de vn.normalize_obs() | training · — |
| 2026-08-24 | ✅ expected_damage contextuelle reward_mapper (2026-08-24) — nouveau module expected_damage.py : NB×P(hit)×P(wound)×P(fail_sv)×DMG ; can_kill_in_one_phase remplace proxy NB×DMG brut ; 8 tests rouge/vert | training · [bot.md#recompense](bot.md#recompense) |
| 2026-08-25 | ✅ feat(curriculum) --etape + --resume-from combinables (2026-08-25) — reprendre un run de curriculum planté sans perdre les steps ; erreur explicite si init='new' ; 14 tests verts | training · — |
| 2026-08-22 | ✅ fix-exploiter-probe-trous (2026-08-22) — 4 trous + 2 simplifications `ExploiterProbeCallback` dans `ai/training_callbacks.py` | training · — |
| 2026-08-24 | ✅ fix _coherency_alive unit_by_id + fixture HP_MAX (2026-08-24) — _coherency_alive lit unit_by_id au lieu de squad_cache ; fixture HP_MAX alignée | ai · — |
| 2026-08-24 | ✅ fix spatial extractor sm_emb (2026-08-24) — zero absent sm_emb slots + purge model_dim mort dans ai/models | ai · — |
| 2026-08-24 | ✅ fix profils count 7→6 (2026-08-24) — x1_selfplay supprimé, références 7 profils → 6 mises à jour | training · — |
| 2026-08-24 | ✅ fix+simplify reward_mapper (2026-08-24) — stubs et code mort retirés ; get_kill_bonus_reward + _was_lowest_hp_target factorisés ; verrous rouge/vert | training · — |
| 2026-08-18 | ✅ Note `bot_eval_freq_normal` réécrite (2026-08-18) — d_bot_eval_seconds=98s, 5h54 pour 50k épisodes | training · — |
| 2026-08-21 | ✅ R0b : compteurs W/L/D ajoutés aux checkpoints figés, publiés en TensorBoard (2026-08-21) | training · — |
| 2026-08-26 | ✅ `training_config_overrides` par étape dans `curriculum.json` (2026-08-26) — surcharge `total_episodes`, `model_params` (lr, ent_coef, n_epochs, vf_coef) et `callback_params` (bot_eval_freq, bot_eval_final) sans créer de profils x1_P* ; P1 75k/n_epochs 5/vf 0.5/ent_coef decay 0.65, P2 100k mêmes HP ; whitelist + cohérence total_episodes/bot_eval_freq×3 ; 30 tests | training · — |

---

## Sections archivées — chantiers livrés (texte conservé tel quel)

## ✅ Obs — canaux « zone obscurante » et « exposition à la vue ennemie » {#canaux-obscurant-exposition}

**Livré et mergé le 2026-09-08** (`dd8a24be`). Le lot impose un ré-entraînement `--new` : la
forme d'entrée du CNN change, et le chantier « OC live + secured », mergé le même jour, bouge en
plus `obs_size`.

`GRID_CHANNELS` passe de 9 à 11 ; la verticalité du move gym l'a depuis porté à **12**
(`occupant_level`, cf. [`moteur.md#verticalite-move-gym`](moteur.md#verticalite-move-gym)).
`obs_size` ne bouge pas — la grille est fournie à part.

- **`GRID_CH_OBSCURING`** — les zones obscurantes n'étaient pas distinguables des autres zones de
  terrain : `_static_hex_arrays` empilait tout dans le canal « couvert » sans lire
  `area["obscuring"]`. Le canal est **dilaté du rayon de socle**, comme son jumeau couvert, parce
  que le moteur tranche 13.09 par chevauchement de socle. Ce qu'il ajoute au couvert : être
  `hidden` ne dégrade pas un jet, il rend **intirable** au-delà de la portée de détection.
- **`GRID_CH_LOS_EXPOSURE`** — part des escouades ennemies vivantes et posées qui voient la
  cellule. **Non dérivable** des autres canaux : la branche spatiale est une pile de conv 3×3
  stride 1, elle n'est pas capable de tracer un rayon. Écrit sur les **cellules du pool de move
  uniquement**, à l'hexe que le décodeur y enverra — donc 0 hors phase de mouvement, même
  doctrine que le coût géodésique, et **aucune seconde réponse cellule→hexe** à côté de celle du
  décodeur (mesuré : elles divergent sur 26,7 % des cellules jouables).

**Coût, protocole graine fixe, 450 steps de mouvement** : step de move 73,31 → 80,33 ms
(**+9,6 %**, sous le seuil de 10 %) ; toutes phases 67,39 → 71,52 ms (+6,1 %). **Sans cache**, et
c'est mesuré : une carte de visibilité plateau mémoïsée par hexe source rate 26 % du temps
(l'ancre ennemie bouge à chaque déplacement ET à chaque perte de figurine), l'amorti retombe au
coût de la version sans cache.

**Reste à faire** : le ré-entraînement `--new`, commun à tous les lots d'observation du 2026-09-08 et du 2026-09-09. Tout modèle antérieur est incompatible par construction.

---

## ✅ Obs — `hidden` 13.09 sur toutes les entités et porte de détection {#hidden-detection-obs}

**Livré et mergé le 2026-09-08.** `obs_size` inchangé (16811), donc ce lot n'impose **par lui-même**
aucun `--new` ; il tombe dans celui que « canaux obscurant / exposition » rend déjà obligatoire.

`los_can_see` ne portait que 06.01. La porte des 15" de 13.09 ne vivait que dans l'éligibilité du
tir (`valid_target_pool_build`), donc l'observation annonçait `1` sur une cible que le moteur
refusait : l'agent ne pouvait apprendre ni à entrer dans la portée de détection, ni à se cacher
au-delà. Le bit vaut désormais **visible ET détectable**, via les mêmes oracles que le moteur
(`compute_unit_los` + `hidden_enemy_out_of_detection`) — aucune réimplémentation.

`hidden` est donc émis pour **toute entité posée** et non plus pour la seule unité active : c'est lui
qui conditionne la visibilité. `_squad_terrain_flags` prend un mode `hidden_only` plutôt qu'un second
chemin — une seule implémentation de 13.09. `gone_to_ground` / `in_cover` restent actif-seul : pour un
ennemi, `cover_vs_observer` porte déjà 13.08 EXACT et le −3" de 13.5 est plié dans la porte de
détection ; les émettre coûterait une seconde passe terrain pour une information redondante.

**Coût mesuré** (`scripts/bench_env_step.py`, 400 steps, x1_long/bot/résolution 1, sous contention) :
`hidden` seul 61,8 µs/entité contre 122,0 µs pour les trois drapeaux, et les gardes gratuites
(`hideable`, `units_shot`) écartent 54 % des entités sans aucun scan. Total **0,596 ms/step, soit
0,30 % du temps de step** et 2,8 % du temps d'observation.

**Divergence refermée le 2026-09-08** : l'obs recalcule `hidden` à chaud là où le moteur lit
`unit['hidden']`, et une perte encaissée en cours de phase les faisait diverger. Le moteur suit
désormais les pertes au choke-point de retrait de figurines, et le contrat D1 tient donc en cours de
phase et plus seulement à son début : voir [moteur.md#hidden-fraicheur](moteur.md#hidden-fraicheur).
Il reste périmé pendant le MOVE, ce qui justifie que l'obs continue de recalculer plutôt que de lire.

---

## ✅ Obs — CONTEXTE des points d'arrêt à deux temps {#contexte-points-arret-obs}

**Livré le 2026-09-09.** `obs_size` 17091 → **17795** : ré-entraînement `--new` obligatoire.

Deux mécanismes demandent un choix dont la moitié est déjà fixée — la sélection d'arme de mêlée
(§0.69 : la cible est désignée, l'arme reste à choisir) et le sous-état CIBLE du tir fractionné
(P3-8 : l'arme est armée, la cible reste à choisir). Ni l'une ni l'autre moitié n'était observée.
S'y ajoute, trouvée en revue puis mesurée, ce que le tir fractionné a déjà DÉCIDÉ : ses
assignations arme → cible, invisibles elles aussi.

**Mesuré avant correction :** dans les deux cas, deux états ne différant que par la moitié déjà
fixée produisaient des observations **strictement identiques** — 28 clés comparées, écart maximal
0,0. La politique n'étant pas récurrente (`MaskablePPO`), elle ne se souvient pas de l'action jouée
au step précédent : l'arme se choisissait sans voir la cible, la cible sans voir l'arme. Cause
commune : l'observation n'encodait qu'un seul des sept points d'arrêt de `PLAYER_CHOICE_MECHANISMS`,
la décision d'agent. Fréquence sur les rosters joués : 5 escouades sur 11 portent ≥ 2 armes de
mêlée, 8 sur 11 ≥ 2 armes de tir ; mesuré en jeu, 5 épisodes gym du pool `training` traversent
36 points d'arrêt de tir fractionné et 2 sélections d'arme de mêlée.

**Ce qui a été livré :**

- `fight_target_selected` (`UNIT_BIN_FIELDS`, +32 scalaires) marque la ligne ennemie de la cible
  désignée. Aucun bit de contexte global ne l'accompagne : la cible occupe toujours un slot ennemi
  observé (`_continue_squad_fight` lève sinon, et `FIGHT_SLOT_COUNT` vaut `K_ENEMY_SLOTS`), donc le
  bit est auto-porteur. L'observation lève si la cible n'y figure pas — jamais un bit muet ;
- `shoot_weapon_selected` (`PROFILE_BIN_FIELDS`, +640) marque le profil de l'arme armée. Le registre
  des profils n'avait qu'un champ, le masque : `present` reste **dernier** (§0.37), lu
  positionnellement par `ai/spatial_extractor` ;
- le slot du profil armé est **écrit par le moteur** (`pending_weapon_slot`, posé et effacé avec
  `pending_weapon`) et relu par l'observation, au lieu d'être re-dérivé du code d'arme — deux
  dérivations d'un même fait divergent ;
- le drapeau d'arme est posé **hors du cache de profils** (mémoïsé par escouade et figurines
  vivantes) : écrit dedans, il serait resté allumé après la fin du point d'arrêt ;
- un test vérifie que les trois canaux **atteignent le réseau** — c'est exactement ce qui manquait
  à `decision_options_cont`, rempli par le moteur et lu par personne ;
- `n_weapons_assigned` (`UNIT_CONT_FIELDS`, +32) comptait, par escouade ennemie, les profils
  d'armes déjà assignés pendant l'activation de tir en cours. **Ce champ n'existe plus** : il a
  cédé la place le même jour aux dix bits `split_assigned_w<i>`, qui portent le même comptage
  (`popcount`) ET l'appariement arme → cible que le comptage perdait — voir
  [Obs — couples arme→cible du tir fractionné](#couples-arme-cible-split-fire).

---

## ✅ Obs — rôle et PV par figurine (retrait de cohérence 03.03) {#role-pv-figurine}

**Livré le 2026-09-09.** `obs_size` 17795 → **17916** : ré-entraînement `--new` obligatoire — il
l'était déjà pour les lots du même jour, ce lot n'en ajoute aucun.

`COHERENCY_SLOT_i` (P3-0) demande à l'agent quelle figurine **détruire** pour regagner la
cohérence. Il désigne la ligne `i` de `self_models_*`, que `pointer_policy._point` score par un
produit scalaire nu **sans biais de slot**, sur un embedding calculé **ligne par ligne**
(`self_model_encoder`, aucune interaction entre slots). Or la ligne ne portait que
`col_rel, row_rel, fight_eligible, in_enemy_ez, elevated, present` : le rôle d'allocation
existait bien dans l'observation, mais **agrégé par TYPE**, et les PV courants n'étaient plus
observés par figurine depuis §9.4. Le tri de `_squad_models_for_observation` place pourtant les
personnages en tête — un rang qu'**aucune tête ne lit**.

**Mesuré avant correction** (16 épisodes gym du pool `training`, actions masquées aléatoires,
3 250 pas) : 8 points d'arrêt de cohérence, dont 4 mêlaient un personnage attaché et des figurines
de base et 5 des figurines de PV différents ; **67 paires de figurines de valeur différente sur
67** portaient une ligne `self_models_bin` **identique**, seule leur position les séparant. Le
choix était donc un tirage au sort entre le Warboss et un Boy. Même mesure sur l'état :
l'observation d'une escouade **avec et sans** `pending_coherency_removal` armé est strictement
identique (écart 0.0 sur toutes les clés), alors que le masque, lui, n'ouvre que les slots
COHERENCY — la politique ne pouvait pas se tromper d'action, mais la **valeur** de l'état ignorait
qu'une figurine était perdue d'office.

**Ce qui a été livré :**

- one-hot de rôle (4 bits) + `wounded` dans `SELF_MODEL_BIN_FIELDS` (+100) et `hp_ratio` dans
  `SELF_MODEL_CONT_FIELDS` (+20) — `present` reste **dernier** (§0.37) ;
- `MODEL_ROLES` devient la **source unique** des deux registres qui portent ce one-hot (bloc TYPES
  et bloc figurines) : deux tuples écrits à la main auraient pu diverger sans rien lever ;
- `wounded` double `hp_ratio` **volontairement** : les continus de ce bloc passent par
  `EntityRunningNorm`, dont la variance est minuscule sur une colonne quasi constante (une figurine
  à 1 PV max n'est jamais entamée), donc `hp_ratio` y sature à ±10 — le FAIT survit à la
  saturation, le DEGRÉ reste porté par `hp_ratio` ;
- `coherency_removal_pending` dans `GLOBAL_BIN_FIELDS` (+1), posé sur l'escouade **observée** et
  non « un retrait quelque part » : pendant l'arrêt, l'observateur EST l'escouade en attente ;
- deux verrous, l'un côté moteur (`tests/unit/engine/test_squad_obs_model_value_p3_0.py`), l'autre
  côté réseau (`tests/unit/ai/test_self_model_value_encoding.py`) : c'est exactement ce qui
  manquait à `decision_options_cont`, rempli par le moteur et lu par personne.

`ai/spatial_extractor.py` n'a **pas** été touché : ses largeurs d'encodeur sont dérivées des formes
de l'espace d'observation, donc les colonnes ajoutées entrent d'elles-mêmes — vérifié par test.

---

## ✅ Obs — seuil et déclenchement du Battle-shock {#leadership-battle-shock}

**Livré le 2026-09-09.** `obs_size` 18205 → **18269** : ré-entraînement `--new` obligatoire —
déjà exigé par les lots du même jour.

**Maillon À PART des précédents, et il faut le dire d'entrée : il ne comble AUCUN écart
d'observation.** Les maillons du même jour tenaient tous sur la même preuve — deux états ne
différant que par le fait manquant rendaient des observations identiques, écart 0.0. Ici la
mesure dit l'inverse, et elle a été faite AVANT de coder.

**Mesuré le 2026-09-09 :**

- sur les **31 compositions d'escouade** de TOUS les rosters de `config/agents/` — agent,
  adversaire (`_p2_rosters`) et benchmarks, variants de réserves compris, soit 26 signatures une
  fois retirés les agrégats —, **aucune paire** ne partage sa signature observée — stats d'unité +
  multiset des types `(role, hp_max, toughness, armor_save, invul_save)` — avec un Ld effectif
  différent. Le Ld est donc une fonction exacte de ce qui était déjà émis, y compris en retirant
  les agrégats `value_alive` / `hp_total` / `oc_total` qui le rendraient distinguable pour de
  mauvaises raisons ;
- sur **6 épisodes gym** (2 scénarios × 3 graines, actions masquées aléatoires), le Ld effectif
  n'a varié dans **aucune des 66 escouades** suivies pas à pas : 19.02 fait tomber le personnage
  attaché en dernier, donc le `min` sur les figurines vivantes est en pratique une constante de
  composition ;
- la règle, elle, n'est pas inerte : **11 jets de Battle-shock, 3 échecs**, Ld rencontrés 5 à 8
  — soit 17 % à 58 % de probabilité d'échec selon la cible.

**Ce que les deux champs achètent, alors :** la validité **hors corpus**. La table « profil → Ld »
tient en 26 lignes et se mémorise ; elle se périme à la première faction ajoutée. Et le prédicat
de 08.03 demande un branchement que `model_count_ratio` seul ne porte pas — à force de départ 1,
l'appendice 25 mesure les **points de vie**.

**Ce qui a été livré :**

- `leadership` (`UNIT_CONT_FIELDS`, 1 × 32 entités = +32) : le Ld le plus BAS des figurines
  vivantes, lu par `unit_effective_leadership` — l'oracle qu'appelle `roll_battle_shock`, jamais
  un `min` recopié sur les figurines déjà chargées ;
- `battle_shock_test_due` (`UNIT_BIN_FIELDS`, 1 bit × 32 entités = +32) : le prédicat EXACT de
  `command_step_battle_shock`, `battle_shocked` **OU** `is_unit_at_or_below_half_strength`. Le
  premier terme n'est pas redondant avec le statut `battle_shock` — il porte la clause de retest
  de 08.03, une unité choquée pouvant cesser de l'être ;
- **ce que le bit ajoute n'est PAS la clause de parité de l'appendice 25** : mesuré par mutation,
  `restant / départ <= 0,5` lui est équivalent sur un effectif en figurines, la parité ne pouvant
  jouer que là où `2 × restant == départ` est arithmétiquement impossible. C'est la bascule de
  mesure mono-figurine qui les sépare, et c'est ce cas-là que le test verrouille ;
- une fixture de test corrigée (`test_model_value_per_figurine.py`) : elle construisait des unités
  sans `LD`, ce que l'observation ne tolère plus — la caractéristique est obligatoire sur toute
  datasheet, et `unit_effective_leadership` refuse de l'inventer ;
- carte des index d'`observation_et_actions.md` mise à jour, dont l'en-tête du bloc de drapeaux qui
  annonçait 37 pour 38 index réels.

**Ce qui n'est PAS prouvé :** que la politique joue mieux. Sur les rosters actuels, la mesure dit
même l'inverse — l'information y était déjà dérivable. Le gain attendu est la robustesse à un
roster jamais vu, et il ne se mesurera que le jour où l'entraînement quittera ces deux armées.
Décision prise par l'utilisateur au moment de la livraison, contre la recommandation de ne rien
ajouter.

---

## ✅ Obs — siège premier / second joueur {#siege-premier-joueur-obs}

**Livré le 2026-09-09.** `obs_size` 18204 → **18205** : ré-entraînement `--new` obligatoire — déjà
acquis avant ce lot, aucun `.zip` de `ai/models/ArmageddonAgent_x1/` ne se rechargeant avec le code
courant (`best_model.zip` : `decision_encoder` [64, 9] contre [64, 11] ; les autres : grille
(9, 32, 32) contre (12, 32, 32) attendue — mesuré par chargement réel).

`is_my_turn` disait qui a la main **maintenant**, jamais si l'adversaire rejoue **après moi** dans
ce battle round. Or `turn` est le round et non le tour de joueur, P1 l'ouvre toujours, et le
primaire se marque à la command phase pour le premier joueur mais à la **fight** phase pour le
second au round 5 (`round5_second_player_phase`) : au round 5, le premier joueur a déjà marqué et
son dernier tour ne lui rapporte plus de primaire. Deux états identiques à l'écran n'ont donc pas
la même valeur selon le siège.

**Vérifié :** aucun des onze registres d'observation ne nommait le joueur — tous sont égocentriques
(`my_` / `enemy_`, `ally` / `enemy`, positions relatives). Le seul signal restant était un PROXY
géométrique (zones `dz_p1` / `dz_p2` attachées au joueur, `objective_dir_cos/sin` calculés dans le
repère **absolu** du board), qui se dégrade quand les unités ont traversé la carte — précisément au
round 5. Écart de siège mesuré sur le run x1_long du 2026-08-12 : 0,707 de win-rate en jouant
premier contre 0,586 en second, ce que `agent_seat_p2_ratio` ne fait que sur-échantillonner.

**Ce qui a été livré :**

- `i_play_first` dans `GLOBAL_BIN_FIELDS`, en **deuxième position**, à côté de `is_my_turn` : le
  retrain étant acquis, le bit prend sa place logique au lieu de consommer un
  `reserved_mission_bin_*` — les 48 slots réservés restent entiers pour J4 ;
- le bit est posé depuis l'**observateur** (`active_player`) et non depuis `current_player` : aux
  points d'arrêt joués pendant le tour adverse, c'est l'ordre de jeu de celui à qui la décision est
  demandée qui compte. `tests/unit/engine/test_squad_obs_seat_bit.py` verrouille cette distinction
  — la mutation « câblé sur `current_player` » met 4 tests sur 5 au rouge ;
- chemin de production sondé : 217 points d'arrêt encodés par `_build_observation_and_mask` sur un
  épisode Armageddon (122 observateur P1, 95 observateur P2, 37 contextes round/joueur/phase
  distincts), **zéro** désaccord entre le bit et le siège de l'observateur.

**Non prouvé, et à mesurer par un run :** que le bit réduise l'écart de siège. Le contenu du canal
est vérifié, son effet sur la politique ne l'est pas.

---

## ✅ Obs — candidats de décision DISCERNABLES {#candidats-decision-discernables}

**Livré et mergé le 2026-09-09** (`0049f9ab`). `obs_size` 17055 → **17091** : ré-entraînement
`--new` obligatoire, décidé par l'utilisateur au moment de la livraison.

Le bloc `decision_options_cont` était rempli par le moteur depuis P3-4 mais **n'atteignait aucun
réseau** : `SpatialCombinedExtractor` ne le listait pas dans ses clés attendues, son
`decision_encoder` était dimensionné sur le seul bloc binaire, et la clé n'apparaissait dans aucun
de ses accès d'observation. Cinq types de décision sur neuf posent des candidats qui n'accordent
aucun effet et ne renoncent à rien — `allocation_model` (à chaque blessure non sauvegardée),
`charge_placement` (à chaque charge réussie), `mortal_wounds_target` et les deux décisions de Grot
Orderly : leurs lignes d'observation étaient **strictement identiques**.

Mesuré avant correction, deux candidats aux traits continus opposés sortaient à un écart
d'embedding de **exactement 0.0** ; `pointer_policy._point` scorant chaque candidat par un produit
scalaire nu, sans biais par slot, les logits étaient égaux. `CHOICE_i` était un pile-ou-face que
PPO ne pouvait pas apprendre. Après câblage, le même cas sort à 0,4544.

Les quatre autres types restaient apprenables par un autre canal, et le restent : `rule_choice`
par le one-hot de l'effet accordé, `waaagh_call`, `fly_declaration` et `ascent_declaration` par le
bit `declines`.

**Ce qui a été livré :**

- l'encodeur de candidat lit ses **deux** blocs, et la construction lève si leurs cardinalités
  divergent — un désaccord ne levait nulle part ailleurs et aurait mélangé les traits d'un
  candidat avec les drapeaux d'un autre ;
- `DECISION_OPTION_CONT_FIELDS` passe de 2 à **8 colonnes nommées**, une grandeur par colonne :
  deux types qui décrivent la même grandeur partagent la colonne (`dist_enemy_norm` sert à
  l'allocation comme au placement rendu), deux grandeurs différentes n'en partagent jamais. Les
  lignes se bâtissent par `decision_option_cont_row`, qui lève sur un champ inconnu ou hors
  [0, 1] — aucun producteur n'écrit de zéro positionnel ;
- le bloc ne passe par **aucune** `EntityRunningNorm` : ses statistiques glissantes excluent les
  candidats absents mais pas les colonnes muettes d'un type, et mélangeraient « sans objet » et
  vraies valeurs. Les colonnes sont donc normalisées à la source ;
- les cinq types sont alimentés. Pour le placement des figurines rendues, ce sont les **distances
  du plan** — jumeau exact du placement de charge — et non un one-hot d'intention : les distances
  disent ce que l'étiquette vaut sur CE plateau, et généralisent à une intention ajoutée sans
  colonne de plus.

**Défaut de fond trouvé en vérifiant, et corrigé :** `_precompute_nearest_enemy_dist` énumérait
`models_cache` sans filtrer les unités hors table. Une escouade en réserves stratégiques (20.01)
est vivante dans le cache, ses figurines y portent la sentinelle (-1,-1), et l'énumération
injectait donc une position qui n'existe pas sur la table. Les deux sites énumèrent désormais par
`enemy_entries_on_battlefield`.

**Son ampleur a été MESURÉE le 2026-09-09, et elle est nulle — la première rédaction de ce
paragraphe surestimait le défaut.** Sur 1 337 appels en bot-contre-bot (pool `training`,
2 scénarios × 20 épisodes), 14 avaient un ennemi hors table et **aucun** ne changeait de
résultat : la sentinelle est un COIN du plateau, donc le `min` ne la retient que pour une
figurine plus proche de ce coin que de tout ennemi réel — cas jamais atteint sur ce volume. Les
classements bot-contre-bot avant/après correction sont **identiques bit à bit** : 2 400 épisodes
sur `holdout`, 1 200 sur `training`, même graine, même protocole.

Conséquence pratique, contre ce qui avait été annoncé ici : **la ligne de base des bots reste
comparable**, et le run `--new` n'a pas besoin d'une re-mesure préalable du panel. Les chiffres
`{0,48 ; 0,46}` → `{0,06 ; 0,08}` cités auparavant venaient du test de non-régression, dont
l'état est construit pour que la sentinelle domine — ils prouvent le verrou, pas une fréquence de
jeu.

---
