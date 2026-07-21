# V11 — Rétablissement de l'entraînement de l'agent (agent rework)

Date d'audit : 2026-07-14. Tous les faits ci-dessous ont été vérifiés dans le code actuel
(lecture + exécution de smoke tests), puis contre-vérifiés par une review indépendante
(2026-07-14 soir). Chaque rupture est accompagnée de sa reproduction exacte.

**Convention d'ancrage** : l'ancre de référence est le NOM DE FONCTION ; les numéros de ligne
sont indicatifs (constaté pendant l'audit : fight_handlers.py a bougé de ~45 lignes en une
journée). Toujours re-localiser par grep du nom avant d'éditer.

---

## 0. ÉTAT AU 2026-07-20 — À LIRE EN PREMIER

> **Cette section ne contient QUE ce qui est ouvert et actionnable.**
> - Ce qui est résolu est en **§0hist — Historique résolu** : entrées intégrales, ancres
>   `### 0.x` inchangées, aucune preuve condensée.
> - Les avertissements et leçons de méthode durables sont regroupés en **§0bis — Pièges et
>   leçons de méthode**, qui en est la **copie canonique**.
>
> **Conventions de tenue de ce document — les respecter en le mettant à jour :**
> - **Un numéro d'entrée est attribué à vie.** Une entrée résolue descend en §0hist en gardant
>   son numéro ; un numéro n'est jamais réattribué. Prochaine entrée libre : `0.23` (`0.18`–`0.21` le 2026-07-20, `0.22` le 2026-07-21).
> - **Un contenu d'état vit à UN seul endroit.** Une entrée à moitié résolue est **scindée** :
>   la part résolue reste sous son numéro en §0hist, la part ouverte prend un numéro neuf ici,
>   et les deux se renvoient l'une à l'autre. Seuls les avertissements et leçons sont dupliqués
>   (§0bis fait foi).
> - Une entrée **périssable** (état de commit, mesure) porte sa date et l'ordre de la
>   reconfronter au réel avant usage.

### Tableau d'état — ce qui est ouvert

| # | Entrée | Nature | Ordre proposé | Pourquoi cet ordre |
|---|---|---|---|---|
| **§0.14** | Re-mesure du run | non-régression §0.11 VALIDÉE, **score par matchup encore dû** | **1** | ✅ **Non-régression §0.11 validée le 2026-07-21 : 3 runs `x5_debug 500` indépendants, 3× 500/500, zéro crash intra-plan** (1500 ép. cumulés). Reste le **score par matchup interprétable** : exige un run long réel (10-30k ép., ~36 h) pour que l'agent **converge** (les runs 500/1k ne mesurent que la non-régression, pas un win-rate) — dépend du gain perf **§0.22**. |
| **§0.22** | `MOVE_POOL_BUILD` = 95,6 % du training | 🎯 **L1 + L_bbox livrés (gain ovale 1,49×, pool strictement identique) ; reste le BFS (étape 4)** | **2** | **L1 (mémoïsation footprint) + L_bbox (dilatations fenêtrées bbox `move_range`, pur NumPy, FLY exclu) faits le 2026-07-21** — A/B fenêtré==plein-board + oracle + snapshot ovale + suite verte. Étapes 0-1 faites (cible confirmée + **pool hex du training verrouillé par test**). Cache des masques : codé, prouvé équivalent, **mesuré 0 % → reverté**. **Facteur dominant = SURFACE, pas numba** (mesuré : `reach`/board ≤ 16,6 %, `_dilate` O(\|offsets\|×board) indépendant de la densité). Levier optimal = **borner toutes les dilatations à la bbox `move_range`** (pur NumPy, exact, inconditionnel) ; Minkowski/cache-murs/numba-dense **caducs** (`\|obstacles\|`≈2400-3000 mesuré) ; numba réservé au seul reliquat BFS petits socles, **à bencher vs wavefront bbox-NumPy**. Ordre : L1 → L_bbox → re-bench → BFS conditionnel. Détail + mesures → **[`V11_move_build_acceleration.md`](V11_move_build_acceleration.md)** (§2bis, §8) ; cadrage garde-fous → **[`V11_move_pool_optimization.md`](V11_move_pool_optimization.md)**. |

Ne restent ouverts que **§0.14** et **§0.22**, liés par une dépendance : le **score par matchup**
de §0.14 exige un run long, dont la durée dépend du **gain perf de §0.22**. (Les dépendances
historiques §0.12 → §0.14 et §0.18 → §0.14 sont **levées** : §0.12 et §0.18 sont livrés et
descendus en §0hist.) Les entrées résolues §0.15, §0.16, §0.17, §0.18, §0.19, §0.21 sont
**descendues en §0hist** (§0.16 aussi en §0ter pour ses notes post-implémentation).

⚠️ **Avant de vous appuyer sur une affirmation de ce document, lire §0bis** — en particulier la
réserve de méthode sur le document lui-même (T1→T5 et section 9 n'ont **pas** été revérifiés
ligne à ligne) et la règle de périmètre `ArmageddonAgent`.


### 0.14 Re-mesure du run — 🟢 NON-RÉGRESSION §0.11 VALIDÉE (3 runs le 2026-07-21) ; score interprétable encore dû

> Part **ouverte** de §0.13 (run x5_debug 100 épisodes). Le run et le fix de l'évaluation
> finale sont résolus et documentés en **§0.13**.

> ✅ **NON-RÉGRESSION §0.11 VALIDÉE (2026-07-21) — 3 runs indépendants, zéro crash.** Après le fix
> §0.18, la commande de re-mesure (`x5_debug --total-episodes 500`) a été relancée **3 fois** :
> **3× 500/500 épisodes, `✅ TRAINING COMPLETE`, ZÉRO `collision intra-plan`, zéro `Traceback`,
> zéro `incohérence masque`** (grep sur les 3 logs). Le crash dépendant de la trajectoire qui
> survenait à l'épisode ~280 (§0.18) **n'est plus jamais réapparu** sur 1500 épisodes cumulés.
> L'avertissement « la non-régression de §0.11 reste non validée par un run » de §0.18 est
> **LEVÉ**. ⚠️ **Ce que ces 3 runs NE prouvent PAS** : le **score par matchup**. À 500 épisodes /
> 2 par bot, les Combined (61,5 % / 38 % / 19,5 % / 42 %) restent **non concluants** (bruit
> d'échantillon) — c'est le **pipeline** qui est validé, pas la politique. Un win-rate
> interprétable exige toujours un run long à `total_episodes` réel (10-30k), aujourd'hui coûteux
> en temps (~36 h) — c'est précisément la cible du chantier `V11_move_pool_optimization.md` (§0.22).
> §0.15 étant tranché, ce win-rate mesurera la robustesse à l'**adversaire**.

**Run de re-mesure du 2026-07-20 — commande exacte :**

```
python3 ai/train.py --agent ArmageddonAgent --scenario bot --new \
        --training-config x5_debug --total-episodes 500
```

(`--total-episodes` surcharge le `total_episodes: 100` de la config ; **la config n'a pas été
modifiée**. Lancé APRÈS §0.12, donc sur le reward définitif.)

**✅ Ce que ce run PROUVE.**

| Point | Résultat |
|---|---|
| Déroulement | **500/500 épisodes, exit 0**, 1 h 48, 8 workers, GPU. **Zéro exception, zéro `incohérence masque/exécution`** dans tout le log. |
| **Non-régression §0.11** | 🔴 **NON — affirmation RETIRÉE le 2026-07-20, voir §0.18.** Ce premier run a bien franchi l'épisode ~250, mais un **second run, même commande**, a **crashé sur le même message d'erreur à l'épisode ~280**. Un run qui passe ne prouve rien ici : le crash dépend de la trajectoire, donc du hasard. **L'avertissement « la non-régression de §0.11 reste non validée par un run » N'EST PAS levé.** |
| **Fix §0.13** | ✅ **VALIDÉ RUNTIME.** Le ranking porte sur `holdout_regular_bot-01` / `-02` — l'éval finale joue bien le pool **holdout**, plus le scénario d'entraînement. |
| Reward §0.12 | Le run tourne sans incident avec la `VALUE` par figurine et l'event `model_value`. Aucun crash du chemin d'allocation. |

**Résultats de l'évaluation finale (12 épisodes = 2 par bot) :**

```
  vs adaptive            :  50.0% (1W-1L-0D)
  vs aggressive_smart    :  50.0% (1W-1L-0D)
  vs control             :   0.0% (0W-2L-0D)
  vs defensive           : 100.0% (2W-0L-0D)
  vs greedy              : 100.0% (2W-0L-0D)
  vs tactical            : 100.0% (2W-0L-0D)   <-- holdout
  Combined Score:  61.5%

🏁 Scenario ranking (combined):
  - holdout_regular_bot-01: combined=0.770 | worst_bot_score=0.000
  - holdout_regular_bot-02: combined=0.460 | worst_bot_score=0.000
```

**🔴 Ce que ce run NE prouve PAS — le score reste NON CONCLUANT.**

- **2 épisodes par bot.** `bot_eval_final` vaut **2** dans la phase `x5_debug`. C'est bien
  « > 1 » comme l'exigeait cette entrée, mais **12 épisodes ne permettent aucune conclusion** :
  chaque bot est un 2W-0L / 1W-1L / 0W-2L, soit une résolution de 50 points de pourcentage.
  Le `61.5 %` est un chiffre **indicatif**, à ne PAS reporter dans §10.6.
- **500 épisodes d'entraînement, ce n'est pas un agent entraîné.** Les phases réelles sont à
  10 000–30 000 (`x1`, `x5_new`, `x5_append`). Ce run valide le **pipeline**, pas la politique.
- **`vs tactical: 100 %` ne vaut rien comme signal de holdout** à 2 épisodes — c'est
  précisément le chiffre qu'on voudrait fiable, et c'est celui qui a le moins d'échantillon.
- ⚠️ **`vs control : 0 % (0W-2L)`** est le seul résultat qui mérite un œil : c'est le
  `worst_bot_score=0.000` des deux scénarios. À 2 épisodes ce peut être du bruit pur ; **à
  reconfronter au prochain run long** avant d'y voir un trou de comportement.

**🔴 DEUXIÈME RUN — CRASH, voir §0.18.** Un run relancé avec la **même commande** après le
correctif de la rupture D s'est arrêté à l'**épisode ~280** sur
`ValueError: execute_squad_move a échoué … collision intra-plan`. **§0.11 n'est donc pas
résolu.** C'est la conclusion la plus importante de cette entrée, et elle contredit ce que le
premier run laissait croire.

**🔴 INVALIDÉ A POSTERIORI (même jour) — la rupture D de §0.12.** Ce run a tourné **avant** la
découverte de la régression d'observation (`value_over_ttk` extrapolait le `points_per_hp` de la
figurine d'index 0). Les deux rosters de §10.2 étant hétérogènes en points, **l'agent s'est
entraîné sur une observation fausse** pendant les 500 épisodes. Ce qui reste valable malgré
tout : la **non-régression §0.11** et la **validation runtime du fix §0.13**, qui ne dépendent
ni du reward ni de l'observation. Le score, lui, est à jeter deux fois plutôt qu'une.

**Ce qui reste à faire pour fermer cette entrée** : un run sur une phase à `bot_eval_final`
élevé (`x1`, `x5_new` et `x5_append` sont déjà à **100**) et à `total_episodes` réel, pour
produire un win-rate **par roster** interprétable au sens de §10.6. ⚠️ Cf. **§0.15** : les
rosters `training` et `holdout_regular` étant identiques, ce win-rate mesurera la robustesse à
l'**adversaire**, jamais au roster.

### 0.22 Coût du move pool — `MOVE_POOL_BUILD` = 95,6 % du training — 🟠 OUVERT (cardinalités mesurées + levier tranché, 2026-07-21)

> **⚠️ MAJ 2026-07-21 — CE QUI SUIT DANS CETTE SECTION EST EN PARTIE SUPERSEDED.** Le profil interne
> a depuis été re-mesuré sur le **vrai board 220×300** et toutes les cardinalités décisives sont
> connues (`reach`/board ≤ 16,6 %, `|walls|`≈435-988, `|occupied|`≈1900/build, `|obstacles|`≈2400-3000).
> **Conclusion tranchée : le facteur dominant est la SURFACE, pas numba.** `_dilate_by_kernel` est
> O(|offsets|×board) *indépendant de la densité* → le levier optimal est **borner les dilatations à la
> bbox `move_range`** (pur NumPy, exact, inconditionnel, **sans dépendance**). Minkowski, cache-murs et
> numba-dense sont **caducs** ; numba n'est en jeu que pour le reliquat BFS des petits socles, **à
> bencher d'abord contre un wavefront bbox-NumPy**. Le « chantier cache » décrit plus bas est **réfuté
> (0 %)** et le cProfile 60×80 ci-dessous est remplacé par le profil 220×300.
> **➜ Source de vérité désormais : [`V11_move_build_acceleration.md`](V11_move_build_acceleration.md)
> (§2 profil réel, §2bis mesures + verdict, §8 ordre L1→L_bbox→re-bench→BFS).**

**Constat chiffré (bench x5 du 2026-07-21, `perf_timing_bench_x5.log.score.json`).**
`MOVE_POOL_BUILD` : **374 390 appels, 17,49 ms/appel, somme 6548,7 s sur 6848,6 s de temps
instrumenté = 95,6 %**. Le BFS seul y pèse `bfs=12,13 ms/appel` (**69 %** du build) ; `prep`/`post`
le reste. `CHARGE_DEST_BFS` (86,9 s) et `CHARGE_PHASE_START` (213 s) sont marginaux. **Le coût d'un
run x5 est, à 95 %, la construction du pool de destinations de move.**

**Outillage — `scripts/profile_move_pool.py` était CASSÉ, réparé (2026-07-21).** Il ne tournait plus
depuis la migration squad (§0.12) : `build_units_cache`/`_build_models_for_unit` exigent désormais
une datasheet complète (`VALUE`, `HP_MAX`, `OC`, `T`, `ARMOR_SAVE`, `INVUL_SAVE`, `SHOOT_LEFT`,
`ATTACK_LEFT`, `RNG_WEAPONS`, `CC_WEAPONS`, `UNIT_RULES`), et le chemin exige `move` (minuscule),
`config["move"]` (règles de traversée), `inches_to_subhex` et `gym_training_mode`. Ajoutés : bloc
`datasheet_defaults` sur chaque unité, section `move` **alignée sur `config/game_config.json`**, flag
`--resolution` (défaut 5), et bascule `gym_training_mode=True` (on profile le chemin **training**,
métrique `move_gym=hex`, celui qui domine). ✅ Tourne à toute résolution.

**Diagnostic cProfile (config cachée après warmup ; board 60×80 SYNTHÉTIQUE — ⚠️ PAS le board de
référence, qui est `config/board/44x60x5` = 220×300 subhex ; move 12, base 5, ez 12, res 5, 300
itérations, tri `tottime`).** Proportions à re-mesurer sur 220×300, cf. `V11_move_pool_optimization.md`.

| Fonction | Part | Note |
|---|---|---|
| `_build_multi_hex_vectorized` ([movement_handlers.py:1523](../../engine/phase_handlers/movement_handlers.py#L1523)) | **~68 %** du build (interne + noyaux) | BFS/disque vectorisé NumPy. Le vrai goulot. |
| `_dilate_by_kernel` / `_spread_by_kernel` | inclus ci-dessus | dilatations par slices, appelées plusieurs fois/build |
| `_hex_center` + `math.sqrt` | ~10 % | **752 appels/build**, dans les footprints |
| footprints (`_footprint_round/_square`) | faible | **PAS** le goulot : `precompute_footprint_offsets` existe déjà, ~6 appels/build |

⚠️ **La config n'est PAS le goulot** : après warmup, `get_game_config` est cachée (le profil froid
montrait un `_io.open` par appel, disparu à chaud). Ne pas partir sur cette fausse piste.

**Chantier proposé — 🔴 RÉFUTÉ (mesuré 0 %, cf. MAJ en tête de §0.22).** *Historique conservé pour
traçabilité, NE PAS engager.* Cacher entre
appels ce qui ne dépend que de (dims plateau × forme de socle) et non de l'état mobile :
`col_parity_mask`, `off_even_arr`/`off_odd_arr`, et les masques de bornes/parité
(`_bounds_bad_parity`), aujourd'hui réalloués/recalculés à **chacun** des 374 k appels. Exige :
(1) une clé de cache correcte, (2) une **invalidation** sûre, (3) des **tests d'équivalence stricte
de pool** (l'invariant du docstring de `_build_multi_hex_vectorized` : équivalence exacte avec le BFS
Python d'origine), (4) un **re-bench**. Ce n'est pas un edit isolé — c'est un cycle moteur dédié.
Aucune ligne de `_build_multi_hex_vectorized` n'a été modifiée.

**Arbitrage TRANCHÉ (2026-07-21).** L'utilisateur a décidé : **on optimise**, à condition explicite
que « le gain de performance ne se fasse pas au détriment du métier et du PvP ». Le chantier (objectif,
garde-fou d'équivalence stricte, exigences cache/invalidation/tests, non-régression PvP, plan par
étapes, Definition of Done) est **cadré dans un document dédié** :
➜ garde-fous/cadrage **[`V11_move_pool_optimization.md`](V11_move_pool_optimization.md)** ; **mesures +
plan d'implémentation à jour [`V11_move_build_acceleration.md`](V11_move_build_acceleration.md)**. Code
toujours **non commencé** (aucune ligne de `_build_multi_hex_vectorized` modifiée) ; cardinalités
mesurées, levier tranché (bbox NumPy). ~~Prochaine action : L1 → L_bbox (cf. §8 du doc dédié).~~
**L1 + L_bbox faits le 2026-07-21** (cf. `V11_move_build_acceleration.md §10`). L1 :
`precompute_footprint_offsets` mémoïsée. L_bbox : dilatations de `_build_multi_hex_vectorized`
fenêtrées sur la bbox `start ± (move_range + max|offset|)` du chemin ground (variante (b), pur NumPy ;
FLY exclu). Garde-fous : oracle + snapshot ovale + **A/B fenêtré==plein-board** (7 cas) + suite
complète verte. **Gain A/B (220×300, gym hex)** : ovale [20,14] 1,49×, round 10 1,78×, round 3 1,13×
(pool strictement identique) — gain croissant avec la taille du socle. **Étape 4 (BFS wavefront)
BENCHÉE ET RÉFUTÉE** : prototype prouvé équivalent mais **plus lent à move_range=12** (le régime réel du
training, mesuré) ; le BFS deque n'y coûte que 0,30 ms. **Nouveau hotspot mesuré (cProfile ez=2)** : la
boucle Python sur les ~200 offsets de `_dilate`/`_spread` (ovale, ~60 % du build) → levier **L2**
(numba OU runs NumPy), que le §8 avait cru caduc. **Décision de périmètre en attente utilisateur** (L2a
numba / L2b runs NumPy / L3 fenêtrer le corps `_build`) — cf. `V11_move_build_acceleration.md §10`.

## 0bis. Pièges et leçons de méthode — 📌 SECTION CANONIQUE

> **Éditer les avertissements ICI.** Chacun est reproduit **mot pour mot** depuis son entrée
> d'origine, dont la référence est donnée. Les occurrences restées dans §0hist en sont des
> **copies** : elles y documentent le raisonnement local, mais la version qui fait foi est
> celle de cette section.
>
> Ces passages existent pour **empêcher de re-diagnostiquer un faux problème**. Aucun ne doit
> être résumé ni supprimé, même si l'entrée dont il vient est close.

### Sur ce document lui-même (§0.-1, §0.0)


**Réserve de méthode — ce qui n'a pas été revérifié (§0.0)**

**⚠️ Réserve de méthode sur ce document.** Les sections §0.x reflètent ce qui a été relu et
exécuté pendant la session du 2026-07-19 soir. **Le reste du document — T1 à T5, section 9 — n'a
PAS été revérifié ligne à ligne contre le code.** Trois affirmations périmées y ont été trouvées
et corrigées ce soir-là (« prochain bloqueur §10.4 » alors qu'il était résolu, « archivage des
holdouts à faire » alors qu'il l'était, « 9 échecs préexistants » alors que la suite est verte) —
**il peut en rester d'autres du même genre**. Vérifier dans le code avant de s'appuyer sur une
affirmation de ce document qui n'est pas datée de la session en cours.

➜ **Cette réserve est désormais une TÂCHE : voir §0.19** (méthode d'audit et historique des
démentis). Tant qu'elle n'est pas menée, la mise en garde ci-dessus reste pleinement valable.

➜ **Passe menée le 2026-07-20 : voir §0.19.1.** T2/T3/T4/T5 sont verrouillés par mutation-test ;
**T1 est repassée en ⏳** (R6 site 1 inatteignable au x5, R4 sans aucun test) ; la section 9 n'a
jamais été marquée ✅ (c'est un plan). La réserve reste valable pour **T1/R4**, dont le
mutation-test n'a pas pu être mené (`shared_utils.py` sous instrumentation §0.18), et pour §7/§10
qui n'ont **pas** été audités.

**Comptages de tests : le seul verdict disponible est le code de sortie (§0.-1)**

⚠️ **Chiffre daté du 2026-07-19** — la suite a grossi depuis (+6 tests le 2026-07-20 : 4 en
§0.10, 2 en §0.13). **Ne pas traiter `1402` comme un compte à retrouver** : le reporter du
projet n'imprime pas la ligne de résumé de pytest, le seul verdict disponible est le **code de
sortie** (`exit 0`, vérifié après chaque lot du 2026-07-20).

**La règle de périmètre `ArmageddonAgent` et les 10 fichiers `CoreAgent` verts (§0.-1)**

⚠️ **10 fichiers de tests contiennent encore la chaîne `CoreAgent` et sont VERTS — c'est
normal.** Audités **un par un** (et non par échantillon — la première vérification avait manqué
`test_board_ref_resolver.py` ci-dessus en généralisant depuis 3 fichiers de `tests/unit/ai/`
alors que le seul cas fautif était dans `tests/unit/engine/`) : ce sont des chaînes passées à des
fonctions **pures** (`_load_bot_eval_params`, `build_agent_model_path`, `_scenario_name_from_file`),
des stubs (`SimpleNamespace`, `_DummyCfgLoader`, `_Cfg`), des arborescences **synthétiques dans
`tmp_path`**, ou de simples commentaires. **Aucun n'atteint la vraie config.** Ne pas les
« corriger » par un `sed` global.

**Leçon de méthode** : « vérifié un par un » sur un échantillon n'est pas une vérification.
Le seul contre-exemple était dans le répertoire non échantillonné.

### Sur le raisonnement et la preuve


**Une invariance est CONDITIONNELLE à son état initial (§0.1)**

**⚠️ Corollaire — une affirmation de ce document était fausse.** L'ancien §0 affirmait que
`require_coherency` est « invariante par translation cube, donc déjà garantie par le pool
d'ancre ». L'invariance est réelle mais **conditionnelle** : elle prouve *si l'origine est
cohérente, le plan l'est*. Elle ne prouve **rien** quand l'origine est déjà incohérente — et dans
ce cas le pool entier est offert alors que rien n'est exécutable. C'est cette demi-vérité qui a
laissé le trou ouvert après T6-g. **Toute contrainte « prouvée invariante » doit être relue en se
demandant : invariante à partir de quel état initial ?**

**Vérifier qu'un point d'ancrage est APPELÉ avant d'y brancher quoi que ce soit (§0.1)**

⚠️ **Piège rencontré, à ne pas refaire** : le premier branchement a été posé en tête de
`_advance_to_next_player`, qui *semble* être la frontière de tour mais est **du code mort**
(cf. §0.4). Le run de vérification a reproduit le crash à l'identique. **Vérifier qu'un point
d'ancrage est appelé AVANT d'y brancher quoi que ce soit.**

**Motif récurrent : du code correct, testé, et jamais appelé (§0.4)**

> **Motif récurrent à surveiller dans ce projet** — six occurrences vérifiées à ce jour.
> **Cinq de type « jamais appelé »** : `update_frozen_model` (§10.4),
> `end_of_turn_coherency_removal` (§0.1), `_advance_to_next_player` (§0.4),
> `game_replay_logger` (§0.8, 795 lignes + 8 tests), `log_unified_action` (§0.8). Du code
> correct, testé, et jamais appelé. **Devant toute fonction sur laquelle repose un
> raisonnement, vérifier d'abord qu'elle a un appelant.**
>
> **Une de type « jamais exercé »** (§0.11) : `test_move_mask_is_executable.py` est appelé, vert,
> et mesure le bon invariant sur le bon scénario — mais par exploration aléatoire, donc il ne
> visite jamais la configuration qui cassait. **Un test vert ne couvre que les états qu'il
> atteint ; sa docstring peut affirmer le contraire de bonne foi.**

**Un test qui explore au hasard ne prouve rien sur ce qu'il n'atteint pas (§0.11)**

🔴 **Pourquoi `test_move_mask_is_executable.py` n'a rien vu** — c'est le point le plus important
de cette entrée. Ce fichier mesure **cet invariant exact**, sur **ce scénario exact**, et il est
vert. Il ne vérifie l'invariant que sur les états atteints par **exploration aléatoire** (3 seeds,
400 steps) : la superposition inter-étages n'y survient jamais. Sa docstring affirme pourtant
combler précisément ce trou (« Ce test remplace ce raisonnement par une mesure »).

> **Quatrième variante du motif §0.4, et la plus sournoise.** Les trois premières étaient du code
> *jamais appelé*. Celle-ci est du code appelé, par un test vert, qui **n'exerce jamais le cas**.
> Un test qui explore au hasard ne prouve rien sur les configurations qu'il n'atteint pas — et sa
> docstring peut affirmer le contraire en toute bonne foi. **Devant un test de type « je déroule
> des parties et je vérifie un invariant », toujours se demander quelles configurations il ne
> visite jamais, et les construire explicitement.**

**Ne pas conclure à un biais de tirage sur quelques dizaines d'observations (§0.10)**

Mesuré sur **400 resets** : Ork/Ork 102 (25,5 %), Ork/SM 107 (26,8 %), SM/SM 104 (26,0 %),
SM/Ork 87 (21,8 %) — **les 4 matchups, équiprobables** (χ² = 2,38 pour un seuil de 7,81 à 3 ddl :
aucun biais détectable). Un premier tir de 40 resets donnait 15/13/9/**3** et laissait craindre un
biais : c'était du **bruit d'échantillonnage**, pas un bug. Leçon : ne pas conclure à un biais de
tirage sur quelques dizaines d'observations — refaire la mesure en grand avant de diagnostiquer.

> **Bandeau de fiabilité du recensement d'ancre** — il vit en **§1bis, « Dette d'ancre restante »**
> et n'a pas été déplacé : seuls 4 sites y ont été relus à la main, le reste est un faisceau
> d'indices. **Ne pas ouvrir de chantier depuis une ligne non marquée ✅ sans avoir lu la
> fonction.** Le lire avant d'exploiter ce recensement.

### Sur les runs et l'outillage


**Un run qui passe ne prouve pas une non-régression sur un crash stochastique (§0.18)**

🔴 **Erreur commise le 2026-07-20, à ne pas refaire.** Un run de 500 épisodes a franchi
l'épisode ~250 sans le crash `collision intra-plan`, et on en a conclu — **par écrit, dans ce
document** — que la non-régression §0.11 était « validée en bout-en-bout ». Un **second run,
même commande**, a crashé à l'épisode ~280. Le crash dépend de la **trajectoire**, donc du
hasard : un run vert est un **échantillon de taille 1**, pas une preuve.

Règle : pour un crash dont le déclenchement dépend de la trajectoire, une non-régression se
prouve par un **test qui reproduit la condition**, ou à défaut par **plusieurs runs**, jamais
par un seul run vert. Et **tout changement de code qui touche l'observation ou le reward change
les trajectoires** — un run vert d'avant le changement ne dit rien du code d'après.

**L'ETA affichée au premier épisode est un artefact de warmup (§0.13)**

⚠️ **Piège de perf, à ne pas re-diagnostiquer** : l'ETA affichée au 1ᵉʳ épisode (~16 h 45 sur le
run de 1000) est un **artefact de warmup** ; elle retombe à sa vraie valeur dès le 10ᵉ épisode.
Ne jamais extrapoler une durée de run depuis les premiers épisodes.

**Ce que `x5_debug` ne produit PAS, et pourquoi il ne se lance pas seul (§0.10)**

**Piège de lancement, préexistant** : `--training-config x5_debug` **seul** échoue pour cet agent
(`No scenario file found … scenario_x5_debug.json`). ArmageddonAgent n'a que
`scenario_training_armageddon.json`, donc `--scenario <chemin explicite>` est **obligatoire** :
```
python3 ai/train.py --agent ArmageddonAgent --training-config x5_debug \
  --scenario config/agents/ArmageddonAgent/scenarios/training/scenario_training_armageddon.json \
  --new --resolution 5
```
⚠️ `x5_debug` = **1000 épisodes** (~2h50 à 8 envs), pas un run de quelques minutes malgré son nom.

⚠️ **Ce que `x5_debug` ne produit PAS**, à cause de ses `callback_params` :
`save_best_min_episodes = 10000` et `checkpoint_save_freq = 10000` sont **supérieurs** à ses
1000 épisodes → **ni « best model » ni checkpoint** ne sont jamais écrits. `model_gating_enabled`
est `False` (le `Gate 🧱` de la barre de progression est purement décoratif) et `bot_eval_final`
vaut **1** épisode par bot — contre 60 pour le run de §0.7. C'est un run de **validation de
pipeline**, pas de mesure : il ne peut pas servir le critère §10.6.

**Tout run `x5_debug` ÉCRASE le modèle canonique (§0.0)**

- ⚠️ **Le modèle en place a été ÉCRASÉ par ce run** (`model_ArmageddonAgent.zip`, 2026-07-20
  02:14 — autorisation utilisateur explicite). C'est donc un modèle **de debug, 100 épisodes
  `--new`**, sans valeur de jeu : `save_best_robust: false` fait que
  [train.py:3548](../../ai/train.py#L3548) écrit le modèle final **inconditionnellement** en fin
  de run. Le modèle précédent (19/07 04:25, entraîné AVANT les `VALUE` Munitorum, avec la
  `WarTrakk` à 175) reste disponible dans
  `ai/models/_backup_pre_munitorum_20260719_232816/` — **vérifié intact après le run**.
  ⚠️ Tout run `x5_debug` ultérieur écrasera à nouveau le modèle canonique : sauvegarder avant
  si le modèle en place compte.

**`config/users.db` réapparaît modifié après chaque run (§0.0, dette 5)**

⚠️ `config/users.db` **réapparaît modifié** après chaque run d'entraînement — fichier
**protégé** (CLAUDE.md), ne JAMAIS l'inclure dans un commit.

**`bot_eval_scenario_pool` placé au mauvais niveau est silencieusement ignoré (§0.13)**

⚠️ **Piège latent voisin, découvert au passage.** Dans
`ArmageddonAgent_training_config.json`, `bot_eval_scenario_pool` est placé à la **racine** de
`x5_debug`, alors que `_resolve_callback_value` ([train.py:3273](../../ai/train.py#L3273)) le
cherche dans **`callback_params`** puis retombe sur `config/agents/_training_common.json`.
La clé racine est donc **ignorée**. Sans effet aujourd'hui (les deux valent `holdout`), mais
toute surcharge par agent placée à la racine serait **silencieusement sans effet**.

**`agent_roster_seed` neutralise le tirage de roster sans le moindre message (§0.10)**

⚠️ **Piège latent voisin — `agent_roster_seed`.** Cette clé de scénario est passée en
`random_seed` au tirage du roster AGENT ([game_state.py:1056](../../engine/game_state.py#L1056)),
et le RNG est reconstruit à chaque appel (`random.Random(seed)`,
[:1142](../../engine/game_state.py#L1142)). Si elle est renseignée, **le roster agent devient
identique à tous les épisodes** — le tirage est neutralisé sans le moindre message. Voulu pour les
scénarios holdout `bot-01..04` (qui la portent, pour la reproductibilité), mais ce serait un piège
silencieux dans un scénario d'entraînement. `scenario_training_armageddon.json` ne la porte pas
(`None`) : vérifié. **À contrôler avant de conclure quoi que ce soit sur une distribution de
matchups.**

**Une suite de tests est une mesure GLOBALE, donc un verrou GLOBAL (§0.19.1, 2026-07-20)**

🔴 **Trois mesures de suite invalidées le même jour, par trois écrivains différents.** Le partage
du dépôt « par fichier » ne protège **rien** : deux agents peuvent éditer des fichiers disjoints
sans conflit, mais ils **ne peuvent pas mesurer en parallèle**, parce qu'une suite lit tout
l'arbre.

| # | Écrivain pendant la mesure | Conséquence |
|---|---|---|
| 1 | **moi-même** : baseline lancée pendant que je mutais 5 fichiers | tuée, non exploitée |
| 2 | **la chasse §0.18** : `shared_utils.py` à 20:14:31 et son test à 20:13:58 pendant une suite de 20:05→20:45 | un `EXIT=1` pris à tort pour un « rouge attendu permanent » |
| 3 | **l'agent concurrent** : `shared_utils.py` à 21:20:33 pendant une suite de 21:17:37→21:22:54 | un `EXIT=0` non exploitable |

**Règle.** Avant de conclure d'un résultat de suite, **relever le `mtime` des fichiers de
`engine/` avant ET après le run** ; tout fichier écrit dans la fenêtre invalide la mesure.
Une consigne « ne modifie pas tel fichier » donnée à un agent **ne suffit pas** si l'autre côté
y écrit : il faut soit interdire les suites complètes, soit geler les écritures pendant la
mesure. ⚠️ Corollaire : `EXIT=0` **et** `EXIT=1` sont également suspects — le n°2 a produit un
faux rouge, le n°3 un vert non fiable. Ne pas ne se méfier que des rouges.

⚠️ **Ne JAMAIS restaurer par `git checkout` un fichier portant du travail non commité d'un
autre agent** (`shared_utils.py`, `w40k_core.py` au 2026-07-20) : la restauration détruirait ses
modifications. Pour un mutation-test sur ces fichiers, sauvegarder par `cp` et restaurer par `cp`.

### Sur les données et les sources officielles


**🔒 Règle métier : `VALUE` suit le Munitorum, ce n'est pas une variable de tuning (§0.9)**

🔒 **RÈGLE MÉTIER (utilisateur, 2026-07-20) — NON NÉGOCIABLE.** `VALUE` **suit les documents
officiels**. Ce n'est pas une variable de tuning. `VALUE` est pourtant consommé **par figurine**
(pondération de menace [reward_calculator.py:1442](../../engine/reward_calculator.py#L1442),
différentiel d'armée [observation_builder.py:367](../../engine/observation_builder.py#L367)) : cet
effet sur l'apprentissage est une **conséquence à assumer**, jamais un motif pour s'écarter du
Munitorum. **Ne pas « rééquilibrer » ces valeurs pour améliorer un résultat d'entraînement.**

**Les PDF Munitorum ne sont pas extractibles en texte (§0.9)**

⚠️ **Le texte de ces PDF n'est pas extractible** (contenu en image : `extract_text()` ne rend que
les en-têtes). Il faut les **rendre en PNG** (`fitz`/pymupdf, dpi≥140) et les lire visuellement.
Ne pas conclure « le PDF est vide ».

**Deux pièges de lecture des sources : Grot Orderly, contradiction Gretchin (§0.9)**

**Deux pièges de lecture des sources, à ne pas re-trébucher dessus :**
1. **Le Grot Infirmier n'est pas une figurine de jeu.** Datasheet Painboy : `UNIT COMPOSITION :
   1 Painboy`, `equipped with : … 1 Grot Orderly` → c'est de l'**équipement**. D'où 38 figurines
   physiques dans la boîte mais **37 modèles de jeu**. Le roster n'a rien qui manque.
2. **Contradiction entre deux sources officielles sur les Gretchin** : le Munitorum cote
   `11 models … 45 pts`, la datasheet dit `UNIT COMPOSITION : 10 Gretchin`. La boîte en a 10.
   Retenu : 10 modèles à 45 pts. Non tranchable depuis les documents — signalé, pas masqué.

**Limite x10 et point non tranché du fix de collision (§0.11)**

**Non tranché** : je n'ai pas l'état exact au moment du crash. Il est prouvé que le prédicat est
aveugle au niveau et qu'il produit ce message sur une configuration légale ; il n'est **pas**
prouvé que les deux figurines de l'escouade 3 étaient à des étages différents plutôt que dans un
état déjà illégal. Si un crash de cette classe réapparaît, dumper l'état avant de conclure.

**Limite connue, HORS PÉRIMÈTRE (décision utilisateur, 2026-07-20) : le cas x10.** Le contrôle
compare les **sous-hex d'ancre**. Sur Board ×10 les figurines ont une **empreinte multi-hex**
(`compute_candidate_footprint` — « Multi-hex footprints are only computed on Board ×10 ») : deux
socles peuvent donc s'y chevaucher **sans partager leur ancre**, et la même classe d'incohérence
masque/exécution reste ouverte à cette résolution. Sur x5 (résolution du training) l'empreinte
vaut le sous-hex, le contrôle est **exact**. Limite préexistante, non introduite par le correctif.
⚠️ Ne pas lire « l'invariant est rétabli » comme valant pour toutes les résolutions : il vaut
pour x1 et x5. **On ne s'occupe pas de x10** — si le projet y vient un jour, rouvrir ce point
AVANT d'y lancer un entraînement.

### Affirmations périmées repérées le 2026-07-20 — **signalées, NON corrigées**

> Relevées pendant la réorganisation de §0. Aucune n'a été « nettoyée » : les corriger sans
> relire le code reproduirait exactement l'erreur qu'elles illustrent. **Vérifier avant de
> s'appuyer sur l'une d'elles.** C'est le motif récurrent n°1 de ce document — au moins
> 5 avaient déjà été trouvées lors des sessions précédentes.

| # | Où | Affirmation | Pourquoi elle est suspecte |
|---|---|---|---|
| 1 | §0.-1 | « la suite est VERTE : `1402 passed, 2 skipped` » | Son propre ⚠️ la déclare datée. Le document porte aussi `1407`, `1440`, `1451`, `1396`, `1398` selon l'endroit. Seul verdict fiable : le code de sortie. |
| 2 | §5 / tableau T6-i | « ❌ test de non-régression **NON écrit** » | `tests/unit/engine/test_end_of_turn_coherency_03_03.py` **existe sur le disque** (vérifié le 2026-07-20) et §0.0 le déclare livré. |
| 3 | §5 / tableau T6 | « le critère T6 est désormais bloqué par `CC_DMG` (§0.3) qui plante des épisodes d'évaluation » | Le portage §0.3 est fait et le run 60/60 de §0.7 le valide runtime. |
| 4 | §10.5 (bandeau) | « ⚠️ Non validé runtime — cf. §0.3 (`CC_DMG`) » | Levé par §0.7 (`TacticalBot` 10/10 épisodes). |
| 5 | §0.10 | « la dette notée en **§0.0** (`--scenario bot` échoue en amont du moteur) » | Cette dette est écrite dans **§0.7**, pas §0.0. Renvoi imprécis, non corrigé. |
| 6 | §0.12, étape 4 | « **9 tests** liés à `roster_pool_schedule` échouent indépendamment de ce travail » | ✅ **TRANCHÉ le 2026-07-20 — l'affirmation était FAUSSE.** Suite complète lancée : **1417 passed, 2 skipped, 0 failed**. Aucun échec `roster_pool_schedule`. §0.-1 avait raison : un test rouge est une régression, il n'y a pas d'échec préexistant à tolérer. |
| 7 | §2 « État des lieux vérifié » | « Tous les imports du pipeline passent (`ai.train`, `ai.env_wrappers`, **`ai.multi_agent_trainer`**, …) » | `ai/multi_agent_trainer.py` **n'existe plus** (supprimé en §0.8, vérifié absent du disque le 2026-07-20). |
| 8 | §0.17 (par construction) | l'état de commit | Périmé dès le prochain `git commit` — l'entrée porte elle-même l'ordre de la reconfronter à `git status`. |
| 10 | §0.18, note annexe | « après ce crash le process … s'est terminé avec un **code de sortie 0** » | ❌ **FAUSSE, tranchée le 2026-07-20 — voir §0.20.** Le handler `return 1`, `sys.exit` propage, et l'exécution confirme `EXIT=1`. Cause probable : un pipe (`| tee`) côté shell lors de la mesure. Enseignement : une note **« hors périmètre »** échappe à la relecture *parce qu'*elle est marquée annexe. |
| 11-13 | §6 (T2, T4), §8.2 | layout d'actions « 41 », « 61 scénarios », `test_agent_interface_contract.py` | ➜ **détaillées en §0.19.1** (audit du 2026-07-20). Signalées, NON corrigées. |
| 9 | §0.14 (rédigée puis **corrigée le même jour**) | « Non-régression §0.11 ✅ **VALIDÉE EN BOUT-EN-BOUT** » | ❌ **FAUSSE, retirée le 2026-07-20** — cf. §0.18 : le run suivant a crashé sur ce même message. Cas d'école : l'affirmation a été produite **par l'auteur du run lui-même**, le jour même, à partir d'un unique run vert. Le motif n°1 de ce document ne vient pas que du passé. |

---

## 0ter. Notes post-implémentation — décisions assumées, non-travaux

> Choses **tranchées et closes** qui ne sont ni des bugs ni des dettes : des décisions de
> périmètre que l'utilisateur assume. À ne pas rouvrir comme des réserves.

- **§0.16(b) — `DefensiveSmartBot` reste hors éval (status quo, 2026-07-21).** Retiré à l'origine
  parce qu'il **sous-performait**. Conséquence acceptée : son unique appelant
  `_best_target_slot_by_threat` (7ᵉ site porté) n'est validé que par un **test unitaire**, jamais
  en éval runtime. Le réintroduire pour la seule couverture fausserait la composition d'éval
  (`combined`, poids) sans bénéfice. **Ne pas re-signaler comme un trou de couverture.**
- **§0.16(c) — clé `holdout_hard_opponent_budget_modifier` + `build_holdout_benchmark.py` gardés
  (2026-07-21).** Non consommés par le training actuel (2 rosters fixes, §10.2), mais **conservés
  volontairement** : un holdout à armées **générées** est prévu **après la démo**. La clé est en
  attente d'usage, pas morte. **Ne pas supprimer ni la clé ni le script.**

---

## 0hist. Historique résolu

> Entrées closes, **conservées intégralement** : mesures, sorties de run copiées, tableaux de
> sites audités, diagnostics d'origine et attributions erronées assumées. Rien n'y est résumé.
> Les titres et ancres `### 0.x` sont **inchangés** : tous les renvois `§0.x` du reste du
> document restent valides.
>
> Les entrées **scindées** (§0.0, §0.5, §0.6, §0.7, §0.13) portent un renvoi `➜` à l'endroit
> exact d'où leur part ouverte a été déplacée.
>
> ⚠️ Ces entrées décrivent l'état **au moment où elles ont été écrites**. Plusieurs contiennent
> des affirmations que leurs propres auteurs ont ensuite corrigées sur place. Ne pas s'appuyer
> sur l'une d'elles sans la confronter au code.


### 0.-1 🟢 PÉRIMÈTRE ET BASELINE (2026-07-19 soir) — LIRE AVANT TOUT

**Règle de périmètre (décision utilisateur 2026-07-19)** : on ne s'occupe **QUE** de
`config/agents/ArmageddonAgent`. `config/agents/CoreAgent` est **hors périmètre** — ne rien y
lire, ni y écrire, ni s'en servir comme référence.

⚠️ **Chiffre daté du 2026-07-19** — la suite a grossi depuis (+6 tests le 2026-07-20 : 4 en
§0.10, 2 en §0.13). **Ne pas traiter `1402` comme un compte à retrouver** : le reporter du
projet n'imprime pas la ligne de résumé de pytest, le seul verdict disponible est le **code de
sortie** (`exit 0`, vérifié après chaque lot du 2026-07-20).

**La suite est VERTE : `1402 passed, 2 skipped, 0 failed`.** C'est la nouvelle baseline. Toute
mention ailleurs dans ce document de « 9 échecs préexistants » est **PÉRIMÉE** : ces 9 échecs
venaient de l'ancienne banque CoreAgent, retirée le 2026-07-19.

⚠️ **Il n'y a plus d'échec « préexistant » à tolérer.** Un test rouge est désormais une
régression, sans exception.

**Ce qui a été fait pour y arriver** : la suppression de la banque CoreAgent a emporté
`CoreAgent_training_config.json`, utilisé comme **fixture** par 9 fichiers de tests **moteur**
(et non comme « l'agent CoreAgent ») — la suite est passée de 9 à **41** échecs, dont les 3 tests
de `test_move_mask_is_executable.py` qui gardent l'invariant « masque ⊆ exécutable ». Les 8
fichiers ont été **repointés sur `ArmageddonAgent`** (clé d'agent + `rewards_config` + scénario) :

| Fichier | Changement |
|---|---|
| `test_move_mask_is_executable.py`, `test_deployment_per_model_commit.py`, `test_deploy_pool_terrain_zones.py`, `test_deployment_clearance_parity.py` | scénario → `scenarios/training/scenario_training_armageddon.json` |
| `test_squad_fight_v11_state.py`, `test_squad_fight_target_parity.py`, `test_t5_bare_loop.py` | clé d'agent seule (ils fabriquent leur scénario) |
| `test_scenario_bank_migration_v11.py` | les tests du **script** de migration sont conservés ; la partie « banque » vise désormais la banque ArmageddonAgent (**5** scénarios : 1 training + 4 holdout, au lieu de 61) et l'échantillon chargé de bout en bout a été réécrit |

**Effet de bord bénéfique** : les 5 tests de déploiement qui faisaient partie des « 9
préexistants » sont **maintenant verts** — ils échouaient sur les rosters manquants, et
`ArmageddonAgent` les résout.

**9e fichier repointé — `test_board_ref_resolver.py`** : son `BANK_SCEN` pointait sur
`CoreAgent/scenarios/training/scenario_training_bot-01.json`, **supprimé du disque**. Ses 8 tests
restaient VERTS parce que `_resolve_board_dir` ([game_state.py:1630](../../engine/game_state.py#L1630))
ne fait que **parser le chemin comme une chaîne**, sans jamais ouvrir le fichier. Les tests ne sont
pas creux (la logique du resolver est réellement exercée) mais la fixture était **mensongère** :
le jour où quelqu'un ajoute un `is_file()` dans le resolver, 8 tests tombent pour une mauvaise
raison. Repointé sur `ArmageddonAgent/scenarios/training/scenario_training_armageddon.json`.

⚠️ **10 fichiers de tests contiennent encore la chaîne `CoreAgent` et sont VERTS — c'est
normal.** Audités **un par un** (et non par échantillon — la première vérification avait manqué
`test_board_ref_resolver.py` ci-dessus en généralisant depuis 3 fichiers de `tests/unit/ai/`
alors que le seul cas fautif était dans `tests/unit/engine/`) : ce sont des chaînes passées à des
fonctions **pures** (`_load_bot_eval_params`, `build_agent_model_path`, `_scenario_name_from_file`),
des stubs (`SimpleNamespace`, `_DummyCfgLoader`, `_Cfg`), des arborescences **synthétiques dans
`tmp_path`**, ou de simples commentaires. **Aucun n'atteint la vraie config.** Ne pas les
« corriger » par un `sed` global.

**Leçon de méthode** : « vérifié un par un » sur un échantillon n'est pas une vérification.
Le seul contre-exemple était dans le répertoire non échantillonné.


### 0.0 Ce qu'il faut faire ENSUITE, dans cet ordre (session du 2026-07-19 soir)

**L'ordre est imposé** : le fix moteur T6-i vient de bouger deux fois (branchement déplacé), donc
il doit être verrouillé par un test AVANT qu'un chantier indépendant y touche.

| # | Tâche | État |
|---|---|---|
| 1 | **Test de non-régression 03.03** (§8 : « une règle = son fichier de tests ») | ✅ FAIT — `tests/unit/engine/test_end_of_turn_coherency_03_03.py`, 11 tests. (a) retour en coherency après la fin de tour ; (b) retrait **une à une**, minimal, et **jamais la dernière figurine** ; (c) `reason='coherency_removal'` (spy sur `destroy_model`) + aucun compteur de kills touché ; (d) **les DEUX chemins** paramétrés (`_fight_phase_complete` ET `_fight_v11_phase_complete`), plus un test que l'étape précède le test de limite de tour. **Mutation-testé** : neutraliser les deux appels rend 4 tests rouges. |
| 2 | **Portage `CC_DMG`/`RNG_DMG` des bots vers le système multi-armes** | ✅ FAIT — 7 sites d'`ai/evaluation_bots.py` portés sur `get_max_ranged_damage`/`get_max_melee_damage`. Voir §0.3 (attribution corrigée). |
| 3 | **Code mort : `_advance_to_next_player`** | ✅ FAIT — supprimé, avec ses **8** tests **et** l'îlot mort qu'il maintenait en vie. Voir §0.4. |

**Éval relancée le 2026-07-19 après le portage — ✅ 60/60 épisodes, voir §0.7.** Elle valide le
portage `CC_DMG` sur les 6 sites `TacticalBot` et **lève** le « §10.5 non validé runtime ». Elle a
aussi établi que le motif d'exclusion du holdout écrit en §10.5 était **empiriquement faux**
(`TacticalBot` n'est PAS le bot le plus fort : 0.60, 2ᵉ meilleur score) — corrigé sur place.
Les tâches 1-3 sont commitées (`6a7a9de1`).

**Reste ouvert** :
- ~~🔴 **Déséquilibre 824 vs 690 points** (§0.6)~~ ✅ **SOLDÉ (§0.9, 2026-07-20)** : il n'y avait
  pas de déséquilibre de listes. Aux points Munitorum, **680 vs 680**. Le +19 % venait de 3 `VALUE`
  fausses (`WarTrakk` 175 au lieu de 60 à elle seule +115). Le critère §10.6 n'est plus bloqué.
- ~~🔴 **`--scenario bot` entraîne sur le holdout** pour cet agent (§0.10)~~ ✅ **CORRIGÉ
  (2026-07-20)** : `bot`/`self` restreints à `training/`, +4 tests de non-régression.
> ➜ **Déplacé en §0.14 (ouvert).** Rien n'a été supprimé : le contenu est intégral là-bas.
- ⚠️ **Le modèle en place a été ÉCRASÉ par ce run** (`model_ArmageddonAgent.zip`, 2026-07-20
  02:14 — autorisation utilisateur explicite). C'est donc un modèle **de debug, 100 épisodes
  `--new`**, sans valeur de jeu : `save_best_robust: false` fait que
  [train.py:3548](../../ai/train.py#L3548) écrit le modèle final **inconditionnellement** en fin
  de run. Le modèle précédent (19/07 04:25, entraîné AVANT les `VALUE` Munitorum, avec la
  `WarTrakk` à 175) reste disponible dans
  `ai/models/_backup_pre_munitorum_20260719_232816/` — **vérifié intact après le run**.
  ⚠️ Tout run `x5_debug` ultérieur écrasera à nouveau le modèle canonique : sauvegarder avant
  si le modèle en place compte.
> ➜ **Déplacé en §0.16 (ouvert).** Rien n'a été supprimé : le contenu est intégral là-bas.
- ~~Dette `ai/game_replay_logger.py` (~8 sites `RNG_DMG`/`CC_DMG`) + `config/unit_definitions.json`.~~
  ✅ **soldée (§0.8)** : module supprimé, pas porté.
- ~~Purge de `multi_agent_trainer.py` / `--orchestrate`~~ ✅ **faite (§0.8)**, module supprimé.
- ~~Bug d'affichage `Total: 30` au lieu de 60~~ ✅ corrigé (§0.7, constat 2).

**⚠️ L'état de fin de session n'est ni « OK » ni « optimal ».** Mise à jour 2026-07-19 (fin de
session tâches 1-3) : suite toujours verte, **exit 0 sur 1407 tests collectés** (1404 + 11 nouveaux
− 8 supprimés). ⚠️ Le compte exact « passed/skipped » n'est **pas** vérifiable ici : le reporter du
projet n'imprime pas la ligne de résumé de pytest — le seul verdict disponible est le code de
sortie. Ne pas recopier un « N passed » sans l'avoir vu.

Constat d'origine — ce qui était solide : suite verte
scellée par un run (`1402 passed, 2 skipped`), fix 03.03 livré et vérifié bout-en-bout, fail-fast
de l'éval, tests repointés, doc à jour. Ce qui ne l'est pas — **les 6 dettes ouvertes** :

| # | Dette ouverte | Pourquoi ça compte |
|---|---|---|
| 1 | ~~**Test 03.03 non écrit**~~ ✅ **FERMÉE** | Verrouillée par `test_end_of_turn_coherency_03_03.py` (11 tests, mutation-testés). |
| 2 | ~~**`CC_DMG` plante 2 épisodes sur 48**~~ ✅ **PORTÉ** — mais **non re-mesuré** | Le code ne lit plus les champs supprimés ; le run `--eval` qui prouve 48/48 **reste à faire**. Ne pas cocher §10.6 avant. |
| 3 | ~~**`_advance_to_next_player` toujours présent**~~ ✅ **SUPPRIMÉ** | Cf. §0.4. |
| 4 | ~~**Déséquilibre 824 vs 690 points** (Orks/SM, +19 %)~~ ✅ **SOLDÉ (§0.9)** | Artefact de 3 `VALUE` fausses, pas un déséquilibre de listes. Points Munitorum : **680 vs 680**. §10.6 débloqué. |
| 5 | **Rien n'est commité** | ➜ **Déplacé en §0.17 (ouvert)** — cette dette est périssable, son état à jour est en §0.17. |

| 6 | ~~🔴 **Le reward de combat ignore la `VALUE` par figurine**~~ | ➜ ✅ **FERMÉE le 2026-07-20 — voir §0.12** (A/B/C **+ D** livrés, 14 tests mutation-testés, suite 1417 verte). |

**⚠️ Réserve de méthode sur ce document.** Les sections §0.x reflètent ce qui a été relu et
exécuté pendant la session du 2026-07-19 soir. **Le reste du document — T1 à T5, section 9 — n'a
PAS été revérifié ligne à ligne contre le code.** Trois affirmations périmées y ont été trouvées
et corrigées ce soir-là (« prochain bloqueur §10.4 » alors qu'il était résolu, « archivage des
holdouts à faire » alors qu'il l'était, « 9 échecs préexistants » alors que la suite est verte) —
**il peut en rester d'autres du même genre**. Vérifier dans le code avant de s'appuyer sur une
affirmation de ce document qui n'est pas datée de la session en cours.


### 0.1 T6-i — REGAINING COHERENCY (03.03) — ✅ FAIT (2026-07-19 soir)

**Root cause d'une classe entière de crashes `incohérence masque/exécution`.** Mesuré :
8 épisodes plantés → **2**, et l'erreur a **totalement disparu** de l'éval `ArmageddonAgent`.

Enchaînement, chaque maillon vérifié :

1. Des figurines meurent → la formation devient incohérente. **C'est légal pendant le tour**
   (03.03 n'impose la coherency qu'au *set up* et à la *fin d'un move*).
2. L'étape End of Turn qui doit résorber cet état n'était **jamais exécutée** :
   `end_of_turn_coherency_removal` (shared_utils) était implémentée et conforme, avec **zéro
   appelant**. L'incohérence survivait donc au tour.
3. Phase de mouvement suivante : `build_rigid_plan` translate le bloc rigidement, ce qui
   **préserve** l'incohérence.
4. `validate_move_plan` rejette le plan — à raison (03.03 « must end any kind of move in
   coherency »).
5. Le pool BFS du masque, construit sur l'**ancre** et sans check de coherency, offre pourtant
   toutes les destinations. Aucune n'est exécutable → `incohérence masque/exécution`.

**⚠️ Corollaire — une affirmation de ce document était fausse.** L'ancien §0 affirmait que
`require_coherency` est « invariante par translation cube, donc déjà garantie par le pool
d'ancre ». L'invariance est réelle mais **conditionnelle** : elle prouve *si l'origine est
cohérente, le plan l'est*. Elle ne prouve **rien** quand l'origine est déjà incohérente — et dans
ce cas le pool entier est offert alors que rien n'est exécutable. C'est cette demi-vérité qui a
laissé le trou ouvert après T6-g. **Toute contrainte « prouvée invariante » doit être relue en se
demandant : invariante à partir de quel état initial ?**

**Où l'étape est branchée, et pourquoi pas ailleurs** : en tête des **deux** chemins de fin de
Fight (`_fight_v11_phase_complete` et `_fight_phase_complete`, tous deux vivants), **avant** le
test de limite de tour pour que l'état final de la partie respecte aussi la règle. Fight est la
dernière phase du tour. Le helper `end_of_turn_regain_coherency_all_squads` est partagé par les
deux chemins pour qu'ils ne puissent pas diverger, traite les escouades des **deux** joueurs
(la règle vise « units on the battlefield ») et itère en ordre trié — `destroy_model` mute les
caches sous l'itération, et les replays doivent rester rejouables.

⚠️ **Piège rencontré, à ne pas refaire** : le premier branchement a été posé en tête de
`_advance_to_next_player`, qui *semble* être la frontière de tour mais est **du code mort**
(cf. §0.4). Le run de vérification a reproduit le crash à l'identique. **Vérifier qu'un point
d'ancrage est appelé AVANT d'y brancher quoi que ce soit.**

⚠️ **Dette assumée (décision 2026-07-19)** : la règle laisse au joueur le **choix** des figurines
retirées ; le moteur choisit à sa place (la plus éloignée du centroïde, tie-break par index
croissant). Retenu pour les deux modes. L'écart n'est pas que positionnel : sur une escouade
**hétérogène**, un humain sacrifierait des figurines de base pour conserver une arme spéciale,
alors que le critère géométrique retire la figurine isolée — l'écart porte sur la **puissance
conservée**. Les retraits sont journalisés en console (`_log_end_of_turn_coherency_removals`)
pour qu'un joueur PvP ne voie pas des figurines disparaître sans explication. Une sélection
manuelle **remplacera** cet appel, elle ne s'y ajoutera pas.


### 0.2 Diagnostic des violations d'invariant — ✅ FAIT (2026-07-19 soir)

Le `ValueError` « incohérence masque/exécution » ne nommait pas la contrainte violée, ce qui
obligeait à re-deviner la cause à chaque occurrence (deux hypothèses fausses ont été explorées
avant d'instrumenter : `fall_back`/ER, puis double soustraction du coût de descente §13.06 —
**les deux innocentées**). Désormais :

- `validate_move_plan` **délègue** à `explain_move_plan_rejection`, qui renvoie la raison —
  une seule implémentation du check, le booléen n'en est que la façade. Aucune duplication
  (décision de design n°2).
- `build_move_blocked_cells_by_level` porte un **libellé par catégorie** (mur / ER ennemie /
  occupation d'une autre escouade). Il renvoie toujours une **liste** de `(label, set)`, jamais
  l'union — cf. l'avertissement de perf plus bas, inchangé.
- Le calcul de budget d'`execute_squad_move` est extrait dans `resolve_squad_move_constraints`,
  pour que le diagnostic évalue **exactement** les contraintes de l'exécution : les recalculer à
  la main à l'endroit de l'erreur produirait un diagnostic qui peut mentir.
- Le site d'erreur (w40k_core) rejoue ces helpers **sur le chemin d'erreur uniquement** (zéro
  coût nominal) et affiche `Contrainte violée : …`.

C'est ce diagnostic qui a donné la root cause en un run : les 12 occurrences portaient toutes
`coherency du plan invalide (formation actuelle DEJA incoherente)`.


### 0.3 `CC_DMG` — champ légacy lu par 2 bots — ✅ PORTÉ (2026-07-19 soir)

**Fait** : les **7** sites d'`ai/evaluation_bots.py` lisent désormais `RNG_WEAPONS`/`CC_WEAPONS`
via `get_max_ranged_damage`/`get_max_melee_damage` (même source que
`RewardMapper._get_unit_threat`). +2 tests (`test_evaluation_bots.py`) et les 2 fixtures légacy
existantes migrées ; les 4 tests sont **rouges sur le code d'avant**.

⚠️ **Deux corrections de fond au diagnostic ci-dessous, vérifiées dans le code** :

1. **L'attribution « `ControlBot`, ligne 674 » était fausse.** La ligne 674 est dans le helper
   module `_best_target_slot_by_threat`, dont l'**unique appelant** (grep) est
   **`DefensiveSmartBot`** — qui n'est PAS dans `bot_training.ratios`
   (random/greedy/defensive/control/aggressive_smart/adaptive). L'exposition était donc
   **l'évaluation, pas le training** : ce n'était pas la mine annoncée. Le raisonnement « bot à
   20 % du training » venait d'un numéro de ligne rattaché à la mauvaise classe.
2. **`RNG_DMG` est mort exactement comme `CC_DMG`** et était lu sur 3 des 7 sites. Traiter le seul
   `CC_DMG` aurait laissé la moitié du bug.

**Changement de sémantique assumé** : l'ancien seuil de charge de `TacticalBot`
(`CC_DMG >= 2`) portait sur un dégât **par touche**. Transposé tel quel sur `NB × DMG` il serait
vrai presque toujours. Le critère est donc devenu « dégâts mêlée attendus > dégâts de tir
attendus », ce que la docstring de la classe décrivait déjà (« charges if melee is advantageous »).

~~**Dette restante repérée au passage, NON traitée** : `ai/game_replay_logger.py` lit encore
`unit["RNG_DMG"]`/`unit["CC_DMG"]` (~8 sites) et `config/unit_definitions.json` les déclare encore
dans `required_properties`.~~ → **soldée en §0.8** : le module n'a pas été porté mais **supprimé**
(aucun appelant vif, aucun consommateur de sa sortie).

**Diagnostic d'origine (historique, attribution erronée conservée pour mémoire) :**

Les 2 épisodes encore plantés après T6-i le sont sur une cause **sans rapport** :

```
ConfigurationError: Required key 'CC_DMG' is missing from mapping
```

`CC_DMG` est un champ **supprimé par le refactor multi-armes**
([reward_mapper.py:22](../../ai/reward_mapper.py#L22) : « Replaces old RNG_DMG/CC_DMG fields »).
Vérifié : **0 des 237 fichiers d'unités TS** ne le définit — le champ n'existe plus à l'exécution.
Il est pourtant encore lu par `require_key` dans :

| Bot | Sites | Exposition |
|---|---|---|
| `TacticalBot` | [1142](../../ai/evaluation_bots.py#L1142), [1230](../../ai/evaluation_bots.py#L1230), [1266](../../ai/evaluation_bots.py#L1266), [1345](../../ai/evaluation_bots.py#L1345) | Éval seule (holdout) |
| `ControlBot` | [674](../../ai/evaluation_bots.py#L674) | **Éval ET TRAINING** — `ControlBot` pèse 20 % de `bot_training.ratios` |

⚠️ **`ControlBot` est le plus urgent** : son site est sur un chemin conditionnel rarement
exercé, donc il n'a pas encore pété — c'est une **mine**, pas un bug bénin. S'il est atteint en
entraînement, c'est un crash de training, pas seulement d'éval. **Le portage doit couvrir les
deux bots.**

C'est exactement la dette annoncée en §10.5 : « les autres bots ont été maintenus au fil des
refactors squad, celui-ci non ».

**⚠️ Correction d'une affirmation portée plus haut dans ce document** : « §10.5 validé runtime »
a été écrit à tort. `TacticalBot` n'avait complété que **4 épisodes sur 8** (W:1 L:2 D:1), les 4
autres ayant été attribués au bug de coherency **sans vérification**. La bonne lecture :
**§10.5 reste NON validé runtime** tant que `TacticalBot` ne complète pas ses épisodes une fois
`CC_DMG` porté. Et `0.25 sur 4 épisodes` n'est de toute façon pas une mesure.


### 0.4 Code mort qui a induit en erreur — `_advance_to_next_player` — ✅ SUPPRIMÉ (2026-07-19 soir)

**Fait** : la méthode et ses **8** tests sont supprimés (les « 12 références » du diagnostic
d'origine étaient des occurrences de grep, pas des tests — vérifié : 32 → 24 tests dans le
fichier). Le grep de vérification a montré que ce
n'était pas une fonction isolée mais un **îlot mort de 4 méthodes** : `_advance_to_next_player`
était l'unique appelant de `_movement_phase_init`, `_charge_phase_init` et `_fight_phase_init`
(ces deux dernières encore marquées `# TODO: Build … activation pool`, et
`_fight_phase_init` branchant sur `_charge_phase_init` à partir du **pool de tir** — du code de
l'ère pré-escouades). Les 4 sont supprimées ensemble. `_shooting_phase_init`, elle, est **vivante**
(appelée par le flux de phase move) et est conservée.

L'en-tête de `test_engine_turn_loop.py` porte désormais la raison de la suppression, pour qu'elle
ne soit pas relue comme une perte de couverture.

**Diagnostic d'origine (historique) :**

`_advance_to_next_player` (w40k_core) **n'a aucun appelant** — vérifié par grep sur `engine/`
et `ai/`. Elle contient pourtant toute la logique de bascule de joueur, d'incrément de tour et de
test de limite de tour, ce qui la fait passer pour LA frontière de tour. La vraie progression de
tour est dans `fight_handlers` (fin de phase de Fight, deux chemins).

**Et elle est couverte par des tests verts** : `tests/unit/engine/test_engine_turn_loop.py`,
12 références. Un fichier de tests vert sur une fonction que rien n'appelle est **le même piège**
qui a masqué `end_of_turn_coherency_removal` (§0.1) et `update_frozen_model` (§10.4) : il donne
au lecteur suivant la certitude que le chemin est vivant et correct.

~~**À traiter** : supprimer la fonction et ses tests~~ → fait, voir en tête de §0.4.

> **Motif récurrent à surveiller dans ce projet** — six occurrences vérifiées à ce jour.
> **Cinq de type « jamais appelé »** : `update_frozen_model` (§10.4),
> `end_of_turn_coherency_removal` (§0.1), `_advance_to_next_player` (§0.4),
> `game_replay_logger` (§0.8, 795 lignes + 8 tests), `log_unified_action` (§0.8). Du code
> correct, testé, et jamais appelé. **Devant toute fonction sur laquelle repose un
> raisonnement, vérifier d'abord qu'elle a un appelant.**
>
> **Une de type « jamais exercé »** (§0.11) : `test_move_mask_is_executable.py` est appelé, vert,
> et mesure le bon invariant sur le bon scénario — mais par exploration aléatoire, donc il ne
> visite jamais la configuration qui cassait. **Un test vert ne couvre que les états qu'il
> atteint ; sa docstring peut affirmer le contraire de bonne foi.**


### 0.5 Fail-fast de l'évaluation standalone — ✅ FAIT (2026-07-19 soir)

Un épisode planté était converti en `wins:0, losses:0, draws:0, failed_episodes:N`
([bot_evaluation.py:619-627](../../ai/bot_evaluation.py#L619-L627)) et le chemin `--eval`
publiait quand même un `Combined Score` — donc **une mesure sur échantillon tronqué par les
crashes, sans aucune mention**. Le win-rate n'était pas dilué (dénominateur = épisodes complétés),
mais le score final était publié sans signaler la troncature.

Le chemin **training** était déjà strict (`_apply_eval_results`, training_callbacks.py:2090-2096) :
c'est `--eval` qui était l'anomalie. Il reprend désormais le même check et lève avant toute
publication de score. **Décision** : ne PAS compter les crashes comme défaites — un crash moteur
n'est pas une défaite de l'agent, ça polluerait §10.6 avec du bruit d'infrastructure.

Conséquence voulue : **aucune mesure §10.6 ne passera tant qu'un bug plante des épisodes.**

> ➜ **Déplacé en §0.16 (ouvert).** Rien n'a été supprimé : le contenu est intégral là-bas.


### 0.6 Listes holdout mortes — ✅ FAIT (2026-07-19 soir)

`ArmageddonAgent_training_config.json` déclarait dans ses **5 phases**
`holdout_regular_scenarios: [bot-01..05]` et `holdout_hard_scenarios: [bot-01..05]` (recopie de
CoreAgent), alors que seuls 4 scénarios `holdout_regular` existent et **aucun** `holdout_hard`.
`_compute_holdout_split_metrics` retournait donc `{}` **silencieusement** : les 3 agrégats de
split étaient morts en permanence.

**Décision utilisateur** : la difficulté porte sur l'**adversaire**, pas sur le roster (§10.5).
Poussée jusqu'au bout, cette décision rend le split de scénarios **redondant** — les rosters
`hard` seraient des copies exactes des `regular`, donc 4 scénarios byte-identiques évalués par
les mêmes bots, et il faudrait en plus câbler un pool de bots par split qui ferait doublon avec
l'axe par-bot déjà en place (`bot_eval/vs_*`, `0_critical/c_holdout_tactical`). Les deux listes
ont donc été **supprimées** des 5 phases : l'absence est désormais **explicite**
(`Worst holdout hard combined: N/A`) au lieu d'être un zéro silencieux.

Le critère §10.6 (win-rate **par roster**) reste servi par les scores **par scénario** : les 4
scénarios holdout SONT les 4 matchups (SM/Ork × SM/Ork).

> ➜ **Déplacé en §0.16 (ouvert).** Rien n'a été supprimé : le contenu est intégral là-bas.

**✅ Points Orks corrigés par l'utilisateur le 2026-07-19** — ils sont désormais différenciés et
plausibles (Boyz 7, Gretchin 4, WarTrakk 175, personnages 50-100), fini le `VALUE = 70` uniforme.
L'objection « points factices » tombe.

~~🔴 **Mais ils rendent mesurable un déséquilibre qui était jusque-là invisible** :~~

| Roster | Points (état 2026-07-19 matin) | Figurines |
|---|---|---|
| Orks | ~~**824**~~ | ~~47~~ |
| Space Marines | ~~**690**~~ | 23 |

⚠️ **CE DÉSÉQUILIBRE N'EXISTAIT PAS — voir §0.9.** Confronté aux Munitorum officiels
(2026-07-20), le « +19 % » s'est révélé être un **artefact de trois `static VALUE` fausses**, la
`WarTrakk` cotée **175** au lieu de **60** pesant à elle seule +115. Aux points réels du
Munitorum, les deux listes font **680 vs 680**, écart **0**. Le raisonnement ci-dessus était
correct dans sa logique et **faux dans ses données** : il concluait à un déséquilibre de listes
à partir de valeurs de code jamais confrontées à la source officielle. **Ne pas re-citer le
824/690.**

**Composition exacte des deux rosters — ÉTAT PÉRIMÉ DU 2026-07-19, conservé pour mémoire.**
Recalculée depuis les fichiers via `UnitRegistry`, donc « confirmée » — mais confirmée contre le
**code**, jamais contre le Munitorum. C'est exactement la faille : recalculer ne vaut pas vérifier
la source. Composition et points à jour en **§0.9**.

| | ~~Orks — **824 pts / 47 fig.**~~ | ~~Space Marines — **690 pts / 23 fig.**~~ |
|---|---|---|
| Masse ⚠️ périmé (10 Gretchin, pas 20) | 20 × Gretchin @4 = 80 ; 18 × Boyz @7 = 126 ; 2 × BoyzNobKombi @9 = 18 | 6 × Intercessor @16 = 96 ; 3 × VanguardVeteran @20 = 60 ; 2 × Eradicator @23 = 46 ; 2 × IntercessorGL @18 = 36 ; 2 × IntercessorSgt @19 = 38 |
| Lourd | WarTrakk **175** ; BigMekDakkarig **100** | LandSpeeder **95** |
| Personnages | PainBoy 80 ; Warboss 75 ; WeirdBoy 65 ; Bigboss 55 ; BannerNob 50 | CaptainRelicShield 80 ; ChaplainJumpPack 75 ; Librarian 60 ; Ancient 40 |

⚠️ **Ce qui reste vrai de l'analyse ci-dessous, et ce qui tombe** (mise à jour §0.9) :
- ❌ **L'écart budgétaire (+134 pts) n'existe pas.** Aux points Munitorum : 680 vs 680. Le
  raisonnement « +255 pts concentrés dans 2 véhicules Orks » reposait sur la `WarTrakk` à 175 :
  elle en vaut **60**. Les deux véhicules orks pèsent **160**, contre 95 pour le Land Speeder.
- ✅ **L'asymétrie de masse reste réelle** : **37 figurines contre 23** (et non 47 — cf. §0.9,
  10 Gretchin et non 20). Plus de corps ⇒ OC supérieur sur les objectifs (§14) et meilleure
  résilience aux pertes.
- 🔁 **Mais ce n'est plus un déséquilibre, c'est une identité de faction** : à budget égal, une
  horde ork EST censée aligner plus de figurines qu'une escouade Space Marine. Les deux listes
  étant par ailleurs figées par le contenu de la boîte (contrainte métier, §0.9), il n'y a rien
  à « rééquilibrer » — et le win-rate par matchup redevient interprétable.

> ➜ **Déplacé en §0.15 (ouvert).** Rien n'a été supprimé : le contenu est intégral là-bas.


### 0.7 Run d'éval du 2026-07-19 (post-portage `CC_DMG`) — 60/60 épisodes

```
python3 ai/train.py --agent ArmageddonAgent --eval --training-config x1_debug
```

Notes sur la commande, lues dans [train.py](../../ai/train.py) : `--eval` est un alias de
`--test-only` (L4384) ; le mode **refuse** `--scenario bot` et résout **seul** les holdouts
(L4647) ; `--training-config` est obligatoire en pratique — le défaut `"default"` n'existe pas
(rupture R1, jamais corrigée). Phases réelles : `x1`, `x5_append`, `x5_new`, `x1_debug`, `x5_debug`.

**Résultat — 60/60 épisodes complétés** (6 bots × `eval_episodes: 10` ; chaque bot affiche
W+L+D = 10). Le fail-fast §0.5 n'a pas levé : **l'absence d'exception EST le résultat**.

| Bot | Score | Détail |
|---|---|---|
| defensive | **0.90** | W:9 L:1 D:0 |
| tactical *(holdout)* | **0.60** | W:6 L:3 D:1 |
| aggressive_smart | 0.30 | W:3 L:7 D:0 |
| control | 0.30 | W:3 L:6 D:1 |
| greedy | 0.20 | W:2 L:8 D:0 |
| adaptive | **0.10** | W:1 L:7 D:2 ← `worst_bot_score` |

`Combined Score: 0.3830` — **recalculé à la main depuis les poids** (`tactical: 0.0`, les 5 autres
sommant à 1.0) : **0.3830 exactement**. Le holdout ne pollue donc pas le score de sélection, et
`worst_bot_score` retient bien `adaptive`, pas `tactical` : **les DEUX verrous de §10.5
fonctionnent, vérifiés par le calcul et pas seulement par lecture du code.**

**Ce que ce run VALIDE** :
- ✅ **Portage `CC_DMG`/`RNG_DMG` validé runtime** sur les **6 sites `TacticalBot`** — le bot a
  joué 10/10 épisodes entiers, contre 4/8 auparavant.
- ✅ **§10.5 enfin validé runtime.** L'avertissement « `TacticalBot` n'a jamais été validé runtime
  sur le pipeline squad » porté plus bas dans ce document est **levé**.

> ➜ **Déplacé en §0.16 (ouvert).** Rien n'a été supprimé : le contenu est intégral là-bas.

**Trois constats du run, à traiter :**

| # | Constat | Suite |
|---|---|---|
| 1 | **Le modèle échouerait au gating** : `worst_bot_score` 0.10 < `model_gating_min_worst_bot` 0.25. | Attendu — ce modèle n'a pas été entraîné dans les conditions actuelles. À re-mesurer après le vrai run. |
| 2 | ~~**Bug d'affichage** : l'en-tête annonçait `Episodes per bot: 10 (Total: 30)` alors que **60** tournaient~~ — `episodes_per_bot * 3` codé en dur, littéral resté de l'époque à 3 bots. | ✅ **CORRIGÉ (2026-07-19)** : le total est dérivé de `len(callback_params.bot_eval_weights)` — **la même source unique** que `bot_evaluation` (`active_bot_names = tuple(eval_weights.keys())`), pour que le nombre annoncé ne puisse pas diverger du nombre joué. Vérifié sur le vrai chemin d'exécution (run interrompu après l'en-tête) : affiche `Total: 60`. |
| 3 | **Réserve §0.5 confirmée OBSERVÉE** : le bloc `🏁 Scenario ranking` s'imprime bien **avant** le résumé. | Toujours ouvert. |

`Worst holdout hard combined: N/A` s'affiche comme voulu (§0.6) : l'absence est **explicite**,
pas un zéro silencieux. Le fix de §0.6 est donc lui aussi confirmé à l'exécution.

**Ce que ce run ne débloque PAS — le critère §10.6.** Ranking par scénario :
`bot-03 = 0.805`, `bot-01 = 0.383`, `bot-04 = 0.305`, `bot-02 = 0.153`. Les 4 scénarios holdout
SONT les 4 matchups (SM/Ork × SM/Ork) : l'écart de 0.65 entre le meilleur et le pire mélange
**compétence de l'agent** et ~~**déséquilibre de listes** (§0.6, 824 vs 690)~~. ⚠️ **Cette dernière
imputation est INVALIDE** (§0.9) : les listes font 680 vs 680, il n'y a pas de déséquilibre de
budget à invoquer. L'écart de 0.65 entre bot-03 et bot-02 mesure donc autre chose — compétence,
asymétrie de masse, ou variance d'échantillon. **À réinterpréter après le run en cours**, sur des
`VALUE` justes ; les chiffres de ce run-là ont été produits avec la `WarTrakk` à 175.

**LE TRAINING TOURNE (2026-07-19, après T6-h + T6-g).** La commande de repro historique passe
désormais de bout en bout :

```
python3 ai/train.py --agent CoreAgent --training-config x5_debug \
  --scenario config/agents/CoreAgent/scenarios/training/training_benchmark/scenario_training_benchmark.json \
  --new --resolution 5
```
→ 10/10 épisodes, 8 workers `SubprocVecEnv` vivants, **zéro** `execute_squad_move a échoué : …
incohérence masque/exécution`, exit 0. Idem en mono-env (`--step`, x1_debug). Les seules
exceptions résiduelles du run sont dans l'**ÉVALUATION** (`bot_evaluation`) et sont la dette
rosters connue (`roster_pool_schedule produced zero eligible training rosters`) — cf. §10.2,
c'est ce qui met les win-rates à 0.00, pas le moteur.

**Chemin critique — LES 2 FIXES SONT LIVRÉS** (détail en section 5, tranche T6) :

| # | Quoi | État |
|---|---|---|
| 1 | **T6-h** — `build_rigid_plan` translatait en OFFSET : à `dx` impair le bloc se DÉFORMAIT (mesuré : distance interne 2 → 1). Fix : translation en CUBE, miroir de `deployment_build_squad_destinations_pool`. **Deux consommateurs de translation de bloc portaient le MÊME bug et ont été alignés** : `translate_squad_to_destination` (l'écrivain du commit, partagé move/charge/fight/pile-in — le laisser en offset aurait fait committer une formation DIFFÉRENTE de celle que `validate_move_plan` avait acceptée) et `preview_hidden_models_after_move` (shooting_handlers). | ✅ FAIT — +10 tests (`test_rigid_plan_translation.py`, paramétrés `dx` pair ET impair, rouges sur le code d'avant) |
| 2 | **T6-g** — le pool BFS du move était construit sur l'ANCRE, mais `build_rigid_plan` translate TOUT le bloc sans le valider → figurines sur un mur / sur une autre escouade. Fix : **érosion morphologique** (`erode_move_pool_by_squad_block`, shared_utils), appelée dans `build_squad_move_cell_map` AVANT la projection sur la grille égocentrique. | ✅ FAIT — +6 tests (`test_move_pool_block_erosion.py`) |

**Sur l'érosion (T6-g), ce qu'il faut savoir pour la maintenir** : le prédicat de cellule est
celui de `validate_move_plan` sous `DEFAULT_MOVE_CONSTRAINTS` — bornes, murs, occupation des
autres escouades **par niveau**, ER ennemie. Ce sont les seules contraintes érodables. Les deux
autres ont été **vérifiées invariantes** par translation cube, donc déjà garanties par le pool
d'ancre : `budget_per_model` (`calculate_hex_distance` est une distance cube → la distance de
chaque figurine à son origine égale celle de l'ancre, bornée par le coût géodésique du pool) et
`require_coherency` / collision intra-plan (ne dépendent que des positions RELATIVES). Escouade
mono-figurine : l'ancre EST le bloc, le pool est déjà exact → court-circuit.

**Déjà corrigé et validé le 2026-07-19** (détail en T6-e / T6-f) : `_turn_step_limit` absent du
chemin single-scenario (T6-e, commité) ; commit de déploiement mono-ancre qui ne plaçait AUCUNE
figurine (T6-f, +10 tests, non commité).

**Suite au 2026-07-19 après T6-h/T6-g** : `9 failed, 1440 passed, 2 skipped`. Baseline vérifiée
par `git stash` : `9 failed, 1421 passed` — **mêmes 9 échecs préexistants** (rosters, cf. plus
bas), +19 = les tests des deux fixes. Zéro régression.

**Dette de conception REMBOURSÉE (2026-07-19)** — la 1re version de l'érosion T6-g DUPLIQUAIT le
prédicat de cellule de `validate_move_plan`, ce que la décision de design n°2 interdit
explicitement (« Interdit de dupliquer le check ») : c'était rouvrir en petit la classe de bug
qu'on venait de fermer. Le prédicat est désormais dans un helper unique,
`build_move_blocked_cells_by_level` (shared_utils), lu par les DEUX côtés de l'invariant —
`validate_move_plan` (par figurine) et `erode_move_pool_by_squad_block` (par bloc).
`erode_move_pool_by_squad_block` prend en plus un paramètre `constraints` : l'érosion codait en
dur `DEFAULT_MOVE_CONSTRAINTS` alors qu'`execute_squad_move` accepte des `extra_constraints`
(divergence latente, non atteinte par le gym aujourd'hui).

⚠️ **Mise à jour §0.1 (2026-07-19 soir)** : l'invariance de `require_coherency` affirmée
ci-dessous est **conditionnelle** et a laissé passer une classe entière de crashes. Lire §0.1
avant de s'appuyer sur ce paragraphe.

⚠️ **Le helper renvoie une LISTE de sets par niveau, jamais leur union — ne pas « simplifier ».**
La 1re version fusionnait, ce qui copie `wall_hexes` (~1100 cellules) à CHAQUE appel : mesuré
+6 % sur `validate_move_plan` (1576 → 1673 µs), qui est appelé en boucle serrée par
`apply_snap_corrections`. En rendant les composants par référence, `validate_move_plan` teste
2-3 appartenances et retombe à 1596 µs, tandis qu'`erode_move_pool_by_squad_block` matérialise
l'union de son côté — là elle est amortie sur |pool| × |figurines| (~2800 × 20). L'arbitrage
appartient au consommateur, pas au helper.

**Invariant MESURÉ, plus seulement raisonné** — `tests/unit/engine/test_move_mask_is_executable.py`
(+3) déroule de vraies parties (3 seeds × 400 steps, actions masquées aléatoires) et vérifie qu'à
chaque step de phase move, TOUTE cellule offerte par le masque produit un plan accepté par
`validate_move_plan`, **avec le budget exact qu'`execute_squad_move` appliquerait** (type de move
inféré du coût géodésique). ~21 700 cellules réelles par run. Cela couvre les deux contraintes
que l'érosion ne filtre pas et qui n'étaient jusque-là que DÉMONTRÉES invariantes par translation
cube (`budget_per_model`, `require_coherency`). **Rouge sur le code d'avant les fixes**
(`git checkout 3886e498 -- shared_utils.py` → `ValueError: execute_squad_move a échoué : squad=103
dest=(24,15) … incohérence masque/exécution`, sur les 3 seeds), vert après.

**✅ §10.4 RÉSOLU (2026-07-19) — l'adversaire d'entraînement est câblé sur TOUS les chemins.**
La construction des adversaires est désormais mutualisée dans `build_training_opponents`
(train.py), appelée par les TROIS chemins : `train_with_scenario_rotation`,
`create_multi_agent_model` (single-scenario) et `create_model` (générique). Sur le chemin
single-scenario, `use_bots` vient de la CONFIG (présence de `bot_training`) et non plus du NOM
du fichier scénario — l'heuristique `"bot" in basename` faisait tomber tout autre scénario sur
`SelfPlayWrapper(frozen_model=None)`. Le `GreedyBot(0.15)` codé en dur est remplacé par les bots
pondérés de `bot_training.ratios`.
Le repli silencieux est **fermé des deux côtés** : `SelfPlayWrapper` lève désormais si
`frozen_model is None` sans `allow_random_opponent=True` (opt-in réservé aux tests), et
`make_training_env` refuse `use_bots=False` **avant de forker les workers** — un worker
vectorisé ne peut pas recevoir de frozen_model, le self-play vectorisé passe par
`BotControlledEnv` + `opponent_mix`.
**Vérifié par un vrai run** : `x5_debug` sur `training_benchmark` affiche désormais
`🤖 Bot training ratios: 10% Random, 20% Greedy, 20% Defensive, 20% Control, 15% Aggressive
Smart, 15% Adaptive` + `seat mode: random`, 8 workers, exit 0. +5 tests
(`test_training_opponent_wiring.py`) + 1 test de refus dans `test_env_wrappers.py`.

**✅ §10.5 FAIT (2026-07-19) — holdout d'évaluation `TacticalBot`.** Câblé dans la factory
d'éval (`bot_evaluation.BOT_CLASSES`), dans `ALL_BOT_NAMES` (training_callbacks — sans quoi son
score n'était ni affiché ni loggé) et dans `bot_eval_weights`/`bot_eval_randomness` des 5 phases
des 2 agents. Deux scalaires TensorBoard : `bot_eval/vs_tactical` et
`0_critical/c_holdout_tactical`.

⚠️ **Un holdout doit être MESURÉ mais ne doit piloter AUCUN signal de sélection** — sinon la
sélection de modèle optimise dessus et ce n'est plus un holdout. Deux verrous, tous deux
nécessaires (le premier seul ne suffit pas) :
- **Poids nul** : `tactical: 0.0` dans `bot_eval_weights` (les 5 autres gardent leurs poids
  d'origine, somme 1.0). `combined` est un critère de gating et pilote le choix du BEST.
- **Exclusion par NOM** : `worst_bot_score`, le gating et le score robuste itèrent sur des
  ensembles de noms de bots, pas sur les poids — un poids nul ne les protège **pas**.
  D'où `HOLDOUT_BOT_NAMES` / `SELECTION_BOT_NAMES = ALL_BOT_NAMES - HOLDOUT_BOT_NAMES`
  (training_callbacks), utilisé aux 3 sites de sélection ; `ALL_BOT_NAMES` reste pour
  l'affichage et le log. `ALL_BOT_KEYS` (metrics_tracker) exclut aussi le holdout, car il
  alimente `0_critical/b_worst_bot_score`.

⚠️ **Le motif d'origine de cette exclusion était FAUX — corrigé le 2026-07-19 après mesure.**
Ce document justifiait l'exclusion par nom en écrivant que « `TacticalBot` est le bot le plus
fort, donc serait presque toujours le `min` et dominerait le gate ». **Mesuré (§0.7)** :
`vs tactical = 0.60`, **deuxième meilleur score de l'agent**, très au-dessus de `greedy` (0.20)
et `adaptive` (0.10) ; le `min` observé est `adaptive`. `TacticalBot` n'est donc pas le bot le
plus fort face à ce modèle.

**Le verrou reste néanmoins nécessaire, et pour une meilleure raison** : un holdout ne doit
piloter aucun signal de sélection **quel que soit son niveau**. S'il était faible, l'inclure
gonflerait `worst_bot_score` et laisserait passer le gate ; s'il était fort, il l'écraserait.
Dans les deux cas la sélection se met à optimiser sur le holdout, et il cesse d'en être un.
La force relative du bot est **hors sujet** — c'était l'erreur de raisonnement.

**Leçon de méthode** (même famille que la demi-vérité de §0.1 sur `require_coherency`) : une
justification par une propriété SUPPOSÉE du système (« ce bot est le plus fort ») est une
hypothèse non mesurée. Ici elle était fausse et le verrou est resté correct par chance. Préférer
une justification qui tient quelle que soit la valeur de la propriété.

**Dette corrigée au passage** : `randomness_config` (bot_evaluation) ne recopiait que
`greedy`/`defensive`/`control` — `aggressive_smart`, `adaptive` et `tactical` retombaient
SILENCIEUSEMENT sur `randomness=0.15`, rendant leur `bot_eval_randomness` de config lettre
morte. La config est désormais transmise entière et l'absence d'une entrée est une **erreur
explicite** aux deux niveaux (planification et construction du bot), sans défaut.

+9 tests (`test_eval_holdout_opponent.py`) : intersection vide `bot_training.ratios` ∩ holdout,
présence en `bot_eval_weights`, somme à 1.0, **poids de holdout == 0.0**, **exclusion des
signaux de sélection**, **absence de défaut de randomness**.
Run de vérification : `vs TacticalBot: 0.00 (0/1 wins)` s'affiche désormais et aucun `KeyError`
de randomness n'est levé — le `0.00` est la dette rosters, pas le câblage.

~~⚠️ **`TacticalBot` n'a jamais été validé runtime sur le pipeline squad**~~
✅ **LEVÉ le 2026-07-19 — voir §0.7** : après le portage `CC_DMG`/`RNG_DMG`, `TacticalBot` a joué
**10/10 épisodes entiers** (`vs tactical: 0.60`, W:6 L:3 D:1). Constat historique : il n'avait
jamais complété un épisode (docstring « unused in training/eval », puis 4/8 épisodes), parce que
les autres bots avaient été maintenus au fil des refactors squad et pas lui.

**Suite après ces deux tranches** : `9 failed, 1451 passed` — **mêmes 9 échecs préexistants**
(dette rosters), zéro régression.

**~~🔴 PROCHAIN BLOQUEUR — dette rosters (§10.2).~~ ✅ RÉSOLU (2026-07-19, commit `d2b377f0`)** —
les 2 rosters SM/Orks existent sous `ArmageddonAgent` et le pipeline tourne dessus.
**✅ Et la banque CoreAgent a été RETIRÉE le 2026-07-19 (décision utilisateur)** : les 9 échecs
qu'elle causait n'existent plus, la suite est verte. Voir §0.-1 pour la nouvelle baseline et la
règle de périmètre.

**Pour la suite immédiate, voir §0.0** (ordre imposé : test 03.03, puis `CC_DMG`, puis code mort).

**Historique — l'ancien libellé du bloqueur §10.4 :**
Re-vérifié dans le code le 2026-07-19 : `update_frozen_model` ([env_wrappers.py:1272](../../ai/env_wrappers.py#L1272))
n'a **aucun appelant** hors son propre test ; le chemin single-scenario construit
`SelfPlayWrapper(masked_env, frozen_model=None, ...)` ([train.py:1537](../../ai/train.py#L1537), [1871](../../ai/train.py#L1871)) ;
et à `frozen_model is None` le wrapper joue **une action valide au hasard**
([env_wrappers.py:1242-1248](../../ai/env_wrappers.py#L1242-L1248)). Les runs de validation T6-g/T6-h et
ArmageddonAgent ont donc tourné avec un P2 aléatoire — **rien ne le signale dans les logs**.
Conséquence : le pipeline est prouvé fonctionnel, mais **aucun win-rate d'entraînement n'a de
sens tant que ce n'est pas câblé**, et le critère T6 reste non évaluable. À traiter AVANT tout
run sérieux et avant T7. (Le combined d'`--eval` reste valide : l'évaluation, elle, joue contre
de vrais bots.)

**Après ça** — ne PAS anticiper : **T7** (unification de la validation de déploiement,
section 5). Son déclencheur « le training tourne » est désormais REMPLI, mais T7 touche le
masque, donc l'espace d'action de l'agent, et exige une mesure avant/après — donc §10.4 d'abord.

**⚠️ AVANT de lancer le premier vrai run, lire la section 10** (stratégie d'entraînement et
d'évaluation, décision utilisateur 2026-07-19). Deux points bloquants y sont établis :
- **§10.4** — toute la machinerie d'adversaires (bots pondérés + self-play `opponent_mix`)
  n'est câblée que sur `--scenario bot`. Le chemin single-scenario vectorisé (x5_debug,
  n_envs=8) tombe sur `SelfPlayWrapper(frozen_model=None)` dont le frozen n'est JAMAIS mis à
  jour (`update_frozen_model` : zéro appelant) → **P2 joue des actions ALÉATOIRES en
  permanence**. Comme `--scenario bot` est cassé (rosters), un run lancé aujourd'hui
  entraînerait contre du hasard **sans que rien ne le signale**. Même famille de divergence
  que T6-e.
- **§10.6** — le critère de succès T6 a été REMPLACÉ : l'ancien (« win-rate vs RandomBot sur
  holdout ») référence un holdout de rosters supprimé. Le holdout porte désormais sur
  l'**adversaire** (`TacticalBot`, réservé à l'évaluation), pas sur les rosters.

**État de la suite** — ⚠️ **PÉRIMÉ, voir §0.-1** (la suite est verte depuis le retrait de la
banque CoreAgent le 2026-07-19 : `1402 passed, 0 failed`). Constat historique :
`tests/unit` — **9 échecs, tous préexistants et hors chemin critique** :
4 × banque de scénarios et 5 × déploiement/terrain, tous dus à des **rosters manquants ou
non résolus** (`roster_pool_schedule produced zero eligible training rosters`, fichiers de
roster holdout absents). Baseline vérifiée par `git stash` — aucune régression des fixes ci-dessus.
Ces rosters ont été supprimés VOLONTAIREMENT (commit `43eae95a`, obsolètes pré-escouades) : la
réparation n'est pas « les restaurer » mais recréer 2 rosters (SM, Orks) — cf. §10.2.

**Dettes à connaître avant de s'y remettre** :
- `--scenario bot` échoue en AMONT du moteur (roster) : utiliser `training_benchmark` pour
  reproduire, pas `bot-01`.
- Toute la banque (61 scénarios) tourne sur `terrain-mc1.json` depuis le 2026-07-19 (décision
  utilisateur : `terrain-train-01/02/03` obsolètes). mc1 porte 8 étages ; l'observation les voit
  via le canal 5 `GRID_CH_LEVEL`. ⚠️ `scripts/migrate_scenario_bank_v11.py` cycle encore sur les
  3 terrains plats — le RELANCER repointerait la banque et casserait le test de banque.
- `config/tutorial/scenario_etape*.json` ne se charge plus (`wall_ref` legacy sans `board_ref`).


### 0.8 `game_replay_logger` — SUPPRIMÉ, pas porté (2026-07-19 soir)

**Point de départ** : la dette annoncée en §0.3 (le module lit encore `RNG_DMG`/`CC_DMG`, champs
supprimés du contrat d'unité). La question posée n'était pas « comment porter » mais « faut-il
porter ». Réponse vérifiée : **non — supprimer**. 12 fichiers, **−1585 lignes**.

**Les 3 constats qui ont tranché** (tous re-vérifiés dans le code, pas dans un rapport) :

1. **Aucun appelant vif.** `enhance_training_env` était appelé à 2 endroits. Dans `train.py`, sous
   `if args.replay or args.convert_steplog` — **inatteignable**, car `main()` fait `return` sur ces
   deux flags bien avant (les deux modes sont intégralement servis par `ai/replay_converter.py`, qui
   n'importe jamais ce module). Dans `multi_agent_trainer.py`, sur le chemin `--orchestrate`
   (voir plus bas). `save_episode_replay` était atteint mais **no-op** : son corps est gardé par
   `if env.replay_logger`, attribut resté à `None`.
2. **Aucun consommateur de sa sortie.** Le replay du frontend charge `/api/replay/default|file|list`,
   qui servent **`step.log`** (texte, `.log` uniquement), parsé par `replayParser.ts`. Le JSON
   `ai/event_log/replay_*.json` est produit par `replay_converter.py`. `game_replay_logger` était le
   **prédécesseur** de `replay_converter`, laissé branché après son remplacement.
3. **Le périmètre cassé dépassait `RNG_DMG`/`CC_DMG`** : le format émis exigeait aussi `CUR_HP`,
   `RNG_RNG`, `CC_RNG`, `MOVE`, `BASE_SHAPE`, `BASE_SIZE`. Porter, c'était réécrire le format entier
   d'un fichier que personne ne lit.

**Supprimé** : `ai/game_replay_logger.py` (795 l.) et son test ; `log_unified_action`
(`shared/gameLogStructure.py`, 85 l., **aucun appelant hors tests** — nouvelle occurrence du motif
§0.4) et ses 2 tests ; les hooks de `w40k_core.step()` (131 l.) + l'attribut `replay_logger` ;
les câblages de `train.py` et `multi_agent_trainer.py` ; `required_properties` des 2
`unit_definitions.json` (**clé sans aucun lecteur** — grep vide, config morte) ;
`RNG_DMG`/`CC_DMG` de `frontend/src/types/api.ts` (types jamais lus).

**Effet de bord assumé** : `SelectiveEpisodeTracker` (`multi_agent_trainer.py`) n'était alimenté
**que** par ce logger. Le laisser en place garantissait un `raise ValueError` sur le chemin
`--orchestrate`. La feature entière est donc supprimée (`EpisodeMetrics`,
`SelectiveEpisodeTracker`, 3 sites de câblage, clé `selective_replay_files`).

**Vérification** : `pytest tests/unit` **exit 0** — 1396 tests, 0 skip, 0 échec (compté sur les
caractères de statut : le reporter du projet **n'imprime pas** la ligne de résumé, tout « N passed »
non compté est à rejeter). `tsc --noEmit` exit 0. Imports des 4 modules touchés OK.

⚠️ **Correction à §5/T2 (§992-995)** : ce paragraphe décrit `multi_agent_trainer.py:1016` comme
contenant encore `action % 8` + `unit_idx = action // 8`. **C'est périmé** — la branche a été purgée
au commit `6a7a9de1` ; il ne restait qu'un commentaire de purge, lui-même supprimé ici. Le grep est
désormais vide. Ce paragraphe a déjà induit deux relecteurs en erreur (citation de la doc au lieu
d'un grep) : **§992-995 est soldé.**

~~**Reste ouvert — chantier distinct, non urgent** : la purge complète de `multi_agent_trainer.py` /
`--orchestrate`.~~ → ✅ **FAIT dans la foulée (2026-07-19 soir)**, le module est supprimé.
Les deux preuves qui l'ont condamné, établies **sans s'appuyer sur la doc** : il chargeait les
modèles via `DQN.load` alors que tous les `.zip` sont MaskablePPO, et il appelait
`base_env.controller.connect_step_logger(...)` alors que `W40KEngine` n'expose que `pve_controller`.
Supprimés avec lui : l'import dans `train.py`, `start_multi_agent_orchestration`, les flags
`--multi-agent` / `--orchestrate` / `--max-concurrent` / `--training-phase`, et les 3 stubs
`sys.modules["ai.multi_agent_trainer"]` des tests qui n'existaient QUE pour contourner cet import
legacy. `--total-episodes` est **conservé** (encore lu dans le chemin d'entraînement vivant).
`create_multi_agent_model` est un **homonyme vivant** de `train.py`, sans rapport — ne pas le purger.


### 0.9 Rosters fidèles à la boîte + points Munitorum — ✅ FAIT (2026-07-20) — **§0.6 SOLDÉ**

**Déclencheur** : l'utilisateur signale que la boîte Armageddon ne contient que **10 Gretchin**,
alors que les 4 rosters en déclaraient 20. Il fournit les 2 Munitorum officiels
(`Documentation/40k_rules/Armageddon/{Orks,Space Marines} - Munitorum UK.pdf`) et les datasheets.
Contrainte métier posée : **les rosters doivent refléter la boîte, pas une liste optimisée.**

⚠️ **Le texte de ces PDF n'est pas extractible** (contenu en image : `extract_text()` ne rend que
les en-têtes). Il faut les **rendre en PNG** (`fitz`/pymupdf, dpi≥140) et les lire visuellement.
Ne pas conclure « le PDF est vide ».

**Points réels relevés dans les Munitorum** (par UNITÉ, pas par figurine) :

| Orks | pts | Space Marines | pts |
|---|---|---|---|
| Boyz ×10 (×2 unités) | 150 | Intercessor Squad ×5 (×2) | 160 |
| Gretchin | 45 | Vanguard Vets w/ Jump Packs ×5 | 100 |
| Warboss 75 / Bigboss 55 / Bannernob 50 | 180 | Eradicators w/ Heavy Bolters ×3 | 70 |
| Painboy 80 / Weirdboy 65 | 145 | Land Speeder | 95 |
| Wartrakk | 60 | Captain 80 / Librarian 60 / Ancient 40 | 180 |
| Big Mek Dakkarig | 100 | Chaplain w/ Jump Pack | 75 |
| **TOTAL** | **680** | **TOTAL** | **680** |

**Les 4 `static VALUE` corrigées** (elles seules créaient le faux déséquilibre de §0.6) :

| Unité | avant | après | source |
|---|---|---|---|
| `WarTrakk` | **175** | **60** | Munitorum : WARTRAKK 1 model 60 pts |
| `BoyzNobKombi` | 9 | 12 | BOYZ 75 pts / 10 → 9×7 + 1×12 = 75 exact |
| `Gretchin` | 4 | 5 | 45 pts / 10 = 4,5 **non représentable** (`VALUE` coercé `int`, [game_state.py:952](../../engine/game_state.py#L952)) — arrondi au supérieur pour ne pas sous-coter |
| `IntercessorGrenadeLauncher` / `IntercessorSergeant` | 18 / 19 | 16 / 16 | 80 pts / 5 modèles ; **en 10ᵉ l'équipement est gratuit**, tous les modèles d'une escouade coûtent pareil |

Résultat mesuré sur les 8 fichiers de roster : **685 (Orks) vs 680 (SM)**, écart **0,7 %** contre
+19,4 % avant. Le résidu de 5 pts est l'arrondi Gretchin, incompressible en entier.

🔒 **RÈGLE MÉTIER (utilisateur, 2026-07-20) — NON NÉGOCIABLE.** `VALUE` **suit les documents
officiels**. Ce n'est pas une variable de tuning. `VALUE` est pourtant consommé **par figurine**
(pondération de menace [reward_calculator.py:1442](../../engine/reward_calculator.py#L1442),
différentiel d'armée [observation_builder.py:367](../../engine/observation_builder.py#L367)) : cet
effet sur l'apprentissage est une **conséquence à assumer**, jamais un motif pour s'écarter du
Munitorum. **Ne pas « rééquilibrer » ces valeurs pour améliorer un résultat d'entraînement.**

**Ventilation par figurine — arbitrée le 2026-07-20, sujet CLOS.** Le document cote l'**unité**,
pas la figurine ; quand le quotient n'est pas entier la répartition est sous-déterminée. Décision :
**faire tomber le total d'unité juste partout où c'est représentable**, quitte à ce que la
ventilation s'en écarte (Boyz : 9 × 7 + Nob 12 = 75 **exact**, plutôt que 10 modèles uniformes
à 7 = 70). **Seul écart résiduel assumé** : Gretchin, unité à **50** au lieu de 45 — aucune
répartition entière ne donne 45 sur 10 figurines identiques. Alternatives examinées et
**écartées** : Gretchin à 4 (→ Orks 675), Boyz uniformes (→ 680/680). Ne pas les rouvrir.

**🔴 Violation de règle corrigée : le Weirdboy ne peut pas mener les Gretchin.** Les 4 rosters
l'attachaient à l'unité de Gretchin. Munitorum : `WEIRDBOY / LEADER : BOYZ, BREAKA BOYZ`. Le seul
personnage habilité à mener des GRETCHIN est **Zodgrod Wortsnagga**, absent de la boîte. Les deux
unités de Boyz ayant déjà chacune un Leader (Warboss, Bigboss) et une unité ne pouvant en accueillir
qu'un, le Weirdboy est devenu une **unité autonome**. Vérifié au moteur : le roster ork charge
désormais 6 unités au lieu de 5, et les 3 scénarios ork tournent jusqu'à terminaison (112/112/125
steps).

**Deux pièges de lecture des sources, à ne pas re-trébucher dessus :**
1. **Le Grot Infirmier n'est pas une figurine de jeu.** Datasheet Painboy : `UNIT COMPOSITION :
   1 Painboy`, `equipped with : … 1 Grot Orderly` → c'est de l'**équipement**. D'où 38 figurines
   physiques dans la boîte mais **37 modèles de jeu**. Le roster n'a rien qui manque.
2. **Contradiction entre deux sources officielles sur les Gretchin** : le Munitorum cote
   `11 models … 45 pts`, la datasheet dit `UNIT COMPOSITION : 10 Gretchin`. La boîte en a 10.
   Retenu : 10 modèles à 45 pts. Non tranchable depuis les documents — signalé, pas masqué.


### 0.10 `--scenario bot` contaminait le holdout sur ArmageddonAgent — ✅ CORRIGÉ (2026-07-20)

> **Correctif livré.** Dans `get_scenario_list_for_phase` ([training_utils.py](../../ai/training_utils.py)),
> la branche `scenario_type in ("bot", "self")` — les deux modes d'**entraînement** — ne balaie
> plus que `training/` (ou la racine `scenarios/` si `training/` n'existe pas). Les dossiers
> `holdout_regular/` et `holdout_hard/` en sont **exclus**. Aucun repli : si `training/` est vide,
> la liste est vide et l'appelant ([train.py:4929](../../ai/train.py#L4929)) lève déjà un
> `FileNotFoundError` explicite — c'est le comportement voulu, pas une régression.
>
> **Mesuré après fix** sur ArmageddonAgent : `bot` et `self` résolvent **1** scénario
> (`training/scenario_training_armageddon.json`) au lieu de 5 ; `holdout` en résout toujours **4**.
> **Non-régression** : `tests/unit/ai/test_training_utils.py`, +4 tests (paramétrés `bot`/`self`) —
> l'ancien test `..._bot_finds_holdout_when_training_empty`, qui **garantissait la contamination**,
> est retourné en `..._bot_empty_training_dir_returns_nothing`. Mutation-testé : les 4 sont rouges
> sur le code d'avant. Suite complète verte (exit 0).
>
> Le diagnostic d'origine est conservé ci-dessous.

`bot` n'est **pas un nom de scénario** mais un **mot-clé de mode rotation**, intercepté à
[train.py:4919](../../ai/train.py#L4919) avant toute résolution de fichier. Il appelle
`get_scenario_list_for_phase(scenario_type="bot")`, qui balaie `training/` **puis
`holdout_regular/` puis `holdout_hard/`** (docstring explicite de la fonction).

Or les 4 scénarios `scenario_bot-01..04` d'ArmageddonAgent vivent dans **`holdout_regular/`** :
ce sont les 4 matchups qui servent à mesurer §10.6. Mesuré : `--scenario bot` résout **5**
scénarios pour cet agent (les 4 holdout + celui d'entraînement). **Entraîner avec ce flag revient
donc à entraîner sur le jeu de test**, silencieusement — aucun message ne le signale.

⚠️ *(Renvoi imprécis — affirmation périmée n°5 de §0bis : cette dette est écrite en §0.7, pas §0.0. Non corrigé.)*
⚠️ La dette notée en §0.0 (« `--scenario bot` échoue en amont du moteur ») vise **CoreAgent**, dont
l'arborescence de scénarios est différente. Elle **ne s'applique pas à ArmageddonAgent**, où le flag
n'échoue pas : il réussit et contamine.

**Le scénario d'entraînement seul couvre déjà les 4 matchups** — inutile de chercher la rotation
ailleurs. `scenario_training_armageddon.json` porte `agent_roster_ref: "training_random"`
(→ `rng.choice` sur les 2 rosters agent, [game_state.py:1187](../../engine/game_state.py#L1187)) et
un `opponent_roster_ref` **en liste** de 2 (→ second `rng.choice`,
[:1200](../../engine/game_state.py#L1200)), tirages indépendants **refaits à chaque `reset()`**.
Mesuré sur **400 resets** : Ork/Ork 102 (25,5 %), Ork/SM 107 (26,8 %), SM/SM 104 (26,0 %),
SM/Ork 87 (21,8 %) — **les 4 matchups, équiprobables** (χ² = 2,38 pour un seuil de 7,81 à 3 ddl :
aucun biais détectable). Un premier tir de 40 resets donnait 15/13/9/**3** et laissait craindre un
biais : c'était du **bruit d'échantillonnage**, pas un bug. Leçon : ne pas conclure à un biais de
tirage sur quelques dizaines d'observations — refaire la mesure en grand avant de diagnostiquer.

⚠️ **Piège latent voisin — `agent_roster_seed`.** Cette clé de scénario est passée en
`random_seed` au tirage du roster AGENT ([game_state.py:1056](../../engine/game_state.py#L1056)),
et le RNG est reconstruit à chaque appel (`random.Random(seed)`,
[:1142](../../engine/game_state.py#L1142)). Si elle est renseignée, **le roster agent devient
identique à tous les épisodes** — le tirage est neutralisé sans le moindre message. Voulu pour les
scénarios holdout `bot-01..04` (qui la portent, pour la reproductibilité), mais ce serait un piège
silencieux dans un scénario d'entraînement. `scenario_training_armageddon.json` ne la porte pas
(`None`) : vérifié. **À contrôler avant de conclure quoi que ce soit sur une distribution de
matchups.**

**Piège de lancement, préexistant** : `--training-config x5_debug` **seul** échoue pour cet agent
(`No scenario file found … scenario_x5_debug.json`). ArmageddonAgent n'a que
`scenario_training_armageddon.json`, donc `--scenario <chemin explicite>` est **obligatoire** :
```
python3 ai/train.py --agent ArmageddonAgent --training-config x5_debug \
  --scenario config/agents/ArmageddonAgent/scenarios/training/scenario_training_armageddon.json \
  --new --resolution 5
```
⚠️ `x5_debug` = **1000 épisodes** (~2h50 à 8 envs), pas un run de quelques minutes malgré son nom.

⚠️ **Ce que `x5_debug` ne produit PAS**, à cause de ses `callback_params` :
`save_best_min_episodes = 10000` et `checkpoint_save_freq = 10000` sont **supérieurs** à ses
1000 épisodes → **ni « best model » ni checkpoint** ne sont jamais écrits. `model_gating_enabled`
est `False` (le `Gate 🧱` de la barre de progression est purement décoratif) et `bot_eval_final`
vaut **1** épisode par bot — contre 60 pour le run de §0.7. C'est un run de **validation de
pipeline**, pas de mesure : il ne peut pas servir le critère §10.6.


### 0.11 Crash du training : collision intra-plan aveugle au niveau — ✅ CORRIGÉ (2026-07-20)

**Symptôme.** Le run `x5_debug` lancé après §0.9 meurt à l'épisode **~250/1000** (exit 1) :
```
execute_squad_move a échoué : squad=3 type=fall_back dest=(205,160) depuis (210,142)
— la destination vient du pool BFS du masque, elle DOIT être exécutable
(incohérence masque/exécution). Contrainte violée : collision intra-plan :
deux figurines en (189,159) (dont 3#9)
```

**Root cause, prouvée.** Dans `explain_move_plan_rejection`
([shared_utils.py](../../engine/phase_handlers/shared_utils.py)), deux contrôles voisins ne
traitaient pas la position de la même façon :

| Contrôle | Clé | Niveau pris en compte |
|---|---|---|
| Cellule interdite — `blocked_by_level[_target_level(entry)]` | `(col, row)` **par niveau** | ✅ |
| Collision intra-plan — `new_cells` | `(col, row)` **tous niveaux confondus** | ❌ |

Or le niveau **fait partie de l'identité d'une position** : tout le prédicat d'occupation du
moteur est per-niveau (`build_move_blocked_cells_by_level`), et le commentaire de `_target_level`
le dit lui-même (« sinon un move vers l'étage est validé contre l'occupation du sol — bug
superposition inter-niveaux »). Deux figurines d'une même escouade **légalement** superposées à
des étages différents étaient donc comptées comme une collision.

**Pourquoi ça tuait le training et pas juste un coup.** `build_rigid_plan` translate le bloc
**rigidement** (même delta cube pour toutes les figurines, tuples à 3 éléments donc niveau
inchangé). Deux figurines partagent donc `(col,row)` à l'arrivée **ssi** elles la partageaient au
départ. Conséquence : dès qu'une escouade se retrouvait superposée sur deux étages, **TOUS ses
déplacements ultérieurs** devenaient injouables — et comme `erode_move_pool_by_squad_block` ne
teste PAS la collision (elle la démontre invariante par translation, ce qui est **exact**), le
masque continuait d'offrir ces destinations. D'où le crash dur, et le profil observé : 250
épisodes sains puis mort brutale, le temps que la superposition apparaisse.

**Correctif** : `new_cells` clée sur `(niveau, col, row)`. Le message d'erreur nomme désormais le
niveau. L'invariant revendiqué par l'érosion redevient vrai *pour de bon* : c'était le prédicat
lui-même qui était faux, pas le raisonnement d'invariance.

**Non-régression** : `tests/unit/engine/test_move_plan_intra_squad_levels.py`, 2 tests sur un
**vrai moteur déploiement joué** (pas un `game_state` fabriqué) — niveaux différents ⇒ pas une
collision (**rouge avant le fix**, vérifié) ; même niveau ⇒ toujours refusé (vert avant/après).
Le 1ᵉʳ assert porte sur « le rejet n'est pas *une collision* » et non « aucun rejet » : la cellule
peut légitimement être refusée pour une autre raison à l'étage (pas de plancher, mur), sinon le
test serait instable. Suite : **1398 tests, 0 échec**.

🔴 **Pourquoi `test_move_mask_is_executable.py` n'a rien vu** — c'est le point le plus important
de cette entrée. Ce fichier mesure **cet invariant exact**, sur **ce scénario exact**, et il est
vert. Il ne vérifie l'invariant que sur les états atteints par **exploration aléatoire** (3 seeds,
400 steps) : la superposition inter-étages n'y survient jamais. Sa docstring affirme pourtant
combler précisément ce trou (« Ce test remplace ce raisonnement par une mesure »).

> **Quatrième variante du motif §0.4, et la plus sournoise.** Les trois premières étaient du code
> *jamais appelé*. Celle-ci est du code appelé, par un test vert, qui **n'exerce jamais le cas**.
> Un test qui explore au hasard ne prouve rien sur les configurations qu'il n'atteint pas — et sa
> docstring peut affirmer le contraire en toute bonne foi. **Devant un test de type « je déroule
> des parties et je vérifie un invariant », toujours se demander quelles configurations il ne
> visite jamais, et les construire explicitement.**

**Non tranché** : je n'ai pas l'état exact au moment du crash. Il est prouvé que le prédicat est
aveugle au niveau et qu'il produit ce message sur une configuration légale ; il n'est **pas**
prouvé que les deux figurines de l'escouade 3 étaient à des étages différents plutôt que dans un
état déjà illégal. Si un crash de cette classe réapparaît, dumper l'état avant de conclure.

**Limite connue, HORS PÉRIMÈTRE (décision utilisateur, 2026-07-20) : le cas x10.** Le contrôle
compare les **sous-hex d'ancre**. Sur Board ×10 les figurines ont une **empreinte multi-hex**
(`compute_candidate_footprint` — « Multi-hex footprints are only computed on Board ×10 ») : deux
socles peuvent donc s'y chevaucher **sans partager leur ancre**, et la même classe d'incohérence
masque/exécution reste ouverte à cette résolution. Sur x5 (résolution du training) l'empreinte
vaut le sous-hex, le contrôle est **exact**. Limite préexistante, non introduite par le correctif.
⚠️ Ne pas lire « l'invariant est rétabli » comme valant pour toutes les résolutions : il vaut
pour x1 et x5. **On ne s'occupe pas de x10** — si le projet y vient un jour, rouvrir ce point
AVANT d'y lancer un entraînement.


### 0.12 Le reward de combat ignore la `VALUE` par figurine — ✅ FAIT (2026-07-20)

> ✅ **LIVRÉ le 2026-07-20 — A, B, C et les tests.** Suite complète **1415 passed, 2 skipped**
> (1403 avant, +12 nouveaux). Ce qui suit est l'énoncé d'origine, conservé intégralement ;
> le détail de ce qui a réellement été écrit est en fin d'entrée (« Ce qui a été livré »).



> **Énoncé de la dette, déplacé depuis le tableau de §0.0 (ligne 6), texte d'origine :**
> Depuis §0.9 les escouades sont **hétérogènes en points**, mais le shaping tue-une-figurine vaut toujours `VALUE_escouade / model_count_at_start` — tuer le Nob (12) rapporte autant qu'un Boy (7), et un HP d'aumônier (75) autant qu'un HP d'Intercessor (16). L'agent n'a **aucun signal** pour cibler les figurines de valeur, alors que l'allocation 05.03 en fait une vraie décision. **Ouvert, aucune ligne écrite.**

> **État vérifié dans le code le 2026-07-20** : le problème est **entier**. La `VALUE` par figurine
> est bien *produite* en amont, mais elle n'est **jamais consommée** en aval. Rien de ce qui suit
> n'est fait. Aucune ligne de code n'a été modifiée pour ce point.

**Ce qui existe déjà (et qui est correct).** `_build_enhanced_unit`
([game_state.py:952-984](../../engine/game_state.py#L952-L984)) pose **deux niveaux de valeur** :
`unit["models"][i]["VALUE"]` = valeur de CHAQUE figurine (lue de la datasheet, ou de
`full_unit_data["VALUE"]` quand l'unité n'a qu'une figurine, [ligne 967](../../engine/game_state.py#L967)),
et `enhanced_unit["VALUE"] = total_value` = **somme** des figurines
([ligne 984](../../engine/game_state.py#L984)). C'est ce qui rend §0.9 exact au point près
(Boyz : 9 × 7 + Nob 12 = 75). La donnée par figurine **est donc disponible**, et elle atteint bien
`_build_models_for_unit` : `build_units_cache` itère `for unit in game_state["units"]`, qui sont les
`enhanced_units` produits par cette même fonction ([game_state.py:622-626](../../engine/game_state.py#L622-L626)).
`spec["VALUE"]` est donc **présent sur chaque `model_spec`** au moment où le cache est construit —
aucune plomberie à ajouter pour l'y amener.

📌 **Ce n'est pas un oubli, c'est une dette assumée** : le commentaire
[game_state.py:977-983](../../engine/game_state.py#L977-L983) énumère explicitement, parmi les
consommateurs de `VALUE`, « les usages par-figurine **qui divisent déjà par
`model_count_at_start`** (`points_per_hp`, reward par fig tuée) ». L'auteur de §0.9 a donc vu la
moyenne et l'a laissée en place. Cette section ne corrige pas une régression : elle **solde** cette
dette, devenue mesurable maintenant que les escouades sont hétérogènes en points.

**Où la chaîne casse — 3 ruptures, toutes vérifiées.**

> 🔴 **CE RECENSEMENT ÉTAIT INCOMPLET — corrigé le 2026-07-20.** Il en manquait une **4ᵉ**,
> côté **observation**, qui n'est pas une rupture préexistante mais une **régression créée par
> les étapes A/B elles-mêmes**. Voir « Rupture D » en fin d'entrée. Leçon de méthode : le grep
> des consommateurs de `points_per_hp` avait bien remonté le site
> ([observation_builder.py:1498](../../engine/observation_builder.py#L1498)) — **il a été vu et
> non ouvert**, parce que la ligne semblait ne concerner que le reward. Un consommateur listé
> par un grep et non lu compte comme non audité (§0bis).

| # | Emplacement | Ce que fait le code | Conséquence |
|---|---|---|---|
| A | [shared_utils.py:632-674](../../engine/phase_handlers/shared_utils.py#L632-L674) (`_build_models_for_unit`) | `models_cache[model_id]` est construit **sans aucune clé `VALUE`** — `spec["VALUE"]` n'est jamais lu | La valeur par figurine **s'arrête à `_build_enhanced_unit`** et n'atteint jamais le moteur de combat |
| B | [shared_utils.py:629](../../engine/phase_handlers/shared_utils.py#L629) + [:666](../../engine/phase_handlers/shared_utils.py#L666) | `points_per_hp = VALUE_escouade / total_hp_pool` calculé **une seule fois**, puis recopié **identique** sur chaque figurine | Un HP retiré au Nob (12 pts) vaut exactement autant qu'un HP retiré à un Boy (7 pts) |
| C | [reward_calculator.py:1020-1022](../../engine/reward_calculator.py#L1020-L1022) (`_squad_combat_shaping`) | figurine détruite → `meta["value"] / model_count_at_start`, soit la **moyenne d'escouade** | Tuer l'aumônier (75) rapporte autant qu'un Intercessor (16) |

Rupture corollaire : **les events ne transportent pas la valeur**. L'event est construit en
**un seul endroit dans tout le moteur** — [shared_utils.py:6309-6313](../../engine/phase_handlers/shared_utils.py#L6309-L6313),
dans `_resolve_one_manual_wound` — et ne porte que `points_per_hp`, `damage`, `destroyed`,
`target_squad_id`, `target_player`. Aucune clé `model_value` / `destroyed_model_value` n'existe
nulle part. Même corrigé en A/B, le reward n'aurait **rien à lire** au moment de la destruction.

> ✅ **Bonne nouvelle vérifiée — le correctif C est beaucoup plus petit que prévu.** Le moteur
> d'allocation est **mutualisé tir/combat** via `ManualAllocCtx` : `fight_handlers.py` ne construit
> **aucun** event, il réutilise `_resolve_one_manual_wound`. **Un seul site à modifier**, pas deux.
> Et surtout : à cet endroit la variable `m` **est le dict de la figurine touchée** (c'est d'elle
> qu'est déjà lu `points_per_hp`, [ligne 6282](../../engine/phase_handlers/shared_utils.py#L6282)).
> Une fois A fait, `m["VALUE"]` est **directement en main** — il n'y a donc **pas besoin de passer
> par `targets_meta`** ni de toucher aux deux sites qui le construisent
> ([shared_utils.py:6130](../../engine/phase_handlers/shared_utils.py#L6130),
> [fight_handlers.py:5707](../../engine/phase_handlers/fight_handlers.py#L5707)). `targets_meta`
> reste ce qu'il doit rester : le porteur des données d'**escouade** (`value`,
> `model_count_at_start`, `player`), consommées par le bonus de wipe.

**Pourquoi ça compte maintenant.** L'allocation des pertes 05.03 (`Documentation/40k_rules/05 -
Attack sequence`) laisse au défenseur le choix de la figurine qui encaisse, et le ciblage
volontaire d'une figurine de valeur est donc une **décision de jeu réelle**. Avec la moyenne
d'escouade, le reward est **plat** sur cette décision : l'agent n'a aucun signal l'incitant à
concentrer le feu sur le Nob, le Sergent ou le personnage attaché. C'est précisément l'effet que
§0.9 rend mesurable, puisque les escouades sont désormais **hétérogènes en points**.

**Ce qui NE doit PAS changer.**
- Le bonus de wipe ([reward_calculator.py:1026](../../engine/reward_calculator.py#L1026)) est
  **déjà correct** : `meta["value"] * squad_kill_bonus_factor` = valeur de l'ESCOUADE, ce qui est
  la sémantique voulue (« l'escouade entière est détruite »). **Ne pas le convertir par figurine.**
- Les **unités mono-figurine** doivent rester **bit-identiques**. Le vérifier plutôt que le
  supposer : `model_count_at_start = 1` ⇒ `value / 1` = `VALUE` de l'unique figurine (posée par
  [game_state.py:967](../../engine/game_state.py#L967)) ; et `total_hp_pool = HP_MAX` ⇒
  `points_per_hp = VALUE / HP_MAX`, identique au per-fig. Les deux formules coïncident — mais
  cela doit être **verrouillé par un test**, pas par ce paragraphe.

⚠️ **Piège de vérification.** L'énoncé naïf « dans le cas homogène la somme doit être inchangée »
est **faux tel quel** : depuis §0.9, une escouade homogène en profil (même `HP_MAX`, même
datasheet) peut être **hétérogène en `VALUE`** — c'est exactement le cas des Boyz (9 × 7 + 12).
L'invariant à tester est donc « **`VALUE` uniforme sur toutes les figurines** ⇒ résultat identique
à l'ancienne formule », pas « même profil ⇒ identique ». Construire le test sur une escouade à
`VALUE` réellement uniforme (Gretchin : 10 × 5), sinon il passera pour la mauvaise raison.

**Travail attendu, dans l'ordre (chaque étape est vérifiable seule) :**
1. **A** — porter `spec["VALUE"]` dans `models_cache` (`_build_models_for_unit`). Source =
   `spec["VALUE"]`, **jamais** `unit["VALUE"]` (valeur d'escouade). Absence de la clé ⇒ `require_key`,
   **pas de défaut** (règle CLAUDE.md : pas de valeur par défaut masquant une donnée absente).
2. **B** — `points_per_hp` **par figurine** = `VALUE_i / HP_MAX_i`, calculé **dans la boucle**
   `for idx, spec in enumerate(model_specs)`. Supprimer le calcul unique ligne 629 et l'agrégat
   `total_hp_pool`, qui n'a alors plus qu'un usage : la **validation** `spec_hp_max <= 0`
   ([ligne 626](../../engine/phase_handlers/shared_utils.py#L626)) — la garder, en la déplaçant
   dans la boucle unique. Mettre à jour la docstring
   [shared_utils.py:580-583](../../engine/phase_handlers/shared_utils.py#L580-L583), qui documente
   encore la formule d'escouade.
   🔻 **Au passage, supprimer un fallback existant** : `... if total_hp_pool > 0 else 0.0`
   ([ligne 629](../../engine/phase_handlers/shared_utils.py#L629)) est une **valeur par défaut
   masquant une erreur** — branche morte, puisque la ligne 626 vient de lever sur tout
   `spec_hp_max <= 0` et que `model_specs` est non vide par construction. Interdit par CLAUDE.md ;
   ne pas le reconduire sur la formule par figurine (`HP_MAX_i` est déjà validé > 0 juste avant).
3. **C** — ajouter la valeur de la figurine détruite à l'**event**, à l'unique site
   [shared_utils.py:6309](../../engine/phase_handlers/shared_utils.py#L6309) (lire `m["VALUE"]`,
   comme `points_per_hp` juste au-dessus), puis remplacer `value / mcs` par cette valeur dans
   `_squad_combat_shaping`. `model_count_at_start` n'est alors plus lu que par le garde `mcs > 0`
   ([reward_calculator.py:1021](../../engine/reward_calculator.py#L1021)), qui **disparaît avec la
   division** — c'est un garde anti-`ZeroDivisionError`, pas une règle métier. Mettre à jour le
   docstring [reward_calculator.py:1006](../../engine/reward_calculator.py#L1006), qui énonce
   encore `(value / model_count_at_start)`.
4. **Tests** — invariant mono-figurine, invariant `VALUE` uniforme (cf. piège ci-dessus), et un cas
   **hétérogène** prouvant que tuer la figurine chère rapporte strictement plus. Suite complète
   attendue verte ; ⚠️ *(affirmation périmée n°6 de §0bis : contredit §0.-1, non vérifiée)* le dossier de rosters de training étant réduit à 2 fichiers, **9 tests liés
   à `roster_pool_schedule` échouent indépendamment de ce travail** — les valider sur un worktree
   propre à HEAD avant de conclure à une régression.

**Note connexe, hors périmètre de ce point.** L'affirmation de §0.9 (« `VALUE` est consommé **par
figurine** — pondération de menace [reward_calculator.py:1442](../../engine/reward_calculator.py#L1442) »)
est **inexacte** : cette ligne lit `friendly["VALUE"]`, soit la valeur de l'**escouade**. La règle
métier 🔒 de §0.9 (suivre le Munitorum, ne pas tuner) reste valable telle quelle ; seule la
justification technique citée est à requalifier.

---

**Ce qui a été livré (2026-07-20) — vérifié, pas supposé.**

| Étape | Fichier | Ce qui a changé |
|---|---|---|
| **A** | [shared_utils.py](../../engine/phase_handlers/shared_utils.py) `_build_models_for_unit` | `models_cache[model_id]["VALUE"] = spec_value`, lu par `require_key(spec, "VALUE")` — **aucun défaut**. Le spec synthétique du chemin **mono-figurine** (unité sans `models[]`) reçoit `"VALUE": value`, ce qui est exact par construction : pour une mono-fig, valeur d'escouade = valeur de la figurine. |
| **B** | idem | `points_per_hp = VALUE_i / HP_MAX_i` calculé **dans la boucle** `for idx, spec`. Supprimés : le calcul unique hors boucle, l'agrégat `total_hp_pool`, **et le fallback `if total_hp_pool > 0 else 0.0`** (valeur par défaut masquante, interdite CLAUDE.md). La validation `spec_hp_max <= 0` a été **déplacée dans la boucle unique**, pas supprimée — verrouillé par `test_hp_max_invalide_leve_toujours`. Docstring réécrite. |
| **C** | idem `_resolve_one_manual_wound` + [reward_calculator.py](../../engine/reward_calculator.py) `_squad_combat_shaping` | L'event porte `"model_value": float(require_key(m, "VALUE"))` — **un seul site** dans tout le moteur, comme prévu (allocation mutualisée tir/combat via `ManualAllocCtx`). Le reward lit `require_key(ev, "model_value") * kill_f` ; `value / mcs` et le garde `mcs > 0` ont disparu. Docstring mise à jour. |

**Tests** — [test_model_value_per_figurine.py](../../tests/unit/engine/test_model_value_per_figurine.py), **14 tests**, trois classes (la 3ᵉ, `TestObservationValueOverTtk`, couvre la rupture D décrite plus bas) :
- `models_cache` : mono-fig inchangé ; **`VALUE` uniforme** (Gretchin 10 × 5) ⇒ identique à l'ancienne formule (c'est bien l'invariant du piège ci-dessus, pas « même profil ») ; **hétérogène** (Boyz 9 × 7 + Nob 12) ⇒ `points_per_hp` 7 vs 12, et assertion explicite que la moyenne 7.5 **n'apparaît plus** ; `HP_MAX` hétérogène ; `VALUE` absente ⇒ lève ; `HP_MAX <= 0` ⇒ lève.
- `_squad_combat_shaping` : mono-fig bit-identique ; `VALUE` uniforme bit-identique ; **figurine chère > figurine bon marché** (`hp_damage_weight = 0` pour **isoler le terme de kill** — sans ça le test passait pour la mauvaise raison, via le terme HP) ; **le bonus de wipe reste sur la valeur d'ESCOUADE** ; event sans `model_value` ⇒ lève ; garde `is_victim` intacte.

**Mutation-testé.** Réintroduire l'ancienne formule (B : `value / (hp_max * len(model_specs))` ; C : `value / mcs`) rend rouges `test_value_heterogene_differencie_les_figurines`, `test_hp_max_par_figurine_divise_bien_par_son_propre_hp`, `test_figurine_chere_rapporte_strictement_plus` et `test_event_sans_model_value_leve`.

⚠️ **Effet de bord rencontré, à connaître.** `require_key(spec, "VALUE")` a cassé **48 tests dans 2 fichiers** (`test_squad_fight_declaration.py`, `test_squad_shoot_declaration.py`) : leurs fixtures appellent `build_units_cache` **directement**, sans passer par `_build_enhanced_unit` qui est le seul producteur de `VALUE` par figurine. Corrigé en ajoutant `"VALUE"` au helper `_m` des deux fichiers — **pas** en assouplissant `require_key`. **Aucun chemin de production n'était concerné** : les 3 producteurs de `models[]` en prod (`game_state.py:210`, `:738`, `:1840`) alimentent tous des unités qui passent ensuite par `_build_enhanced_unit`.

**Rupture D — l'observation de l'agent, régression introduite par A/B (trouvée et corrigée le 2026-07-20).**

| | |
|---|---|
| Emplacement | [observation_builder.py:1496-1505](../../engine/observation_builder.py#L1496-L1505), calcul de `value_over_ttk` (slot ennemi, `obs[base + 7]`) |
| Ce que faisait le code | `ppl = models_cache[e_mids[0]]["points_per_hp"]` puis `e_value = ppl * e_hp_total` — le `points_per_hp` de la **figurine d'index 0** extrapolé à toute l'escouade |
| Pourquoi c'était juste AVANT | `points_per_hp` était **uniforme par construction** : `ppl × HP_total` valait exactement la `VALUE` d'escouade |
| Pourquoi A/B l'ont cassé | `points_per_hp` devient **hétérogène**. Boyz (9 × 7 + Nob 12) : `7 × 10 = 70` au lieu de 75. L'erreur dépend de **qui est en index 0** — un personnage attaché cher en tête ferait sur-évaluer toute l'escouade |
| Portée | **L'observation de l'agent** (`value_over_ttk` = sa perception de la valeur des cibles) — soit exactement ce que §0.12 prétendait améliorer |
| Correctif | `e_value = Σ points_per_hp_i × HP_CUR_i` sur les figurines vivantes. Même sémantique qu'avant (décroît avec les blessures), calculée par figurine. **Le fallback `.get(..., 0.0)` et le `try/except Exception` ont été supprimés** — c'est précisément ce masquage qui a rendu la régression silencieuse |

Tests : `TestObservationValueOverTtk` (2 de plus, **14 au total** dans le fichier). L'invariant
choisi est le plus fort disponible — **le résultat ne doit pas dépendre de l'ORDRE des
figurines** : Nob en index 0 vs index 9 ⇒ même `value_over_ttk`. **Mutation-testé** : restaurer
`ppl * e_hp_total` rend `test_invariant_a_lordre_des_figurines` rouge.

⚠️ **Conséquence sur les mesures** : le run de 500 épisodes de **§0.14 a tourné AVANT ce
correctif**, donc sur une observation fausse pour toute escouade hétérogène — c'est-à-dire pour
les deux rosters de §10.2. Son score est à jeter pour cette raison **en plus** de celle déjà
notée (12 épisodes d'éval).

📌 **Réserve non traitée** (hors périmètre §0.12) : la variable locale `model_count_at_start` de `_build_models_for_unit` est **inutilisée** — elle l'était déjà avant ce travail, ce n'est pas une séquelle. Non supprimée.


### 0.13 Run de validation x5_debug 100 ép. — ✅ pipeline OK / éval finale sur le mauvais pool — ✅ CORRIGÉ (2026-07-20)

**Le run.** `x5_debug` reparamétré par l'utilisateur (100 épisodes, `bot_eval_freq: 50`,
`bot_eval_final: 2`), lancé après les fixes §0.10 et §0.11 :
**100/100 épisodes, exit 0, aucune exception**, ~114 s/ép. à 8 envs (28 min). Éval finale
exécutée, modèle écrasé (autorisation utilisateur explicite) — `model_ArmageddonAgent.zip`
au 2026-07-20 02:14 ; la sauvegarde `_backup_pre_munitorum_20260719_232816/` est intacte.

> ➜ **Déplacé en §0.14 (ouvert).** Rien n'a été supprimé : le contenu est intégral là-bas.

⚠️ **Piège de perf, à ne pas re-diagnostiquer** : l'ETA affichée au 1ᵉʳ épisode (~16 h 45 sur le
run de 1000) est un **artefact de warmup** ; elle retombe à sa vraie valeur dès le 10ᵉ épisode.
Ne jamais extrapoler une durée de run depuis les premiers épisodes.

---

🔴 **BUG VÉRIFIÉ — l'évaluation FINALE ignore `bot_eval_scenario_pool` et tourne sur le scénario
d'ENTRAÎNEMENT.**

**Preuve dans la sortie du run** : `🏁 Scenario ranking (combined): - training_armageddon`,
alors que la config demande `holdout`.

**Root cause, 5 sites d'appel de `evaluate_against_bots` audités un par un :**

| Site | `scenario_pool` transmis |
|---|---|
| [train.py:3012](../../ai/train.py#L3012) | ✅ `"holdout"` (en dur) |
| [train.py:4257](../../ai/train.py#L4257) | ✅ `"holdout"` (en dur) |
| [train.py:4646](../../ai/train.py#L4646) | ✅ `"holdout"` (en dur) |
| [training_callbacks.py:2449](../../ai/training_callbacks.py#L2449) | ✅ `self.scenario_pool` (éval **intermédiaire**, alimentée par [train.py:3428](../../ai/train.py#L3428)) |
| [training_callbacks.py:1024](../../ai/training_callbacks.py#L1024) `_run_final_bot_eval` | 🔴 **RIEN** → défaut de signature |

La signature déclare `scenario_pool: str = "training"`
([bot_evaluation.py:744](../../ai/bot_evaluation.py#L744)). **Un seul site sur cinq oublie le
paramètre, et une valeur par défaut masque l'oubli** — interdit par CLAUDE.md, et exactement la
famille T6-a / T6-b / T6-e : *migration partielle d'un chemin, un site oublié, aucun message*.

**Conséquences :**
1. **Le score `Combined 0.46` de ce run ne vaut RIEN pour §10.6** : mesuré sur le scénario
   d'entraînement, pas sur le holdout. Le contrat §10.5 est contourné sur ce chemin.
2. De toute façon, à **1 épisode par bot** (3 victoires / 3 défaites), c'est du bruit pur —
   ne pas l'interpréter même une fois le pool corrigé.
3. Tout « best model » retenu par un gating adossé à cette éval l'aurait été sur le mauvais
   jeu (sans effet ici : `model_gating_enabled: false` et `save_best_min_episodes` > 100).

**✅ CORRIGÉ (2026-07-20).** `_run_final_bot_eval` passe désormais `scenario_pool="holdout"`
explicitement ([training_callbacks.py:1024](../../ai/training_callbacks.py#L1024)).

**Pourquoi en dur plutôt que résolu depuis la config** (arbitrage tranché, ne pas rouvrir) :
l'éval finale est une éval de **MESURE**, elle doit porter sur le holdout par contrat §10.5 —
comme les 3 autres sites de mesure (`train.py:3012`, `:4257`, `:4646`), qui codent déjà la même
valeur en dur. La clé de config `bot_eval_scenario_pool` n'alimente, elle, que l'éval
**INTERMÉDIAIRE** (gating en cours d'entraînement), où un pool `training` peut se défendre.
Re-résoudre depuis la config ici aurait dupliqué la logique de layering
(`callback_params` → `_training_common.json`) pour aboutir à la même valeur.
`MetricsCollectionCallback` n'a pas d'attribut `scenario_pool` et n'en a donc pas besoin.

**Non-régression** : `tests/unit/ai/test_final_eval_uses_holdout.py`, **2 tests**, tous deux
**rouges avant le fix** (vérifié par `git stash` du seul fichier source) :
1. **comportemental** — `_run_final_bot_eval` est réellement appelée, `evaluate_against_bots`
   interceptée (patch sur `ai.bot_evaluation`, car l'import est *lazy* dans la méthode), et
   l'argument reçu est `holdout` ;
2. **de contrat** — parcours AST de `train.py` + `training_callbacks.py` : **aucun** appel à
   `evaluate_against_bots` ne doit omettre `scenario_pool`. Il attraperait la réintroduction du
   bug sur un site que le test comportemental ne couvre pas, et pointe le site fautif par
   fichier:ligne. Il commence par vérifier que le défaut de signature vaut bien `"training"` —
   si quelqu'un le change, le test le signale au lieu de devenir silencieusement sans objet.

Suite complète verte (exit 0).

> ➜ **Déplacé en §0.14 (ouvert).** Rien n'a été supprimé : le contenu est intégral là-bas.

⚠️ **Piège latent voisin, découvert au passage.** Dans
`ArmageddonAgent_training_config.json`, `bot_eval_scenario_pool` est placé à la **racine** de
`x5_debug`, alors que `_resolve_callback_value` ([train.py:3273](../../ai/train.py#L3273)) le
cherche dans **`callback_params`** puis retombe sur `config/agents/_training_common.json`.
La clé racine est donc **ignorée**. Sans effet aujourd'hui (les deux valent `holdout`), mais
toute surcharge par agent placée à la racine serait **silencieusement sans effet**.

### 0.18 `collision intra-plan` — cause trouvée dans le pile-in — ✅ CORRIGÉ (2026-07-20)

> ✅ **RÉSOLU le 2026-07-20.** L'écrivain fautif est identifié, le bug **reproduit par un test**
> (pas par un run), corrigé sur ses **deux** consommateurs, et la suite complète est verte.
> La part autrefois ouverte (ordre glouton, B2B non maximal) est **également corrigée** — voir **§0.21**.
> ⚠️ Entrée conservée ici et **non descendue en §0hist** tant que la session écrit dans ce
> fichier ; l'énoncé d'origine ci-dessous est celui du diagnostic, conservé intégralement.

**Cause racine — `fight_pile_in_plan` ([shared_utils.py:6989](../../engine/phase_handlers/shared_utils.py#L6989)).**
Trois défauts cumulés faisaient qu'une cellule occupée par une camarade était vue comme libre :

| # | Défaut | Site |
|---|---|---|
| 1 | `occupied_after` démarrait **vide** — non amorcé avec les origines de l'escouade | [:6989](../../engine/phase_handlers/shared_utils.py#L6989) |
| 2 | `_cell_legal` **saute sa propre escouade** quand il teste l'occupation (`if str(sid) == squad_id: continue`) | [:7009-7010](../../engine/phase_handlers/shared_utils.py#L7009-L7010) |
| 3 | La branche « déjà B2B → reste sur place » `append` son origine **sans appeler `_cell_legal`** | [:7020-7022](../../engine/phase_handlers/shared_utils.py#L7020-L7022) |

**Scénario.** S#0, traitée en premier, choisit la cellule X : légale, car X appartient à sa
propre escouade (2) et `occupied_after` est encore vide (1). Mais X est l'origine de S#1, traitée
plus tard, qui y est déjà B2B et **reste sur place sans contrôle** (3). Les deux finissent sur X.
Le plan étant un 3-tuple, le niveau est inchangé pour les deux → même `(col, row, niveau)`.
Ni la « validation finale » ([:7073-7089](../../engine/phase_handlers/shared_utils.py#L7073-L7089),
qui ne teste que cohérence et zone d'engagement) ni `commit_move` (« ne re-valide pas », par
contrat, [:4284](../../engine/phase_handlers/shared_utils.py#L4284)) ne rattrapent.

**Pourquoi ça n'explosait qu'au move suivant.** Exactement ce que le diagnostic ci-dessous
démontrait : la translation cube de `build_rigid_plan` est **injective**, donc la superposition
d'origine se reporte sur chaque destination et `validate_move_plan` la voit — une phase trop
tard, sous la forme d'un `collision intra-plan` qui accusait le move.

**Second consommateur : `squad_consolidate_plan`** ([:7316](../../engine/phase_handlers/shared_utils.py#L7316)).
Même défaut, trouvé en corrigeant le premier. Pas de branche B2B ici : la collision naît de la
branche « rien de mieux → reste sur place » ([:7364-7365](../../engine/phase_handlers/shared_utils.py#L7364-L7365)),
dont l'origine a pu être prise entre-temps. *Un bug, deux consommateurs* — même famille que T6-h.

**Correctif — l'affectation gloutonne est remplacée par un COUPLAGE MAXIMUM.** Le parcours dans
l'ordre des index est supprimé : il était à la fois la cause de la collision *et* une violation
de 12.03 (cf. §0.21). L'algorithme est désormais :

1. **Immobiles** — figurines au contact socle à socle : elles restent, leur cellule est
   définitivement réservée (12.03 WHILE MOVING, « Models in base-contact … **cannot be moved** »).
2. **Couplage maximum** figurine → cellule bord-à-bord (algorithme de Kuhn,
   `_max_b2b_matching`), qui réalise exactement l'obligation « engaged with it **if possible** »
   et l'intention « **maximise** the number of models that are engaged ». **Indépendant de
   l'ordre**, donc la classe de bug d'origine ne peut plus se reformer.
   Une cellule qui est l'origine d'une camarade n'est utilisable que si celle-ci la quitte :
   point fixe monotone (`blocked` décroît strictement), sans collision à **chaque** itération.
3. **Repli** pour les non-couplées : finir strictement plus proche, sinon rester sur place
   (le pile-in est optionnel — encart 12, « you don't have to pile in »).

`mids` ne contient que des figurines **vivantes** — vérifié : `destroy_model` retire l'entrée de
`models_cache` **et** de `squad_models`
([:3213-3221](../../engine/phase_handlers/shared_utils.py#L3213-L3221)) — donc aucune cellule de
cadavre n'est réservée.

**SOURCE UNIQUE.** Pile-in et consolidation partagent `_assign_cells_toward_enemies` : 12.03 et
12.08 (modes Ongoing et Engaging, lus dans le PDF) portent la **même** obligation. La
duplication est ce qui avait permis au bug d'exister en deux exemplaires ; la supprimer est le
correctif structurel. ➜ **Corrige au passage un point de règle jamais implémenté** :
`squad_consolidate_plan` ne respectait pas « Models in base-contact … cannot be moved ».
L'appliquer inconditionnellement est correct — en mode Engaging l'unité n'est pas engagée, donc
aucune figurine n'est au contact et la contrainte est sans objet, jamais fausse.

**Preuves.**

| Élément | Preuve |
|---|---|
| Reproduction | `tests/unit/engine/test_pile_in_intra_squad_collision.py` — rouge sur le code d'avant : `[('S#0',10,9), ('S#1',10,9)]` |
| Optimalité (12.03) | **Mutation-testé** : couplage remplacé par un glouton → **1 figurine engagée sur 2** ; couplage → **2 sur 2** |
| Correctif consolidation | **Mutation-testé** : neutralisé → rouge, restauré → vert |
| Non-régression | Suite `tests/unit` complète, **exit 0** |
| Chemin PvP | **Non concerné**, vérifié dans le code (order-independent par construction) |

⚠️ **Ce que ça ne prouve PAS** : que le training va au bout. Aucun run long n'a été relancé
depuis le correctif. La leçon de cette entrée s'applique à elle-même — il faudra **2-3 runs**,
un run vert ne valant pas preuve (§0.14).

⚠️ **Le test de non-régression du second test a failli passer pour la mauvaise raison** : sans
murer cinq hex pour priver la figurine de toute alternative, il passait **déjà avant** le
correctif. Motif §0.19 rencontré en direct.

---

**Énoncé d'origine (diagnostic du 2026-07-20, conservé intégralement) :**

**Reproduction.** Commande **identique** à celle de §0.14, relancée après le correctif de la
rupture D (§0.12) :

```
python3 ai/train.py --agent ArmageddonAgent --scenario bot --new \
        --training-config x5_debug --total-episodes 500
```

Arrêt à l'**épisode ~280** (worker `SubprocVecEnv` mort → `EOFError` côté maître → `💥 Fatal
error`) :

```
ValueError: execute_squad_move a échoué : squad=104 type=advance dest=(137,212)
depuis (135,180) — la destination vient du pool BFS du masque, elle DOIT être exécutable
(incohérence masque/exécution). Contrainte violée : collision intra-plan :
deux figurines en (147,227) niveau 0 (dont 104#5)
```

⚠️ **Le premier run de §0.14 avait passé les 500 épisodes.** Même commande, même seed de config.
La divergence vient du correctif D, qui change l'observation, donc la politique, donc les
trajectoires. **Leçon : sur ce crash, « un run est passé » n'est PAS une preuve de
non-régression** — il faut plusieurs runs, ou une preuve statique.

**Ce qui est DÉMONTRÉ (pas supposé) — la collision préexistait au move.**

`build_rigid_plan` ([shared_utils.py:3312](../../engine/phase_handlers/shared_utils.py#L3312))
translate en **cube** : `cube_to_offset(mx + dcx, my + dcy, mz + dcz)`.
`offset_to_cube`/`cube_to_offset` ([hex_utils.py:92](../../engine/hex_utils.py#L92)) sont
**bijectives**, et la translation cube est une **injection** : deux positions distinctes restent
distinctes. Par ailleurs le plan qu'elle produit est un **3-tuple sans niveau**, donc
`_target_level` relit le niveau **du `models_cache`**, inchangé par le move.

⇒ **Une collision intra-plan sur un plan rigide implique une collision à l'ORIGINE** : deux
figurines de l'escouade 104 occupaient **déjà** la même `(col, row, niveau)` avant le move. Le
crash n'est donc **pas** un défaut de la translation (T6-h), ni du pool BFS ou de son érosion
(T6-g) : **le masque et l'exécution sont d'accord — c'est l'état de départ qui est invalide.**
Le fix de §0.11 (clé `(niveau, col, row)`) reste correct ; il traitait un **autre** cas.

**Ce qui n'est PAS identifié.** *Quel* écrivain de positions produit la superposition. Le
soupçon porte sur un chemin qui écrit dans `models_cache` **sans passer par
`validate_move_plan`** — pile-in / consolidation, retrait de coherency (03.03), déploiement —
mais **rien n'a été vérifié**, et ce document interdit d'ouvrir un chantier sur une intuition
(§0bis). C'est le point de départ du prochain travail.

**Piste d'instrumentation suggérée** (à valider avant de coder) : faire dire au message d'erreur
**les positions d'ORIGINE** des deux figurines en cause, pas seulement leur destination. Si
elles sont identiques, la démonstration ci-dessus est confirmée en runtime et le crash devient
un simple révélateur ; l'invariant « deux figurines vivantes d'une même escouade n'occupent
jamais la même `(col, row, niveau)` » mérite alors d'être vérifié **à l'écriture**, au plus près
du fautif, plutôt qu'au move suivant.

~~⚠️ **Bloquant** : aucun run long ne va au bout de façon fiable, donc **§0.14 et le critère §10.6
sont bloqués derrière cette entrée**.~~ ➜ **LEVÉ le 2026-07-20** par le correctif ci-dessus.
§0.14 est **débloquée** — sous réserve des 2-3 runs qui restent à faire.

📌 **Note annexe** : après ce crash le process a affiché `💥 Fatal error` et se serait terminé
avec un **code de sortie 0**. ➜ **Affirmation DÉMENTIE le 2026-07-20, voir §0.20** — le code
sort bien en 1, vérifié statiquement et par exécution. Aucun fix n'est requis.

### 0.20 « Le crash sort en code 0 » — ✅ DÉMENTI, AUCUN FIX REQUIS (2026-07-20)

**Origine.** La note annexe de §0.18 affirmait que le training, après `💥 Fatal error`, se
terminait avec un **code de sortie 0** — donc qu'un échec passait pour un succès auprès de toute
automatisation. L'entrée a été ouverte pour corriger ce piège. **L'investigation l'a démentie.**

**Ce qui a été vérifié (statique).**

| Site | Constat |
|---|---|
| [train.py:5033-5037](../../ai/train.py#L5033-L5037) | Le handler qui imprime `💥 Fatal error` fait `return 1`. |
| [train.py:5039-5041](../../ai/train.py#L5039-L5041) | `sys.exit(exit_code)` — le 1 est propagé au shell. |
| `ai/train.py`, `ai/env_wrappers.py`, `ai/training_callbacks.py` | **Aucun autre** `sys.exit` / `os._exit`, et **aucun** handler `EOFError` / `BrokenPipe` qui pourrait avaler le code. |
| `train_model` | Retourne `False` sur exception ; `main` en tire `return 1`. Pas de chemin qui rendrait 0 après une exception. |

**Ce qui a été vérifié (exécution).** `python3 ai/train.py --agent AgentQuiNExistePas --scenario
bot --new --total-episodes 1` → imprime `💥 Fatal error: No config directory found…` et
**sort en 1** (`EXIT=1`).

**Cause probable de l'observation d'origine — non tranchée.** Une mesure côté shell : un
`| tee` (ou tout pipe) renvoie le code de sortie du **dernier** élément du pipeline, pas celui
de python. Impossible de trancher sans le shell exact du run de §0.18.

⚠️ **Leçon.** Cette entrée a failli devenir un chantier de fix sur un bug **qui n'existe pas**,
sur la seule foi d'une note d'observation non revérifiée — et c'est un lecteur, pas l'auteur,
qui a demandé « la doc prévoit-elle de le fixer ? ». Le motif n°1 du document s'applique aussi
aux notes marquées « hors périmètre » : **elles échappent à la relecture précisément parce
qu'elles sont marquées annexes.**

### 0.21 Pile-in / consolidation : ordre glouton, B2B non maximal — ✅ CORRIGÉ (2026-07-20)

> Ouverte **et fermée le même jour**. Elle avait été rédigée comme une dette d'algorithme
> (« correct mais pas optimal ») ; l'utilisateur a refusé ce mode de clôture, et l'optimum a été
> implémenté. ➜ **C'est l'origine de la règle 7 de `CLAUDE.md`** (« CLÔTURE COMPLÈTE DES
> SUJETS ») : une dette n'est ouvrable que si le traitement est *techniquement impossible* dans
> la session, jamais parce qu'il est plus long.

**Ce qui était en dette.** `fight_pile_in_plan` et `squad_consolidate_plan` attribuaient les
cellules **dans l'ordre des index**. Le placement était légal, mais pas maximal : une figurine
pouvait se voir refuser une cellule qu'une figurine suivante allait libérer, ou prendre la seule
cellule accessible à une autre. Or 12.03 / 12.08 WHILE MOVING imposent :

> ▪ Each model that is moved must end its move closer to the closest [target], and
>   **engaged with it if possible**.

et l'encart du même PDF donne l'intention : « units will pile in to **maximise** the number of
models that are engaged ». **Un glouton ne satisfait pas cette obligation** — ce n'était donc
pas un simple manque d'optimalité, mais une violation de règle.

**Correctif.** Couplage maximum (Kuhn) — voir §0.18, section « Correctif », pour l'algorithme
complet et la source unique partagée avec la consolidation.

**Preuve — mutation-test.** Couplage remplacé par une affectation gloutonne sur le scénario
`test_greedy_order_does_not_cost_an_engagement` : **1 figurine engagée sur 2**. Avec le
couplage : **2 sur 2**. Le test verrouille donc l'optimalité, pas seulement l'absence de
collision.

### 0.15 Rosters `training` ≡ `holdout_regular` — ✅ TRANCHÉ (2026-07-21 : identité ASSUMÉE)

> Part **ouverte** de §0.6. La suppression des listes holdout mortes, elle, est résolue — voir
> §0.6 pour la décision et sa justification.

⚠️ **Les rosters `training` et `holdout_regular` sont IDENTIQUES** (vérifié : mêmes compositions,
mêmes totaux, aux deux emplacements). C'est cohérent avec la décision §10.5 — le holdout porte sur
l'**adversaire**, pas sur le roster — mais il faut en avoir conscience : **il n'existe aucune
séparation de listes entre entraînement et évaluation**. Un sur-apprentissage sur les
particularités de ces deux listes ne serait détecté par aucun des scénarios d'éval actuels.

**Statut** : ✅ **TRANCHÉ le 2026-07-21 — l'utilisateur ASSUME l'identité** (« Oui : rosters
training ≡ holdout_regular »). Le holdout porte donc **exclusivement sur l'adversaire** (§10.5),
jamais sur le roster : c'est cohérent avec la démo de financement (2 rosters fixes SM/Orks, §10.2)
et avec la spécialisation assumée. **Conséquence à garder en tête** : aucun scénario d'éval ne
détectera un sur-apprentissage sur les particularités de ces deux listes ; le win-rate par matchup
mesure la robustesse à l'**adversaire**, pas au roster. Ce n'est pas un angle mort à corriger,
c'est le périmètre choisi.

### 0.16 Réserves de l'évaluation — ✅ SOLDÉE (2026-07-21 ; extraits de §0.5, §0.6 et §0.7)

> Trois réserves distinctes, aucune bloquante aujourd'hui, toutes déjà constatées. Leurs
> entrées d'origine (§0.5 fail-fast, §0.6 listes holdout, §0.7 run 60/60) sont résolues par
> ailleurs.

**(a) Réserves du fail-fast `--eval` (ex-§0.5)**

Réserves :
- ✅ **CORRIGÉE (2026-07-21)** — Le bloc `🏁 Scenario ranking` s'imprimait **avant** le raise
  eval-only sur `total_failed_episodes > 0` : quand des épisodes échouaient, les `combined`/
  `worst_bot_score` par scénario (calculés sur un dénominateur **tronqué** — épisodes plantés
  retirés par `_get_result_with_timeout`) étaient présentés comme un classement fiable juste
  avant que la mesure ne soit invalidée. **Root cause** : la décision d'affichage n'était pas
  gardée par la fiabilité de l'éval. **Fix** : décision extraite dans le helper pur
  `_render_scenario_ranking(scenario_scores, total_failed_episodes)`
  ([bot_evaluation.py](../../ai/bot_evaluation.py)) — si `total_failed_episodes > 0`, il retourne
  un **avertissement explicite** (`⚠️ Scenario ranking SUPPRIMÉ : évaluation NON FIABLE`) au lieu
  du classement, jamais un chiffre. Vaut pour le training ET l'eval-only (les deux passent par ce
  print quand `show_summary`). **Verrou** : 3 tests dans `test_eval_holdout_opponent.py`
  (affichage nominal trié, suppression + avertissement quand `failed>0`, liste vide sans scores) ;
  **mutation** de la garde (`total_failed_episodes > 0` → `False`) → **1 rouge** ciblé, vert après.
- ✅ **CORRIGÉE (2026-07-21)** — `worst_bot_name` du chemin eval-only était calculé sur **toutes**
  les clés de `bot_eval_weights`, `tactical` **inclus**, alors que §10.5 impose son exclusion des
  signaux de sélection. Le poids nul ne protégeait pas ce site (min sur des NOMS). **DEUX sites
  étaient touchés, pas un** : le eval-only ([train.py:4682](../../ai/train.py#L4682)) ET le
  `worst_bot_score` **par-scénario** de [bot_evaluation.py:1180](../../ai/bot_evaluation.py#L1180),
  qui alimente le **gate de curriculum** (`_extract_worst_bot_scores_for_gate`) — donc un vrai
  signal de sélection, pas seulement un affichage. Source unique : helper
  `selection_worst_bot(scores)` dans `training_callbacks.py` (exclut `HOLDOUT_BOT_NAMES`, lève si
  plus aucun bot de sélection). Verrou : 3 tests dans `test_eval_holdout_opponent.py` (lock
  comportemental « holdout=min ne pilote pas worst_bot », lock du `raise`, lock **structurel** que
  les deux sites délèguent au helper) ; **2 rouges sous mutation** du helper, verts après. Le test
  préexistant `test_holdout_bots_excluded_from_every_selection_signal` couvrait metrics_tracker
  mais **manquait ces deux sites** — c'était exactement le trou.

**(b) Le 7ᵉ site du portage n'est pas couvert runtime — ✅ STATUS QUO VALIDÉ (2026-07-21)**

Décision utilisateur : **`DefensiveSmartBot` reste hors éval.** Il avait été retiré délibérément
parce qu'il **sous-performait** ; le réintroduire seulement pour couvrir `_best_target_slot_by_threat`
en runtime n'a pas de justification (et fausserait la composition d'éval, donc `combined` et poids).
Ce site reste couvert par son **test unitaire**, ce qui est jugé suffisant. ➜ Sujet clos, déplacé en
**§0ter — Notes post-implémentation**. (Constat d'origine conservé ci-dessous pour mémoire.)

- Le **7ᵉ site du portage** (`_best_target_slot_by_threat`) n'est couvert que par un test unitaire :
  son appelant `DefensiveSmartBot` n'est pas dans `bot_eval_weights`, donc l'éval ne le joue pas
  (`active_bot_names = tuple(eval_weights.keys())`, [bot_evaluation.py:893](../../ai/bot_evaluation.py#L893)).
  Piège §10.5 : **une liste de poids détermine qui TOURNE, pas seulement qui COMPTE.**

**(c) Clé de config `holdout_hard_opponent_budget_modifier` — ✅ CONSERVÉE DÉLIBÉRÉMENT (2026-07-21)**

Décision utilisateur : **garder la clé ET `scripts/build_holdout_benchmark.py`.** Un holdout à armées
**générées** est prévu **après la démo** (une fois les 2 armées focus terminées). La clé n'est donc pas
« morte » mais **en attente d'usage** : elle n'est simplement pas consommée par le chemin de training
actuel (2 rosters fixes, §10.2). ➜ Ni la clé ni le script ne sont supprimés ; ce n'est plus une
réserve mais un **choix assumé**. Note en §0ter.

### 0.17 Travail non commité — ✅ CLÔTURÉE (entrée périssable périmée : tout est commité, `git status` propre)

⚠️ **Entrée périssable par nature : la confronter à `git status` / `git log` AVANT de s'en
servir.** Elle a déjà été fermée à tort une fois, rouverte, puis **rendue fausse par les commits
eux-mêmes** — la version précédente listait 6 fichiers « non commités » au moment où ils étaient
commités. Une entrée d'état ne survit pas à l'action qu'elle décrit.

**Session du 2026-07-20 : intégralement commitée**, `HEAD` = `056c948e`, arbre de travail propre.
Quatre lots, du plus indépendant au plus transverse :

| Lot | Commit | Contenu |
|---|---|---|
| A | `47af78f3` | Correctif §0.18/§0.21 — couplage maximum, source unique pile-in/conso, 4 tests |
| B | `ea79e545` | Audit §0.19.2 — 3 replis silencieux de `_ai_select_fight_target`, 6 tests |
| C | `04170652` | Documentation — §0.18/§0.20/§0.21, §0.19.1/§0.19.2, garde d'arbre en §0bis |
| D | `056c948e` | Gouvernance — **règle 7 de `CLAUDE.md`** (lot séparé : ce n'est pas du code) |

🔴 **`config/users.db` — restauré (`git checkout`) AVANT les commits, il n'entre dans aucun.**
Fichier **protégé** (CLAUDE.md), sali par les runs d'enquête §0.18 (`probe20`, `probe60`).
Il redeviendra sale au prochain training : le restaurer avant chaque commit.

**Pourquoi l'entrée reste OUVERTE malgré tout** : les tests R4 de §8.3 sont en cours d'écriture
(cf. §0.19). Ils produiront du non-commité dès qu'ils existeront. Fermer cette entrée maintenant
la rendrait fausse une troisième fois.

### 0.19 Revérifier T1→T5 et la section 9 ligne à ligne — ✅ SOLDÉ (§0.19.1 → §0.19.3, 2026-07-21)

**Énoncé.** Les tranches **T1, T2, T3, T4, T5** (§5) et toute la **section 9** (Phase A') sont
marquées ✅ FAIT, mais **n'ont jamais été revérifiées ligne à ligne contre le code**. Leur statut
repose sur les sessions où elles ont été écrites, pas sur un audit ultérieur. La réserve existe
depuis le 2026-07-19 en §0bis (« Réserve de méthode — ce qui n'a pas été revérifié ») ; elle y
est une **mise en garde**, pas une tâche. **Cette entrée en fait une tâche**, pour qu'elle cesse
d'être un avertissement que chacun contourne.

**Pourquoi ça n'est pas de la précaution abstraite.** Le taux de découverte est élevé partout où
on a effectivement regardé :

| Session | Ce qui a été trouvé en revérifiant |
|---|---|
| 2026-07-19 soir | **3** affirmations périmées (« prochain bloqueur §10.4 » déjà résolu ; « archivage des holdouts à faire » déjà fait ; « 9 échecs préexistants » alors que la suite est verte) |
| 2026-07-20 | **8** affirmations périmées recensées en §0bis, dont la n°6 (« 9 tests `roster_pool_schedule` échouent ») **démontrée fausse** par la suite complète |
| 2026-07-20 | **§0.11 déclaré résolu ne l'est pas** (§0.18) — et le T6-i portait déjà, en 2026-07-19, le motif « code testé mais jamais appelé » |

Trois marqueurs ✅ démentis sur les seules zones auditées. **Rien n'indique que T1→T5 et la
section 9 soient d'une autre nature** — simplement, personne n'y a regardé.

**Méthode suggérée** (une tranche = une passe, résultat écrit ici même) :
1. Pour chaque critère d'acceptation de §6, retrouver **le test** qui le verrouille — pas le
   code, le **test**. §8 pose la règle « une règle = son fichier de tests ».
2. Vérifier que ce test **s'exécute** (il est collecté par la suite) **et qu'il échoue** si on
   neutralise le code qu'il prétend couvrir. Le motif récurrent de ce projet est le **code testé
   mais jamais appelé** (T6-i) et le **test qui passe pour la mauvaise raison** (rencontré en
   §0.12 sur le bonus de kill, où le terme HP masquait le terme testé).
3. Tout ✅ qui ne survit pas à (1) et (2) redevient ⏳, avec la preuve du démenti.

⚠️ **Ne pas « nettoyer » en relisant la prose.** Corriger une affirmation sans relire le code
reproduit exactement l'erreur qu'on cherche — c'est écrit en tête du tableau des affirmations
périmées (§0bis), et c'est pour cette raison que ces 8 lignes ont été **signalées et non
corrigées**.

**Non planifié** : cette entrée n'a pas d'ordre dans le tableau d'état. C'est un audit de fond,
à mener quand le chemin critique (§0.18 → §0.14) est dégagé — ou immédiatement si l'on doute
d'une tranche en particulier.

#### 0.19.2 Retrait du repli silencieux de `_ai_select_fight_target` — ✅ FAIT (2026-07-20)

**Décision utilisateur** : « il faut absolument fixer ça ». Livré après la fin de la chasse §0.18.

**Ce qui était en cause.** `_ai_select_fight_target` (fight_handlers) enveloppait tout son corps
dans un `try/except Exception: return valid_targets[0]`. Il avalait les **deux** `require_key`
(`reward_configs`, puis la config de l'agent combattant) **et** le `ValueError` de
`get_model_key` sur un `unitType` inconnu. **Aggravant vérifié** : sa seule trace était
`add_console_log`, qui est un **no-op tant que `debug_mode` est faux**
([game_utils.py:74](../../engine/game_utils.py#L74)) — en entraînement normal l'erreur était
**totalement** silencieuse, le seul symptôme étant un ciblage de mêlée dégradé sur la première
cible du pool.

**Ce qui a été écarté avant d'agir.** On pouvait craindre que le repli soit atteint en
permanence : tous les `unitType` des rosters mappent vers `CoreAgent`, alors que le moteur tourne
en `rewards_config="ArmageddonAgent"`. **Faux** : [w40k_core.py:918-924](../../engine/w40k_core.py#L918-L924)
enregistre le `model_key` de **chaque** unité vers les rewards de l'agent contrôlé, donc
`reward_configs` contient bien `CoreAgent`. Le cas nominal n'atteint pas le repli — c'est ce qui
rendait le retrait sûr.

**Fix** : `try/except` supprimé, corps désindenté, aucune autre modification de comportement.

**Test** : `tests/unit/engine/test_fight_target_selection_no_fallback.py` (+4, porté à **10**
par §0.19.3) —
`reward_configs` sans la clé de l'agent, `reward_configs` absent, `unitType` inconnu, plus une
non-régression sur l'erreur explicite qui précède le `try`.
**Contre-épreuve faite** (`git stash` du seul `fight_handlers.py`) : **3 rouges sur le code
d'avant** (`DID NOT RAISE`), **4 verts après**. Suite complète `EXIT=0`.

⚠️ **Piège rencontré en écrivant le test** : il attendait `KeyError`, alors que `require_key`
lève `ConfigurationError` (sous-classe de `RuntimeError`,
[data_validation.py:17](../../shared/data_validation.py#L17)). Le test a donc échoué **après** le
fix alors que le fix était bon — c'était l'attente qui était fausse. Corrigé en vérifiant
**type ET fragment de message** (§8.1).

**Les DEUX autres replis de la même fonction — également retirés (2026-07-20).** Ils avaient
d'abord été renvoyés à l'utilisateur « pour arbitrage » : **c'était une erreur de cadrage**.
La règle métier était déjà posée (« aucun fallback pour masquer une erreur ») ; il ne manquait
que la **lecture du code**, qui est du ressort de l'implémentation. Rappel utilisateur, à
retenir : *« Je tranche le métier, pas l'optimisation du code. »*

| Repli | Ce que la lecture a établi | Remplacé par |
|---|---|---|
| `if not valid_targets: return ""` | **Branche MORTE** : les **4** sites d'appel gardent déjà le pool vide en amont — fight_handlers ~3381 (`if not targets: return []`), ~5537 (`if not valid: … return`), ~6271 (`if valid:`), w40k_core ~5518 (`if targets else None`). | `ValueError` « pool de cibles VIDE » |
| `if not target: continue` (×2 boucles) | Le pool vient de `units_cache` ([fight_handlers:2037](../../engine/phase_handlers/fight_handlers.py#L2037)) ; une cible qui y figure sans être dans `unit_by_id` est une **désynchronisation d'index**, donc un bug. Si TOUTES manquaient, la fonction renvoyait `valid_targets[0]` sans avoir scoré. | `ValueError` « absente de unit_by_id » |

⚠️ **Affirmation fausse émise en cours de route, corrigée après lecture** : il avait été écrit que
le `""` « remonte à 3 des 4 sites d'appel **sans garde** ». C'est l'**inverse** — les 4 gardent.
Le recensement avait été fait de mémoire du `grep`, pas en lisant les sites. Motif n°1 du
document, commis dans la session qui l'auditait.

**Tests (portés à 6)** : + `test_empty_target_pool_raises_instead_of_empty_string` et
`test_target_missing_from_unit_by_id_raises`. Contre-épreuve rejouée (`git stash` du seul
`fight_handlers.py`) : **5 rouges avant, 6 verts après**. ✅ **Cette mesure est fiable même en
contexte concurrent** : elle ne dépend que de `fight_handlers.py`, qu'aucun autre agent ne
touche — contrairement aux suites complètes (cf. le piège « verrou global » de §0bis).

#### 0.19.3 Fermeture de T1 — les deux trous de §0.19.1 sont comblés — ✅ FAIT (2026-07-21)

**Déclencheur** : règle 7 de `CLAUDE.md` (commit `056c948e`). §0.19.1 avait *documenté* l'absence
de tests R4 et la non-couverture de R6 site 1 — or « documenter un manque n'est PAS le traiter ».
Le traitement était techniquement possible (l'instrumentation §0.18 avait été retirée), donc dû.

**Récapitulatif — chiffres relevés par exécution le 2026-07-21, pas de mémoire.**

| Fichier | Tests | Objet | Mutations → verdict |
|---|---|---|---|
| `test_fight_target_selection_no_fallback.py` | **10** | §0.19.2 (3 replis) + sélection sans sentinelle | 5 rouges (replis) ; 2 rouges (`max`→`min`, scoring aplati) |
| `test_charge_oval_base_reverse_bfs.py` | **4** | R6, **les 2 sites**, déterministe + garde d'atteinte | 3 rouges par site (L826 et L3629, mutés isolément) |
| `test_programmatic_owner_predicate.py` | **22** | R4 — le **prédicat** et son refus du repli | 3 rouges (bascule gym, `player_types`, erreur explicite) |
| `test_r4_auto_decider_wiring.py` | **14** | R4 — le **branchement** et sa consommation | 3 rouges (débranchements) + 1 rouge (site `defender_human` isolé) |
| **Total** | **50** | | **17 mutations, 17 rouges** |

**Suite complète après ces travaux : `EXIT=0`, zéro échec, `GARDE=OK`** — empreinte `mtime` de
`engine/ tests/ ai/ config/` identique avant et après le run (`833a2bfc…`), donc aucun écrivain
concurrent : la mesure est valide au sens du piège « verrou global » de §0bis.

⚠️ **Ce qui n'a PAS été mesuré**, à ne pas déduire de ce qui précède : aucun run d'entraînement
n'a été lancé de toute cette passe. Les runs §0.18 restent dus (cf. l'entrée correspondante) —
un crash dépendant de la trajectoire ne se solde pas par une suite verte.

**R6 site 1 — arbitrage utilisateur et ce qui en a été fait.** L'utilisateur a tranché : « x5 est
LA priorité ; si on doit sacrifier x1, on le sacrifie. » **On n'a pas eu à le faire**, et le
signaler faisait partie du travail : l'arbitrage était conditionnel, et la condition n'est pas
remplie. Le chemin x1 est **vif** — [api_server.py:56](../../services/api_server.py#L56) et
`frontend/src/hooks/useGameConfig.ts:228` exposent le board `25x21` au PvP, et
`ArmageddonAgent_training_config.json` porte une phase de curriculum x1. Le supprimer aurait été
une **régression PvP sans aucun gain au x5** : le fix R6 y était déjà correct, seulement invisible
aux tests. Traitement retenu : le **couvrir**.

`tests/unit/engine/test_charge_oval_base_reverse_bfs.py` (+4) — Carnifex `[41,27]`, Psychophage
`[47,36]`, non-régression socle rond `int`, et surtout une **garde d'atteinte**
(`test_reverse_bfs_is_actually_reached`) qui espionne l'appel à
`_charge_reverse_goal_bfs_for_eligibility`. ⚠️ **Sans cette garde le fichier ne vaudrait rien** :
c'est le motif §0.11 (« un test vert ne couvre que les états qu'il atteint »), déjà subi par
`test_move_mask_is_executable.py`. Le test unitaire atteint le site parce que la fixture ne
définit pas `inches_to_subhex` → `.get(..., 1)` vaut 1, ce qui active le BFS inverse.
**Mutation `max(_mover_bs)` → `int(_mover_bs)` : 3 ROUGES** (dont la garde), le socle rond reste
vert.

**R4 — prédicat ET branchement, les six exigences de §8.3 sont couvertes (2026-07-21).**

| Exigence §8.3 pour R4 | État | Où |
|---|---|---|
| Matrice (gym True/False) × (`player_types` human/ai) | ✅ | `test_programmatic_owner_predicate.py` |
| Test négatif `_is_ai_controlled_shooting_unit` | ✅ | idem |
| Allocation **fight** auto en gym, pertes réelles (FIGHT_CTX) | ✅ | `test_t5_bare_loop.py` (préexistant) |
| Allocation **tir** auto en gym | ✅ | `test_r4_auto_decider_wiring.py` |
| Les **4 sites `defender_human`** du flux fight | ✅ | idem — **verrou STRUCTUREL** `test_every_defender_human_site_delegates_to_the_predicate`, pas une déduction depuis le helper |
| **Miroir PvP** : en PvP humain l'allocation reste manuelle | ✅ | idem, un jumeau PvP par cas gym |

🔴 **Pourquoi les tests de prédicat ne suffisaient pas.** Le prédicat était déjà correct AVANT
T1 ; la rupture R4 était son **branchement**. `test_programmatic_owner_predicate.py` ne rougit
pas si l'on débranche `SHOOT_CTX.auto_decider` — d'où
`tests/unit/engine/test_r4_auto_decider_wiring.py` (**+14**, comptés par exécution), qui
vérifie la **chaîne** :

    SHOOT_CTX.auto_decider = _target_defender_is_ai -> is_programmatic_defender -> is_programmatic_owner
    FIGHT_CTX.auto_decider = _fight_auto_defender   -> _is_ai_controlled_fight_unit -> is_programmatic_owner
    les 4 sites `defender_human` (~5523, ~5548, ~6248, ~6282) -> _is_ai_controlled_fight_unit
    consommation : _manual_allocation_step (shared_utils) — DEUX sites d'interrogation

⚠️ **Le second site de consommation avait failli être manqué** : `_manual_allocation_step`
interroge `auto_decider` **deux fois** — une fois pour l'ordre des groupes (~L6416), une fois
pour le **choix de la figurine** qui encaisse (~L6446). Le premier test ne couvrait que l'ordre.
Les deux sont désormais couverts, chacun avec son miroir PvP.

**3 mutations de débranchement, 3 rouges :**

| Mutation | Tests rouges |
|---|---|
| `SHOOT_CTX.auto_decider` → `None` | 5 |
| `FIGHT_CTX.auto_decider` → `None` | 2 |
| `_is_ai_controlled_fight_unit` recâblé sur `player_types` en direct (**la rupture R4 d'origine reproduite**) | 2, dont `defender_human_is_false_in_gym` |

La troisième est la preuve qui manquait : elle rejoue le bug historique et le test le rattrape.

⚠️ **Erreur commise puis corrigée dans la même passe, à retenir.** La première version de ce
fichier testait `_is_ai_controlled_fight_unit` et en **déduisait** que les 4 sites
`defender_human` étaient couverts. C'est **exactement le raisonnement « prédicat correct donc
branchement correct »** que le fichier existe pour interdire, reproduit un cran plus haut :
débrancher un seul des 4 sites laissait la suite **verte**. ➜ Corrigé par
`test_every_defender_human_site_delegates_to_the_predicate`, un **verrou structurel** qui lit la
source, exige que chaque affectation de `defender_human` passe par le prédicat, et qu'il y en ait
**exactement 4** (un 5ᵉ site non gardé fait rougir). Mutation d'un seul site → **ROUGE**.
**Leçon : un test de helper ne couvre jamais ses appelants ; il faut vérifier l'appel.**

⏳ **Faiblesse assumée, non corrigée** : les deux tests de consommation
(`_manual_allocation_step`) reposent sur **8 monkeypatches** de fonctions vives
(`_build_alloc_groups`, `_group_alive`, `_auto_declared_order`, `_declare_order_payload`,
`_finalize_manual_allocation`, `_current_live_group`, `_select_allocation_model`,
`_manual_waiting_payload`). C'est légal (§8.1 n'interdit que le monkeypatch de code **mort**),
mais ils vérifient en partie le **modèle** qu'on se fait de la fonction plutôt que la fonction :
si sa forme change, ils peuvent rester verts pendant que la production casse. Une couverture par
un vrai `game_state` d'allocation serait plus solide — coût non négligeable, à peser si ce
chemin bouge.

`tests/unit/engine/test_programmatic_owner_predicate.py`
(+22) : matrice complète (gym True/False) × (`player_types` human/ai) × (joueur 1/2) ; les trois
erreurs explicites (`player_types` manquant hors gym, joueur inconnu, cible absente de
`units_cache`) ; le court-circuit gym qui précède le `require_key` ;
`is_programmatic_defender` résolvant le propriétaire via `units_cache` ; et le **test négatif**
exigé par le ⚠️ R4 — `_is_ai_controlled_shooting_unit` lit `player_types` et **jamais** le flag
gym, sous peine d'auto-activer les unités du joueur entraîné.

**3 mutations, 3 rouges**, une par branche du contrat :

| Mutation | Effet | Tests rouges |
|---|---|---|
| `if game_state.get("gym_training_mode")` → `if False` | bascule gym neutralisée | 4 (dont `defender_in_gym`) |
| `return player_types[p] == "ai"` → `return True` | branche hors-gym toujours vraie | 4 (dont le miroir PvE) |
| `raise KeyError(...)` → `return False` | erreur explicite → **défaut silencieux** | 1 (`unknown_player_raises`) |

La troisième est la plus importante : elle prouve que le test **interdit le repli**, au lieu de
seulement constater un comportement.

⚠️ **Restauration par `cp`, jamais `git checkout`** — `shared_utils.py` portait alors du travail
non commité d'un autre agent (cf. §0bis). Vérifiée par `git diff --stat` vide.

**Deux dettes révélées par cette passe — ✅ TOUTES DEUX TRAITÉES le 2026-07-21 (règle 7) :**

1. ✅ **Le site R6 n°2 n'était verrouillé QUE par un test à exploration aléatoire.**
   `test_t5_bare_loop.py` déroule des épisodes au hasard : c'était **l'antipattern §0.11**
   reproché au site n°1, qui a déjà piégé `test_move_mask_is_executable.py`. Il tenait par
   chance de trajectoire, pas par construction.
   ➜ **Résolu sans écrire une ligne de plus** : le site n°2 (~L3629) est situé **avant**
   l'embranchement vers le BFS inverse (~L3698), donc tout appel à
   `charge_build_valid_destinations_pool` le traverse — `test_charge_oval_base_reverse_bfs.py`
   le couvrait déjà. **Vérifié par mutation isolée du seul L3629, ce fichier seul (sans
   `test_t5_bare_loop.py`) : 3 ROUGES.** Les deux sites R6 sont donc désormais verrouillés de
   façon **déterministe**.
2. ✅ **Code mort introduit par le fix §0.19.2** : `best_reward = -999999` était une sentinelle
   utile tant que `if not target: continue` pouvait sauter toutes les cibles ; depuis que ce
   `continue` lève, elle est inatteignable.
   ➜ Boucle remplacée par `max(resolved, key=...)`, qui supprime **aussi** le second
   `get_unit_by_id` par cible (la première boucle l'avait déjà résolue). `max` retient le
   **premier** maximum : départage identique au `>` strict, donc sélection **stable**
   (déterminisme §8.1). **+4 tests** dans `test_fight_target_selection_no_fallback.py`
   (argmax réel, stabilité sur deux appels, égalité → premier du pool, un scoring par cible),
   **2 mutations → rouges** (`max`→`min`, scoring aplati à 0).

⚠️ **Piège auto-infligé, à ne pas refaire** : le helper de mutation restaurait par
`git checkout --`, ce qui a **effacé le refactor non commité en cours** — précisément la mise en
garde inscrite en §0bis, commise par son propre auteur. Les 10 tests sont alors repassés au vert
sur le code d'origine, donnant l'illusion d'une mutation validée. **Sauvegarde/restauration par
`cp` obligatoire dès qu'on mute un fichier qu'on est soi-même en train de modifier.**

**Suite complète — première mesure VALIDE de tout ce travail** : `EXIT=0`, zéro échec, avec la
garde de stabilité d'arbre de §0bis (empreinte `mtime` de `engine/ tests/ ai/ config/` identique
avant et après le run → aucun écrivain concurrent). Les trois suites précédentes de la session
avaient toutes été invalidées.

#### 0.19.1 Passe d'audit du 2026-07-20 (soir) — T1→T5 faits, section 9 **sans objet**

**Méthode réellement appliquée.** Pour chaque critère de §6 : retrouver le test, vérifier qu'il
est collecté, puis le **neutraliser par mutation du code de production** et observer le verdict,
puis restaurer. Six mutations menées. **Les cinq fichiers mutés ont été restaurés et vérifiés
par `git diff --stat` vide** : `charge_handlers.py`, `macro_intents.py`, `train.py`,
`game_state.py`, `action_decoder.py`. `shared_utils.py`, `w40k_core.py` et le script de chasse
**n'ont pas été touchés** pendant CETTE passe (ils portaient alors l'instrumentation §0.18) ;
aucun training lancé. ⚠️ **État daté** : depuis, l'instrumentation a été retirée,
`scripts/hunt_intra_squad_superposition.py` a été **supprimé**, et `shared_utils.py` a bien été
muté — proprement, en §0.19.3 (sauvegarde/restauration par `cp`).

**Tableau de verdicts.**

| Tranche | Critère §6 | Test qui le verrouille | Mutation appliquée | Verdict | Statut |
|---|---|---|---|---|---|
| **T1 / R6 site 1** | socle ovale en **éligibilité** de charge | ~~aucun~~ → `test_charge_oval_base_reverse_bfs.py` (§0.19.3) | `charge_handlers.py:826` → `int(_mover_bs)` | ~~VERT~~ → **ROUGE (3 tests)** | ~~⏳~~ **✅** |
| **T1 / R6 site 2** | socle ovale, **pool de destinations** | `test_charge_oval_base_reverse_bfs.py` (déterministe, §0.19.3) + `test_t5_bare_loop.py` | `charge_handlers.py:3629` → `int(_mover_bs)` | **ROUGE** (`TypeError`) | ✅ |
| **T1 / R4** *(prédicat)* | prédicat programmatique unique | ~~AUCUN~~ → `test_programmatic_owner_predicate.py` (§0.19.3) | 3 mutations : bascule gym, branche `player_types`, erreur explicite | **ROUGE (3/3)** | ✅ |
| **T1 / R4** *(branchement)* | `auto_decider` tir + 4 sites `defender_human` + miroir PvP | `test_r4_auto_decider_wiring.py` (§0.19.3) | 3 débranchements : `SHOOT_CTX`, `FIGHT_CTX`, prédicat recâblé | **ROUGE (3/3)** | ✅ |
| **T2** | zéro littéral d'action dans `ai/` | `test_action_space_mirror.py` | `macro_intents.ACTION_CHARGE` 1030→1029 | **ROUGE** (2 tests) | ✅ |
| **T3** | board refs + `--training-config` obligatoire | `test_train_board_refs.py` | reconstruction `{cols}x{rows}` **et** garde R1 neutralisée | **ROUGE** (3 tests) | ✅ |
| **T4** | resolver `board_ref` | `test_board_ref_resolver.py` | garde « board dir inexistant » neutralisée | **ROUGE** | ✅ |
| **T5** | parité masque ↔ commit de déploiement | `test_deployment_clearance_parity.py::test_deployment_mask_mirrors_commit_overlap_predicate` | `_deployment_clearance_filter` → `return candidates` | **ROUGE**, symptôme d'origine | ✅ |

> ✅ **Les deux démentis ci-dessous sont RÉSOLUS depuis le 2026-07-21 — voir §0.19.3.** Le
> constat historique est conservé tel quel : c'est lui qui documente le trou et la méthode qui
> l'a trouvé.

**Les deux démentis de fond.**

1. 🔴 **T1 / R6 site 1 est du CODE MORT à la résolution du training — septième occurrence du
   motif §0.4.** `_charge_reverse_goal_bfs_for_eligibility` est gardé par
   `int(game_state.get("inches_to_subhex", 1)) <= 1`
   ([charge_handlers.py:3698](../../engine/phase_handlers/charge_handlers.py#L3698)). Le training
   tourne en **x5**, donc ce site n'est **jamais atteint**. Preuve : `int()` sur une liste lève
   `TypeError` de façon inconditionnelle, et la suite reste **verte** sous cette mutation. Le fix
   R6 y est correct mais **non exercé et non verrouillé** ; seul le site 2 l'est. Conséquence
   pratique : nulle aujourd'hui (x5/x10 passent par le BFS avant) — mais toute réactivation du
   chemin x1, ou tout run à `inches_to_subhex = 1`, s'appuierait sur du code qu'aucun test ne
   garde.

2. 🔴 **T1 / R4 n'a aucun test.** `grep -rln "is_programmatic_owner\|is_programmatic_defender"
   tests/` retourne **vide**, alors que §8.3 impose explicitement une matrice
   (gym × `player_types`), l'allocation tir **et** fight en gym, les 4 sites `defender_human`, le
   **miroir PvP** et le test négatif sur `_is_ai_controlled_shooting_unit`. Le code est présent et
   conforme à sa description ([shared_utils.py:97-124](../../engine/phase_handlers/shared_utils.py#L97-L124),
   lu). La seule couverture est **indirecte** : `test_bare_loop_melee_losses_via_fight_ctx`
   exerce la branche gym=True. **Rien** ne couvre la branche PvP ni la non-régression du miroir.
   ⚠️ **Mutation impossible dans cette session** : `shared_utils.py` porte l'instrumentation
   §0.18. **Ce ⏳ repose sur une absence de test constatée, pas sur un mutation-test** — à
   confirmer par mutation quand l'instrumentation sera retirée.

**Ce que l'audit n'a PAS trouvé.** T2, T3, T4, T5 sont verrouillés par des tests qui rougissent
sur mutation. Aucun « test qui passe pour la mauvaise raison » sur ces quatre tranches.

**Section 9 : la prémisse de §0.19 était FAUSSE.** L'énoncé ci-dessus affirme que « toute la
section 9 est marquée ✅ FAIT ». Vérification : les lignes de la section 9 ne contiennent
**aucun** marqueur `✅`, `FAIT` ni `⏳`. C'est une section de **plan** (P1→P5), **non
implémentée** — il n'y a donc aucun ✅ à démentir. Ses affirmations de *diagnostic* ont
néanmoins été revérifiées **par lecture** (pas par grep seul) et **tiennent toutes** :
`_attack_sequence_rng` sans appelant vif (seuls des tests l'importent) ; `apply_rules` /
`_apply_single_rule` toujours `return context` pass-through
([rules.py:279-327](../../engine/weapons/rules.py#L279-L327)) ; `_cover_worsened_bs` ne lit
toujours pas `IGNORES_COVER` ([shared_utils.py:5980-6005](../../engine/phase_handlers/shared_utils.py#L5980-L6005)) ;
`_ai_select_shooting_target` de `shooting_handlers` toujours sans appelant (l'homonyme de
`pve_controller` est, lui, vif — ne pas les confondre) ; `reroll_charge` toujours dans
`config/unit_rules.json` et nulle part dans le code ; `_select_ai_rule_choice_option` toujours en
`raw_action_int % len(options)` en gym ([w40k_core.py:2471](../../engine/w40k_core.py#L2471)) ;
le `except Exception: … return valid_targets[0]` de `_ai_select_fight_target` toujours présent.
**Seules les références de ligne ont dérivé** (~+200 à +350 lignes) — signalées, non corrigées.

**Trois affirmations périmées repérées, SIGNALÉES et NON corrigées** (elles rejoignent le
tableau de §0bis) :

| # | Où | Affirmation | Pourquoi elle est périmée |
|---|---|---|---|
| 11 | §6, critère **T2**, et §8.2 | « `action_space.n == 41` », « `ACTION_WAIT` (18) », « `6+6+6+1+5+1+1+15 == 41` », « 19→shoot slot 0, 24→charge » | Le layout réel est **1047** actions : `ACTION_WAIT = 1024`, `SHOOT_SLOT_BASE = 1025`, `ACTION_CHARGE = 1030`, `ACTION_FIGHT = 1031` ([macro_intents.py:20-38](../../engine/macro_intents.py#L20-L38)). Changé par la refonte spatiale du move. Le critère T2 **réel** (zéro littéral d'action dans `ai/`) reste, lui, satisfait. |
| 12 | §6, critère **T4** | « Les **61 scénarios** se chargent (script de balayage) » | La banque `ArmageddonAgent` compte **5** scénarios et `test_bank_has_expected_count` l'assert explicitement ; la banque `CoreAgent` en compte **4**. De plus `scripts/sweep_scenario_bank_v11.py:24` pointe encore `config/agents/CoreAgent/scenarios` : **le balayage du critère n'est plus exécutable tel quel**. La migration T4 a bien eu lieu ; c'est le critère qui n'a pas suivi. |
| 13 | §8.2 | « Fichier proposé : `tests/unit/engine/test_agent_interface_contract.py` … C'est LE verrou anti-récidive de R5 » | Ce fichier **n'existe pas**. Le verrou existe sous un autre nom et une autre forme — `test_action_space_mirror.py` — et il est **meilleur** : il vérifie `macro_intents` ≡ `shared_utils` constante par constante, et le décodeur **importe** ces mêmes constantes ([action_decoder.py:25-32](../../engine/action_decoder.py#L25-L32)), donc la désynchronisation visée par §8.2 est structurellement impossible. |

**Réserve sur le critère T5, indépendante du mutation-test.** §6 exige « 10 épisodes aléatoires
masqués terminés sur **≥3 scénarios × sièges p1/p2** ». `test_t5_bare_loop.py` exerce **un**
scénario fixe × 3 seeds et **aucun siège** (`grep agent_seat_mode tests/` ne retourne que des
fichiers `tests/unit/ai/`). T5 le dit d'ailleurs lui-même dans son « Reste » : le siège
`p2`/`random` crashait encore au reset. **Le ✅ de T5 couvre un périmètre strictement plus étroit
que son critère** — il vaut pour le moteur nu, siège p1, comme la tranche l'annonce en tête.

**Réserves de méthode sur cette passe elle-même** (à ne pas répéter) :
- Une première suite complète avait été lancée **en parallèle des mutations** : contaminée par
  construction, elle a été **tuée et non exploitée**. Ne jamais mesurer une baseline pendant
  qu'on mute.
- Deux premières tentatives de mutation-test sur T5 ont été **tuées par leur propre `timeout`**
  sans verdict, et un `pkill` trop large a tué sa propre commande. Un non-aboutissement n'est
  **pas** un rouge : le verdict n'a été obtenu qu'en isolant le test d'assertion pure
  (**42 s vert** / **6,7 s rouge**) au lieu du fichier entier, dont l'autre test déroule des
  épisodes. Sur une machine chargée (load ~15, 10 process de chasse), **chronométrer le
  contrôle propre AVANT de conclure d'une lenteur sous mutation**.
- `tests/unit/engine/test_pile_in_intra_squad_collision.py` est apparu dans `git status` pendant
  la session : il vient des process §0.18, **pas de cet audit**.

**⚠️ La première suite de fin de passe est sortie en `EXIT=1` — mesure INVALIDE, ne pas la citer.**
Elle montrait un échec de
`test_pile_in_intra_squad_collision.py::test_stationary_b2b_figurine_cell_is_not_stolen`. Cause
identifiée par les **mtimes** : la **chasse §0.18** écrivait `shared_utils.py` (20:14:31) et son
propre test (20:13:58) **pendant** que cette suite tournait (~20:05→20:45). **Deuxième baseline
contaminée de la session**, après celle des mutations — même erreur, autre écrivain. ⚠️ **Ne
jamais mesurer une suite pendant qu'un autre process écrit dans `engine/`**, y compris un process
qu'on n'a pas lancé soi-même.

⚠️ **Aucune suite complète de cette session ne constitue une mesure de référence.** Trois runs
ont été invalidés par un écrivain concurrent (détail et règle : piège « verrou global » en §0bis).
Le dernier, `EXIT=0`, a tourné de 21:17:37 à 21:22:54 alors que `shared_utils.py` était écrit à
**21:20:33** par l'agent concurrent — **non exploitable, malgré son vert**. La mesure de référence
est celle produite par l'agent concurrent **après gel des écritures**, à reprendre ici quand elle
tombe.

**Ce qui EST mesuré de façon fiable**, parce que cela ne dépend que de fichiers qu'aucun autre
agent ne touche : les mutation-tests par tranche du tableau ci-dessus, et la contre-épreuve de
§0.19.2 sur `fight_handlers.py`. Le test de pile-in passe **3 fois sur 3** en isolé.

## 1. Objectif

Rétablir un entraînement fonctionnel de `CoreAgent` (`python3 ai/train.py --agent CoreAgent
--scenario bot ...`) sur le moteur actuel (board 44x60x5, niveaux, per-model, fight V11,
allocation des pertes par-figurine), en trois phases :

- **Phase A (obligatoire)** : remise en route — le pipeline tourne de bout en bout sans erreur,
  à interface agent constante (action 41 / obs 108).
- **Phase A' (obligatoire, décision utilisateur 2026-07-14)** : entraîner l'agent sur TOUTES les
  règles implémentées — (P1) porter dans le chemin vif les règles restées dans le code mort puis
  supprimer le code mort, (P2-P3) donner à l'agent chaque décision que les règles laissent au
  joueur (mécanisme générique de décision), (P4-P5) observation de support + validation par
  tranche. Périmètre strict : règles DÉJÀ implémentées — aucune feature absente du moteur.
  Détail en section 9.
- **Phase B (obligatoire)** : mise à niveau de l'observation — l'agent perçoit les niveaux
  (élévation) et les coûts associés.
- **Phase C (optionnelle, hors scope initial)** : nouveaux points de décision au-delà de la
  Phase A' (ex. montée d'étage). À ne PAS entamer sans validation utilisateur.

**Interdits absolus** (CLAUDE.md) : aucun fallback/workaround/valeur par défaut pour masquer une
erreur ; ne jamais modifier `config/users.db` ni `ai/models/**/*.zip` ; les règles de jeu se
vérifient dans `Documentation/40k_rules/` avant toute décision règles.

## 1bis. L'ANCRE — concept central, source commune des ruptures V11

> Rédigé le 2026-07-20 après que le plan T7 se soit révélé faux faute d'avoir ce concept écrit
> quelque part. **À lire avant de toucher à toute validation de position.**

### Définition

Une unité 40K est un **ensemble de figurines**, chacune sur son propre hex. Mais l'agent doit
produire une **action discrète** (« déploie l'unité 3 ici ») : il ne peut pas émettre N
coordonnées. L'**ancre** est le point unique qui représente l'unité entière dans les interfaces
qui ne savent manipuler qu'UNE position — l'espace d'action, et le code moteur legacy écrit
quand une unité *était* une seule figurine.

Deux structures parallèles coexistent, et tout se joue là :

| Structure | Contenu | Statut |
|---|---|---|
| `models_cache` | position de **chaque figurine** (`col`, `row`, `level`) | la **vérité** |
| `units_cache` | **une** position par unité | l'ancre, un **résumé** |

L'ancre **n'est pas un objet physique**. C'est la position de la **figurine vivante d'index
minimal** ([shared_utils.py:3061](../../engine/phase_handlers/shared_utils.py#L3061) :
« n'update `units_cache` que si la figurine est l'ancre courante (index minimum vivant) »).
Ce n'est ni le centre, ni le barycentre de l'unité : un simple délégué désigné par convention.
**Corollaire à ne pas oublier : quand la figurine d'index minimal meurt, l'ancre SAUTE** sur la
suivante — la position « de l'unité » change sans qu'aucune figurine n'ait bougé.

### Trois usages, de natures différentes

1. **Désigner** — l'agent choisit un hex : c'est l'ancre visée. ✅ légitime.
2. **Translater** — `build_rigid_plan` calcule un delta entre ancre de départ et ancre
   d'arrivée, puis l'applique à TOUTES les figurines. ✅ légitime *si* le delta est réellement
   rigide (ce qui était faux avant T6-h, cf. parité de `dx`).
3. **Résumer pour valider** — les fonctions legacy (`compute_candidate_footprint(col, row,
   unit, …)`) prennent l'ancre + le `BASE_SIZE` de l'**unité** et testent *un socle* à cet
   endroit. 🔴 **C'est un mensonge** : elles testent un objet qui n'existe pas.

### Le motif de bug unique

**Quelque chose est VALIDÉ sur l'ancre, puis EXÉCUTÉ sur les figurines** — et les deux divergent.
D'où le message récurrent `incohérence masque/exécution`. Toutes les ruptures traitées en V11
sont des variantes du même mensonge :

| Tranche | Variante |
|---|---|
| **T6-f** | le commit n'écrivait QUE l'ancre → figurines restées à `(-1,-1)` |
| **T6-g** | le pool BFS validait l'ancre → le bloc translaté débordait |
| **T6-h** | la translation « rigide » déformait le bloc selon la parité de `dx` |
| **§0.11** | la collision intra-plan ignorait le **niveau**, autre attribut d'identité écrasé par le résumé |
| **T7** | le contrôle mono-ancre de `deploy_unit` teste ce socle fantôme |

### ⚠️ Le piège : « ancre » désigne TROIS contrats différents

Le mot est le même partout, le contrat non — et c'est précisément ce qui a fait écrire un plan
T7 faux :

| Chemin | Ce que « ancre » veut dire |
|---|---|
| `units_cache` | position de la figurine d'index minimal (dérivée, elle SAUTE aux pertes) |
| action de l'agent | point de **désignation** (contraignant : ce qui est désigné doit être exécuté) |
| **déploiement** | **simple suggestion** : `generate_compact_formation` part de l'ancre en spirale BFS et retient la 1ʳᵉ case légale — l'ancre **oriente**, elle ne **contraint pas**. Une ancre hors zone place l'unité 22 colonnes plus loin au lieu d'échouer (mesuré, cf. T7). |

**Avant d'écrire ou de supprimer une validation de position, déterminer LEQUEL des trois contrats
s'applique sur ce chemin.** Ne jamais supposer que « le contrôle par-figurine valide déjà
l'ancre » : au déploiement, c'est faux.

### Dette d'ancre restante — recensement du 2026-07-20

> Balayage de `engine/` + `ai/`. Les sites marqués ✅ *vérifié* ont été relus directement ; les
> autres viennent du balayage et **restent à confirmer par lecture avant toute action**.
>
> 🔴 **Statut de fiabilité de ce recensement — à lire avant de s'en servir.** Il est issu d'un
> balayage automatique dont **seuls 4 sites ont été relus à la main** (le pool de move, les 2
> sites objectif, la ventilation LoS). Le reste est un **faisceau d'indices, pas un audit**.
> Un premier essai d'exploitation a déjà produit une conclusion fausse : « la charge n'a pas
> d'équivalent de l'érosion T6-g » a été écrit ici sur la seule absence de fonction `erode_*`,
> alors qu'une machinerie per-model existe ailleurs dans le même fichier (cf. la ligne charge
> ci-dessous). **Ne pas ouvrir de chantier depuis une ligne non marquée ✅ sans avoir lu la
> fonction.** C'est la même erreur de méthode que §0.11 (« vérifié un par un » sur un
> échantillon n'est pas une vérification) et que le plan T7 (conclusion tirée sans lire les
> deux avertissements présents dans le code).

**Le levier unique** : `compute_candidate_footprint(col, row, unit, game_state)`
([shared_utils.py:416](../../engine/phase_handlers/shared_utils.py#L416)) ne calcule **qu'UNE
base** (le `BASE_SHAPE`/`BASE_SIZE` de l'unité) centrée sur `(col,row)`. Passée une unité
multi-figurines, elle rend l'empreinte d'**une figurine à l'ancre**, jamais celle de l'escouade.
C'est la source commune des gravités 1-2 ci-dessous.

**G1 — pool/masque construit à l'ancre, commit exécuté par figurine**

| Site | Décision prise sur l'ancre |
|---|---|
| `movement_build_valid_destinations_pool` (movement:2266, 2870) | ✅ *vérifié* : le pool ne valide QUE l'ancre — [shared_utils.py:7668](../../engine/phase_handlers/shared_utils.py#L7668) l'écrit. ⚠️ **Le chemin du MASQUE GYM est couvert** : `erode_move_pool_by_squad_block` (T6-g) est appliquée juste après, en [:7671](../../engine/phase_handlers/shared_utils.py#L7671). **Les autres consommateurs n'érodent PAS** — `pve_controller.py:468`, `movement_handlers.py:813/846`, `shooting_handlers.py:5128`, `action_decoder.py:720`, `w40k_core.py:2682`. À auditer : le PvP tombe-t-il dans le même mismatch, ou son preview le rattrape-t-il ? |
| `charge_build_valid_destinations_pool` ([charge:3472](../../engine/phase_handlers/charge_handlers.py#L3472), 166) | Portée de charge 2d6 + légalité d'arrivée mesurées depuis l'ancre, empreinte mono-base ; commit per-model. **Le code admet la dette** : charge_handlers.py:267. ⚠️ **STATUT NON ÉTABLI — ne pas partir de cette ligne pour ouvrir un chantier.** Il n'existe aucune fonction `erode_*` dans `charge_handlers.py`, MAIS la charge possède une machinerie **par figurine** ailleurs : [`_compute_plan_context`](../../engine/phase_handlers/charge_handlers.py#L1955) calcule un champ de portée per-model (`_euclidean_reach(m, sib, …)`, avec le `BASE_SHAPE`/`BASE_SIZE` **de chaque figurine**). **Question ouverte, à trancher par lecture de `charge_build_valid_destinations_pool` :** ce contexte per-model réconcilie-t-il le pool d'ancre, ou les deux coexistent-ils sans se parler ? Tant que ce n'est pas lu, « la charge a le même trou que le move » est une **hypothèse, pas un constat**. |
| `charge_target_selection_handler` (charge:4360) | `charge_reference_hex` = ancre → décide quelles cibles sont engagées. |

**G2 — éligibilité de phase décidée sur l'ancre**

| Site | Décision |
|---|---|
| `get_eligible_units` (movement:544, 573, 599) | « L'unité peut-elle bouger ? » = existe-t-il un voisin de **l'ancre** où une base tient. Une escouade dont l'ancre est bloquée mais dont d'autres figurines peuvent bouger est déclarée inéligible — et l'inverse. |
| pile-in / consolidation (fight:545, 726, 893, 1116, 1203, 1372, 1731) | BFS et distances mesurés sur une base à l'ancre, alors que le pile-in 12.03 et la consolidation 12.08 sont **par figurine** (cf. `project_pile_in_par_figurine`). |
| `action_decoder.py:1218` | Case décodée validée sur une empreinte mono-base avant exécution per-model. |

**G3 — règles satellites d'objectif sur position unique** (✅ *les deux vérifiés*)

| Site | Décision |
|---|---|
| [shooting_handlers.py:6127](../../engine/phase_handlers/shooting_handlers.py#L6127) | Règle `reroll_towound_target_on_objective` : « la cible est-elle sur un objectif ? » testée sur `target["col"]/["row"]` = **l'ancre**. Une escouade dont seule une figurine non-ancre tient l'objectif est ratée. ⚠️ Utilise en plus `target.get("col", -1)` — **valeur par défaut masquant une absence**, interdite par CLAUDE.md. |
| [fight_handlers.py:165](../../engine/phase_handlers/fight_handlers.py#L165) `_is_unit_on_objective` | Même bug côté mêlée (`require_unit_position` = ancre). |

✅ **Le vrai Objective Control est SAIN** : `_sum_objective_control_oc`
([game_state.py:1863](../../engine/game_state.py#L1863)) compte bien OC × figurines dans la zone
(14.02). Ce sont les règles *satellites* qui n'ont pas suivi.

**G4 — heuristiques IA à l'ancre** (aucun impact règles, biais de politique seulement) :
`_select_strategic_destination` (movement:3923+, charge:4169), `observation_builder.py:1043/2332`
(« Anchor-based distance (approx, sufficient for RL obs) »), `analyzer.py:603`. Assumé et
auto-documenté, sauf charge:4169 qui n'a **pas** de justification écrite.

**Ce qui est SAIN et ne doit pas être touché** : la **LoS** est entièrement par-figurine
(`_compute_unit_los_uncached`, `_unit_can_see_any`, couvert 13.08 — itèrent sur `models_cache`) ;
les **portées de tir/mêlée** passent par `occupied_hexes` (union per-model) avec l'ancre en simple
repli ; `units_cache[sid]["occupied_hexes"]` **est** l'union par-figurine
([shared_utils.py:2897](../../engine/phase_handlers/shared_utils.py#L2897)) ; les logs et la sync
d'ancre post-commit sont des résumés légitimes.

⚠️ **Indice de méthode** : [shared_utils.py:2902](../../engine/phase_handlers/shared_utils.py#L2902)
porte le commentaire « Fix F2 (audit) : `occupied_hexes` doit couvrir TOUTES les figs, pas
seulement le footprint de l'ancre ». La correction analogue a donc **déjà** été faite à cet
endroit, et **pas** aux sites G1-G2. Le motif se répare site par site depuis des années.

## 2. État des lieux vérifié (ce qui marche)

⚠️ **Affirmation périmée n°7 — voir la table de §0bis** : `ai.multi_agent_trainer` n'existe plus (supprimé en §0.8). Ligne conservée telle quelle, non corrigée.

- Tous les imports du pipeline passent (`ai.train`, `ai.env_wrappers`, `ai.multi_agent_trainer`,
  `ai.reward_mapper`, `ai.scenario_manager`, `ai.unit_registry`, ... — vérifié par exécution).
- L'environnement gym EST le moteur : `W40KEngine(gym.Env)` ([w40k_core.py:147](../../engine/w40k_core.py#L147)),
  `reset()` L918, `step(action: int)` L1330. Espace d'action `Discrete(41)` (L629), observation
  `Box(108,)` (L660), les deux lus depuis `observation_params` de
  [CoreAgent_training_config.json](../../config/agents/CoreAgent/CoreAgent_training_config.json) (obs_size 108, action_space_size 41), sans défaut.
- Espace d'action squad actuel — source unique [macro_intents.py:8-20](../../engine/macro_intents.py#L8-L20) :
  - 0-5 move normal (6 directions), 6-11 advance (6 dir), 12-17 fall back (6 dir),
  - 18 wait/end activation, 19-23 shoot slots 0-4, 24 charge, 25 fight,
  - 26-40 zone intents (5 objectifs × 3 intents). Total 41.
- Masque : `ActionDecoder.get_squad_action_mask_and_eligible_units`
  ([action_decoder.py:146](../../engine/action_decoder.py#L146)) ; exposé par `W40KEngine.get_action_mask()` (L5563), branché
  MaskablePPO via `ActionMasker` ([train.py:1448-1451](../../ai/train.py#L1448-L1451)).
- Observation squad 108 : `build_squad_observation` ([observation_builder.py:1253](../../engine/observation_builder.py#L1253)) —
  16 global + 5 agrégats squad + 6 figurines × 7 features + 5 slots ennemis × 9 features.
  Layout **purement 2D** (col/row) : aucune feature de niveau/élévation.
- Rewards : `RewardCalculator` ([reward_calculator.py:23](../../engine/reward_calculator.py#L23)) piloté par
  `CoreAgent_rewards_config.json` (squad_shaping, base_actions, situational_modifiers,
  zone_intent_shaping) — pas de valeurs par défaut, à une nuance près :
  `situational_modifiers` est optionnel dans une branche (~L782). OK à interface constante.
- Le moteur distingue déjà training et PvP : `gym_training_mode` (auto-résolution des prompts,
  `_is_player_human` renvoie False — [w40k_core.py:2201-2206](../../engine/w40k_core.py#L2201-L2206)) et `pve_mode` (adversaire géré
  par wrapper externe en training, `pve_mode=False`, [w40k_core.py:226-229](../../engine/w40k_core.py#L226-L229)).
- Wrappers : `BotControlledEnv` (scénarios "bot", GreedyBot, [train.py:1749-1791](../../ai/train.py#L1749-L1791)) et
  `SelfPlayWrapper` (self-play, modèle gelé) dans [env_wrappers.py](../../ai/env_wrappers.py).
- Un smoke test moteur nu (actions aléatoires masquées, scénario board actuel) déroule
  deployment/command/move/shoot/charge/fight jusqu'au tour 5 une fois les ruptures R4/R6
  contournées — le cœur par-figurine (fight V11 auto, footprints, descente §13.06) fonctionne
  en gym.

**Contexte de divergence (git)** : dernier commit sur `ai/env_wrappers.py` = 2026-05-30, sur
`ai/train.py` = 2026-05-31. Toutes les features suivantes sont postérieures : charge rework
(06-01), fight V11 (06-12→07), LoS unifiée (07-02), niveaux + coût descente §13.06 (07-09),
perModelMove (07-10), replay/snapshots (07). Le pipeline RL est resté sur le modèle de fin mai.

## 3. Ruptures vérifiées (avec reproduction)

### R1 — Phase de training `default` absente
**Repro** : `python3 ai/train.py --agent CoreAgent --scenario bot --step` →
`KeyError: "Phase 'default' not found in CoreAgent_training_config.json. Available:
['x1','x5_append','x5_new','x1_debug','x5_debug']"` (config_loader.py:274).
`--training-config` a pour défaut `"default"` ([train.py:4232](../../ai/train.py#L4232)).

### R2 — train.py reconstruit le chemin board depuis {cols}x{rows}
**Repro** : `python3 ai/train.py --agent CoreAgent --scenario bot --step --training-config x1_debug`
→ `FileNotFoundError: Board walls directory not found: config/board/220x300/walls`.
Cause : `_list_available_board_refs` ([train.py:586-591](../../ai/train.py#L586-L591)) construit
`config/board/{cols}x{rows}/` (= 220x300, dimensions subhex) alors que le dossier réel est
`config/board/44x60x5/` (44x60 pouces, scale 5). La source de vérité existe déjà :
`config_loader.get_board_dir()` ([config_loader.py:79-87](../../config_loader.py#L79-L87), gère `W40K_BOARD_PATH` + `paths.board`).
**Auditer toute reconstruction `f"{cols}x{rows}"` dans ai/ et engine/** (même motif ailleurs, cf. R3-d).

### R3 — Banque de scénarios d'entraînement incompatible avec le contrat scénario actuel
La banque vit dans `config/agents/CoreAgent/scenarios/` — **61 JSONs** : training/ 30 +
training/training_benchmark/ 4, holdout_regular/ 10, holdout_hard/ 10 + holdout_hard/matchups/ 7
(dans des sous-sous-dossiers `matchups/run_*/` ; attention : ne pas compter les dossiers comme
des fichiers) + rosters
`config/agents/_p2_rosters/`. Il existe aussi `scenarios/training_save/` (30 JSONs de plus) —
statuer en T4 : migrer ou archiver. Le contrat moteur a changé
(commit `540d0674` "terrain OK") — cinq incompatibilités indépendantes, toutes vérifiées par
exécution ou lecture :

- **(a) Localisation obligatoire** : `_resolve_shared_config_path` exige que le scénario soit dans
  un dossier nommé exactement `scenario/` sous un board ([game_state.py:1646-1651](../../engine/game_state.py#L1646-L1651)) ; idem pour
  `wall_ref: "random"` ([game_state.py:1437-1441](../../engine/game_state.py#L1437-L1441)) et `terrain_ref` (L1496-1505).
  **Repro** : charger `holdout_hard/scenario_bot-01.json` → `ValueError: must be located in a
  'config/board/<board>/scenario/' directory`.
- **(b) Objectifs** : les clés `objectives`, `objectives_ref`, `objective_hexes` sont SUPPRIMÉES et
  lèvent une erreur explicite ([game_state.py:320-329](../../engine/game_state.py#L320-L329)). Source unique désormais : terrains
  flaggés `"objective": true` dans le `terrain_ref` (règles 14.01/14.02). **Tous** les scénarios
  de la banque utilisent `objectives_ref` → tous invalides.
- **(c) Refs de walls périmées** : `config/board/44x60x5/walls/` ne contient que `walls-33`,
  `walls-mc1`, `walls-none`. 28 scénarios de la banque référencent `walls-11` (inexistant) —
  27 avec extension `.json`, 1 sans (format à normaliser au passage) ; les 33 autres utilisent
  `"random"`.
- **(d) Zones de déploiement** : voie moderne = section `deployment_zones` du terrain_ref
  (polygones par joueur, [game_state.py:400-432](../../engine/game_state.py#L400-L432)) ; voie legacy = fichier nommé
  `config/deployment/{cols}x{rows}/<zone>.json` (L436-440), or `config/deployment/220x300/` ne
  contient que `mc1.json` — le `deployment_zone: "hammer"` de toute la banque est introuvable.
- **(e) Niveaux** : les scénarios d'entraînement n'ont pas de `terrain_ref`, donc aucun étage —
  l'agent ne s'entraînerait jamais sur la feature niveaux même une fois le reste réparé.
- **(f) La training config ELLE-MÊME est cassée** (raté des deux premiers audits) : dans les
  5 phases de `CoreAgent_training_config.json`, `scenario_sampling.train_wall_ref_weights` =
  `walls-11/21/31.json` (0.3 chacun, inexistants) et `eval_objectives_refs` =
  `objectives-51.json` (le dossier `objectives/` n'existe plus). Après le fix R2,
  `_expand_random_ref_weights` lèvera « unknown refs for board walls » ([train.py:623-628](../../ai/train.py#L623-L628)).
- **(g) Chemin d'éval holdout cassé dans `ai/bot_evaluation.py`** :
  `_materialize_eval_scenario_refs` ÉMET `objectives_ref` (L75, clé rejetée par le moteur) et
  les `eval_wall_refs`/`eval_objectives_refs` pointent les mêmes fichiers inexistants.
  Consommé par les callbacks d'éval de train.py (~L3231/3340), l'éval finale (~4185) —
  cassera même après T3/T4 si seul train.py est migré.

### R4 — Allocation des pertes : gym non reconnu comme "défenseur IA" (BLOQUANT runtime)
**Repro** (moteur nu, gym_training_mode=True, scénario board valide) : première action
`squad_shoot` → `RuntimeError: squad_shoot: allocation tir non terminee en auto pour squad 1001
(defenseur non-IA ?)` ([w40k_core.py:4938-4943](../../engine/w40k_core.py#L4938-L4943)).
Cause : le moteur d'allocation mutualisé tir/fight décide humain-vs-auto via des prédicats qui
lisent UNIQUEMENT `game_state["player_types"]` ; en training self-play `pve_mode=False` →
`player_types = {"1":"human","2":"human"}` ([w40k_core.py:454-456](../../engine/w40k_core.py#L454-L456)) → l'allocation attend un
humain. Il y a en réalité **QUATRE prédicats divergents** :
- `W40KEngine._is_player_human` — consciente de `gym_training_mode` (L2201-2206) ;
- `_target_defender_is_ai` ([shared_utils.py:89-101](../../engine/phase_handlers/shared_utils.py#L89-L101)) — player_types only, `auto_decider` de SHOOT_CTX ;
- `_is_ai_controlled_fight_unit` (fight_handlers, def ~L97) — player_types only ; utilisée par
  `_fight_auto_defender` (def ~L5705) → `auto_decider` de **FIGHT_CTX** (~L5715-5728) et par
  les 4 décisions `defender_human` du flux fight (~L5425, L5450, L6150, L6184) ;
- `_is_ai_controlled_shooting_unit` (shooting_handlers, def ~L2144) — player_types only, pilote
  l'auto-activation `active_shooting_unit` (cf. ⚠️ ci-dessous : ne PAS la rendre vraie en gym).
**La mêlée crashe de la même façon que le tir** (vérifié par lecture) : `squad_fight` →
`build_manual_fight_allocation` non `done` → `RuntimeError "squad_fight: allocation combat non
terminee en auto"` ([w40k_core.py:5026-5031](../../engine/w40k_core.py#L5026-L5031)), garde jumelle dans fight_handlers
(~L3352-3357). Le gate `is_gym_training` de la consolidation (~L1552) ne couvre PAS
l'allocation.
**Fix vérifié par simulation côté tir uniquement** (monkeypatch : `_target_defender_is_ai`
renvoie True si `game_state["gym_training_mode"]`) : le tir s'auto-résout ensuite correctement.
⚠️ Le smoke test « moteur nu jusqu'au tour 5 » ne prouve PAS le chemin d'allocation fight :
seule `_target_defender_is_ai` était patchée — la seule explication cohérente est qu'aucune
blessure de mêlée n'a été réussie pendant le smoke. À couvrir explicitement en T1 (scénario de
smoke avec pertes en mêlée garanties).
⚠️ Ne PAS "fixer" en mettant `player_types` à `"ai"` : cela active l'auto-activation tir
(`active_shooting_unit`, [shooting_handlers.py:1082-1086](../../engine/phase_handlers/shooting_handlers.py#L1082-L1086)) qui reste alors périmé après
l'activation et fait exploser le décodeur (`active_shooting_unit X is not in
shoot_activation_pool`, [action_decoder.py:418-423](../../engine/action_decoder.py#L418-L423)) — vérifié par exécution.

### R5 — Wrappers et bots sur l'ANCIEN layout d'actions (BLOQUANT runtime)
**Repro** (pile complète `BotControlledEnv(ActionMasker(W40KEngine))` + GreedyBot) :
`env_wrappers.py:436` force `self.env.step(11)` comme "WAIT" → dans l'espace actuel 11 =
**advance direction 5** → `ValueError: convert_squad_action: advance_roll manquant`
([action_decoder.py:885](../../engine/action_decoder.py#L885)).
- `ai/evaluation_bots.py:36` : `WAIT_ACTION = 11` (actuel : **18**) ; usages de `12` comme action
  spéciale (actuel : fall back dir 0) ; slots de tir supposés 4-8 (actuel : **19-23**) ;
  `DEPLOYMENT_ACTIONS = [4..8]` réutilisé comme slots de TIR (L86) ; moves supposés 0-3
  (`0 in valid_actions` L135, `[0, 1, 2, 3, WAIT_ACTION]` L179) au lieu de 0-5.
- `ai/env_wrappers.py` : littéraux `11` périmés en L436 (`step(11)`), L796 (`action == 11`),
  L900 (`bot_action == 11`) ; plages shoot 4-8 codées en dur L793, L871, L898. Le fichier
  **mélange déjà les deux espaces** : les branches "Pool empty -> advance phase via WAIT"
  retournent, elles, `18` (valeur correcte) — L556, L854 (BotControlledEnv) et L1172, L1188
  (SelfPlayWrapper). C'est la preuve d'une migration partielle, pas un layout cohérent.
- `ai/game_replay_logger.py:774-828` (raté des deux premiers audits) : layout encore PLUS
  ancien à 8 actions (`action % 8`, moves 0-3, shoot=4, charge=5, wait=6, fight=7) — les
  replays de training décoderaient n'importe quoi ; à migrer ou à condamner explicitement.
- Les actions de déploiement 4-8 sont, elles, TOUJOURS valides ([action_decoder.py:160-175](../../engine/action_decoder.py#L160-L175)).
- L'incohérence est documentée dans la config elle-même : `justification` dit
  "action_space_size=31 (16 micro + 15 macro)" alors que le champ vaut 41 (26 micro + 15 macro)
  — les wrappers/bots sont restés sur un layout intermédiaire.

### R6 — Bug moteur : socles ovales en éligibilité de charge (touche AUSSI le PvP)
**Repro** : scénario contenant un Carnifex ou Psychophage (seuls types à `BASE_SIZE` liste,
vérifié via UnitRegistry : `[41,27]` et `[47,36]`) → à l'entrée en phase charge,
`charge_build_valid_destinations_pool` → `TypeError: can only concatenate list (not "int") to
list` ([charge_handlers.py:3627-3628](../../engine/phase_handlers/charge_handlers.py#L3627-L3628)) : `_mover_bs = unit["BASE_SIZE"]` puis
`(_mover_bs + 1) // 2` sans gérer le cas liste, alors que le même bloc le gère pour l'ennemi
6 lignes plus bas (`_e_bs_int = max(_e_bs) if isinstance(_e_bs, (list, tuple)) ...`, L3634-3635).
Chemin atteignable en PvP via `_has_valid_charge_target` (L3390) → à corriger indépendamment du
training. Les rosters d'entraînement Tyranids peuvent contenir ces unités.
**DEUXIÈME occurrence du même pattern** : `_charge_reverse_goal_bfs_for_eligibility`
([charge_handlers.py:825-826](../../engine/phase_handlers/charge_handlers.py#L825-L826)), même asymétrie avec l'ennemi (L832-833), calcul fait AVANT le
garde `BASE_SHAPE == "round"`. Nuance vérifiée : la fonction est DÉSACTIVÉE sur boards scalés
(appelée seulement si `inches_to_subhex <= 1`, ~L3693-3697 ; notre board = 5) → site
inatteignable en pratique sur 44x60x5. Le fix T1 couvre quand même LES DEUX sites (défense en
profondeur) ; seul le premier (L3627) crashe réellement.

### R7 — Fin d'épisode au tour limite : masque vide sans terminaison (moteur nu)
**Repro** (moteur nu, sans wrapper, scénario fight, R4 simulé) : au dernier tour, phase fight
du joueur 2, tous les pools vides, aucun état fight pendant → masque entièrement vide,
`terminated=False`. MaskablePPO crashe sur masque vide.
Analyse statique concordante : SEULE `_fight_phase_complete` (fight_handlers, def ~L1867,
appelée ~L1488/1904/2408) pose `game_over` en vif — et uniquement **au sein d'un `step()`**.
Masque vide = plus aucun step légal = la complétion de phase n'est jamais déclenchée.
⚠️ `_advance_to_next_player` était du CODE MORT en production — **supprimée le 2026-07-19**
(cf. §0.4) : elle n'existe plus, ne pas la chercher.
Nuance config : la limite de tours existe en deux endroits — `max_turns` (game_config.json L14)
et `max_turns_per_episode` (training config) ; clarifier en T5 lequel fait foi en moteur nu.
Dans la pile réelle, ce cas est censé être absorbé par le "WAIT forcé" du wrapper
([env_wrappers.py:427-436](../../ai/env_wrappers.py#L427-L436)) — actuellement cassé par R5. **À revalider après R5** : si le
deadlock persiste à travers le wrapper, corriger la root cause côté moteur (la complétion de la
phase fight du dernier tour doit déclencher la fin d'épisode sans exiger une action illégale),
pas en injectant des actions bidon.

### R8 — Interface agent aveugle aux nouvelles règles (non bloquant pour Phase A)
Vérifié par lecture concordante :
- **Niveaux** : aucune feature d'élévation dans l'observation (ni 108 ni 357) ; l'agent subit le
  coût de descente §13.06 (retranché du budget rigide, [shared_utils.py:3760-3763](../../engine/phase_handlers/shared_utils.py#L3760-L3763)) sans pouvoir
  le percevoir ; il ne peut pas monter (commentaire moteur : "l'IA directionnelle 2D ne monte
  pas", même bloc). Le moteur, lui, gère montée/descente (`_model_climb_reachable_floor_cells`
  [movement_handlers.py:2889](../../engine/phase_handlers/movement_handlers.py#L2889), `reachable_multilevel_field`
  [engine/phase_handlers/geodesic_move.py:148](../../engine/phase_handlers/geodesic_move.py#L148)).
- **Pivot/perModelMove** : résolus automatiquement par le moteur (plan rigide) — aucun point de
  décision agent. Légal règles (un placement légal parmi d'autres), sous-optimal seulement.
- **Fight V11** : action 25 = pile-in + déclaration + résolution + consolidation auto
  (`_ai_select_pile_in_destination` fight_handlers.py:1686, `_ai_select_fight_target` L1725,
  `_ai_select_consolidation_destination` L1436). Légal, choix internes non pilotés par la policy.
- **LoS/engagement 3D** : gate vertical implémenté ([spatial_relations.py:143-231](../../engine/spatial_relations.py#L143-L231)) mais le module
  lève lui-même "câblage incomplet" si les données verticales manquent (L186-189, chantier 4) ;
  l'observation utilise une `los_topology` 2D "legacy boards" (observation_builder.py:741).
  → Le chantier LoS 3D (Documentation projet "Chantier 5") est un PRÉREQUIS règles pour le tir
  multi-niveaux ; le training Phase A n'en dépend pas tant que les scénarios d'entraînement
  restent mono-niveau, mais la Phase B avec terrains à étages OUI. Vérifier l'état du chantier
  avant d'activer des terrains à étages en training.

### Notes non bloquantes (à traiter en T6)
- `active_shooting_unit` : cycle de vie sain uniquement pour le flux PvP/PvE ; ne pas l'activer
  en gym (cf. R4 ⚠️).
- `ai/target_selector.py` : orphelin (importé seulement par son test unitaire).
- Docs périmées : AI_OBSERVATION.md décrit 357 floats, AI_TRAINING.md 355 — aucun ne décrit le
  pipeline squad 108 actif ; `justification` de la config dit 31 au lieu de 41. Les snapshots
  `BEST_CoreAgent_training_config.json` (obs 355) sont incompatibles avec le code actuel
  (`build_observation` exige 357, [observation_builder.py:1094-1097](../../engine/observation_builder.py#L1094-L1097)).

## 4. Décisions de design imposées

1. **Phase A à interface constante** : on garde `Discrete(41)` / `Box(108)`. Aucun ancien modèle
   n'est réutilisable de toute façon (layout obs squad + VecNormalize stats) → tout run se fait
   avec `--new`. Ne jamais écraser les zips existants (protégés).
2. **Source de vérité unique "joueur programmatique"** : le prédicat "ce joueur est piloté par la
   machine (auto-résolution)" doit exister en UN seul endroit, consultable depuis game_state
   (le flag `gym_training_mode` y est déjà copié, [w40k_core.py:491](../../engine/w40k_core.py#L491)/1011). Les QUATRE prédicats
   recensés en R4 (`W40KEngine._is_player_human`, `_target_defender_is_ai`,
   `_is_ai_controlled_fight_unit`, `_is_ai_controlled_shooting_unit`) doivent s'appuyer dessus.
   Interdit de dupliquer le check. ⚠️ La bascule gym ne doit s'appliquer qu'aux décisions
   d'ALLOCATION/résolution, pas aux mécanismes d'auto-activation type `active_shooting_unit`
   (cf. ⚠️ R4) : auditer chaque site d'appel avant de brancher le prédicat unique.
3. **Plus aucun ID d'action littéral dans ai/** : importer les constantes depuis
   `engine/macro_intents.py`. État réel : **AUCUNE constante d'action n'existe** — le mapping
   n'est qu'en commentaire (L9-18) ; seuls `INTENT_*`, `MAX_OBJECTIVES`, `BASE_ZONE_INTENT`,
   `TOTAL_ACTION_SIZE` sont définis. TOUT est donc à créer : `ACTION_WAIT = 18`,
   `SHOOT_SLOT_BASE = 19`, bases move/advance/fallback, `ACTION_CHARGE = 24`,
   `ACTION_FIGHT = 25`, `DEPLOY_SLOTS = range(4, 9)`. Un littéral d'action dans ai/ = bug de
   revue.
4. **Scénarios : référence de board explicite** — les scénarios d'agent restent sous
   `config/agents/<agent>/scenarios/` (banque par agent, rosters aléatoires) mais déclarent
   `"board_ref": "44x60x5"`. Le résolveur ([game_state.py:1646](../../engine/game_state.py#L1646), 1437, 1496) accepte alors :
   parent == `scenario/` d'un board (comportement actuel, inchangé pour le PvP) OU clé
   `board_ref` présente → `config/board/<board_ref>/`. Absence des deux = erreur explicite
   (pas de fallback). Alternative rejetée : déplacer la banque sous
   `config/board/44x60x5/scenario/` — casse la structure par-agent et le check exige un parent
   nommé exactement `scenario` (pas de sous-dossiers training/holdout).
5. **Miroir PvP strict** : la phase A ne modifie AUCUNE règle de jeu ; les fixes moteur (R4, R6)
   doivent être neutres pour le flux PvP manuel (mémoire projet : le flux gym copie le flux
   PvP, jamais le durcir/diverger). Seuils/conversions via `inches_to_subhex`.
6. **Prochain agent : 2 rosters seulement** (décision utilisateur 2026-07-14). Le nouvel agent
   ne s'entraîne que sur 2 rosters différents — spécialisation assumée, pas de généralisation
   multi-rosters. Câblage vérifié dans le code, AUCUNE modif moteur nécessaire :
   - la résolution passe par `agent_roster_ref`/`opponent_roster_ref` du scénario
     ([game_state.py:1026-1057](../../engine/game_state.py#L1026-L1057)) ; trois formes supportées : `"training_random"` (tirage
     dans `config/agents/<agent_key>/rosters/<scale>/training/agent_training_roster*.json`),
     ref explicite `"training/<fichier>.json"`, ou **liste de refs** → `rng.choice`
     ([game_state.py:1176-1186](../../engine/game_state.py#L1176-L1186)) ;
   - **voie retenue** : dossier `config/agents/<NouvelAgent>/rosters/<scale>/training/` ne
     contenant QUE les 2 fichiers (pattern `agent_training_roster*.json` obligatoire, clé
     interne `roster_id` requise) + `"agent_roster_ref": "training_random"` dans les scénarios
     → tirage 50/50 par épisode ;
   - `config/agents/_p2_rosters/` est PARTAGÉ entre agents (pool de tirage
     `150pts/training/` = 151 fichiers ; le dossier 150pts en contient bien plus, holdouts
     inclus) : si les 2 rosters incluent l'adversaire, restreindre `opponent_roster_ref`
     (ref explicite ou liste) — sinon P2 continue de tirer dans toute la banque ;
   - désactiver `roster_pool_schedule` dans la training config
     (`_filter_training_roster_candidates`, game_state ~L1322-1393) : le filtre progressif
     swarm/troop/elite peut vider un pool de 2 fichiers → `ValueError
     "roster_pool_schedule produced zero eligible training rosters"` (~L1422-1426).
     Si le schedule reste actif : le nommage doit matcher `(elite|swarm|troop)_(\d+)$`
     sinon écart SILENCIEUX du fichier ;
   - contraintes fichiers : suffixes `_kpis`/`_matchups` exclus du tirage, composition non
     vide. ⚠️ L'unicité des `roster_id` internes n'est PAS vérifiée au tirage (contrôlée
     seulement sur un chemin marginal) : deux fichiers au même roster_id passent en silence
     et fausseraient le suivi win-rate par-roster — vérifier à la main les 2 fichiers ;
   - `agent_roster_seed` (clé scénario) fige le tirage AGENT seulement — il ne fige PAS le
     tirage opponent (seed non transmis, `random_seed=None`) ;
   - conséquences training attendues : convergence plus rapide (distribution d'observations
     quasi stationnaire), holdouts multi-rosters non pertinents comme critère ; risque
     principal = un roster qui domine le gradient → **suivre le win-rate PAR roster**
     (`roster_info`/`agent_roster_id` déjà loggé par épisode,
     [step_logger.py:188-194](../../ai/step_logger.py#L188-L194)), jamais l'agrégé seul (critère T6.3 à lire par-roster).

## 5. Tranches d'implémentation

Chaque tranche se termine par sa validation (section 6) AVANT de passer à la suivante.

### T1 — Fixes moteur neutres (R4, R6) — ✅ FAIT, prédicat ET branchement verrouillés (2026-07-21)

> **Historique du statut** : ✅ (2026-07-15) → ⏳ PARTIEL (audit §0.19.1, 2026-07-20) → ✅
> (§0.19.3, 2026-07-21).
>
> 🔴 **Le démenti de §0.19.1** : le code de T1 était en place et conforme, mais deux de ses trois
> volets n'étaient **verrouillés par aucun test** — le **site R6 n°1**
> (`_charge_reverse_goal_bfs_for_eligibility`, inatteignable au x5 : mutation `int()` sur une
> liste, suite **verte**) et **R4** (zéro occurrence de `is_programmatic_owner` /
> `is_programmatic_defender` dans `tests/`, alors que §8.3 impose une matrice complète).
>
> ✅ **R6 comblé en §0.19.3** : `test_charge_oval_base_reverse_bfs.py` (+4, avec garde
> d'atteinte) — les DEUX sites rougissent désormais sur mutation.
>
> ✅ **R4 comblé** : `test_programmatic_owner_predicate.py` (+22) verrouille le **prédicat** et
> son refus du repli ; `test_r4_auto_decider_wiring.py` (+14) verrouille son **BRANCHEMENT** —
> or c'était ça, la rupture R4. Les **6** exigences de §8.3 sont couvertes, chaque cas gym ayant
> son jumeau PvP. 6 mutations au total, toutes rouges, dont une qui **rejoue la rupture R4
> d'origine**. Détail en §0.19.3. Le texte ci-dessous est celui de la session d'origine,
> **conservé tel quel**.

Réalisé : R6 normalisé dans les 2 sites ; prédicat unique `is_programmatic_owner` /
`is_programmatic_defender` (shared_utils), délégation de `_target_defender_is_ai` (SHOOT_CTX)
et `_is_ai_controlled_fight_unit` (FIGHT_CTX + 4 defender_human) ; `player_types` et
`_is_ai_controlled_shooting_unit` non touchés. Validé : 1152 passed / 2 skipped ; smoke gym
3 seeds — charge Carnifex OK, pertes fight réellement allouées via FIGHT_CTX (kill constaté).
Le masque vide au tour 5 (fin de fight P2) a été RE-CONSTATÉ → confirme R7, à traiter en T5.
Reste : validation PvP manuelle rapide (non-régression) côté utilisateur.
1. **R6** : normaliser `_mover_bs` en miroir exact du traitement ennemi
   (`_mover_bs_int = max(_mover_bs) if isinstance(_mover_bs, (list, tuple)) else
   int(_mover_bs)`) dans les DEUX sites : `charge_build_valid_destinations_pool`
   (~L3627-3628) ET `_charge_reverse_goal_bfs_for_eligibility` (~L825-826).
2. **R4** : introduire un prédicat unique (proposé : `is_programmatic_defender(game_state,
   target_sid)` dans shared_utils) : renvoie True si `game_state.get("gym_training_mode")` est
   True, sinon comportement actuel (player_types, erreurs explicites conservées). Sites à
   brancher — inventaire vérifié :
   - `SHOOT_CTX.auto_decider = _target_defender_is_ai` (shared_utils ~L113), consommé par
     `_manual_allocation_step` (~L6212, L6242) ;
   - `FIGHT_CTX.auto_decider = _fight_auto_defender` (fight_handlers ~L5728), les checks
     `defender_human` du flux fight (~L5425, L5450, L6150, L6184), ET les deux gardes
     `RuntimeError "allocation ... non terminee en auto"` (`squad_shoot`/`squad_fight` dans
     w40k_core + garde jumelle fight_handlers ~L3352-3357) qui doivent cesser de crasher une
     fois le prédicat branché ;
   - `HAZARD_CTX` (shared_utils ~L6423-6437) n'a pas d'`auto_decider` : le hazard est DÉJÀ
     gym-aware au call-site (`auto_resolve = gym_training_mode`, [w40k_core.py:2634](../../engine/w40k_core.py#L2634)) sans lire
     player_types — rien à faire en gym ; corollaire à vérifier : en PvE, un défenseur IA
     passerait par l'allocation hazard MANUELLE ;
   - chemins `squad_shoot_validate` ([w40k_core.py:4685](../../engine/w40k_core.py#L4685)) et prompts rule-choice
     ([w40k_core.py:2527](../../engine/w40k_core.py#L2527)) — déjà sur `_is_player_human`, vérifier qu'ils basculent sur le
     prédicat unique sans changement de comportement PvP.
   Ne PAS toucher `player_types`. Ne PAS brancher `_is_ai_controlled_shooting_unit`
   (auto-activation) sur la bascule gym (cf. ⚠️ R4).
   Ajouter au smoke test T1 un scénario garantissant des **pertes en mêlée** (le chemin
   FIGHT_CTX n'a jamais été exercé en gym, cf. R4).
3. Vérification de non-régression PvP : `python3 -m pytest tests/ -x -q` (suite existante,
   1152 tests collectés au 2026-07-14) + une partie PvP manuelle rapide côté utilisateur.

### T2 — Migration wrappers + bots vers l'espace squad (R5) — ✅ FAIT (2026-07-15)

Réalisé : constantes nommées dans `macro_intents.py` (MOVE/ADVANCE/FALL_BACK_DIRS, ACTION_WAIT=18,
SHOOT_SLOTS=19-23, ACTION_CHARGE=24, ACTION_FIGHT=25, DEPLOY_SLOTS=4-8 — miroir de
`SQUAD_ACTION_*` de shared_utils). `evaluation_bots.py` : 8 bots migrés (helper `_first_action_in`,
`_shoot_focus_fire` sur SHOOT_SLOTS, dicts de poids déploiement via DEPLOYMENT_ACTIONS, TacticalBot
inclus) — zéro littéral d'action résiduel. `env_wrappers.py` : bug phare R5 corrigé (`step(11)` →
`ACTION_WAIT`), `return 18` et trackers diagnostiques shoot/wait migrés (BotControlledEnv +
SelfPlayWrapper). `game_replay_logger.log_action` (layout `% 8` mort + lit `self.env.controller`
absent du moteur squad, aucun appelant vif) CONDAMNÉ (NotImplementedError explicite). Tests migrés
(`test_evaluation_bots.py`, `test_env_wrappers.py`, `test_game_replay_logger.py`). Audit train.py /
multi_agent_trainer / bot_evaluation : aucun littéral d'action (les `objectives_ref` restent T3/T4).
Validé : 1152 passed / 2 skipped ; smoke moteur nu 3 seeds (shoot+charge+fight, unité socle-ovale
BASE_SIZE liste présente → charge franchie sans TypeError R6, 2 pertes mêlée via FIGHT_CTX) ; smoke
pile complète (BotControlledEnv + GreedyBot migré) avance 45-48 steps → **dépasse le 1er WAIT forcé**
(preuve que R5 est levé). Persiste : deadlock fight pile_in fin de partie (boucle 1000 steps /
masque vide sur eligible units) = R7, UNMASQUÉ par le fix R5, à traiter en T5 (déjà prévu par le doc).

**Contre-vérification indépendante (2026-07-15)** — T2 confirmée conforme (code relu, suite
rejouée verte, grep de contrôle passé, smoke pile complète rejoué), avec 3 précisions :
1. ~~**Inexactitude du rapport** : `multi_agent_trainer.py:1016` contient encore `action % 8` +
   `unit_idx = action // 8` (monkeypatch legacy de `controller.execute_gym_action`). Branche
   INERTE (gardée par `hasattr(actual_env, 'controller')`, attribut absent du moteur squad)
   mais « aucun littéral dans multi_agent_trainer » est faux — à condamner/purger comme
   `game_replay_logger.log_action` (raccroché à T6 hygiène ou T5).~~
   → ✅ **SOLDÉ, NE PLUS CITER (voir §0.8).** Le monkeypatch a été purgé au commit `6a7a9de1`,
   le commentaire de purge qui l'a remplacé a disparu avec §0.8, et `game_replay_logger` est
   supprimé. **`grep 'action % 8' ai/multi_agent_trainer.py` est vide.** Ce point a induit deux
   relecteurs en erreur *après* sa résolution, parce qu'ils l'ont cité depuis cette doc au lieu de
   grep le fichier — d'où le rappel : **une doc n'est pas une source, le code l'est.**
2. **Précision sur le smoke pile complète** : les épisodes 40-48 steps ne se terminent PAS
   normalement — ils sont tués par le garde « 1000 steps » du wrapper, en deadlock
   `squad_wait` fight/pile_in dès le **TOUR 1** (scénario à unités pré-engagées), pas
   seulement au tour limite. Le périmètre T5 est donc PLUS LARGE que « fin d'épisode au
   dernier tour » : toute phase fight avec pile-in éligibles peut boucler.
3. **Nouveau symptôme, même famille (T5)** : avec `agent_seat_mode="p2"` ou `"random"`
   (= la config réelle de train.py), le RESET crashe —
   `RuntimeError "bot-owned eligible units with empty action mask"` en fight tour 1
   (le bot P1 déroule son tour jusqu'à la phase fight alternée où l'unité éligible
   n'appartient plus au joueur courant). Seul seat="p1" passe. À couvrir en T5.

1. Ajouter dans [macro_intents.py](../../engine/macro_intents.py) les constantes nommées manquantes (WAIT=18, bases des
   plages move/advance/fallback/shoot, CHARGE=24, FIGHT=25, DEPLOY_SLOTS=range(4,9)) et les
   utiliser partout dans `ai/env_wrappers.py` et `ai/evaluation_bots.py` (supprimer
   `WAIT_ACTION = 11`, les littéraux 11/12, les plages 4-8 hors déploiement ; remplacer aussi
   les `return 18` déjà corrects mais en dur — L556, L854, L1172, L1188 — par la constante).
2. **Auditer la logique de chaque bot phase par phase** contre le mapping actuel : la sélection
   "shoot" doit itérer les slots 19-23 (slots ennemis via `get_enemy_slot_mapping`), "charge"=24,
   "fight"=25, les moves par direction 0-5/6-11/12-17. Les bots choisissent des actions dans le
   masque : tout choix hors masque = erreur explicite (comportement existant à préserver).
3. `SelfPlayWrapper` : mêmes corrections (WAIT forcé, détection "pool empty").
4. Auditer `ai/train.py`, `ai/bot_evaluation.py` ET `ai/game_replay_logger.py` (layout 8
   actions, L774-828) pour les mêmes littéraux périmés — y compris les dicts de poids
   `{4: 0.50, ...}` d'evaluation_bots (6 occurrences) et les `return 10/4`.

### T3 — Chemins board + config training (R1, R2) — ✅ FAIT (2026-07-15)

Réalisé : **R2** — `_list_available_board_refs` (train.py) et `analyzer.py` résolvent via
`config_loader.get_board_dir()` (plus aucune reconstruction `{cols}x{rows}` en ai/ ; grep ai/
+ scripts/ = seuls ces 2 sites vifs, `analyzer_avant_refactor.py` = backup jamais importé, laissé
tel quel). **R1** — `--training-config` sans défaut silencieux : helper `_require_training_config_phase`
lève une erreur explicite listant les phases (`['x1','x5_append','x5_new','x1_debug','x5_debug']`)
quand un agent est sélectionné sans phase (décision recommandée du doc retenue en MODE NUIT).
**1bis** — retrait de la dimension objectives du tirage de scénarios (`_load_scenario_objectives_ref`
supprimée, `_apply_wall_ref_weighting` en wall-only, `_materialize_scenario_with_refs` n'émet plus
objectives_ref via ce chemin). **1ter** — training config purgée dans les 5 phases
(`train_wall_ref_weights` → `{"default":1.0}`, `eval_wall_refs` → walls-33/mc1 réels,
`train_objectives_ref_weights`/`eval_objectives_refs` supprimées) ; `bot_evaluation.py`
(`_materialize_eval_scenario_refs`) migré : n'émet plus `objectives_ref`/`objectives`/`objective_hexes`
(objectifs = contrat terrain). Point 3 (deployment legacy `{cols}x{rows}`) : différé T4 (décision T4).
Tests ajoutés : `tests/unit/ai/test_train_board_refs.py` (get_board_dir, expand refs inconnus/valides,
R1 message) + `tests/unit/ai/test_bot_evaluation_eval_refs.py` (objectives_ref absent du matérialisé) +
maj `test_analyzer_utils.py` (fake loader get_board_dir).
Validé : **1162 passed / 2 skipped** (baseline 1152 + 10 tests T3, zéro régression) ;
`train.py --step --training-config x1_debug` **dépasse la résolution walls/objectives** (500 entrées
pondérées, plus de FileNotFoundError board dir) — le crash suivant = **R3-a** (scénario hors dossier
`scenario/`) = T4, hors périmètre T3. Smoke moteur nu (Annexe A.1) + pile GreedyBot (A.2), 3 seeds ×
scénario Psychophage/ScreamerKiller : **charge franchie sans TypeError (R6 non régressé)**, toutes
phases atteintes, zéro exception.
⚠️ **Pertes de mêlée non re-démontrées end-to-end** : le smoke A.1 (aléatoire non dirigé, adversaire
passif) ne les produit pas *par conception* (réserve explicite Annexe A) ; le smoke A.2 (GreedyBot des
2 camps) bute sur le **deadlock R7/T5 `fight/pile_in` dès le tour 1** AVANT toute résolution de
blessure. Ce blocage est un item OUVERT (T5), indépendant de T3 (aucun code moteur touché) — la
preuve FIGHT_CTX reste celle de T1 (committée). À re-valider après T5.

**Contre-vérification indépendante (2026-07-15)** — T3 confirmée conforme : repro R1 rejouée
(erreur explicite avec les 5 phases), repro R2/x1_debug rejouée (« 500 entries, 100 unique
files », crash suivant = R3-a exactement), 1162 tests collectés / suite verte, config purgée
vérifiée dans les 5 phases, aucun code moteur touché (git status). UNE réserve mineure :
`_materialize_scenario_with_refs` (train.py ~L642-668) conserve un paramètre `objectives_ref`
et sa branche d'émission `scenario_copy["objectives_ref"] = ...` — MORTE (l'unique appelant
~L854 ne passe que wall_ref) mais tout futur appelant réémettrait une clé rejetée par le
moteur. À purger en T4 (avec la migration) ou T6.

1. **R2** : remplacer la reconstruction `{cols}x{rows}` de `_list_available_board_refs`
   ([train.py:586-591](../../ai/train.py#L586-L591)) par `config_loader.get_board_dir()`. Même motif déjà repéré ailleurs :
   `ai/analyzer.py:224` (et `analyzer_avant_refactor.py:224`) reconstruisent
   `config/board/{cols}x{rows}/objectives`. Greper `ai/` et `scripts/` pour le solde.
1bis. **train.py émet encore `objectives_ref`** : `_load_scenario_objectives_ref`
   ([train.py:562-577](../../ai/train.py#L562-L577)) et le sampler `train_objectives_ref_weights` (~L873, L887-893)
   expansent des refs `objectives-*.json` — clé que le moteur REJETTE (game_state:320-329).
   Cette branche doit être supprimée/migrée vers les terrains (T4), sinon le tirage de
   scénarios de train.py casse après migration.
1ter. **Migrer la training config et le chemin d'éval** (R3-f/R3-g) : purger
   `train_wall_ref_weights`/`eval_wall_refs`/`eval_objectives_refs` des refs inexistantes
   dans les 5 phases de `CoreAgent_training_config.json`, et migrer
   `_materialize_eval_scenario_refs` (bot_evaluation.py:59-98, émission d'`objectives_ref`)
   vers le contrat terrain — les callbacks d'éval train.py en dépendent.
2. **R1** : décision de config (pas de code) : soit ajouter une phase `default` pointant vers la
   config x1 courante dans `CoreAgent_training_config.json`, soit rendre `--training-config`
   obligatoire (erreur explicite listant les phases disponibles). Recommandé : la seconde (pas
   d'alias silencieux). À valider avec l'utilisateur au checkpoint T3.
3. La voie legacy `config/deployment/{cols}x{rows}/` ([game_state.py:436-440](../../engine/game_state.py#L436-L440)) : si la banque
   migrée (T4) n'utilise plus `deployment_zone` nommée, ne pas y toucher ; sinon fournir les
   fichiers de zones pour `220x300` (décision en T4).

### T4 — Migration de la banque de scénarios (R3) — ✅ FAIT (2026-07-15)

Réalisé : **resolver `board_ref`** — helper `_resolve_board_dir(scenario_file, board_ref,
purpose)` dans game_state.py (seul fichier moteur touché) : parent `scenario/` (voie PvP
inchangée) OU `board_ref` → `config/board/<board_ref>/` ; erreurs explicites (absence des
deux, board inexistant, traversal), câblé dans `_resolve_shared_config_path`,
`_load_shared_walls_from_ref` (random) et `_read_terrain_file` + call-sites. **Bug moteur
corrigé au passage** : `pool_set` gardé derrière le NOM legacy `deployment_zone` → les zones
issues du terrain (voie moderne) ne peuplaient pas le pool de déploiement random/fixed
(fix neutre PvP, commenté en ~L576). **Terrains plats** `terrain-train-01/02/03.json`
(5 objectifs, deployment_zones "1"/"2", 0 étage). **Migration** :
`scripts/migrate_scenario_bank_v11.py` (idempotent) — 61 scénarios migrés (0 clé legacy,
`board_ref`+`terrain_ref`), `training_save/` (30) archivé sous `_archive_pre_v11/`.
**Outillage** : `build_holdout_benchmark.py` migré ; `scenario_manager.py` NON touché
(chemin dormant — `config/scenario_templates.json` absent → lève à la construction ; son
alignement 0/1 vs 1/2 traverse multi_agent_trainer = chantier séparé à valider).
**Balayage** : `scripts/sweep_scenario_bank_v11.py` — 61/61 chargés + reset. Tests +83.
Validé : 1245 passed / 2 skipped ; Carnifex en charge 3 seeds sans TypeError (R6).
⚠️ Pertes de mêlée toujours non démontrables end-to-end (deadlock R7/T5 fight/pile_in tour 1,
confirmé 3 voies) — inchangé depuis T2/T3, aucun code fight/charge touché par T4.

**Contre-vérification indépendante (2026-07-15)** — T4 confirmée conforme : balayage rejoué
(61/61 + reset, 0 clé legacy hors archive — grep indépendant), suite rejouée (1245 collectés,
verte), sample de scénario migré inspecté (clés legacy absentes, refs présentes), 3 terrains
inspectés (5 objectifs, dz 1/2, 0 floor), resolver relu (zéro fallback, traversal gardé),
`users.db` propre, `charge_handlers` non touché (non-régression R6 structurelle). Réserves
mineures : (1) les scripts `migrate_/sweep_scenario_bank_v11.py` n'ont pas de bootstrap
`sys.path` — exécutables uniquement avec `PYTHONPATH=.` ; (2) la réserve T3 (paramètre
`objectives_ref` mort de `_materialize_scenario_with_refs`, train.py ~L645-668) n'a PAS été
purgée en T4 → reste pour T6.

Plan d'origine (réalisé ci-dessus) :
1. Implémenter la clé **`board_ref`** dans le résolveur (décision de design n°4) :
   `_resolve_shared_config_path`, `_load_shared_walls_from_ref` (branche "random") et
   `_read_terrain_file` ([game_state.py:1646](../../engine/game_state.py#L1646), 1437, 1496). Erreur explicite si ni parent
   `scenario/` ni `board_ref`.
2. Créer les **terrains d'entraînement** sous `config/board/44x60x5/terrain/` : chaque terrain
   porte objectifs (`"objective": true`) et `deployment_zones` (polygones J1/J2). Point de départ:
   dériver des terrains existants (`terrain-mc1.json`, `terrain-floors-test.json`) et des
   anciennes refs objectives/walls de la banque. Phase A : terrains PLATS uniquement (pas
   d'étages) — les étages arrivent en Phase B (cf. R8/LoS 3D).
   ⚠️ Piège vérifié : un terrain SANS aucune area `"objective": true` donne une liste
   d'objectifs VIDE en silence (game_state ~L376-381) — le script de migration doit valider
   ≥ 1 objectif par terrain produit.
3. Migrer les **61 scénarios** de la banque (training 30 + training_benchmark 4,
   holdout_regular 10, holdout_hard 10 + matchups 7) : supprimer `objectives_ref`, remplacer
   `deployment_zone`/`wall_ref` par `terrain_ref` (+ `wall_ref` réel encore supporté) +
   `board_ref`. Statuer sur `scenarios/training_save/` (30 JSONs) : migrer ou archiver.
   Écrire un script de migration dans `scripts/` (one-shot, vérifiable) plutôt qu'une édition
   manuelle. Les refs `"random"` (walls/terrain)
   doivent piocher dans le board résolu — vérifier le support côté train.py
   (`_expand_random_ref_weights`, [train.py:603](../../ai/train.py#L603)) après le fix R2.
4. Outillage impacté — état vérifié :
   - `scripts/build_holdout_benchmark.py` **ÉMET les clés legacy** (`deployment_zone: "hammer"`
     L110, `objectives_ref` L118/246/254) → à migrer, pas seulement à vérifier ;
   - `ai/scenario_manager.py` : utilise des `deployment_zones` avec clés joueur **0/1** alors
     que les terrains modernes utilisent **"1"/"2"** → incompatibilité à résoudre ;
   - `scripts/rebalance_holdout_hard_scenarios.py`, `scripts/build_dynamic_rosters.py` : aucune
     clé legacy détectée, re-vérifier après migration.

### T5 — Boucle complète et fin d'épisode (R7) — ✅ FAIT (moteur nu, 2026-07-16) — verrou confirmé par mutation (§0.19.1)

> ✅ **Confirmé le 2026-07-20** : le fix `_deployment_clearance_filter` est verrouillé —
> neutralisé, `test_deployment_mask_mirrors_commit_overlap_predicate` rougit en 6,7 s avec le
> symptôme d'origine (42 s vert sans mutation).
> ⚠️ **Mais le critère §6 de T5 est plus large que ce ✅** : il exige « ≥3 scénarios × sièges
> p1/p2 », alors que `test_t5_bare_loop.py` exerce **un** scénario × 3 seeds et **aucun siège**.
> Le ✅ vaut pour le **moteur nu, siège p1**, comme la tranche l'annonce dans son « Reste ».

Réalisé (périmètre MOTEUR NU, décision utilisateur : « smoke moteur nu avec pertes en mêlée
garanties + Carnifex en phase charge ») :

- **R7 ne se manifeste PAS en moteur nu** : `W40KEngine.get_action_mask()`
  ([w40k_core.py:5563](../../engine/w40k_core.py#L5563)) auto-avance déjà la phase fight quand ses pools sont vides
  (boucle `fight_phase_end` tant que masque vide ET pas game_over) → l'invariant
  `mask.any() or game_over` tient à CHAQUE step. Vérifié sur 3 scénarios `active` × 3 seeds +
  scénario fixe pré-engagé : zéro masque vide sans terminaison, zéro exception, toutes les
  parties se terminent (turn limit). Le fix conditionnel T5.2 sur `_fight_phase_complete`
  n'était donc PAS requis — non touché ; `_advance_to_next_player` (mort) laissé tel quel
  **à l'époque, supprimé depuis le 2026-07-19 (§0.4)**.
- **Vraie rupture bloquante en moteur nu = déploiement `active`, PAS R7 (nouvelle, hors R1-R8)** :
  `ActionDecoder._get_valid_deployment_hexes` ([action_decoder.py:961](../../engine/action_decoder.py#L961)) testait le
  chevauchement inter-unités par CELLULES (`build_occupied_positions_set`), alors que le commit
  `deployment_handlers.deploy_unit` (~L1017) le teste par CLEARANCE euclidien CONTINU
  (`candidate_overlaps_any_unit`, plus strict rond↔rond). Le masque proposait donc des hexes que
  le commit rejetait (`deploy_footprint_occupied`) ; l'action restant dans le masque, elle
  échouait en boucle → deadlock (épisode tué au garde 1000 steps ; ~2/3 des seeds sur bot-01).
  **Fix** : `_get_valid_deployment_hexes` filtre désormais les candidats cellule-valides par le
  MÊME modèle que le commit (nouveau `_deployment_clearance_filter` : broad-phase numpy
  distance-centres puis `candidate_overlaps_any_unit` exact), miroir strict (règle projet « le
  déploiement copie la phase move »). Neutre PvP (même prédicat que le commit ; volet bornes/murs/
  pool inchangé). Seul `action_decoder.py` touché.
- **Smoke moteur nu (`scripts/smoke_t5_bare.py`, committé, sans monkeypatch)** :
  (A) bot-01/02/03 × seeds 1-3 → terminate + zéro masque vide ;
  (B) scénario fixe (ScreamerKiller P1 pré-engagé vs Termagant P2 ; Carnifex P1 à portée de
  charge d'un Termagant P2) → **pertes en mêlée réelles via FIGHT_CTX à chaque seed** (kill
  `squad_fight` constaté) + **Carnifex éligible en phase charge sans TypeError (R6)**.
- **Tests ajoutés (+7)** : `tests/unit/engine/test_deployment_clearance_parity.py` (4 : parité
  masque↔commit + anti-deadlock en clustering forcé) et `tests/unit/engine/test_t5_bare_loop.py`
  (3 : invariant `mask.any() or game_over`, pertes mêlée FIGHT_CTX, Carnifex charge R6). Suite
  `tests/unit/` verte (baseline 1245 + 7).

Reste (hors moteur nu, non couvert par cette tranche) : le smoke **pile complète** (wrapper
`BotControlledEnv`) — cf. contre-vérif T2 : reset crashe encore avec `agent_seat_mode="p2"/"random"`
(`bot-owned eligible units with empty action mask` en fight tour 1). Chantier wrapper/pool alterné
distinct, à traiter avant l'entraînement réel T6 avec la config de siège de train.py.

Plan d'origine :
1. Rejouer le smoke test pile complète (annexe A) après T1+T2 : 10 épisodes aléatoires masqués
   doivent se terminer (`terminated=True`, winner déterminé), zéro masque vide, zéro exception.
2. Si le deadlock R7 persiste : corriger côté moteur la complétion de phase fight au dernier
   tour, via le SEUL chemin vif : `_fight_phase_complete` (fight_handlers, def ~1867) doit
   aboutir à `terminated` sans exiger une action supplémentaire quand le pool est vide.
   `_advance_to_next_player` était mort en production (cf. R7) — **supprimée le 2026-07-19**
   (§0.4), donc plus rien à statuer. Interdit de résoudre par injection d'action côté
   wrapper.
3. Étendre le smoke test aux scénarios migrés (T4), sièges p1/p2/random, et à un scénario
   contenant Carnifex/Psychophage (validation R6).

### T6 — Entraînement de validation + hygiène — ⏳ EN COURS (màj 2026-07-19)

> **Bloqueurs actifs : T6-h puis T6-g** (cf. §0). T6-a→T6-f sont résolus. Les entrées ci-dessous
> sont chronologiques ; chercher `T6-g` / `T6-h` pour le chemin critique.

**Préalable levé** : le bloqueur résiduel laissé par T5 (« reset crashe avec
`agent_seat_mode="p2"/"random"` — `bot-owned eligible units with empty action mask` en fight
tour 1 ») **ne se reproduit plus**. Vérifié en miroir exact de train.py:1673-1716
(`ActionMasker` + `BotControlledEnv` + `GreedyBot`) sur `scenario_training_bot-01` × sièges
p1/p2/random × 2 seeds : les 6 combinaisons terminent (`terminated=True`, turn=5), zéro masque
vide. Le fix de parité déploiement de T5 l'a manifestement couvert.

**Rappel des critères de sortie (re-démontrés sur l'arbre T6)** : suite `tests/unit/` verte ;
smoke moteur nu `scripts/smoke_t5_bare.py` → `(A) invariant/terminaison=OK | (B) mêlée+Carnifex=OK`
avec `melee_kills_total=5` (pertes réelles via FIGHT_CTX) et `carnifex_charge_any=True` (R6).

**Deux ruptures T6 vérifiées et corrigées** (aucune ne figure dans R1-R8 — ce sont des reliquats
de T4/de code latent) :

- **T6-a — `wall_ref` exigé par le sampler alors que T4 l'a supprimé (BLOQUANT, crash immédiat)**
  **Repro** : `train.py --agent CoreAgent --scenario bot --new --training-config x1_debug --step`
  → `ConfigurationError: Required key 'wall_ref' is missing from mapping`
  (`_load_scenario_wall_ref`, train.py ~L556, via `_apply_wall_ref_weighting`).
  **Cause** : `migrate_scenario_bank_v11.py` supprime délibérément `wall_ref` (docstring : « supprime
  les clés legacy … wall_ref ») — les 61 scénarios migrés sont TERRAIN-ONLY (`board_ref` +
  `terrain_ref`, vérifié : 61/61 sans `wall_ref`). Le contrat moteur rend `wall_ref` OPTIONNEL
  (`wall_hexes` XOR `wall_ref`, `terrain_ref` additif — game_state.py ~L285-314). T4 a migré la
  banque mais pas ce sampler.
  **Fix** : `_load_scenario_wall_ref` renvoie `Optional[str]` — `None` quand la clé est ABSENTE
  (état légitime du contrat, pas une valeur par défaut masquant une erreur) ; une clé présente
  reste strictement validée (erreur explicite si vide/non-string). `None` traverse
  `_apply_wall_ref_weighting` sans override (poids `"default"` = « garde les murs du scénario »,
  ~L853) → aucun `wall_ref` injecté.

- **T6-b — `--step` était un no-op SILENCIEUX (bloque analyzer + replay)**
  **Repro** : le run affiche « 📝 Step logging enabled » puis « ✅ StepLogger connected », et
  `step.log` reste réduit à son en-tête (7 lignes) après 20 min d'entraînement.
  **DEUX causes indépendantes, les deux corrigées** :
  1. *Le StepLogger n'est branché que sur la branche mono-env* (`if step_logger:
     base_env.step_logger = step_logger`) ; les **trois** branches vectorisées construisent leurs
     envs avec `step_logger_enabled=False`. Avec `n_envs=48` (x1_debug), `--step` ne pouvait rien
     produire. Le code forçait déjà `n_envs=1` pour `--replay`/`--convert-steplog` (~L1326) mais
     PAS pour `--step`. → helper unique `_resolve_n_envs_for_step_logging` (train.py ~L571) branché
     aux **3** sites de résolution de `n_envs` (~L1354, ~L1665, ~L2129) : force l'env unique ET le
     DIT. Factorisé volontairement — trois gardes dupliqués sont exactement le motif de migration
     partielle qui a produit R5. ⚠️ Piège vérifié : les 3 sites impriment le MÊME message
     « 🚀 Creating N parallel environments » — ne pas se fier au log pour identifier le site actif
     (`--scenario bot` passe par `train_with_scenario_rotation`, site ~L2129).
  2. *Bug latent : l'env est RECRÉÉ sans reconnecter le StepLogger* (train.py ~L2637-2651,
     « For n_envs==1: recreate env with frozen model for self-play »). Ce second `base_env` reçoit
     `_metrics_tracker` mais jamais `step_logger` → le run journalisait « StepLogger connected »
     pour un env aussitôt jeté, puis s'entraînait sur un moteur MUET. Chemin exigeant `n_envs==1`
     (config = 48) → jamais emprunté, donc jamais vu. **Révélé par le fix (1).**
     → reconnexion en miroir de ~L2377.
  ⚠️ `StepLogger.log_episode_start` avale toute exception (`except Exception: print("⚠️ Episode
  start logging error")`, step_logger.py ~L254) — un step.log vide peut donc masquer une erreur.
  Ici le diagnostic a été fait par élimination (aucun warning émis ⇒ la fonction n'était PAS
  appelée ⇒ le moteur entraîné n'avait pas de logger).

- **T6-c — `squad_fight` : le COMMIT gym divergeait du PvP (crash d'épisode) — ✅ CORRIGÉ**
  **Repro** (déterministe) : `MELEE_SCENARIO` + actions tirées par `default_rng(seed*777+i)`,
  seed=1 → `ValueError: squad_fight: aucune cible pour squad 3 — mask aurait dû l'empêcher`.
  Seul seed=1 échoue (2 et 3 passent) → **un smoke vert ne prouvait pas son absence**
  (`smoke_t5_bare.py` tire avec `seed*99991+steps`, séquence différente).
  **Verdict contre-intuitif** : ce n'était PAS le masque. `_squad_is_in_fight` (« a chargé OU en
  ER ») est CONFORME à 12.04 et au prédicat PvP `fight_v11_is_eligible_to_fight`, explicitement
  « indépendant de la présence de cibles ». C'est le commit qui cherchait sa cible dans le
  **mapping de slots gelé du TIR** (`get_enemy_slot_mapping`) scoré par menace globale, **sans
  filtre de zone d'engagement** — donc capable de frapper hors ER (violation 12.05) et de crasher
  quand tous les slots sont morts (chargeur dont la cible meurt avant son activation).
  **Fix** (`w40k_core.py` SEUL, gym-only — `_process_squad_action` n'est appelé que par `step()`) :
  le commit consomme le prédicat du flux PvP (`_fight_build_valid_target_pool` +
  `_ai_select_fight_target`, cf. `_fight_v11_resolve_attacks`) ; pile-in avant la sélection de
  cible (ordre V11 12.02→12.04) ; pool vide = fight « à vide » via le MÊME moteur d'allocation
  (0 intent → summary vide, `done=True`). Garde `ValueError` supprimée : elle interdisait un cas
  légal (12.04/12.06) déjà accepté par le PvP. **Neutralité PvP totale** (`fight_handlers` intact).
  **Tests (+5)** : `tests/unit/engine/test_squad_fight_target_parity.py` (2 vérifiés comme
  échouant sur l'ancien code). Détail : `Implémenté/bug_squad_fight_mask_mismatch.md`.
  ⚠️ **Impact sur le plan §9.4** : le site vif de la cible de mêlée a changé → cf. §9.4 point 1.

- **T6-d — dettes constatées pendant T6-c — DÉCISION UTILISATEUR (2026-07-16) : traiter AVANT le training**
  - **✅ RÉSOLU (2026-07-16) — Le gym n'entrait PAS dans la machine V11.** Mesuré sur épisode
    complet : en phase fight, l'état était invariablement `(fight_subphase='pile_in',
    snapshot_present=False, nb_selected_to_fight=0)`. `fight_phase_start` initialisait la machine,
    puis `squad_fight` (`_process_squad_action`) déroulait le sien — pile-in + fight +
    consolidation **par escouade, en une passe** — sans jamais avancer les états V11.

    **Diagnostic — deux ruptures, pas une.** (1) *États jamais posés* :
    `engaged_at_fight_step_start` absent (branche 12.04 « was engaged at the start of this step »
    inapplicable), `units_selected_to_fight` vide (12.04 « has not already been selected to fight
    this phase » **non appliqué** → une escouade engagée pouvait être re-sélectionnée dans la même
    phase ; 12.08 « was eligible to fight this phase » dérive du même set), `pile_in_done` vide.
    (2) *Ordre de phase faux* : 12.02 exige que TOUS les pile-in des DEUX joueurs précèdent le
    premier combat, et 12.04 date son snapshot du début de l'étape FIGHT — impossible tant que le
    pile-in d'une escouade s'intercale entre deux combats. Aucune pose d'état a posteriori ne
    corrige ça : c'est la découpe de l'action qui était fausse.

    **Fix — `w40k_core.py` seul, `fight_handlers` NON touché (neutralité PvP).** `squad_fight`
    devient **UNE sélection de l'étape FIGHT (12.04)**, encadrée par `_fight_v11_gym_settle` qui
    résout les deux étapes groupées (PILE IN 12.02 puis CONSOLIDATE 12.07) via les planificateurs
    **par-figurine** existants (`fight_pile_in_plan` / `squad_consolidate_plan` — jamais les
    helpers par-ancre condamnés). Aucune perte d'agence : l'agent ne choisissait déjà aucune
    destination de pile-in/consolidation, seulement l'unité qui combat. Action space, taxonomie de
    reward et compte de steps inchangés. Le driver **ne termine pas la phase** : le gym transitionne
    par `advance_phase` sur masque vide, comme toutes les autres phases — compléter depuis une
    action d'unité déclencherait la cascade, qui **remplace** le résultat de l'action et ferait
    perdre à l'agent le `fight_result` (donc le reward) du combat clôturant la phase.

    **Vérifié** : `fight_subphase` atteint `fight` puis `consolidate`, snapshot posé après les
    pile-in, alternance des sélecteurs P1↔P2 réelle, 17 `squad_fight` (vs 6) sur le même épisode.
    Suite 1293 verte, smoke `(A)/(B)` OK (5 kills mêlée, Carnifex charge), 18 épisodes
    BotControlledEnv+GreedyBot (p1/p2/random × 2 seeds) sans échec. Verrou :
    `tests/unit/engine/test_squad_fight_v11_state.py` (6 tests, tous rouges sur l'ancien code).
    Effet de bord corrigé au passage : `end_activation(arg4=FIGHT)` dérivait `phase_complete` des
    pools V10 que V11 ne construit plus (toujours vides → toujours `True`) ; signal mort écarté.
  - **Overrun 12.06 absent du gym** — n'existe qu'en modèle par-ancre, condamné par la décision
    « le pile-in de référence est le par-figurine du PvP » (2026-07-16). Légal (12.06 : « **can**
    make one additional pile-in move »). Spec complète : `A_faire/overrun.md`.
  - **Mismatch cellules/clearance du BFS pile-in/conso** — mesuré 1102 ancres sur 72857 ; fix
    écrit, mesuré (0/71755 après, perf 2m01→1m33), puis **REVERTÉ** : `fight_handlers` est partagé
    et le changement n'est pas neutre PvP. Ne concerne que du code par-ancre condamné → priorité
    basse. Détail + mesures : `A_faire/bug_pile_in_bfs_clearance_mismatch.md`.

- **T6-e — `_turn_step_limit` absent sur le chemin single-scenario (BLOQUANT, crash immédiat) —
  ✅ CORRIGÉ (2026-07-19)**
  **Repro** : `train.py --agent CoreAgent --training-config x5_debug --scenario <fichier.json>
  --new --resolution 5` → `ConfigurationError: Required key '_turn_step_limit' is missing from
  mapping` dans `setup_callbacks` ([train.py:3096](../../ai/train.py#L3096)).
  **Cause** (même famille que T6-a/T6-b : migration partielle d'un chemin de train.py) :
  `training_config["_turn_step_limit"]` n'était écrit que par DEUX chemins — la rotation de
  scénarios (`train_with_scenario_rotation`, bloc inline de calcul du budget) et MacroController
  ([train.py:4786](../../ai/train.py#L4786), relevé sur son propre moteur). Le chemin
  **single-scenario** (`--scenario <fichier>` → `create_multi_agent_model` → `setup_callbacks`)
  ne l'écrivait jamais, alors que TROIS lecteurs le `require_key` :
  [train.py:3096](../../ai/train.py#L3096), [train.py:3469](../../ai/train.py#L3469),
  [multi_agent_trainer.py:556](../../ai/multi_agent_trainer.py#L556). Crash systématique, quel
  que soit le scénario.
  **Fix** : le bloc inline de la rotation est extrait en helper
  `resolve_turn_step_limit(scenario_files, training_config, use_bots, log)`
  ([train.py:2102](../../ai/train.py#L2102)) — MÊME formule (`compute_turn_step_limit` sur le
  scénario au max de figurines, probe des sièges p1/p2/random si `use_bots`) — appelé par les
  deux chemins : rotation ([train.py:2302](../../ai/train.py#L2302)) et single-scenario
  ([train.py:1757](../../ai/train.py#L1757), `use_bots` dérivé de « bot » dans le nom du
  scénario, miroir du choix `BotControlledEnv` ~L1830). Factorisation volontaire : deux calculs
  dupliqués = le motif exact qui a produit R5 et T6-a. Code mort supprimé au passage dans le
  bloc extrait (`num_phases`/import `GAME_PHASES`, calculé et jamais lu).

- **T6-f — Commit de déploiement `deploy_unit` mono-ancre : `models_cache` JAMAIS écrit
  (BLOQUANT gym, crash DIFFÉRÉ en phase move ; touche AUSSI des chemins PvP) — ✅ FAIT
  (2026-07-19, +10 tests `test_deployment_per_model_commit.py`)**
  ⚠️ Cet en-tête est resté « ❌ À FAIRE » jusqu'au 2026-07-19 alors que le fix était livré et
  testé : il contredisait §0 ET le tableau des critères. Corrigé. L'analyse ci-dessous reste
  valable comme historique de la rupture.
  **Rayon (vérifié par lecture, conséquence runtime démontrée côté gym seulement)** : le commit
  fautif est PARTAGÉ — (a) gym via l'action decoder ; (b) auto-déploiement P2 du tutoriel
  ([api_server.py:2255](../../services/api_server.py#L2255)) ; (c) drag mono-socle PvP encore
  actif quand `deployment_type != "active"` (`handleDeployUnit`,
  [useEngineAPI.ts:5512](../../frontend/src/hooks/useEngineAPI.ts#L5512), cf.
  [BoardPvp.tsx:10875](../../frontend/src/components/BoardPvp.tsx#L10875)) et sa route
  sémantique ([w40k_core.py:5265](../../engine/w40k_core.py#L5265)). Tous laissent les
  figurines à `(-1,-1)`.
  **C'est un TROISIÈME bug de déploiement, distinct** de la parité masque/commit T5
  (`_deployment_clearance_filter` — divergence de prédicat, mono-ancre des deux côtés) et du
  logging analyzer (§ « Le déploiement n'était PAS journalisé ») : ici c'est le COMMIT lui-même
  qui est resté pré-V11.
  **Repro** (déterministe, moteur nu, scénario `training_benchmark`, premier index du masque à
  chaque step) : crash au step 7, première action de move —
  `ValueError: execute_squad_move a échoué : squad=1 type=fall_back dest=(214,96) depuis
  (217,154) — incohérence masque/exécution`. Indépendant du terrain (reproduit avec
  `terrain-mc1` ET `terrain-train-01`) et du roster.
  **Root cause (tracée sur l'état)** : après le déploiement gym, `units_cache["1"]` porte bien
  l'ancre `(217,154)` mais les 6 figurines de `models_cache` restent à `(-1,-1)`. La branche
  `deploy_unit` d'`execute_deployment_action`
  ([deployment_handlers.py:953](../../engine/phase_handlers/deployment_handlers.py#L953)) commit
  via `set_unit_coordinates` + `update_units_cache_position`
  ([shared_utils.py:1255](../../engine/phase_handlers/shared_utils.py#L1255) — n'écrit que
  `units_cache` + carte d'occupation, jamais `models_cache`). Le chemin PvP `deploy_commit` →
  `_apply_deploy_plan`
  ([deployment_handlers.py:824](../../engine/phase_handlers/deployment_handlers.py#L824)), lui,
  écrit chaque figurine via `update_model_position` puis synchronise l'ancre.
  **Mécanisme du crash** : le pool BFS du masque de move part de l'ancre `units_cache` (valide),
  mais `build_rigid_plan` ([shared_utils.py:3243](../../engine/phase_handlers/shared_utils.py#L3243))
  translate depuis `models_cache` : 6 figurines confondues en `(-1,-1)` → plan = 6 figs sur le
  MÊME hex destination, et `validate_move_plan` rejette (budget per-model : distance 215 depuis
  `(-1,-1)` > 60 ; collision intra-plan en second rideau). Le masque avait autorisé la cellule →
  la garde « incohérence masque/exécution » de `_process_squad_action` lève. En vectorisé, les
  8 workers `SubprocVecEnv` meurent (EOFError côté parent).
  **Pourquoi invisible jusqu'ici** : T5 a validé la boucle moteur nu AVANT la migration squad
  par-figurine du move (T6/refonte spatiale) — tant que l'exécution du move raisonnait par
  ancre, des figurines à `(-1,-1)` ne faisaient rien crasher (elles produisaient seulement les
  fausses collisions analyzer, cf. § logging).
  **Fix appliqué (2026-07-19) — le commit produit et exécute un plan PAR-FIGURINE validé, pour
  les TROIS chemins d'un coup** (`deployment_handlers.py` + `action_decoder.py`) :
  1. Nouveau `build_validated_deployment_plan` (deployment_handlers) : `generate_compact_formation`
     autour de l'ancre + `deployment_preview_plan` ; rend le plan (4-uplets, niveau 0) SI toutes
     les figurines sont légales, sinon `None`. Lecture pure et déterministe.
  2. `deploy_unit` commit désormais via `_apply_deploy_plan` — le MÊME écrivain que le flux PvP
     par escouade (`update_model_position` par figurine + sync de l'ancre). Plan illégal =
     refus explicite `deploy_plan_invalid`. Comme les trois chemins du rayon partagent cette
     branche, ils sont corrigés ensemble.
  3. `_select_deployment_hex_for_action` (décodeur) retient la meilleure ancre de la stratégie
     **dont la formation est exécutable** : le `max` est remplacé par un parcours par score
     décroissant qui s'arrête au 1er plan valide ; épuisement = `ValueError` explicite. Sans
     ça, une ancre au bord de zone pouvait scorer 1re et n'admettre aucune formation → deadlock
     masque/commit, exactement la classe de bug corrigée en T5.
  4. Le plan validé par le décodeur est mémoisé (`store_/read_validated_deployment_plan`, tampon
     escouade+ancre+phase+nb déployés) pour que le commit ne le RECALCULE pas. Pure économie —
     le helper étant déterministe (verrouillé par test), la mémo n'est jamais une source de
     vérité divergente ; son absence (chemins PvP sans décodeur) est un état légitime.
  **Résultat mesuré** : déploiement gym complet, `training_benchmark` — 0 figurine à `(-1,-1)`
  (6/6 escouades). Chemin « ancre imposée » (drag PvP / auto-deploy tutoriel) exercé sur les
  16 104 hexes de la zone : 6/6 escouades posées, refus répartis en 1815
  `deploy_footprint_out_of_bounds` + 263 `outside_zone` + 31 `occupied` (tous de la validation
  mono-ancre PRÉEXISTANTE) et seulement **2** `deploy_plan_invalid` — le fix ne restreint
  quasiment pas les placements.
  **Coût, et son optimisation** (phase de déploiement complète, board x5, 6 escouades) :
  | étape | temps | note |
  |---|---|---|
  | avant le fix | 1,03 s | ne plaçait AUCUNE figurine — coût non représentatif |
  | fix naïf | 2,31 s | `generate_compact_formation` payé 2× (décodeur + commit) |
  | + mémoisation (point 4) | 1,70 s | supprime le doublon |
  | + empreinte pré-calculée | **1,37 s** | voir ci-dessous |
  5. **Empreinte par translation d'offsets dans `generate_compact_formation`.** cProfile :
     `_legal_socle` = 92 % du coût de la fonction, dont 67 % à reconstruire l'empreinte du socle
     via `compute_occupied_hexes`/`_footprint_round` — **2 590 reconstructions et 341 660 appels
     à `_hex_center` pour UNE formation**, parce que la spirale BFS recalcule la forme à chaque
     case. Remplacé par `precompute_footprint_offsets` (deux jeux d'offsets, parité de colonne),
     le helper prévu exactement pour ça (docstring : « expensive when called per-BFS-step ») et
     déjà utilisé par `_get_valid_deployment_hexes`. **50 ms → 17,4 ms par formation (×2,9).**
     Équivalence stricte vérifiée par test aux deux parités — code partagé avec le déploiement
     PvP par escouade, une divergence déplacerait des socles à l'écran.
  **Reste optimisable (non fait)** : la spirale teste encore chaque case par balayage de son
  empreinte (~77 % du résiduel) et `_deploy_pool_set` est reconstruit à chaque appel (~13 %).
  Pistes, mesures et pièges : [`A_faire/perf_generate_compact_formation.md`](A_faire/perf_generate_compact_formation.md).
  ⚠️ Le gain d'une érosion n'est PAS acquis dans le cas nominal (spirale qui s'arrête en
  quelques cases) — à mesurer avant d'implémenter. Non bloquant : le vrai frein du training est
  T6-g/T6-h, pas cette perf.
  **Tests (+10)** : `tests/unit/engine/test_deployment_per_model_commit.py` — placement de toutes
  les figurines, ancre = figurine d'index minimal (l'invariant dont `build_rigid_plan` dépend),
  légalité du plan committé, déterminisme + lecture pure du helper, invalidation de la mémo sur
  tampon périmé, équivalence de l'empreinte pré-calculée aux deux parités. Les 8 premiers sont
  rouges sur l'ancien code. Suite `tests/unit` : mêmes échecs préexistants qu'avant le fix
  (baseline vérifiée par `git stash`), aucune régression.
  **Dette assumée** : `deploy_unit` porte désormais DEUX modèles de validation — la mono-ancre
  héritée de T5 (empreinte du socle de l'unité ⊆ pool, miroir du masque) et la par-figurine.
  La première n'a plus de sens géométrique strict une fois le placement fait par figurine ; elle
  ne survit que parce que le masque T5 s'y aligne. **Planifié en T7** (section 5), déclencheur
  « le training tourne » — le fondement règles y est établi par lecture des PDF (la mise en place
  est PAR FIGURINE, aucun socle à l'ancre dans les règles).
  ⚠️ **Écarté après analyse — deux fausses bonnes idées** :
  - *Filtrer le pool entier par `deployment_build_squad_destinations_pool`*
    ([deployment_handlers.py:552](../../engine/phase_handlers/deployment_handlers.py#L552)) :
    INSUFFISANT (ne teste que zone-fit du bloc rigide — pas les murs par-figurine, pas le
    chevauchement d'unités déployées, pas §13.06, tous exigés par `deployment_preview_plan`) et
    SURDIMENSIONNÉ (~16 000 hexes validés pour 5 slots-stratégies utilisés).
  - *Valider les ancres DANS le masque* : impossible sans le réécrire — le masque n'active que
    5 slots (`mask[4+i]`) et ne connaît PAS les ancres, qui sont calculées au décodage par
    `_select_deployment_hex_for_action`. C'est donc le décodeur qui doit filtrer (point 3).
  ⚠️ **Comportement non évident vérifié et verrouillé par test** : dans
  `generate_compact_formation`, l'ancre ORIENTE le placement mais ne le CONTRAINT pas (sa
  spirale retient la 1re case légale) — une ancre hors zone place l'escouade dans la zone la
  plus proche au lieu d'échouer. Le refus d'une ancre hors zone reste donc porté par la
  validation mono-ancre de `deploy_unit` (`deploy_footprint_outside_zone`), à ne pas retirer.
  ⚠️ **Chemin tutoriel PvP non validé runtime** : `config/tutorial/scenario_etape*.json` ne se
  charge plus du tout (`wall_ref` legacy sans `board_ref` →
  `ValueError` dans `_resolve_board_dir`, game_state ~L1664) — dette T4 indépendante de ce fix
  (la migration de banque n'a pas couvert `config/tutorial/`). Le chemin a été validé par son
  équivalent fonctionnel (commit à ancre imposée, ci-dessus).

- **T6-g — Le pool BFS du move valide l'ANCRE, pas le BLOC translaté — ✅ FAIT (2026-07-19)**
  **Réalisé** : `erode_move_pool_by_squad_block` (shared_utils), appelée par
  `build_squad_move_cell_map` sur les `costs` du BFS, AVANT `project_pool_to_grid` — donc la
  grille égocentrique, le masque et le décodage lisent tous le pool érodé (la source unique
  reste unique). Le bloc est réduit à ses offsets CUBE relatifs à l'ancre (invariants depuis
  T6-h), **groupés par NIVEAU** (une figurine ne collisionne qu'avec les figs d'un autre squad
  au même étage — miroir exact de `validate_move_plan`), et les cellules interdites sont
  pré-agrégées par niveau en un seul set (murs ∪ occupation ∪ ER ennemie) → un test
  d'appartenance par figurine et par candidate, pas d'appel à `validate_move_plan` dans la
  boucle. Invariants non érodés car démontrés invariants par translation : budget per-model et
  cohésion (cf. §0). Aucune règle de jeu modifiée : l'érosion ne fait que RETIRER du masque des
  destinations que l'exécution refusait déjà.
  **Validation** : +6 tests dédiés (mur/autre escouade/ER sous une SŒUR alors que l'ANCRE est
  légale, débordement de plateau, non-sur-filtrage, court-circuit mono-figurine) ; run x5_debug
  8 workers 10/10 épisodes et run mono-env x1_debug, **zéro** « incohérence masque/exécution ».
  ⚠️ **Ce « zéro » ne vaut que pour les 10 épisodes mesurés** : une AUTRE cause de la même
  classe a tué un run de 250 épisodes le 2026-07-20 — cf. **§0.11** (collision intra-plan
  aveugle au niveau). L'érosion de T6-g reste correcte ; c'était le prédicat de collision
  qu'elle ne teste pas — à raison — qui était faux.
  Historique de la rupture ci-dessous.
  **Repro** (moteur nu, `training_benchmark`, premier index du masque) : dès que les figurines
  sont réellement placées, le crash T6-f se déplace au squad suivant —
  `ValueError: execute_squad_move a échoué : squad=3 type=normal dest=(195,163) depuis
  (197,168) — incohérence masque/exécution`.
  **Root cause (tracée entrée par entrée sur le plan rigide)** : `build_squad_move_cell_map`
  ([shared_utils.py:7394](../../engine/phase_handlers/shared_utils.py#L7394)) construit le pool
  via `movement_build_valid_destinations_pool`, qui raisonne sur l'**ancre** de l'escouade, puis
  le projette sur la grille égocentrique. Mais l'exécution passe par `build_rigid_plan`, qui
  **translate TOUTES les figurines** du même vecteur — sans qu'aucune contrainte n'ait été
  testée sur elles. Sur le plan rejeté : 3 figurines (`3#4`, `3#5`, `3#6`) atterrissent sur une
  autre escouade et 1 (`3#17`) sur un mur, alors que l'ancre `3#0` est parfaitement légale.
  `validate_move_plan` rejette donc une destination que le masque avait offerte.
  **Ce n'est PAS une régression de T6-f** : le mismatch est structurel (pool d'ancre vs
  exécution de bloc) et préexistait ; il était simplement masqué par T6-f, qui faisait échouer
  le move plus tôt, pour une autre raison.
  **Modèle retenu (décision utilisateur 2026-07-19) : érosion morphologique** — éroder la grille
  des cellules acceptables par l'empreinte COMBINÉE de l'escouade, puis lire le résultat à
  l'ancre. Exact (les autres unités sont fixes pendant le move de l'escouade), vectorisable, et
  le code a déjà ce précédent exact dans `_get_valid_deployment_hexes` (érosion par empreinte,
  DEUX jeux d'offsets selon la parité de colonne). Écarté : `validate_move_plan` en post-filtre
  des candidates — exact aussi mais Python pur, |pool| × |figurines| par step (~2800 × 20).
  ⚠️ **Ordre imposé par T6-h** : l'érosion suppose des offsets de bloc INVARIANTS par
  translation. C'est faux aujourd'hui (cf. T6-h) — corriger la translation AVANT d'éroder,
  sinon l'érosion valide une forme que l'exécution ne reproduit pas.
  **À ne pas oublier dans le filtre** : bornes, murs, occupation des autres escouades PAR NIVEAU
  et `forbid_enemy_er` (toutes des contraintes de cellule, donc érodables). La cohésion et le
  budget per-model deviennent invariants une fois T6-h corrigé (translation réellement rigide),
  mais `validate_move_plan` mesure le budget par `calculate_hex_distance` depuis chaque origine :
  le vérifier plutôt que le supposer.

- **T6-h — `build_rigid_plan` : la translation « rigide » DÉFORME le bloc (bug de parité hex) —
  ✅ FAIT (2026-07-19)**
  **Réalisé** : translation en coords CUBE (`offset_to_cube` / `cube_to_offset`) dans
  `build_rigid_plan`. **L'audit « autres consommateurs de translation de bloc » demandé par le
  plan a trouvé DEUX autres sites portant le même bug**, tous deux alignés :
  - `translate_squad_to_destination` (shared_utils) — **le plus grave** : c'est l'ÉCRIVAIN du
    commit, partagé par move / charge / fight / pile-in / consolidation. Corriger
    `build_rigid_plan` seul aurait fait committer une formation DIFFÉRENTE de celle que
    `validate_move_plan` venait d'accepter (plan validé en cube, commit appliqué en offset) —
    soit exactement la classe de bug « validé ≠ exécuté » que T6-g élimine ;
  - `preview_hidden_models_after_move` (shooting_handlers) — simulation read-only du statut
    « caché » (13.09) après move, dont la docstring se réclame explicitement du miroir de
    `translate_squad_to_destination` : à `dx` impair, le preview affichait un bloc déformé,
    donc un statut caché faux (impact PvP direct, pas seulement gym).
  **Validation** : +10 tests paramétrés sur `dx` pair ET impair (distances internes préservées,
  ancre exactement sur la destination) — **rouges sur le code d'avant** aux seules parités
  impaires, verts après. Historique de la rupture ci-dessous.
  **Mesure** (2 figurines voisines, translation du bloc en offset puis distance interne
  recalculée par `calculate_hex_distance`) :
  `dx` pair → écart 0 (forme préservée) ; **`dx` impair → écart 1** : deux figurines à distance
  2 se retrouvent à distance 1.
  **Cause** : `build_rigid_plan`
  ([shared_utils.py:3243](../../engine/phase_handlers/shared_utils.py#L3243)) applique
  `new_col = col + dx, new_row = row + dy` en coordonnées OFFSET. En grille hexagonale offset,
  une translation à `dx` impair change la parité de colonne de chaque figurine et n'est donc PAS
  une translation hexagonale — la formation se déforme.
  **Le projet connaît déjà ce piège et l'évite ailleurs** :
  `deployment_build_squad_destinations_pool`
  ([deployment_handlers.py:552](../../engine/phase_handlers/deployment_handlers.py#L552)) passe
  explicitement par les coords CUBE, docstring « La translation rigide passe par les coords cube
  (pas de bug de parité) ». `build_rigid_plan` n'a pas reçu ce traitement.
  **Conséquences** : cohésion et collisions intra-plan faussées (deux figurines peuvent se
  télescoper alors que le bloc d'origine était valide), distances per-model non uniformes, et
  toute optimisation supposant des offsets constants (dont l'érosion de T6-g) invalide.
  **Fix** : translater en cube (`offset_to_cube` / `cube_to_offset`), miroir du helper de
  déploiement. Vérifier au passage les autres consommateurs de translation de bloc.
  ⚠️ **Distinct de T6-g** : le crash T6-g mesuré avait `dx = -2` (pair), donc sans déformation —
  les deux bugs sont indépendants et cumulatifs.

**T6.2 — métriques TensorBoard : RÉSOLU, la mémoire projet était périmée.** Inspection directe
des `events.out.tfevents.*` (EventAccumulator) sur training neuf : `0_critical/` porte bien les
métriques PPO — `f_loss_mean`, `g_explained_variance`, `h_clip_fraction`, `i_approx_kl`,
`j_entropy_loss`, `m_value_loss_smooth`, **56 points chacune** ; `training_critical/` expose ses
6 tags. Le fix `_dump_with_capture` du 2026-05-22 tient. Nuance non diagnostiquée (sans impact) :
`train/*` et `training_critical/*` n'ont qu'1 point là où `0_critical/*` en a 56 — répartition
entre les deux fichiers d'events (`CoreAgent/` et `x1_debug_CoreAgent_1/`).

**Run T6.1 — « run court complet sans erreur » : DÉMONTRÉ sur les deux chemins.**
- **n_envs=48** : **467/500 épisodes, zéro exception** (`win_rate_overall = 0.296` à l'ép. 467),
  coupé par le `timeout 2400` de l'opérateur — pas par une erreur.
- **mono-env (`--step`, après fixes T6-b)** : **475/500 épisodes, zéro exception**, step.log de
  12 561 lignes, coupé par le `timeout 5400` de l'opérateur.
x1_debug (500 ép.) demande > 40 min à n_envs=48 et > 90 min en mono-env — dimensionner le timeout
en conséquence pour un run réellement complet.

**T6.3 — baseline bots : NON DÉMONTRÉE (données insuffisantes, pas une régression).**
Mesuré sur le run de 467 épisodes (adversaire = GreedyBot randomness=0.15 via BotControlledEnv) :
- `win_rate_100ep` (glissant) ~0.33 au milieu → **0.296** à la fin ; `win_rate_overall` plat
  autour de **0.30** (0.270 → 0.320 → 0.307 → 0.305 → 0.296 par tranches de 100).
- `episode_reward` (moyenne 100 premiers vs 100 derniers) : **-12.53 → -8.33** (progression nette).
Lecture honnête : le reward progresse, le win-rate stagne à ~30 % (l'agent ne bat PAS GreedyBot).
**Mais 467 épisodes sur un budget nominal de 50 000 (`total_episodes_normal` de x1_debug) est du
bruit** — ni preuve de succès ni preuve d'échec. Le critère « win-rate en progression / stabilité
multi-scénarios » exige la phase `x1` réelle + `bot_evaluation` sur holdout (vs RandomBot), pas
`x1_debug` (500 ép.). ⚠️ Ne pas conclure sur ces chiffres.

### ✅ T6-c — RÉSOLU (2026-07-16) : le StepLogger n'avait jamais été migré vers le pipeline squad

**Décision utilisateur : migrer (option a).** Fait. `ai/analyzer.py` tourne désormais de bout en
bout sur un step.log produit par le pipeline squad.

**Root cause réelle — pas « le step logger n'a pas été câblé », mais un CONTRAT MOTEUR VIOLÉ.**
`end_activation(game_state, unit, arg1, ...)` (generic_handlers ~L70-101) définit :
`arg1="ACTION"` → « *Log the action (action already logged by handlers)* » ;
`arg1="WAIT"` → `end_activation` émet lui-même l'action_log ; `arg1="NO"` → rien.
Or `_process_squad_action` appelait `end_activation(..., ACTION, ...)` après un move et une charge
réussis — donc en PROMETTANT que le handler avait journalisé — alors que `execute_squad_move` et
`charge_build_valid_plan` n'émettaient **aucun** `append_action_log` (contrairement au chemin
legacy par-figurine, movement_handlers ~L3701/4107, charge_handlers ~L5597/5877).
**`game_state["action_logs"]` était donc incomplet sur le chemin squad** ; le step.log vide n'en
était qu'un symptôme.

**Solution — réparer le contrat, pas dupliquer 17 sites de journalisation** :
1. **Émission des action_logs manquants** dans `_process_squad_action` (miroir des payloads
   legacy) : `move` (avec `move_type` portant normal/advance/fall_back), `charge`, `charge_fail`,
   **`deploy_unit`** (cf. ci-dessous). `shoot`/`combat`/`hazard`/`wait` en émettaient déjà.
2. **Un point d'accroche UNIQUE** : `_flush_squad_action_logs_to_step_logger` (w40k_core), appelé
   depuis `step()` après le dispatch. Draine `action_logs[curseur:]` → `log_action`, via une table
   `_STEP_LOG_TYPE_MAP` (type moteur → action_type du formateur) et `_build_step_log_details`
   (camelCase moteur → snake_case formateur). No-op complet sans `--step`.
3. **Émission PAR JET** pour `shoot`/`combat` : le moteur agrège les jets d'un groupe (arme,
   cible) dans `shootDetails`, le formateur travaille par attaque → une ligne par jet, via
   `_SHOT_RECORD_FIELD_MAP` (`attackRoll`→`hit_roll`, `strengthRoll`→`wound_roll`,
   `saveSuccess`→`save_result`…). Les 11 champs sont exigés même sur un MISS (présence de la clé) :
   `None` est correct, le formateur ne rend `Wound` que si `hit_result == "HIT"`.
4. **État fight capturé AVANT l'action** (`_pre_action_fight_state`) : le formateur `combat`
   exige `fight_subphase` + les 3 pools d'activation (contrat replay), et l'action les mute.

⚠️ **Rayon PvP : NUL, vérifié.** `execute_squad_move` n'a qu'UN appelant (`_process_squad_action`)
et `_process_squad_action` n'est appelé que depuis `step()`/`_build_observation` = gym.
Le PvP (`services/api_server.py`) passe par `execute_semantic_action` → `_process_semantic_action`.

**Le déploiement n'était PAS journalisé non plus** (`deployment_handlers` : grep
`append_action_log` = 0). Conséquence mesurée et non évidente : `log_episode_start` écrit les
unités non déployées en `(-1,-1)`, et sans log de déploiement l'analyzer n'apprenait JAMAIS leur
position réelle → **49 fausses « collisions »** (contrôle 2.2). Émettre `deploy_unit` les a
résolues d'un coup (49 → 0).

**Bug de règle trouvé DANS l'analyzer** (faux positifs, pas un bug moteur) :
`_track_action_phase_accuracy` (analyzer.py ~L835) attendait `"advance": "SHOOT"`. **Faux** :
PDF projet « 09 Movement phase.pdf », règle **09.02 MOVE UNITS > Select Move Type** liste
l'*Advance move* parmi les types de mouvement de la **phase de Mouvement** (avec Normal move,
Fall-back move, Remain stationary). Le moteur le résout bien en phase MOVE. Corrigé en
`"advance": "MOVE"` → **105 faux positifs supprimés**.

**Résultat sur le VRAI `train.py --agent CoreAgent --scenario bot --new --training-config
x1_debug --step`** (56 épisodes, **3452 lignes d'action**, **0 erreur avalée**) — `ai/analyzer.py`
tourne de bout en bout et rendait **14 erreurs** ; après le traitement du faux positif LoS
(2026-07-16) il n'en reste **2**, le seul ❌ étant l'artefact 2.6 ci-dessous :
- ✅ 1.1 move : 0 ; ✅ 1.3 charge : 0 ; ✅ 1.4 fight : 0 ; ✅ 1.5 wrong phase : 0 ;
  ✅ 1.6 double-activation : 0 ; ✅ 2.1 dead units : 0 ; ✅ **2.2 positions : 0** ;
  ✅ 2.3 DMG : 0 ; ✅ 2.5 episode ending : 0 ; ✅ 2.7 core issue : 0.
- ✅ **1.2 erreurs en phase de shooting : 0** — **TRANCHÉ ET TRAITÉ le 2026-07-16**, était 12
  (`shoot_through_wall = 6` + `shoot_invalid.no_los = 6` = les MÊMES 6 tirs, incrémentés dans la
  MÊME branche, shoot_handler.py ~L165). **Verdict : faux positifs de l'analyzer, aucun bug
  moteur, backend non modifié.** Détail complet, preuve et options rejetées :
  `A_faire/analyzer_los_ancre_vs_perfig.md`.
  **Cause structurelle confirmée — le CONTRÔLEUR est périmé, pas le moteur** (et il n'y a
  AUCUNE divergence training/PvP : le moteur est unique et pilote les deux) :
  - L'analyzer n'a PAS sa propre LoS — il appelle bien `engine.hex_utils.compute_los_state`
    (analyzer.py ~L602, docstring : « same algorithm as the game engine »). **Mais il l'appelle
    ANCRE-À-ANCRE** : `has_line_of_sight(shooter_col, shooter_row, target_col, target_row,
    wall_hexes)` — un point contre un point.
  - Le moteur, lui, fait `_attacker_model_can_reach_squad` (shared_utils ~L4243) : LoS
    **PER-FIGURINE**, origine = **empreinte COMPLÈTE du socle tireur** (« pas son seul centre »),
    distance bord-à-bord, via `_compute_visibility_with_obscuring` (murs denses + obscurcissant,
    13.10). **Son propre commentaire décrit exactement ce faux positif** : « une grosse base dont
    le centre est masqué par un terrain (mais dont un bord voit la cible) était grisée à tort ».
  - → L'analyzer refait le test centre-à-centre que le moteur a DÉLIBÉRÉMENT abandonné. Même
    dette que R5 / le step logger / les objectifs de l'analyzer : outil resté sur le modèle
    pré-squad « une unité = un point ».
  - Second suspect : `except Exception: return False` (analyzer.py ~L630) — **écarté par mesure**
    (aucune exception levée : `compute_los_state` brut rend le même `False`). Supprimé quand même
    (CLAUDE.md). Troisième suspect « murs incomplets » écarté aussi : ligne `Walls:` complète.
  - **Confirmé sur un tir précis** (E7 T3 P1 `Unit 4(215,155) SHOT Unit 104(116,66)`) : l'ancre
    rend `can_see=False`, mais **3 des 19 cellules** de l'empreinte du socle (`round/6`) voient la
    cible. Règle 06.01 (PDF lu) : « from **any part** of that model to **any part** of the model
    being observed » → l'ancre-à-ancre est plus restrictif que la règle.
  - **Correction (option c)** : le contrôle est SUPPRIMÉ de l'analyzer et la vérification
    DÉPLACÉE dans `tests/unit/engine/test_shoot_los_perfig_parity.py`, où `game_state` existe.
    Le réparer sur place était impossible : les primitives moteur exigent `game_state`
    (empreintes, obscurcissant 13.10, LoS 3D) que step.log ne porte pas ; et logger le verdict du
    moteur serait circulaire (le tir est déjà gaté par `_attacker_model_can_reach_squad`).
  ⚠️ **La journalisation n'est fidèle que pour les JETS** (`Hit 6(3+) - Wound 5(5+) - Save 1(4+) -
  Dmg:2HP` ; un MISS ne rend que `Hit 2(3+)`). **Ses COORDONNÉES sont fausses** :
  `_emit_squad_shoot_log` (shared_utils ~L5758) loggue l'ancre d'ESCOUADE, pas la figurine qui
  tire — dette V11 « une unité = un point » non traitée, chantier séparé.
- ❌ 2.6 « Sample missing (2/5) : charge, fight » = artefact du run (agent frais : ne charge ni
  ne combat jamais sur 56 épisodes), PAS un défaut.

**C'est la valeur du chantier T6-c** : l'outil de validation du projet fonctionne enfin, et il a
IMMÉDIATEMENT trouvé une divergence LoS analyzer↔moteur qu'aucun test unitaire ne voyait.

**Résultat sur un step.log de moteur nu (3 épisodes, actions aléatoires)** — `157 erreurs → 52 → 3` :
- ✅ 1.1/1.2/1.3/1.4 erreurs par phase : 0 ; ✅ 1.5 wrong phase : **0** (était 105) ;
  ✅ 1.6 double-activation : 0 ; ✅ 2.1 dead units : 0 ; ✅ 2.2 positions incohérentes : **0**
  (était 49) ; ✅ 2.3 DMG issues : 0 ; ✅ 2.5 episode ending : 0 ; ✅ 2.7 core issue : 0.
- ❌ 2.6 « Sample missing (3/5) : shoot, charge, fight » = **artefact du run** (actions aléatoires
  non dirigées : ni tir ni charge ni combat), PAS un défaut. Le scénario de mêlée garantie produit
  bien `FOUGHT`/`FAILED CHARGE` (vérifié : 40 lignes `FOUGHT` avec détail par jet
  « Hit 3(3+) - Wound 5(2+) - Save 2(7+) - Dmg:1HP »), et zéro erreur avalée.

⚠️ **Piège vérifié** : `StepLogger.log_action` et `log_episode_start` AVALENT toute exception
(`except Exception: print("⚠️ ... logging error")`, step_logger.py ~L254). Un champ manquant
produit une ligne SILENCIEUSEMENT absente, pas un crash. **Contrôler `grep -c "logging error"`
après tout changement de mapping** — c'est ainsi qu'ont été trouvés les manques `hit_roll` puis
`deploy … position data`.

Plan d'origine (résolu ci-dessus) :

**Fait vérifié (statique)** : `_process_squad_action` (w40k_core.py, def ~L4750, plage ~4750-5146)
— le chemin VIF du pipeline squad en gym — contient **ZÉRO appel à `step_logger.log_action`**
(grep sur la plage = 0). Son docstring l'annonce : « Dispatch sémantique squad vers helpers squad.
**Remplace `_process_semantic_action`** ». Or les **17** sites `log_action` vivent dans
`_process_semantic_action` (def ~L2725) et ses handlers, atteignables seulement via
`execute_semantic_action` (~L2090) et `execute_ai_turn` (~L2114) = chemins PvE/legacy.

**Preuve empirique (run mono-env réel, 475 épisodes, après les fixes T6-b)** :
- `Steps=0` sur **474/475** épisodes (`episode_step_count` n'est jamais incrémenté) ;
- **0 ligne** correspondant à `Unit N (MOVED|SHOT|CHARGED|FOUGHT|WAITED)` sur 12 561 lignes ;
- ~26 lignes/épisode = les seuls en-têtes (`Scenario`, `Rosters`, `Walls`, `Objectives`, `Rules`,
  `Board`) + `EPISODE END` + `OBJECTIVE CONTROL`.

⚠️ **Nuance vérifiée (à ne pas sur-simplifier)** : `log_action` n'est pas TOTALEMENT inatteignable
depuis le gym — **3 épisodes sur 475** portent `Actions=9|9|18`. Ce sont exclusivement des
`rule_choice` (« Unit 105 chose [AGGRESSION IMPERATIVE] »), émis par le site w40k_core ~L2416-2425
dont le commentaire dit explicitement « select_rule_choice **bypasses normal step logger flow** ».
C'est donc le seul `log_action` atteignable — précisément parce qu'il court-circuite le flux
normal — et il n'incrémente pas `step_count`. **Toutes les actions de JEU (move/shoot/charge/
fight/wait), celles à `step_increment=True` dont l'analyzer a besoin, ne sont jamais journalisées.**

**Conséquence** : `ai/analyzer.py` échoue en `Missing objective control snapshot at episode end`
(analyzer_core.py ~L250) — il construit ses snapshots de contrôle d'objectif à chaque action
`step_inc` (~L861-907), et il n'y en a aucune. Aucun réglage de l'analyzer ne peut compenser :
**la matière première n'est pas produite**.

**Même famille que R5 et `game_replay_logger`** (condamné en T2 pour exactement ce motif : code
resté sur l'architecture pré-squad). La migration RL de fin mai a laissé derrière elle TOUTE la
chaîne d'observabilité, pas seulement les wrappers.

**À statuer (utilisateur)** : (a) migrer `log_action` vers `_process_squad_action` (chemin partagé
PvP/gym → impacte aussi la journalisation PvP, à cadrer) ; (b) condamner explicitement `--step`
sur le pipeline squad, comme `game_replay_logger.log_action` (NotImplementedError), et retirer
« analyzer + replay » du critère T6 ; (c) laisser en l'état. **Interdit : laisser `--step`
annoncer « Step logging enabled » en ne produisant que des en-têtes.**
Cadrage PvP si (a) : les 17 sites legacy sont tous gardés par `if self.step_logger`, et le
logger n'est branché QUE par train.py → instrumenter `_process_squad_action` avec la même
garde est neutre PvP par construction. Granularité : l'action squad (move dir, shoot slot,
charge, fight, wait) — ce que l'analyzer consomme.

**Décisions annexes actées (2026-07-16)** :
1. **Modèles de validation** : les runs de validation/baseline écrivent leurs artefacts sous
   `ai/models/_validation/<run_id>/` — JAMAIS dans `ai/models/<agent_key>/` (zips protégés,
   CLAUDE.md). Règle permanente : plus aucun arbitrage ponctuel `--new` vs zips à chaque run.
2. **Raccrochés au chantier (a)** (même fichier, même passe) : le 3e site `--step` encore non
   gardé dans train.py (les 3 sites impriment le même message — ajouter au passage un
   identifiant de site dans le log), et la ligne `OBJECTIVE CONTROL:` de step.log au format
   `Obj<id_string>` que personne ne lit (l'aligner sur le format attendu `Obj(\d+)` du parser,
   ou la supprimer — pas de statu quo).

### Corrections T6 faites en chemin vers l'analyzer (toutes vérifiées)

- **Parser d'armes — bug SILENCIEUX sur les apostrophes** (`engine/weapons/parser.py`, motif
  `["\']([^"\']+)["\']`) : ouvrait sur `"` ou `'`, capturait tout sauf CES DEUX caractères, fermait
  sur l'un ou l'autre. Une apostrophe DANS une chaîne à guillemets doubles cassait la lecture —
  or les noms Orks en sont pleins. `display_name: "Dok's Tools"` → capturait **`"Dok"`** (tronqué,
  SANS erreur) ; `"'eadbanger'"`, `"'urty Syringe"`, `"'Waaagh! Staff"` → **aucun match**, la clé
  `display_name` n'était jamais posée et l'absence explosait ailleurs
  (`require_key(weapon, "display_name")`, analyzer_config.py:150). **Impacte aussi le PvP.**
  → constante `_TS_QUOTED_STRING = r'(["\'])((?:(?!\1).)*)\1'` (backréférence : fermeture sur le
  MÊME guillemet), appliquée à `display_name`, `COMBI_WEAPON` et `WEAPON_RULES`. Strictement
  identique pour tout nom sans apostrophe. Résultat : registre à **176 unités, 0 erreur de
  parsing** (contre 107 erreurs).
- **Donnée corrigée en conséquence** : `wolf_guard_weapon` déclarait `WEAPON_RULES: [""]`
  (spaceMarine/armory.ts:142) — une chaîne VIDE que l'ancien motif (`+`, 1 car. min.) avalait
  silencieusement. Le motif corrigé la lit fidèlement → règle vide rejetée. `[""]` → `[]` :
  comportement inchangé (l'ancien parser produisait déjà `[]`), la donnée dit enfin ce que le code
  comprenait. Occurrence unique dans tout le projet.
- **`_resolve_scenario_path` (analyzer.py) résolvait vers l'ARCHIVE** : T4 a déposé la banque
  pré-V11 sous `scenarios/_archive_pre_v11/` — donc DANS l'arbre parcouru par `os.walk` →
  `ValueError: Ambiguous scenario path for 'scenario_training_bot-29'` (l'archivé garde ses clés
  legacy, sa signature d'objectifs diffère du migré homonyme). → la marche élague les dossiers
  `_archive*`. Aligné sur la convention du projet : `get_scenario_list_for_phase`
  (training_utils.py:308) travaille sur une liste blanche explicite (training/, holdout_regular/,
  holdout_hard/) et n'a jamais eu ce problème.
- **`_get_objective_name_to_id_map` (analyzer.py) était resté sur le contrat LEGACY** : lisait
  `objectives` inline / `objectives_ref` → `config/board/<board>/objectives/` (dossier supprimé).
  T3 avait migré train.py et bot_evaluation.py, **pas analyzer.py**. → migrée vers la source
  unique terrain (areas `"objective": true`, miroir de `resolved_scenario_objectives` de
  game_state.py), via un nouveau `_resolve_terrain_path_for_scenario` (miroir du resolver
  `board_ref` de T4). Nuance : les ids terrain sont des STRINGS (`rect_b_nw_OK`) alors que
  l'analyzer indexe par int → id positionnel (1..N, ordre du fichier terrain = stable) ; seul le
  NOM sert d'appariement, et c'est bien le `name` de l'area que le StepLogger écrit.
  ⚠️ **Reste incohérent** (non corrigé, car sous le bloqueur T6-c) : la ligne `OBJECTIVE CONTROL:`
  de step.log écrit `Obj<id_string>` (`Objrect_b_nw_OK`) alors que le parser attend `Obj(\d+)`
  (analyzer_core.py ~L112) — **trois formats coexistent** (nom / `Obj`+string / `Obj`+int).

**✅ Bloqueur résolu (historique) — `ai/analyzer.py` ne démarrait pas** :
`ConfigurationError: Required key 'RNG' is missing` (`analyzer_config.py:167`) —
`load_analyzer_config` itère TOUT `unit_registry.units`, donc 4 armes de TIR de l'armory Ork sans
clé `RNG` bloquaient l'analyzer QUEL QUE SOIT le scénario, même sans Ork. Renseignées par
l'utilisateur (`RNG: 24`) le 2026-07-16 : `kombi_rokkit`, `kombi_shoota`, `rokkit_launcha`,
`rokkit_launcha_heavy`. A permis de découvrir les blocages suivants (parser d'apostrophes,
archive T4, contrat objectifs legacy) puis le vrai mur structurel T6-c.

Plan d'origine :
1. `python3 ai/train.py --agent CoreAgent --scenario bot --new --training-config x1_debug --step`
   → run court complet sans erreur ; puis `ai/analyzer.py` sur les résultats + replay.
2. Vérifier les métriques TensorBoard (cf. mémoire projet : métriques PPO manquantes dans
   0_critical — diagnostiquer si toujours le cas).
3. Baseline bots : l'agent frais doit apprendre à battre RandomBot/GreedyBot sur quelques
   scénarios avant tout tuning (critère de succès : stabilité multi-scénarios, pas un pic).
4. Hygiène (ne bloque pas) : corriger la `justification` (31→41) de la config ; mettre à jour
   AI_OBSERVATION.md/AI_TRAINING.md (pipeline squad 108) ; statuer sur `ai/target_selector.py`
   (mort → suppression à valider utilisateur) ; marquer les configs snapshot obs 355 comme
   archives.

**Hygiène T6.4 — état réalisé (2026-07-16)** :
- ✅ `justification` corrigée dans les **5 phases** : `action_space_size=41 (26 micro [6 move +
  6 advance + 6 fall back + 1 wait + 5 shoot + 1 charge + 1 fight] + 15 macro)`. Décompte vérifié
  contre macro_intents.py.
- ✅ **AI_OBSERVATION.md / AI_TRAINING.md** : bandeau de tête « ne décrit PAS le pipeline actif »
  + table de correspondance (obs 108 / action 41, layout squad, routage `_build_observation` par
  `obs_size`). Les corps de doc (355/357) sont conservés : le pipeline mono-fig reste atteignable
  via `obs_size=357`. `obs_size: 355` de l'exemple de config AI_TRAINING.md corrigé en 108.
- ✅ **Snapshots obs 355 marqués archives** : clé `_ARCHIVE` en tête de
  `BEST_CoreAgent_training_config.json`, `CoreAgent_training_config_BEST_X1.json`,
  `CoreAgent_training_config_save_avant_X10.json`. Sûr : aucun code ne les charge
  (`load_agent_training_config` résout `<AGENT>_training_config.json`) — vérifié par grep.
  Contenu strictement préservé (comparaison JSON parsée vs `git show HEAD:` = identique).
- ✅ **Réserve T2 purgée** : `multi_agent_trainer.py` ~L996-1040 — monkeypatch
  `controller.execute_gym_action` portant le dernier layout à 8 actions (`action // 8`,
  `action % 8`). Code mort ET cassé : `W40KEngine` n'a aucun attribut `controller` (grep vide) et
  le patch appelait 6 méthodes inexistantes (`_get_gym_eligible_units`,
  `_convert_gym_action_to_mirror`, `_log_gym_action`…). Supprimé.
- ✅ **Réserve T3/T4 purgée** : paramètre `objectives_ref` de `_materialize_scenario_with_refs`
  (branche morte qui aurait émis une clé REJETÉE par le moteur — game_state ~L329). ⚠️ La purge
  avait laissé un `NameError` latent (`hash_payload` référençait encore la variable) — attrapé par
  le test `test_materialize_scenario_with_refs_wall_override_emits_no_legacy_key`, corrigé.
- ✅ **Réserve T4 close** : `sweep_scenario_bank_v11.py` a désormais son bootstrap `sys.path`
  (L19) ; `migrate_scenario_bank_v11.py` n'a **aucun import projet** → n'en a pas besoin.
- ✅ **`ai/target_selector.py` SUPPRIMÉ** (validation utilisateur obtenue le 2026-07-16), avec son
  test `tests/unit/ai/test_target_selector.py`. Mort confirmé par grep exhaustif avant suppression :
  aucun importeur hors le module lui-même et son propre test (-9 tests collectés).
- ⚠️ **Contradiction non résolue (décision produit requise)** : T6.1 impose `--new`, qui écrit
  `ai/models/CoreAgent/model_CoreAgent.zip` — or CLAUDE.md (L51-53, L215) et la décision de design
  n°1 interdisent d'écraser les zips protégés, et `ai/models/` est **gitignoré** (aucune
  récupération git). Écrasement autorisé ponctuellement par l'utilisateur (2026-07-16 : « le modèle
  est obsolète » — effectivement pré-squad, obs 355/357 incompatible avec obs 108). Voie propre à
  acter : chemin de sortie dédié pour les runs de validation (ex. `ai/models/_validation/<run_id>/`).

**Tests** :
- **+11** — `tests/unit/ai/test_train_wall_ref_contract.py` : `_load_scenario_wall_ref`
  (absent→None ; présent→strict ; présent-mais-invalide→erreur explicite, 5 cas paramétrés),
  `_apply_wall_ref_weighting` sur scénario terrain-only (repro de T6-a),
  `_materialize_scenario_with_refs` (param `objectives_ref` purgé, aucune clé legacy émise,
  passthrough sans override).
- **-9** — suppression de `test_target_selector.py` (module mort supprimé, cf. hygiène).
- **+2 nets** — `tests/unit/ai/test_analyzer_utils.py` : les 2 tests encodant le contrat LEGACY
  (`objectives` inline / `objectives_ref`) ont été MIGRÉS vers le contrat terrain — pas
  neutralisés : c'est LE comportement testé qui a changé par décision documentée (T3/T4), seule
  exception admise par §8. Ajout de 2 non-régressions : terrain sans area `"objective": true`
  → erreur explicite (piège T4 « liste vide en silence ») ; l'archive `_archive_pre_v11` de T4 ne
  masque pas un scénario vif.

**Bilan suite `tests/unit/` : VERTE, 1259 collectés** (1255 baseline T5 + 11 − 9 + 2), zéro échec,
zéro erreur. Smoke `scripts/smoke_t5_bare.py` rejoué après TOUS les fixes T6 :
`(A) invariant/terminaison=OK | (B) mêlée+Carnifex=OK`, `melee_kills_total=5`,
`carnifex_charge_any=True` — aucune régression moteur.

### T7 — Unification de la validation de déploiement — ⏸️ EN ATTENTE (déclencheur explicite)

**Déclencheur : le training tourne** (donc T6-h puis T6-g livrés, cf. §0). **Ne PAS commencer
avant** — voir « pourquoi pas maintenant ».

**Le problème.** Depuis T6-f, `deploy_unit` enchaîne DEUX contrôles :
1. **mono-ancre** (hérité de T5) : l'empreinte d'UN socle posé à l'ancre ⊆ zone, hors mur,
   clearance — miroir exact de `_get_valid_deployment_hexes` ;
2. **par-figurine** (T6-f) : la formation entière validée par `deployment_preview_plan`.

Le contrôle 1 teste **un objet qui n'existe plus** : l'unité n'occupe pas un socle à l'ancre,
elle occupe N socles répartis ; l'ancre est un point de référence, pas une figurine.

**Fondement règles (PDF lus, pas supposés)** :
- « 18 Transports.pdf » : « Set up **each model** in your unit wholly within the set-up
  distance » → la mise en place est PAR FIGURINE.
- « 24 Core abilities.pdf » : « set up that unit anywhere that is **wholly within** your
  deployment zone » → la contrainte porte sur l'unité ENTIÈRE, c.-à-d. toutes ses figurines.

Aucune règle ne mentionne un socle à l'ancre. Le contrôle 1 refuse donc des placements **légaux
au sens des règles** — typiquement une ancre en bord de zone dont le socle déborde alors que la
formation tiendrait entièrement dedans. Ordre de grandeur mesuré sur le balayage des 16 104
hexes de la zone (T6-f) : 263 refus `outside_zone` + 1 815 `out_of_bounds`, dont une part est
légale au sens 40K.

**Fix visé** : supprimer le contrôle mono-ancre du commit ET du masque, et laisser le décodeur
(`_select_deployment_hex_for_action`, qui valide déjà la formation depuis T6-f) être le SEUL
filtre. Un seul modèle de validation, aligné sur les règles, et l'agent récupère des placements
aujourd'hui interdits.

> 🔴 **CE FIX EST FAUX EN L'ÉTAT — NE PAS L'APPLIQUER (mesuré le 2026-07-20).**
>
> Il repose sur l'idée que le contrôle par-figurine « valide déjà la formation » à l'ancre
> demandée. **C'est faux** : `build_validated_deployment_plan` passe par
> `generate_compact_formation`, dont la spirale BFS retient la 1ʳᵉ case **légale** — l'ancre
> **oriente** le placement, elle ne le **contraint** pas.
>
> **Mesure** (balayage des 16 104 hexes de zone × 5 unités = 80 520 ancres, scénario
> d'entraînement réel). Sur les ancres refusées par le mono-ancre mais pour lesquelles un plan
> existe, **aucune figurine n'est posée à l'ancre demandée** :
> ```
> unit 3  ancre=(2,299)  mono=outside_zone   fig_à_l_ancre=False  plan=[(24,293)]
> unit 3  ancre=(3,298)  mono=outside_zone   fig_à_l_ancre=False  plan=[(24,293)]
> unit 3  ancre=(4,298)  mono=outside_zone   fig_à_l_ancre=False  plan=[(24,293)]
> unit 1  ancre=(2,299)  mono=out_of_bounds  fig_à_l_ancre=False  plan=[(8,297),(14,293),…]
> ```
> Quatre ancres distinctes → **le même plan**, à 22 colonnes de là.
>
> ⚠️ **Le chiffre « 14 859 ancres refusées à tort (18,5 %) », produit pendant cette session, est
> RETIRÉ.** Il mesure « il existe un placement légal quelque part », pas « ce placement-ci est
> légal ». Ne pas le recycler.
>
> **Supprimer le contrôle 1 ne débloquerait donc pas des placements légaux : ça rendrait 18,5 %
> de l'espace d'action non déterministe** — l'agent désigne une ancre et l'unité atterrit
> ailleurs. C'est la classe de bug « validé ≠ exécuté » que T6-g/T6-h ont éliminée.
>
> **Le code l'écrit déjà deux fois**, et l'audit T7 ne les avait pas lus :
> [deployment_handlers.py:904-908](../../engine/phase_handlers/deployment_handlers.py#L904)
> (« ne pas la retirer en croyant ce helper suffisant ») et le test dédié
> `test_anchor_is_a_suggestion_not_a_constraint`
> ([test_deployment_per_model_commit.py:290](../../tests/unit/engine/test_deployment_per_model_commit.py#L290)).
>
> **Le fond de T7 reste valide** : le contrôle 1 teste un socle unique à l'ancre, objet qui
> n'existe plus, et refuse de vraies formations légales en bord de zone. Mais le fix ne peut pas
> être « supprimer le contrôle 1 ». Il faut d'ABORD rendre le plan **contraint par l'ancre**
> (échec si la formation ne tient pas autour d'elle, au lieu de glisser), ce qui **inverse** le
> test ci-dessus — donc une **décision de design**, pas une correction de bug, à arbitrer
> explicitement. Périmètre restreint : `build_validated_deployment_plan` n'est appelé que par le
> décodeur gym ([action_decoder.py:1983](../../engine/action_decoder.py#L1983)) et le commit
> `deploy_unit` ; le flux PvP par escouade passe par
> [:859](../../engine/phase_handlers/deployment_handlers.py#L859) et n'est PAS touché.

**Pourquoi pas maintenant (raisonnement à ne pas re-dérouler)** : ça modifie le masque de
déploiement, donc **l'espace d'action de l'agent** — ça invalide les modèles entraînés et exige
une mesure avant/après. Le faire pendant que le training ne tourne pas ajoute du risque sans
pouvoir l'évaluer. Ordre optimal : **T6-h → T6-g → training qui tourne → T7**, dans sa propre
tranche, avec avant/après mesuré (win-rate et taux de refus de déploiement).

**Critère d'acceptation** : un seul prédicat de validation de déploiement dans le code (grep :
plus de `compute_candidate_footprint` dans `deploy_unit`) ; un placement légal au sens 40K mais
refusé aujourd'hui (ancre en bord de zone, formation entièrement dedans) est ACCEPTÉ — test
dédié, rouge avant le fix ; suite verte hors échecs préexistants ; PvP non régressé (le drag
mono-socle et l'auto-déploiement passent par le même commit).

### Phase B (après T6 ET Phase A' — section 9 — validés) — Observation niveaux
Spec à figer à ce moment-là, principes déjà actés :
- Ajouter aux 7 features par-figurine un `level` normalisé (source : champ `level` de la
  figurine, posé game_state.py ~L162) et aux 9 features par slot ennemi le niveau de l'ancre ;
  exposer aussi un signal de coût de descente pour l'activation courante
  (`squad_descent_penalty_subhex`, movement_handlers.py:276). Toute modif de layout change
  `obs_size` (config + constantes `SQUAD_*` observation_builder ~L1245-1251) → nouveau modèle from
  scratch, mettre à jour la `justification` en même temps.
- Terrains d'entraînement à étages : SEULEMENT après vérification de l'état du chantier LoS 3D
  (spatial_relations.py:186-189 "câblage incomplet") — sinon l'agent apprendrait sur un tir
  non conforme aux règles.
- Action "monter" (nouveau slot) = Phase C, décision utilisateur explicite requise.

## 6. Critères d'acceptation

| Tranche | Critère (tous vérifiables par commande) |
|---|---|
| T1 | Suite de tests verte ; smoke test moteur nu (annexe A) passe la phase shoot, la phase charge avec Carnifex ET une phase fight avec pertes allouées (chemin FIGHT_CTX) sans exception |
| T2 | Zéro littéral d'action dans ai/. Le grep n'est qu'une HEURISTIQUE (3 versions successives ont toutes eu des trous : `== 11`, `X in valid_actions`, listes, `return 10/12/18`, dicts de poids `{4: 0.50,...}`, `action % 8`, sous-dossiers, + faux positifs légitimes dans train.py) — le critère réel est un AUDIT MANUEL exhaustif des 4 fichiers `evaluation_bots.py`, `env_wrappers.py`, `bot_evaluation.py`, `game_replay_logger.py` : chaque comparaison/émission d'entier d'action passe par une constante de macro_intents. Grep de contrôle : `grep -rnE "(step\([0-9]+\)|WAIT_ACTION|==\s*[0-9]+\b|\b[0-9]+ in valid_actions|return 1[028]\b|% 8)" ai/` avec revue de chaque hit. Smoke test pile complète avance au-delà du premier WAIT forcé |
| T3 | `train.py --step --training-config x1_debug` dépasse la résolution walls/objectives sans FileNotFoundError |
| T4 | Les 61 scénarios se chargent (`W40KEngine(scenario_file=...)` + reset, script de balayage) ; zéro clé legacy ; sort de training_save/ statué |
| T5 | 10 épisodes aléatoires masqués terminés sur ≥3 scénarios × sièges p1/p2 ; zéro masque vide |
| T6 | ⚠️ *(périmée n°3 de §0bis : le blocage par `CC_DMG` est levé — §0.3 porté, run 60/60 en §0.7 — cellule conservée telle quelle, non corrigée)* Run `--new` court complet + analyzer + replay OK ; ~~win-rate vs RandomBot en progression~~ → **critère REMPLACÉ le 2026-07-19, voir section 10.6** (win-rate PAR ROSTER contre un adversaire de holdout jamais vu à l'entraînement + absence de comportement absurde en partie humaine). L'ancien critère référençait un holdout de rosters qui n'existe plus. — ⏳ **PARTIEL (2026-07-16)**. ✅ Run `--new` : déroule sans AUCUNE exception (467/500 ép.). ✅ Suite verte (1293) + smoke `(A)/(B)` OK (mêlée 5 kills, Carnifex charge). ✅ T6-c résolu : `_process_squad_action` journalise, analyzer tourne, `1.2 erreurs shooting = 0`. ✅ **T6-d résolu** : `squad_fight` = sélection FIGHT 12.04, machine V11 déroulée par `_fight_v11_gym_settle` (ordre 12.02→12.04→12.07 respecté, snapshot posé, double activation interdite). ❌ **win-rate NON concluant** : ~30 % vs GreedyBot sur 467 ép. (bruit) — mesuré AVANT T6-d, donc sur un moteur où la mêlée était fausse ; **à re-mesurer** avec phase `x1` + `bot_evaluation` holdout vs RandomBot. ✅ **Le run TOURNE de nouveau depuis le 2026-07-19** : T6-g et T6-h sont livrés (cf. §0), x5_debug 8 workers 10/10 ép. exit 0. ❌ **Le critère T6 reste NON évaluable**, mais pour une raison DIFFÉRENTE et désormais isolée : **§10.4** — sur le chemin single-scenario, P2 joue ALÉATOIRE (`SelfPlayWrapper(frozen_model=None)`, `update_frozen_model` sans appelant). Tout win-rate mesuré aujourd'hui est du bruit. ~~C'est le prochain bloqueur.~~ **✅ §10.4 RÉSOLU le 2026-07-19** (adversaires câblés sur les 3 chemins) ; le critère T6 reste néanmoins NON évalué, désormais bloqué par `CC_DMG` (§0.3) qui plante des épisodes d'évaluation. Voir §0.0 pour l'ordre des travaux. |
| T6-i | ⚠️ *(périmée n°2 de §0bis : le test de non-régression existe : `test_end_of_turn_coherency_03_03.py` — cellule conservée telle quelle, non corrigée)* Une escouade rendue incohérente par des pertes est ramenée en coherency à la fin du tour (03.03), sur les **deux** chemins de fin de Fight, avant le test de limite de tour ; aucune destination du masque de move n'est rejetée pour cause de coherency — ⏳ **PARTIEL (2026-07-19 soir)** : ✅ fix livré et vérifié par run bout-en-bout (8 épisodes plantés → 2, erreur `incohérence masque/exécution` disparue, suite sans régression) ; ❌ **test de non-régression NON écrit** — §8 l'impose, c'est la tâche n°1 de §0.0 |
| T6-f | Après le commit de déploiement, AUCUNE figurine vivante à `(-1,-1)` et ancre `units_cache` = figurine d'index minimal, sur les 3 chemins (gym, ancre imposée tutoriel, drag) — ✅ **FAIT (2026-07-19)** |
| T6-g | Toute cellule offerte par le masque de move est exécutable : sur N épisodes aléatoires, zéro `ValueError` « incohérence masque/exécution » — et un test dédié où une escouade dont le BLOC déborde (mur / autre escouade) ne voit PAS la cellule dans son masque — ✅ **FAIT (2026-07-19)** : `test_move_pool_block_erosion.py` (+6, mur/escouade/ER sous une SŒUR, débordement plateau, non-sur-filtrage, mono-fig) ; runs x5_debug 8 workers (10/10 ép.) et mono-env x1_debug, zéro occurrence |
| T6-h | La translation de bloc préserve les distances internes pour TOUTES les parités de `dx` (test paramétré `dx` pair ET impair) — rouge sur le code actuel — ✅ **FAIT (2026-07-19)** : `test_rigid_plan_translation.py` (+10), rouge avant le fix aux seules parités impaires ; fix étendu à `translate_squad_to_destination` (écrivain du commit) et `preview_hidden_models_after_move` |

## 7. Annexe A — Smoke tests de référence

Deux scripts éprouvés pendant l'audit (à recréer dans `scripts/` ou en scratch ; ne pas
committer les monkeypatches, ils simulent les fixes T1) :

1. **Moteur nu** : `W40KEngine(gym_training_mode=True, scenario_file=<board scenario>)`,
   boucle `reset()` puis `step(choice(flatnonzero(get_action_mask())))` jusqu'à
   terminated/masque vide, 3 seeds. Diagnostic à imprimer si masque vide : phase, tour, joueur,
   pools `*_activation_pool`, états `pending_*`/`fight_*`.
2. **Pile complète** : `Monitor(BotControlledEnv(ActionMasker(engine), GreedyBot(0.15),
   registry, agent_seat_mode="random", global_seed=...))` — miroir exact de
   [train.py:1777-1791](../../ai/train.py#L1777-L1791).

Résultats d'audit (2026-07-14) : moteur nu OK jusqu'au tour 5 avec fixes R4 simulés (deadlock
R7 en fin de partie) ; pile complète bloquée immédiatement par R5 (`step(11)`).
Réserve : seul le décideur tir était patché — le chemin d'allocation de pertes en mêlée
(FIGHT_CTX) n'a pas été prouvé par ce smoke test (cf. R4/T1).

## 8. Tests de non-régression (obligatoires, toutes tranches)

Commande canonique (à lancer après CHAQUE modification, avant de déclarer une tranche finie) :

```bash
source /home/greg/40k/.venv/bin/activate && python3 -m pytest tests/unit/ -q
```

**Baseline vérifiée (2026-07-15)** : 1152 tests collectés dans `tests/unit/` (ai/ engine/
services/ shared/), zéro erreur de collecte, 1152 passed / 2 skipped après T1. Toute exécution
qui passe SOUS ce compte de collectés = suppression de test à justifier explicitement (jamais
en silence). Un test qui devient rouge après une tranche = STOP, corriger la root cause (jamais
adapter le test pour le faire passer, sauf si c'est LE comportement testé qui change par
décision documentée ici).

### 8.1 Principes (non négociables)

- **Un fix = ses tests dans la même tranche** : chaque rupture R1-R7 corrigée s'accompagne de
  tests qui reproduisent la panne d'origine (le test doit échouer sur l'ancien code) ET
  verrouillent le comportement corrigé.
- **Miroir PvP** : pour tout prédicat/chemin bifurquant gym vs PvP, tester LES DEUX branches —
  le test PvP fige le comportement d'avant-fix (neutralité), le test gym fige le fix.
- **Zéro monkeypatch de code mort** : les tests qui patchent `_attack_sequence_rng` disparaissent
  avec lui (P1) ; aucun nouveau test ne doit s'appuyer sur du code sans site d'appel vif.
- **Déterminisme** : tout test utilisant du RNG fixe sa seed ; tout test d'ordre de candidats
  (P2/P3) vérifie la STABILITÉ de l'ordre sur deux appels identiques.
- **Erreurs explicites testées** : chaque garde « erreur explicite, pas de fallback » ajoutée
  par le plan a un test `pytest.raises` vérifiant le TYPE et le MESSAGE (fragment discriminant).
- Les tests règles encodent le PDF du projet (référence 40k_rules citée en docstring), jamais
  le comportement du code mort.

### 8.2 Socle transverse — tests de contrat d'interface (à écrire en T2, maintenus ensuite)

Fichier proposé : `tests/unit/engine/test_agent_interface_contract.py`.
- `action_space.n == 41` et `observation_space.shape == (108,)` lus depuis la config (échec
  explicite si la config change sans migration de modèle actée).
- **Cohérence constantes ↔ décodeur** : pour chaque constante de `macro_intents.py` créée en T2
  (`ACTION_WAIT`, `SHOOT_SLOT_BASE`, bases move/advance/fallback, `ACTION_CHARGE`,
  `ACTION_FIGHT`, `DEPLOY_SLOTS`), un test vérifie que `ActionDecoder` route bien cet entier
  vers l'intention attendue (wait→wait, 19→shoot slot 0, 24→charge...). C'est LE verrou
  anti-récidive de R5 : tout futur re-layout casse ce test au lieu de casser le training.
- Somme du layout : `6+6+6+1+5+1+1+15 == TOTAL_ACTION_SIZE == 41`.
- Le masque retourné par `get_action_mask()` a exactement `shape (41,)`, dtype bool.

### 8.3 Couverture par tranche

**T1 (fait — tests à vérifier présents, compléter si trous)** :
- R6 : éligibilité + destinations de charge avec `BASE_SIZE` liste (Carnifex `[41,27]`,
  Psychophage `[47,36]`) dans les DEUX sites (`charge_build_valid_destinations_pool`,
  `_charge_reverse_goal_bfs_for_eligibility`) — plus cas socle rond int (non-régression).
- R4 : `is_programmatic_owner`/`is_programmatic_defender` — matrice complète :
  (gym_training_mode True/False) × (player_types human/ai) ; allocation tir auto en gym ;
  **allocation fight auto en gym avec pertes réellement allouées** (le chemin FIGHT_CTX,
  jamais exercé avant T1) ; les 4 sites `defender_human` du flux fight ; en PvP humain,
  l'allocation reste manuelle (miroir) ; `_is_ai_controlled_shooting_unit` NON branché sur
  gym (test négatif : pas d'auto-activation `active_shooting_unit` en gym).

**T2** :
- Tests 8.2 ci-dessus.
- `env_wrappers` : WAIT forcé émet `ACTION_WAIT` (18) ; détection « pool empty » ; plus AUCUN
  test ne référence 11/12 ou les plages 4-8 hors déploiement.
- `evaluation_bots` : pour chaque phase (move/shoot/charge/fight), le bot ne choisit QUE des
  actions du masque ; choix hors masque = erreur explicite (test `raises`) ; les dicts de
  poids déploiement pointent des actions de `DEPLOY_SLOTS`.
- ~~`game_replay_logger` : décodage correct du layout 41 (un cas par famille d'action) — ou, si
  condamné, erreur explicite testée.~~ → **sans objet : le module est supprimé (§0.8).** Ne pas
  réécrire de test pour lui.

**T3** :
- `_list_available_board_refs` retourne les refs du board résolu par
  `config_loader.get_board_dir()` (test avec `W40K_BOARD_PATH` pointant un board de fixture) ;
  plus aucune reconstruction `{cols}x{rows}` (test sur analyzer si migré).
- `_expand_random_ref_weights` : refs inconnues → erreur explicite listant les refs
  disponibles ; refs valides → expansion correcte.
- R1 selon la décision : phase `default` existante OU `--training-config` manquant → erreur
  explicite listant les phases (test du message).
- `_materialize_eval_scenario_refs` n'émet PLUS `objectives_ref` (clé absente du scénario
  matérialisé — test de sortie).

**T4** :
- Résolveur `board_ref` : (a) parent `scenario/` sans `board_ref` → OK (comportement PvP
  inchangé) ; (b) `board_ref` valide hors `scenario/` → OK ; (c) ni l'un ni l'autre → erreur
  explicite ; (d) `board_ref` inexistant → erreur explicite. Idem pour `wall_ref: "random"`
  et `terrain_ref`.
- **Balayage de la banque** (test paramétré sur les 61 scénarios migrés) :
  `W40KEngine(scenario_file=...)` + `reset()` sans exception ; zéro clé legacy
  (`objectives`, `objectives_ref`, `objective_hexes`, `deployment_zone`) ; ≥ 1 objectif
  résolu (piège « liste vide en silence », game_state ~L376-381) ; `deployment_zones` avec
  clés `"1"`/`"2"`.
- Script de migration : idempotence (2e passage = zéro diff).

**T5** :
- R7 : scénario minimal amené au dernier tour, phase fight du dernier joueur, pools vides →
  `terminated=True`, winner déterminé, JAMAIS masque vide avec `terminated=False`. Cas
  symétriques P1/P2.
- Invariant global (smoke intégré en test, 3 seeds × 2 sièges, plafonné en steps) : à chaque
  step, `mask.any() or terminated` — c'est l'invariant qui protège MaskablePPO.

**T6** : à l'origine « pas de test unitaire nouveau (validation par run réel + analyzer +
replay), suite complète verte ». Les ruptures T6-c→T6-h ont imposé des verrous :
- `test_squad_fight_target_parity.py` (T6-c, +5) et `test_squad_fight_v11_state.py` (T6-d, +6).
- `test_deployment_per_model_commit.py` (T6-f, +10) : aucune figurine à `(-1,-1)` après commit ;
  ancre = figurine d'index minimal (invariant de `build_rigid_plan`) ; légalité du plan
  committé ; déterminisme + lecture pure de `build_validated_deployment_plan` ; invalidation de
  la mémo sur tampon périmé ; équivalence de l'empreinte pré-calculée aux DEUX parités de
  colonne (l'optimisation touche du code partagé PvP).
- `test_rigid_plan_translation.py` (T6-h, +10) : distances internes du bloc préservées, paramétré
  sur `dx` PAIR **et** IMPAIR — un test qui n'exerce que `dx` pair passe sur le code buggé.
- `test_move_pool_block_erosion.py` (T6-g, +6) : mur / autre escouade / ER ennemie sous une SŒUR
  alors que l'ANCRE est légale, débordement de plateau, absence de sur-filtrage, court-circuit
  mono-figurine. `game_state` fabriqué — d'où le test suivant.
- `test_move_mask_is_executable.py` (T6-g/T6-h, +3) : l'invariant « masque ⊆ exécutable » sur le
  VRAI moteur (3 seeds × 400 steps, ~21 700 cellules par run), avec le budget exact
  qu'`execute_squad_move` appliquerait. Couvre les deux contraintes que l'érosion ne filtre pas
  et qui n'étaient que RAISONNÉES invariantes par translation cube (`budget_per_model`,
  `require_coherency`).
  ⚠️ **Contre-épreuve obligatoire pour ce genre de test** : il a d'abord été « validé » par un
  `git stash` qui, les fixes ayant été committés entre-temps, n'annulait que le refactor — le
  test passait donc pour une mauvaise raison. La vraie épreuve est
  `git checkout 3886e498 -- engine/phase_handlers/shared_utils.py` : le test devient ROUGE sur
  les 3 seeds avec l'erreur d'origine (`squad=103 dest=(24,15) … incohérence masque/exécution`).
  Un test de non-régression qu'on n'a pas vu échouer ne garde rien.

⚠️ **La suite n'est PAS verte et ne l'était pas avant ces fixes** : 9 échecs préexistants
(4 banque de scénarios + 5 déploiement/terrain), tous dus à des rosters manquants ou non
résolus. Le critère réel est donc « pas de NOUVEL échec », à établir par baseline `git stash`
avant de conclure quoi que ce soit sur une régression.

### 8.4 Couverture Phase A' (une règle = son fichier de tests, AVANT suppression du code mort)

- Chaque règle du tableau P1 (section 9.2) : tests sur le chemin VIF (`_manual_roll_intent` /
  `_resolve_one_manual_wound`) encodant le PDF — cas nominal, cas limite, cas d'inapplicabilité.
  Minimum par règle : HEAVY (les 3 conditions 24.16, chacune isolée) ; HAZARDOUS (un jet PAR
  ARME sélectionnée, pas par attaque ; réutilisation de `roll_hazard_for_unit`) ;
  IGNORES_COVER (bypass du malus, ET non-régression : arme sans le trait subit toujours
  13.08) ; DEVASTATING_WOUNDS (arrêt de séquence, MW après dégâts normaux, max 1 figurine
  par critical wound) ; RAPID_FIRE (bonus à mi-portée exacte, rien au-delà) ;
  closest_target_penetration (AP+1 seulement sur la cible la plus proche) ; rerolls tir
  (parité avec les tests fight existants).
- Suppression du code mort : après purge, la suite passe SANS les tests monkeypatchés
  supprimés, et un test-sentinelle vérifie que `execute_action` sur les anciennes branches
  lève l'erreur « squad path expected ».
- P2/P3 (par décision branchée) : ordre des candidats déterministe et stable (deux appels →
  même liste) ; masque expose exactement les `CHOICE_i` des candidats valides ; décision
  appliquée = candidat choisi ; en PvP le prompt `waiting_for_player` équivalent est intact
  (miroir) ; heuristique `_ai_select_*` toujours utilisée par le bot adversaire.

### 8.5 Critère d'acceptation global

`python3 -m pytest tests/unit/ -q` vert (0 failed, 0 error, skips justifiés) est une condition
NÉCESSAIRE de sortie de CHAQUE tranche (T1→T6, puis chaque tranche P1/P3) — en complément des
critères spécifiques de la section 6, jamais à leur place.

## 9. Phase A' — Toutes les règles implémentées dans le training (P1-P5)

Décision utilisateur (2026-07-14) : l'agent doit s'entraîner sur TOUTES les règles déjà
implémentées, et chaque fois que les règles laissent un choix au joueur, c'est l'agent qui
choisit. Périmètre strict : règles présentes dans le moteur — on n'entraîne sur AUCUNE feature
absente (stratagèmes, CP, FNP, transports, etc. restent hors scope). Prérequis : Phase A
(T1-T6) validée.

### 9.1 Constat d'architecture (audit 2026-07-14, vérifié par lecture)

Il existe DEUX moteurs de résolution d'attaque :
- **Chemin vif** (PvP ET gym) : résolution squad — `_manual_roll_intent`
  ([shared_utils.py:5905-5993](../../engine/phase_handlers/shared_utils.py#L5905-L5993)) + `_resolve_one_manual_wound` (L6038-6114).
- **Code mort** : `_attack_sequence_rng` (shooting_handlers, ~L5820-6003) — zéro site
  d'appel vif (utilisé seulement par des tests via monkeypatch) ; les branches `execute_action`
  qui y menaient lèvent des RuntimeError « squad ... expected » (shoot ~L5510-5529,
  activate_unit ~L5519-5523, select_weapon ~L5534-5538 « squad_select_weapon expected »,
  left_click ~L5589-5593, invalid ~L5627-5631) ; état orphelin `_rapid_fire_*` dans
  w40k_core (~L1055-1061, L2055-2061) et sites shooting_handlers associés (~L230, L947-953,
  L2500-2506, L4912-4925, L5689-5696). NB : w40k_core ~L3561 est un simple champ de LOG
  `rapid_fire_bonus_shot`, pas de l'état — le grep `_rapid_fire_` ne l'attrape pas.
- `WeaponRulesApplier.apply_rules` est un placeholder pass-through ([rules.py:279-327](../../engine/weapons/rules.py#L279-L327)) :
  les règles d'armes sont validées/parsées mais PAS appliquées par ce système.

Conséquence : toute règle implémentée uniquement dans `_attack_sequence_rng` est inactive
partout (gym ET PvP).

### 9.2 P1 — Parité de résolution : réimplémentation depuis les PDFs, puis suppression du mort

⚠️ **Le code mort N'EST PAS une spec à porter** — vérifié contre les PDFs du projet (24 Core
abilities lu) : il implémente une AUTRE édition des règles. Il ne sert que d'indice de point
d'insertion. Chaque règle se réimplémente depuis le PDF du projet.

Règles à implémenter dans le chemin vif (absentes du vif, présentes dans le mort sous forme
non conforme) — descriptions = PDF projet :

| Règle (PDF projet) | Indice mort | Point d'insertion vif |
|---|---|---|
| HEAVY (24.16) : +1 to hit si unité unengaged ET pas posée sur la table ce tour ET aucun modèle bougé de plus de 3" ce tour — PAS « remained stationary » | ~:5869-5880 | `_manual_roll_intent` (seuil de touche) |
| HAZARDOUS (24.15) : après que l'unité a résolu TOUTES ses attaques, un hazard roll (06.03) PAR ARME hazardous sélectionnée — pas un jet par attaque. NB : `roll_hazard_for_unit` (vif, shared_utils ~3410, câblé au move via w40k_core ~2635) implémente déjà 06.03 → réutiliser | ~:5887, :5916 | fin d'activation tir/fight |
| IGNORES_COVER : 17 armes la déclarent, la feature est OBSERVÉE, mais `_cover_worsened_bs` (shared_utils ~5745) ne la vérifie jamais — le malus de couvert est infligé À TORT à ces armes (gym ET PvP ; le commentaire w40k_core ~4380 « appliqué côté frontend » est faux pour la résolution backend) | — (jamais implémentée) | `_cover_worsened_bs` (bypass si arme IGNORES_COVER) |
| DEVASTATING_WOUNDS (24.10) : critical wound → la séquence de CETTE attaque s'arrête, la cible subit D blessures mortelles APRÈS les dégâts normaux, max 1 figurine endommagée par critical wound — PAS « save sauté » (le mort n'est pas conforme non plus) | ~:5970-5980 | `_resolve_one_manual_wound` + moteur MW |
| RAPID_FIRE : attaques bonus à mi-portée (conforme PDF) | état w40k_core ~:1055-1061 | `_manual_roll_intent` (calcul NB à la déclaration, comme Blast) |
| closest_target_penetration (règle projet unit_rules.json) : AP+1 sur la cible éligible la plus proche | ~:5836-5840 | `_manual_roll_intent` (AP effectif) |
| reroll_1_towound au TIR | ~:5935-5940 | `_manual_roll_intent` — déjà vif en fight (`_manual_roll_fight_intent`) : asymétrie tir/fight à combler |
| reroll_towound_target_on_objective au TIR | ~:5945-5957 | idem |

Méthode : une règle = une tranche (PDF relu AVANT implémentation + test unitaire dédié).
⚠️ Le chemin squad est partagé PvP/gym : chaque implémentation corrige AUSSI le PvP — c'est
voulu (conformité accrue partout), à annoncer à l'utilisateur (équilibre de jeu modifié).

Cas particulier : **`reroll_charge`** est déclaré dans `config/unit_rules.json` mais
n'existe NULLE PART dans le code (grep zéro, ni vif ni mort). À statuer : implémenter
(charge_handlers, reroll du 2D6) ou retirer de la config.

Déjà vifs (rien à porter) : charge_impact (règle d'unité D6 4+ → 1 MW, `_apply_charge_impact`
~L4551), charge/shoot_after_advance/flee, move_after_shooting, reactive_move,
**Desperate Escape (09.07)**, les 4 rerolls de fight, Blast, Pistol (10.06), couvert 13.08
(mécanique conforme PDF SAUF le cas IGNORES_COVER ci-dessus), obscuring, invuln, allocation
05.03/05.04, T du bodyguard 19.02.
NB : `closest_target_penetration` apparaît aussi comme feature d'OBSERVATION
(observation_builder) — actuellement observée sans effet en résolution.

**Périmètre à statuer (utilisateur)** : ~10 règles d'armes sont déclarées dans les armories ET
observées (observation_builder ~65-92) mais appliquées NULLE PART (ni vif ni mort) : TORRENT,
TWIN_LINKED, SUSTAINED_HITS, LETHAL_HITS, MELTA, ANTI_*, INDIRECT_FIRE, EXTRA_ATTACKS,
PSYCHIC. Elles sont hors périmètre A' (« règles présentes dans le moteur ») — MAIS
IGNORES_COVER fait exception (intégrée au tableau P1 ci-dessus) car son absence rend FAUSSE
une règle implémentée (le couvert). Pour les autres : soit les implémenter (extension de
périmètre à valider), soit retirer leurs canaux d'observation (bruit pur pour PPO), jamais
le statu quo silencieux.

Suppression du code mort (fin de P1) : `_attack_sequence_rng` (~5820-6003), les branches
`squad path expected` (shoot, left_click, select_weapon, invalid — cf. 9.1), l'état
`_rapid_fire_*` de w40k_core (~1055-1061, 2055-2061) ET ses sites shooting_handlers
(~L230, 947-953, 2500-2506, 4912-4925, 5689-5696), le champ de log `rapid_fire_bonus_shot`
(w40k_core ~3561, non attrapé par le grep), et les tests qui monkeypatchent le mort.
Critère : grep `_attack_sequence_rng|_rapid_fire_|rapid_fire_bonus_shot` vide (hors nouvelle
implémentation vive) + suite verte.

### 9.3 P2 — Mécanisme générique « décision agent »

Un seul mécanisme pour tous les choix joueur, au lieu d'actions ad hoc par décision :
- quand le moteur atteint un point de choix joueur en gym, au lieu d'appeler une heuristique
  `_ai_select_*`, il pousse un `pending_agent_decision` (type + liste ORDONNÉE et STABLE de
  ≤ K candidats) ;
- le masque expose K actions génériques `CHOICE_0..K-1` ; l'observation gagne un bloc
  « contexte de décision » (type one-hot + features par candidat) ;
- l'agent choisit, le moteur applique. **Miroir exact des prompts PvP `waiting_for_player`**
  (même sémantique, consommateur différent) — conforme à la règle projet « le flux gym copie
  le flux PvP » ;
- les heuristiques `_ai_select_*` sont CONSERVÉES pour le bot adversaire (GreedyBot) uniquement.

Impact interface : action_space 41 → 41+K (recommandé K=6, aligné sur les 6 slots figurines ;
actions dédiées plutôt que surcharge des slots tir 19-23, pour la lisibilité du masque) ;
obs_size change → nouveau modèle from scratch (`--new`, déjà acté). Mettre à jour la
`justification` de la config en même temps.

### 9.4 P3 — Branchement décision par décision (une tranche = une décision + validation)

⚠️ Les sites à remplacer sont ceux du PIPELINE VIF gym (vérifiés par contre-review), pas les
heuristiques `_ai_select_*` qui ne sont que des fallbacks/chemins legacy.

Ordre par valeur tactique :
0. **Prompts rule-choice** (le plus urgent — pseudo-décision aléatoire structurelle) : en gym,
   `_select_ai_rule_choice_option` choisit par `raw_action_int % len(options)`
   ([w40k_core.py:2494](../../engine/w40k_core.py#L2494)) — l'agent « choisit » via une action émise pour tout autre chose,
   sans voir le prompt. À remplacer par une vraie décision P2.
1. **Cible de mêlée** — ⚠️ **MIS À JOUR le 2026-07-16 (le fix du bug `squad_fight` a déplacé ce
   site)** : la boucle `get_best_enemy_score_for_unit` de `squad_fight` **n'existe plus** — elle
   sélectionnait sa cible dans le mapping de slots gelé du tir, sans filtre de zone d'engagement
   (violation 12.05) et crashait quand ce mapping était vide (cf.
   `Implémenté/bug_squad_fight_mask_mismatch.md`). Le site vif est **désormais
   `_ai_select_fight_target`** (fight_handlers ~L1725), que `squad_fight` consomme via
   `_fight_build_valid_target_pool` — en miroir du flux PvP (`_fight_v11_resolve_attacks`).
   Ce n'est donc plus un « fallback » : c'est le sélecteur vif, partagé gym/PvP.
   ⚠️ Il porte un `except Exception: … return valid_targets[0]` (~L1781) qui masque toute erreur
   de config/registry — vérifié : jamais déclenché sur la suite + smoke. Retrait = backend
   partagé, arbitrage requis (cf. `A_faire/bug_pile_in_bfs_clearance_mismatch.md` §dernier).
   La boucle `get_best_enemy_score_for_unit` reste vive pour la **cible de charge** (point 2).
   Pilote du mécanisme P2.
2. **Cible de charge** — le site vif est la même boucle de scoring dans `convert_squad_action`
   du décodeur (action_decoder ~L917-940), PAS `charge_handlers:1506` (chemin
   `convert_gym_action`, hors gym mais encore vif en PvE via pve_controller — ne pas le
   supprimer, juste ne pas le brancher).
3. **Choix de l'unité à activer** par phase — `eligible_units[0]` a 9 occurrences dans
   action_decoder ; les sites DÉCISIFS du flux vif sont dans `convert_squad_action`
   (~L837, L876), les autres sont dans la construction du masque ; le plus gros gain
   stratégique. Contrainte règles : l'ordre en fight reste borné par Fights First
   (11.04/12.04) et les pools alternés — le choix agent se fait DANS le pool légal courant.
4. **Allocation des pertes défenseur** — remplace `_select_allocation_model`
   (shared_utils ~5643) ; candidats = figurines éligibles 05.03/06.02 ; inclut l'allocation
   hazard ET l'ordre de déclaration des groupes (`declare_order`, décision défenseur 05.03,
   aujourd'hui `_auto_declared_order`).
5. **Pile-in / consolidation** — les sites vifs sont `fight_pile_in_plan`
   (shared_utils ~6708) et `squad_consolidate_plan` (~7038) appelés par `squad_fight`,
   PAS les `_ai_select_*` de fight_handlers ; candidats = top-K destinations du pool.
   NB règles : pile-in/conso sont OPTIONNELS et la consolidation a 3 modes en cascade (dont
   vers objectif) — l'espace de choix doit inclure « ne pas bouger ». ⚠️ Le site vif gym
   `squad_consolidate_plan` n'implémente que le mode (1) (docstring : option (2) « vers
   objectif » déférée) — le flux PvP (fight_handlers ~1161-1176) a la cascade complète :
   écart gym/PvP à combler quand cette tranche s'ouvre.
6. **Move-after-shooting** (destination — remplace
   `_select_move_after_shooting_destination_for_ai`, shooting_handlers ~4961) et
   **reactive_move** (accepter/décliner + destination — protocole `decline_reactive_move`
   déjà formalisé, shared_utils ~2190).
7. **FLY / Take to the skies** — déclaration binaire (aujourd'hui auto pour l'IA,
   movement_handlers ~261/271).
8. **Optionnels, à statuer utilisateur** : split-fire (en gym, l'escouade entière vise UN
   slot ; le PvP a `squad_shoot_assign` par-figurine), choix d'arme — deux régimes distincts
   en gym : RNG = `selectedRngWeaponIndex` pris tel quel (shared_utils ~4489), CC =
   auto-sélection par expected damage `_auto_select_cc_weapon_for_fig` (shared_utils ~6938,
   appel ~7016) — les deux sont des décisions joueur auto-résolues,
   déclaration multi-cibles de charge (PvP oui, gym mono-cible), placement final de charge
   (`charge_build_valid_plan`, shared_utils ~3955), déploiement (les actions 4-8 sont 5
   STRATÉGIES scorées, action_decoder ~1682-1698, pas « les 5 premiers hex » — élargir ou non).

Hors scope A' (reste auto, conforme règles car « un placement légal parmi d'autres ») :
placement par-figurine du move rigide, pivot. Montée d'étage = Phase C.

### 9.5 P4 — Observation de support

Bloc décision (P2) + features nécessaires aux choix : LoS/couvert par slot ennemi, portée
effective de l'arme active vs distance du slot, flags advanced/fell_back de l'unité active.
Les niveaux/élévation restent en Phase B (scénarios plats jusque-là).

### 9.6 P5 — Validation par tranche

Chaque tranche P3 : suite de tests verte + smoke 10 épisodes + run court `x1_debug` +
win-rate vs GreedyBot ≥ tranche précédente. Si l'ajout d'un point de décision DÉGRADE le
win-rate, la décision est mal observée ou mal récompensée → corriger avant d'empiler la
suivante. Interdits : masquer une régression en retirant silencieusement la décision.

Points de vigilance :
- l'ordre des candidats doit être déterministe et stable (sinon l'assignation de crédit PPO
  est brouillée) ;
- chaque décision ajoutée allonge l'épisode en steps → surveiller `episode_steps` vs la
  normalisation `/100` de l'observation globale ;
- les heuristiques du RewardMapper utilisées par les anciens `_ai_select_*`
  (`get_shooting_priority_reward`) peuvent devenir du reward shaping pour guider les
  nouvelles décisions — à statuer par tranche, jamais en silence. NB : un de ses deux
  consommateurs, `_ai_select_shooting_target` (shooting_handlers, def ~2093), est DÉJÀ mort
  (zéro appelant) — à inclure dans la suppression P1.

---

## 10. Stratégie d'entraînement et d'évaluation — DÉCISION UTILISATEUR (2026-07-19)

### 10.1 Contexte et arbitrage

**Objectif métier** : présenter le jeu avec une IA « acceptable » pour obtenir un financement.
La démo oppose un **joueur humain** à l'IA, avec les **armées de la boîte de base**.

**Arbitrage assumé** : l'agent n'apprendra PAS à jouer 40K, il apprendra à jouer **ces deux
rosters**. C'est un choix délibéré pour éviter des semaines de tuning — la spécialisation réduit
la variance de composition, donc le signal d'apprentissage est plus net et la convergence plus
rapide. Pour une démo, un agent spécialisé est indiscernable d'un agent généraliste.

⚠️ **Ne PAS « corriger » ce choix** en réintroduisant de la diversité de rosters : c'est une
décision produit, pas un oubli.

### 10.2 Rosters et matchups

- **2 rosters** : Space Marines (SM) et Orks — les armées de la boîte de base, donc celles de
  la démo. L'entraînement est aligné sur ce qui sera montré.
- **3 matchups** : SM vs Orks, SM vs SM, Ork vs Ork.
- Les rosters de l'ancienne banque ont été **supprimés volontairement** (commit `43eae95a`,
  370 fichiers) : ils précédaient l'implémentation des escouades, donc obsolètes. Les nouveaux
  sont à créer.

**✅ FAIT le 2026-07-19 — agent `ArmageddonAgent`, scale `500pts`.** Les 2 rosters existent et
le pipeline tourne de bout en bout sur eux (training + évaluation).

| Quoi | Où |
|---|---|
| Rosters agent (training) | `config/agents/ArmageddonAgent/rosters/500pts/training/agent_training_roster_{space_marines,orks}.json` |
| Rosters adversaire (training) | `config/agents/_p2_rosters/500pts/training/opponent_training_roster_{space_marines,orks}.json` — le dossier `500pts` n'existait pas côté P2 |
| Scénario d'entraînement | `config/agents/ArmageddonAgent/scenarios/training/scenario_training_armageddon.json` — `agent_roster_ref: "training_random"` (tirage 50/50, **pas de `agent_roster_seed`** : il figerait le tirage agent), `opponent_roster_ref` = liste explicite des 2 fichiers (sinon P2 tire dans tout `_p2_rosters`) |
| Config agent | `ArmageddonAgent_training_config.json` (copie CoreAgent, `roster_pool_schedule.enabled = false` dans les **5** phases) + `ArmageddonAgent_rewards_config.json` (clé racine renommée : le moteur indexe le fichier par nom d'agent, cf. `_build_reward_configs_for_current_units`) |
| Holdout (rosters + scénarios) | `rosters/500pts/holdout_regular/agent_holdout_regular_roster_*.json`, `_p2_rosters/500pts/holdout_regular/opponent_holdout_regular_roster_*.json`, `scenarios/holdout_regular/scenario_bot-0{1..4}.json` (les 4 matchups) |

**Vérifié** : 16 resets → les 4 matchups sortent, plus aucun `roster_pool_schedule produced zero
eligible training rosters` ; training `x5_debug` 8 workers **10/10 épisodes, exit 0** ;
`--eval --test-episodes 2` **exit 0**, combined 0.69 sur 5 bots (le `.zip` du modèle vérifié
intact par md5 — jamais réécrit).

⚠️ **Dette assumée (décision utilisateur 2026-07-19) : le holdout est fait par DUPLICATION des
2 rosters de training**, ce qui **contredit §10.6** (le holdout devait porter sur l'ADVERSAIRE,
pas sur les rosters — ici l'agent est évalué sur les armées qu'il a vues à l'entraînement).
Retenu comme point de départ, à raffiner plus tard. La voie propre est documentée : le résolveur
accepte une ref à **split explicite** (`training/agent_training_roster_orks.json` depuis un
scénario holdout — cf. commentaire « cross-split evaluation P1 holdout vs P2 training »,
`_resolve_roster_ref`), ce qui permettrait de garder les mêmes armées et de ne faire porter le
holdout que sur `TacticalBot`.

⚠️ **Les points des unités Orks sont factices** : `VALUE = 70` pour TOUTES (Boyz, Gretchin,
Warboss, WarTrakk, BigMek…). Le total « 3290 pts » du roster Orks n'a aucun sens, et le moteur
ne valide PAS les points (`scale` n'est qu'un nom de dossier). ~~Déséquilibre réel à surveiller :
**47 figurines côté Orks contre 23 côté SM**.~~ → chiffre périmé : **37 contre 23** depuis §0.9
(10 Gretchin et non 20), et ce n'est pas un déséquilibre mais une identité de faction à 680 vs 680.

**Bug corrigé au passage (registry d'unités)** : `LandSpeederOnslaughtGatlingCannon.ts` et
`LandSpeederHeavyFlamer.ts` déclaraient TOUS DEUX `export class LandSpeeder`. `UnitRegistry`
scanne les `.ts` et indexe par nom de classe → les deux s'écrasaient, `HeavyFlamer` gagnait au
hasard de l'ordre de parcours et la variante Onslaught était **inatteignable**. Classes
renommées (+ `NAME`, `DISPLAY_NAME`) et les deux variantes ajoutées à `config/unit_registry.json`
ET `frontend/public/config/unit_registry.json` (159 → 161). Reste ouvert : les deux pointent vers
`/icons/LandSpeeder.webp`, absent de `frontend/public/icons/` (cosmétique frontend).

**Défaut structurel constaté (non corrigé)** : au TOUT PREMIER run d'un agent neuf, l'évaluation
finale échoue avec `VecNormalize enabled but stats not found: <agent>/vec_normalize.pkl` — le pkl
est écrit à la FIN du run, l'éval tourne avant. CoreAgent ne le voyait jamais (pkl hérité de mai).
Ne se reproduit pas aux runs suivants. Si on veut le traiter : ordonnancer la sauvegarde
VecNormalize avant l'éval finale dans `train.py`.

### 10.3 Progression d'adversaires (l'axe qui porte la robustesse)

Le risque dominant pour cette démo n'est PAS la composition des armées, c'est **l'écart entre
l'adversaire d'entraînement et l'humain de la démo**. Trois niveaux, qualitativement différents :

| Niveau | Nature | Limite |
|---|---|---|
| 1. Bots scriptés | politique **fixe** | l'agent apprend un exploit ; le win-rate monte sans que la compétence monte |
| 2. Self-play | politique **non-stationnaire** qui s'adapte en retour | les exploits cessent de payer ; risque de catastrophic forgetting |
| 3. MCTS | adversaire qui **cherche** | non exploitable par pattern ; coûteux |

**Plan retenu** : (1) les bots scriptés → (2) introduction **progressive** du self-play →
(3) MCTS **seulement si** la perf mesurée est insuffisante.

⚠️ « Diversité d'adversaires » = diversité des **distributions de comportement**, pas nombre de
classes de bots. Huit bots appliquant la même heuristique gloutonne ne font qu'UN adversaire du
point de vue de l'apprentissage.

**Déjà implémenté, à paramétrer et non à développer — mais UNIQUEMENT sur le chemin rotation**
(`--scenario bot`, cf. §10.4) :
- `training_config.bot_training.ratios` — mélange pondéré de bots
  (`_build_training_bots_from_config`, train.py ~L91 ; 7 classes supportées, 6 pondérées dans
  la config actuelle — `defensive_smart` n'y est pas). Configuré dans les 5 phases.
- `training_config.opponent_mix` — self-play progressif : `self_play_ratio_start` →
  `self_play_ratio_end`, `warmup_episodes`, snapshot publié par
  `_publish_self_play_snapshot` (train.py ~L2854) et rechargé par mtime dans
  `BotControlledEnv` (env_wrappers ~L515). Chaîne complète vérifiée : parse → publication →
  rechargement. Le « progressivement » est donc de la config.
  ⚠️ `opponent_mix` n'est PARSÉ que dans `train_with_scenario_rotation` (~L2362) —
  `create_multi_agent_model` l'ignore totalement.

### 10.4 ⚠️ Écart CODE vs PLAN à corriger avant le premier run

> **Statut 2026-07-19 : ✅ RÉSOLU** — construction d'adversaires mutualisée dans
> `build_training_opponents`, `use_bots` dérivé de la config (`bot_training`) et non du nom de
> fichier, repli aléatoire refusé explicitement par `SelfPlayWrapper` et `make_training_env`.
> Détail et vérification en §0. Le constat ci-dessous est conservé comme historique.
>
> **Constat d'origine — les trois faits ci-dessous ont été
> re-vérifiés dans le code ce jour (aucun n'a bougé). Ce n'est plus théorique : les runs de
> validation de T6-g/T6-h (`x5_debug`, n_envs=8, `training_benchmark`) **et** le run de mise en
> service d'`ArmageddonAgent` (§10.2) sont tous passés par la ligne 2 du tableau — donc **contre
> un P2 aléatoire**. Ces runs prouvent que le PIPELINE tourne (zéro exception, épisodes
> complets) ; ils ne prouvent RIEN sur l'apprentissage. C'est le bloqueur n°1, cf. §0.

**Toute la machinerie d'adversaires (bots pondérés + opponent_mix) n'est câblée que sur le
chemin ROTATION.** L'adversaire réel du chemin single-scenario dépend de `n_envs` et du NOM du
fichier scénario — vérifié branche par branche :

| Chemin | Adversaire d'entraînement RÉEL |
|---|---|
| `--scenario bot` (`train_with_scenario_rotation`) | ✅ `bots=training_bots` pondérés (~L2492, ~L2755) + self-play `opponent_mix` |
| `--scenario <fichier>`, `n_envs > 1` (cas RÉEL : x5_debug = 8) | ❌ `make_training_env` appelé SANS `use_bots`/`training_bots` (~L1782) → `SelfPlayWrapper(frozen_model=None)` → **ACTIONS ALÉATOIRES UNIFORMES, en permanence** (voir ci-dessous) |
| `--scenario <fichier>`, `n_envs == 1`, nom contenant « bot » | `GreedyBot(randomness=0.15)` EN DUR (~L1855) |
| `--scenario <fichier>`, `n_envs == 1`, autre nom (dont `scenario_training_benchmark.json`) | ❌ `SelfPlayWrapper` → **aléatoire permanent** aussi (~L1871) |

**Pourquoi « aléatoire permanent » et pas du self-play** (bug latent distinct, vérifié) :
`SelfPlayWrapper._get_frozen_model_action` (env_wrappers ~L1237) retombe sur
`random.choice(valid_actions)` tant que `frozen_model is None` — et
**`update_frozen_model` n'a AUCUN appelant** dans tout `ai/` (grep = 0 ; le compteur
`frozen_model_update_frequency = 100` de train.py ~L2690 est du code mort). Le « self-play »
du chemin single-scenario n'en est pas : P2 joue au hasard du premier au dernier épisode.
Ne pas confondre avec le VRAI self-play (`opponent_mix` → `BotControlledEnv`, chemin rotation),
qui recharge un snapshot publié sur disque et fonctionne.

Or `--scenario bot` est cassé en amont (rosters, cf. §0) : le chemin réellement utilisable est
le single-scenario. **Un run x5_debug lancé aujourd'hui entraînerait donc contre un adversaire
ALÉATOIRE, sans qu'aucun log ne le signale** — pire que « spécialisé sur GreedyBot » : un agent
qui n'a jamais rencontré d'opposition cohérente.

C'est la même famille de divergence que **T6-e** (`_turn_step_limit` absent du chemin
single-scenario) : deux chemins de `train.py` qui ont divergé. À traiter de la même façon —
faire passer les deux par la même construction d'adversaires (`training_bots` + `opponent_mix`
dans `make_training_env`, qui accepte DÉJÀ ces paramètres : seul l'appel de
`create_multi_agent_model` ne les transmet pas).

### 10.5 Évaluation : le holdout porte sur l'ADVERSAIRE, pas sur les rosters

> **Statut 2026-07-19 : ✅ CÂBLÉ** — `TacticalBot` est le holdout, à poids nul et exclu de tout
> signal de sélection ; le défaut silencieux de `randomness` est supprimé. Détail en §0.
> ⚠️ **Affirmation périmée n°4 — voir la table de §0bis** (levée par §0.7 : `TacticalBot` a joué 10/10 épisodes). Conservée telle quelle.
> ⚠️ **Non validé runtime** — cf. §0.3 (`CC_DMG`). L'archivage des scénarios holdout était à
> faire (voir plus bas). Le constat ci-dessous décrit l'état d'AVANT.

**Constat (historique)** : les bots d'évaluation viennent de `callback_params.bot_eval_weights`
(`_load_bot_eval_params`, bot_evaluation.py ~L168 ; itération sur `eval_weights.keys()` ~L886).
Config actuelle, identique dans les 5 phases : `{greedy, defensive, control, aggressive_smart,
adaptive}` — un **sous-ensemble strict des bots d'entraînement** (`bot_training.ratios` = les
mêmes 5 + `random`). L'agent n'est donc évalué QUE contre des adversaires rencontrés à
l'entraînement : ce win-rate mesure **l'exploitation apprise, pas la compétence**, et sera
systématiquement optimiste par rapport au comportement face à un humain.

**Décision** : le holdout est un **adversaire réservé à l'évaluation**, jamais vu en
entraînement. Candidat déjà disponible : **`TacticalBot`** — le seul des 8 qui n'est utilisé
nulle part (`evaluation_bots.py` L19 : « unused in training/eval »).

À faire : ajouter `TacticalBot` aux bots d'évaluation, et **garantir qu'il n'entre jamais**
dans `bot_training.ratios` (test de non-régression : l'intersection entre bots d'entraînement
et bots de holdout est vide).

Cela remplace avantageusement le holdout de rosters supprimé, et répond à la question
« 2 ou 4 rosters » : **rester à 2**, et mettre le holdout sur l'axe adversaire.

⚠️ Les 20 scénarios de `holdout_regular/` + `holdout_hard/` pointent vers des rosters supprimés :
ils ne chargent pas. **À archiver** dans `_archive_pre_v11/`. Tant qu'ils sont là,
`bot_eval_scenario_pool: "holdout"` (présent dans les 5 phases de
`CoreAgent_training_config.json`) pointe sur un pool mort.
NB — répartition VÉRIFIÉE des 9 échecs de la suite (cause relue test par test) : **8 viennent
des scénarios TRAINING** (`agent_roster_ref: "training_random"` →
`roster_pool_schedule produced zero eligible training rosters`, candidates=1 : le pool de
rosters d'entraînement est quasi vide depuis le cleanup `43eae95a`) et **1 seul** d'un fichier
de roster holdout absent. Archiver les holdouts n'en fait tomber qu'un : le gros de la
réparation est la création des nouveaux rosters SM/Orks (§10.2) + la mise à jour des scénarios
training qui les référencent.

### 10.6 Critère de succès (remplace le critère T6 « win-rate vs RandomBot »)

Le critère historique référençait une capacité qui n'existe plus (holdout de rosters). Nouveau
critère, en deux volets — **les deux sont requis** :

1. **Quantitatif** : **win-rate PAR ROSTER** contre l'adversaire de holdout (`TacticalBot`),
   jamais rencontré à l'entraînement. Par roster, car avec seulement 2 rosters, un effondrement
   sur l'un pendant que l'autre monte est la **signature du catastrophic forgetting** (piège
   listé dans CLAUDE.md) et le seul garde-fou qui reste. Un win-rate agrégé le masquerait.
2. **Qualitatif — décisif pour l'objectif démo** : **absence de comportement absurde** sur N
   parties jouées par quelqu'un n'ayant pas travaillé sur le projet, cherchant activement à
   surprendre l'agent (déploiement inhabituel, tactique atypique).

**Pourquoi le volet 2 n'est pas optionnel** : devant un financeur, ce qui convainc est que l'IA
paraisse *sensée* (elle va sur les objectifs, tire sur des cibles plausibles, charge quand c'est
logique). Un agent à 45 % de victoires qui joue de façon lisible impressionne davantage qu'un
agent à 70 % qui gagne en exploitant une faiblesse de bot et produit un coup absurde au pire
moment. **En démo, l'incohérence coûte plus cher que la défaite.**

### 10.7 MCTS — deux usages distincts, ne pas les confondre

| Document | Usage | Effet |
|---|---|---|
| `A_faire/MCTS/MCTS_bot_final.md` | MCTS comme **adversaire d'entraînement** (fraction d'épisodes, entre bots et self-play) | améliore l'entraînement → demande un cycle complet de plus |
| `A_faire/MCTS/MCTS_agent_implementation.md` | MCTS **dans l'agent**, à l'inférence | corrige les coups absurdes **sans retraining** |

Pour l'objectif démo (§10.6 volet 2), c'est le **second** qui a le meilleur rapport
effort/résultat : c'est l'absurdité ponctuelle qui coûte cher, et une recherche à l'inférence la
corrige directement. Contre-argument à mesurer : la **latence** en temps réel devant un public —
`MCTS_agent_implementation.md` note lui-même « micro à chaque activation + rollouts = beaucoup
plus lourd » et suggère « macro + feuille value seule » comme prototype. Un MCTS macro peu
profond, ou limité aux seules décisions critiques, suffirait probablement.

**À ne PAS anticiper** : plan B après mesure. Rien ne sert de décider avant de savoir si le PPO
spécialisé suffit.
