# Le journal nomme la figurine qui encaisse chaque attaque (2026-08-12)

## Le défaut

Le journal disait qu'une escouade perdait des PV. Il ne disait jamais **qui** les perdait.

L'analyzer devait donc deviner, et il devinait deux fois :

**Qui encaisse.** Il déduisait la figurine touchée d'un tri à un seul critère — non-CHARACTER
avant CHARACTER, puis l'ordre du segment `[MODELS:]` (`_ordered_living_mids`). Le moteur, lui,
applique une cascade (`_select_allocation_model`) : figurine déjà blessée d'abord, puis tier de
rôle (base < arme spéciale < sergent < support < leader), puis proximité d'un ennemi, puis index.
Deux règles différentes, donc deux figurines différentes.

**Où sont les autres.** À chaque perte, `_apply_damage_and_handle_death` effaçait **tous** les
socles connus de l'escouade (`positions_by_model.pop`) — le journal ne disant pas lequel retirer.
L'escouade était alors mesurée comme un point unique, son ancre, restée sur le hex de la figurine
qui venait de tomber.

## La mesure, avant de corriger

Sur le journal de 600 épisodes du 2026-08-12 :

| | |
|---|---|
| Fenêtres « socles inconnus » ouvertes | **2 342** (toutes en SHOOT ou FIGHT) |
| Refermées par `[TARGET_MODELS:]` / `[MODELS:]` / instantané de tour | 1 652 / 690 / **0** |
| Longueur : médiane / p90 / max | 3 / 119 / 2 629 lignes |
| PV par socle faux, comparés aux instantanés `T{n} STATE:` | **200 sur 173 129** (141 escouades sur 32 233) |

Les PV faux sont un **minorant** : l'instantané de début de tour recale tout, donc seules les
divergences qui lui survivent sont comptées.

## La correction

Le moteur connaît la figurine au moment exact où il l'alloue (`_resolve_one_manual_wound`, qui
sert le tir **et** la mêlée). Il l'écrit désormais au journal :

```
… - Save 2(5+) - Dmg:2HP [R:+0.0] [MODELS: …] [SHOOTER_MODELS: …] [ALLOC_MODEL: 101#3] [SUCCESS]
```

Émis au point d'écriture **commun** aux deux formateurs (`log_action`), jamais dans les branches
SHOT et FOUGHT séparément — c'est la paire où ce dépôt diverge. Posé dès que la figurine est
choisie, donc **avant** les trois retours anticipés (sauvegarde réussie, D nul, Feel No Pain) :
l'allocation a eu lieu dans tous ces cas, les dégâts n'en sont que la conséquence.

L'analyzer le **lit** au lieu de déduire. Disparaissent avec la devinette : le tri par rôle, et le
report du surplus de dégâts sur la figurine suivante — un calcul qui contredisait le moteur, lequel
plafonne (`dmg_dealt = min(dmg, hp_before)`).

### La version de grammaire, sans laquelle le token serait un piège

`Log grammar: 2` entre à l'entête. Sans elle, un lecteur qui ne trouve pas le segment ne peut pas
distinguer « ce journal ne le porte pas » de « le producteur est en panne », et n'a d'autre choix
que de retomber **en silence** sur la devinette qu'on vient de retirer. Avec elle, l'absence LÈVE.
Source unique producteur/lecteur : `ai/step_logger.LOG_GRAMMAR_VERSION`.

### Le moment du retrait : la fin de l'ACTIVATION

C'est le point le moins évident, et il a été trouvé par la mesure, pas par le raisonnement.

