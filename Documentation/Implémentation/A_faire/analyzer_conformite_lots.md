# Analyzer — conformité des règles : découpage en lots

> Ouvert le **2026-08-16**. État établi par LECTURE DU CODE sur `main` à `cdd3e057`, pas depuis
> `analyzer_couverture.md` — la matrice est tenue à la main et a déjà vieilli en silence
> plusieurs fois. Chaque affirmation ci-dessous porte sa preuve (fichier:ligne ou grep).
>
> Objectif du chantier : que l'analyzer VÉRIFIE les règles, au lieu de compter leur usage. Le
> découpage est séquentiel parce que tous les lots éditent `ai/analyzer*.py` — voir §3.

## 1. Ce qui est ACQUIS (ne pas re-lancer)

| Acquis | Preuve |
|---|---|
| Cartographie règle → contrôle → champs de log | [`analyzer_couverture.md`](../analyzer_couverture.md) |
| Triage des compteurs du run (pile-in/conso > 3", charge depuis hex adjacent, tirs hors portée, tir engagé sur unité non engagée, attaques > CC_NB) | tous tranchés faux positifs, contrôles réancrés par-figurine |
| Géométrie move / charge / fight | `FLED` contrôlé (09.07), BFS avec bord de plateau (`parse_board_dims_from_log`) et exemption 17.01 (`monster_or_vehicle_by_unit`), compteurs morts supprimés |
| **Pont des tokens de règles d'armes** | grammaire 3 (2026-08-12) : `[TORRENT]`, `[LETHAL HITS]`, `[IGNORES COVER]`, `[EXTRA ATTACKS]`, `[ANTI-X:Y+]`, `[PSYCHIC]`, au tir ET en mêlée (`ai/step_logger.py`, tables `_HIT_SEGMENT_RULE_TOKENS` / `_WOUND_SEGMENT_RULE_TOKENS` / `_LINE_TAG_RULE_TOKENS`). Grammaire 4 (2026-08-16) : `[ASSAULT]` 24.04 et `[CLOSE-QUARTERS]` 24.07 |
| Couverture rendue en DONNÉE | `config/rules_corpus.json` + `ai/analyzer_rules.py` — **7 règles** : 03.01, 03.03, 09.05, 09.07, 20.04, `PROJET.reactive_move`, `PROJET.move_after_shooting` |

**Le « lot A — pont des tokens » du découpage initial n'a plus d'objet** : l'entrée `L5` de
`analyzer_couverture.md` §7 est soldée. Ce qui a changé n'est pas mince — pour ces six règles,
un compteur d'usage à zéro veut désormais dire « la règle n'a pas joué », plus « le journal ne
sait pas le dire ».

## 2. Hors périmètre de ce chantier

- **`[INDIRECT FIRE]` 24.19** — pièce 6 du chantier `10.07`, déjà ouvert
  → [`indirect_fire_10_07.md`](../Implémenté/indirect_fire_10_07.md). ⚠️ La règle JOUE depuis le 2026-08-16
  sans que le journal le dise : une ligne de tir indirect rend `Hit 6(3+->6+)` sans que rien ne
  distingue le modificateur de la règle de celui de la datasheet.
- **`[LANCE]` 24.21** — règle non implémentée dans le moteur ; son token n'est pas un travail de
  journal.
- **Les bugs moteur** que les lots 1 et 6 vont prouver : ils se listent, ils ne se corrigent pas
  ici.

## 3. Ordre et parallélisation

    Manche 1 : lot 1 ∥ lot 4        (2 worktrees)
    Manche 2 : lot 2                 (a besoin du socle de tir assaini par le lot 1)
    Manche 3 : lot 3 puis lot 5      (ordre libre, jamais ensemble)
    Manche 4 : lot 6

**Ce qui sérialise n'est pas « le fichier analyzer », ce sont trois zones de
[`ai/analyzer.py`](../../../ai/analyzer.py)** que tout lot AJOUTANT un compteur doit éditer : la
déclaration du dict `stats` (~1780-1900), les buckets d'`error_totals` (~1470-1560) et
`print_statistics` (~3200-3900). Le conflit git y est mécanique ; c'est sa RÉSOLUTION qui est
dangereuse — un bucket oublié dans `error_totals` produit un « ❌ 1.6 : 1 » suivi d'un
« ✅ 0 erreur », défaut déjà vécu (V16) et verrouillé depuis par
`tests/unit/ai/test_analyzer_error_totals.py`.

Le lot 1 ne crée aucun compteur (il corrige des contrôles existants) : c'est ce qui le rend
parallélisable avec le lot 4. **Si le lot 1 doit finalement supprimer ou renommer un compteur, il
retombe dans les trois zones : le sérialiser à nouveau.**

Une découpe de l'analyzer en modules par section rendrait tout parallèle. **Déconseillé** : c'est
un refactor structurel sur le chemin exact que le chantier va modifier, payé par une passe de
re-vérification de tous les totaux avant d'avoir écrit un seul contrôle neuf.

## 4. Méthode commune — à recopier dans CHAQUE lot

    VERROU par contrôle : un test pytest tests/unit/ai/ qui CONSTRUIT une ligne de log fautive
    (compteur → 1) ET le cas sain (→ 0). Prouve le rouge : remets le défaut, purge __pycache__
    (une mutation de même longueur restaurée laisse Python exécuter le mutant), constate le rouge,
    rétablis, rapporte-le. Lance uniquement les fichiers de test que tu as écrits.

    CONTRÔLE DE MASSE, en plus du verrou — un test vert ne dit rien du taux de fausse alarme, et
    c'est le mode d'échec historique de ce chantier : 317 faux positifs, puis 334, puis 31, tous
    livrés verts. Avant de livrer, fais tourner ai/analyzer.py sur un journal RÉEL et rends, pour
    chaque contrôle neuf : le nombre de verdicts RENDUS, le nombre d'erreurs LEVÉES, et l'examen
    MANUEL d'au moins 5 occurrences (ou de toutes s'il y en a moins) — épisode, ligne, pourquoi
    c'est une vraie faute.
    Un contrôle qui lève des erreurs en masse sans qu'une seule soit prouvée ne se livre pas.
    Un contrôle qui ne rend AUCUN verdict ne se livre pas non plus : c'est un vert vacant.

    Règles transverses : tout seuil passe par inches_to_subhex, la géométrie suit geometry_is_hex,
    les distances sont par-figurine et jamais d'ancre à ancre, l'état se juge AVANT les pertes de
    la ligne jugée. Le plafond d'attaques est déjà mutualisé tir/mêlée
    (analyzer_perfig.per_model_attack_cap) : passe par lui, n'en écris pas un second exemplaire.

