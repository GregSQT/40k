# Chantier 03 — Capacités de faction : Waaagh! et Oath of Moment
> ✅ **LIVRÉ** (vérifié code le 2026-08-10 : `waaagh`, `oath_of_moment`, `hit_any_fail` sur les trois sites jumeaux). La **CONCEPTION** reste la référence vivante. Dette bornée : « Détachement Codex » reste un champ de config déclaré, non déduit.
>
> **Série « chantiers capacités » (ex-`2_Various/`, dossier dissous le 2026-08-10).** Les chantiers **01 à 05 sont LIVRÉS** et rangés dans `Implémenté/` ; seul le **06** reste ouvert, dans `A_faire/`. Les renvois « chantier 0X » du texte désignent ces fichiers, qui ont gardé leur nom.
> Ordre du travail : [`../ROADMAP.md`](../ROADMAP.md) — ce fichier n'est pas une roadmap.

> **Deux cycles de vie.** **CONCEPTION** fait foi après livraison. **EXÉCUTION** est un
> prompt consommé une fois.

---

# CONCEPTION — à maintenir

## Sources

- `Documentation/40k_rules/Armageddon/Waaagh!.txt`
- `Documentation/40k_rules/Armageddon/OathOfMoment.txt`

Les deux sont la source de vérité. Toute divergence entre ce document et ces fichiers se
tranche en faveur des fichiers.

## Pourquoi ces capacités ne vont PAS dans `ability_ids`

Une capacité de faction s'applique **uniformément à toutes les unités de l'armée qui la
portent**. L'inscrire dans l'ensemble par unité, c'est répéter les mêmes ids sur 28 entités,
faire déborder les slots, et n'apporter aucune information : le réseau reconstitue l'effet à
partir de « cette unité appartient à cette faction » + « la capacité est active », deux
informations **globales**.

Elles vont donc dans `global_bin`. Voir chantier 01, section « Ce qui ne va PAS dans
l'ensemble par unité ».

---

## Waaagh! (ORKS)

> If your Army Faction is ORKS, once per battle, at the start of your Command phase, you can
> call a Waaagh!. If you do, until the start of your next Command phase, the Waaagh! is active
> for your army and:
> - Units from your army with this ability are eligible to declare a charge in a turn in which
>   they Advanced.
> - Add 1 to the Strength and Attacks characteristics of melee weapons equipped by models from
>   your army with this ability.
> - Models from your army with this ability have a 5+ invulnerable save.

### Décomposition

| Clause | Traitement | Primitive |
|---|---|---|
| Décision : appeler, **1×/partie**, début de phase de commandement | `pending_agent_decision`, 2 candidats (appeler / passer) → `CHOICE_0`/`CHOICE_1` | — |
| Charge après Advance | `charge_after_advance` **existe déjà** (`UNIT_RULE_EFFECT_IDS`) — accordé, rien à coder | B |
| +1 S et +1 A aux armes de mêlée | `melee_strength_bonus`, `melee_attacks_bonus` | B |
| Sauvegarde invulnérable 5+ | `invul_save_override` (seuil paramétré) | F |

### L'effet réel, mesuré

`INVUL_SAVE` est aujourd'hui une caractéristique **statique** par figurine :

| Unité | `INVUL_SAVE` | Waaagh! actif |
|---|---|---|
| Boyz | 7 (aucune) | **5** |
| Gretchin | 7 (aucune) | **5** |
| WarTrakk | 6 | **5** |
| Warboss, BannerNob, BigMekDakkarig | 5 | 5 (inchangé) |

Pendant un round complet, l'armée orke entière gagne une invulnérable 5+, +1 S, +1 A en mêlée
et la charge après Advance. C'est de très loin la décision la plus lourde de la liste orke, et
c'est une décision de **tempo** — à quel tour l'appeler. C'est exactement ce qu'un agent RL
doit apprendre ; elle vaut probablement plus, pour l'entraînement, que plusieurs des petites
capacités d'unité du chantier 06.

### Observation

`global_bin`, 4 bits : mon Waaagh! disponible, mon Waaagh! actif, celui de l'adversaire
disponible, celui de l'adversaire actif.

Les quatre, pas deux : la durée court *« until the start of your next Command phase »*, donc
elle enjambe le tour adverse. Le Waaagh! ennemi actif pendant mon tour change ce que je dois
faire.

---

## Oath of Moment (ADEPTUS ASTARTES)