Retirer le socle **dès sa mort** fait juger les jets suivants de la même salve sur les survivants
des précédents. Mesuré sur le run du jour, E44 : un Onslaught Gatling Cannon (24") vise une
escouade dont la figurine la plus proche est à 22 hex, tue les six plus proches, et ses trois
derniers jets ressortent « hors portée » — les quatre survivantes étant à 25, 26, 26 et 27. La
portée se décide **une fois**, au Select Targets (10.02).

Ne rien retirer du tout ne marche pas non plus : une mort qui n'émet aucun segment de survivants
(blessures mortelles, retrait de cohérence) laisserait la figurine debout jusqu'à la prochaine
action de son escouade.

Le retrait est donc différé jusqu'à ce qu'une **autre unité agisse** (`pending_model_removals`).
C'est le miroir, côté lecteur, de ce que le moteur fait déjà côté producteur : il diffère
`[TARGET_MODELS:]` au dernier jet parce que « les pertes se retirent APRÈS résolution de toutes
les attaques ».

### Interaction avec le gel « Select Targets » (livré le même jour, autre branche)

Le chantier voisin *L'engagement d'un tir se juge AVANT les pertes* fige la géométrie de la cible
à la première ligne de l'activation (`freeze_select_targets`), et le contrôle de portée lit
désormais cette carte gelée. On pourrait croire les deux mécanismes redondants : ils ne le sont
pas, et la mutation le prouve.

Le gel capture la carte **telle qu'elle est quand il est pris** — or les dégâts d'une ligne sont
appliqués avant que ses contrôles ne soient rendus. Sans le différé, la première ligne d'une salve
qui tue fige déjà une carte amputée, et tous les jets suivants héritent de cette amputation. Le
différé garantit ce qui est gelé ; le gel garantit qu'on ne le relit pas ligne à ligne.

Vérifié après merge : retrait ramené à la ligne → le verrou de portée redevient ROUGE, gel présent.

## Vérification sur le même journal, avant / après

60 épisodes (17 h 23). Le passage « avant » est ce journal **privé de sa ligne d'entête et de ses
tokens**, donc la même partie, les mêmes dés, le même tout.

| | avant | après |
|---|---|---|
| Lignes de seuil de blessure non vérifiables — tir | 201 | **0** |
| — mêlée | 295 | **0** |
| Seuils faux découverts | — | **0** |
| Section 2.8 (état reconstruit vs moteur) | 0 | **0** |
| Toute autre famille du rapport | — | inchangée |

**496 lignes cessent d'être écartées**, et aucune ne condamne le moteur : il avait raison, l'analyzer
ne pouvait pas le dire. La cause était directe — `target_bodyguard_toughness` (19.02) se rabat sur
le roster complet quand les socles vivants sont inconnus, et refuse de trancher dès que les
bodyguards n'ont pas tous la même E.

Le nouveau compteur `figurine allouée inconnue` (section 2.8) reste à **0** : sur 60 épisodes,
l'état par-socle reconstruit ne contredit jamais les instantanés du moteur.

## Deux corrections de l'analyse initiale, trouvées en implémentant

**1. Le faux positif « tir engagé, arme non-CLOSE_QUARTERS » n'est PAS expliqué par ce chantier.**
Le journal de démonstration qui l'avait reproduit omettait `[TARGET_MODELS:]` sur une ligne de tir,
c'est-à-dire construisait un journal qu'aucun moteur ne produit. Sur un journal réel, ce segment
referme la fenêtre à chaque fin d'activation : elle ne franchit donc pas l'activation. Les 2 342
fenêtres sont réelles, mais elles vivent **à l'intérieur** d'une salve — là où le défaut de portée
E44 s'est manifesté, et nulle part ailleurs. **Ce faux positif retourne à l'état de non expliqué.**

**2. Le premier correctif a introduit une erreur, attrapée par la mesure.** Différer le retrait
d'une seule ligne (au lieu de la fin de l'activation) a produit l'erreur E44 ci-dessus, absente
avant le chantier. Le chemin hérité y échappait par accident : en effaçant toute l'escouade, il
faisait retomber la mesure sur l'ancre, fraîche. Nommer la figurine supprime ce hasard et oblige à
poser la discipline explicitement.

## Verrous (prouvés ROUGES un par un, par mutation)

`tests/unit/ai/test_step_log_weapon_rule_tokens.py` — chaîne d'ÉMISSION : record moteur → mapping
→ ligne, paramétré tir/mêlée (émission coupée → 2 rouges) ; aller-retour de l'entête de grammaire
(ligne supprimée → 1 rouge).

`tests/unit/ai/test_analyzer_alloc_model_named.py` — EXPLOITATION : portée non jugée sur les
survivants de la même salve (retrait ramené à la ligne → 1 rouge) ; dégâts sur la figurine nommée
et non déduite (nom ignoré → 2 rouges) ; token exigé et absent → erreur explicite ; journal
d'ancienne grammaire toujours lisible.

`frontend/src/utils/replayParser.test.ts` — le token n'est pas lu comme un nom de capacité (retiré
du jeu fermé → 1 rouge). ⚠️ Ce verrou place le token juste après le jet, ce que l'émetteur ne fait
pas aujourd'hui : l'entrée dans `LINE_METADATA_TOKEN` est **défensive** (le token est en pratique
précédé de `[R:]` et `[MODELS:]`, déjà membres). Elle protège un changement d'ordre d'émission
futur, pas un défaut vivant — et c'est dit dans le code.

## Ce qui reste ouvert

- Trois chemins de retrait n'écrivent aucune ligne exploitable : cohérence de fin de tour (03.03,
  console seule), blessures mortelles (ligne sans détail par socle), expiration de réserves. Ils
  restent rattrapés par l'instantané de fin de tour — 1 fantôme mesuré sur 600 épisodes.
- `_apply_charge_impact` applique ses blessures mortelles à l'**escouade**
  (`update_units_cache_hp`), sans toucher aucune figurine, donc sans allocation 06.02. C'est une
  divergence **moteur**, pas analyzer. Signalée, non traitée : elle mérite son propre chantier.
- Le faux positif « tir engagé, arme non-CLOSE_QUARTERS » (11 côté P2 au run du matin) : sans
  cause établie, et le journal qui le portait a été écrasé.
