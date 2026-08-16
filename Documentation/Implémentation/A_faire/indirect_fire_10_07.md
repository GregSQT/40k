# [INDIRECT FIRE] 24.19 — tir indirect 10.07

**Ouvert** : 2026-08-16. **Option retenue** : A1 (tout d'un bloc, choix exposé à l'agent),
validée par l'utilisateur, ré-entraînement complet accepté.
**Dans le ROADMAP** : §0 « En cours ».

---

## 1. Ce que disent les PDF, verbatim

`24 Core abilities` §24.19 ne décrit aucun effet : il **délègue** entièrement.

> Units containing one or more models with an [INDIRECT FIRE] weapon can shoot using indirect
> shooting (10.07).

`10 Shooting phase` §10.02, étape 2 de la phase — **c'est la ligne qui commande tout le
chantier** :

> **Select Shooting Type**: Select **one** shooting type that unit is eligible to make, and
> resolve it with that unit. This can be one listed below, or one presented elsewhere:
> Normal shooting / Assault shooting / Close-quarters shooting / **Indirect shooting**

`10 Shooting phase` §10.07 :

> **ELIGIBLE IF**: All of the following apply to your unit:
> ▪ Unengaged and did not make an advance move this turn.
> ▪ Has one or more [INDIRECT FIRE] weapons.
>
> **EFFECT**: Your unit shoots as described in Making Attacks (04).
>
> **WHILE SHOOTING**:
> ▪ [INDIRECT FIRE] weapons in your unit can target units that are not visible to the
>   attacking model.
> ▪ Each time an [INDIRECT FIRE] weapon makes an attack:
>   ▫ The target has the benefit of cover against that attack (13.08).
>   ▫ You cannot re-roll hit rolls.
>   ▫ An unmodified hit roll of 1-5 fails, unless your unit remained stationary this turn and
>     the target is visible to one or more friendly units, in which case an unmodified hit roll
>     of 1-3 fails instead.
>
> **AFTER SHOOTING**: Until the end of the phase, your unit is not eligible to start an action.

Encadré de la même page, qui lève l'ambiguïté sur les AUTRES armes de l'unité :

> When you select indirect shooting for a unit, its [INDIRECT FIRE] weapons can launch punishing
> barrages on targets that are not visible, but don't forget that its **other weapons can still
> target other visible targets**.

### Ce que ces citations excluent

- **Ce n'est pas un « −1 à la touche »**, comme le supposait la note de chantier du 2026-08-15.
- **Ce n'est pas non plus un « seuil substitué »**, comme le disait la première version de cette
  spec. C'est un **plancher d'échec sur le dé NON MODIFIÉ**, qui se compose avec la table 05.01.
  Celle-ci teste, dans l'ordre : `unmodified 1 → FAILS`, `unmodified 6 → CRITICAL HIT`,
  `≥ BS → HIT`, sinon `FAILS`. 10.07 remplace la première ligne par `unmodified 1-5 → FAILS`
  (ou `1-3` avec spotter). D'où le seuil EFFECTIF :

      seuil_effectif = max(seuil_de_touche_effectif, plancher)      plancher ∈ {6, 4}

  Deux conséquences que la formulation « seuil substitué » masquait :
  * **sans spotter, c'est un 6+ DUR, quel que soit le BS** — et même quels que soient les
    modificateurs, puisque `unmodified 6 → CRITICAL HIT` reste la deuxième ligne de 05.01. Un
    `BS 2+` sous [HEAVY] touche sur 6+. C'est exact et c'est fixe, littéralement dans la règle.
  * **avec spotter, ce n'est PAS un 4+ plat** : `1-3` échouent, puis la ligne `≥ BS` s'applique
    normalement. Un `BS 5+` touche donc toujours sur 5+, pas sur 4+. C'est `max(BS, 4)`.
- **L'unité qui tire compte comme son propre spotter.** 01.02 : « Friendly units and models are
  those in your army », sans exclusion de l'unité active. Le cas est de toute façon marginal —
  contre une cible visible, le tir normal domine (cf. §6) — mais il doit être tranché au code et
  non laissé à l'ordre des tests.
- Le couvert est **octroyé**, pas calculé : la cible l'a, quelle que soit la géométrie. C'est
  l'exact opposé de [IGNORES COVER] 24.18, et les deux peuvent coexister sur une même arme.
