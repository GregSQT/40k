# Replis silencieux sur `unit_by_id` — le second index — 2026-08-05

**Chantier CLOS.** T0→T4-ter livrés (2026-08-25). 0 garde is-None résiduelle sur `get_unit_by_id` dans les 7 fichiers T3 (re-grep final T4-ter : 4 hits légitimes conservés).

**T4-ter (2026-08-25)** — 39 conversions supplémentaires dans 6 fichiers (`shared_utils`, `shooting_handlers`, `observation_builder`, `w40k_core`, `charge_handlers`, `action_decoder`). T4-bis n'avait couvert que `shared_utils` + `action_decoder` partiellement ; le re-grep T4-bis ne portait pas sur les 7 fichiers T3. 17 tests ROUGE→VERT dans `test_require_unit_by_id_residuals.py`. 4 gardes conservées : `w40k_core` 5307 (entrée externe API), `charge_handlers` 3638/3650/4404 (condition composée sur cibles déclarées par le joueur).

🔴 **CHIFFRES À NOUVEAU PÉRIMÉS — re-mesurés le 2026-08-06 sur `main` (`d7be203e`) :
186 appels, 79 déjà bruyants, 56 replis, 51 à lire.**
C'est la DEUXIÈME dérive de cet inventaire en deux jours (198/78/56/64 la veille). La leçon n'est
pas « recompter » mais **ne jamais partir des chiffres écrits** : les relever soi-même en ouvrant
le chantier, avec le script du §3. Les tableaux par site ci-dessous gardent leur valeur (ils
nomment des FONCTIONS, pas des lignes), les totaux non.

🔴 **Premier recalage, conservé pour mémoire (`e672683a`).** Le premier relevé avait été
fait DANS le worktree du lot `units_cache`, donc sur un arbre qui ignorait à la fois les avancées
de `main` (réserves 20.01, registre `_once_claims` — ~2 783 lignes) et les 38 suppressions de code
mort de ce lot. Écarts constatés : 198 appels (et non 186), 78 déjà bruyants (et non 82), **56
replis** (et non 59), 64 à lire (et non 45). **Leçon : un inventaire relevé dans un worktree se
périme au merge — le re-mesurer avant d'ouvrir le chantier, jamais le reprendre tel quel.**

**Vérifié le 2026-08-05, rien n'a été fait entre-temps** : `require_unit_by_id` n'existe nulle part
(`grep -rn "require_unit_by_id"` → 0 hit) et les QUATRE implémentations de `get_unit_by_id` sont
toujours en place, ordres d'arguments contradictoires compris.

**Origine** : signalé en clôture du lot `units_cache`
([`replis_units_cache_2026-08-05.md`](replis_units_cache_2026-08-05.md) §7). Un site y est resté
non traité — `_shoot_engagement_blocks_target`, `shooter_unit is None → return False` — parce qu'il
lit `units`, pas `units_cache`. Le grep qui a suivi a montré que ce n'était pas un site isolé.

**Convention d'ancrage** : l'ancre de référence est le **nom de fonction** ; les numéros de ligne
sont indicatifs, relevés le 2026-08-05. Re-localiser par `grep` avant d'éditer.

---

## 1. Le défaut — et pourquoi il n'est PAS le même que celui de `units_cache`

🔴 **Lire cette section AVANT de recopier la méthode du lot précédent. Le contrat est INVERSÉ.**

| | `units_cache` (lot clos) | `unit_by_id` (ce lot) |
|---|---|---|
| Écrivains | `build_units_cache`, `remove_from_units_cache`, `update_units_cache_*` | `_rebuild_unit_by_id` **uniquement** (`w40k_core.py`) |
| Quand | à chaque mutation, et **à chaque mort** | au reset / reload / chargement de scénario, **jamais en cours de partie** |
| Une unité morte y est ? | **NON** — l'absence EST l'encodage de la mort | **OUI** — `game_state["units"]` n'est jamais purgé |
| Donc `.get()` → `None` signifie | « morte », souvent un cas métier | **id inconnu / index désynchronisé — jamais un cas de jeu** |

Conséquence directe, et c'est tout l'intérêt de ce lot : sur `units_cache`, environ un site sur
quatre était un refus métier légitime qu'il fallait préserver. Ici, **il n'y en a a priori aucun** —
un `None` ne peut pas vouloir dire « morte », puisque les morts restent dans `units`. Tout repli est
donc suspect par défaut.