## 5. Les six lots

### Lot 1 — trancher les familles d'erreurs encore vivantes

```
[MODE AGENT] Worktree : EnterWorktree name=analyzer-lot1-familles.

Investigation (T3) puis correction. Quatre familles d'erreurs sont encore affichées par le
rapport : engaged_non_close_quarters, tir engagé visant une unité NON engagée avec le tireur,
attaque non allouée, advance au-delà du budget. Relance d'abord python3 ai/analyzer.py sur un
step.log récent : les effectifs cités dans ROADMAP.md datent du run du 2026-08-11 et ne sont pas
une source.

Pour CHAQUE famille : verdict PROUVÉ, fichier:ligne + épisode témoin — faux positif de l'analyzer
(à corriger ici) ou faute du moteur (à LISTER pour l'utilisateur, PAS à corriger dans ce lot).

Point de départ documenté, à ne pas re-parcourir : ROADMAP.md dit du faux positif « tir engagé
arme non-CLOSE_QUARTERS » qu'il ne s'explique PAS par la fenêtre de position fantôme — celle-ci
est refermée par [TARGET_MODELS:] à l'intérieur de l'activation — et qu'il « vient d'ailleurs, et
reste ouvert ». ⚠️ Les tokens [ASSAULT] et [CLOSE-QUARTERS] enregistrent le verdict du portier
d'éligibilité depuis le 2026-08-16 (grammaire 4) : c'est une donnée neuve pour cette famille.
Pièges déjà rencontrés, à écarter en premier : mesure d'ancre au lieu du par-figurine ; distance
hex vs euclidienne ; état jugé APRÈS les pertes de la ligne alors que le moteur a décidé avant ;
roll d'advance absent du budget ; seuil raisonné en pouces au lieu de passer par inches_to_subhex.

Ce lot passe AVANT l'écriture des contrôles d'armes : trois des quatre familles sont des contrôles
de tir, et le lot 2 va en écrire d'autres juste à côté. Livrer le lot 2 sur un socle dont on sait
qu'il ment est ce qui a déjà coûté deux campagnes de faux positifs.

VERROU + CONTRÔLE DE MASSE : cf. §4. Ici l'avant/après sur le MÊME journal est possible et exigé,
famille par famille — l'analyzer est déterministe à journal donné. Une famille qui tombe à 0 doit
être expliquée : contrôle corrigé, ou contrôle devenu aveugle. Ce n'est pas la même chose, et
seule la seconde est une régression.
Fin : commit, ExitWorktree keep, merge main, suppression worktree+branche, rapport de clôture T2.
```