- L'interdiction de relance porte sur les **jets de touche** seulement. Les relances de blessure
  ([TWIN-LINKED] 24.38, capacités d'unité) ne sont pas touchées.

---

## 2. Le vrai coût : la dérivation devient une décision

`engine/phase_handlers/shared_utils.resolve_squad_shooting_type` rend **un seul** type, et son
docstring justifie explicitement ce choix :

> Ordre des tests = ordre des conditions du PDF ; un seul type peut s'appliquer (les conditions
> « engaged / unengaged » et « advance / pas d advance » sont exclusives).

L'invariant est vrai pour les trois types implémentés. **10.07 le casse** : sa condition
d'éligibilité (*unengaged, pas d'advance*) est exactement celle de 10.04 normal. Une unité
unengaged, qui n'a pas avancé et qui porte une arme [INDIRECT FIRE] est éligible aux DEUX, et
§10.02 dit que c'est le joueur qui tranche.

Conséquences en cascade, et c'est ce qui fait le périmètre :

| Ce qui change | Pourquoi |
|---|---|
| `resolve_squad_shooting_type` → rend un **ensemble** de types éligibles | un seul type ne peut plus représenter l'état |
| Un point de **décision** (agent et PvP) | §10.02 confie le choix au joueur |
| **Espace d'action** de l'agent | le choix doit être une action masquable |
| **Observation** | l'agent ne peut choisir que ce qu'il perçoit : éligibilité indirecte, immobilité, présence d'un spotter |
| **Modèles entraînés** | invalidés par le changement d'espace d'action — accepté par l'utilisateur |

⚠️ L'`obs_id` de la règle, lui, est **gratuit** : le vocabulaire est pré-dimensionné
(`OBS_ID_VOCAB_SIZE = 128`, `engine/observation_entities.py`), donc l'ajouter ne touche ni
`obs_size` ni les poids. Le retrain vient du choix, pas de l'observation.

---

## 3. Périmètre, par pièce

Chaque pièce est nommée avec son critère d'entrée. Les tests et docs ne comptent pas dans la
limite T2 des ~5 fichiers.

1. ✅ **FAIT le 2026-08-16.** **Registre** — `config/weapon_rules.json` : donner son `obs_id` à `INDIRECT_FIRE`, et
   `engine/observation_weapon_profiles.WEAPON_RULE_BITS` l'accueillir. Retirer
   `tests/unit/engine/test_squad_obs_weapon_profiles.py::test_indirect_fire_is_deliberately_absent`,
   dont l'objet même disparaît, et le remplacer par son inverse.
