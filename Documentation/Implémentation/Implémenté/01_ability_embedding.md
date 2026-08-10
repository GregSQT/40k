# Chantier 01 — Embedding des capacités et gel de l'observation
> ✅ **LIVRÉ le 2026-08-04** (vérifié code le 2026-08-10). La **CONCEPTION** ci-dessous reste la référence vivante du socle obs/action ; l'**EXÉCUTION** n'a plus que valeur d'historique.
>
> ⚠️ Chiffres d'`obs_size` de ce fichier **périmés** (14609/14615) : la valeur à HEAD est **16659**. Voir [`../ROADMAP.md`](../ROADMAP.md) §5.
>
> **Série « chantiers capacités » (ex-`2_Various/`, dossier dissous le 2026-08-10).** Les chantiers **01 à 05 sont LIVRÉS** et rangés dans `Implémenté/` ; seul le **06** reste ouvert, dans `A_faire/`. Les renvois « chantier 0X » du texte désignent ces fichiers, qui ont gardé leur nom.
> Ordre du travail : [`../ROADMAP.md`](../ROADMAP.md) — ce fichier n'est pas une roadmap.

> **Deux cycles de vie dans ce fichier.** La partie **CONCEPTION** reste vraie après
> l'implémentation et fait foi. La partie **EXÉCUTION** est un prompt consommé une fois ;
> une fois le chantier livré, elle n'a plus valeur que d'historique.

---

# CONCEPTION — à maintenir

## Pourquoi ce chantier existe

Aujourd'hui, chaque entité d'unité de l'observation porte **un bit par capacité connue du
moteur** : `UNIT_RULE_EFFECT_IDS`, 13 entrées, émises comme `rule_<id>` dans
`UNIT_BIN_FIELDS` (`engine/observation_entities.py:103`).

Ce schéma grossit linéairement avec le nombre de capacités du jeu. Chaque capacité ajoutée
change `UNIT_BIN_SIZE`, donc `obs_size`, donc **invalide tout modèle entraîné**
(`retrain --new`). Les 17 capacités Armageddon coûteraient déjà `17 × 28 = 476` scalaires
et un retrain ; chaque faction ultérieure en coûterait un de plus.

L'objectif est de **rendre le coût nul** : après ce chantier, ajouter une capacité, un
statut ou une faction entière ne change ni `obs_size`, ni le nombre de paramètres du réseau,
ni l'action space. Aucun retrain.

## Le mécanisme

Chaque unité porte deux **ensembles d'identifiants entiers**, pas des bitmaps :

| Champ | Contenu | Cardinal |
|---|---|---|
| `ability_ids` | capacités **en vigueur** (règle 19.04 : union des sources vivantes) | 8 |
| `status_ids`  | statuts **en vigueur** (`battle_shock`, `oath_target`, `suppressed`) | 4 |

Ces entiers alimentent deux `EmbeddingBag` **distinctes**, chacune pré-dimensionnée à
**128 lignes × 16 dimensions**, avec `padding_idx = 0`, pooling **somme**. Les deux sorties
(16 + 16) sont concaténées et rejoignent l'encodeur d'entité partagé.

### Pourquoi aucun one-hot n'apparaît

Un `EmbeddingBag` fait une **lecture de ligne** `table[id]`. Le one-hot n'est jamais
matérialisé, ni dans l'observation, ni dans le réseau. L'observation transporte des entiers.
C'est ce qui rend la longueur du vecteur indépendante du nombre de capacités existantes.

### Pourquoi deux tables et pas une

Une capacité (« cette unité a Feel No Pain ») et un statut (« cette unité est la cible Oath
adverse ») sont de nature différente. Un pooling commun les additionnerait dans le même
espace et le réseau ne pourrait plus les distinguer. Deux tables, deux poolings, concaténation.

### Pourquoi le pooling somme

- **Invariance par permutation** : `{A, B}` écrit en (slot0, slot1) ou (slot1, slot0) produit
  le même vecteur. C'est la propriété qui disqualifiait les « slots » naïfs.
- **Multiplicité préservée** : contrairement à la moyenne, la somme distingue un ensemble de
  1 élément d'un ensemble de 3.

### Pourquoi trier quand même

Le pooling rend l'ordre indifférent au réseau, mais **pas au debug**. Les ids sont écrits
**triés par ordre croissant**, pour que l'observation soit reproductible bit à bit d'un run à
l'autre : sans ça, les diffs de replay et les comparaisons d'état deviennent illisibles.