### Lot 2 — validité des règles d'armes

```
[MODE AGENT] Worktree : EnterWorktree name=analyzer-lot2-armes. Prérequis : lot 1 mergé.

§1.8 ne rend aujourd'hui qu'un compteur d'USAGE (OK / NOT USED / INVALID), pas un contrôle de
conformité : INVALID ne qualifie qu'une paire (règle, arme) observée que l'armurerie ne déclare
pas. Écris le contrôle de VALIDITÉ de chaque règle de config/weapon_rules.json. Pour CHAQUE règle,
lis sa définition dans Documentation/40k_rules/24*.pdf AVANT d'écrire le contrôle ; en cas d'écart
PDF/json, le PDF fait foi et l'écart se SIGNALE — le json ne se modifie pas (il peut être relu à
chaud par un training en cours).

Au minimum : RAPID FIRE (attaques doublées seulement à mi-portée), MELTA (bonus de dégâts
seulement à mi-portée), HEAVY (+1 touche seulement si l'unité n'a pas bougé), ASSAULT (tir
autorisé après advance, et pour ces armes seulement), TORRENT (aucun jet de touche), SUSTAINED
HITS (touches additionnelles ≤ X par critique), LETHAL HITS (blessure automatique, pas de jet de
blessure), DEVASTATING WOUNDS (sauvegarde sautée), ANTI-X Y+ (seuil critique de blessure Y+ contre
le mot-clé X et lui seul), TWIN-LINKED (une relance de blessure, une seule), IGNORES COVER (le +1
de couvert 13.08 ne s'applique pas), EXTRA ATTACKS (l'arme s'ajoute, elle ne remplace pas),
PRECISION, BLAST, CLEAVE. PSYCHIC n'a aucun instant où elle « joue » (mot-clé d'INTERACTION) :
traite-la par un STATUT d'affichage distinct de NOT USED, jamais par un compteur.
Contrôle par arme aussi : portée, nombre d'attaques (RNG_NB / CC_NB), cohérence des profils de dés
avec config/unit_definitions.json.

DETTE À SOLDER EN PREMIER, elle est bon marché : six règles ont leur token dans step.log depuis le
2026-08-12 et AUCUN compteur d'usage, ni au tir ni en mêlée — ANTI-X, PSYCHIC, EXTRA_ATTACKS,
LETHAL_HITS, TORRENT, IGNORES_COVER. Le fait est écrit dans le code lui-même
(ai/analyzer_phases/fight_handler.py, docstring de la fonction de comptage d'usage) : « leur token
EST dans step.log […] c'est le compteur qui n'est pas encore écrit ». Elles ressortent « NOT USED »
alors qu'elles jouent.

Trois défauts distincts, tous vérifiés le 2026-08-16 :
- HAZARDOUS (24.15 / 06.03) n'a plus AUCUN lecteur : le commit 15d95480 a supprimé la branche de
  parsing, et grep -rn HAZARD sur les 8 modules de l'analyzer ne rend qu'UN commentaire
  (shoot_handler.py:269). La ligne « Unit N(c,r) SUFFERS X Mortal Wounds [HAZARDOUS] »
  (ai/step_logger.py) et le token « [HAZARDOUS] Roll:N » des lignes de tir sont écrits pour
  personne. ⚠️ Ne cherche pas la forme « was DESTROYED [HAZARDOUS] » : elle n'a jamais eu de
  producteur dans step.log (grep -c DESTROYED ai/step_logger.py → 0). Contrôle attendu : un jet de
  1 au test → la figurine tireuse subit les MW, et rien d'autre.
- ai/analyzer_phases/shoot_handler.py:605 juge DEVASTATING WOUNDS sur `wound_roll_value == 6` en
  dur : faux dès qu'une arme ANTI-X Y+ rend critique un Y+ < 6. Le seuil critique doit venir de
  l'arme.
- Le compteur d'usage CLOSE_QUARTERS de §1.8 mesure une adjacence ANCRE-à-ANCRE alors que les
  contrôles d'erreur voisins mesurent l'engagement par-figurine ; à x5 (ez=10) il est quasi
  toujours à 0.

VERROU + CONTRÔLE DE MASSE : cf. §4. Une partie des contrôles porte sur des tokens récents
(grammaire 3 et 4) : vérifie que le journal que tu mesures les porte, sinon tu mesureras un faux
négatif. Dis quelle version de grammaire porte ton journal.
Fin : commit, merge main, suppression worktree+branche, rapport de clôture T2.
```

