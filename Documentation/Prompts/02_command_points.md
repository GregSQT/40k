# Chantier 02 — Points de Commandement (CP)

> **Deux cycles de vie.** **CONCEPTION** fait foi après livraison. **EXÉCUTION** est un
> prompt consommé une fois.

---

# CONCEPTION — à maintenir

## Pourquoi ce chantier existe

Aucune notion de CP n'existe dans le moteur (`grep -riE "command_point" engine/` → 0 hit).
Deux capacités Armageddon en dépendent directement :

- **Rites of Battle** (Captain with Relic Shield) — *« Once per battle round, per army: When a
  stratagem targets this unit, you can reduce its cost by 1CP for that use. »*
- **Thievin' Scavengers** (Gretchin) — *« At the start of your Movement phase, for each
  objective you control that has one or more friendly non-battle-shocked units with this
  ability within range of it, roll one D6. If one or more of those rolls is a 4+, you gain 1CP. »*

Les CP sont aussi le prérequis de tout le système de stratagèmes, hors périmètre ici.

## Ce qui manque, exactement

| Élément | État |
|---|---|
| Compteur de CP par joueur | absent |
| Gain de CP (début de phase de commandement) | absent |
| Dépense de CP | absent — aucun consommateur tant qu'il n'y a pas de stratagème |
| Réduction de coût (Rites of Battle) | absent, et sans objet sans stratagème |
| **Battle-shock** | absent — `LD` est porté par les unités mais jamais utilisé |

## La dépendance non évidente : battle-shock

Thievin' Scavengers exige des unités **non battle-shocked**. Sans battle-shock, la condition
est toujours vraie, donc la capacité serait implémentée **fausse** — plus généreuse que la
règle. Ce n'est pas acceptable : ce serait une valeur par défaut masquant un manque (T1).

Deux voies honnêtes :

1. **Implémenter le battle-shock dans ce chantier.** `LD` existe déjà sur chaque unité. Le
   test de commandement est une mécanique bornée et bien définie. C'est la voie recommandée :
   elle rend Thievin' Scavengers exacte, et le battle-shock est de toute façon requis par la
   suite (il conditionne le contrôle d'objectif et bien d'autres règles).
2. **Renoncer à Thievin' Scavengers** et la laisser explicitement non implémentée.

**Recommandation : voie 1.** Elle est plus large que le titre du chantier — c'est signalé
ici, en amont, pour arbitrage, conformément à la règle « annoncer AVANT, pas après ».

## Rites of Battle : honnêteté sur ce qui est livrable

Sans système de stratagème, *« when a stratagem targets this unit »* n'a **aucun déclencheur**.
Implémenter la réduction de coût produirait du code jamais atteint — le motif « code testé
mais jamais appelé » déjà rencontré dans ce dépôt.

Rites of Battle est donc **hors de ce chantier**. Elle est débloquée par les CP mais exige les
stratagèmes. Elle reste comptée dans le décompte des capacités par unité (chantier 01 :
le Captain en porte 2 avec elle), mais n'est pas codée ici.

## Observation

Le CP est une grandeur **globale**, pas par unité : deux scalaires continus dans
`global_cont` (mes CP, ceux de l'adversaire), normalisés.

Le battle-shock est un **statut d'unité** : un id dans `status_ids` (chantier 01), pas un
nouveau bit.

**Ni l'un ni l'autre ne change `obs_size`** — les emplacements sont déclarés par le
chantier 01. Si `global_cont` doit s'élargir de deux scalaires, c'est le **chantier 01** qui
le fait, pas celui-ci. À vérifier au démarrage : si les deux places n'ont pas été réservées,
remonter au chantier 01 plutôt que de changer `obs_size` ici.

---

# EXÉCUTION — prompt

## Préalable bloquant

Trancher la question du battle-shock (voie 1 ou 2 ci-dessus) **avant** d'écrire. Ne pas
implémenter Thievin' Scavengers avec une condition « non battle-shocked » toujours vraie.

## Périmètre

**Autorisé :**
- `engine/game_state.py` — compteur de CP dans l'état
- `engine/phase_handlers/command_handlers.py` — gain en début de phase de commandement
- `engine/observation_builder.py` — lecture des deux scalaires globaux
- `config/game_config.json` — CP de départ, gain par round
- Le battle-shock si voie 1 : test de commandement, statut, effets
- Tests ciblés, `Documentation/AI_TURN.md`

**Interdit :** stratagèmes, Rites of Battle, toute dépense de CP sans consommateur réel.

## Étapes

1. **État.** `command_points` par joueur dans `game_state`. Valeur initiale lue en config,
   **sans valeur par défaut** : absente → erreur explicite.
2. **Gain.** Au début de la phase de commandement du joueur actif, appliquer le gain
   configuré.
3. **Battle-shock** (si voie 1) : test de commandement sur `LD`, statut porté dans
   `status_ids`, effets sur le contrôle d'objectif.
4. **Thievin' Scavengers** — `cp_gain_on_objective` : au début de ta phase de mouvement, pour
   chaque objectif contrôlé où se trouve ≥ 1 unité amie non battle-shocked portant la
   capacité, 1 D6 ; ≥ 1 résultat de 4+ → +1 CP. **Un seul CP au total**, pas un par objectif —
   relire le texte, la formulation « If one or more of those rolls is a 4+ » est un test
   global.
5. **Observation.** Renseigner les deux scalaires globaux.

## Vérification exigée

- **Verrou de gain** : partie à graine fixée, CP au tour N conforme au calcul attendu.
- **Verrou Thievin'** : construire l'état (2 objectifs contrôlés avec Gretchin dessus,
  dés forcés) et vérifier **+1 CP, pas +2**. Remettre le défaut (un CP par objectif) et
  vérifier que le test devient **rouge**. Le rapporter.
- **Verrou battle-shock** (voie 1) : une unité sous son seuil de `LD` échoue le test et perd
  le contrôle d'objectif. Prouver le rouge.
- Le test doit **construire** l'état observé, jamais l'espérer d'une graine.

## Pièges

- Ne pas ajouter de dépense de CP « pour plus tard » : sans consommateur, c'est du code mort.
- `obs_size` ne bouge pas. Si un emplacement manque, c'est le chantier 01 qu'il faut corriger.
- Le gain de Thievin' se fait en **phase de mouvement**, pas de commandement. Ne pas le
  ranger avec le gain de round par confort.