### Pourquoi 8 et 4, et pas 6 et 3

⚠️ **Correction du 2026-08-04, à la livraison.** Le chiffre de 6 ci-dessous n'est pas une mesure
mais une **projection** de l'état post-chantier 06 : les capacités citées n'existent pas encore
dans le moteur. Mesuré sur le dépôt réel le jour de la livraison (`UnitRegistry` +
`unit_has_rule_effect` sur les 13 effets, 179 datasheets, puis les 70 paires et 50 trios
d'attachement légaux 19.01/24.22/24.34) : **2** effets au maximum par datasheet et **3** au
maximum en vigueur sur une entité (`AssaultIntercessor + CaptainPowerWeaponBolter [+ Ancient]`).
La marge réelle est donc de 5 slots aujourd'hui, et le dimensionnement à 8 se justifie par la
projection — qui deviendra mesurable au chantier 06, où ce chiffre est à rouvrir.

Le maximum **projeté** sur les rosters Armageddon est de 6 capacités en vigueur sur une même
entité :

> `Boyz + Warboss + Painboy` → Get da Good Bitz, Might Is Right, Da Biggest and da Best,
> Dok's Toolz, Hold Still and Say Aargh, Grot Orderly
>
> `Intercessor + Captain Relic Shield + Ancient` → Objective Secured, Hail of Bolts,
> Finest Hour, Rites of Battle, Relic Banner, Unbreakable Resolve

6 slots signifierait **zéro marge** : une seule capacité ajoutée à une figurine rattachée fait
déborder. 8 coûte `2 × 28 = 56` scalaires — 0,3 % de l'observation — pour supprimer un mode de
défaillance dur.

### Débordement : erreur, jamais troncature

Si une unité porte plus de capacités que de slots, le moteur **lève**. Tronquer
silencieusement ferait subir à l'agent des règles qu'il ne perçoit pas — exactement le trou
que V11 §0.30 avait fermé.

## Ce qui ne va PAS dans l'ensemble par unité

**Les effets de faction.** Waaagh! accorde quatre effets identiques à *toutes* les unités
orkes. Les inscrire dans l'ensemble de chaque unité, c'est répéter 4 ids sur 28 entités et
faire déborder les slots pour zéro information : le réseau reconstitue l'effet à partir de
« cette unité est orke » + « Waaagh! actif », deux informations **globales**.

Les capacités de faction vont donc dans `global_bin`. Voir chantier 03.

## Registre des identifiants

`config/unit_rules.json` est déjà le registre des règles. Chaque règle y gagne un champ
`obs_id` : entier **stable et jamais réattribué** dans `[1, 127]`. `0` est réservé au padding.

Un second registre, `config/unit_statuses.json`, suit la même convention pour les statuts.

### Amendement du 2026-08-04 — vocabulaire OBSERVÉ ≠ effets ACCORDABLES

`UNIT_RULE_EFFECT_IDS` jouait **deux** rôles : le vocabulaire des capacités observées (dont
l'ajout devait être gratuit) **et** la liste des effets qu'un candidat de décision peut
accorder — registre POSITIONNEL, 1 bit par effet, émis pour chacun des `MAX_DECISION_OPTIONS`
slots (`DECISION_OPTION_BIN_FIELDS`). Ajouter **une** capacité observable coûtait donc
**+6 scalaires** d'`obs_size`, donc un retrain `--new` : la promesse ci-dessus était fausse
d'un facteur 6, et 6 des 13 effets portaient des bits qu'aucun roster ne pouvait jamais mettre
à 1 (36 scalaires morts).

Les deux vocabulaires sont **séparés** depuis :

| Tuple | Rôle | Coût d'une entrée |
|---|---|---|
| `UNIT_RULE_EFFECT_IDS` | ce que l'agent PERÇOIT (ids → embedding) | **0 scalaire** |
| `DECISION_GRANTABLE_EFFECT_IDS` | ce qu'un candidat de `rule_choice` ACCORDE | 1 bit × 6 slots |

Le second est un sous-ensemble strict du premier, **dérivé** des `grantsRuleIds` réellement
déclarés par les rosters — un test de contrat le recalcule et échoue dans les deux sens. La
garde d'`effect_ids` de `agent_decision.set_pending_agent_decision` contrôle contre ce tuple-là :
un effet accordable mais non déclaré **lève** à la pose de la décision, au lieu d'être décrit
par un vecteur nul.

Le verrou qui manquait — et sans lequel le couplage pouvait revenir sans que rien ne lève —
est `test_adding_an_observed_capability_costs_zero_scalar` : il recalcule `obs_size` **dans un
processus neuf** bâti sur un schéma d'entités augmenté d'une capacité fictive, et compare le
**nombre**.
Lire le texte de la formule ne suffirait pas — un terme d'un autre module (`PROFILE_BIN_SIZE`)
ou derrière une indirection (`K_X = _calcule()`) y échapperait ; le nombre couvre tous les
termes où qu'ils vivent. Le balayage des constantes du schéma vient en plus, pour nommer le
registre fautif.

Stabilité : un `obs_id` réattribué après suppression d'une règle ferait pointer un modèle
entraîné sur une ligne d'embedding qui ne veut plus dire la même chose — corruption
silencieuse. Un id retiré reste **brûlé**.

## Bilan de taille

| | Avant | Multi-hot (rejeté) | Retenu |
|---|---|---|---|
| Par entité d'unité | 13 bits | 30 bits | 12 entiers |
| × 28 entités (8 alliées + 20 ennemies) | 364 | 840 | 336 |
| Δ `obs_size` (base 20780) | — | +476 | **−28** |
| Ajouter une faction | retrain | retrain | **rien** |

## Le gel

Ce chantier est **le seul** de la séquence autorisé à changer `obs_size` ou
`TOTAL_ACTION_SIZE`. Après lui, les deux sont figés : les chantiers 02 à 06 n'utilisent que
des dimensions déjà déclarées ici. C'est ce qui garantit **un seul retrain** en fin de séquence.

⚠️ **LE GEL A ÉTÉ ROMPU, ET C'ÉTAIT PRÉVU.** L'élément `L2` du lot §0.48 (choix de l'escouade à
activer, 2026-08-07) ajoute une FAMILLE D'ACTIONS entière qui n'existait sous aucune forme :
`TOTAL_ACTION_SIZE` **1127 → 1139**, et `K_ALLY_SLOTS` 8 → 12 avec lui, donc `obs_size`
**14615 → 16659**. Ce n'est pas un chantier « 02 à 06 » — le gel ne le couvrait pas, §0.48 l'avait
inventorié comme cassant deux contrats. Le retrain reste UNIQUE : `L1`, `L2` et `L6` voyagent
ensemble. Les valeurs ci-dessous sont donc l'HISTORIQUE du socle, plus l'état courant.

**Valeur gelée par le socle : `obs_size = 14609`** — socle du lot V11 §0.48 (2026-08-07 : règles d'armes en ids,
types de décision et slots de déploiement pré-dimensionnés, cf. `V11_agent_rework.md` §0.67), plus
le drapeau `declines` du bloc candidat de décision livré par `L1` (`14609` → `14615`, même jour,
même retrain).
Valeurs antérieures : `20727` (amendée le 2026-08-06, cf. ci-dessous), 20725 au 2026-08-05, 20718
au 2026-08-04. Historique du même jour, tout entier
absorbé par le retrain unique : `20780` → `20752` (les 13 bits `rule_*` remplacés par 8+4 slots
d'ids) → `20754` (les deux scalaires de CP que le chantier 02 attendait, oubliés ici) → `20718`
(découplage du registre de décision, ci-dessus). Le gel porte désormais ce qu'il promettait :
une capacité observée de plus coûte **zéro** scalaire, verrou à l'appui.

**Amendement du 2026-08-05 — les emplacements des capacités de faction, oubliés ici.** La section
« Ce qui ne va PAS dans l'ensemble par unité » ci-dessus conclut que les capacités de faction vont
dans `global_bin` et renvoie au chantier 03 — mais ce chantier-ci n'y a déclaré aucun emplacement,
ni le type de décision qu'exige l'appel du Waaagh!. C'est le même oubli que les deux scalaires de
CP du chantier 02, et il est réparé de la même façon : le chantier 03 pose les sept emplacements
manquants, `20718 → 20725`, et le retrain `--new` reste **unique** (les `.zip` existants datent
d'avant le gel du 2026-08-04). Détail :

| Emplacement | Registre | Coût |
|---|---|---|
| `my`/`enemy_waaagh_available`, `my`/`enemy_waaagh_active` | `GLOBAL_BIN_FIELDS` | 4 |
| `my`/`enemy_oath_target_selected` | `GLOBAL_BIN_FIELDS` | 2 |
| `waaagh_call` | `AGENT_DECISION_TYPE_IDS` (→ `decision_ctx_bin`) | 1 |
| `my`/`enemy_oath_wound_bonus_active` (2026-08-06) | `GLOBAL_BIN_FIELDS` | 2 |

Quatre bits pour le Waaagh! et non deux : sa durée court *« until the start of your next Command
phase »*, donc elle enjambe le tour adverse. L'identité de la cible d'Oath n'est PAS dans
`global_bin` — elle est portée par le statut `oath_target` de l'entité visée, déjà déclaré ici,
pour **zéro** scalaire.

**Amendement du 2026-08-06 — la clause conditionnelle du +1 Wound.** `20725 → 20727`. Les deux
bits `*_oath_target_selected` disent qu'une désignation est en vigueur, jamais quelle RÈGLE elle
ouvre : le +1 au jet de blessure est subordonné au détachement Codex ET à l'absence d'unité BLOOD
ANGELS / DARK ANGELS / DEATHWATCH / SPACE WOLVES, là où la relance de touche ne dépend d'aucune des
deux moitiés. Cette clause dépend du ROSTER, qu'aucune autre feature ne porte — les mots-clés de
sous-faction des unités ALLIÉES ne sont pas observés, et la clause compte les unités MORTES. Sans
ces bits, deux parties identiques à l'écran n'ont pas la même règle d'attaque et la politique de
désignation n'est pas séparable.

D'où l'inclusion, ici et pas en 03, des slots d'action d'Oath of Moment (ci-dessous).

## `OATH_SLOTS` — dimension d'action, pas `CHOICE_k`

Oath of Moment désigne *« one unit from your opponent's army »*. `engine/macro_intents.py:65`
porte la doctrine applicable :

> ⚠️ Elles [les actions `CHOICE_i`] ne concernent QUE les décisions dont les candidats ne sont
> PAS des entités déjà observées : une décision « quelle escouade ennemie » se paramètre en
> dimension d'action + pointeur, pas en `CHOICE_k`.

Oath suit donc le motif de `SHOOT_SLOTS` / `CHARGE_SLOTS` / `FIGHT_SLOTS` : un
`OATH_SLOT_COUNT` **dérivé** de `SHOOT_SLOT_COUNT`, indexant le **même**
`get_enemy_slot_mapping` que l'observation.

C'est l'invariant D1 : l'action *i* et la ligne *i* du tenseur ennemi désignent la **même**
escouade. Les désolidariser ferait pointer l'action et l'observation sur deux escouades
différentes sans que rien ne lève.

`MAX_DECISION_OPTIONS` **reste à 6**. Waaagh! est une décision binaire (appeler / ne pas
appeler) et y tient sans difficulté.

Carte d'action après ce chantier :

```
   0-1023 : move cells (32×32)
   1024   : wait / fin d'activation
1025-1044 : shoot slot 0-19
1045-1064 : charge slot 0-19
1065-1084 : fight slot 0-19
   1085   : fight sans cible éligible
1086-1100 : zone intents (5 objectifs × 3)
1101-1106 : CHOICE_0..5
1107-1126 : oath slot 0-19          ← NOUVEAU
TOTAL_ACTION_SIZE : 1107 → 1127
```

---

# EXÉCUTION — prompt

## Périmètre

**Autorisé :**
- `engine/observation_entities.py` — schéma d'entités
- `engine/observation_builder.py` — construction des tenseurs, `SQUAD_OBS_SIZE_TARGET`
- `engine/macro_intents.py` — `OATH_SLOT_*`, `TOTAL_ACTION_SIZE`
- `engine/phase_handlers/shared_utils.py` — miroir `SQUAD_ACTION_*`
- `ai/` — features extractor (les deux `EmbeddingBag`)
- `config/unit_rules.json` — champ `obs_id`
- `config/unit_statuses.json` — **création**
- `config/agents/*/*_training_config.json` — nouvelle valeur `obs_size`
- Tests des fichiers ci-dessus
- `Documentation/AI_OBSERVATION.md`, `Documentation/Unit_rules.md`

**Interdit :** toute implémentation de capacité. Ce chantier ne change *aucun* comportement
de jeu. À la fin, les 13 effets existants passent par le nouveau canal et produisent
exactement le même jeu.

## Étapes

1. **Registres.** Ajouter `obs_id` aux 13 règles de `config/unit_rules.json`
   (marqueurs de rôle `leader`/`support`/`sergeant`/`special_weapon` **exclus** : ils ne sont
   pas dans `UNIT_RULE_EFFECT_IDS` et ne sont pas observés). Créer
   `config/unit_statuses.json` avec les trois statuts déjà identifiés par les chantiers
   suivants — `battle_shock` (02), `oath_target` (03), `suppressed` (06) — déclarés ici et
   **non renseignés** : ce sont leurs chantiers qui les posent. Les déclarer maintenant est ce
   qui garantit que ces chantiers ne toucheront pas `obs_size`.
   Chargeur : `obs_id` absent, dupliqué ou hors `[1,127]` → **erreur explicite**.
   *(Amendement 2026-08-04.)* Le registre du bloc `decision_options_bin` n'est **pas** ce
   vocabulaire : c'est `DECISION_GRANTABLE_EFFECT_IDS`, dérivé des `grantsRuleIds` des rosters
   (cf. CONCEPTION). `obs_id` occupés à ce jour : **1 → 14** ; le prochain libre est **15**.

2. **Schéma d'entités.** Retirer les 13 bits `rule_<id>` de `UNIT_BIN_FIELDS`. Ajouter
   `UNIT_ABILITY_SLOTS = 8`, `UNIT_STATUS_SLOTS = 4` (noms LIVRÉS ; ce plan écrivait
   `ABILITY_SLOTS`/`STATUS_SLOTS`, corrigé le 2026-08-10), et les tenseurs `allies_ability_ids`,
   `allies_status_ids`, `enemies_ability_ids`, `enemies_status_ids`.
   Mettre à jour `SQUAD_OBS_SIZE_TARGET`.

3. **Construction.** Dans `observation_builder`, remplacer l'écriture des bits par
   l'écriture des ids : lire les capacités **en vigueur** (même source que les bits
   actuels — `unit_has_rule_effect` sur `UNIT_RULES`, l'union 19.04), mapper vers `obs_id`,
   **trier croissant**, remplir les slots, padder à `0`.
   Débordement → `raise` nommant l'unité et les capacités en excès.

4. **Action space.** `OATH_SLOT_BASE`, `OATH_SLOT_COUNT = SHOOT_SLOT_COUNT`,
   `OATH_SLOTS`, `TOTAL_ACTION_SIZE`. Répercuter dans le miroir `SQUAD_ACTION_*` de
   `shared_utils.py`. Les slots sont **déclarés et masqués à zéro** : aucun consommateur
   avant le chantier 03.

5. **Features extractor.** Deux `nn.EmbeddingBag(128, 16, mode="sum", padding_idx=0)`,
   sorties concaténées à la représentation d'entité.

6. **Config.** Recalculer `obs_size` et le reporter dans les configs d'agent, avec la
   justification mise à jour.

## Vérification exigée

- **Iso-comportement** : à capacités identiques, un épisode à graine fixée produit la même
  séquence d'actions qu'avant le chantier. C'est le critère d'acceptation principal.
- **Verrou de débordement** : test qui construit une unité à 9 capacités et exige le `raise`.
  Le retirer doit rendre le test **rouge** — le prouver et le rapporter.
- **Verrou de la promesse** (amendement 2026-08-04) : une capacité fictive ajoutée au
  vocabulaire OBSERVÉ ne change **aucune** dimension d'observation. Prouvé rouge sur trois
  défauts remis : `DECISION_OPTION_BIN_FIELDS` rebâti sur `UNIT_RULE_EFFECT_IDS` (`15 ≠ 16`),
  `PROFILE_BIN_SIZE` couplé au vocabulaire depuis un autre module, et `K_MODEL_TYPES` couplé
  derrière une indirection.
- **Verrou de tri** : deux unités de mêmes capacités déclarées dans des ordres différents
  produisent des `ability_ids` identiques.
- **Verrou d'unicité** : `obs_id` dupliqué dans `unit_rules.json` → erreur au chargement.
- `test_action_space_mirror.py` doit rester vert (il verrouille le miroir
  `macro_intents` ↔ `shared_utils`).
- Fichiers de test ciblés lancés par l'agent. **La vérification large appartient à
  l'utilisateur** (cf. CLAUDE.md).

## Pièges

- **Ne pas** réattribuer un `obs_id` libéré.
- **Ne pas** mettre les effets de faction dans `ability_ids` (chantier 03).
- Les entités ennemies et alliées partagent le **même** schéma : toute écriture faite d'un
  côté doit l'être de l'autre. C'est le motif d'échec n°1 du dépôt.
- `SQUAD_OBS_SIZE_TARGET` est calculé, jamais recopié en littéral.
