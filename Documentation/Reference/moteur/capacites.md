# Capacités — socle obs/action, CP, capacités de faction, réserves, et le chantier Armageddon

> **Objet** : référence de conception consolidée du système de capacités — le socle observation/action (embedding des capacités), les points de commandement et le battle-shock, les capacités de faction (Waaagh!, Oath of Moment), les réserves stratégiques / Deep Strike, et le chantier ouvert 06 (capacités d'unité Armageddon).
> **Sources absorbées** : `01_ability_embedding.md`, `02_command_points.md`, `03_faction_abilities.md`, `04_strategic_reserves.md` (Reference/moteur) et `06_armageddon_abilities.md` (Chantiers/backlog) — elles partent dans `Documentation/Archives/docs/` avec un bandeau retour.
> **L'état des chantiers fait foi dans `Documentation/Roadmap/`, jamais ici** — pour le 06 : [Roadmap/capacites.md](../../Roadmap/archives/capacites.md) ; ordre global : [ROADMAP_INDEX.md](../../Roadmap/ROADMAP_INDEX.md).
> Chiffres volatils (`obs_size`, `TOTAL_ACTION_SIZE`, `obs_id` occupés) : jamais recopiés ici — les emplacements où les lire sont donnés à chaque fois.

---

# 1. Le socle obs/action — embedding des capacités

## Pourquoi ce socle existe

Avant le chantier 01, chaque entité d'unité de l'observation portait un bit par capacité connue du moteur (bits `rule_<id>` dans `UNIT_BIN_FIELDS`). Ce schéma grossissait linéairement avec le nombre de capacités du jeu : chaque capacité ajoutée changeait `UNIT_BIN_SIZE`, donc `obs_size`, donc invalidait tout modèle entraîné (`retrain --new`), et chaque faction ultérieure en coûtait un de plus.

L'objectif du socle est de **rendre le coût nul** : ajouter une capacité, un statut ou une faction entière ne change ni `obs_size`, ni le nombre de paramètres du réseau, ni l'action space. Aucun retrain.

## Le mécanisme : deux ensembles d'identifiants entiers

Chaque unité porte deux **ensembles d'identifiants entiers**, pas des bitmaps :

| Champ | Contenu | Cardinal |
|---|---|---|
| `ability_ids` | capacités **en vigueur** (règle 19.04 : union des sources vivantes) | `UNIT_ABILITY_SLOTS` (8) |
| `status_ids` | statuts **en vigueur** (`battle_shock`, `oath_target`, `suppressed`) | `UNIT_STATUS_SLOTS` (4) |

Les constantes vivent dans `engine/observation_entities.py` (tenseurs `allies_ability_ids`, `allies_status_ids`, `enemies_ability_ids`, `enemies_status_ids`). Ces entiers alimentent deux `EmbeddingBag` **distinctes** (`def _id_bag`, `ai/spatial_extractor.py`), pré-dimensionnées à `OBS_ID_VOCAB_SIZE` lignes (padding + `[OBS_ID_MIN, OBS_ID_MAX]`, soit `[1, 127]`), avec `padding_idx = 0`, pooling **somme**. Les deux sorties sont concaténées et rejoignent l'encodeur d'entité partagé. Les tables sont pré-dimensionnées et **jamais ajustées** au nombre de capacités existantes — c'est ce qui rend l'ajout gratuit en paramètres.

### Pourquoi aucun one-hot n'apparaît

Un `EmbeddingBag` fait une **lecture de ligne** `table[id]`. Le one-hot n'est jamais matérialisé, ni dans l'observation, ni dans le réseau. L'observation transporte des entiers. C'est ce qui rend la longueur du vecteur indépendante du nombre de capacités existantes.

### Pourquoi deux tables et pas une

Une capacité (« cette unité a Feel No Pain ») et un statut (« cette unité est la cible Oath adverse ») sont de nature différente. Un pooling commun les additionnerait dans le même espace et le réseau ne pourrait plus les distinguer. Deux tables, deux poolings, concaténation.

### Pourquoi le pooling somme

- **Invariance par permutation** : `{A, B}` écrit en (slot0, slot1) ou (slot1, slot0) produit le même vecteur. C'est la propriété qui disqualifiait les « slots » naïfs.
- **Multiplicité préservée** : contrairement à la moyenne, la somme distingue un ensemble de 1 élément d'un ensemble de 3.

### Pourquoi trier quand même

Le pooling rend l'ordre indifférent au réseau, mais **pas au debug**. Les ids sont écrits **triés par ordre croissant** (`def _fill_id_slots`, `engine/observation_builder.py`), pour que l'observation soit reproductible bit à bit d'un run à l'autre : sans ça, les diffs de replay et les comparaisons d'état deviennent illisibles.

## Dimensionnement des slots : mesure vs projection

`UNIT_ABILITY_SLOTS = 8` garde un chemin de crash dur (débordement = `raise`), donc sa marge se lit sur la **mesure**, pas sur la projection :

- **Mesuré le 2026-08-04 sur le dépôt réel** (`class UnitRegistry` de `ai/unit_registry.py` + `def unit_has_rule_effect` de `engine/phase_handlers/shared_utils.py` sur les effets du vocabulaire, 179 datasheets, puis les unions 19.04 légales — paires et trios bodyguard + leader + support validés par 19.01/24.22/24.34) : **2** effets au maximum par datasheet, **3** au maximum en vigueur sur une entité (`AssaultIntercessor + CaptainPowerWeaponBolter [+ Ancient]`). Marge actuelle : 5 slots.
- **Recalculé le 2026-08-30 sur les 25 capacités actées** (contrainte 19.01 : max 1 leader + 1 support par escouade ; Da Jump = action active, pas d'obs_id — même logique que Waaagh! en `global_bin`) : **6 au maximum** sur une entité. Pires cas Orks : `Boyz + Warboss + Painboy` → Get da Good Bitz, Might Is Right, Da Biggest and da Best, `feel_no_pain`, Hold Still and Say Aargh, Grot Orderly ; `Boyz + WeirdBoy + Painboy` → Get da Good Bitz, Waaagh! Energy, `deadly_demise`, `feel_no_pain`, Hold Still and Say Aargh, Grot Orderly. Pire cas SM : `Intercessor + Librarian + Ancient` → Hail of Bolts, Objective Secured, Mental Fortress (`invul_save_override`), Psychic Hood (`feel_no_pain_vs_psychic`), Unbreakable Resolve (`feel_no_pain_near_objective`), Relic Banner (`oc_bonus`). **Marge : 2 slots. `UNIT_ABILITY_SLOTS = 8` tient pour l'intégralité du chantier 06.** Ces capacités n'existent pas encore dans le moteur : c'est une projection de la conception, pas une mesure.

8 et non 6 : dimensionner sur la projection laisserait zéro marge le jour où elle se réalise — une seule capacité ajoutée à une figurine rattachée ferait déborder. Le surcoût (2 scalaires × nombre d'entités) est négligeable face à la suppression d'un mode de défaillance dur.

### Débordement : erreur, jamais troncature

Si une unité porte plus de capacités que de slots, le moteur **lève** (`observation_builder`), en nommant l'unité et les capacités en excès. Tronquer silencieusement ferait subir à l'agent des règles qu'il ne perçoit pas — exactement le trou que V11 §0.30 avait fermé.

## Registres des identifiants

`config/unit_rules.json` est le registre des règles ; chaque règle observable y porte un champ `obs_id` : entier **stable et jamais réattribué** dans `[OBS_ID_MIN, OBS_ID_MAX]`. `0` est réservé au padding (un slot vide doit contribuer exactement zéro au pooling). `config/unit_statuses.json` suit la même convention pour les statuts — les trois statuts (`battle_shock`, `oath_target`, `suppressed`) y ont été **déclarés avant leurs chantiers respectifs** (02, 03, 06) : c'est ce qui garantit qu'aucun d'eux ne retouche `obs_size`.

Contraintes du chargeur : `obs_id` absent, dupliqué ou hors bornes → **erreur explicite**. Les marqueurs de rôle (`leader`, `sergeant`, `support`, `special_weapon`) sont **exclus** du vocabulaire observé : le sous-registre « types de figurines » les porte déjà.

**Stabilité** : un `obs_id` réattribué après suppression d'une règle ferait pointer un modèle entraîné sur une ligne d'embedding qui ne veut plus dire la même chose — corruption silencieuse. Un id retiré reste **brûlé**. Cas d'école vécu : `deep_strike` devait recevoir le 15 selon le plan du chantier 04 ; le 15 était parti entre-temps à `feel_no_pain`, `deep_strike` porte le 16 — celui qu'un document prévoit n'est pas celui qui est libre le jour venu. Les ids occupés se lisent dans les deux fichiers JSON, jamais dans un document.

## Vocabulaire OBSERVÉ ≠ effets ACCORDABLES

`UNIT_RULE_EFFECT_IDS` (`engine/observation_entities.py`) jouait **deux** rôles : le vocabulaire des capacités observées (dont l'ajout devait être gratuit) **et** la liste des effets qu'un candidat de décision peut accorder — registre POSITIONNEL, 1 bit par effet, émis pour chacun des `MAX_DECISION_OPTIONS` slots (`DECISION_OPTION_BIN_FIELDS`). Ajouter **une** capacité observable coûtait donc autant de scalaires que de slots de candidats, donc un retrain `--new` : la promesse du gel était fausse d'un facteur 6, et 6 des 13 effets d'alors portaient des bits qu'aucun roster ne pouvait jamais mettre à 1.

Les deux vocabulaires sont **séparés** depuis le 2026-08-04 :

| Tuple (`engine/observation_entities.py`) | Rôle | Coût d'une entrée |
|---|---|---|
| `UNIT_RULE_EFFECT_IDS` | ce que l'agent PERÇOIT (ids → embedding) | **0 scalaire** |
| `DECISION_GRANTABLE_EFFECT_IDS` | ce qu'un candidat de `rule_choice` ACCORDE | 1 bit × `MAX_DECISION_OPTIONS` slots |

Le second est un sous-ensemble strict du premier (contrôlé au chargement du module), **dérivé** des `grantsRuleIds` réellement déclarés par les rosters (`frontend/src/roster/**`) — un test de contrat le recalcule et échoue dans les deux sens. La garde d'`effect_ids` de `def set_pending_agent_decision` (`engine/agent_decision.py`) contrôle contre ce tuple-là : un effet accordable mais non déclaré **lève** à la pose de la décision, au lieu d'être décrit par un vecteur nul.

Le verrou sans lequel le couplage pouvait revenir silencieusement est `test_adding_an_observed_capability_costs_zero_scalar` (`tests/unit/engine/test_squad_obs_unit_rules.py`) : il recalcule `obs_size` **dans un processus neuf** bâti sur un schéma d'entités augmenté d'une capacité fictive, et compare le **nombre**. Lire le texte de la formule ne suffirait pas — un terme d'un autre module ou derrière une indirection y échapperait ; le nombre couvre tous les termes où qu'ils vivent.

## Ce qui ne va PAS dans l'ensemble par unité

**Les effets de faction.** Waaagh! accorde quatre effets identiques à *toutes* les unités orkes. Les inscrire dans l'ensemble de chaque unité, c'est répéter les mêmes ids sur toutes les entités et faire déborder les slots pour zéro information : le réseau reconstitue l'effet à partir de « cette unité est orke » + « Waaagh! actif », deux informations **globales**.

Les capacités de faction vont donc dans `GLOBAL_BIN_FIELDS` (`engine/observation_entities.py`). Emplacements déclarés par le socle (amendements des 2026-08-05 et 2026-08-06) :

| Emplacement | Registre |
|---|---|
| `my_waaagh_available`, `my_waaagh_active`, `enemy_waaagh_available`, `enemy_waaagh_active` | `GLOBAL_BIN_FIELDS` |
| `my_oath_target_selected`, `enemy_oath_target_selected` | `GLOBAL_BIN_FIELDS` |
| `my_oath_wound_bonus_active`, `enemy_oath_wound_bonus_active` | `GLOBAL_BIN_FIELDS` |
| `waaagh_call` | `AGENT_DECISION_TYPE_IDS` (→ `decision_ctx_bin`) |

Quatre bits pour le Waaagh! et non deux : sa durée court *« until the start of your next Command phase »*, donc elle enjambe le tour adverse. L'identité de la cible d'Oath n'est PAS dans `global_bin` — elle est portée par le statut `oath_target` de l'entité visée, pour zéro scalaire. La justification des bits `*_oath_wound_bonus_active` est en [§3](#la-clause-conditionnelle-du-1-wound).

Les deux scalaires de CP (`my_command_points`, `enemy_command_points`, registre `GLOBAL_CONT_FIELDS`) ont eux aussi été déclarés par le socle pour le compte du chantier 02.

## `OATH_SLOTS` — dimension d'action, pas `CHOICE_k`

Oath of Moment désigne *« one unit from your opponent's army »*. `engine/macro_intents.py` porte la doctrine applicable :

> ⚠️ Elles [les actions `CHOICE_i`] ne concernent QUE les décisions dont les candidats ne sont PAS des entités déjà observées : une décision « quelle escouade ennemie » se paramètre en dimension d'action + pointeur, pas en `CHOICE_k`.

Oath suit donc le motif de `SHOOT_SLOTS` / `CHARGE_SLOTS` / `FIGHT_SLOTS` : `OATH_SLOT_COUNT` est **dérivé** de `SHOOT_SLOT_COUNT` (`OATH_SLOT_BASE`, `OATH_SLOTS`, `engine/macro_intents.py`), indexant le **même** `def get_enemy_slot_mapping` (`engine/phase_handlers/shared_utils.py`) que l'observation.

C'est l'invariant D1 : l'action *i* et la ligne *i* du tenseur ennemi désignent la **même** escouade. Les désolidariser ferait pointer l'action et l'observation sur deux escouades différentes sans que rien ne lève.

`MAX_DECISION_OPTIONS` reste à 6 : Waaagh! est une décision binaire (appeler / ne pas appeler) et y tient sans difficulté.

L'espace d'action complet (familles, bases, tailles) se lit dans `engine/macro_intents.py` (`TOTAL_ACTION_SIZE` en est dérivé, jamais configuré) ; le miroir côté handlers est le bloc `SQUAD_ACTION_*` de `engine/phase_handlers/shared_utils.py`, verrouillé par `tests/unit/engine/test_action_space_mirror.py`. `SQUAD_OBS_SIZE_TARGET` (`engine/observation_builder.py`) est calculé, jamais recopié en littéral.

## Le gel du socle

Le chantier 01 était **le seul** de la série capacités (01→06) autorisé à changer `obs_size` ou `TOTAL_ACTION_SIZE` ; les chantiers 02 à 06 n'utilisent que des dimensions déjà déclarées par lui. La garantie était **un seul retrain pour toute la série** — tenue au sens strict : les deux nombres ont encore bougé deux fois APRÈS le 01 (pose des sept emplacements manquants au chantier 03, 20718 → 20725 le 2026-08-05, puis 20725 → 20727 le 2026-08-06), mais comme **amendements du socle déclaré par le 01**, absorbés par le même retrain ; le 06 est sous la même interdiction (voir l'Historique, §7).

Le gel a été rompu **hors série**, sciemment, par le lot V11 §0.48 (élément L2, choix de l'escouade à activer, 2026-08-07) : une famille d'actions entière qui n'existait sous aucune forme, inventoriée d'avance comme cassant les deux contrats, retrain unique avec le reste du lot. Le gel ne couvrait pas ce cas et ne prétendait pas le couvrir.

Valeurs courantes : `obs_size` se lit dans la clé `obs_size` de `config/agents/ArmageddonAgent/ArmageddonAgent_training_config.json` (dont la `justification` attenante tient la lignée des changements de schéma) ; `TOTAL_ACTION_SIZE` dans `engine/macro_intents.py`.

---

# 2. Points de commandement (CP) et battle-shock

## Sources règles

- `Documentation/40k_rules/08 Command phase.pdf` — 08.01 à 08.05
- `Documentation/40k_rules/01 Core concepts.pdf` — 01.06 jets de commandement, 01.07 jets de battle-shock
- `Documentation/40k_rules/25 Rules appendix.pdf` — force de départ et demi-effectif
- `Documentation/40k_rules/Armageddon/Datasheets - Orks.pdf` — Thievin' Scavengers (Gretchin)

Les PDF font foi. Toute divergence avec ce document se tranche en leur faveur.

## Périmètre — arbitrage rendu

Le battle-shock **fait partie du chantier CP**. Décision de l'utilisateur. Raison : Thievin' Scavengers exige des unités *« non battle-shocked »*. Sans battle-shock, la condition serait toujours vraie et la capacité serait implémentée **plus permissive que la règle** — une valeur par défaut masquant un manque, interdite (T1). Le battle-shock est par ailleurs requis par le contrôle d'objectif, les stratagèmes et les actions.

## La phase de commandement en cinq étapes

`engine/phase_handlers/command_handlers.py` implémente les cinq étapes du PDF, orchestrées par `def command_phase_start` :

| Règle | Symbole | Contenu |
|---|---|---|
| 08.01 | `command_step_start_of_phase` | début de phase — remises à zéro, caches |
| 08.02 | `command_step_gain_core_cp` | les **deux** joueurs gagnent 1 CP |
| 08.03 | `command_step_battle_shock` | jets du joueur **actif** seulement |
| 08.04 | `command_step_command_abilities` | capacités « in your Command phase » (Waaagh!, Oath) |
| 08.05 | `command_phase_end` | fin de phase → transition move |

L'ordre compte : plusieurs capacités du chantier 06 se déclenchent à des étapes précises (Get da Good Bitz en **fin** de phase, Grot Orderly en phase de commandement, Waaagh! et Oath au **début**). `def command_phase_resume` reprend la phase une fois les décisions de 08.04 jouées — le moteur n'avance pas tant qu'une décision de faction est pendante (`def faction_decision_is_pending`).

### 08.02 — Gain de Core CP

> Both players gain 1 Command Point (CP).

**Les deux joueurs**, pas seulement le joueur actif. Un gain de 1 (`CORE_CP_GAIN_PER_COMMAND_PHASE`, appliqué via `gain_command_points`), pas une valeur libre : c'est la règle, rien à configurer. La valeur de **départ** des CP, elle, est lue en config, sans valeur par défaut — absente → erreur explicite.

Dette assumée et bornée : la **dépense** de CP n'a aucun consommateur tant qu'il n'y a pas de stratagèmes.

### 08.03 — Battle-shock

> The active player must now make one battle-shock roll (01.07) for each unit in their army that fulfils one or both of the following conditions:
> ▪ That unit is currently battle-shocked.
> ▪ That unit is at, or below, half-strength.
>
> If a unit was battle-shocked at the start of this step and its battle-shock roll during this step succeeds, it is no longer battle-shocked.

Le jet se fait pour le **joueur actif seulement**. Une unité déjà battle-shocked rejette chaque tour : c'est ce jet qui lui permet de s'en sortir.

## Le battle-shock, tel que le PDF le définit

### 01.06 — Jet de commandement

> To make a leadership roll for a unit, its controlling player rolls 2D6: if the result is equal to or greater than **one or more** of the Ld characteristics in that unit, that roll succeeds.

**2D6**, pas 1D6 — les seuils `LD` des datasheets (`6+`, `7+`, `8+`) sont des cibles de 2D6. Et *« one or more of the Ld characteristics »* : dans une unité à plusieurs profils (escouade + character rattaché), on retient le **meilleur** Ld, c'est-à-dire le seuil le plus bas. Un Warboss (`LD 6+`) rattaché à des Boyz (`LD 7+`) fait passer l'unité à 6+. Conséquence directe de la règle 19.04 déjà implémentée (`def _fold_attached_characters`, `engine/game_state.py`) : ne pas recoder une sélection de Ld à côté, lire l'unité effective — c'est ce que fait `def unit_effective_leadership` (`engine/phase_handlers/shared_utils.py`), consommé par `def roll_battle_shock`.

### 01.07 — Jet de battle-shock

> To make a battle-shock roll for a unit, its controlling player makes a leadership roll for it.
> ▪ If that roll succeeds, that unit does not become battle-shocked.
> ▪ If that roll fails, that unit, **and each model in it**, is battle-shocked.
>
> While a unit is battle-shocked:
> ▪ The Objective Control (OC) characteristic of all of its models is modified to '-' (02.02).
> ▪ Its controlling player cannot target that unit with stratagems (15).
> ▪ It is not eligible to start an action (16), and any action it has started cannot be completed.

Trois effets, dont **un seul est applicable aujourd'hui** :

| Effet | Applicable ? |
|---|---|
| OC → '-' | **oui** — le drapeau `battle_shocked` de l'unité est lu par le calcul d'OC (`def objective_control_contributions` / `def _sum_objective_control_oc`, `engine/game_state.py`) |
| Pas ciblable par un stratagème | sans objet — pas de stratagèmes |
| Inéligible aux actions | sans objet — pas de système d'actions (16) |

Les deux derniers ne se codent pas : ils n'ont aucun déclencheur. Écrire du code pour eux produirait du code jamais atteint. Ils sont documentés ici pour que le jour où stratagèmes et actions existent, on sache que le battle-shock les concerne. `OC → '-'` n'est pas une convention interne : c'est une caractéristique modifiée (02.02).

### Force de départ et demi-effectif (appendice 25)

> The number of models a unit contains at the start of the first battle round is its starting strength. The starting strength of an attached unit is the number of models that unit contains at the start of the first battle round.

| | Force de départ 1 | Force de départ ≥ 2 |
|---|---|---|
| **Sous l'effectif de départ** | PV restants < W | figurines restantes < force de départ |
| **À demi-effectif** | PV restants = W / 2 | figurines restantes = force de départ / 2 |
| **Sous le demi-effectif** | PV restants < W / 2 | figurines restantes < force de départ / 2 |

> If a model's W characteristic or a unit's starting strength cannot be evenly divided in half, that model or unit **cannot be at half-strength** (but can be below half-strength).

Ce dernier point est un piège réel : une escouade de 5 ne peut **jamais** être *à* demi-effectif. Une implémentation en `<=` sur une division entière le raterait. Prédicats : `def is_unit_below_starting_strength`, `def is_unit_at_half_strength`, `def is_unit_below_half_strength`, `def is_unit_at_or_below_half_strength` (`engine/phase_handlers/shared_utils.py`).

Exemple du PDF, directement applicable aux rosters Armageddon :

> A Captain (1 model) is attached to a unit of Intercessors (5 models). This attached unit has a starting strength of **6**.

La force de départ se calcule sur l'unité **après** rattachement, pas sur la datasheet, et elle est figée au début du premier round.

## Thievin' Scavengers (Gretchin)

> At the start of your Movement phase, for each objective you control that has one or more friendly non-battle-shocked units with this ability within range of it, roll one D6. If one or more of those rolls is a 4+, you gain 1CP.

Nom générique : `cp_gain_on_objective` (`config/unit_rules.json` ; porteur : `frontend/src/roster/ork/units/Gretchin.ts`). Deux pièges de lecture :

1. Le déclenchement est en **phase de mouvement**, pas de commandement. Ne pas le ranger avec le gain de Core CP par confort d'implémentation.
2. *« If one or more of those rolls is a 4+, you gain 1CP »* — **un seul CP au total**, quel que soit le nombre d'objectifs qui réussissent. On lance un dé par objectif, mais le gain est global.

## Rites of Battle : non livrable, et pourquoi

> Once per battle round, per army: When a stratagem targets this unit, you can reduce its cost by 1CP for that use.

Sans système de stratagème, *« when a stratagem targets this unit »* n'a **aucun déclencheur**. Coder la réduction produirait du code jamais atteint — le motif « code testé mais jamais appelé » déjà rencontré dans ce dépôt. Rites of Battle est donc **hors périmètre**. Elle reste comptée dans le décompte des capacités par unité du socle (le Captain en porte 2 avec elle), mais n'est pas implémentée. Ce n'est pas une dette déguisée : le blocage est technique et externe.

## Observation

| Donnée | Emplacement | Nature |
|---|---|---|
| CP des deux joueurs | `my_command_points` / `enemy_command_points`, `GLOBAL_CONT_FIELDS` (`engine/observation_entities.py`) | grandeur globale |
| Battle-shock | `status_ids` de l'unité (id `battle_shock`, `config/unit_statuses.json`) | statut, pas un bit dédié |
| Sous / à demi-effectif | dérivable des PV et du nombre de figurines déjà observés | rien à ajouter |

Ces emplacements ont été déclarés par le socle (§1) : ce sous-système n'a changé ni `obs_size` ni `TOTAL_ACTION_SIZE`.

**Jumeau** : le battle-shock touche le contrôle d'objectif (moteur), le replay, l'analyzer et le frontend — toute retouche se vérifie sur les quatre.

---

# 3. Capacités de faction : Waaagh! et Oath of Moment

## Sources règles

- `Documentation/40k_rules/Armageddon/Waaagh!.txt`
- `Documentation/40k_rules/Armageddon/OathOfMoment.txt`

Les deux sont la source de vérité. Toute divergence entre ce document et ces fichiers se tranche en faveur des fichiers.

Une capacité de faction s'applique uniformément à toutes les unités de l'armée qui la portent : elle est observée dans `global_bin`, jamais dans `ability_ids` (voir [§1](#ce-qui-ne-va-pas-dans-lensemble-par-unité)). Les deux règles sont déclarées au registre (`waaagh`, `oath_of_moment`, `config/unit_rules.json`, sans `obs_id` — elles ne passent pas par l'embedding).

## Waaagh! (ORKS)

> If your Army Faction is ORKS, once per battle, at the start of your Command phase, you can call a Waaagh!. If you do, until the start of your next Command phase, the Waaagh! is active for your army and:
> - Units from your army with this ability are eligible to declare a charge in a turn in which they Advanced.
> - Add 1 to the Strength and Attacks characteristics of melee weapons equipped by models from your army with this ability.
> - Models from your army with this ability have a 5+ invulnerable save.

### Décomposition et câblage livré

| Clause | Traitement livré |
|---|---|
| Décision : appeler, **1×/partie**, début de phase de commandement | `pending_agent_decision` de type `waaagh_call`, 2 candidats (appeler / passer) → `CHOICE_0`/`CHOICE_1` ; posée en 08.04, appliquée par `def apply_waaagh_call_decision` (`command_handlers.py`) |
| Charge après Advance | `charge_after_advance` (déjà dans `UNIT_RULE_EFFECT_IDS`) — accordé pendant le Waaagh! |
| +1 S et +1 A aux armes de mêlée | `def waaagh_melee_bonus` (`engine/game_state.py`) |
| Sauvegarde invulnérable 5+ | `def effective_invul_save` (`engine/game_state.py`) ; seuils affichés via `def display_save_threshold_with_waaagh` (`shared_utils.py`) |

Les effets s'appliquent aux unités **portant la capacité**, pas à toute l'armée indistinctement. NB : les noms de primitives génériques que la conception d'origine visait (`melee_strength_bonus`, `melee_attacks_bonus`, `invul_save_override`) n'existent pas dans le code — la livraison est passée par les fonctions dédiées ci-dessus ; les primitives génériques restent au programme du chantier 06 ([§5](#5-à-faire--chantier-06-armageddon)).

État (`engine/game_state.py`, initialisé d'un bloc pour qu'aucun point d'entrée ne puisse en poser une partie) : `waaagh_called` (verrou 1×/partie, jamais remis à False), `waaagh_active`, plus `oath_target` et `pending_oath_selection` pour l'Oath. Lecture : `def waaagh_is_active`.

**Condition ajoutée le 2026-08-11** : la décision d'appel n'est posée que si **le joueur a au moins une escouade sur la table** (`def player_has_squads_on_board`, `command_handlers.py`). Le moteur ne termine pas l'épisode sur une armée anéantie, donc la phase de commandement du joueur vidé arrive ; la décision est une capacité d'ARMÉE, sans unité porteuse, et l'observation prend la première escouade du décideur comme repère — sans aucune, elle lève et l'épisode plante. Le « once per battle » n'est **pas** consommé dans ce cas : la décision se repose si le joueur revient sur la table.

### L'effet réel, mesuré

`INVUL_SAVE` est une caractéristique statique par figurine sur les datasheets ; le Waaagh! la borne à 5 :

| Unité | `INVUL_SAVE` datasheet | Waaagh! actif |
|---|---|---|
| Boyz | 7 (aucune) | **5** |
| Gretchin | 7 (aucune) | **5** |
| WarTrakk | 6 | **5** |
| Warboss, BannerNob, BigMekDakkarig | 5 | 5 (inchangé) |

Pendant un round complet, l'armée orke entière gagne une invulnérable 5+, +1 S, +1 A en mêlée et la charge après Advance. C'est de très loin la décision la plus lourde de la liste orke, et c'est une décision de **tempo** — à quel tour l'appeler. C'est exactement ce qu'un agent RL doit apprendre. L'invulnérable **observée** (`invul_save` des tenseurs d'unité) est la valeur EFFECTIVE, Waaagh! compris : c'est celle que la résolution applique.

### Observation

`GLOBAL_BIN_FIELDS`, 4 bits : `my_waaagh_available`, `my_waaagh_active`, `enemy_waaagh_available`, `enemy_waaagh_active`. Les quatre, pas deux : la durée enjambe le tour adverse — le Waaagh! ennemi actif pendant mon tour change ce que je dois faire.

## Oath of Moment (ADEPTUS ASTARTES)

> If your Army Faction is ADEPTUS ASTARTES, at the start of your Command phase, select one unit from your opponent's army. Until the start of your next Command phase, that enemy unit is your Oath of Moment target.
> Each time a model with this ability makes an attack that targets your Oath of Moment target:
> ▪ You can re-roll the Hit roll.
> ▪ If you are using a Codex: Space Marines Detachment and your army does not include one or more units with the BLOOD ANGELS, DARK ANGELS, DEATHWATCH or SPACE WOLVES keywords, or one or more units from those factions' Munitorum Field Manual sections, add 1 to the Wound roll as well.

Noter : **chaque tour**, pas une fois par partie. Et **non optionnel** — « select one unit » : si des ennemis existent, l'agent doit en désigner un (pas de candidat « aucune cible »). Câblage : `def arm_oath_selection`, `def oath_selectable_enemy_ids`, `def apply_oath_selection` (`command_handlers.py`) ; état `oath_target` / `pending_oath_selection` (`game_state.py`).

### La relance de touche : `hit_any_fail`

`class RerollProfile` (`engine/phase_handlers/attack_sequence.py`) portait `hit_1`, `wound_1`, `wound_any_fail`, `save_1` ; le chantier 03 y a **créé** `hit_any_fail` sur le motif de `wound_any_fail` : relance des **échecs** uniquement, un seul dé de relance, priorité explicite entre les causes, et `hitRerollCause` au record — sans cette trace, le log dit que la relance était *possible*, jamais qu'elle a *eu lieu* (l'analyzer ne pourrait pas les distinguer). La résolution de cause vit dans `def resolve_hit_reroll_ability` / `def stamp_reroll_abilities` (`shared_utils.py`).

**Jumeau tir/mêlée** — motif d'échec n°1 du dépôt : la relance est câblée aux sites jumeaux de construction du profil, tir (`def _manual_roll_intent`, `shared_utils.py`) et mêlée (`def _manual_roll_fight_intent`, `fight_handlers.py`), plus le chemin gym (`engine/w40k_core.py`). Elle s'applique **uniquement** quand l'attaque cible l'unité désignée, et uniquement pour les modèles portant la capacité.

### Désignation : dimension d'action, pas `CHOICE_k`

Oath désigne littéralement une escouade ennemie déjà observée : ce sont les `OATH_SLOTS` (déclarés par le socle, [§1](#oath_slots--dimension-daction-pas-choice_k)) que ce sous-système consomme — décodage et masque dans `engine/action_decoder.py`, masque exposant les slots des escouades ennemies vivantes.

### La clause conditionnelle du +1 Wound

Elle a deux moitiés de faisabilité opposée :

- *« votre armée ne contient pas d'unité BLOOD ANGELS / DARK ANGELS / DEATHWATCH / SPACE WOLVES »* → **implémentée pour de vrai** : `UNIT_KEYWORDS` existe, c'est un balayage de l'armée — et la clause compte les unités **mortes**.
- *« vous utilisez un Détachement Codex: Space Marines »* → aucun système de détachement dans le moteur. La moitié détachement est un **champ obligatoire de la config de scénario** : `uses_codex_detachment` (porté par les scénarios, ex. `config/scenario_pvp.json` ; consommé par `def oath_wound_bonus_applies`, `engine/game_state.py`). Absent → erreur explicite, jamais de valeur par défaut.

Ce n'est pas un contournement : la valeur est une donnée métier légitime que l'utilisateur possède et que le moteur ne peut pas déduire. Le jour où les détachements existent, le champ devient calculé au lieu d'être déclaré, et le reste du code ne bouge pas. Dette bornée : « Détachement Codex » reste déclaré, non déduit.

Cette clause dépend du ROSTER, qu'aucune autre feature ne porte (les mots-clés de sous-faction des unités alliées ne sont pas observés) — d'où les deux bits globaux `my`/`enemy_oath_wound_bonus_active` : sans eux, deux parties identiques à l'écran n'ont pas la même règle d'attaque et la politique de désignation n'est pas séparable.

### Observation

- `global_bin` : `my`/`enemy_oath_target_selected` (une désignation est en vigueur) + `my`/`enemy_oath_wound_bonus_active` (la clause +1 W est ouverte).
- `status_ids` de l'entité ennemie visée : id `oath_target` (`config/unit_statuses.json`). Symétriquement, mes unités désignées par l'Oath adverse portent le même statut — l'Oath adverse est visible dans **mon** observation.

## Expiration des deux capacités

Les deux durent *« until the start of your next Command phase »*. Le nettoyage se fait à l'ouverture de la phase de commandement suivante **du même joueur**, pas en fin de tour : le Waaagh! appelé au tour N est encore actif pendant le tour adverse. Un test qui n'observe que le tour du déclarant ne verrouille rien.

---

# 4. Réserves stratégiques et Deep Strike

## Sources règles

- `Documentation/40k_rules/20 Strategic reserves.pdf` — règles 20.01 à 20.04
- `Documentation/40k_rules/24 Core abilities.pdf` — Deep Strike 24.09
- `Documentation/40k_rules/03 Moving.pdf` — Set Up 03.02, référencé par 20.04

Source de vérité : les PDF. Porteurs Armageddon de `CORE: Deep Strike` : Chaplain with Jump Pack, Vanguard Veteran Squad with Jump Packs, Land Speeder — plus **Da Jump** du Weirdboy (chantier 06), qui place l'unité en réserves puis lui accorde Deep Strike.

## Structure d'état : une seule source « hors table »

La mécanique s'appuie sur l'état qui existait déjà — ne **jamais** créer un second modèle de « pas encore sur la table » à côté :

- `deployed_on_turn` dans l'état d'unité (`engine/game_state.py`) ;
- les bits d'observation `deploy_not_on_board`, `deploy_pre_battle`, `deploy_in_battle`, `deployed_this_turn` (`UNIT_BIN_FIELDS`, `engine/observation_entities.py`) — l'unité en réserves est `deploy_not_on_board` avec `deployed_on_turn` nul ;
- `def movement_build_valid_destinations_pool` (`engine/phase_handlers/movement_handlers.py`) — la validité de placement n'est pas réimplémentée.

## Les règles, décomposées

### 20.01 — Mise en réserve

Avant la bataille, à l'étape Declare Battle Formations, on peut placer des unités en réserves (hors `FORTIFICATIONS`) au lieu de les déployer. **Plafond : la valeur totale en points des réserves ne peut dépasser 50 % de la limite de points de la bataille.** Contrôle dur au chargement du roster — dépassement → erreur explicite nommant les unités et le total, jamais une troncature silencieuse.

### 20.02 — Unités repositionnées

Unités retirées de la table pendant la bataille et replacées en réserves (le cas de **Da Jump**). Trois clauses :

- Utilisable en phase de mouvement même sur une unité ayant déjà bougé.
- Une unité replacée le tour même où elle a fait un Advance / Fall Back / débarquement **a toujours fait** ce mouvement ce tour-là.
- Les effets en cours (durée ou circonstance) **continuent** de s'appliquer hors table tant que la durée court. Exemple du PDF : une unité battle-shocked au retrait est toujours battle-shocked à son retour le même tour ; une aura, en revanche, cesse si elle n'est plus à portée en revenant. Cette clause interagit avec le battle-shock (§2) et le Waaagh! (§3), tous deux vivants — elle est donc testable pour de vrai, sur l'exemple littéral du PDF.

### 20.03 — Arrivée

Chaque unité en réserves arrive par un **ingress move**. Sauf mention contraire, **pas avant le second round de bataille** — le masque est fermé au round 1.

### 20.04 — Ingress move

| Élément | Valeur |
|---|---|
| Distance de mise en place | 6" |
| Éligibilité | l'unité est en réserves |
| Effet | mise en place selon Set Up (03.02) |
| Pendant | entièrement à 6" ou moins d'un ou plusieurs **bords de table**, et à **plus de 8" horizontalement de toute unité ennemie** |
| Avant le 3ᵉ round | aucune figurine dans la zone de déploiement adverse |
| Après | sauf mention contraire, l'unité n'est éligible à **aucun autre type de mouvement** jusqu'au début de la prochaine phase de charge |

Le pool de destinations est précalculé (`def precompute_ingress_pools` et les helpers `_ingress_*`, `movement_handlers.py`) ; le masque de l'ingress passe par `engine/action_decoder.py`. Borne réelle des 8" : une destination à 8" pile est refusée (*« more than 8" »*), à 8,1" acceptée — tester la borne, pas le milieu.

**À la fin du 3ᵉ round, toute unité en réserves n'ayant pas fait d'ingress move est détruite** (exceptions : unités embarquées dans des transports ayant fait un ingress, et unités repositionnées). C'est une **règle de jeu**, pas un cas d'erreur — implémentée par `def destroy_unarrived_strategic_reserves` (`engine/w40k_core.py`), journalisée comme un événement de jeu normal. Conséquence directe sur l'entraînement : un agent qui garde ses unités en réserves les perd — pression de tempo réelle qu'il doit apprendre.

### 24.09 — Deep Strike

> Each time this unit makes an ingress move (20.04), if **every model in this unit** has this ability, it can be set up anywhere on the battlefield that is more than 8" horizontally from all enemy units, even if that is within your opponent's deployment zone.

Deep Strike **remplace** la contrainte de bord de 20.04 ; il conserve les 8" et lève l'interdiction de zone adverse (`def unit_has_deep_strike`, `movement_handlers.py`, bascule le pool d'ingress). La condition « every model » compte : une escouade Deep Strike menée par un character sans la capacité **perd** Deep Strike. Elle se lit sur les règles PROPRES de chaque figurine (`models_cache[mid]["UNIT_RULES"]`), **pas** sur les slots d'observation, qui décrivent l'union 19.04. Dans les rosters Armageddon, Chaplain JP et Vanguard Veteran JP l'ont tous deux, donc l'unité attachée le conserve ; le Land Speeder est seul.

## Observation

Aucun nouveau champ d'état : les bits `deploy_*` suffisent. **`deep_strike` est une capacité OBSERVÉE** (`obs_id` 16, `config/unit_rules.json`, entrée de `UNIT_RULE_EFFECT_IDS`) : deux escouades en réserves sont indiscernables sans elle, alors que l'une arrive dans la bande de 6" au bord et l'autre n'importe où, zone adverse comprise. Elle avait été appliquée par le moteur **sans** être observée pendant six jours — l'agent la subissait sans la percevoir, exactement le trou que V11 §0.30 a fermé. Coût mesuré à la pose : zéro scalaire (verrou `test_adding_an_observed_capability_costs_zero_scalar`). Ne PAS l'ajouter à `DECISION_GRANTABLE_EFFECT_IDS` : aucun candidat de `rule_choice` ne l'accorde.

Les trois porteurs sont ancrés dans `test_composite_datasheet_abilities_are_captured_through_their_effects` (`tests/unit/engine/test_squad_obs_unit_rules.py`), les autres unités du même tableau faisant la contre-épreuve ; le `leader` du Chaplain, marqueur de rôle sans `obs_id`, ne remonte pas.

**Point resté ouvert, non tranché** : le **round restant avant destruction** (20.04) n'est pas observé — sans lui, l'agent ne perçoit pas la pression de tempo. Si un scalaire global devient nécessaire, c'est une retouche du **socle** (`obs_size` bouge) : remonter au §1, pas le poser en douce.

## Pièges

- Les 8" sont **horizontaux**. Le dépôt raisonne en subhex : convertir via la clé `inches_to_subhex` de la config board (lue par `require_key`, cf. `def _get_inches_to_subhex`, `engine/game_state.py`), jamais un seuil en pouces absolus.
- Ne pas créer un second modèle de « hors table » à côté de `deployed_on_turn`.
- **Jumeau déploiement/mouvement** : l'ingress est une mise en place (03.02), pas un déplacement. Vérifier lequel des deux chemins de validation s'applique et ne pas durcir l'un par rapport à l'autre.

---

# 5. À FAIRE — chantier 06 Armageddon

> 🔴 **Chantier OUVERT.** L'état d'avancement (passes livrées, prérequis, jalon) fait foi dans [Roadmap/capacites.md](../../Roadmap/archives/capacites.md), jamais ici. Tout ce qui suit est la CONCEPTION et le PLAN D'EXÉCUTION du chantier : 6 primitives moteur pour les 25 capacités d'unités des rosters Armageddon.
>
> ⚠️ Risque d'exécution : `UNIT_ABILITY_SLOTS = 8` est une projection non mesurée (voir [§1](#dimensionnement-des-slots--mesure-vs-projection)) — si une entité dépasse 8 capacités en vigueur, le moteur lève. Ce chantier est ce qui rend le chiffre mesurable ; le recalcul de la projection se fait AVANT la passe 1.

## Sources règles

- `Documentation/40k_rules/Armageddon/Datasheets - Orks.pdf` (9 pages)
- `Documentation/40k_rules/Armageddon/Datasheets - Space Marines.pdf` (8 pages)
- `Documentation/40k_rules/24 Core abilities.pdf` — Deadly Demise 24.08

Les PDF font foi. Toute divergence avec ce document se tranche en leur faveur.

## Note sur le décompte

Les premières analyses annonçaient « 17 capacités ». Le chiffre a monté à **25** parce que les chantiers 03 et 04 ont débloqué ce qui était classé non codable : Waaagh! et ses effets dérivés, Deep Strike, Da Jump. Rien n'a été ajouté au périmètre — des capacités en sont sorties de la catégorie « impossible ».

Conséquence sur le socle : la projection « 6 capacités en vigueur au maximum sur une entité », qui justifie `UNIT_ABILITY_SLOTS = 8`, a été calculée sur les 17 — elle n'a pas été recalculée sur les 25. **Recalculée le 2026-08-30, avant la passe 1** : mesure sur les 179 datasheets du registre après câblage de la passe 1 → **2 capacités observables au maximum par datasheet**, donc au plus 6 sur une entité attachée (escouade + 1 leader + 1 support, contrainte 19.01). `UNIT_ABILITY_SLOTS = 8` tient, marge 2 slots ; aucun ajustement n'a été nécessaire.

## Vocabulaire

Une **primitive** est un mécanisme moteur irréductible, absent au moment de la conception, sur lequel plusieurs capacités s'appuient. Ce ne sont pas les capacités elles-mêmes. Six primitives couvrent les 25 capacités.

## État du code constaté (2026-08-28 — à re-vérifier au démarrage de chaque passe)

- **Primitive A** : **LIVRÉE** (passe 1, 2026-08-30). `hit_any_fail` venait du chantier 03 ; les quatre autres modificateurs sont vifs — `def resolve_hit_roll_modifiers` et `def resolve_melee_wound_bonus` (`shared_utils.py`, appelés par les DEUX rollers), `def unit_charge_roll_bonus` lu dans `def roll_charge_distance`. Statut `suppressed` stocké dans `game_state["suppressed_squads"]` (`squad_id -> joueur suppresseur`), purgé au début de la phase de commande du suppresseur ; aucune datasheet ne le POSE encore — c'est la passe 6 (Indiscriminate Detonations).
- **Primitive B/F** : `invul_save_override`, `melee_strength_bonus`, `melee_attacks_bonus` rendent **0 hit** dans tout le dépôt — le Waaagh! est passé par des fonctions dédiées (`waaagh_melee_bonus`, `effective_invul_save`, §3). Les primitives génériques sont à **créer**, ne pas partir du principe qu'il suffit de les câbler.
- **Primitive C** : mécanisme moteur livré (voir passe 3) ; aucune datasheet ne porte encore `feel_no_pain` (`grep feel_no_pain frontend/src/roster` → 0 hit).
- **Primitive D** : le helper commun **existe** — `def allocate_mortal_wounds` (`shared_utils.py`), consommé par `def _apply_deadly_demise` (Deadly Demise) et `def roll_hazard_for_unit` (`[HAZARDOUS]`). `deadly_demise` est au registre (`config/unit_rules.json`, paramètre `value`) et câblée sur le WeirdBoy (prérequis posé hors passe, 2026-08-25, cf. Roadmap). Restent à unifier : `charge_impact` (`def _apply_charge_impact`, `charge_handlers.py`, chemin direct) et le lien avec `[DEVASTATING WOUNDS]`.
- **Primitive E** : le mécanisme « secured » existe comme propriété d'objectif (logique `control_method` « secured »/« default » de `def _sum_objective_control_oc`, `game_state.py`).

---

## Primitive A — `roll_modifiers`

**Modificateurs (+1/−1) et relances complètes sur les jets de touche et de blessure.**

### Point d'intégration

Les seuils sont calculés par l'appelant, puis passés au résolveur d'attaques (`def roll_attack_pool`, `engine/phase_handlers/attack_sequence.py`). Sites **jumeaux** : tir dans `engine/phase_handlers/shared_utils.py` (deux chemins, dont `def _manual_roll_intent`), mêlée dans `engine/phase_handlers/fight_handlers.py` (`def _manual_roll_fight_intent`).

Le seuil devient `clamp(base − bonus + malus, 2, 6)`. Le **1 non modifié reste un échec** (05.01) : le clamp ne doit jamais transformer un 1 en réussite.

`class RerollProfile` (`attack_sequence.py`) porte `hit_1`, `hit_any_fail` (livré par le chantier 03), `wound_1`, `wound_any_fail`, `save_1`.

### Capacités couvertes

| Capacité | Unité | Nom générique |
|---|---|---|
| Might Is Right | Warboss | `hit_roll_bonus_fight` |
| Litany of Hate | Chaplain with Jump Pack | `wound_roll_bonus_fight` |
| Somethin' to Prove | Bigboss | `charge_roll_bonus` |
| (malus de suppression) | posé par Indiscriminate Detonations | `hit_roll_malus_suppressed` |

`charge_roll_bonus` ne passe pas par l'attaque : il modifie le jet de charge, à côté de `reroll_charge` qui existe déjà.

## Primitive B — `granted_weapon_effects`

**Règles d'arme et caractéristiques (A / S / D) accordées par une règle d'unité.**

### Point d'intégration

`def build_weapon_attack_profile` (`attack_sequence.py`) est le point unique où les règles d'arme sont résolues pour un couple (arme, cible). Il gagne le contexte attaquant. Les lecteurs de A / S / D suivent le même chemin.

Les règles d'arme du PDF 24 sont **déjà implémentées** (`config/weapon_rules.json` : `SUSTAINED_HITS`, `LETHAL_HITS`, `BLAST`, `DEVASTATING_WOUNDS`, `HAZARDOUS`, etc. — voir [armes.md](../jeu/armes.md)). Cette primitive ne les réimplémente pas — elle permet à une règle d'**unité** de les accorder conditionnellement à une arme.

### Capacités couvertes

| Capacité | Unité | Nom générique | Effet |
|---|---|---|---|
| Breakin' Heads | Bigboss | `grant_weapon_rule_melee` | mêlée gagne `[SUSTAINED HITS 1]` |
| Vanguard Assault | Vanguard Veteran JP | `grant_weapon_rule_melee_after_charge` | mêlée gagne `[LETHAL HITS]` le tour d'une charge |
| Overlapping Detonations | Eradicator (heavy bolters) | `grant_weapon_rule_vs_designated_target` | heavy bolters gagnent `[BLAST 1]` contre la cible désignée, hors `MONSTER`/`VEHICLE` |
| Dakkablitz | Big Mek Dakkarig | `weapon_attacks_bonus_vs_keyword` | blitzkannon +6 A hors `MONSTER`/`VEHICLE` |
| Hail of Bolts | Intercessor | `weapon_attacks_bonus_vs_designated_target` | bolt rifles +2 A contre la cible désignée |
| Waaagh! Energy | Weirdboy | `weapon_profile_scaling_by_model_count` | 'Eadbanger : +1 S et +1 D par tranche de 5 figurines ; `[HAZARDOUS]` à 10+ |
| Da Biggest and da Best | Warboss | `melee_attacks_bonus_while_waaagh` | mêlée +4 A tant que le Waaagh! est actif |
| Finest Hour | Captain with Relic Shield | `once_per_battle_melee_buff` | mêlée +3 A et `[DEVASTATING WOUNDS]` jusqu'à la fin de la phase |

**Attention Dakkablitz** : la datasheet écrit `blitzcannon` dans la composition et `Blitzkannon` dans le profil d'arme. Même arme, deux orthographes dans le PDF. Ne pas créer deux entrées.

## Primitive C — `feel_no_pain`

**Jet d'ignorance de blessure, après allocation, avant décrément des PV.**

### Point d'intégration

**Le mécanisme moteur EST livré** : `def _get_feel_no_pain_threshold` / `def _roll_feel_no_pain` (`shared_utils.py`), lus par trois sites — tir, mêlée et blessures mortelles. La règle générique `feel_no_pain` existe au registre avec son `obs_id` et son paramètre `threshold` (`config/unit_rules.json`).

Ce qui manque est le CÂBLAGE : aucune datasheet ne la porte. La passe se réduit à déclarer la règle sur le Painboy, plus les deux variantes conditionnelles (Psychic Hood, Unbreakable Resolve) qui, elles, demandent un contexte que le seuil actuel ne porte pas.

L'ordre compte : le FNP s'applique **après** que la sauvegarde a échoué et que les dégâts sont alloués à une figurine, blessure par blessure. Il ne remplace pas la sauvegarde.

### Capacités couvertes

| Capacité | Unité | Nom générique | Condition |
|---|---|---|---|
| Dok's Toolz | Painboy | `feel_no_pain` (seuil 5) | aucune |
| Psychic Hood | Librarian | `feel_no_pain_vs_psychic` (seuil 4) | l'attaque provient d'une arme ou capacité `PSYCHIC` |
| Unbreakable Resolve | Ancient | `feel_no_pain_near_objective` (seuil 4) | à portée d'un objectif **ou** à 6" du centre du champ de bataille |

Le mot-clé `PSYCHIC` existe déjà sur les armes (`config/weapon_rules.json`). Les **capacités** psychiques (Da Jump) doivent aussi être marquées, sinon Psychic Hood sera incomplète. Les 6" d'Unbreakable Resolve se convertissent via `inches_to_subhex` — jamais de seuil en pouces absolus.

## Primitive D — `mortal_wounds`

**Blessures mortelles hors `[DEVASTATING WOUNDS]`, avec plusieurs déclencheurs.**

### Point d'intégration

Le helper commun « infliger N blessures mortelles à une unité » existe : `def allocate_mortal_wounds` (`shared_utils.py`), déjà appelé par Deadly Demise (`def _apply_deadly_demise`) et `[HAZARDOUS]` (`def roll_hazard_for_unit`). Restent deux chemins à **unifier**, pas dupliquer :

- `[DEVASTATING WOUNDS]` — `attack_sequence.py`, résolu à l'allocation par l'appelant ;
- `charge_impact` — `def _apply_charge_impact` (`engine/phase_handlers/charge_handlers.py`), qui décrémente les PV en direct sans passer par le helper.

### Capacités couvertes

| Capacité | Unité | Nom générique | Déclencheur |
|---|---|---|---|
| Hold Still and Say Aargh | Painboy | `mortal_wounds_on_critical_wound` | blessure critique de l'`'urty syringe` contre une unité non-`VEHICLE` → D6 MW |
| Exhortation of Rage | Chaplain JP | `mortal_wounds_on_fight_activation` | sélection pour combattre : D6 → 4-5 : D3 MW ; 6 : 3 MW à une unité engagée |
| Deadly Demise D3 | Weirdboy | `deadly_demise` | figurine détruite : D6 → sur 6, D3 MW à chaque unité dans 6" — **livrée hors passe** (registre + WeirdBoy, cf. Roadmap) |
| Da Jump (échec) | Weirdboy | — | D6 = 1 → D6 MW à l'unité elle-même (réserves : §4) |

**Deadly Demise 24.08** : le jet se fait **par figurine détruite**, après les débarquements d'urgence, et le X est tiré **séparément pour chaque unité** dans les 6" si c'est un nombre aléatoire. Trois détails qu'une implémentation rapide rate.

**Exhortation of Rage** : *« you can select one enemy unit it is engaged with »* — c'est un choix de joueur, donc une décision d'agent, pas une heuristique interne.

## Primitive E — `objective_effects`

**Sécurisation d'objectif et modification d'OC.**

### Point d'intégration

`def _sum_objective_control_oc` (`engine/game_state.py`, règle 14.02) et sa logique `control_method` « secured »/« default » (règle 14.03). Le mécanisme « secured » **existe déjà** comme propriété d'objectif — il s'agit de permettre à une capacité d'unité de le déclencher.

### Capacités couvertes

| Capacité | Unité | Nom générique |
|---|---|---|
| Get da Good Bitz | Boyz | `secure_objective_on_control` |
| Objective Secured | Intercessor | `secure_objective_on_control` |
| Relic Banner | Ancient | `oc_bonus` (+1 OC) |

**Les deux premières sont des jumeaux exacts** — textes identiques mot pour mot dans les deux PDF. Une seule règle générique, déclarée deux fois avec des `displayName` différents. Les coder séparément serait une duplication pure.

Déclenchement : fin de ta phase de commandement, si l'unité contrôle l'objectif.

## Primitive F — `unit_state_effects`

**Écritures dans l'état d'une unité : override de caractéristique, statut temporaire, compteur « une fois par bataille », restitution de figurines.**

C'est la primitive résiduelle. Elle est large mais cohérente : tout ce qui modifie l'état d'une unité en dehors de la séquence d'attaque.

### Capacités couvertes

| Capacité | Unité | Nom générique | Nature |
|---|---|---|---|
| Waaagh! Banner (clause 1) | Bannernob | `invul_save_override` (5) | override, **toute l'unité** |
| Waaagh! Banner (clause 2) | Bannernob | `toughness_bonus_while_waaagh` (+1 T) | override conditionnel |
| Mental Fortress | Librarian | `invul_save_override` (4) | override, **toute l'unité** |
| Indiscriminate Detonations | Wartrakk | `suppress_target_on_shooting` | statut posé sur l'ennemi |
| Grot Orderly | Painboy | `return_destroyed_models` | 1×/partie, phase de commandement, D3 figurines |
| Finest Hour (compteur) | Captain | `once_per_battle` | compteur, l'effet est en primitive B |
| Purgation Run | Land Speeder | `move_after_shooting` **étendu** | voir ci-dessous |

### Le piège des InSv conférés

`frontend/src/roster/ork/units/BannerNob.ts` porte `INVUL_SAVE = 5` **sur la figurine**. La datasheet dit *« This unit has a 5+ InSv »* — donc **toute l'escouade** à laquelle il est rattaché. Aujourd'hui, attacher un Bannernob à des Boyz ne leur donne rien. Même défaut pour Mental Fortress (Librarian, 4+ InSv, *« This unit »*). Ce n'est pas une caractéristique statique : c'est un effet conféré, qui disparaît si le porteur meurt (règle 19.04 sur l'union des règles en vigueur). Le motif d'override existe déjà pour le Waaagh! (`def effective_invul_save`, §3) — la déclinaison « accordé par une règle d'unité » reste à créer.

### `move_after_shooting` : extension, pas création

La règle **existe** (`UNIT_RULE_EFFECT_IDS`, `def _build_move_after_shooting_destinations`, `engine/phase_handlers/shooting_handlers.py`). Deux manques :

1. La distance est un **entier fixe** en paramètre ; Purgation Run demande **D6"**.
2. `frontend/src/roster/spaceMarine/units/LandSpeederOnslaughtGatlingCannon.ts` ne déclare que `deep_strike` (chantier 04) — Purgation Run n'est pas câblée.

### Suppression

*« While a unit is suppressed, it has -1 to hit rolls. »* Durée : jusqu'au début de ta prochaine phase de commandement. Le statut vit dans `status_ids` (id `suppressed`, déjà déclaré dans `config/unit_statuses.json`) ; le malus est appliqué par la primitive A.

## Capacités traitées ailleurs

| Capacité | Unité | Où |
|---|---|---|
| Waaagh! (faction) | toutes les orkes | §3 |
| Oath of Moment (faction) | toutes les SM | §3 |
| Thievin' Scavengers | Gretchin | §2 (CP) |
| Rites of Battle | Captain Relic Shield | §2 — **non livrable** sans stratagèmes |
| CORE: Deep Strike | Chaplain JP, Vanguard JP, Land Speeder | §4 |
| Da Jump | Weirdboy | §4 (20.02) + primitive D |

## Déjà correct, à ne pas retoucher

- **Relic Shield** (Captain, +1 W) — inclus dans le profil, la datasheet le dit explicitement (*« included in profile »*).
- Les règles d'arme du PDF 24 (`config/weapon_rules.json`) — implémentées.

## Prompt d'exécution — 6 passes

> Prompt CONSERVÉ (chantier à venir) : une passe par primitive, exécutables séparément sans replanifier. L'avancement se pointe dans [Roadmap/capacites.md](../../Roadmap/archives/capacites.md).

### Préalable

Chantiers 01, 03, 04, 05 livrés. Le chantier 02 est souhaitable mais pas bloquant (aucune capacité de ce chantier ne dépend des CP).

Ce chantier **ne change ni `obs_size` ni `TOTAL_ACTION_SIZE`**. Toute capacité qui semble l'exiger signale une erreur du socle (§1) : remonter, ne pas contourner.

### Découpage en passes

Une passe par primitive, dans cet ordre. Chaque passe est autonome et se termine par ses propres tests.

| Passe | Primitive | Capacités |
|---|---|---|
| 1 | A `roll_modifiers` | 4 |
| 2 | B `granted_weapon_effects` | 8 |
| 3 | C `feel_no_pain` | 3 |
| 4 | D `mortal_wounds` | 4 |
| 5 | E `objective_effects` | 3 |
| 6 | F `unit_state_effects` | 7 |

Les passes 1 et 2 débloquent à elles seules 12 capacités et n'exigent aucune structure d'état nouvelle — les faire d'abord.

### Ce que le chantier 05 laisse en entrée (2026-08-10)

Le placeholder `reroll_charge` / « Unstoppable Valour » est purgé de **tous** les rosters, sans exception ni dette. Les tests de la règle 19.04 s'ancraient dessus faute d'autre porteur ; ils reposent désormais sur un couple de vraies datasheets — `ChaplainJumpPack` (`deep_strike`) mené sur `AssaultIntercessorJumpPack` (`charge_impact`), discriminant dans les deux sens et légal au titre de 19.01.

Conséquence pour la passe 1 : rien à solder avant de commencer. Le témoin de règle de LEADER observable qui manquait est arrivé sans attendre **Litany of Hate** : `deep_strike` a reçu son `obs_id`, et `test_attached_squad_rule_is_observed_then_extinguished_with_its_source` (`tests/unit/engine/test_squad_obs_unit_rules.py`) verrouille les deux sources de l'union 19.04 au lieu de la seule BODYGUARD. Quand Litany of Hate (`wound_roll_bonus_fight`) sera livrée sur le Chaplain, elle n'aura donc rien à rattraper de ce côté.

### Périmètre

**Autorisé :**
- `engine/phase_handlers/` — `attack_sequence.py`, `shared_utils.py`, `fight_handlers.py`, `shooting_handlers.py`, `charge_handlers.py`, `command_handlers.py`
- `engine/game_state.py` — contrôle d'objectif, overrides
- `config/unit_rules.json` — déclaration des règles génériques + `obs_id`
- `frontend/src/roster/{ork,spaceMarine}/units/*.ts` — `UNIT_RULES` des unités concernées
- Tests ciblés, [`Documentation/Reference/jeu/regles_unites.md`](../jeu/regles_unites.md)

**Interdit :** toucher `obs_size`, l'action space, ou une unité hors rosters Armageddon.

### Vérification exigée — pour chaque passe

- **Verrou par capacité** : un test qui **construit** la situation, l'observe, puis remet le défaut et vérifie que le test devient **rouge**. Sans cette preuve, considérer le test comme absent. (Inutile sur du parsing trivial.)
- **Jumeau** : après chaque correction, `grep` du motif et vérification explicite de son existence ailleurs — tir/mêlée, IA/PvP, moteur/replay/analyzer, front/back. Rapporter le résultat **même vide**.
- **Chemin de production** : vérifier que le code écrit est réellement **atteint** par le vrai chemin. Du code testé mais jamais appelé ne corrige rien — motif déjà rencontré ici.
- **Vert vacant** : vérifier que l'échantillon produit des données. Un contrôle qui ne regarde rien affiche « tout va bien ».
- **Analyzer** : chaque capacité doit être vérifiable par `ai/analyzer.py` sur un replay. Une capacité invisible à l'analyzer n'est pas vérifiable en conditions réelles.

### Pièges spécifiques relevés à la lecture des PDF

- **Get da Good Bitz / Objective Secured** : textes identiques. Une règle, deux déclarations.
- **Deadly Demise** : par figurine, après débarquements, X tiré séparément par unité.
- **Hold Still and Say Aargh** : uniquement l'`'urty syringe`, uniquement sur une **blessure critique**, uniquement contre du non-`VEHICLE`.
- **Waaagh! Energy** : « for every 5 models » compte les figurines de l'**unité**, pas les Weirdboyz. `[HAZARDOUS]` à 10+, pas à 11+.
- **Overlapping Detonations** et **Hail of Bolts** : la cible est **désignée** au moment où l'unité est sélectionnée pour tirer, avant de choisir les cibles des armes. Deux étapes distinctes, ne pas les fusionner.
- **Purgation Run** : D6", pas 6" fixes.
- **InSv conférés** (Bannernob, Librarian) : effet sur l'**unité**, pas caractéristique de la figurine.
- **Finest Hour** : *« when this unit is selected to fight »*, une fois par bataille, effet jusqu'à la **fin de la phase** — pas de l'activation.
- Toute distance en pouces se convertit via `inches_to_subhex`.

---

# Correspondance des sources

| Source | Ancien § | Section actuelle |
|---|---|---|
| `01_ability_embedding.md` | Pourquoi ce chantier existe | §1 « Pourquoi ce socle existe » |
| `01_ability_embedding.md` | Le mécanisme (+ ses quatre « Pourquoi ») | §1 « Le mécanisme : deux ensembles d'identifiants entiers » |
| `01_ability_embedding.md` | Pourquoi 8 et 4, et pas 6 et 3 | §1 « Dimensionnement des slots : mesure vs projection » |
| `01_ability_embedding.md` | Débordement : erreur, jamais troncature | §1 « Débordement : erreur, jamais troncature » |
| `01_ability_embedding.md` | Ce qui ne va PAS dans l'ensemble par unité (+ amendements 2026-08-05/06) | §1 « Ce qui ne va PAS dans l'ensemble par unité » |
| `01_ability_embedding.md` | Registre des identifiants + Amendement OBSERVÉ ≠ ACCORDABLE | §1 « Registres des identifiants » et « Vocabulaire OBSERVÉ ≠ effets ACCORDABLES » |
| `01_ability_embedding.md` | `OATH_SLOTS` — dimension d'action, pas `CHOICE_k` | §1 « `OATH_SLOTS` — dimension d'action, pas `CHOICE_k` » |
| `01_ability_embedding.md` | Le gel (+ rupture §0.48) ; Bilan de taille | §1 « Le gel du socle » (chiffres → configs/code) |
| `01_ability_embedding.md` | EXÉCUTION — prompt | purgé (chantier livré) ; clauses normatives repliées dans §1 |
| `02_command_points.md` | Sources ; Périmètre — arbitrage rendu | §2 « Sources règles » et « Périmètre — arbitrage rendu » |
| `02_command_points.md` | La phase de commandement (08.01–08.05) | §2 « La phase de commandement en cinq étapes » |
| `02_command_points.md` | Le battle-shock (01.06, 01.07, appendice 25) | §2 « Le battle-shock, tel que le PDF le définit » |
| `02_command_points.md` | Thievin' Scavengers ; Rites of Battle ; Observation | §2 sections homonymes |
| `02_command_points.md` | Ce qui manque, exactement ; EXÉCUTION — prompt | purgés (état d'avant-chantier / prompt consommé) |
| `03_faction_abilities.md` | Pourquoi ces capacités ne vont PAS dans `ability_ids` | §3 (préambule) + §1 |
| `03_faction_abilities.md` | Waaagh! (décomposition, effet mesuré, observation) | §3 « Waaagh! (ORKS) » |
| `03_faction_abilities.md` | Oath of Moment (`hit_any_fail`, désignation, clause +1 W, observation) | §3 « Oath of Moment (ADEPTUS ASTARTES) » |
| `03_faction_abilities.md` | EXÉCUTION — prompt (dont expiration, condition escouades sur table) | purgé ; clauses normatives repliées dans §3 |
| `04_strategic_reserves.md` | Pourquoi ce chantier existe ; Ce qui existe déjà | §4 (préambule) et « Structure d'état » |
| `04_strategic_reserves.md` | Les règles, décomposées (20.01–20.04, 24.09) | §4 « Les règles, décomposées » |
| `04_strategic_reserves.md` | Observation (dont `deep_strike` obs_id, round restant) | §4 « Observation » |
| `04_strategic_reserves.md` | EXÉCUTION — prompt (dont pièges) | purgé ; clauses normatives repliées dans §4 « Pièges » |
| `06_armageddon_abilities.md` | Note sur le décompte | §5 « Note sur le décompte » (**titre conservé — cité par `engine/observation_entities.py`**) |
| `06_armageddon_abilities.md` | Vocabulaire ; Primitives A–F | §5 sections homonymes |
| `06_armageddon_abilities.md` | Capacités traitées ailleurs ; Déjà correct | §5 sections homonymes |
| `06_armageddon_abilities.md` | EXÉCUTION — prompt (6 passes) | §5 « Prompt d'exécution — 6 passes » (**conservé**, chantier ouvert) |

# Historique et sources

- **Chantier 01** (embedding des capacités, socle obs/action) : livré le **2026-08-04**, vérifié code le 2026-08-10. Amendements le jour de la livraison : séparation OBSERVÉ/ACCORDABLE et correction de la projection « 6 en vigueur » ; le 2026-08-05 : emplacements des capacités de faction (oubliés au gel) ; le 2026-08-06 : bits `*_oath_wound_bonus_active`.
- **Chantier 02** (CP + battle-shock) : livré, vérifié code le 2026-08-10. Dette bornée : dépense de CP sans consommateur ; Rites of Battle hors périmètre.
- **Chantier 03** (Waaagh! / Oath) : livré, vérifié code le 2026-08-10 (`waaagh`, `oath_of_moment`, `hit_any_fail` sur les sites jumeaux). Condition `player_has_squads_on_board` ajoutée le 2026-08-11. Dette bornée : `uses_codex_detachment` déclaré, non déduit.
- **Chantier 04** (réserves / Deep Strike) : livré, vérifié code le 2026-08-10 ; `obs_id` de `deep_strike` posé le 2026-08-10 (six jours après la mécanique). Point non tranché : round restant avant destruction non observé.
- **Chantier 05** (purge du placeholder `reroll_charge`) : livré le 2026-08-10 — son legs pour le 06 est en §5.
- **Chantier 06** : ouvert — état dans [Roadmap/capacites.md](../../Roadmap/archives/capacites.md) ; recomptage du bandeau le 2026-08-10 (seul `hit_any_fail` était posé) ; Deadly Demise câblée hors passe le 2026-08-25.
- **Gel rompu hors série** par V11 §0.48 L2 (2026-08-07) — cf. [ROADMAP_INDEX.md](../../Roadmap/ROADMAP_INDEX.md).
- Chiffres volatils : `obs_size` → clé `obs_size` + `justification` de `config/agents/ArmageddonAgent/ArmageddonAgent_training_config.json` (lignée complète) ; `TOTAL_ACTION_SIZE` et la carte des familles d'actions → `engine/macro_intents.py` ; `obs_id` occupés → `config/unit_rules.json` + `config/unit_statuses.json` ; schéma d'observation → `engine/observation_entities.py` et [observation_et_actions.md](../training/observation_et_actions.md).
