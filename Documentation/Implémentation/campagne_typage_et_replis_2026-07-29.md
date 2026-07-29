# Campagne « typage & replis silencieux » — 2026-07-29

**Chantier vivant** : contient à la fois du travail **LIVRÉ** (§2) et de la **DETTE RESTANTE**
(§3, la partie la plus importante). Placé à la racine de `Implémentation/` pour cette raison —
`A_faire/` ne porte que du backlog, `Implémenté/` que du livré.

**Périmètre de commits** : `bb3a788f` (14 h 38) → `d061f21b` (16 h 57), soit **38 commits hors
merge + 19 merges = 57 commits** sur `main`. Constaté par `git log --oneline bb3a788f~1..d061f21b`.
Le même jour, `main` a par ailleurs absorbé les six branches V11 (§0.46 → §0.51 du journal V11) —
elles NE font PAS partie de cette campagne et sont consignées dans
[`V11_agent_rework.md`](V11_agent_rework.md). Total du jour : **106 commits d'avance sur
`origin/main`**.

**Convention d'ancrage** (identique au journal V11) : l'ancre de référence est le **nom de
fonction** ; les numéros de ligne sont indicatifs. Re-localiser par `grep` avant d'éditer.

⏳ **Entrée périssable** : les mesures de §3 ont été prises le **2026-07-29 en fin de campagne**,
sur un working tree où **quatre fichiers moteur étaient modifiés par l'utilisateur**
(`fight_handlers.py`, `shared_utils.py`, `shooting_handlers.py`, `w40k_core.py`). Les recompter
avant de s'en servir.

---

## 1. Le fait marquant — le typage n'était presque jamais le défaut

La campagne est partie de **deux fichiers de log** : une sortie de suite de tests et une sortie du
vérificateur de types. Elle a dérivé en chasse à la dette technique parce que, **commit après
commit, le `cast` ou le repli signalé n'était pas le défaut mais son symptôme visible**.

Le motif s'est répété assez pour être nommé :

| Ce que le vérificateur signalait | Ce que c'était réellement |
|---|---|
| `cast(SummaryWriter, _DummyWriter())` **et** `cast(_DummyWriter, t.writer)` | un type absent — le tracker n'a jamais eu besoin d'un `SummaryWriter`, seulement de 4 méthodes (`dde97ed2`) |
| 9 `cast` sur `Socle.base_size` | une **union étiquetée modélisée comme un enregistrement plat** (`44486667`, puis `6f0c0c6b`) |
| `cast(str, <int>)` × 6 | des **fixtures** qui construisaient des ids `int` que la production ne produit jamais (`1cb2c416`) |
| un `cast` sur un quadruplet | une **branche CLI qui ne pouvait que lever** — le cast la faisait passer pour vivante au typage (`e469dff3`) |
| `# pyright: ignore[reportGeneralTypeIssues]` anonyme | « **Code is too complex to analyze** » — la méthode centrale du moteur échappait entièrement au vérificateur (`b376f2ae`) |
| `cast("W40KEngine", ...)` × 3 | **deux règles de déballage différentes** dans le même module (`d5bb0571`) |
| 6 `cast` autour d'`Optional` | du code **DQN** dans un dépôt qui n'instancie que `MaskablePPO` (`d837cb11`) |

**Conséquence pour un lecteur futur : ne refais pas un balayage mécanique.** Un contournement de
typage est une **question** (« pourquoi le code a-t-il besoin de mentir ici ? »), pas une tâche de
suppression. Le contre-audit du parc l'a chiffré : sur **85 contournements** recensés, **13
seulement** étaient légitimes — l'audit précédent en concluait 66, et sa catégorie « évitable »
absorbait la moitié du parc.

> ⚠️ **Ce chiffre 85 / 13 / 66 n'a PAS d'artefact versionné dans le dépôt** : il provient du
> contre-audit conduit pendant la campagne, dont le rapport n'a pas été commité. Ce qui **est**
> vérifiable par `git grep` : **87 `cast(` avant la campagne (`bb3a788f~1`) → 33 à `d061f21b`**, et
> **21 lignes portant `type: ignore` / `pyright: ignore` → 10, dont 1 simple mention en
> commentaire** (`ai/pointer_policy.py:254`), soit **9 sourdines réelles**.

---

## 2. Ce qui a été livré

Chaque ligne porte le hash **constaté** par `git log` et lu dans son message de commit.

### 2.1 Replis silencieux supprimés

