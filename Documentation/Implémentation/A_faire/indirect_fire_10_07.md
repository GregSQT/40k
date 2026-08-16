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
  C'est un **seuil fixe qui remplace la CT** : 6+, ou 4+ sous condition. Un `BS 2+` tirant en
  indirect touche sur 6+, pas sur 3+.
- Le seuil de 4+ n'est PAS une propriété de l'arme ni de la cible seule : il exige **deux**
  faits simultanés — l'unité est restée immobile ce tour, ET la cible est visible d'au moins une
  unité amie (le « spotter »).
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

1. **Registre** — `config/weapon_rules.json` : donner son `obs_id` à `INDIRECT_FIRE`, et
   `engine/observation_weapon_profiles.WEAPON_RULE_BITS` l'accueillir. Retirer
   `tests/unit/engine/test_squad_obs_weapon_profiles.py::test_indirect_fire_is_deliberately_absent`,
   dont l'objet même disparaît, et le remplacer par son inverse.
2. **Éligibilité** — `shared_utils.resolve_squad_shooting_type` rend un ensemble ;
   `SHOOTING_TYPE_INDIRECT` ; `shooting_type_allows_weapon` rend `True` pour toutes les armes
   sous le type indirect (cf. l'encadré : les autres armes tirent normalement).
3. **Ciblage** — le pool de cibles des armes [INDIRECT FIRE] cesse d'exiger la ligne de vue.
   ⚠️ Ne PAS toucher `compute_unit_los` : c'est la source unique de l'obs, du reward et du
   déploiement. Le contournement se fait au niveau du **gate de ciblage**, pas du calcul.
4. **Résolution** — seuil 6+/4+ **substitué** à la CT, couvert octroyé, relances de touche
   interdites. Le prédicat spotter (« la cible est visible d'une unité amie ») est neuf.
5. **Décision** — masque d'action + observation + application côté agent ; côté PvP, le choix
   du type de tir à l'activation.
6. **Journal** — `[SHOOT_TYPE:indirect]` est **déjà prévu** : le token existe depuis la
   grammaire 4 et son jeu de valeurs est lu dans le moteur, donc l'ajout d'un type le fait
   apparaître sans toucher `ai/step_logger.py`. Vérifier que `_shoot_types()` le récupère bien,
   et que `replayParser.ts` le tolère (il vit dans les tags de ligne, pas sur un jet).
7. **Analyzer** — nouveau contrôle possible : un tir indirect doit porter le couvert et un seuil
   conforme. ⚠️ **À traiter comme un lot séparé**, avec sa mesure de taux de fausse alarme : c'est
   le mode d'échec historique de ce fichier (317, puis 334, puis 31 faux positifs livrés verts).

## 4. Ordre d'exécution imposé

La résolution AVANT la décision : un type qu'on peut choisir mais que le moteur résout mal
produirait des parties fausses, et l'agent apprendrait sur elles. Donc 1 → 2 → 3 → 4, chacun
verrouillé par ses tests, PUIS 5, PUIS le retrain, PUIS 7 en lot séparé.

## 5. Pièges nommés d'avance

- **Le seuil remplace la CT, il ne la modifie pas.** Le journal affiche déjà `base+->eff+` pour
  [HEAVY] et [COVER] ; ici il n'y a pas de « base » qui joue — écrire `2+->6+` laisserait croire
  à un modificateur de −4.
- **Le couvert octroyé traverse `_cover_worsened_bs`**, qui court-circuite sur [IGNORES COVER].
  Une arme portant les deux règles doit être tranchée explicitement, pas par l'ordre des `if`.
- **`resolve_squad_shooting_type` commence par rendre `None` si l'escouade a déjà tiré.** Tout
  lecteur différé (l'émetteur de log l'est) lira `None` : le type doit être CAPTURÉ à
  l'activation, jamais relu après coup — c'est déjà le cas pour `shooting_type`, ne pas le
  défaire.
- **Ne pas confondre « unité immobile » et « n'a pas avancé ».** Le seuil de 4+ exige *remained
  stationary*, condition plus forte que l'absence d'advance qui conditionne l'éligibilité.
