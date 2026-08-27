# Chantier 02 — Points de Commandement (CP) et Battle-shock
> ✅ **LIVRÉ** (vérifié code le 2026-08-10). La **CONCEPTION** reste la référence vivante. Dette assumée et bornée : la **dépense** de CP n'a aucun consommateur (pas de stratagèmes) et *Rites of Battle* est hors périmètre, faute de déclencheur.
>
> **Série « chantiers capacités » (ex-`2_Various/`, dossier dissous le 2026-08-10).** Les chantiers **01 à 05 sont LIVRÉS** et rangés dans `Implémenté/` ; seul le **06** reste ouvert, dans `A_faire/`. Les renvois « chantier 0X » du texte désignent ces fichiers, qui ont gardé leur nom.
> Ordre du travail : [`../ROADMAP.md`](../ROADMAP.md) — ce fichier n'est pas une roadmap.

> **Deux cycles de vie.** **CONCEPTION** fait foi après livraison. **EXÉCUTION** est un
> prompt consommé une fois.

---

# CONCEPTION — à maintenir

## Sources

- `Documentation/40k_rules/08 Command phase.pdf` — 08.01 à 08.05
- `Documentation/40k_rules/01 Core concepts.pdf` — 01.06 jets de commandement, 01.07 jets de battle-shock
- `Documentation/40k_rules/25 Rules appendix.pdf` — force de départ et demi-effectif
- `Documentation/40k_rules/Armageddon/Datasheets - Orks.pdf` — Thievin' Scavengers (Gretchin)

Les PDF font foi. Toute divergence avec ce document se tranche en leur faveur.

## Périmètre — arbitrage rendu

Le battle-shock **fait partie de ce chantier**. Décision de l'utilisateur.

Raison : Thievin' Scavengers exige des unités *« non battle-shocked »*. Sans battle-shock, la
condition serait toujours vraie et la capacité serait implémentée **plus permissive que la
règle** — une valeur par défaut masquant un manque, interdite (T1). Le battle-shock est par
ailleurs requis par le contrôle d'objectif, les stratagèmes et les actions.

Le chantier est donc plus large que son titre d'origine. C'est assumé et arbitré en amont.

---

## Ce qui manque, exactement

| Élément | État |
|---|---|
| Compteur de CP par joueur | absent (`grep -riE "command_point" engine/` → 0 hit) |
| Gain de CP (08.02) | absent |
| Dépense de CP | absent — **aucun consommateur** tant qu'il n'y a pas de stratagème |
| Battle-shock | absent — `LD` est porté par chaque unité mais **jamais lu** |
| Force de départ / demi-effectif | absent |

---

## La phase de commandement, telle que le PDF la définit

`08.01` Début de phase → `08.02` Gain de Core CP → `08.03` Battle-shock →
`08.04` Capacités de commandement → `08.05` Fin de phase.

L'ordre compte : le moteur a déjà une phase `command`
(`engine/phase_handlers/command_handlers.py`), mais pas ces cinq étapes. Plusieurs capacités
du chantier 06 se déclenchent à des étapes précises (Get da Good Bitz en **fin** de phase,
Grot Orderly en phase de commandement, Waaagh! et Oath au **début**). Sans les étapes, ces
capacités ne peuvent pas être placées correctement.

### 08.02 — Gain de Core CP

> Both players gain 1 Command Point (CP).

**Les deux joueurs**, pas seulement le joueur actif. Un gain de 1, pas une valeur libre. Il
n'y a rien à configurer ici : c'est la règle. Un champ de config serait une invention.

### 08.03 — Battle-shock

> The active player must now make one battle-shock roll (01.07) for each unit in their army
> that fulfils one or both of the following conditions:
> ▪ That unit is currently battle-shocked.
> ▪ That unit is at, or below, half-strength.
>
> If a unit was battle-shocked at the start of this step and its battle-shock roll during this
> step succeeds, it is no longer battle-shocked.

Le jet se fait pour le **joueur actif seulement**. Une unité déjà battle-shocked rejette
chaque tour : c'est ce jet qui lui permet de s'en sortir.

---

## Le battle-shock, tel que le PDF le définit

### 01.06 — Jet de commandement

> To make a leadership roll for a unit, its controlling player rolls 2D6: if the result is
> equal to or greater than **one or more** of the Ld characteristics in that unit, that roll
> succeeds.

**2D6**, pas 1D6. Et *« one or more of the Ld characteristics »* : dans une unité contenant
plusieurs profils (escouade + character rattaché), on retient le **meilleur** Ld, c'est-à-dire
le seuil le plus bas. Un Warboss (`LD 6+`) rattaché à des Boyz (`LD 7+`) fait passer l'unité
à 6+.