> If your Army Faction is ADEPTUS ASTARTES, at the start of your Command phase, select one unit
> from your opponent's army. Until the start of your next Command phase, that enemy unit is
> your Oath of Moment target.
> Each time a model with this ability makes an attack that targets your Oath of Moment target:
> ▪ You can re-roll the Hit roll.
> ▪ If you are using a Codex: Space Marines Detachment and your army does not include one or
>   more units with the BLOOD ANGELS, DARK ANGELS, DEATHWATCH or SPACE WOLVES keywords, or one
>   or more units from those factions' Munitorum Field Manual sections, add 1 to the Wound
>   roll as well.

Noter : **chaque tour**, pas une fois par partie. Et **non optionnel** — « select one unit ».

### Décomposition

| Clause | Traitement | Primitive |
|---|---|---|
| Désigner une unité ennemie, chaque phase de commandement | `OATH_SLOTS` (dimension d'action + pointeur) | — |
| Relance du jet de touche contre la cible | **`hit_any_fail`, à créer** | A |
| +1 au jet de blessure contre la cible | `wound_roll_bonus_vs_oath_target` | A |

### `hit_any_fail` n'existe pas

`RerollProfile` (`engine/phase_handlers/attack_sequence.py:53`) porte `hit_1`, `wound_1`,
`wound_any_fail`, `save_1`. Il n'y a **aucune** relance complète du jet de touche
(`grep -rn "hit_any_fail" engine/` → 0 hit). C'est une création, pas une réutilisation.

Le motif à suivre est celui de `wound_any_fail`, déjà en place à
`attack_sequence.py:332` : relance des **échecs** uniquement, un seul dé de relance,
priorité explicite entre les causes, et `hitRerollCause` au record — sans cette trace, le log
dit que la relance était *possible*, jamais qu'elle a *eu lieu*.

### Désignation : dimension d'action, pas `CHOICE_k`

`engine/macro_intents.py:65` :

> ⚠️ Elles ne concernent QUE les décisions dont les candidats ne sont PAS des entités déjà
> observées : une décision « quelle escouade ennemie » se paramètre en dimension d'action +
> pointeur, pas en `CHOICE_k`.

Oath désigne littéralement une escouade ennemie. Les `OATH_SLOTS` (20, dérivés de
`SHOOT_SLOT_COUNT`, indexant le même `get_enemy_slot_mapping`) sont **déclarés par le
chantier 01**. Ce chantier ne fait que les consommer et lever leur masque.

`MAX_DECISION_OPTIONS` reste à 6.

### La clause conditionnelle du +1 Wound

Elle a deux moitiés de faisabilité opposée :

- *« votre armée ne contient pas d'unité BLOOD ANGELS / DARK ANGELS / DEATHWATCH /
  SPACE WOLVES »* → **implémentable immédiatement et pour de vrai**. `UNIT_KEYWORDS` existe ;
  c'est un balayage de l'armée. Aucune raison de la différer.
- *« vous utilisez un Détachement Codex: Space Marines »* → aucun système de détachement dans
  le moteur.

**Traitement retenu** : coder le balayage de mots-clés réellement, et exposer la moitié
détachement comme un **champ obligatoire de la config d'armée** (`uses_codex_detachment`).
Absent → erreur explicite, jamais de valeur par défaut.

Ce n'est pas un contournement : la valeur est une donnée métier légitime que l'utilisateur
possède et que le moteur ne peut pas déduire. Le jour où les détachements existent, le champ
devient calculé au lieu d'être déclaré, et le reste du code ne bouge pas. Aujourd'hui il vaut
`true` — parce que c'est le cas réel des rosters Armageddon, pas pour masquer un manque.

### Observation

- `global_bin` : 2 bits — j'ai une cible Oath désignée / l'adversaire en a une.
- `status_ids` de l'entité ennemie visée : id `oath_target`.
- Symétriquement, mes unités désignées par l'Oath adverse portent le même statut.

Aucun de ces emplacements ne change `obs_size` : ils sont déclarés par le chantier 01.

---

# EXÉCUTION — prompt

## Préalable

Le chantier 01 doit être livré. Vérifier avant de commencer que `OATH_SLOTS` existe dans
`macro_intents.py` et que `status_ids` est bien construit. Si non, **arrêter** : ce chantier
n'a pas le droit de changer `obs_size` ni `TOTAL_ACTION_SIZE`.

## Périmètre

**Autorisé :**
- `engine/phase_handlers/command_handlers.py` — les deux décisions de début de phase
- `engine/phase_handlers/attack_sequence.py` — `hit_any_fail` dans `RerollProfile`
- `engine/phase_handlers/shared_utils.py`, `fight_handlers.py` — seuils et relances aux sites
  d'appel (`shared_utils.py:7566`, `:8966`, `fight_handlers.py:5232`)
- `engine/action_decoder.py` — décodage des `OATH_SLOTS`, masque
- `engine/game_state.py` — état Waaagh! / cible Oath
- `config/unit_statuses.json` — id `oath_target`
- `config/armies/*.json` — champ `uses_codex_detachment`
- Tests ciblés, `Documentation/Unit_rules.md`

## Étapes

1. **État.** `waaagh_called` (par joueur, 1×/partie), `waaagh_active_until`,
   `oath_target` (par joueur, id d'unité ennemie).
2. **Décision Waaagh!** en début de phase de commandement du joueur orke, si non encore
   appelé : `pending_agent_decision` à 2 candidats. Troisième condition, ajoutée le
   2026-08-11 : **le joueur doit avoir au moins une escouade sur la table**
   (`player_has_squads_on_board`). Le moteur ne termine pas l'épisode sur une armée anéantie,
   donc la phase de commandement du joueur vidé arrive ; la décision est une capacité d'ARMÉE,
   sans unité porteuse, et l'observation prend la première escouade du décideur comme repère —
   sans aucune, elle lève et l'épisode plante. Le « once per battle » n'est pas consommé : la
   décision se repose si le joueur revient sur la table.
3. **Décision Oath** en début de phase de commandement du joueur SM : masque exposant les
   `OATH_SLOTS` des escouades ennemies vivantes. **Non optionnel** — pas de candidat « aucune
   cible » ; si des ennemis existent, l'agent doit en désigner un.
4. **Effets Waaagh!** : `charge_after_advance` accordé, `melee_strength_bonus` /
   `melee_attacks_bonus` (primitive B), `invul_save_override` à 5 (primitive F).
   Ils s'appliquent aux unités **portant la capacité**, pas à toute l'armée indistinctement.
5. **Effets Oath** : `hit_any_fail` + `wound_roll_bonus` **uniquement** quand l'attaque cible
   l'unité désignée, **et** uniquement pour les modèles portant la capacité.
6. **Clause détachement** : balayage réel des 4 mots-clés + champ de config obligatoire.
7. **Expiration** : les deux durent *« until the start of your next Command phase »*. Le
   nettoyage se fait à l'ouverture de la phase de commandement suivante **du même joueur**,
   pas en fin de tour.

## Vérification exigée

- **Verrou Waaagh! invulnérable** : Boyz (`INVUL_SAVE=7`), Waaagh! actif, une blessure qui
  passe l'armure → jet de sauvegarde à 5+. Retirer l'override, le test devient **rouge**.
  Le prouver et le rapporter.
- **Verrou de durée** : le Waaagh! appelé au tour N est encore actif pendant le tour adverse
  et **expire** à l'ouverture de la phase de commandement N+1 du joueur orke. Un test qui
  n'observe que le tour du déclarant ne verrouille rien.
- **Verrou 1×/partie** : seconde tentative d'appel → l'action n'est pas dans le masque.
- **Verrou Oath ciblage** : la relance de touche s'applique contre l'unité désignée et
  **pas** contre une autre. Construire les deux cas.
- **Verrou clause détachement** : ajouter une unité `BLOOD ANGELS` à l'armée → le +1 Wound
  disparaît, la relance de touche reste. Champ de config absent → erreur.
- **Verrou d'invariant D1** : l'action `OATH_SLOT_i` désigne la même escouade que la ligne
  *i* du tenseur ennemi. Test dédié.
- Les tests **construisent** leur état ; ils ne l'espèrent pas d'une graine.

## Pièges

- **Jumeau tir/mêlée** : `hit_any_fail` doit être câblé aux **trois** sites de calcul de
  seuil, pas seulement au tir. C'est le motif d'échec n°1 du dépôt.
- Ne pas appliquer les effets Waaagh! aux unités orkes **sans** la capacité s'il en existe.
- Ne pas oublier `hitRerollCause` au record : sans elle, l'analyzer ne peut pas distinguer
  une relance possible d'une relance effectuée.
- L'Oath adverse doit être visible dans **mon** observation (mes unités portent le statut).
- Ne pas toucher `obs_size` ni `TOTAL_ACTION_SIZE`.