### Lot 3 — règles spéciales d'unités

```
[MODE AGENT] Worktree : EnterWorktree name=analyzer-lot3-unites. Prérequis : lot 2 mergé.

Six règles de config/unit_rules.json sont réellement contrôlées (charge_after_advance,
charge_after_flee, shoot_after_advance, shoot_after_flee, move_after_shooting, reactive_move).
Traite les autres, en commençant par celles dont la donnée est DÉJÀ au journal — ne fais grossir
step.log qu'après avoir prouvé que l'info n'est pas re-dérivable ; c'est ce qui a clos l'entrée L2
de analyzer_couverture.md §7 sans ajouter un seul champ (le seuil de blessure attendu se recalcule
depuis [MODEL_TYPES:] + le registry + T{tour} EFFECTS:).

- Déjà loggable : charge_impact (la ligne IMPACTED porte seuil, jet et MW : vérifie 4+ → 1 MW et
  « cible dans l'engagement »), cp_gain_on_objective (CP1= / CP2= de l'instantané de tour ; gain
  GLOBAL, 1 CP max).
- Champs à ajouter puis contrôler : reroll_charge (la ligne CHARGED ne porte que le jet final),
  reroll_1_save_fight (aucun nom de capacité côté Save en mêlée → la cause est invisible),
  closest_target_penetration (l'AP de l'arme n'est pas loggué), feel_no_pain (jets absents),
  leader / support (lien leader ↔ bodyguard, 19.01 / 19.02).
- Deux clés de « T{tour} EFFECTS: » sont écrites et lues par personne : oath_wound=+X (la
  magnitude déclarée du +1 d'Oath — §1.9 lit le TOKEN, pas le chiffre) et waaagh_invul (le volet
  5++). Soit elles alimentent un contrôle, soit elles disparaissent.
- oath_of_moment : ce qui reste non contrôlé est que la CIBLE effectivement visée soit bien
  oath_target.

Piège à traiter explicitement : §1.7 affiche « 0 usage, verdict OK » pour beaucoup de règles. Pour
chacune, détermine si le 0 est VRAI (aucune unité du roster ne porte la règle → verdict HORS
ROSTER) ou si l'usage n'est pas loggué (→ JAMAIS EXERCÉE, en avertissement). Un 0 ambigu ne doit
plus produire de ✅ : c'est la règle déjà tenue par ai/analyzer_rules.py, applique-la ici.

Jumeau obligatoire pour tout champ ajouté : tir/mêlée, IA/PvP, moteur/replay/analyzer. Le jeu de
tokens de replayParser.ts est FERMÉ — un token inconnu y passe pour un nom de capacité. Grep et
rapporte, même 0 hit.
VERROU + CONTRÔLE DE MASSE : cf. §4.
Fin : commit, merge main, suppression worktree+branche, rapport de clôture T2.
```

### Lot 4 — structure de partie

