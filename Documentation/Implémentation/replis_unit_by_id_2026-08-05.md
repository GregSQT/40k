# Replis silencieux sur `unit_by_id` — le second index — 2026-08-05

**Chantier OUVERT, rien de livré.** Inventaire, pas rapport de travail.

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
| Écrivains | `build_units_cache`, `remove_from_units_cache`, `update_units_cache_*` | `_rebuild_unit_by_id` **uniquement** (`w40k_core.py:6609`) |
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
`_ai_select_fight_target` ([`fight_handlers.py:1602`](../../engine/phase_handlers/fight_handlers.py))
porte depuis le 2026-07-20 (V11 §0.19.2) le raisonnement complet et le `raise` correspondant :

> Le pool vient de `units_cache` : une cible qui y figure mais manque de `unit_by_id` est une
> DÉSYNCHRONISATION D'INDEX, donc un bug. L'ancien `if t:` / `if not target: continue` la sautait
> en silence — si toutes les cibles manquaient, la fonction renvoyait `valid_targets[0]` sans avoir
> scoré quoi que ce soit.

Ce commentaire est le modèle du verdict attendu sur les 59 sites ci-dessous.

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
| [`engine/combat_utils.py:95`](../../engine/combat_utils.py) | `get_unit_by_id(game_state, unit_id)` | **non**, et le docstring dit que la coercition serait un défaut |
| [`engine/game_utils.py:51`](../../engine/game_utils.py) | `get_unit_by_id(unit_id, game_state)` | oui |
| [`shooting_handlers.py:6058`](../../engine/phase_handlers/shooting_handlers.py) | `_get_unit_by_id(game_state, unit_id)` | oui |
| [`w40k_core.py:6213`](../../engine/w40k_core.py) | `self._get_unit_by_id(unit_id)` | délègue à `game_utils` |

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

## 3. Inventaire — 186 appels, 59 replis

Relevé à l'AST : tout appel `get_unit_by_id(` / `_get_unit_by_id(` dans `engine/`, `ai/`,
`services/`, classé par ce qui suit dans les 4 lignes. **Dénominateur brut publié exprès** (leçon
§4.1 de la campagne : un contrôle qui ne regarde rien répond « tout va bien »).

| Catégorie | N |
|---|---|
| **déjà bruyants** (`raise` dans les 4 lignes) | **82** |
| **replis** (Formes B et C ci-dessous) | **59** |
| **sans repli détecté dans la fenêtre** — à LIRE, forme D | **45** |
| `# get allowed` | 0 |
| **total** | **186** |

Le ratio 82/186 déjà bruyants est le fait marquant : **ce dépôt a déjà tranché ce contrat, à 44 %.**
Le travail est de finir une conversion commencée, pas d'imposer une règle nouvelle. C'est l'argument
le plus solide du lot, et il est vérifiable en une commande.

### Forme B — `if x is None: return <valeur>` — 48 sites

Le refus est explicite mais **muet sur sa cause** : l'appelant ne distingue pas « pas de cible » de
« index désynchronisé ».

**Sous-forme B1 — `return` nu (3)** — les plus insidieuses : la fonction rend `None`/rien et
l'appelant continue.

| Site | Fonction |
|---|---|
| `shooting_handlers.py:1192` | `build_unit_los_cache` |
| `shooting_handlers.py:1876` | `_rebuild_los_cache_for_unit` |
| `services/api_server.py:916` | `_attach_shoot_visible_cells` |

**Sous-forme B2 — `return <valeur>` (45)**

| Fichier | Fonctions (ligne) |
|---|---|
| `charge_handlers.py` (13) | `_charge_footprint_union_for_anchors` (312), `execute_action` (1219), `charge_model_plan_state` (2464), `charge_build_valid_targets` (2651), `charge_unit_execution_loop` (2786), `charge_build_valid_destinations_pool` (3338, 3364, 3376), `charge_target_selection_handler` (4058), `charge_autoplace_plan` (4692), `charge_set_fly_mode_handler` (5365), `charge_commit_move_plan_handler` (5437), `charge_destination_selection_handler` (5605) |
| `movement_handlers.py` (11) | `squad_descent_penalty_subhex` (394), `execute_action` (926), `movement_set_advance_mode_handler` (1044), `movement_set_fly_mode_handler` (1081), `movement_unit_execution_loop` (1161), `movement_build_valid_destinations_pool` (2630), `movement_build_model_destinations_pool` (3491), `movement_commit_move_plan_handler` (4181), `movement_click_handler` (4341, 4349), `movement_destination_selection_handler` (4385) |
| `shooting_handlers.py` (8) | `preview_hidden_models_from_position` (1090), `preview_hidden_models_from_model_positions` (1150), `preview_shoot_valid_targets_from_position` (1410, 1469), `_should_auto_activate_next_shooting_unit` (2106), `shooting_unit_activation_start` (2398), `execute_action` (5653) |
| `fight_handlers.py` (5) | `_fight_pile_in_build_model_pool` (3197), `pile_in_autoplace_plan` (3758), `consolidate_autoplace_plan` (4309), `_fight_consolidation_build_model_pool` (4522), `_manual_roll_fight_intent` (5432) |
| `shared_utils.py` (5) | `unit_is_on_battlefield` (1293), `unit_is_in_strategic_reserves` (1305), `_shoot_engagement_blocks_target` (6011) ⬅ **le site d'origine**, `resolve_squad_shooting_type` (7035), `squad_model_shootable_weapon_indices` (7112) |
| `w40k_core.py` (2) | `_handle_hazard_confirm` (3592), `_process_squad_manual_shoot` (4237) |
| `action_decoder.py` (1) | `_get_eligible_units_for_current_phase` (511) |
| `reward_calculator.py` (1) | `_calculate_on_objective_reward` (1258) |