C'est une conséquence directe de la règle 19.04 déjà implémentée
(`engine/game_state.py` `_fold_attached_characters`) : ne pas recoder une sélection de Ld
à côté, lire l'unité effective.

### 01.07 — Jet de battle-shock

> To make a battle-shock roll for a unit, its controlling player makes a leadership roll for
> it.
> ▪ If that roll succeeds, that unit does not become battle-shocked.
> ▪ If that roll fails, that unit, **and each model in it**, is battle-shocked.
>
> While a unit is battle-shocked:
> ▪ The Objective Control (OC) characteristic of all of its models is modified to '-' (02.02).
> ▪ Its controlling player cannot target that unit with stratagems (15).
> ▪ It is not eligible to start an action (16), and any action it has started cannot
>   be completed.

Trois effets, dont **un seul est applicable aujourd'hui** :

| Effet | Applicable ? |
|---|---|
| OC → '-' | **oui** — `engine/game_state.py` `_sum_objective_control_oc` |
| Pas ciblable par un stratagème | sans objet — pas de stratagèmes |
| Inéligible aux actions | sans objet — pas de système d'actions (16) |

Les deux derniers ne se codent pas : ils n'ont aucun déclencheur. Écrire du code pour eux
produirait du code jamais atteint. Ils sont documentés ici pour que le jour où stratagèmes et
actions existent, on sache que le battle-shock les concerne.

`OC → '-'` n'est **pas** `OC = 0` par convention interne : c'est une caractéristique modifiée
(02.02). Vérifier comment `_sum_objective_control_oc` traite une valeur absente avant de
choisir la représentation.

### Force de départ et demi-effectif (appendice 25)

> The number of models a unit contains at the start of the first battle round is its starting
> strength. The starting strength of an attached unit is the number of models that unit
> contains at the start of the first battle round.

| | Force de départ 1 | Force de départ ≥ 2 |
|---|---|---|
| **Sous l'effectif de départ** | PV restants < W | figurines restantes < force de départ |
| **À demi-effectif** | PV restants = W / 2 | figurines restantes = force de départ / 2 |
| **Sous le demi-effectif** | PV restants < W / 2 | figurines restantes < force de départ / 2 |

> If a model's W characteristic or a unit's starting strength cannot be evenly divided in
> half, that model or unit **cannot be at half-strength** (but can be below half-strength).

Ce dernier point est un piège réel : une escouade de 5 ne peut jamais être *à* demi-effectif.
Une implémentation en `<=` sur une division entière le raterait.

Exemple du PDF, directement applicable aux rosters Armageddon :

> A Captain (1 model) is attached to a unit of Intercessors (5 models). This attached unit has
> a starting strength of **6**.

Donc la force de départ se calcule sur l'unité **après** rattachement, pas sur la datasheet.

---

## Thievin' Scavengers (Gretchin)

> At the start of your Movement phase, for each objective you control that has one or more
> friendly non-battle-shocked units with this ability within range of it, roll one D6. If one
> or more of those rolls is a 4+, you gain 1CP.

Nom générique : `cp_gain_on_objective`.

Deux pièges de lecture :

1. Le déclenchement est en **phase de mouvement**, pas de commandement. Ne pas le ranger avec
   le gain de Core CP par confort d'implémentation.
2. *« If one or more of those rolls is a 4+, you gain 1CP »* — **un seul CP au total**, quel
   que soit le nombre d'objectifs qui réussissent. On lance un dé par objectif, mais le gain
   est global.

---

## Rites of Battle : non livrable, et pourquoi

> Once per battle round, per army: When a stratagem targets this unit, you can reduce its cost
> by 1CP for that use.

Sans système de stratagème, *« when a stratagem targets this unit »* n'a **aucun
déclencheur**. Coder la réduction produirait du code jamais atteint — le motif « code testé
mais jamais appelé » déjà rencontré dans ce dépôt.

Rites of Battle est donc **hors périmètre**, y compris de ce chantier. Elle reste comptée dans
le décompte des capacités par unité du chantier 01 (le Captain en porte 2 avec elle), mais
n'est pas implémentée. Ce n'est pas une dette déguisée : le blocage est technique et externe
au chantier.

---

## Observation

| Donnée | Emplacement | Nature |
|---|---|---|
| CP des deux joueurs | `global_cont`, 2 scalaires normalisés | grandeur globale |
| Battle-shock | `status_ids` de l'unité | statut, pas un bit dédié |
| Sous / à demi-effectif | dérivable des PV et du nombre de figurines déjà observés | rien à ajouter |

**Ce chantier ne change ni `obs_size` ni `TOTAL_ACTION_SIZE`.** Les deux scalaires de CP et
l'id de statut `battle_shock` sont déclarés par le **chantier 01**. Si les emplacements
manquent, remonter au chantier 01 — ne pas les créer ici.