⚠️ **Mais « suspect par défaut » n'est pas « à convertir en masse ».** L'inversion du contrat rend
le tri PLUS facile, pas inutile : il reste à vérifier par site que l'id passé vient bien d'une
source qui garantit son existence (pool, `units_cache`, `squad_models`) et non d'une entrée
utilisateur ou d'un champ optionnel. C'est exactement la leçon §3.2 de la campagne, et elle ne
s'annule pas parce que le contrat est plus net.

**Précédent DÉJÀ ÉCRIT dans le dépôt**, à réutiliser tel quel comme argument :
`_ai_select_fight_target` ([`fight_handlers.py`](../../../engine/phase_handlers/fight_handlers.py))
porte depuis le 2026-07-20 (V11 §0.19.2) le raisonnement complet et le `raise` correspondant :

> Le pool vient de `units_cache` : une cible qui y figure mais manque de `unit_by_id` est une
> DÉSYNCHRONISATION D'INDEX, donc un bug. L'ancien `if t:` / `if not target: continue` la sautait
> en silence — si toutes les cibles manquaient, la fonction renvoyait `valid_targets[0]` sans avoir
> scoré quoi que ce soit.

Ce commentaire est le modèle du verdict attendu sur les 56 sites ci-dessous.

---

## 2. L'outil MANQUE — c'est le premier livrable, pas une note de bas de page

Le lot `units_cache` disposait de `require_unit_from_cache`, livré par le lot charge. **Ici, rien
d'équivalent n'existe.** Écrire le jumeau bruyant est la tranche T0, et elle doit être faite AVANT
tout site — sinon le lot réécrit des `raise` à la main, et la revue du lot charge a mesuré ce que ça
donne : la même condition levait `KeyError`, `ValueError` et `ConfigurationError` selon le site,
dont `ValueError` qui est un canal de **refus métier** ailleurs dans le moteur et se fait avaler par
des `except ValueError`.

🔴 **Complication propre à ce lot : il y a QUATRE implémentations du même lookup, dont deux avec
l'ordre des arguments INVERSÉ.**

| Implémentation | Signature | `str()` sur l'id ? |
|---|---|---|
| [`engine/combat_utils.py`](../../../engine/combat_utils.py) | `get_unit_by_id(game_state, unit_id)` | **non**, et le docstring dit que la coercition serait un défaut |
| [`engine/game_utils.py`](../../../engine/game_utils.py) | `get_unit_by_id(unit_id, game_state)` | oui |
| [`shooting_handlers.py`](../../../engine/phase_handlers/shooting_handlers.py) | `_get_unit_by_id(game_state, unit_id)` | oui |
| [`w40k_core.py`](../../../engine/w40k_core.py) | `self._get_unit_by_id(unit_id)` | délègue à `game_utils` |

Les trois premières font *exactement* la même chose : `require_key(game_state, "unit_by_id").get(...)`.
Deux positions de `str()` divergentes, deux ordres d'arguments contradictoires.

**Ce qui est mesuré, et ce qui ne l'est pas** : l'inversion d'arguments est aujourd'hui rattrapée
par `pyright` (`Dict` vs `str` sur le premier paramètre) — 6 modules importent l'une ou l'autre
variante et le type-check passe. Ce n'est donc **pas** un bug actif, c'est un piège de maintenance.
Ne pas le vendre comme une panne : le vendre comme la raison de n'avoir qu'UNE implémentation à la
sortie de ce lot.

**Décision à prendre en T0** (elle appartient à l'utilisateur, pas à l'agent) : unifier sur une
seule signature — et laquelle. Le reste du lot en dépend.

---

## 3. Inventaire — 198 appels, 56 replis

Relevé à l'AST : tout appel `get_unit_by_id(` / `_get_unit_by_id(` dans `engine/`, `ai/`,
`services/`, classé par ce qui suit dans les 4 lignes. **Dénominateur brut publié exprès** (leçon
§4.1 de la campagne : un contrôle qui ne regarde rien répond « tout va bien »).

| Catégorie | N (recalé sur `e672683a`) |
|---|---|
| **déjà bruyants** (`raise` dans les 4 lignes) | **78** |
| **replis** (Formes B et C ci-dessous) | **56** |
| **sans repli détecté dans la fenêtre** — à LIRE, forme D | **64** |
| `# get allowed` | 0 |
| **total** | **198** |

Le ratio 78/198 déjà bruyants est le fait marquant : **ce dépôt a déjà tranché ce contrat, à 39 %.**
Le travail est de finir une conversion commencée, pas d'imposer une règle nouvelle. C'est l'argument
le plus solide du lot, et il est vérifiable en une commande.

### Forme B — `if x is None: return <valeur>` — 46 sites