```
[MODE AGENT] Worktree : EnterWorktree name=analyzer-lot4-structure. Parallélisable avec le lot 1,
JAMAIS avec un autre lot (cf. §3).

Quatre trous, vérifiés dans le code le 2026-08-16 :

1. ORDRE DES PHASES (07.02). ai/step_logger.py `log_phase_transition` n'a aucun appelant de
   production (grep sur tout le dépôt → 1 seul appelant, tests/unit/ai/test_step_logger.py:317) :
   la ligne « phase Start » n'existe dans aucun journal. Soit tu la câbles, soit tu reconstruis la
   séquence depuis les entêtes « T{tour} P{joueur} {PHASE} » des lignes d'action — choisis, et dis
   pourquoi. Contrôle attendu : command → move → shoot → charge → fight, alternance des joueurs,
   aucune phase sautée ni répétée.
2. FIN DE PARTIE. grep « turn == 5|max_turn|turn_limit » sur les 8 modules de l'analyzer → 0 hit.
   Rien ne vérifie que la partie s'arrête au tour prévu par le scénario, ni que la condition de
   victoire déclarée (elimination / objectives / value_tiebreaker) correspond à l'état final
   reconstruit.
3. OBJECTIFS (14.02 / 14.03). Les VP sont LUS tels quels dans « T{tour} OBJECTIVE CONTROL: VP1=…
   VP2=… ZONES=… » et jamais recoupés avec les positions (grep objective_control_contributions
   dans ai/analyzer*.py → 0 hit). Un recalcul naïf a déjà été supprimé comme faux par construction
   — lis le commentaire ai/analyzer.py:243 AVANT toute chose : somme d'OC par ANCRE, sans le
   battle-shock (01.07 / 02.02), et à chaque action alors que le contrôle est figé en fin de
   phase. Le moteur a depuis (commit d9502810) une source unique décomposée par escouade et
   per-figurine — objective_control_contributions / fold_control_contributions
   (engine/game_state.py), déjà consommées par ai/bot_doctrines.py. Aligne-toi sur CETTE fonction,
   n'en écris pas une copie. Il te manque encore l'OC par figurine et le drapeau `secured` dans
   ZONES= (analyzer_couverture.md §7, entrée L18) et le drapeau battle_shocked par unité (entrée
   L1) : ajoute-les. Si l'un des deux est hors de portée, dis lequel et contrôle ce qui reste —
   pas de contrôle à moitié faux.
4. DOUBLE-ACTIVATION DE TIR (10.02). ai/analyzer_core.py:1158 : `is_activation_marker` ne connaît
   que MOVE, DEPLOYED, CONSOLIDATED, ADVANCED, CHARGED, FAILED CHARGE, FLED. La phase SHOOT est
   testée ligne 1175 mais aucun marqueur ne peut la satisfaire : le contrôle est structurellement
   muet pour le tir. Trouve le marqueur d'activation de tir — les lignes SHOT sont par ATTAQUE, il
   y en a des dizaines ; c'est le même problème que FIGHT, résolu là-bas par la ligne CONSOLIDATED.
   ⚠️ Corrige AUSSI le commentaire de ai/analyzer_core.py:1167-1174 : il énonce comme une MESURE
   (« Mesuré sur le run de 600 épisodes du 2026-08-08 : 24 unités combattent DEUX fois ») un
   résultat réfuté depuis par le commentaire situé dix lignes plus bas DANS LE MÊME BLOC (55
   doublons sur 12 épisodes, ZÉRO vrai, 1427 phases instrumentées, 0 appel double de
   fight_phase_start) et par analyzer_couverture.md §1.6. Un lecteur du code croira le premier. Un
   commentaire rendu faux par une livraison ultérieure est une régression au même titre qu'un
   document. Ne reprends donc pas cet énoncé comme motivation du trou n°4 : le trou est l'absence
   de marqueur, pas une faute moteur connue.

VERROU + CONTRÔLE DE MASSE : cf. §4. Ici l'avant/après sur le MÊME journal est possible (aucun
token neuf) : rends-le.
Fin : commit, merge main, suppression worktree+branche, rapport de clôture T2.
```

### Lot 5 — migrer le corpus de règles en donnée

