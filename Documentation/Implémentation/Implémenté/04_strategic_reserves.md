# Chantier 04 — Réserves stratégiques et Deep Strike

> **Deux cycles de vie.** **CONCEPTION** fait foi après livraison. **EXÉCUTION** est un
> prompt consommé une fois.

---

# CONCEPTION — à maintenir

## Sources

- `Documentation/40k_rules/20 Strategic reserves.pdf` — règles 20.01 à 20.04
- `Documentation/40k_rules/24 Core abilities.pdf` — Deep Strike 24.09
- `Documentation/40k_rules/03 Moving.pdf` — Set Up 03.02, référencé par 20.04

Source de vérité : les PDF. Toute divergence se tranche en leur faveur.

## Pourquoi ce chantier existe

Quatre unités Armageddon portent `CORE: Deep Strike` sans qu'il produise le moindre effet :

- Chaplain with Jump Pack
- Vanguard Veteran Squad with Jump Packs
- Land Speeder
- (et **Da Jump** du Weirdboy, qui place l'unité en réserves puis lui accorde Deep Strike)

`grep -riE "reserve|ingress" engine/` ne rend aucun résultat de mécanique de jeu. Rien
n'existe.

## Ce qui existe déjà et qu'il faut réutiliser

- `deployed_on_turn` dans l'état d'unité (`engine/game_state.py:269`)
- Les bits d'observation `deploy_not_on_board`, `deploy_pre_battle`, `deploy_in_battle`,
  `deployed_this_turn` (`engine/observation_entities.py:136-139`)
- `movement_build_valid_destinations_pool` — le pool de destinations de mouvement

**La structure d'état est déjà prête ; c'est la mécanique qui manque.** Ne pas créer un
second modèle de « pas encore sur la table » à côté de `deployed_on_turn`.

## Les règles, décomposées

### 20.01 — Mise en réserve

Avant la bataille, à l'étape Declare Battle Formations, on peut placer des unités en réserves
(hors `FORTIFICATIONS`) au lieu de les déployer.

**Plafond : la valeur totale en points des réserves ne peut dépasser 50 % de la limite de
points de la bataille.** Ce plafond est un contrôle dur — dépassement → erreur explicite au
chargement du roster, pas une troncature silencieuse de la liste.

### 20.02 — Unités repositionnées

Unités retirées de la table pendant la bataille et replacées en réserves (c'est le cas de
**Da Jump**). Trois clauses :

- Utilisable en phase de mouvement même sur une unité ayant déjà bougé.
- Une unité replacée le tour même où elle a fait un Advance / Fall Back / débarquement **a
  toujours fait** ce mouvement ce tour-là.
- Les effets en cours (durée ou circonstance) **continuent** de s'appliquer pendant qu'elle
  est hors table, tant que la durée court. Exemple du PDF : une unité battle-shocked au
  retrait est toujours battle-shocked à son retour le même tour ; une aura, en revanche,
  cesse si elle n'est plus à portée en revenant.

Cette dernière clause interagit avec le battle-shock et le Waaagh!. Les deux existent au
moment où ce chantier s'exécute — battle-shock livré par le **chantier 02** (décision prise,
il y est inclus), Waaagh! par le **chantier 03**. La clause est donc testable pour de vrai,
sur l'exemple littéral du PDF ci-dessus, et non en théorie.

### 20.03 — Arrivée

Chaque unité en réserves arrive par un **ingress move**. Sauf mention contraire, **pas avant
le second round de bataille**.

### 20.04 — Ingress move

| Élément | Valeur |
|---|---|
| Distance de mise en place | 6" |
| Éligibilité | l'unité est en réserves |
| Effet | mise en place selon Set Up (03.02) |
| Pendant | entièrement à 6" ou moins d'un ou plusieurs **bords de table**, et à **plus de 8" horizontalement de toute unité ennemie** |
| Avant le 3ᵉ round | aucune figurine dans la zone de déploiement adverse |
| Après | sauf mention contraire, l'unité n'est éligible à **aucun autre type de mouvement** jusqu'au début de la prochaine phase de charge |

**À la fin du 3ᵉ round, toute unité en réserves n'ayant pas fait d'ingress move est
détruite.** Exceptions : unités embarquées dans des transports ayant fait un ingress, et
unités repositionnées.

Cette destruction est une **règle de jeu**, pas un cas d'erreur. Elle doit être implémentée,
et elle a une conséquence directe sur l'entraînement : un agent qui garde ses unités en
réserves les perd. C'est une pression de tempo réelle qu'il doit apprendre.

### 24.09 — Deep Strike

> Each time this unit makes an ingress move (20.04), if **every model in this unit** has this
> ability, it can be set up anywhere on the battlefield that is more than 8" horizontally from
> all enemy units, even if that is within your opponent's deployment zone.

Deep Strike **remplace** la contrainte de bord de 20.04 ; il conserve les 8" et lève
l'interdiction de zone adverse. La condition « every model » compte : une escouade Deep Strike
menée par un character sans la capacité **perd** Deep Strike (règle 19.04 sur l'union des
règles — vérifier le comportement du `_fold_attached_characters` sur ce point).

Dans les rosters Armageddon : le Chaplain with Jump Pack **et** la Vanguard Veteran Squad
with Jump Packs ont tous deux Deep Strike, donc l'unité attachée le conserve. Le
Land Speeder est seul. Aucune régression n'est attendue, mais la condition doit être codée,
pas supposée.