---

# EXÉCUTION — prompt

## Préalable

Chantier 01 livré. Vérifier que `config/unit_statuses.json` contient l'id `battle_shock` et
que `global_cont` porte les deux emplacements de CP. Sinon, **arrêter** et corriger le
chantier 01.

## Périmètre

**Autorisé :**
- `engine/phase_handlers/command_handlers.py` — les 5 étapes 08.01–08.05
- `engine/phase_handlers/movement_handlers.py` — Thievin' Scavengers (début de phase)
- `engine/game_state.py` — CP, force de départ, statut battle-shock, OC modifié
- `engine/observation_builder.py` — lecture des CP
- `config/unit_rules.json` — `cp_gain_on_objective`
- `frontend/src/roster/ork/units/Gretchin.ts` — déclaration de la capacité
- Tests ciblés, `Documentation/AI_TURN.md`

**Interdit :** stratagèmes, Rites of Battle, dépense de CP sans consommateur, effets du
battle-shock sur les stratagèmes ou les actions (pas de déclencheur).

## Étapes

1. **Étapes de la phase de commandement.** Découper la phase existante selon 08.01–08.05.
   C'est le prérequis des chantiers 03 et 06.
2. **Force de départ.** Figée au début du premier round, sur l'unité **après** rattachement
   19.04. Prédicats `is_below_starting_strength`, `is_at_half_strength`,
   `is_below_half_strength`, avec la clause « division impaire → jamais *à* demi-effectif ».
3. **CP** (08.02). Les **deux** joueurs gagnent 1 CP. Valeur de départ lue en config, sans
   valeur par défaut : absente → erreur explicite.
4. **Battle-shock** (08.03 + 01.06 + 01.07). Jet 2D6 contre le **meilleur** Ld de l'unité
   effective, pour le joueur **actif** seulement, sur les unités battle-shocked **ou** à/sous
   demi-effectif. Réussite d'une unité déjà battle-shocked → elle cesse de l'être.
5. **Effet OC** (01.07). OC modifié à '-' pour toutes ses figurines, répercuté dans
   `_sum_objective_control_oc`.
6. **Thievin' Scavengers** — 1 D6 par objectif contrôlé portant ≥ 1 unité amie non
   battle-shocked avec la capacité ; ≥ 1 résultat de 4+ → **+1 CP au total**.
7. **Observation.** Renseigner les deux scalaires de CP et le statut.

## Vérification exigée

- **Verrou 2D6 / meilleur Ld** : Boyz (`LD 7+`) + Warboss (`LD 6+`) → l'unité teste à 6+.
  Retirer la sélection du meilleur Ld, le test devient **rouge**. Le prouver et le rapporter.
- **Verrou demi-effectif impair** : escouade de force de départ 5 réduite à 2 figurines →
  **sous** le demi-effectif, jamais *à*. Une escouade de 5 ne doit **jamais** être classée
  « à demi-effectif ». Construire le cas, prouver le rouge.
- **Verrou force de départ attachée** : Intercessors (5) + Captain (1) → force de départ 6,
  pas 5. C'est l'exemple littéral du PDF.
- **Verrou OC** : unité battle-shocked sur un objectif → elle ne compte plus dans
  `_sum_objective_control_oc`, et le contrôle bascule. Prouver le rouge.
- **Verrou de sortie** : unité battle-shocked qui réussit son jet au tour suivant cesse de
  l'être.
- **Verrou Thievin'** : 2 objectifs contrôlés avec Gretchin, les deux dés forcés à 4+ →
  **+1 CP, pas +2**. Remettre le défaut (un CP par objectif), prouver le rouge.
- **Verrou joueur actif** : le jet de 08.03 ne se fait **que** pour l'armée du joueur actif.
- **Vert vacant** : vérifier que l'énumération des unités à tester rend réellement des
  éléments. Une liste vide fait passer tous les tests de battle-shock.
- Les tests **construisent** leur état ; ils ne l'espèrent pas d'une graine.

## Pièges

- **2D6, pas 1D6.** Le seuil `LD` est écrit `6+`, `7+`, `8+` sur les datasheets — ce sont des
  cibles de 2D6, pas de D6.
- **Meilleur Ld**, pas celui du chef ni celui du premier modèle.
- Une escouade à force de départ impaire ne peut **jamais** être *à* demi-effectif.
- Le gain de CP concerne **les deux** joueurs ; le jet de battle-shock **un seul**.
- Thievin' se déclenche en phase de **mouvement**.
- Ne pas coder les effets « stratagèmes » et « actions » du battle-shock : aucun déclencheur.
- `obs_size` ne bouge pas.
- **Jumeau** : le battle-shock touche le contrôle d'objectif (moteur), le replay, l'analyzer
  et le frontend. Vérifier les quatre.