```
[MODE AGENT] Worktree : EnterWorktree name=analyzer-lot5-corpus. Prérequis : lots 2, 3, 4 mergés.

config/rules_corpus.json ne porte que 7 règles (03.01, 03.03, 09.05, 09.07, 20.04,
PROJET.reactive_move, PROJET.move_after_shooting), lues par ai/analyzer_rules.py et rendues à
chaque analyse sous « 1.1 COUVERTURE DES REGLES ». Toutes les autres vivent dans un tableau
Markdown tenu à la main (analyzer_couverture.md §3, §4, §5-bis), qui a déjà été faux plusieurs
fois — toujours dans le sens qui annonce une donnée disponible alors qu'elle ne l'est pas.
Recompte les lignes des trois matrices toi-même : le total de 214 date du 2026-08-10.

Généralise le mécanisme : une entrée par règle, portant son applicabilité (dérivée du journal —
action vue, phase jouée, règle portée par le roster), le ou les contrôles qui la mesurent, et son
état de vérifiabilité. Trois interdits par construction, déjà tenus par ai/analyzer_rules.py : une
règle applicable et JAMAIS exercée sort en ⚠️, une règle non vérifiable n'entre dans aucun ✅, une
règle hors roster ne pèse sur rien. Principe déjà écrit dans le code, à respecter :
l'OBSERVATION PRIME SUR LA PRÉDICTION — un exercice ou une faute sont des faits, le prédicat
d'applicabilité n'est qu'une déduction, il ne tranche que les cas où l'on n'a rien observé.

Ordre de découpe : les entrées PROUVABLES d'abord — les contrôles vivants, plus les règles dont
l'applicabilité se dérive du journal sans être écrite à la main (03.01 dès qu'il y a eu un
déplacement, 12.02 dès qu'il y a eu une phase de combat…). Les règles conditionnelles (transports,
aéronefs, stratagèmes) sortent en « non vérifiable » ASSUMÉ plutôt qu'en prédicat inventé : c'est
exactement ce qui a produit les lignes fausses de la matrice.
Invariant : un compteur d'erreur n'apparaît que dans UNE entrée, et la somme des erreurs des
règles d'une section égale le total de la section.
Le tableau migré est SUPPRIMÉ du Markdown au profit d'un renvoi vers la donnée : un document que
sa propre livraison rend faux est une régression (T2).

VERROU : un test qui vérifie que chaque compteur d'erreur du rapport appartient à exactement une
entrée du corpus, et qu'une entrée neuve sans compteur est refusée. Modèle :
tests/unit/ai/test_analyzer_error_totals.py, qui pose 1 dans CHAQUE compteur l'un après l'autre.
CONTRÔLE DE MASSE : sur un journal réel, vérifie qu'aucune règle ne sort « HORS ROSTER » alors
qu'un compteur d'erreur la concernant est non nul — c'est le défaut exact déjà rencontré (verdict
d'applicabilité testé AVANT les erreurs).
Fin : commit, merge main, suppression worktree+branche, rapport de clôture T2.
```

### Lot 6 — contre-audit final

```
[MODE AGENT] Worktree : EnterWorktree name=analyzer-lot6-audit. Prérequis : lots 1→5 mergés.

Relance python3 ai/analyzer.py sur un step.log POSTÉRIEUR au lot 5 — un journal antérieur ne porte
pas les champs ajoutés, et le mesurer produirait un faux négatif. Demande-le à l'utilisateur si tu
n'en as pas.

Pour chaque compteur encore non nul : verdict PROUVÉ (fichier:ligne + épisode témoin) — faux
positif résiduel, à corriger ici ; ou bug moteur, à LISTER pour l'utilisateur et PAS à corriger
dans ce lot. Sur les familles instruites jusqu'ici, la majorité étaient des défauts de mesure.

Verts vacants encore ouverts au 2026-08-16, à fermer ici :
- damage_exceeds_hp n'a AUCUN site d'incrémentation (déclaré ai/analyzer.py:1840, remis à None
  :1952, sommé dans le bucket 'damage' :1512, affiché :3827) : la ligne « Dmg > HP_CUR (overkill) »
  affiche 0 en permanence et contribue à un ✅. Donne-lui un producteur réel, ou supprime la clé —
  et si tu supprimes, dis par quoi l'invariant est tenu.
- has_line_of_sight (ancre-à-ancre, documentée comme inexacte) classe les WAIT en wait_with_los /
  wait_no_los ; ces métriques servent au pilotage de l'agent, donc l'approximation se corrige ou
  s'assume explicitement dans le rapport.
Ne cherche PAS « les tirs non évalués ne sont comptés par personne » : c'est fermé, le compteur
« portees non jugees (cible sans socle) » existe (ai/analyzer.py:3276).

Vérifie ensuite ligne par ligne la couverture rendue par le corpus (lot 5) : chaque règle non
couverte doit être NON-TESTABLE-OFFLINE avec sa justification, ou traitée. Mets à jour
analyzer_couverture.md — c'est le document de référence final, et il doit être vrai le jour de la
livraison.

Livrable : couverture chiffrée avant/après, liste des bugs moteur découverts (un prompt autonome
par bug, pour arbitrage utilisateur), preuves de verrou, et ce qui n'a PAS pu être vérifié.
Fin : commit, merge main, suppression worktree+branche, rapport de clôture T2.
```