Le refus est explicite mais **muet sur sa cause** : l'appelant ne distingue pas « pas de cible » de
« index désynchronisé ». Relevé sur `e672683a`, hors `tests/`.

| Fichier | Fonctions (ligne) |
|---|---|
| `engine/phase_handlers/charge_handlers.py` (13) | _charge_footprint_union_for_anchors (312), charge_autoplace_plan (4640), charge_build_valid_destinations_pool (3286), charge_build_valid_destinations_pool (3312), charge_build_valid_destinations_pool (3324), charge_build_valid_targets (2632), charge_commit_move_plan_handler (5385), charge_destination_selection_handler (5553), charge_model_plan_state (2445), charge_set_fly_mode_handler (5313), charge_target_selection_handler (4006), charge_unit_execution_loop (2767), execute_action (1200) |
| `engine/phase_handlers/fight_handlers.py` (5) | _fight_consolidation_build_model_pool (3620), _fight_pile_in_build_model_pool (2319), _manual_roll_fight_intent (4533), consolidate_autoplace_plan (3435), pile_in_autoplace_plan (2884) |
| `engine/phase_handlers/movement_handlers.py` (11) | execute_action (931), movement_build_model_destinations_pool (3502), movement_build_valid_destinations_pool (2641), movement_click_handler (4352), movement_click_handler (4360), movement_commit_move_plan_handler (4192), movement_destination_selection_handler (4396), movement_set_advance_mode_handler (1055), movement_set_fly_mode_handler (1092), movement_unit_execution_loop (1172), squad_descent_penalty_subhex (398) |
| `engine/phase_handlers/shared_utils.py` (5) | _shoot_engagement_blocks_target (5991), resolve_squad_shooting_type (7015), squad_model_shootable_weapon_indices (7092), unit_is_in_strategic_reserves (1311), unit_is_on_battlefield (1299) |
| `engine/phase_handlers/shooting_handlers.py` (8) | _should_auto_activate_next_shooting_unit (1935), build_unit_los_cache (1159), execute_action (5271), preview_hidden_models_from_model_positions (1117), preview_hidden_models_from_position (1057), preview_shoot_valid_targets_from_position (1334), preview_shoot_valid_targets_from_position (1393), shooting_unit_activation_start (2227) |
| `engine/reward_calculator.py` (1) | _calculate_on_objective_reward (1256) |
| `engine/w40k_core.py` (2) | _handle_hazard_confirm (3585), _process_squad_manual_shoot (4230) |
| `services/api_server.py` (1) | _attach_shoot_visible_cells (951) |

⚠️ **`unit_is_on_battlefield` (1299) et `unit_is_in_strategic_reserves` (1311) restent à traiter EN
PREMIER** dans cette forme, pour la raison lue dans le code et rappelée ci-dessous : les deux
rendent `False` sur le même id inconnu — « ni sur la table, ni en réserves » — et le docstring de
la première justifie un contrat `units_cache` que la ligne en dessous n'applique pas (elle lit
`unit_by_id`). Le repli ET sa justification sont à reprendre.

### Forme C — `if x is None: continue` — 10 sites

**Pire que B** : l'élément disparaît de l'énumération sans trace.

| Fichier | Fonctions (ligne) |
|---|---|
| `engine/phase_handlers/shared_utils.py` (2) | squad_declare_fight (9776), squad_fight_activation_order (9169) |
| `engine/phase_handlers/shooting_handlers.py` (7) | _unit_has_firable_target (1967), build_hidden_detection_info_by_unit_id (1698), build_hidden_too_far_by_unit_id (1594), build_unit_los_cache (1226), build_visible_cells_by_target (1547), compute_hidden_statuses (1023), weapon_availability_check (673) |
| `engine/w40k_core.py` (1) | _enqueue_rule_choice_candidates (3146) |

⚠️ **`squad_fight_activation_order` (9169) reste le site le plus grave**, et c'est vérifié : sa
boucle est `for sid, entry in entries_on_battlefield(units_cache)`, donc chaque `sid` sort du
cache — un manque dans `unit_by_id` est par construction une désynchronisation d'index. Le
`continue` retire l'escouade du dict `eligible`, c'est-à-dire **une activation de combat qui ne se
produit pas**. C'est exactement la condition pour laquelle `_ai_select_fight_target` lève déjà :
le contrat est écrit, il n'est pas appliqué ici. À verrouiller par un test qui COMPTE les
activations.

