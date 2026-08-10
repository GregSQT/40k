# Chantier 06 — Capacités d'unité Armageddon (6 primitives, 25 capacités)
> 🔴 **OUVERT — 0/6 passes** (vérifié code le 2026-08-10 : aucun nom générique des 6 primitives n'existe dans `config/unit_rules.json`). Tous les prérequis (01→05) sont livrés.
>
> ⚠️ Risque d'exécution : `UNIT_ABILITY_SLOTS = 8` (`engine/observation_entities.py`, `grep UNIT_ABILITY_SLOTS` — le nom `ABILITY_SLOTS` nu, écrit ici jusqu'au 2026-08-10, n'existe nulle part dans le code) est une **projection non mesurée** — si une entité dépasse 8 capacités en vigueur, le moteur **lève** (débordement par erreur, jamais troncature). Ce chantier est ce qui rend le chiffre mesurable.
>
> ⚠️ **Recompté le 2026-08-10 — ce bandeau était faux aux 3/4.** Seul `hit_any_fail` (primitive A) a été posé par le chantier 03 (5 hits : `engine/w40k_core.py`, `engine/phase_handlers/attack_sequence.py`). `invul_save_override`, `melee_strength_bonus` et `melee_attacks_bonus` (primitives B et F) rendent **0 hit** dans tout le dépôt : ils sont à **créer**, comme le prévoit le texte ci-dessous. Ne pas partir du principe qu'il suffit de les câbler.
>
> **Série « chantiers capacités » (ex-`2_Various/`, dossier dissous le 2026-08-10).** Les chantiers **01 à 05 sont LIVRÉS** et rangés dans `Implémenté/` ; seul le **06** reste ouvert, dans `A_faire/`. Les renvois « chantier 0X » du texte désignent ces fichiers, qui ont gardé leur nom.
> Ordre du travail : [`../ROADMAP.md`](../ROADMAP.md) — ce fichier n'est pas une roadmap.

> **Deux cycles de vie.** **CONCEPTION** fait foi après livraison. **EXÉCUTION** est un
> prompt consommé une fois — organisé en **6 passes, une par primitive**, exécutables
> séparément sans replanifier.

---

# CONCEPTION — à maintenir

## Sources

- `Documentation/40k_rules/Armageddon/Datasheets - Orks.pdf` (9 pages)
- `Documentation/40k_rules/Armageddon/Datasheets - Space Marines.pdf` (8 pages)
- `Documentation/40k_rules/24 Core abilities.pdf` — Deadly Demise 24.08

Les PDF font foi. Toute divergence avec ce document se tranche en leur faveur.

## Note sur le décompte

Les premières analyses annonçaient « 17 capacités ». Le chiffre a monté à **25** parce que
les chantiers 03 et 04 ont débloqué ce qui était classé non codable : Waaagh! et ses effets
dérivés, Deep Strike, Da Jump. Rien n'a été ajouté au périmètre — des capacités en sont
sorties de la catégorie « impossible ».

## Vocabulaire

Une **primitive** est un mécanisme moteur irréductible, absent aujourd'hui, sur lequel
plusieurs capacités s'appuient. Ce ne sont pas les capacités elles-mêmes. Six primitives
couvrent les 25 capacités.

---

## Primitive A — `roll_modifiers`

**Modificateurs (+1/−1) et relances complètes sur les jets de touche et de blessure.**

### Point d'intégration

Les seuils sont calculés par l'appelant, puis passés à `resolve_attacks`
(`engine/phase_handlers/attack_sequence.py:248`). Trois sites, **jumeaux** :

| Site | Contexte |
|---|---|
| `engine/phase_handlers/shared_utils.py:7566` | tir |
| `engine/phase_handlers/shared_utils.py:8966` | tir (second chemin) |
| `engine/phase_handlers/fight_handlers.py:5232` | mêlée |

Le seuil devient `clamp(base − bonus + malus, 2, 6)`. Le **1 non modifié reste un échec**
(05.01) : le clamp ne doit jamais transformer un 1 en réussite.

`RerollProfile` (`attack_sequence.py:53`) porte `hit_1`, `wound_1`, `wound_any_fail`,
`save_1`. Le chantier 03 y ajoute `hit_any_fail` ; s'il n'est pas encore livré, cette
primitive le crée.

### Capacités couvertes

| Capacité | Unité | Nom générique |
|---|---|---|
| Might Is Right | Warboss | `hit_roll_bonus_fight` |
| Litany of Hate | Chaplain with Jump Pack | `wound_roll_bonus_fight` |
| Somethin' to Prove | Bigboss | `charge_roll_bonus` |
| (malus de suppression) | posé par Indiscriminate Detonations | `hit_roll_malus_suppressed` |

`charge_roll_bonus` ne passe pas par l'attaque : il modifie le jet de charge, à côté de
`reroll_charge` qui existe déjà.

---

## Primitive B — `granted_weapon_effects`

**Règles d'arme et caractéristiques (A / S / D) accordées par une règle d'unité.**

### Point d'intégration

`build_weapon_attack_profile(weapon, target_unit)` — `attack_sequence.py:110` — est le point
unique où les règles d'arme sont résolues pour un couple (arme, cible). Il gagne le contexte
attaquant. Les lecteurs de A / S / D suivent le même chemin.

Les 22 règles d'arme du PDF 24 sont **déjà implémentées** (`config/weapon_rules.json`) :
`SUSTAINED_HITS`, `LETHAL_HITS`, `BLAST`, `DEVASTATING_WOUNDS`, `HAZARDOUS`, etc. Cette
primitive ne les réimplémente pas — elle permet à une règle d'**unité** de les accorder
conditionnellement à une arme.

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

**Attention Dakkablitz** : la datasheet écrit `blitzcannon` dans la composition et
`Blitzkannon` dans le profil d'arme. Même arme, deux orthographes dans le PDF. Ne pas créer
deux entrées.

---

## Primitive C — `feel_no_pain`

**Jet d'ignorance de blessure, après allocation, avant décrément des PV.**

### Point d'intégration

**Le mécanisme moteur EST livré** — mesuré le 2026-08-10, ce paragraphe annonçait le contraire
(« 0 hit ») et c'était faux. `_get_feel_no_pain_threshold` / `_roll_feel_no_pain`
(`engine/phase_handlers/shared_utils.py:2350`) sont lus par trois sites : tir, mêlée et
blessures mortelles. La règle générique `feel_no_pain` existe au registre avec son `obs_id` et
son paramètre `threshold` (`config/unit_rules.json`).

Ce qui manque est le CÂBLAGE : `grep feel_no_pain frontend/src/roster` → **0 hit**, aucune
datasheet ne la porte. La passe se réduit donc à déclarer la règle sur le Painboy, plus les
deux variantes conditionnelles (Psychic Hood, Unbreakable Resolve) qui, elles, demandent un
contexte que le seuil actuel ne porte pas.

L'ordre compte : le FNP s'applique **après** que la sauvegarde a échoué et que les dégâts sont
alloués à une figurine, blessure par blessure. Il ne remplace pas la sauvegarde.

### Capacités couvertes

| Capacité | Unité | Nom générique | Condition |
|---|---|---|---|
| Dok's Toolz | Painboy | `feel_no_pain` (seuil 5) | aucune |
| Psychic Hood | Librarian | `feel_no_pain_vs_psychic` (seuil 4) | l'attaque provient d'une arme ou capacité `PSYCHIC` |
| Unbreakable Resolve | Ancient | `feel_no_pain_near_objective` (seuil 4) | à portée d'un objectif **ou** à 6" du centre du champ de bataille |

Le mot-clé `PSYCHIC` existe déjà sur les armes (`config/weapon_rules.json`). Les **capacités**
psychiques (Da Jump) doivent aussi être marquées, sinon Psychic Hood sera incomplète.

Les 6" d'Unbreakable Resolve se convertissent via `inches_to_subhex` — jamais de seuil en
pouces absolus.

---

## Primitive D — `mortal_wounds`

**Blessures mortelles hors `[DEVASTATING WOUNDS]`, avec plusieurs déclencheurs.**

### Point d'intégration

Deux chemins existent déjà et doivent être **unifiés**, pas dupliqués :

- `[DEVASTATING WOUNDS]` — `attack_sequence.py`, résolu à l'allocation par l'appelant
- `charge_impact` — `engine/phase_handlers/charge_handlers.py:4401`

Cette primitive extrait un helper commun « infliger N blessures mortelles à une unité »,
appelable depuis n'importe quel déclencheur.

### Capacités couvertes

| Capacité | Unité | Nom générique | Déclencheur |
|---|---|---|---|
| Hold Still and Say Aargh | Painboy | `mortal_wounds_on_critical_wound` | blessure critique de l'`'urty syringe` contre une unité non-`VEHICLE` → D6 MW |
| Exhortation of Rage | Chaplain JP | `mortal_wounds_on_fight_activation` | sélection pour combattre : D6 → 4-5 : D3 MW ; 6 : 3 MW à une unité engagée |
| Deadly Demise D3 | Weirdboy | `deadly_demise` | figurine détruite : D6 → sur 6, D3 MW à chaque unité dans 6" |
| Da Jump (échec) | Weirdboy | — | D6 = 1 → D6 MW à l'unité elle-même (voir chantier 04) |

**Deadly Demise 24.08** : le jet se fait **par figurine détruite**, après les débarquements
d'urgence, et le X est tiré **séparément pour chaque unité** dans les 6" si c'est un nombre
aléatoire. Trois détails qu'une implémentation rapide rate.

**Exhortation of Rage** : *« you can select one enemy unit it is engaged with »* — c'est un
choix de joueur, donc une décision d'agent, pas une heuristique interne.

---

## Primitive E — `objective_effects`

**Sécurisation d'objectif et modification d'OC.**

### Point d'intégration

`engine/game_state.py:2564` `_sum_objective_control_oc` (règle 14.02) et la logique de
`control_method` à `:2654` (règle 14.03). Le mécanisme « secured » **existe déjà** comme
propriété d'objectif — il s'agit de permettre à une capacité d'unité de le déclencher.

### Capacités couvertes

| Capacité | Unité | Nom générique |
|---|---|---|
| Get da Good Bitz | Boyz | `secure_objective_on_control` |
| Objective Secured | Intercessor | `secure_objective_on_control` |
| Relic Banner | Ancient | `oc_bonus` (+1 OC) |

**Les deux premières sont des jumeaux exacts** — textes identiques mot pour mot dans les deux
PDF. Une seule règle générique, déclarée deux fois avec des `displayName` différents. Les
coder séparément serait une duplication pure.

Déclenchement : fin de ta phase de commandement, si l'unité contrôle l'objectif.

---

## Primitive F — `unit_state_effects`

**Écritures dans l'état d'une unité : override de caractéristique, statut temporaire,
compteur « une fois par bataille », restitution de figurines.**

C'est la primitive résiduelle. Elle est large mais cohérente : tout ce qui modifie l'état
d'une unité en dehors de la séquence d'attaque.

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

`BannerNob.ts` porte `INVUL_SAVE = 5` **sur la figurine**. La datasheet dit *« This unit has a
5+ InSv »* — donc **toute l'escouade** à laquelle il est rattaché. Aujourd'hui, attacher un
Bannernob à des Boyz ne leur donne rien.

Même défaut pour Mental Fortress (Librarian, 4+ InSv, *« This unit »*).

Ce n'est pas une caractéristique statique : c'est un effet conféré, qui disparaît si le
porteur meurt (règle 19.04 sur l'union des règles en vigueur).

### `move_after_shooting` : extension, pas création

La règle **existe** (`UNIT_RULE_EFFECT_IDS`, `engine/phase_handlers/shooting_handlers.py:5178`
`_build_move_after_shooting_destinations`). Deux manques :

1. La distance est un **entier fixe** en paramètre ; Purgation Run demande **D6"**.
2. `LandSpeederOnslaughtGatlingCannon.ts` ne déclare **aucune** `UNIT_RULES` — la capacité
   n'est pas câblée du tout.

### Suppression

*« While a unit is suppressed, it has -1 to hit rolls. »* Durée : jusqu'au début de ta
prochaine phase de commandement. Le statut vit dans `status_ids` (chantier 01) ; le malus est
appliqué par la primitive A.

---

## Capacités traitées ailleurs

| Capacité | Unité | Chantier |
|---|---|---|
| Waaagh! (faction) | toutes les orkes | 03 |
| Oath of Moment (faction) | toutes les SM | 03 |
| Thievin' Scavengers | Gretchin | 02 (CP) |
| Rites of Battle | Captain Relic Shield | 02 — **non livrable** sans stratagèmes |
| CORE: Deep Strike | Chaplain JP, Vanguard JP, Land Speeder | 04 |
| Da Jump | Weirdboy | 04 + primitive D |

## Déjà correct, à ne pas retoucher

- **Relic Shield** (Captain, +1 W) — inclus dans le profil, la datasheet le dit
  explicitement (*« included in profile »*).
- Les 22 règles d'arme du PDF 24 — implémentées.

---

# EXÉCUTION — prompt

## Préalable

Chantiers 01, 03, 04, 05 livrés. Le chantier 02 est souhaitable mais pas bloquant (aucune
capacité de ce chantier ne dépend des CP).

Ce chantier **ne change ni `obs_size` ni `TOTAL_ACTION_SIZE`**. Toute capacité qui semble
l'exiger signale une erreur du chantier 01 : remonter, ne pas contourner.

## Découpage en passes

Une passe par primitive, dans cet ordre. Chaque passe est autonome et se termine par ses
propres tests.

| Passe | Primitive | Capacités |
|---|---|---|
| 1 | A `roll_modifiers` | 4 |
| 2 | B `granted_weapon_effects` | 8 |
| 3 | C `feel_no_pain` | 3 |
| 4 | D `mortal_wounds` | 4 |
| 5 | E `objective_effects` | 3 |
| 6 | F `unit_state_effects` | 7 |

Les passes 1 et 2 débloquent à elles seules 12 capacités et n'exigent aucune structure d'état
nouvelle — les faire d'abord.

### Ce que le chantier 05 laisse en entrée (2026-08-10)

Le placeholder `reroll_charge` / « Unstoppable Valour » est purgé de **tous** les rosters, sans
exception ni dette. Les tests de la règle 19.04 s'ancraient dessus faute d'autre porteur ; ils
reposent désormais sur un couple de vraies datasheets — `ChaplainJumpPack` (`deep_strike`) mené
sur `AssaultIntercessorJumpPack` (`charge_impact`), discriminant dans les deux sens et légal au
titre de 19.01.

Conséquence pour la passe 1 : rien à solder avant de commencer. Le témoin de règle de LEADER
observable qui manquait est arrivé sans attendre **Litany of Hate** : `deep_strike` a reçu son
`obs_id` (**16**) le 2026-08-10, et
`test_squad_obs_unit_rules.py::test_attached_squad_rule_is_observed_then_extinguished_with_its_source`
verrouille désormais les deux sources de l'union 19.04 au lieu de la seule BODYGUARD. Quand
Litany of Hate (`wound_roll_bonus_fight`) sera livrée sur le Chaplain, elle n'aura donc rien à
rattraper de ce côté.

## Périmètre

**Autorisé :**
- `engine/phase_handlers/` — `attack_sequence.py`, `shared_utils.py`, `fight_handlers.py`,
  `shooting_handlers.py`, `charge_handlers.py`, `command_handlers.py`
- `engine/game_state.py` — contrôle d'objectif, overrides
- `config/unit_rules.json` — déclaration des règles génériques + `obs_id`
- `frontend/src/roster/{ork,spaceMarine}/units/*.ts` — `UNIT_RULES` des unités concernées
- Tests ciblés, `Documentation/Unit_rules.md`

**Interdit :** toucher `obs_size`, l'action space, ou une unité hors rosters Armageddon.

## Vérification exigée — pour chaque passe

- **Verrou par capacité** : un test qui **construit** la situation, l'observe, puis remet le
  défaut et vérifie que le test devient **rouge**. Sans cette preuve, considérer le test comme
  absent. (Inutile sur du parsing trivial.)
- **Jumeau** : après chaque correction, `grep` du motif et vérification explicite de son
  existence ailleurs — tir/mêlée, IA/PvP, moteur/replay/analyzer, front/back. Rapporter le
  résultat **même vide**.
- **Chemin de production** : vérifier que le code écrit est réellement **atteint** par le
  vrai chemin. Du code testé mais jamais appelé ne corrige rien — motif déjà rencontré ici.
- **Vert vacant** : vérifier que l'échantillon produit des données. Un contrôle qui ne regarde
  rien affiche « tout va bien ».
- **Analyzer** : chaque capacité doit être vérifiable par `ai/analyzer.py` sur un replay. Une
  capacité invisible à l'analyzer n'est pas vérifiable en conditions réelles.

## Pièges spécifiques relevés à la lecture des PDF

- **Get da Good Bitz / Objective Secured** : textes identiques. Une règle, deux déclarations.
- **Deadly Demise** : par figurine, après débarquements, X tiré séparément par unité.
- **Hold Still and Say Aargh** : uniquement l'`'urty syringe`, uniquement sur une **blessure
  critique**, uniquement contre du non-`VEHICLE`.
- **Waaagh! Energy** : « for every 5 models » compte les figurines de l'**unité**, pas les
  Weirdboyz. `[HAZARDOUS]` à 10+, pas à 11+.
- **Overlapping Detonations** et **Hail of Bolts** : la cible est **désignée** au moment où
  l'unité est sélectionnée pour tirer, avant de choisir les cibles des armes. Deux étapes
  distinctes, ne pas les fusionner.
- **Purgation Run** : D6", pas 6" fixes. Et le Land Speeder n'a aucune `UNIT_RULES` à câbler.
- **InSv conférés** (Bannernob, Librarian) : effet sur l'**unité**, pas caractéristique de la
  figurine.
- **Finest Hour** : *« when this unit is selected to fight »*, une fois par bataille, effet
  jusqu'à la **fin de la phase** — pas de l'activation.
- Toute distance en pouces se convertit via `inches_to_subhex`.