⚠️ **`unit_is_on_battlefield` et `unit_is_in_strategic_reserves` (shared_utils 1289/1299) sont à
traiter EN PREMIER dans cette forme**, et pour une raison lue dans le code, pas supposée :

- Les deux rendent `False` sur `None`. Un même id inconnu est donc **à la fois** « pas sur la
  table » et « pas en réserves » — deux réponses qui ne peuvent pas être vraies ensemble (20.01 :
  une unité est l'un ou l'autre).
- 🔴 Le docstring de `unit_is_on_battlefield` dit : *« Une unité absente de `units_cache` est morte,
  donc pas sur le champ de bataille »*. **Le code n'interroge pas `units_cache`** : il appelle
  `get_unit_by_id`, donc `unit_by_id`, où l'absence ne veut PAS dire morte. Le commentaire justifie
  un contrat que la ligne en dessous n'applique pas. C'est le repli et sa justification qui sont
  tous les deux à reprendre — ne pas se contenter de convertir l'appel.

**Reachabilité, à borner honnêtement** : ces deux `False` ne peuvent pas tomber sur une unité morte
(les morts restent dans `unit_by_id`), seulement sur un id réellement inconnu. Le scénario est donc
une contradiction logique PROUVÉE, mais son déclenchement en production reste à établir par les
appelants. Ne pas l'annoncer comme un bug observé.

### Forme C — `if x is None: continue` — 11 sites (dont 1 dans du CODE MORT → 10 à traiter)

**Pire que B** : l'élément disparaît de l'énumération sans trace.

| Site | Fonction |
|---|---|
| ~~`fight_handlers.py:1503`~~ | ~~`_ai_select_consolidation_destination`~~ — **CODE MORT** (0 référence AST, cf. `replis_units_cache_2026-08-05.md` §8). Ne pas corriger, ne pas tester. |
| `shared_utils.py:9189` | `squad_fight_activation_order` |
| `shared_utils.py:9787` | `squad_declare_fight` |
| `shooting_handlers.py:706` | `weapon_availability_check` |
| `shooting_handlers.py:1056` | `compute_hidden_statuses` |
| `shooting_handlers.py:1259` | `build_unit_los_cache` |
| `shooting_handlers.py:1623` | `build_visible_cells_by_target` |
| `shooting_handlers.py:1670` | `build_hidden_too_far_by_unit_id` |
| `shooting_handlers.py:1775` | `build_hidden_detection_info_by_unit_id` |
| `shooting_handlers.py:2138` | `_unit_has_firable_target` |
| `w40k_core.py:3155` | `_enqueue_rule_choice_candidates` |

⚠️ **`squad_fight_activation_order` (9189) est le site le plus grave de la liste**, et c'est
vérifié : la boucle est `for sid, entry in entries_on_battlefield(units_cache)`, donc **chaque `sid`
sort de `units_cache`** — un manque dans `unit_by_id` est par construction une désynchronisation
d'index. Le `continue` retire alors l'escouade du dict `eligible`, c'est-à-dire **une activation de
combat qui ne se produit pas**. Ce n'est pas un verdict géométrique faux, c'est un tour de jeu
perdu. C'est aussi *exactement* la condition pour laquelle `_ai_select_fight_target`
(`fight_handlers.py:1602`) lève déjà : le contrat est écrit, il n'est pas appliqué ici.
À instruire en premier, à verrouiller par un test qui COMPTE les activations.

Note relevée en passant, même fonction (`shared_utils.py:9199`) :
`int(units_cache.get(sid, {}).get("player", -1))  # get allowed` — un `player = -1` de repli, du
même genre que les trois corrigés au lot `units_cache`. Hors périmètre de ce document (c'est
`units_cache`, pas `unit_by_id`) : signalé, pas classé.

Note : 4 de ces 11 (`build_hidden_too_far_by_unit_id`, `build_hidden_detection_info_by_unit_id`,
`_unit_has_firable_target`, plus `compute_hidden_statuses`) sont dans des fonctions dont le volet
`units_cache` vient d'être traité par le lot précédent — leur contrat d'appelant est donc **déjà
établi et écrit dans le code**. Commencer par elles : le coût d'investigation y est nul.

### Forme D — 45 appels sans repli dans la fenêtre — à LIRE

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
| **T0** | **Unifier les 4 implémentations en une** + écrire le jumeau bruyant `require_unit_by_id`. Décision de signature à l'utilisateur. Rien d'autre. | ½ session |
| **T1** | Forme C, 11 sites, en commençant par `squad_fight_activation_order` (activation perdue) et les 4 dont le contrat est déjà écrit par le lot `units_cache`. | 1 session |
| **T2** | Forme B, 48 sites, en commençant par `unit_is_on_battlefield` / `unit_is_in_strategic_reserves` (deux réponses contradictoires sur le même id). `charge_handlers` (13) et `movement_handlers` (11) dominent : les prendre par fichier. | 2 sessions |
| **T3** | Forme D, 45 appels. Lecture d'abord, classement ensuite. | 1 session |

Repère de coût mesuré : le lot `units_cache` a traité 47 sites sur 5 fichiers en une session, tests
et mutations compris — mais avec l'outil déjà livré et un contrat déjà établi par un lot antérieur.
Ici T0 n'existait pas. **Ne pas prendre les 59 en bloc.**

**Ne PAS faire** : un balayage mécanique forme par forme sans contrat d'appelant.

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