✅ **Deux sites de la Forme C ont DISPARU depuis le premier relevé** :
`_ai_select_consolidation_destination` et `build_hidden_*` volet tireur — le premier était du code
mort supprimé par le lot `units_cache` (cf. son §8), les autres ont changé de forme. Ne pas
chercher à les retrouver.

### Forme D — 64 appels sans repli dans la fenêtre — à LIRE

Aucune hypothèse posée. Ce sont les appels dont les 4 lignes suivantes ne contiennent ni `raise` ni
garde `is None`. Deux possibilités, indiscernables sans lecture :
- l'appelant déréférence directement → il **crashe** sur `None`, c'est déjà bruyant (bien) ;
- le `None` se propage plus loin → repli à retardement, le pire cas (l'erreur sort loin du site).

Commande de reprise :
```bash
python3 - <<'EOF'
# même script AST que §3, filtrer sur la catégorie "sans repli detecte"
EOF
```

---

## 4. Méthode imposée (identique au lot `units_cache`, un point ajouté)

1. **Établir le contrat d'appelant AVANT de toucher.** Remonter les appelants, citer `fichier:ligne`.
   **Corollaire** : un site qui remonte le manque dans une structure de sortie (`missing_*`, liste
   d'erreurs, drapeau) n'est PAS classable « métier » sans lire ce que l'appelant fait de cette
   structure — le piège mesuré sur `charge_preview_move_plan`.
2. **Chercher le code mort d'abord.** Patron de preuve en quatre directions : (a) aucun appel ni
   import, (b) aucune référence par chaîne ni réflexion, (c) aucune route d'API ni chemin frontend,
   (d) aucune mention en documentation.
   🔴 **La direction (d) N'EST PAS un veto — mesuré le 2026-08-05.** Une mention en documentation
   peut être PÉRIMÉE : `_fight_plan_consolidation_destinations` était citée par quatre documents,
   dont deux édités APRÈS la disparition de son appelant, et elle était bien morte. Quand (a),
   (b) et (c) sont vides, la bonne suite est `git log -S"<nom>("` pour dater la disparition de
   l'appelant : si elle correspond à une purge délibérée, la fonction est un résidu de purge et
   les documents sont à corriger, pas à respecter.
   🔴 **Sur ce dépôt, 10 des fonctions privées de `fight_handlers.py` sont orphelines** (~641 l.).
   Le lot `unit_by_id` en touche au moins une (`_ai_select_consolidation_destination`, Forme C) :
   passer le balayage AST AVANT de traiter le moindre site. Le lot charge a supprimé 49 lignes plutôt que d'y corriger
   deux sites ; le lot `units_cache` a supprimé deux copies d'un jumeau parfait.
3. **Vérifier le jumeau frontend.** Ne pas propager un correctif sans regarder.
4. **Prouver le verrou par mutation.** Remettre le repli, voir le test ROUGE, rétablir, le rapporter.
   Un test qui passe du premier coup n'est pas un verrou.
5. **Borner le verdict.** Beaucoup de sites seront précédés d'une garde qui mord d'abord et rend le
   `raise` statiquement inatteignable. La preuve est alors **statique** et doit être écrite comme
   telle — pas présentée comme un vert de test. Sur le lot `units_cache`, c'était le cas de la
   moitié des sites.
6. 🔴 **NOUVEAU, et c'est la leçon la plus chère du lot précédent : l'inventaire borne un périmètre
   de LECTURE, jamais un périmètre de DÉFAUT.** Le balayage AST de `units_cache` ne couvrait que les
   quatre modules de phase ; un `grep` dépôt entier sur le motif corrigé a rendu **7 sites de plus**
   dans `ai/evaluation_bots.py`, plus dangereux que ceux de l'inventaire — dont un écrit sous une
   forme syntaxique différente (`if x is not None: … else: …`) qui a survécu au premier grep.
   **À la fin de CE lot : re-grepper le motif corrigé sur tout le dépôt, sous ses deux formes, et
   publier le résultat même vide.**
7. 🔴 **Se méfier des tests qui valident le repli.** Deux tests de `test_evaluation_bots.py`
   construisaient un `units_cache` VIDE avec `is_unit_alive` doublé à `True` : ils exigeaient le
   repli pour passer. Un test rouge après correction n'est pas forcément une régression — lire
   l'état qu'il construit avant de conclure.

---

## 5. Découpage recommandé

| Tranche | Contenu | Charge |
|---|---|---|
| **T0** ✅ | **Unifier les 4 implémentations en une** + écrire le jumeau bruyant `require_unit_by_id`. Décision de signature à l'utilisateur. Rien d'autre. | ½ session |
| **T1** ✅ | Forme C, 9 sites traités (10 - 1 déjà Forme B). `squad_fight_activation_order` → supprimé (code mort, 0 appelant depuis fb7e83b6). 7 sites shooting_handlers + `_enqueue_rule_choice_candidates` w40k_core → `require_unit_by_id`. T2 bonus : résidu waaagh w40k_core:4326. Grep 0 résidu. Commit dff4e8f0 (2026-08-25). | 1 session |
| **T2** ✅ | Forme B, 46 sites. `charge_handlers` (1), `fight_handlers` (2+5), `shared_utils`, `shooting_handlers` — tous convertis + `charge_preview_move_plan` bonus. Grep 0 résidu. Commit bf139af5 (2026-08-25). | 2 sessions |
| **T3** ✅ | Forme D, 20 sites convertis dans 7 fichiers (action_decoder, charge_handlers, fight_handlers, shared_utils, shooting_handlers, observation_builder, w40k_core). `display_save_threshold_with_waaagh` et `_select_fight_weapon_indices_for_fig` non-Optionnalisées. Mutation ROUGE→VERT confirmée. Clôture : 74 gardes résiduelles = Forme B/C futures ou entrée externe légitime (scripts/_t3_closture_grep.py). Commit 43521169 (2026-08-25). | 1 session |
| **T4** ✅ | Forme B résiduelle, 15 sites fight_handlers.py non couverts par T2 (flux manuel PvP pile-in/fight/consolidate + _ai_select_fight_target + _fight_auto_defender). Import `get_unit_by_id` retiré. Tests mis à jour (ValueError/KeyError → ConfigurationError sur 2 cas). Mutation ROUGE→VERT confirmée. Commit 29ea9fea (2026-08-25). | ½ session |
| **T4-bis** ✅ | Gardes résiduelles (fenêtre 4 lignes post-`get_unit_by_id`) dans les 7 fichiers du T3 : 7 sites convertis (shared_utils ×6, action_decoder ×1) + import `require_unit_by_id` manquant dans action_decoder (NameError latent depuis T3). 9 tests, mutation ROUGE→VERT par site. Re-grep global : 0 garde is-None résiduelle sur `get_unit_by_id` dans le moteur. Commit 3645a5c8 (2026-08-25). | ½ session |

Repère de coût mesuré : le lot `units_cache` a traité 47 sites sur 5 fichiers en une session, tests
et mutations compris — mais avec l'outil déjà livré et un contrat déjà établi par un lot antérieur.
Ici T0 n'existait pas. **Ne pas prendre les 59 en bloc.**

**Ne PAS faire** : un balayage mécanique forme par forme sans contrat d'appelant.

🔴 **AVANT LE PREMIER SITE, deux gestes que le lot `units_cache` a payé cher pour apprendre** :
1. **Re-mesurer l'inventaire** (les chiffres ci-dessus datent de `e672683a` et se périmeront) ;
2. **Passer le balayage de code mort** — ce lot a corrigé, puis TESTÉ, trois fonctions sans
   appelant, dont une que seul son propre test neuf faisait paraître vivante. Un détecteur de code
   mort doit énumérer par parcours disque (pas `git ls-files`, qui ignore le non-suivi) et exclure
   `tests/` du décompte des appelants.

---

## 6. Limites de preuve de ce document

1. **Aucune correction livrée.** Inventaire, pas rapport de travail.
2. **Le tri B/C/D est syntaxique**, pas sémantique : il classe la **forme** du repli, pas sa
   légitimité. Les ⚠️ signalés (`squad_fight_activation_order`, `unit_is_on_battlefield`) sont les
   deux seuls à porter un **scénario d'échec concret** ; tout le reste est un soupçon.
3. **La fenêtre de détection est de 4 lignes** après l'appel. Un repli plus loin est classé « sans
   repli détecté » (forme D) — le chiffre 59 est donc un **plancher**, pas un total.
4. **Les 82 « déjà bruyants » n'ont pas été relus.** Ils sont comptés sur la présence d'un `raise`
   dans la fenêtre, pas sur la justesse de ce `raise`. Le lot charge a trouvé trois types
   d'exception différents pour une même condition : ce compartiment mérite sa propre passe.
5. **`ai/` n'a rendu aucun site** dans ce relevé (0 appel `get_unit_by_id` hors `engine/` et
   `services/`). Ce n'est pas une preuve d'absence de motif : `evaluation_bots` a ses propres
   lookups sur `game_state["units"]` par compréhension, hors de la portée de ce grep.
6. **Aucune vérification large** n'a été lancée : elle appartient à l'utilisateur (CLAUDE.md).