2. ✅ **FAIT le 2026-08-16**, mais autrement que prévu ici : plutôt que de changer le type de
   retour de `resolve_squad_shooting_type` — ce qui aurait forcé ses QUATRE appelants à choisir,
   dont le masque gym —, l'ensemble vit dans une fonction NEUVE,
   `eligible_squad_shooting_types`, et la dérivation garde son rôle : elle rend le type
   **retenu**, c'est-à-dire le défaut tant que personne ne choisit. Zéro appelant touché, zéro
   changement de comportement. **Éligibilité** — l'ancienne formulation :
   `shared_utils.resolve_squad_shooting_type` rend un ensemble ;
   `SHOOTING_TYPE_INDIRECT` ; `shooting_type_allows_weapon` rend `True` pour toutes les armes
   sous le type indirect (cf. l'encadré : les autres armes tirent normalement).
3. **Ciblage** — le pool de cibles des armes [INDIRECT FIRE] cesse d'exiger la ligne de vue.
   ⚠️ Ne PAS toucher `compute_unit_los` : c'est la source unique de l'obs, du reward et du
   déploiement. Le contournement se fait au niveau du **gate de ciblage**, pas du calcul.
4. ✅ **FAIT le 2026-08-16** (sauf le volet journal, cf. pièce 6). **Résolution** — plancher d'échec `max(seuil, 6)` ou `max(seuil, 4)` (cf. §1), couvert
   octroyé, relances de touche interdites. Le prédicat spotter est neuf mais **PAS coûteux** :
   `compute_unit_los` est mémoïsé par PAIRE `(tireur, cible)` dans un cache persistant, invalidé
   de façon ciblée par `_touch_unit_los` à chaque mouvement ou perte de figurine. Les paires
   `(unité amie, cible)` sont déjà chaudes — c'est le balayage d'éligibilité au tir qui les
   remplit à chaque step. Le prédicat coûte donc une dizaine de lectures de dict, pas un calcul
   de LoS. ⚠️ La v1 de cette spec annonçait un « risque de performance » : mesure faite sur le
   code, il n'y en a pas, et l'inventer aurait fait sur-concevoir un cache de plus.
5. **Décision** — masque d'action + observation + application côté agent ; côté PvP, le choix
   du type de tir à l'activation.
6. **Journal** — ⚠️ **la v1 de cette spec disait « déjà prévu » : c'était faux, et c'était le
   mode d'échec que toute la session du 12-16 août a servi à fermer.** `[SHOOT_TYPE:indirect]`
   sortira bien tout seul (le jeu de valeurs est lu dans le moteur), mais il ne nomme que le
   TYPE. Les deux effets qui se vérifient n'auraient aucune représentation :
   * le **plancher** — `Hit 6(3+->6+)` est exact, mais rien ne dirait si le 6 vient de la règle
     ou de la datasheet, ni si le cas 4+ était mérité. D'où `[INDIRECT FIRE:<plancher>+]`, valeur
     DÉCLARÉE par la règle : le lecteur recoupe `eff == max(base_après_couvert, plancher)` ;
   * le **couvert octroyé** — il agit sur le même seuil que le plancher, et `hit_rule_modifier`
     ne porte qu'une cause. Le token `[COVER]` existe déjà : il doit être posé ici aussi, sinon
     une des deux causes du seuil affiché reste muette.
   Vérifier enfin que `replayParser.ts` tolère les deux (tags de ligne pour `[SHOOT_TYPE:]`,
   segment `Hit` pour les deux autres → jeu FERMÉ `NON_ABILITY_ROLL_TOKENS` à étendre).
7. **Analyzer** — nouveau contrôle possible : un tir indirect doit porter le couvert et un seuil
   conforme. ⚠️ **À traiter comme un lot séparé**, avec sa mesure de taux de fausse alarme : c'est
   le mode d'échec historique de ce fichier (317, puis 334, puis 31 faux positifs livrés verts).

8. **Mesure** — DÉCISION UTILISATEUR du 2026-08-16 : la règle est livrée pour le **PvP et la
   conformité aux règles**, PAS pour le win-rate. Aucun roster d'ArmageddonAgent ne porte d'arme
   [INDIRECT FIRE] (mesuré : 0 occurrence de `Biovore` / `HiveGuardImpalerCannon` dans les quatre
   rosters d'entraînement, qui sont Space Marines et Orks) — l'agent entraîné ne rencontrera donc
   jamais la règle, et un compteur d'usage à zéro sur ces runs-là sera CORRECT. Ne pas en faire un
   critère de succès, ne pas l'attendre dans un rapport d'analyzer.

## 4. Ordre d'exécution imposé

La résolution AVANT la décision : un type qu'on peut choisir mais que le moteur résout mal
produirait des parties fausses, et l'agent apprendrait sur elles. Donc 1 → 2 → 3 → 4, chacun
verrouillé par ses tests, PUIS 5, PUIS le retrain, PUIS 7 en lot séparé.

## 5. Pièges nommés d'avance

- **Le journal : `base+->eff+` convient, contrairement à ce que disait la v1 de cette spec.**
  Puisque `eff = max(base, plancher)`, l'affichage `Hit 4(3+->6+)` est exact et strictement
  analogue à [COVER] — qui dégrade lui aussi le seuil. La v1 refusait cette forme en croyant à
  un « modificateur de −4 » : il n'y en a pas, il y a une composition par `max`.
  ⚠️ En revanche **deux causes agissent sur le même nombre** sous tir indirect : le couvert
  octroyé (+1 au seuil dans ce moteur) PUIS le plancher. `hit_rule_modifier` ne porte qu'une
  cause. Décision retenue : garder `base+->eff+` pour le résultat composé, et poser en plus
  `[INDIRECT FIRE:<plancher>+]` — le plancher est une valeur DÉCLARÉE par la règle (6 ou 4),
  donc exactement la grammaire `[REGLE:X]` du dépôt, et un lecteur peut alors recouper
  `eff == max(base_après_couvert, plancher)` sans re-dériver quoi que ce soit.
- **Le couvert octroyé traverse `_cover_worsened_bs`**, qui court-circuite sur [IGNORES COVER].
  Une arme portant les deux règles doit être tranchée explicitement, pas par l'ordre des `if`.
- **`resolve_squad_shooting_type` commence par rendre `None` si l'escouade a déjà tiré.** Tout
  lecteur différé (l'émetteur de log l'est) lira `None` : le type doit être CAPTURÉ à
  l'activation, jamais relu après coup — c'est déjà le cas pour `shooting_type`, ne pas le
  défaire.
- **Ne pas confondre « unité immobile » et « n'a pas avancé ».** Le seuil de 4+ exige *remained
  stationary*, condition plus forte que l'absence d'advance qui conditionne l'éligibilité.