## Observation

Aucun nouveau champ. Les bits `deploy_*` existent. L'unité en réserves est
`deploy_not_on_board` avec un `deployed_on_turn` nul.

**`deep_strike` est une capacité OBSERVÉE, et c'est ce chantier qui la déclare** (amendement du
chantier 01, 2026-08-04). La règle technique n'existe pas encore : la créer dans
`config/unit_rules.json` avec le prochain `obs_id` LIBRE — **15** à ce jour, jamais un id brûlé
— et l'ajouter à `UNIT_RULE_EFFECT_IDS`. Coût : **zéro scalaire**, `obs_size` reste à `20718`,
aucun retrain (verrou :
`test_squad_obs_unit_rules.py::test_adding_an_observed_capability_costs_zero_scalar`).
Ne PAS l'ajouter à `DECISION_GRANTABLE_EFFECT_IDS` : aucun candidat de `rule_choice` ne
l'accorde. Sans cette déclaration, l'agent subit Deep Strike sans le percevoir — exactement le
trou que V11 §0.30 a fermé, et la raison d'être de l'embedding du chantier 01.

Vérification attendue : sur le roster d'entraînement Armageddon, les `allies_ability_ids` de
CHAQUE unité à laquelle ce chantier accorde `deep_strike` — la liste en tête de ce chantier, à
confirmer datasheet en main, aucune ne portant la capacité aujourd'hui — contiennent son
`obs_id`, et une escouade sans la capacité ne le contient pas. Attention : la condition
« every model » de 24.09 se lit sur les règles PROPRES de chaque figurine
(`models_cache[mid]["UNIT_RULES"]`), pas sur les slots d'observation, qui décrivent l'union
19.04.

Ce qui manque éventuellement : le **round restant avant destruction**. Si l'agent ne le
perçoit pas, il ne peut pas apprendre la pression de tempo de 20.04. Si un scalaire global est
nécessaire, il doit être **déclaré par le chantier 01** — vérifier au démarrage, et remonter
au chantier 01 plutôt que changer `obs_size` ici.

---

# EXÉCUTION — prompt

## Préalable

Chantier 01 livré. Ce chantier n'a le droit de changer **ni** `obs_size` **ni**
`TOTAL_ACTION_SIZE`.

## Périmètre

**Autorisé :**
- `engine/game_state.py` — état de réserve, plafond 50 %
- `engine/phase_handlers/movement_handlers.py` — ingress move, pool de destinations
- `engine/w40k_core.py` — destruction en fin de 3ᵉ round
- `engine/action_decoder.py` — masque de l'ingress
- `config/agents/*/rosters/**` — déclaration des unités en réserve
- Tests ciblés, `Documentation/AI_TURN.md`

## Étapes

1. **Mise en réserve** (20.01) : champ de roster, plafond 50 % **vérifié au chargement**,
   dépassement → erreur explicite nommant les unités et le total.
2. **Pool d'ingress** (20.04) : construire les destinations légales — à 6" d'un bord, > 8"
   de tout ennemi, hors zone adverse avant le round 3. Réutiliser
   `movement_build_valid_destinations_pool` ; ne pas réimplémenter la validité de placement.
3. **Deep Strike** (24.09) : variante du pool — contrainte de bord levée, 8" conservés, zone
   adverse autorisée. Condition **« toutes les figurines »**, évaluée sur l'unité effective
   après rattachement 19.04.
4. **Après ingress** : marquer l'unité inéligible à tout autre mouvement jusqu'au début de la
   phase de charge.
5. **Round 2 minimum** (20.03) : masque fermé au round 1.
6. **Destruction fin de round 3** (20.04) : appliquer, avec les exceptions du PDF.
7. **Unités repositionnées** (20.02) : les trois clauses, dont la persistance des effets.
   Requis par **Da Jump** (chantier 06).

## Vérification exigée

- **Verrou des 8"** : une destination à 8" pile d'un ennemi est **refusée** (la règle dit
  « more than 8" »), à 8,1" acceptée. Tester la borne, pas le milieu.
- **Verrou de zone adverse** : au round 2, une unité **sans** Deep Strike ne peut pas être
  placée dans la zone adverse ; une unité **avec** le peut. Au round 3, les deux le peuvent.
- **Verrou de destruction** : unité laissée en réserves, fin du round 3 → détruite. Retirer
  la règle, le test devient **rouge**. Le prouver et le rapporter.
- **Verrou « every model »** : escouade Deep Strike + character sans la capacité → l'unité
  perd Deep Strike. Construire le cas.
- **Vert vacant** : vérifier que le pool d'ingress rend réellement des destinations non vides
  avant de conclure qu'un placement est refusé pour la bonne raison. Un pool vide fait passer
  n'importe quel test de refus.
- Les tests **construisent** leur état.

## Pièges

- Les 8" sont **horizontaux**. Le dépôt raisonne en subhex : convertir via
  `inches_to_subhex`, ne jamais coder un seuil en pouces absolus.
- Ne pas créer un second modèle de « hors table » à côté de `deployed_on_turn`.
- La destruction de fin de round 3 est une règle, pas une erreur : elle se journalise comme un
  événement de jeu normal.
- **Jumeau déploiement/mouvement** : l'ingress est une mise en place (03.02), pas un
  déplacement. Vérifier lequel des deux chemins de validation s'applique et ne pas durcir
  l'un par rapport à l'autre.