| # | Hash | Ce que c'était |
|---|---|---|
| 1 | `e67066da` | `_resolve_one_manual_wound` résolvait la caractéristique **D** dans un `try/except Exception` qui **retombait sur 1 dégât** — et avalait aussi le `KeyError` de `pw['attacker_mid']`. Un lot d'attaques mal formé devenait « 1 dégât ». Propagé aux 4 sites qui l'avaient manqué (`DMG`/`NB` en `.get(..., 1)`, `_resolve_intent_nb`, `squad_declare_fight`). Vérifié : les **231 profils d'armes** de `frontend/src/roster` déclarent tous `DMG`, les 7 valeurs employées se résolvent. |
| 2 | `5542456d` | **Quinze** replis de la même famille, tous à **valeur de jeu crédible** donc invisibles à l'œil : `weapon.get("ATK", weapon.get("BS", 4))`, `weapon.get("STR", weapon.get("S", attacker.get("T", 4)))` (repli sur l'**endurance de l'attaquant**), `AP → 0`, `T → 4`, `ARMOR_SAVE/INVUL_SAVE → 7`, et le **filtre de portée** `weapon.get("RNG", 0) > 0`. Preuve sur donnée réelle : 243 profils de tir portent tous RNG/NB/ATK/STR/AP/DMG, 185 profils de mêlée portent NB/ATK/STR/AP/DMG et **aucun** ne porte RNG, 179 datasheets portent T/ARMOR_SAVE/INVUL_SAVE. |
| 3 | `5542456d` | **Trois caractéristiques fossiles** : `BS`, `S`, `WS`. **Zéro occurrence dans la donnée** (re-vérifié : `grep '"BS"'` et `grep '"WS"'` sur `config/` et `frontend/src/roster` = 0), présentes uniquement dans **14 fixtures de test**, renommées en `ATK` par ce commit. |
| 4 | `5542456d` | `_build_weapon_availability_enemy_precheck` : un `except Exception: continue` faisait **disparaître du calcul** une arme sans portée — l'unité pouvait perdre sa portée maximale réelle et ne plus voir ses cibles. Plus le `except Exception: topo_str = "los=N/A"` du bloc `LOS_DEBUG` : un instrument de diagnostic qui avale la panne de la primitive qu'il observe ne diagnostique plus rien. |
| 5 | `e23827bc` | **Un cache qui mémorisait son propre échec** : `_fight_prepare_footprint_offsets` écrivait `None` dans le cache d'offsets quand `precompute_footprint_offsets` levait. Un socle invalide n'était pas seulement ignoré — il était **mémorisé pour la clé (unité, orientation)**, et toutes les décisions de combat passaient au chemin lent, en silence, pour le reste de la partie. |
| 6 | `72dcf0d5` | `game_state.get("weapon_rule", 1)` situé **dans la fonction qui écrit `game_state["weapon_rule"] = 1`** soixante lignes plus haut. Le repli de la preview de MOVE est **conservé et justifié par écrit** : c'est un montage de simulation sur une copie, pas un repli anti-erreur. |
| 7 | `3b3ddd83` | `_weapon_has_assault_rule` / `_weapon_has_close_quarters_rule` : deux doublons laxistes de `weapon_has_rule`, dont ils s'écartaient par `if not weapon: return False` et `"WEAPON_RULES" in weapon else []`. 24 sites délèguent désormais. Vérifié iso-comportement sur les 153 armes des armureries et les 428 armes des 179 unités des rosters réels. |

### 2.2 L'invariant de socle, puis la scission du type

- `44486667` — l'invariant `BASE_SHAPE`/`BASE_SIZE` (`round`/`square` → diamètre scalaire, `oval` →
  paire) est validé **une fois, à la frontière** (`_scale_socle` au chargement de datasheet,
  `GameStateManager.create_unit` au second point d'entrée). Les **9 `cast`** disparaissent
  (`hex_utils` ×6, `terrain_utils` ×2, `movement_handlers` ×1), ainsi que deux gardes correctes qui
  dormaient (`_cache_entry_round_base_size`, appelée nulle part). Vérifié : **161 datasheets**
  respectent l'invariant (156 `round` + 5 `oval`, 0 violation). Coût mesuré des accesseurs :
  **+85 ns par lecture**, soit **+13 %** sur `euclidean_edge_distance` et **+24 %** sur
  `footprints_overlap`.
- `6f0c0c6b` — le type est **scindé** : `RoundSocle` / `SquareSocle` / `OvalSocle`
  ([`engine/hex_utils.py:1728/1741/1754`](../../engine/hex_utils.py#L1728)) portent chacun le type
  exact de `base_size` ; `Socle(...)` devient la **fabrique** qui choisit la classe. **Un socle
  incohérent ne peut plus exister** — l'invariant n'est plus vérifié à la lecture. La classe de
  base ne déclare pas `base_size` : on ne peut pas lire la taille sans savoir de quelle forme il
  s'agit, et le vérificateur l'impose. Gain mesuré (timeit, n=200000, 3 passes) :

  | | avant | après | |
  |---|---|---|---|
  | `euclidean_edge_distance` | 883 ns | 645 ns | **−27 %** |
  | `footprints_overlap` | 679 ns | 490 ns | **−28 %** |
  | construction | 243 ns | 274 ns | **+31 ns — assumé**, c'est le prix de l'invariant |

  Net sur le couple réel « construire un socle puis tester le chevauchement » : **−17 %**.

### 2.3 Les quatre compteurs de combat rebranchés

`5f1878eb` — `shots_fired`, `hits`, `damage_dealt`, `damage_received` étaient **déclarés** dans
`episode_tactical_data` et **jamais incrémentés**. Le commit **`fe1df7d8` « metrics OK » du
2025-10-25** (date constatée) a déplacé ce dictionnaire du callback vers le moteur : le déplacement
a réimplémenté `valid_actions`, `invalid_actions`, `units_lost` et `units_killed`, **mais pas ces
quatre-là**, tout en supprimant leur calcul côté callback dans le même diff. **Migration partielle,
neuf mois de silence.**

Les consommateurs sont gardés par `> 0` : **une courbe absente ne se distingue pas d'un agent qui
ne se bat jamais**. Quatre courbes muettes : `game_tactical/shooting_accuracy`,
`game_detailed/damage_dealt`, `game_detailed/damage_received`, `game_tactical/damage_efficiency`.

Rebranchés dans le bloc de fin d'épisode de `step()` sur `action_logs`
([`engine/w40k_core.py:2007`](../../engine/w40k_core.py#L2007) et suivants) — **pas** sur
`attack_details`, qui vit sous `if (self.step_logger and self.step_logger.enabled)` et rendrait les
métriques dépendantes de `--step`. Preuve de cohérence croisée sur vraie partie (14 tests, moteur
réel, 3 graines) : `damage_dealt` == PV réellement perdus par l'adversaire et `damage_received` ==
PV perdus par le camp contrôlé, à l'unité près, **dans les deux sens et pour les deux sièges**.

➡️ **Conséquence sur les mesures d'entraînement** : reportée au journal V11, **§0.52**.

### 2.4 La méthode centrale du moteur

`b376f2ae` — le `# pyright: ignore[reportGeneralTypeIssues]` posé sur la ligne de définition de
`_process_semantic_action` ([`engine/w40k_core.py:3035`](../../engine/w40k_core.py#L3035)) était
**anonyme**. Retiré, pyright dit ce qu'il taisait : **« Code is too complex to analyze »** — soit
**1582 lignes / 205 `if`** au moment du commit (mesuré à nouveau après la campagne : **1613 lignes,
205 `if`**, sur un fichier que l'utilisateur modifiait). Ce n'était pas une erreur de type précise :
c'était **l'analyse entière refusée**.

Le corps a été rendu analysable par **extraction temporaire** du bloc `step_logger`. Trois défauts
réels ont été trouvés et corrigés :

1. `action_details` n'était lié que sous `if updated_unit:` — quand l'unité n'existe plus, toutes
   les branches en aval levaient un **`UnboundLocalError` avalé par le `except Exception` du bloc**
   (ligne de `step.log` perdue sans cause) ;
2. branche `advance` : `require_unit_position(updated_unit, ...)` recevait un optionnel sans garde ;
3. filet post-tir : `isinstance(result.get(x), str)` puis `result.get(x).strip()` contrôlaient un
   **accès différent** de celui utilisé.

La sourdine **reste, mais motivée** : elle acte le refus d'analyse, pas un faux positif.
➡️ **Sa disparition = dette n°1 (§3.1).**

### 2.5 Le flux de replay qui effaçait un scénario versionné

`ed0ef47c` — quatre attributs posés sur des objets fonction faisaient croire à un mécanisme vivant
(`_current_template_name`, `_detected_template_name`, `_detected_agents` : jamais écrits par la
production, ou écrits jamais relus). Le quatrième, `_scenario_file`, était vivant mais **fuyait** :
le bloc de nettoyage ne le remettait pas à zéro, donc une deuxième conversion dans le même
processus relisait le scénario de la première. Devenu **paramètre explicite** de
`convert_to_replay_format` / `convert_steplog_to_replay`
([`ai/replay_converter.py:58`](../../ai/replay_converter.py#L58)).

🔴 **Défaut connexe, le plus grave du lot** : le nettoyage appelait **`os.remove` sur le scénario
bot**. Depuis que la source est `get_scenario_list_for_phase`, ce chemin désigne un **vrai fichier
versionné** de `config/agents/<agent>/scenarios/training/` — **le workflow amputait le jeu
d'entraînement à chaque exécution.**

### 2.6 Code mort supprimé, avec preuve en quatre directions

Le patron de preuve appliqué à chaque suppression : (a) aucun appel ni import, (b) aucune référence
par chaîne ni réflexion, (c) aucune route d'API ni chemin frontend ne l'atteint, (d) aucune mention
en documentation.

| Hash | Ce qui tombe | Point saillant |
|---|---|---|
| `6b4c0329` | `WeaponRulesApplier` — la classe d'application des règles d'armes | `_apply_single_rule` n'a **jamais reçu le moindre handler** : elle renvoyait `context` inchangé. Son **unique test verrouillait son inaction**, ce qui lui donnait une apparence de vie. L'application effective passe par `weapon_helpers.weapon_has_rule`. |
| `c9518efc` | la clé `_parsed_rules`, **écrite dans chaque arme** | C'était le canal d'entrée du défunt applicateur. **Aucun lecteur**, tout en pesant dans chaque dict d'arme et en forçant `api_server` à l'exclure pour ne pas la faire fuiter dans chaque réponse JSON — dette payée deux fois. L'**appel** `validate_weapon_rules_field` (le fail-fast) est conservé : c'est le retour qui était inutile, pas l'appel. |
| `a7688806` | les branches défensives `ParsedWeaponRule` (4 sites) | Preuve **par la provenance** : le type n'est construit qu'en un seul endroit, dont l'unique chemin de production jette désormais le retour ⇒ **aucune instance ne peut survivre**. Vérifié au runtime par balayage du tas (`gc.get_objects()`) : 153 armes parsées, **zéro instance vivante**. |
| `a80dff3e` | `_get_available_weapons_for_selection`, **~160 lignes** | Marquée `DEPRECATED` dans sa propre docstring, sans appelant. Ce **n'était pas une fonctionnalité jamais branchée** : ses 5 filtres sont tous couverts par `weapon_availability_check`, **sur-ensemble strict**. La rebrancher aurait été une **régression de règles** (mélange `[CLOSE-QUARTERS]` ignorant l'exclusion MONSTER/VEHICLE de 24.07). |
| `e469dff3` | la branche `MacroController` de `ai/train.py` | `create_macro_controller_model` et `_build_macro_eval_env` levaient `NotImplementedError` **sans condition** ; un `cast` habillait le premier en quadruplet et **faisait passer la branche pour vivante au typage**. `--agent MacroController` plantait à coup sûr. Ni `ai/macro_training_env.py`, ni `config/agents/MacroController/`, ni `Documentation/TODO/Macro_agent.md` n'existent : **aucun projet en attente à préserver**. |
| `d837cb11` | 3 blocs **DQN** (`q_value_mean`, `q_value_mean_smooth`, `exploration_rate`) + la protection d'import des bots | Gardés par `hasattr(self.model, 'q_net' / 'exploration_rate')` : le dépôt n'instancie que `MaskablePPO` (12 sites), un actor-critic. **Les courbes n'ont jamais rien reçu.** 6 `cast` partent avec. |
| `8755dd2f` | `EpisodeBasedEvalCallback` — **classe jamais instanciée** | Exportée dans `__all__` et importée par `ai/train.py`, jamais construite. L'évaluation périodique réelle est faite par `BotEvaluationCallback`. Au passage, révélé par le désindentage : `freq_unit`, variable locale assignée et jamais lue. |
| `92f3d5dc` + `970ecb6a` + `134546bc` | 2 gardes sur des métriques **sans producteur**, puis les métriques orphelines | `position_score` : producteur supprimé par `329d140e` « move reward deleted » (2026-02-01) — suppression **voulue** côté produit, le consommateur est resté derrière, silencieux. `totalDamage` : clé qu'aucun chemin n'écrit. Dans les deux cas **une courbe absente se confond avec une courbe nulle** — c'est exactement pourquoi personne ne l'a vu. |
| `f1647f3a` | `is_hex_adjacent_to_enemy`, `update_units_cache_unit`, et `normalize_coordinates` sur 2 sites | **Zéro appelant de production** pour les deux premières — leurs seuls appelants étaient les tests qui **assertaient la coercition**, un contrat que personne ne consomme. Réponse à la question de fond : c'était une rustine, pas un service rendu ; mais elle ne masquait **aucun appelant fautif de production**. |

### 2.7 Journal de tir : quatre positions `(0,0)` fausses

`e811accd` — `_emit_squad_shoot_log` lisait la position de **l'attaquant** par
`game_state.get("units_cache", {}).get(sid, {}).get("col", 0)` : deux défauts enchaînés, donc
**(0,0) pour une escouade absente du cache**. Le commentaire situé **trois lignes plus bas**
documentait que ce défaut exact avait déjà été corrigé pour la **cible**.

**`(0,0)` est une case RÉELLE du plateau** : ce n'est pas une métrique manquante mais **une donnée
d'analyse fausse**, dans le `step.log` que l'analyzer lit et que le replay rejoue. Le motif existait
à **quatre endroits**, tous corrigés : position d'attaquant du log tir/mêlée, `rec["targetCol"/
"targetRow"]` de `shootDetails`, `_resolve_one_hazard_wound`, `allocate_mortal_wounds`.

### 2.8 Déballages d'environnement unifiés

`d5bb0571` — `BotControlledEnv` et `SelfPlayWrapper` tiraient `self.engine` d'un `cast` sans
vérification, **selon deux règles différentes** : l'un pelait **un** niveau
(`getattr(env, 'env', env)`), l'autre **tous** (`while hasattr(..., 'env')`). L'ordre d'emballage
`Wrapper(ActionMasker(W40KEngine))` n'est garanti nulle part — il est reconstruit à l'identique sur
**huit sites**. Un niveau de plus et `self.engine` pointait silencieusement sur un wrapper.

Remplacé par `unwrap_engine(env, owner)`
([`ai/env_wrappers.py:46`](../../ai/env_wrappers.py#L46)), qui pèle tous les `gym.Wrapper`, vérifie
`ENGINE_CONTRACT_ATTRS` (les 7 membres réellement utilisés) et lève un `TypeError` nommant la pile
traversée. Coût : O(profondeur), **une fois par `__init__`** — aucun coût sur le chemin chaud.

### 2.9 Les sourdines de typage instruites

`7c9ee7ea` — recensement exhaustif, **chacune retirée pour lire ce qu'elle taisait**, puis
tranchée. **20 → 9.** Dont **7 inertes** : des codes **mypy** (`[assignment]`, `[method-assign]`)
alors que le dépôt n'a **ni mypy ni config mypy**. Elles ne taisaient rien — mais un
`# type: ignore` reste actif pour pyright et **aurait avalé une vraie erreur future** sur ces lignes.

État constaté à `d061f21b` : **10 lignes** correspondent au motif, dont **1 est une simple mention
en commentaire** (`ai/pointer_policy.py:254`) ⇒ **9 sourdines réelles**, toutes motivées sur place.

### 2.10 Divers, sans catégorie

- `edc9e765` + `bb3a788f` — quatre fichiers de test **tenaient la phase de déploiement pour
  acquise** : ils ne l'obtenaient que parce que `x1_debug` ne portait **aucun** bloc
  `deployment_mode_schedule`. La rampe livrée par `v11-pre-lot-eval-baseline` (0.0 au premier
  épisode) les a fait tomber en bloc — **le test avait raison d'échouer, il reposait sur une
  ABSENCE de configuration**. Épinglé sur l'**instance** (jamais dans le fichier de config, qui
  porte une décision utilisateur), factorisé dans `tests/unit/engine/_config_helpers.py`.
- `06c035ec` / `93ad5485` / `78c8beff` / `0f4fecd5` / `4cbaac65` / `1bf1be0d` / `dde97ed2` /
  `3e853cba` — annotations rendues honnêtes (protocoles `_UnitRegistryHolder`, `MetricsWriter`,
  `@overload` sur `train_with_scenario_rotation`), casts de complaisance des tests supprimés.
- `1cb2c416` / `6fc3159b` / `194fbe98` — coercitions d'ids retirées là où **un seul type circule**
  (voir §4.3). Sur `charge_handlers`, balayage **à l'AST** : 143 `str(x)`, dont **38 retirées** (le
  paramètre est déjà `str`) et **105 gardées sans exception** (la conversion EST la normalisation
  qui produit la valeur typée depuis un JSON non typé).
- `5466dbea` — mode **Endless Duty** : mesuré par exécution réelle, **jamais démarrable** (7
  obstacles), consigné dans [`A_faire/Endless_duty.md`](A_faire/Endless_duty.md) + un signet
  exécutable. **Aucun correctif livré** — l'état est documenté et instrumenté, pas réparé.

---

## 3. LA DETTE RESTANTE

> **Statut de preuve.** Chaque point porte explicitement ce qui a été **instruit** et ce qui ne
> l'a pas été. Un point non instruit est écrit **non instruit**, jamais « sain » — c'est
> précisément l'erreur que cette campagne a passé la journée à corriger.

### 3.1 🔴 La méthode centrale du moteur reste non analysée — **décision en attente**

- **Où** : `_process_semantic_action`, [`engine/w40k_core.py:3035`](../../engine/w40k_core.py#L3035).
- **Ce que c'est** : **1613 lignes, 205 `if`** (mesuré après campagne ; 1582 / 205 au commit
  `b376f2ae`). pyright refuse d'analyser le corps : *« Code is too complex to analyze »*. La
  sourdine est **désormais motivée par écrit**, mais elle reste — donc la méthode la plus centrale
  du moteur n'a **aucune couverture statique**.
- **Ce qui a été instruit** : la levée temporaire a trouvé **3 défauts réels** (§2.4). Une
  **extraction simple du bloc `step_logger` ne suffit pas** : c'est mesuré, les blocs partagent
  **16 à 50 variables locales**, une extraction naïve rend une signature ingérable.
- **Pourquoi ce n'est pas traité** : faire disparaître la sourdine exige de **décomposer le point
  unique de journalisation** — un changement de structure du dispatcher, pas un refactor local.
  **Décision d'architecture : elle appartient à l'utilisateur.**
- **Effort** : non estimé. À estimer une fois la décomposition arbitrée.

### 3.2 🟠 540 coercitions redondantes — **arrêt décidé**

- **Où** : 33 fichiers ; `engine/phase_handlers/shared_utils.py` en concentre **160**.
- **Ce que c'est** : `str(x)` sur un paramètre déjà annoté `str`, `int(x)` sur un `int`. Même
  contradiction qu'en §2.1 (« si l'annotation dit vrai la conversion est morte, si elle dit faux
  c'est l'annotation qu'il faut corriger »), mais à l'échelle du dépôt.
- **Ce qui a été instruit** : l'**inventaire** a été fait **à l'analyse syntaxique** (AST), pas à
  l'œil. Le tri type par type n'a pas été fait.
- **Pourquoi ce n'est pas traité — arrêt décidé** : le tri **bruit vs frontière** ne peut pas être
  mécanique. Le lot `charge_handlers` (§2.10) l'a montré : 38 sur 143 étaient du bruit, **105
  étaient la normalisation elle-même**, et les retirer aurait échangé un `str` prouvé contre un
  `Any` silencieux — **strictement pire**. Rapport valeur/effort faible.
- ⏳ **Chiffre non reproduit dans cette passe** (aucun outil d'analyse relancé). Ordre de grandeur
  brut par `grep` sur le working tree : `shared_utils.py` porte **214 `str(`** et **349 `int(`**,
  toutes formes confondues — cohérent avec « 160 redondantes », non probant.
- **Priorité : basse.** Explicitement **moins prioritaire que §3.3**.

### 3.3 ✅ TRAITÉ le 2026-07-29 — et la prémisse ci-dessous était **fausse**

> **Correction mesurée (2026-07-29).** L'instrumentation qui a produit ce constat n'a tourné que sur
> **20 fichiers de tests moteur** : elle n'a jamais joué `tests/integration/pvp/`. Réinstrumentées sur
> ce répertoire, **6 des 7 fonctions SONT appelées** par
> [`tests/integration/pvp/test_charge.py`](../../tests/integration/pvp/test_charge.py) —
> `charge_build_valid_targets` 6 appels, `charge_target_selection_handler` /
> `charge_preview_move_plan` / `charge_commit_move_plan_handler` / `_charge_model_pos_is_closer`
> 2 chacune, `charge_autoplace_plan` 1. Couverture ligne mesurée : **62 % à 89 %**.
> Seule `charge_build_model_destinations_pool` était à **1 %** (voir §3.5 : supprimée).
>
> **Le vrai défaut n'était donc pas « aucun test » mais « seulement le chemin nominal »** : une
> escouade mono-figurine qui charge une cible unique et réussit. **Tous les trous étaient du côté du
> refus** — « end closer » (11.04 WHILE MOVING), interdiction d'engager un non-cible (11.04 AFTER
> MOVING), cohérence d'unité (03.03), couverture du plan par toutes les figurines vivantes, jet
> raté non consommé, entrées manquantes de l'autoplace. Une correction fausse sur ces branches
> passait au vert.
>
> **Livré** : [`tests/unit/engine/test_charge_manual_surface.py`](../../tests/unit/engine/test_charge_manual_surface.py)
> — 27 tests sur plateau nu (1 sous-hex = 1", bases 1 hex), chacun construisant sa situation et
> vérifiant ses prémisses avant d'observer le refus. **26 mutations rejouées une par une : les 26
> font rougir le test visé** (dont 2 contrôles positifs, pour qu'un « refuse tout » ne passe pas).
>
> Le constat original est conservé ci-dessous, tel qu'il a été écrit.

### 3.3 (constat d'origine) 🔴 Sept fonctions de la surface PvP manuelle n'ont AUCUN test

- **Où** : `engine/phase_handlers/charge_handlers.py` —
  `charge_autoplace_plan`, `charge_preview_move_plan`, `charge_commit_move_plan_handler`,
  `charge_target_selection_handler`, `charge_build_valid_targets`, `_charge_model_pos_is_closer`,
  `charge_build_model_destinations_pool`.
- **Ce qui a été instruit** : **instrumentation temporaire** des 13 fonctions du module comptant
  les **APPELS** (pas seulement les violations — voir §4.1), sur **20 fichiers de tests moteur**.
  Résultat : 6 fonctions atteintes, **7 jamais appelées par aucun test du dépôt**. C'est la surface
  PvP manuelle, atteignable seulement par l'API avec une session.
- **Conséquence directe, déjà payée** : pour ces 7, la preuve de `194fbe98` est **statique et
  structurelle, pas observée à l'exécution** — l'agent l'a écrit tel quel et refusé de la présenter
  comme un vert de test. **Tout chantier qui les touche se paie en preuve statique faute de rouge
  possible.**
- **Pourquoi ce n'est pas traité** : hors périmètre du lot ; demande un harnais de session API.
  Un tel harnais **existe déjà** — [`scripts/pvp_smoke_test.py`](../../scripts/pvp_smoke_test.py),
  27 checks via l'API sans navigateur — il n'a pas été instruit comme point de départ ici.
- **Effort** : non estimé. **C'est la recommandation la plus forte de la campagne** — elle vaut
  mieux que les 540 coercitions de §3.2.

### 3.4 🟠 Deux motifs de repli non traités

| Motif | Constat (working tree, 2026-07-29) | Nature |
|---|---|---|
| `get("squad_models", <défaut>)` | **13** `.get("squad_models"` au total, dont **10** avec valeur par défaut | **Net** — même nature que les replis corrigés en §2.1. Pas de tri à faire, seulement le travail. |
| `get("occupied_hexes", <défaut>)` | **103** `.get("occupied_hexes"` au total, dont **42** avec valeur par défaut ; **266** occurrences du symbole toutes formes confondues | 🔴 **TRI NÉCESSAIRE** : une partie est un **repli métier documenté** (« utiliser l'ancre faute d'empreinte »), pas un repli anti-erreur. Traiter en bloc régresserait. |

⏳ Les chiffres annoncés en fin de campagne étaient **11 sites** pour `squad_models` et **97
occurrences** pour `occupied_hexes` ; les relevés ci-dessus sont ceux du working tree au moment de
la rédaction (fichiers moteur modifiés par l'utilisateur). L'écart n'est pas instruit.

### 3.5 ✅ `charge_build_model_destinations_pool` — **instruit puis SUPPRIMÉ** (2026-07-29)

- **Preuve en quatre directions (patron §2.6), appliquée** :
  (a) aucun appel ni import — `grep` sur `.py`/`.ts`/`.tsx` ne rendait que sa définition, son propre
  message d'erreur et le commentaire l.4721 ;
  (b) aucune référence par chaîne ni réflexion — le seul `getattr` dynamique du dépôt
  (`ai/bot_evaluation.py:608`) porte sur un pool de processus ;
  (c) **aucune route d'API** — tout le trafic de charge passe par `/api/game/action` → `w40k_core` →
  `charge_handlers.execute_action`, dont le dispatch (chaîne `if/elif` explicite) ne le nomme pas ;
  `api_server.py` n'appelle que les jumeaux **move** et **deployment** du même nom ;
  (d) documentation — `stage.md` le déclarait déjà CODE MORT.
- **Mesuré** : **0 appel** sous instrumentation de la suite de charge (unitaires + intégration PvP),
  1 % de couverture ligne — contre 62-89 % pour les six autres fonctions de §3.3.
- **Contradiction du commentaire l.4721 : tranchée.** Le commentaire était **périmé** — le code de
  `charge_preview_move_plan` appelle `_charge_model_pos_is_closer`, jamais le pool. Commentaire
  corrigé, puis fonction supprimée (148 lignes) avec une trace à l'emplacement du retrait.
- **Raison de fond de ne pas la rebrancher** : elle était restée **2D** (plan provisoire en 2-uplet,
  `level=0` codé en dur) alors que les deux chemins vivants sont niveau-conscients. La ressusciter
  aurait régressé la charge d'étage (§03.04).

### 3.6 🟠 Un cache-miss avalé en silence dans le calcul de distance de charge

- **Où** : `_charge_bfs_max_distance`, `engine/phase_handlers/charge_handlers.py` (~l.594,
  `return rid`).
- **Ce que c'est** : un défaut de cache qui **retourne au lieu de lever**.
- **Pourquoi il compte** : c'est lui qui a **rendu invisible la première mutation d'un agent**
  pendant la campagne — le test ne pouvait pas rougir parce que le miss était absorbé.
- **Statut** : identifié, **non corrigé, non instruit au-delà de ce constat.** Noter que
  `_charge_bfs_max_distance` est l'une des 6 fonctions **effectivement atteintes** par les tests
  (11 appels, §3.3) : le rouge est donc possible ici, contrairement aux 7 autres.

### 3.7 🟠 L'inventaire de `TESTING.md` est globalement périmé

- **Où** : [`Documentation/TESTING.md`](../TESTING.md), 319 lignes.
- **Ce qui existe** : l'**avertissement est en place**, ligne 56 —
  *« ⚠️ Chiffre périmé : « 990 tests, ~2.2s » (2 skipped). L'inventaire ci-dessous n'a pas suivi… »*.
  Deux entrées ont été corrigées ponctuellement (`test_reward_calculator.py`, l.90 ; la largeur de
  parité passée de 103 à 166 actions, `bb3a788f`).
- **Statut** : **aucun relevé complet n'a été fait.** L'avertissement rend le document honnête, il
  ne le rend pas juste. Un relevé exige une collecte réelle (`pytest --collect-only`) qui relève de
  la **vérification large de l'utilisateur**.

---

## 4. Leçons réutilisables

> Formulées pour resservir. Le pendant V11 de cette section est **§0bis** de
> [`V11_agent_rework.md`](V11_agent_rework.md), qui reste la copie canonique des leçons V11 ; celles
> ci-dessous appartiennent à ce chantier.

### 4.1 Le piège du **vert vacant** — un contrôle qui ne regarde rien répond « tout va bien »

**Quatre fois dans la même journée**, un contrôle a rendu vert parce qu'il ne mesurait rien :

| Forme prise | Pourquoi le vert était vide |
|---|---|
| échantillon mal formé | le stub ne ressemblait pas à ce que la production construit ⇒ le chemin testé n'était jamais atteint |
| énumération rendant zéro élément | on affirmait « aucune violation » sur un ensemble vide |
| motif de mutation introuvable | la mutation censée faire rougir ne s'appliquait à aucune ligne |
| instrumentation comptant les **violations** au lieu des **appels** | zéro violation sur zéro appel = zéro information |

**Règle** : un contrôle doit publier **le dénominateur**. Une instrumentation compte les **appels**
avant de compter les violations ; un test de mutation doit être **vu rouge** avant d'être cru vert ;
une doublure typée `Any` satisfait n'importe quel protocole et ne prouve rien (`0f4fecd5`,
`dde97ed2`). Chaque fois, l'agent s'en est sorti **parce qu'il s'en méfiait explicitement** — pas
parce que l'outillage l'a signalé.

### 4.2 Une liste d'audit est une liste de **soupçons**, pas un verdict

Deux fois, un agent a **réfuté l'audit, preuve à l'appui** :

- `1bf1be0d` — un paramètre annoncé **mort** (`_collect_parallel_results_with_timeouts(pool)`) qui
  était en fait **déréférencé** (reforwardé à `_force_terminate_process_pool`). Le `cast` n'existait
  que parce que le test monkeypatchait la terminaison et passait un `object()` nu. **Correctif : le
  test, pas le code.**
- `1cb2c416` — une annotation annoncée **trop étroite** (`unit_id: str`) qui **disait vrai** :
  c'étaient la **docstring** (« int or string ») et la **coercition** (`str(unit_id)`) qui
  mentaient. Trois sources de vérité, deux mensonges.

**Règle** : avant de suivre une ligne d'audit, établir le fait. Le coût d'une réfutation est bien
inférieur au coût d'un correctif appliqué à un défaut inexistant.

### 4.3 Ne pas élargir une annotation « au cas où »

Face à `param: Any` + `str(param)` dans le corps, le réflexe d'élargir en `Optional[...]` ou de
laisser `Any` **fige un laxisme dont aucun appelant n'a besoin, et prive le vérificateur du seul
contrôle possible** (`6fc3159b`).

**Règle** : établir **quel type circule réellement** (instrumentation temporaire sur des épisodes
complets, pas lecture d'intention), puis : **si un seul type circule, on supprime la coercition et
on garde le type strict.** Corollaire (`3e853cba`) : élargir en `Optional[float]` pour justifier un
garde `if x is None: return`, c'est **inventer un appelant**.

### 4.4 Une correction faite d'un côté et pas de son jumeau — motif récurrent

**Trois occurrences dans la journée** :

1. `e67066da` — le repli sur les dégâts : la décision « une valeur de DMG non résoluble doit lever »
   était **déjà écrite dans le même fichier** (`_auto_select_cc_weapon_index`) et n'avait pas été
   propagée aux 4 autres sites ;
2. `5f1878eb` — la migration des compteurs : 4 métriques déplacées, **4 oubliées dans le même
   diff**, neuf mois de silence ;
3. `e811accd` — la position d'attaquant : le défaut avait été corrigé pour la **cible**, et le
   commentaire qui le documentait était **trois lignes au-dessus** du site resté fautif.

**Règle** : quand une correction est appliquée, chercher **le jumeau** — l'autre côté du même
contrat (écriture/lecture, attaquant/cible, tir/mêlée, auto/manuel). Un commentaire qui documente
une correction passée est un **indice de jumeau**, pas une preuve de complétude.

### 4.5 Prouver par la **provenance** plutôt que par la recherche de consommateurs

`a7688806` — plutôt que de chercher tous les lecteurs de `ParsedWeaponRule` (un `grep` qui ne peut
jamais être exhaustif face à la réflexion), l'agent a établi que **son unique site de construction
était mort**. Un type dont le seul producteur ne produit plus **ne peut exister nulle part** : c'est
une preuve d'**inexistence**, strictement plus forte qu'une absence de résultat de recherche.

**Règle** : quand on veut prouver qu'une valeur n'existe pas, remonter à ses **producteurs** (ils
sont peu nombreux et localisables) plutôt que d'énumérer ses **consommateurs** (ils sont ouverts).
Vérification de confirmation possible et bon marché : un **balayage du tas** au runtime
(`gc.get_objects()`).

---

## 5. Limites de preuve de cette campagne

À lire avant de s'appuyer sur ce document.

1. **La vérification large n'a PAS été faite.** Suite de tests complète, `pyright`,
   `ai/hidden_action_finder.py`, `scripts/check_ai_rules.py`, `biome`, `tsc` : elles appartiennent à
   l'utilisateur (CLAUDE.md). Chaque commit porte **ses tests ciblés**, verts et prouvés rouges sous
   mutation — **ce n'est pas la même chose qu'une suite verte.**
2. **Les chiffres du contre-audit (85 / 13 / 66) n'ont pas d'artefact versionné** (§1).
3. **Sept fonctions de `charge_handlers` n'ont aucune preuve d'exécution** (§3.3) — leur preuve est
   statique, et l'agent l'a explicitement refusée comme « vert de test ».
4. **Une branche du lot n'est pas mergée** : `fix-weapon-collection-defaults` (`5980a035`,
   « distinguer *pas d'arme* (liste vide) de *entité mal construite* (clé absente) », 8 fichiers,
   +310/−35, dont un test de contrat de 213 lignes). **En attente parce qu'elle touche exactement
   les quatre fichiers sur lesquels l'utilisateur a du travail en cours**
   (`charge_handlers`, `fight_handlers`, `shared_utils`, `shooting_handlers`, plus `w40k_core`,
   `weapon_helpers`, `main.py`).
5. **Les mesures de §3 datent du 2026-07-29** et ont été prises sur un working tree modifié par
   l'utilisateur.
