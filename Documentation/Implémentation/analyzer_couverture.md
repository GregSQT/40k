# Couverture analyzer — matrice RÈGLE → CONTRÔLE → CHAMPS step.log → STATUT

> Cartographie exhaustive, produite le 2026-08-08, remise à jour le 2026-08-09, **remise à jour
> le 2026-08-10** sur `main` après les 11 commits non-merge qui ont suivi (`c1487fcb` →
> `586c0553`). Document d'ENTRÉE des lots suivants : il dit ce qui est vérifié, ce qui ne l'est
> pas, et **pourquoi**. Aucun code n'a été modifié pour le produire.
>
> **Ce que la LIVRAISON du 2026-08-10 a ajouté** (elle suit la mise à jour ci-dessous, dans le
> même commit) — trois verts vacants traités : **V10** (09.07, le fall-back n'avait AUCUN
> contrôle → §1.1 #65-#67), **V14** (le plafond de tir passe par figurine, et le calcul est
> désormais mutualisé avec la mêlée) et **05.01** (verdict de touche, module neuf
> `ai/analyzer_hit.py` → §1.10). Un **quatrième défaut a été trouvé en livrant** : les totaux
> d'erreurs existaient en deux exemplaires divergents (**V16**, fermé), et un **cinquième** en
> instruisant celui-là : une clé de `stats` absente de sa propre structure plus un compteur
> mort (**V17**, fermé). Contrôles vivants **64 → 69**.
>
> **Ce que la mise à jour du 2026-08-10 a changé** — un MODULE neuf (`ai/analyzer_wound.py`) et
> ses 4 compteurs, qui ferment 05.02 côté tir ET mêlée (§1.9) ; deux **corrections de ma part**,
> l'une sur la double-activation FIGHT que j'avais annoncée fermée alors qu'elle était un faux
> positif (§5, V11), l'autre sur `oath_of_moment` que j'avais donné sans aucun contrôle (§5-bis) ;
> deux affirmations de format démenties par le code (`[HAZARDOUS]` n'atteignait pas step.log,
> `[MODEL_TYPES:]` rendait le type d'ESCOUADE) ; le modèle de dégâts §2.3 inversé (l'excès est
> reporté, pas perdu). **Les numéros de ligne ont été retirés** (cf. §2) — les
> fichiers ont beaucoup bougé (`analyzer.py` 3469 → 3690 l., `analyzer_core.py` 1265 → 1422).
>
> **Ce que la mise à jour du 2026-08-09 avait changé** — trois lignes de journal neuves
> (`AGENT_PLAYER=`, `T{tour} STATE:`, `T{tour} EFFECTS:`) et un segment neuf (`[MODEL_TYPES:]`) ;
> une section de rapport neuve (§2.8) et ses 3 compteurs.

> ⚠️ **CE QUE CE DOCUMENT PROUVE, ET CE QU'IL N'EST QU'UNE AFFIRMATION.** Les trois matrices
> (§3 règles PDF, §4 règles d'armes, §5-bis règles d'unité) sont tenues **À LA MAIN**, par lecture
> des PDF et du code. Rien ne les confronte automatiquement à l'état réel du dépôt, donc elles
> vieillissent en silence — et elles l'ont fait. Le 2026-08-10, **trois de leurs lignes étaient
> fausses**, toutes dans le sens qui coûte le plus cher, celui qui annonce une donnée disponible
> qui ne l'est pas : `phase Start` donnée « produite et non lue » alors que sa fonction d'écriture
> n'a **aucun appelant** ; `[FIGHT_SUBPHASE:]` donné exploitable alors qu'il vaut `fight` sur
> **192 lignes de combat sur 192** ; 12.06 donné ABSENT-LOGGABLE sur la foi du précédent. Les
> trois ont été révisées, mais le mode de défaillance, lui, n'est pas corrigé : il tient à la
> méthode.
>
> **Première tranche livrée le 2026-08-10 : §1.1 est passée en DONNÉE** — `config/rules_corpus.json`,
> lu par `ai/analyzer_rules.py`, rendu à chaque analyse sous « 1.1 COUVERTURE DES REGLES ». Pour
> ces 6 règles, le document n'est plus la source : il commente une donnée que le rapport
> confronte au journal. Trois verdicts — **HORS ROSTER** (aucune unité jouée ne porte la règle),
> **JAMAIS EXERCÉE** (applicable, et aucun contrôle n'a rien eu à juger : c'est le signal 17.01),
> **ERREURS**.
>
> ⚠️ **La première version de ce paragraphe les disait « impossibles à falsifier ». C'était faux,
> et la revue du jour l'a démontré cinq fois** — verdict d'applicabilité testé AVANT les erreurs
> (une règle fautive sortait « hors roster »), exercice noté sur un seul des trois sites de
> `wall_collisions` (fausse alerte « jamais exercée » sur un journal de fall-back), notes posées
> devant les gardes qui conditionnent les contrôles. Corrigé le même jour, et la règle qui le
> rend structurel est écrite dans le code : **l'OBSERVATION PRIME SUR LA PRÉDICTION**. Un exercice
> ou une faute sont des faits ; le prédicat d'applicabilité n'est qu'une déduction, et il ne
> tranche donc que les cas où l'on n'a rien observé. Le rapport ne peut plus contredire sa propre
> mesure.
>
> ✅ **LIVRÉ le 2026-08-17 (SUMMARY §1.1 + corpus §1.2–§2.8).** La ligne 1.1 du SUMMARY porte
> désormais le signal de couverture : `⚠️ 1.1 Erreurs en phase de move : 0 (⚠️ N règles jamais
> exercées)` quand N > 0, `❌` si des erreurs existent. L'icône n'est plus forcément `✅` quand le
> contrôle n'a rien regardé.
>
> `SECTION_TO_BUCKET` étendu à 7 sections : §1.1 (move), §1.2 (shooting), §1.3 (charge), §1.4
> (fight), §2.1 (dead_units), §2.3 (damage), §2.8 (state_resync). 44 nouvelles entrées corpus. Un
> nouveau chemin `"#"` dans `_counter_value` couvre les scalaires sans split joueur (`state_resync`).
> La somme par règle DOIT égaler le bucket correspondant d'`error_totals` pour chaque section
> couverte — sinon le rapport imprime l'écart.
>
> **Deuxième dette évaluée et FERMÉE sans code.** La déduplication corpus/`error_totals`
> affaiblirait l'architecture : si `error_totals["move"]` devenait `_section_error_sum(stats, "1.1")`,
> l'invariant du test `test_the_per_rule_sum_matches_the_section_total` deviendrait tautologique.
> La duplication est voulue : `error_totals` est la source de vérité, `_section_error_sum` en est
> le vérificateur. Liés par un test, pas par construction.
>
> Verrous : `test_summary_signals_never_exercised_rules` · `test_section_12_corpus_sum_matches_bucket`
> (×6 sections) · `test_section_12_gap_detected` (×6) — 24 tests verts.
>
> Sections non couvrables : §1.5–§1.8 (listes dynamiques ou compteurs dérivés), §2.2 (dérivé de
> §1.2), §2.4–§2.7 (dicts dynamiques). Ces sections n'ont pas de bucket fixe dans `error_totals`
> dont la somme serait vérifiable sans refonte de l'infrastructure.

## 0. Méthode et sources

| Source | Ce qui en a été tiré |
|---|---|
| `Documentation/40k_rules/*.pdf` (25 fichiers, texte intégral extrait) | 156 règles numérotées `NN.MM` |
| `config/weapon_rules.json` | 23 règles d'armes |
| `config/rules_corpus.json` | 6 règles de §1.1 décrites en DONNÉE (applicabilité, contrôles, vérifiabilité) — lu par `ai/analyzer_rules.py` |
| `config/unit_rules.json` | 35 règles spéciales d'unité |
| `ai/analyzer.py` + `analyzer_core.py` + `analyzer_config.py` + `analyzer_perfig.py` + `analyzer_state.py` + `analyzer_wound.py` + `analyzer_hit.py` + **`analyzer_rules.py`** + `analyzer_phases/*` — **10 298 l. au total, 8 fichiers + 5 handlers** (mesuré le 2026-08-10) | 70 contrôles vivants, 1 mort, 8 supprimés documentés |
| `ai/step_logger.py` (1186 l.), `engine/w40k_core.py` (`_STEP_LOG_TYPE_MAP`, `_build_step_log_details`, `_build_shot_details`, `_models_segment_for_unit`, `_run_rules_for_step_log`, `_log_effects_snapshot_if_changed`), `engine/action_log_utils.py` | format réel de `step.log`, champ par champ, type d'action par type d'action |

### Légende des STATUTS

| Statut | Définition stricte |
|---|---|
| **COUVERT** | Un contrôle existe, il regarde la bonne grandeur (par-figurine, métrique du run), et tous les champs nécessaires sont journalisés. |
| **PARTIEL** | Un contrôle existe mais ne couvre qu'une partie de la règle, **ou** regarde la mauvaise chose (ancre au lieu du socle, hex au lieu d'euclidien, adjacence au lieu de zone d'engagement). Le trou est nommé. |
| **ABSENT-LOGGABLE** | `step.log` porte déjà toute l'information ; il ne manque que le contrôle. |
| **ABSENT-LOG-MANQUANT** | Le contrôle est impossible en l'état : les champs à ajouter au StepLogger sont nommés. |
| **NON-TESTABLE-OFFLINE** | Structurellement hors de portée d'un contrôle post-hoc sur journal (définition, donnée de registre, terrain absent du log, jet non reproductible, ou contrôle qui serait tautologique). |

#### Statuts propres à la table §1.8 (weapon rule usage)

| Statut §1.8 | Définition |
|---|---|
| **OK** | Au moins un usage (P1 ou P2 > 0) et la paire (règle, arme) est déclarée dans l'armurerie. |
| **INVALID** | La paire (règle, arme) a été observée dans `step.log` mais l'armurerie ne la déclare pas. |
| **NOT USED** | La paire est attendue selon l'armurerie, l'arme a été tirée/utilisée, mais le token de la règle n'a jamais été compté. Signal d'implémentation manquante côté compteur. |
| **N/A — KEYWORD** | La règle est un **mot-clé d'interaction**, pas un effet discret à compter. Il n'y a structurellement rien à incrémenter, et 0 ne signifie donc pas « jamais exercée ». Appliqué à **PSYCHIC (24.29)** : le token est posé sur chaque attaque de l'arme, mais son effet (marquer l'attaque comme « psychic attack » pour interaction avec les règles anti-psychic) ne correspond à aucun moment précis dans le journal. Ces paires ne déclenchent ni avertissement `⚠️` ni contribution au compteur « Not used » du tableau. |

**Vert vacant** : un contrôle qui existe mais mesure la mauvaise chose est classé **PARTIEL**, jamais COUVERT.
La §5 liste les verts vacants trouvés.

---

## 1. Format réel de `step.log`

### 1.1 Entête d'épisode (`StepLogger.log_episode_start`, `ai/step_logger.py`)

```
[hh:mm:ss] === EPISODE N START ===
[hh:mm:ss] Scenario: <texte>                       (optionnel)
[hh:mm:ss] Scenario file: <chemin relatif>          (optionnel)
[hh:mm:ss] Rosters: scale=<n> AGENT_PLAYER=<1|2> AGENT=<id> (<ref>) OPPONENT=<id> (<ref>)  (optionnel)
[hh:mm:ss] Opponent: <Nom>Bot                       (optionnel)
[hh:mm:ss] Walls: (c,r);(c,r);…      |  Walls: none
[hh:mm:ss] Objectives: <nom>:(c,r);(c,r)|<nom>:…   |  Objectives: none
[hh:mm:ss] Rules: {"primary_objective":…}
[hh:mm:ss] Board: cols=<n> rows=<n> inches_to_subhex=<n> hex_radius=<n> margin=<n>
[hh:mm:ss] Run rules: engagement_zone_subhex=… engagement_zone_vertical_inches=…
           metric.engagement=… metric.ranged=… move.thru_ez=… move.thru_enemy=… move.thru_friendly=…
[hh:mm:ss] Log grammar: <n>
[hh:mm:ss] Unit <id> (<unitType>) [<DISPLAY_NAME>] P<n>: Starting position (c,r), HP_MAX=<n>
           base=<shape>/<size> [MODELS: <mid>@(c,r,z<h>) …] [MODEL_TYPES: <mid>=<UnitType> …]
[hh:mm:ss] === ACTIONS START ===
```

`Log grammar:` (2026-08-12) déclare ce que le journal **garantit porter** — `1` = grammaire
antérieure, `2` = `[ALLOC_MODEL:]` sur toute attaque allouée. Absente ⇒ 1. Elle existe pour une
seule raison : sans elle, un lecteur qui ne trouve pas un segment ne peut pas distinguer « ce
journal ne le porte pas » de « le producteur est en panne », et n'a d'autre choix que de retomber
en silence sur une reconstruction approximative. Avec elle, l'absence LÈVE
(`analyzer_core._alloc_model_from_line`). Source unique : `ai/step_logger.LOG_GRAMMAR_VERSION`.

`Board:` et `Run rules:` sont **exigés** par l'analyzer (`analyzer_config.get_run_inches_to_subhex:68` /
`get_run_rule:44` lèvent sinon) : ils figent l'échelle et les règles du run analysé, jamais celles du
`config/` du jour. **`AGENT_PLAYER=` l'est aussi** depuis le 2026-08-09 (`analyzer_core.py`
puis levée en fin d'épisode, `:656`) : `controlled_player_mode` accepte `p2` et `random`, et supposer
« agent == P1 » attribuait les victoires de l'agent au bot dans 30 % des épisodes.

`[MODEL_TYPES:]` donne la **datasheet par figurine** : une escouade n'est pas homogène (règle 19,
sergents, armes spéciales), et tout plafond calculé par socle à partir du type d'ESCOUADE est faux.
C'est ce segment qui rend le plafond d'attaques de §1.4 juste (`fight_handler.py`), la F par
figurine de §1.9 (`analyzer_wound.py`) et les PV par figurine de §2.3 (`analyzer_core.py`).

> ⚠️ **Correction du 2026-08-10.** La version du 2026-08-09 décrivait `[MODEL_TYPES:]` comme livré
> et juste. Il ne l'était pas : `baf4859a` (« [MODEL_TYPES:] rendait le type d'ESCOUADE pour chaque
> figurine ») montre que le segment était émis en répétant la datasheet de l'escouade sur chaque
> `mid`. Tout ce qui en dépend — plafond de mêlée par figurine en tête — n'était donc réellement
> par-figurine qu'à partir de ce commit. L'émetteur est `w40k_core._model_types_segment_for_unit`
> (`:5344-5386`).

### 1.2 Ligne d'action (`log_action`, `ai/step_logger.py`)

```
[hh:mm:ss] E<ep> T<turn> P<player> <PHASE> : <message> [<MODELS:…>] [<TARGET_MODELS:…>] [<SHOOTER_MODELS:…>] [<ALLOC_MODEL:…>] [SUCCESS|FAILED]
```

Segments per-figurine (`engine/action_log_utils.py`) :

| Segment | Contenu | Consommateur |
|---|---|---|
| `[MODELS: <mid>@(c,r,z<h>) …]` | socles VIVANTS de l'unité qui agit ; `mid = <unit_id>#<index>` ; `z` = hauteur de PLANCHER en pouces | analyzer (source de vérité par-socle) + replay |
| `[TARGET_MODELS: …]` | survivants de la CIBLE après pertes, uniquement sur le DERNIER jet visant cette cible | replay + **état per-figurine** (`analyzer_core`, depuis le 2026-08-11). ⚠️ **JAMAIS un verdict de distance** : `shoot_handler` (portée) l'a lu jusqu'au 2026-08-12 et rendait 31 faux « hors portée » sur 600 épisodes — la figurine visée, la plus proche, disparaît du segment quand elle meurt du tir |
| `[SHOOTER_MODELS: <mid> …]` | figurines ayant EFFECTIVEMENT tiré/frappé | replay seul |
| `[ALLOC_MODEL: <mid>]` | figurine de la CIBLE à qui CETTE attaque a été allouée (05, « Allocate Attack ») — une ligne = un jet, donc jamais une liste. Émise sur toute attaque parvenue à l'allocation, y compris sauvegarde réussie ; absente des lignes `Save [NOT ALLOCATED]`, de `IMPACTED` (charge : dégâts appliqués à l'ESCOUADE, aucune figurine allouée côté moteur) et des lignes `[HAZARDOUS]` | analyzer : PV par socle et retrait du socle mort, **nommément** (depuis le 2026-08-12). ⚠️ Avant ce segment, l'analyzer DEVINAIT : socle touché déduit d'un tri CHARACTER/non-CHARACTER quand le moteur applique `_select_allocation_model` (200 PV par socle faux sur 173 129), et TOUS les socles de l'escouade oubliés à chaque mort (2 342 fenêtres, p90 119 lignes, 19 % débordant sur le tour suivant) |

### 1.3 Messages par type d'action

Seuls ces types atteignent `step.log` (`_STEP_LOG_TYPE_MAP` + `_STEP_LOG_MOVE_TYPE_MAP` +
l'écriture directe de `rule_choice`) :

| `action_type` | Message | Champs porteurs de règle |
|---|---|---|
| `move` | `Unit N(c,r) MOVED [FLY] from (a,b) to (c,d)[R:±x]` | `[FLY]` (21.03), positions, `[MODELS:]` |
| `advance` | `Unit N(c,r) ADVANCED [FLY] from … to … [Roll: N]` | jet D6 (en **pouces**), `[FLY]` |
| `flee` | `Unit N(c,r) FLED [FLY] from … to …` | `[FLY]`, positions |
| `move_after_shooting` | `Unit N(c,r) MOVED AFTER SHOOTING [<CAPACITÉ>] from … to …` | nom de la capacité (obligatoire) |
| `reactive_move` | `Unit N(c,r) REACTIVE MOVED [<CAPACITÉ>] from … to … [Roll: N] - trigger: Unit M->(c,r)` | jet, déclencheur ; **pas de `[MODELS:]` d'arrivée** |
| `deploy_unit` | `Unit N(c,r) DEPLOYED from (-1,-1) to (c,r)` | sentinelle hors-table `(-1,-1)` (20.01) |
| `shoot` | `Unit N(c,r) SHOT [ASSAULT] [CLOSE-QUARTERS] [RAPID FIRE:X] [MELTA:X] [BLAST:X] [EXTRA ATTACKS] [PRECISION] Unit M(c,r) with [<arme>] - Hit R(T+ ou base+->eff+) [HEAVY\|COVER] [TORRENT] [IGNORES COVER] [PSYCHIC] [REROLLED:n] [SUSTAINED HITS] [<CAPACITÉ>] - Wound R(T+) [LETHAL HITS] [ANTI-<KW>:Y+] [<CAPACITÉ>] [REROLLED:n] - Save R(T+) [REROLLED:n] [<CAPACITÉ>] - Dmg:NHP [HAZARDOUS] Roll:N` ; ou `Save [DEVASTATING WOUNDS]` | jets, seuils, tokens de règle |
| `hazardous` | `Unit N(c,r) SUFFERS X Mortal Wounds [HAZARDOUS]` — forme UNIQUE | MW infligées + vérif présence arme HAZARDOUS en armurerie — **COUVERT (2026-08-17)** |
| `charge` | `Unit N(c,r) CHARGED [<CAPACITÉ>] [FLY] Unit M(c,r) from … to … [Roll: N]` | jet 2D6 (pouces), `[FLY]`, **une seule** cible |
| `charge_fail` | `Unit N(c,r) FAILED CHARGE to unit M(c,r) [Roll: N]` | jet |
| `charge_impact` | `Unit N(c,r) IMPACTED [<CAPACITÉ>] Unit M(c,r) - Hit:T+:R(HIT\|FAIL) Wound:AUTO Save:NONE[MW] Dmg:NHP` | seuil, jet, MW |
| `combat` | `Unit N(c,r) FOUGHT [WAAAGH!] [CLEAVE:X] Unit M(c,r) with [<arme>] - Hit R(T+) [SUSTAINED HITS] [<CAPACITÉ>] [REROLLED:n] - Wound … - Save R(T+) \| Save [DEVASTATING WOUNDS] \| Save [NOT ALLOCATED] - Dmg:NHP [FIGHT_SUBPHASE:<x>]` | idem tir + sous-phase de combat + `[WAAAGH!]` (confort de lecture — la **donnée** est dans `T{tour} EFFECTS:`) |
| `pile_in` / `consolidation` | `Unit N(c,r) PILED IN\|CONSOLIDATED from … to …` | positions, `[MODELS:]` |
| `wait` | `Unit N(c,r) WAIT` | — |
| `rule_choice` | `Unit N(c,r) chose [<NOM DE RÈGLE>]` | nom d'affichage |

**Formateurs sans producteur** (code mort côté moteur) : `skip`, `shoot_summary`, `combat_summary`.
Conséquence directe : le contrôle §2.1 « Dead unit skipping » et tout `handle_skip`
(`shoot_handler.py`) sont inatteignables. Vérifié le 2026-08-10 sur
`w40k_core._STEP_LOG_TYPE_MAP` (`:5211-5238`) : `skip` n'y figure pas.

**Deux rectifications de format (2026-08-10), toutes deux prouvées par un commit du moteur :**

- **La ligne `hazardous` n'atteignait pas step.log.** Le tableau ci-dessus la décrivait comme
  produite dès le 2026-08-08 ; `d891fff1` (« la ligne [HAZARDOUS] n'atteignait jamais step.log »)
  établit qu'il manquait l'entrée `"hazard": "hazardous"` dans `_STEP_LOG_TYPE_MAP`. Elle y est
  aujourd'hui (`w40k_core.py`). Conséquence sur §3 : le statut **ABSENT-LOGGABLE de 06.03
  n'est vrai que depuis ce commit** — avant, c'était ABSENT-LOG-MANQUANT.
- **Le `X` de `[RAPID FIRE:X]` a changé de sens** (`69996bf1`). Il porte désormais le **X déclaré
  par l'arme**, plus le cumul de dés ajoutés : un shoota `[RAPID FIRE 1]` tiré par 10 figurines
  écrivait `[RAPID FIRE:10]`. Le contrôle #41, qui compare le marqueur à l'armurerie, ne pouvait
  donc *que* rendre `parse_error` sur toute escouade de plus d'une figurine. Chaîne :
  `additive_rules_applied` (`shared_utils.py`) → `rapidFireApplied` (`:8310`) →
  `w40k_core.py` → `step_logger.py`.

✅ **Le pont est posé (2026-08-12, lot A).** Cette section décrivait six tokens que le moteur
savait produire (`shared_utils.weapon_rule_log_tokens`) mais ne posait que sur la ligne de
SYNTHÈSE d'escouade du **Game Log PvP** (`_emit_squad_shoot_log`) — donc invisibles de
l'analyzer et du replay. `[EXTRA ATTACKS]`, `[TORRENT]`, `[IGNORES COVER]`, `[PSYCHIC]`,
`[ANTI-<KW>:Y+]` et `[LETHAL HITS]` atteignent désormais `step.log`, **au tir comme en mêlée**
(même émetteur, même formateur). Les statuts §3 de 24.03/11/18/23/29/37 passent d'ABSENT-LOG-MANQUANT
à **ABSENT-LOGGABLE** : le contrôle reste à écrire, mais il est désormais possible.

Trois chemins, selon où vit le fait :
- **par ATTAQUE**, via `_SHOT_RECORD_FIELD_MAP` — `autoHit` → `[TORRENT]`, `lethalHit` →
  `[LETHAL HITS]`. Ce sont les deux seules règles du lot dont l'application varie d'un jet à
  l'autre du même groupe (24.23 ne joue que sur les touches critiques) ;
- **par GROUPE**, via des clés du log d'action lues par `_build_shot_details` —
  `ignoresCoverApplied`, `extraAttacksApplied`, `psychicApplied`, `antiKeyword` + `antiThreshold` ;
- le **formatage** vit dans `ai/step_logger.py` seul (`_HIT_SEGMENT_RULE_TOKENS`,
  `_WOUND_SEGMENT_RULE_TOKENS`, `_LINE_TAG_RULE_TOKENS`, `_anti_rule_token`), en tables partagées
  par les deux branches `SHOT` et `FOUGHT` — un token écrit d'un seul côté du miroir est
  structurellement impossible.

⚠️ **`[ANTI-<KW>:Y+]` porte le seuil DÉCLARÉ par l'arme**, pas le `crit_wound_on` que le moteur
en tire (le clamp de 05.02). Les deux coïncident pour tout Y+ jouable ; la distinction n'est pas
cosmétique : écrire le chiffre du moteur ferait vérifier le moteur avec sa propre réponse, et le
seul recoupement qui vaille — le token contre l'armurerie — deviendrait un vert vacant. La ligne
de synthèse du Game Log PvP a été alignée sur cette grammaire dans la même livraison ; c'est
d'ailleurs celle que son propre docstring annonçait (« TOUJOURS le paramètre X que l'ARME DÉCLARE »).

**`INDIRECT_FIRE` reste hors du journal, et ce n'est pas un oubli** : la règle n'est pas
implémentée dans le moteur. Son token annoncerait un effet qui n'a pas lieu — le pont ne peut
pas précéder la règle.

✅ **`[MELTA:X]` et `[PRECISION]` sont sortis de cette liste le 2026-08-11** : le pont a été posé
(`meltaApplied` / `precisionApplied` dans le log de groupe → `_build_shot_details` →
`StepLogger` → analyzer). Les deux étaient dans le cas décrit ci-dessus — appliqués par le moteur,
écrits dans la seule ligne que rien ne relit — et §1.8 les déclarait « NOT USED » alors que
`Multi-Melta` était tiré 708 fois sur le run du 2026-08-11. **C'est le mode d'échec de cette liste
entière** : un token qui n'atteint pas `step.log` ne rend pas la règle invisible, il la rend
**FAUSSEMENT MORTE**, ce qui est pire — le rapport affirme alors que le moteur ne l'applique pas.

### 1.4 Lignes hors action

| Ligne | Producteur | Lue par l'analyzer ? |
|---|---|---|
| `[ts] T<n> P<n> <PHASE> phase Start` | `log_phase_transition` (`step_logger.py`) | **Non** — jamais parsée (grep `"phase Start"` sur les 7 fichiers analyzer → 0 hit, 2026-08-10) |
| `[ts] T<n> OBJECTIVE CONTROL: VP1= VP2= CP1= CP2= ZONES=<nom>:Ctrl=…` | `log_objective_control_snapshot` (`step_logger.py`) | Oui — VP uniquement |
| `[ts] T<n> STATE: <uid>[<mid>@(c,r,z<h>):<pv> …] …` | `log_state_snapshot` (`step_logger.py`) | **Oui** — `_apply_state_snapshot` (`analyzer_core.py`) : compte l'écart, PUIS recale |
| `[ts] T<n> EFFECTS: P1 <clé>=<val> … \| P2 none` | `log_effects_snapshot` (`step_logger.py`) | Partiellement — `_parse_effects_snapshot` (`analyzer_core.py`) lit tout ; **quatre des six** clés sont consommées depuis le 2026-08-10 (cf. §5, V15) |
| `[ts] EPISODE END: Winner=, Method=, Actions=, Steps=, Total=, Duration=…s` | `log_episode_end` | Oui |
| `[ts] OBJECTIVE CONTROL: Obj<id>:P1_OC=,P2_OC=,Ctrl=` (récap de fin) | `log_episode_end` | Non (motif distinct, non matché) |

Clés émises par `T{tour} EFFECTS:` (`w40k_core._log_effects_snapshot_if_changed:7217`, valeurs
prises aux constantes du moteur — le journal dit ce qui a été appliqué, il ne le redécrit pas) :
`waaagh=on`, `waaagh_melee_str=+X`, `waaagh_melee_atk=+X`, `waaagh_invul=<n>`,
`oath_target=<unit_id>`, `oath_wound=+X`.

**Quatre sont lues** au 2026-08-10, contre une seule au 2026-08-09 :

| Clé | Consommateur | Ce qu'elle alimente |
|---|---|---|
| `waaagh_melee_atk` | `fight_handler.py` (`_cc_cap_for_line`) | plafond d'attaques de mêlée (#28) |
| `waaagh_melee_str` | `analyzer_wound.py` (via `_effect_bonus:68`) | seuil de blessure de mêlée (#63) |
| `waaagh` | `analyzer_core._FACTION_ABILITY_KEYS:127` → `_count_faction_activations:141` | compteur d'activations §1.7 |
| `oath_target` | idem | compteur d'activations §1.7 (`oath_of_moment`) |

**Une reste inexploitée** : `waaagh_invul` (5++). `oath_wound` est désormais lue
par `analyzer_wound.py` (`_effect_bonus`) pour alimenter la magnitude du bonus de blessure
Oath : le TOKEN `[OATH OF MOMENT]` gate l'application, la CLÉ `oath_wound` en fixe la magnitude
(fallback 1 pour les journaux antérieurs au 2026-08-10) — **COUVERT (2026-08-17)**.

---

## 2. Inventaire des contrôles analyzer (70 vivants)

> **PLUS AUCUN NUMÉRO DE LIGNE, et c'est délibéré (2026-08-10).** Ce document en portait 147 ;
> ils avaient été re-dérivés par grep le matin même, et un contrôle automatique le soir en a
> trouvé **76 prouvés faux et 40 invérifiables** — après une seule journée de livraisons. Un
> numéro de ligne a une durée de vie de vingt-quatre heures dans ce dépôt : c'est mesuré, pas
> supposé. Les re-dériver aurait produit un document exact le soir, faux le lendemain, et
> horodaté de façon à inviter à s'y fier. Chaque renvoi porte donc désormais le **fichier et le
> nom du symbole** : un nom se grep, pointe l'endroit exact, et ne rouille pas.

### §1.1 MOVEMENT ERRORS

| # | Compteur | Site | Ce qu'il regarde VRAIMENT |
|---|---|---|---|
| 1 | `wall_collisions` | **TROIS sites** : `move_handler.py` (move normal ET fall-back), `shoot_handler.py` (advance) | destination d'ANCRE ∈ `wall_hexes`. Les trois notent l'exercice de 03.01 depuis le 2026-08-10 — un seul le faisait, d'où une fausse alerte « jamais exercée » sur un journal de fall-back |
| 2 | `move_to_adjacent_enemy` | `move_handler.py` | zone d'engagement per-figurine, socles d'ARRIVÉE + hauteurs d'arrivée |
| 3 | `move_adjacent_before_non_flee` | `move_handler.py` | zone d'engagement per-figurine, socles de DÉPART (survivants) |
| 4 | `move_distance_over_limit['move']` | `move_handler.py` | `_per_model_move_violation` : BFS par socle, budget `M` (−2" si `[FLY]`) |
| 5 | `move_after_shooting_distance_over_limit` | `move_handler.py` | idem, budget = `rule_args.distance` × échelle |
| 6 | `reactive_move_stats.abnormal` | `analyzer_core.py` | phase ∉ {MOVE,SHOOT} **ou** `calculate_hex_distance` ANCRE > jet×échelle |
| 7 | `reactive_move_checks.to_adjacent_enemy` | `analyzer_core.py` | engagement, sujet mesuré à l'ANCRE (pas de `[MODELS:]` réactif, cf. commentaire `:1302-1308`) |
| 8 | `reactive_move_checks.into_wall` | `analyzer_core.py` | ancre ∈ `wall_hexes` |
| 9 | `reactive_move_checks.distance_over_roll` | `analyzer_core.py` | `_per_model_move_violation`, budget jet×échelle |
| 65 | `move_distance_over_limit['flee']` | `move_handler.py` (bloc `_check_fall_back_move`, `:81`) | **09.07 « MAXIMUM DISTANCE: your unit's M »** — BFS par socle, budget `M` (−2" si `[FLY]`), figurines ennemies TRAVERSABLES (cf. ci-dessous) |
| 66 | `flee_from_unengaged` | `move_handler.py` | **09.07 « ELIGIBLE IF: your unit is engaged »** — engagement per-fig aux socles de DÉPART. Négatif exact de #3 : l'un punit le move normal parti engagé, l'autre le fall-back parti libre |
| 67 | `flee_still_engaged` | `move_handler.py` | **09.07 « AFTER MOVING: your unit must be unengaged »** — engagement per-fig aux socles et hauteurs d'ARRIVÉE |
| **68** | `squad_coherency_violations` | `analyzer_core._check_line_coherency` | **03.03** — cohérence à la mise en place et à la fin de TOUT déplacement, une faute par formation. Mesure par socle (empreinte à empreinte) ; VERDICT délégué à `_coherency_verdict` du moteur, la 1re puce étant une CONNEXITÉ et non « au moins un voisin ». Seuils lus dans l'entête `Run rules:` (`cohesion.*`). Volet vertical NON couvert. La purge End of Turn est JOURNALISÉE depuis le 2026-08-12 (`COHERENCY REMOVED`) : ses retraits sont comptés par `coherency_removals` (compteur d'EXERCICE, pas d'erreur) et purgent les socles retirés de l'état reconstruit |
| **69** | `fight_double_pile_in` | `analyzer_core` (bloc `PILED IN`) | **12.02** — un seul pile-in par unité et par étape. Ensemble SÉPARÉ de celui de la double-activation §1.6, dont le marqueur est `CONSOLIDATED` : pile-in et consolidation sont deux étapes distinctes qu'une unité fait légalement toutes les deux |

**Compteurs d'EXERCICE (2026-08-10).** Les contrôles de §1.1 alimentent en plus `rule_usage`
(`ai/analyzer_rules.py`), qui compte les OCCASIONS JUGÉES par règle — pas les lignes vues. C'est
ce qui distingue « le contrôle n'a rien trouvé » de « le contrôle n'a rien regardé », et ce qui
permet le verdict `JAMAIS EXERCÉE`. Ces compteurs ne sont PAS des contrôles : ils ne rendent aucun
verdict de conformité et n'entrent dans aucun total d'erreurs.

**Vert vacant V10 fermé le 2026-08-10.** Le fall-back était le SEUL des six déplacements sans
aucun contrôle de budget ni de chemin : `_handle_fled` ne regardait que la collision d'ancre et
le mur d'arrivée. Les trois compteurs entrent dans le total MOVE (`analyzer.error_totals:1067`)
— un compteur hors de tout total est aussi silencieux qu'un compteur jamais incrémenté (c'est V1
pris par l'autre bout). Verrou : `tests/unit/ai/test_analyzer_fall_back_move.py`, 6 tests, dont
la prémisse géométrique et l'assertion sur la ligne RENDUE du SUMMARY.

**Ce qui reste hors de portée, et pourquoi ce n'est pas un trou.** 09.07 « WHILE MOVING ▪
Desperate Escape: Each model that is moved can be moved through enemy models » : des DEUX modes
de fall-back, un seul traverse les ennemis, et le mode choisi n'est PAS journalisé (§7 L11).
Bloquer sur les ennemis rendrait « chemin impossible » sur toute retraite désespérée légale. Le
BFS les laisse donc traversables (`_build_move_bfs_blockers(force_thru_enemy=True)`), ce qui ne
perd que la retraite ORDONNÉE ayant traversé un ennemi ; le BUDGET, commun aux deux modes, reste
pleinement contrôlé. Le jour où `[MOVE_TYPE:fall_back]` portera son mode, ce paramètre doit
disparaître. Les volets « AFTER MOVING: not eligible to shoot / declare a charge » sont déjà
portés par #14 et #24 ; « start an action » exige les lignes d'action (16.01), absentes.

### §1.2 SHOOTING ERRORS

| # | Compteur | Site | Ce qu'il regarde VRAIMENT |
|---|---|---|---|
| 10 | `shoot_invalid.out_of_range` | `shoot_handler.py` | `squads_min_ranged_distance` socle→socle, métrique `metric.ranged` du run, cap **non tronqué** depuis le 2026-08-09 ; cible lue dans `positions_by_model` — l'état d'AVANT l'action, **jamais** `[TARGET_MODELS:]` (2026-08-12) ; **aucun verdict** si la cible n'a pas de socles connus — et ce renoncement est COMPTÉ depuis le 2026-08-12 (`shoot_range_unverifiable`, affiché en §1.2), plus silencieux comme avant |
| 11 | `shoot_invalid.engaged_non_close_quarters` / `engaged_shot_with_non_close_quarters_weapon` | `:670,671` | tireur engagé (per-fig) ∧ arme non-CQ ∧ non-M/V |
| 12 | `shoot_over_rng_nb` | `shoot_handler.py` (`per_model_attack_cap`) | compteur de séquence vs plafond **PAR FIGURINE depuis le 2026-08-10** (V14 fermé) : `[SHOOTER_MODELS:]` donne les socles qui ont tiré, `[MODEL_TYPES:]` la datasheet de chacun. Le X de `[RAPID FIRE]` suit la même résolution — c'est un attribut d'ARME. Repli explicite sur `NB d'escouade × effectif` sans ces segments. `[SUSTAINED HITS]` exclu. ⚠️ **Le GROUPE de tireurs est entré dans la clé du compteur le 2026-08-11** : il détermine le plafond de la ligne, et sans lui la somme de deux groupes d'une même escouade était opposée au plafond d'un seul — **320 faux positifs sur 23 169 tirs**. `fight_handler` avait fermé ce défaut de son côté sans que le tir suive |
| 13 | `shoot_combi_profile_conflicts` | `:335` | 2 profils d'un même `COMBI_WEAPON` dans le même tour |
| 14 | `shoot_after_flee` | `:163` | `units_fled` ∧ pas de règle `shoot_after_flee` |
| 15 | `shoot_at_friendly` | `:186` | `unit_player[cible] == unit_player[tireur]` |
| 16 | `shoot_at_engaged_enemy` | `:617` | cible engagée (per-fig) ∧ arme non-CQ ∧ ¬exemption 17.03 ∧ ¬tireur engagé avec elle |
| 17 | `close_quarters_shot_at_unengaged_target` | `:659` | tireur engagé non-M/V visant une unité avec laquelle il n'est PAS engagé (10.06) — **passé à l'engagement per-figurine le 2026-08-10** (`c1487fcb`), il mesurait `calculate_hex_distance(ancre,ancre)==1` : 144 faux positifs sur un run de 600 épisodes. **Puis à l'engagement d'AVANT les pertes le 2026-08-12** : la mesure se faisait après les dégâts de la ligne jugée, une cible tuée par le tir disparaissait de l'énumération (1 faux positif de plus, E422). Les cartes viennent désormais de `AnalyzerState.freeze_select_targets`, gelées au Select Targets step de l'activation — comme #16, et comme l'alternance 12.04 côté mêlée |
| 18 | `advance_after_shoot` | `:1229` | `units_shot` puis `ADVANCED` |
| 19 | `advance_twice_in_shoot_phase` | `:1220` | 2e `ADVANCED` en phase SHOOT |
| 20 | `move_distance_over_limit['advance']` | `:1213` | BFS par socle, budget `M + D6×échelle` (−2" si `[FLY]`) |
| 21 | `advance_from_adjacent` | `:1277` | engagement per-fig aux socles de départ |

### §1.3 CHARGE ERRORS

| # | Compteur | Site | Ce qu'il regarde VRAIMENT |
|---|---|---|---|
| 22 | `charge_from_adjacent` | `charge_handler.py` | engagement per-fig aux socles de départ |
| 23 | `charge_invalid.advanced` | `:81` | `units_advanced` ∧ ni `[WAAAGH!]` ni `charge_after_advance` |
| 24 | `charge_invalid.fled` | `:91` | `units_fled` ∧ pas de `charge_after_flee` |
| 25 | `charge_invalid.distance_over_roll` | `:132` | BFS par socle, budget `2D6×échelle` (−2" si `[FLY]`, obstacles ignorés si vol) |
| 26 | `charge_after_flee` | `:227` | doublon du #24, compteur distinct |

### §1.4 FIGHT ERRORS

| # | Compteur | Site | Ce qu'il regarde VRAIMENT |
|---|---|---|---|
| 27 | `fight_friendly` | `fight_handler.py` | même joueur |
| 28 | `fight_over_cc_nb` | `:216` (plafond : `_cc_cap_for_line`, `:16`, appelé `:188`) | séquence vs plafond **par figurine** : `[SHOOTER_MODELS:]` donne les socles qui ont frappé, `[MODEL_TYPES:]` la datasheet de chacun, `T{tour} EFFECTS:` le bonus `waaagh_melee_atk` (`:39`). Le groupe de frappeurs entre dans la clé de séquence. Repli explicite sur `NB d'escouade × effectif` si le journal n'a pas ces segments. `[SUSTAINED HITS]` exclu. ⚠️ **Réellement par-figurine seulement depuis `baf4859a` (2026-08-10)** — avant, `[MODEL_TYPES:]` répétait le type d'escouade sur chaque socle (cf. §1.1). **Le comptage lui-même a quitté ce fichier le 2026-08-10** : il est mutualisé avec le tir dans `analyzer_perfig.per_model_attack_cap` (`:262`), et `_cc_cap_for_line` ne porte plus que le bonus de Waaagh, propre à la mêlée |
| 29 | `fight_alternation_violations` | `:151` | une unité ayant chargé, encore engagée et non encore activée, existait au moment où une autre a frappé |
| 30-31 | `fight_move_invalid.pile_in` / `.consolidation` | `:423` | BFS par socle, budget `3"×échelle` |

### §1.5–§1.8

| # | Contrôle | Site |
|---|---|---|
| 32 | `action_phase_accuracy` (move / move_after_shooting / fled / shoot / advance / charge / fight → phase attendue) | `analyzer.py` |
| 33 | `double_activation_by_phase` — **MOVE/SHOOT/CHARGE/FIGHT** | `analyzer_core.py` ; marqueurs `:1010-1018` ; garde de phase `:1027` |
| 34 | `double_activation_reactive_move` (2e réactif / tour / joueur) | `analyzer_core.py` |
| 35 | `special_rule_usage` → colonne `Validité` : l'unité porte-t-elle la règle qu'elle a utilisée ? | `analyzer.py` (§1.7) |
| 36 | `rule_choice_selection_invalid` (label inconnu/ambigu, ou choix hors des sources de l'unité) | `analyzer_core.py` |
| 37 | `rule_choice_usage.missing` (effet utilisé sans choix préalable) | `analyzer_core.py` |
| 38 | `rule_choice_usage.mismatch` (effet utilisé ≠ effet choisi) | `analyzer_core.py` |
| 39 | `weapon_rule_usage` → `Validité` : la paire (règle, arme) existe-t-elle dans l'armurerie ? + `NOT USED` | `analyzer.py` (§1.8) |
| 39bis | **QUI compte l'usage** — refonte du 2026-08-11. Étaient comptés : `TWIN_LINKED`, `ASSAULT`, `HEAVY`, `SUSTAINED_HITS`, et `CLOSE_QUARTERS` sur `distance ancre-à-ancre == 1`. S'y ajoutent `RAPID_FIRE`, `MELTA`, `PRECISION` et `DEVASTATING_WOUNDS` **par arme** (la ligne GLOBAL existait seule) ; `CLOSE_QUARTERS` mesure désormais l'ENGAGEMENT, comme #17 et §10.06 — les deux sections comptaient deux grandeurs sous le même nom, **43 contre 1 280** sur le run du 2026-08-11. La clé `(<arme> (<datasheet>))` désigne la **datasheet PORTEUSE** et non plus le type d'escouade : sur 23 169 tirs, **3 138 (14 %)** portaient une arme que seule une figurine déclare (règle 19), invisible des deux côtés — ni attendue, ni comptée. Résolution : `analyzer_perfig.weapon_profile_for_line` | `shoot_handler.py` |
| 39ter | **LA MÊLÉE ENTRE DANS LE TABLEAU — 2026-08-11.** Jusque-là `unit_weapons_cache` n'était bâti que sur `RNG_WEAPONS` : **aucune arme de corps à corps n'existait pour §1.8**, donc aucune règle propre à la mêlée n'a jamais été comptée ni même listée — **32 paires (règle, arme)** hors du champ de la mesure, dont les 2 armes `[CLEAVE]`. Sur le run du 2026-08-11 le tableau gagne **8 lignes**. Compté côté mêlée : `[CLEAVE:X]` et `[SUSTAINED HITS]` (tokens), `TWIN_LINKED` (déclaration) — c'est-à-dire tout ce dont la ligne `FOUGHT` porte la trace. ⚠️ Chaque entrée du cache porte `is_melee`, et ce n'est pas décoratif : `Castellan Axe`, `Guardian Spear` et `Sentinel Blade` désignent DEUX profils selon la phase (le premier déclare `[ASSAULT]` au tir et rien en mêlée). Résoudre par le seul nom crédite `ASSAULT` à une ligne de COMBAT — un usage FABRIQUÉ — et expose le contrôle de portée du tir à une portée nulle. Verrou : `tests/unit/ai/test_analyzer_melee_weapon_usage.py` | `fight_handler.py` (`_note_melee_weapon_rule_usage`), `analyzer_config.py`, `analyzer_perfig.py` |
| 39quater | **`DEVASTATING_WOUNDS` est comptée en mêlée depuis le 2026-08-11** — le formateur de mêlée écrit enfin `Save [DEVASTATING WOUNDS]` (24.10 : « no saving throw can be made »), là où il imprimait `Save None(<seuil>+)`, un jet inexistant sous un seuil réel. Le compteur suit le token, comme au tir | `step_logger.py` (`_save_segments`, partagé SHOT/FOUGHT), `fight_handler.py` |
| 39quinquies | **`Save [NOT ALLOCATED]` — le segment de sauvegarde ne se fabrique plus.** Le seuil n'est écrit qu'à l'ALLOCATION (`_resolve_one_manual_wound`) : une attaque jamais allouée n'a ni seuil ni résultat. Le formateur imprimait quand même `Save <jet>(None+)` ou `Save None(None+)` — **1 429 lignes sur 10 021 (14 %)** du run du 2026-08-11, qu'aucun contrôle ne pouvait relire (ils cherchent des nombres) et qu'ils sautaient donc EN SILENCE. C'est un état de jeu LÉGITIME (05 Attack sequence, « excess attacks lost » : la cible est détruite avant que le pool ne soit résolu) — vérifié sur E127 T4, l'unité 4 est absente de l'instantané `T5 STATE:` qui suit. Le moteur a raison de s'arrêter ; c'était le log qui inventait | `step_logger.py` (`_save_segments`) |
| 40 | `devastating_wounds_incorrect` | `shoot_handler.py` |
| 41 | marqueur `[RAPID FIRE:X]` absent de l'armurerie ou valeur ≠ armurerie → `parse_error` | `shoot_handler.py` |
| ~~41ter~~ | **SUPPRIMÉ le 2026-08-12** (cf. « Contrôles SUPPRIMÉS » plus bas) — « attaque non allouée alors que la cible a survécu ». Le journal ne peut pas trancher : le moteur ne laisse une blessure sans allocataire QUE sur une escouade anéantie, si bien que le contrôle ne mesurait plus que la dérive de l'état reconstruit par l'analyzer. L'invariant 05 est tenu par `tests/unit/engine/test_attack_allocation_contract.py`. Le piège de méthode qui avait coûté 334 fausses erreurs à la première version reste valable pour tout futur contrôle du même genre : **l'ordre des LIGNES n'est pas l'ordre d'ALLOCATION** (pool trié par jet de sauvegarde croissant 05.04, lots enchaînés par profil d'arme 04.03) — E79 T2 : le lot Blitzcannon tue la cible, le lot Rokkit Launcha entier est perdu, y compris une sauvegarde de 1 qui aurait été allouée en premier | — |
| 41bis | marqueur `[BLAST:X]` / `[CLEAVE:X]` absent de l'armurerie ou valeur ≠ armurerie → `parse_error` ; et **les dés additionnels entrent dans le plafond d'attaques** (#12/#28). Un seul calcul pour les deux règles (`analyzer_perfig.additive_rule_extra_dice`), avec l'effectif de la cible figé à l'ACTIVATION — pas à la séquence par arme, le moteur déclarant toutes ses attaques avant d'en résoudre une. Créé le 2026-08-11 : sans lui, les 24 « Attacks over CC_NB » du run étaient les dés de `[CLEAVE]` comptés en dépassement, soit **100 % du compteur en faux positifs** | `shoot_handler.py`, `fight_handler.py` |
| 42 | marqueur `[SUSTAINED HITS]` sur arme sans la règle → `parse_error` | `shoot_handler.py` |

Le marqueur d'activation de la phase FIGHT est `) CONSOLIDATED ` (`analyzer_core.py`) : les
lignes `FOUGHT` sont par ATTAQUE (des dizaines par activation), la consolidation est la seule
frontière d'activation d'une par unité et par phase (12.07). **SHOOT — COUVERT le 2026-08-17** :
`is_shoot_activation_start` introduit dans `is_activation_marker` via `shoot_last_activator`
(variable d'état qui suit le dernier acteur de la phase) : le PREMIER SHOT d'un acteur différent
du précédent ouvre une nouvelle activation ; les tirs consécutifs de la même escouade (salve)
ne déclenche pas de second marqueur. Reset : en début de tour (turn reset), pas en début de phase
(pour que la mise à jour de la ligne courante ne soit pas écrasée par le reset de phase qui
s'exécute après le bloc `if _dmg_actor_match:`). Vérifié rouge → vert :
`tests/unit/ai/test_analyzer_shoot_double_activation.py` (2 tests).

**⚠️ La clé de phase FIGHT était fausse — corrigée le 2026-08-10 (`c1487fcb`).** Elle valait
`(tour, phase, joueur)`. Or un TOUR contient DEUX phases de combat, celle du tour de P1 et celle du
tour de P2, et les unités des deux camps agissent dans chacune : c'est la règle (12.04, les joueurs
alternent leurs sélections). Le `player` d'une ligne est celui de l'unité qui agit, pas celui de la
phase — les deux activations LÉGITIMES d'une unité tombaient donc sur la même clé. La seule
grandeur qui identifie une phase de combat est `fight_phase_seq_id` (`:1042-1052`), avec sa
détection de frontière appliquée sur place (sinon la première ligne d'une phase voit encore
l'identifiant de la précédente, et le VRAI doublon passe inaperçu). **Le chiffre « 24 unités
combattent deux fois » annoncé par la version du 2026-08-09 est réfuté** : `fight_phase_start`
instrumenté sur 1427 phases n'a jamais été appelé deux fois pour la même ; 55 « doublons » sur
12 épisodes, dont zéro vrai.

### §1.9 SEUIL DE BLESSURE — section neuve (2026-08-10, `ai/analyzer_wound.py`, 307 l.)

Le journal écrit le seuil qu'il a réellement appliqué (`Wound 4(4+)`) ; rien ne le vérifiait. Le
seuil ATTENDU est recalculé depuis la donnée et comparé au seuil imprimé :

    F de CHAQUE profil d'arme de la ligne   (`[SHOOTER_MODELS:]` + `[MODEL_TYPES:]` + registry,
                                             `attacker_weapon_strengths:80`. Le moteur fusionne
                                             sur une ligne les armes de même signature d'attaque
                                             (« A / B ») : chaque profil garde sa F RÉELLE, aucune
                                             n'est agrégée, et le seuil n'est rendu que si tous
                                             tombent sur la même valeur)
  + bonus de Force en vigueur               (`waaagh_melee_str`, MÊLÉE seulement — 08.04)
  vs E de la cible                          (19.02 : plus haute E des BODYGUARDS, jamais celle du
                                             leader rattaché — `target_bodyguard_toughness:157`)
  → `engine.combat_utils.calculate_wound_target`   (la fonction du MOTEUR, jamais une copie)
  − 1 si `[OATH OF MOMENT]` suit le segment `Wound` (plancher 2+)

| # | Compteur | Site | Ce qu'il signifie |
|---|---|---|---|
| 63 | `shoot_wound_threshold_mismatch` | `analyzer_wound.py`, appelé `shoot_handler.py` | le seuil imprimé au TIR contredit F/E + bonus |
| 64 | `fight_wound_threshold_mismatch` | idem, appelé `fight_handler.py` | jumeau MÊLÉE |
| — | `*_wound_threshold_unverifiable` | `:296` | donnée absente (arme irrésolue, socle hors `[MODEL_TYPES:]`, datasheet hors registre, tous les bodyguards morts) ou profils de la ligne qui n'attendent PAS le même seuil — compté à part, **jamais en erreur** |

Deux pièges nommés dans le code, tous deux mesurés :
- `[OATH OF MOMENT]` est aussi posé sur la relance de TOUCHE. Le chercher n'importe où dans la
  ligne abaissait le seuil attendu d'un point sur toute ligne qui ne le porte que côté touche —
  80 occurrences pour 60 lignes sur le journal témoin. D'où `WOUND_SEGMENT_RE:50`, qui n'accepte
  que les tokens ATTACHÉS au segment `Wound`.
- Les socles vivants de la cible sont effacés à chaque perte (le journal ne dit pas QUELLE figurine
  est morte). Se limiter à eux écartait 96 lignes sur 96 : le contrôle ne jugeait rien. On retombe
  donc sur le roster complet (`[MODEL_TYPES:]`, jamais effacé), exact tant qu'un bodyguard vit, et
  l'effectif (`unit_models_alive`) détecte le seul cas ambigu.

Les deux compteurs `_mismatch` entrent dans les totaux SHOOTING et FIGHT
(`analyzer.error_totals:1067`) : un écart est une ERREUR, pas un diagnostic.

### §1.10 VERDICT DE TOUCHE — section neuve (2026-08-10, `ai/analyzer_hit.py`, 108 l.)

Jumeau déclaré de §1.9, livré dans le même lot. Le seuil de blessure était recoupé ; le VERDICT
de la touche ne l'était pas — rien ne contredisait un `Hit 1(3+)` suivi d'une blessure.

« 05 Attack sequence.pdf », 05.01 HIT ROLLS, table normative **dans son ordre** :

    Unmodified 1 → FAILS ; Unmodified 6 → CRITICAL HIT ; ≥ BS/WS → HIT ; sinon FAILS.

**Le verdict n'est écrit nulle part, et c'est ce qui rend le contrôle possible sans nouveau
champ** : le formateur n'ajoute le segment `Wound …` QUE sous `hit_result == "HIT"`
(`step_logger.py`). La présence du segment EST le verdict, et elle se lit.

| # | Compteur | Site | Ce qu'il signifie |
|---|---|---|---|
| 68 | `shoot_hit_result_mismatch` | `analyzer_hit.py`, appelé `shoot_handler.py` | le verdict de touche au TIR contredit la table 05.01 |
| 69 | `fight_hit_result_mismatch` | idem, appelé `fight_handler.py` | jumeau MÊLÉE |
| — | `*_hit_result_checked` | `analyzer_hit.py` | lignes RÉELLEMENT jugées — même raison d'être que les `*_unverifiable` de §1.9 |

Deux points de méthode, tous deux repris de verts vacants connus :
- le seuil critique et le 1 d'échec sont IMPORTÉS du moteur
  (`attack_sequence.CRITICAL_HIT_ROLL` / `NATURAL_FAIL_ROLL`), jamais écrits en dur. Coder `== 6`
  ici recréerait exactement **V8**, qui se trompe dès qu'une règle abaisse le seuil critique.
- `[TORRENT]` 24.37 et `[SUSTAINED HITS]` 24.36 n'ont AUCUN jet : le moteur écrit
  `attackRoll=None` ET `hitTarget=None` (`attack_sequence.py`), donc la ligne porte
  `Hit None(None+)` et la regex ne la reconnaît pas. **Ce n'est pas une exception codée dans le
  contrôle** — c'est le journal qui ne présente pas de dé.
- **le verdict se lit sur la GRAMMAIRE du segment, jamais sur la valeur du jet.**
  `[LETHAL HITS]` 24.23 blesse automatiquement : `wound_roll = None` (`attack_sequence.py`)
  et le formateur écrit sans condition `Wound None(4+)` (`step_logger.py`). Une regex
  exigeant des chiffres après `Wound` déclarait donc MANQUÉE toute touche critique d'une arme
  [LETHAL HITS]. Défaut trouvé en review le 2026-08-10 et corrigé le jour même ; il était
  **armé mais latent** — aucun roster du projet ne porte la règle, alors qu'elle est implémentée
  dans le moteur et déclarée dans `weapon_rules.json`.

Affiché par `_hit_result_rows` (`analyzer.py`), sommé dans les totaux SHOOTING et FIGHT
(`analyzer.error_totals:1067`). Verrou :
`tests/unit/ai/test_analyzer_hit_result.py`, 14 tests (table cas par cas, ancrage des constantes
moteur, seuil effectif vs base, et bout-en-bout dans les deux phases).

### §2.1 DEAD UNITS (11 compteurs)

| # | Compteur | Site |
|---|---|---|
| 43 | `dead_unit_moving` | `move_handler.py` |
| 44 | `shoot_dead_unit` | `shoot_handler.py` |
| 45 | `shoot_at_dead_unit` | `analyzer_core.py` |
| 46 | `dead_unit_advancing` | `shoot_handler.py` |
| 47 | `dead_unit_charging` | `charge_handler.py` |
| 48 | `charge_dead_unit` | `charge_handler.py` |
| 49 | `fight_dead_unit_attacker` | `fight_handler.py` |
| 50 | `fight_dead_unit_target` | `fight_handler.py` |
| 51 | `dead_unit_waiting` | `shoot_handler.py` |
| 52 | `dead_unit_skipping` | `shoot_handler.py` — **inatteignable** (pas de producteur `skip`) |
| 53 | `unit_revived` | `analyzer.py` |

Tous appliquent la même exception 05 (« excess attacks lost » de la même activation, via `unit_kill_context`).

### §2.2–§2.3

| # | Contrôle | Site |
|---|---|---|
| 54-56 | `position_log_mismatch` move / advance / charge (`move_start_status`, per-figurine, avec catégorie informative `anchor_absorbed`) | prédicat `analyzer_perfig.py` ; compteurs `move_handler.py`, `shoot_handler.py`, `charge_handler.py` |
| 57 | `unit_position_collisions` (2 unités vivantes sur la même ANCRE, après mouvement le même tour) | 4 sites : `move_handler.py` ; `shoot_handler.py` ; `charge_handler.py` |
| 58 | `damage_missing_unit_hp` | `analyzer.py` |
| ~~59~~ | ~~`damage_exceeds_hp`~~ | **SUPPRIMÉ le 2026-08-17** — irréalisable par construction : `shared_utils` plafonne `dmg_dealt = min(dmg, hp_before)` avant de journaliser, donc `Dmg:X > HP_figurine` ne peut jamais apparaître dans le journal. La dérive de reconstruction est déjà capturée par §2.8 (`state_resync`). Bucket `error_totals['damage']` réduit à `damage_missing_unit_hp` seul. Verrou : `test_bucket_damage_ne_contient_que_damage_missing_unit_hp` (`test_analyzer_error_totals.py`) |

**Investigation `damage_exceeds_hp` (2026-08-17, conduit à la suppression du 2026-08-17).** Ce compteur était affiché et sommé dans le
bucket `damage` de `error_totals`, mais **aucun site ne l'incrémentait** (grep `+= 1` sur tout
`ai/` : 0 hit). L'investigation du 2026-08-17 établit que cela n'est pas un oubli d'implémentation
mais une impossibilité structurelle :

- `shared_utils` (seul site écrivant un `damageDealt` non nul) plafonne AVANT de journaliser :
  `dmg_dealt = min(int(dmg), hp_before)`. Chaque `Dmg:X` en journal vaut donc EXACTEMENT les PV
  retirés à cette figurine — `damage > HP_de_la_figurine` ne peut jamais apparaître.
- Dans `_apply_damage_to_named_model` (grammaire 2+, figurine nommée) : `hp_before - damage > 0`
  (survie) ou ≤ 0 (mort). Le moteur garantit `damage ≤ hp_before` par le plafond pré-log — le
  cas `damage > hp_before` décrit une situation de jeu impossible.
- Dans `_apply_damage_and_handle_death` (chemin hérité) : `unit_hp[target_id]` est le HP
  RECONSTRUIT de la figurine front. Si la reconstruction a dérivé, `damage` pourrait y paraître
  supérieur — mais ce cas est déjà capturé par §2.8 (`state_resync`).

**Compteur supprimé le 2026-08-17** : init `stats`, `error_totals['damage']`, `first_error_lines` et affichage §2.3 retirés de `ai/analyzer.py`. Contrôles vivants réduits à 70 (était 71).

**Le modèle de dégâts a été INVERSÉ le 2026-08-10** (`586c0553`, après un aller-retour). La version
précédente de ce document décrivait `_apply_damage_and_handle_death` comme perdant l'excès de
dégâts. C'est le contraire : l'excès est désormais **reporté sur la figurine suivante**, et la
raison est dans le moteur, pas dans une corrélation. Le seul site qui écrit un `damageDealt` non
nul plafonne d'abord (`dmg_dealt = min(int(dmg), hp_before)`), donc chaque `Dmg:X` journalisé vaut
EXACTEMENT les PV retirés à une figurine : ne pas reporter faisait survivre des escouades que le
moteur avait tuées. Les PV sont par ailleurs passés **par figurine** (`e7de5a54`,
`_model_full_hp`, `analyzer_core.py`) : une escouade hétérogène ne meurt plus avant l'heure.
Seule exception connue, sans effet observable : la ligne `IMPACTED … Dmg:` de la charge écrit une
constante de blessures mortelles et plafonne au niveau de l'UNITÉ.

### §2.8 ÉTAT RECONSTRUIT vs ÉTAT MOTEUR — section neuve (2026-08-09)

Le reste du rapport repose sur un état **reconstruit par accumulation** (PV initial moins chaque
`Dmg:`, position initiale plus chaque déplacement). Rien ne disait quand cette reconstruction
dérivait. La ligne `T{tour} STATE:` est le point de recalage : `_apply_state_snapshot`
(`analyzer_core.py`) **compte l'écart avant de le corriger** — une correction muette ferait
disparaître le symptôme sans jamais signaler sa cause.

| # | Compteur | Site | Ce qu'il signifie |
|---|---|---|---|
| 60 | `state_resync.dead_missed` | `analyzer_core.py` | l'analyzer croyait l'unité vivante, le moteur ne la voit plus — le **fantôme** (une escouade hors table n'est pas comptée : réserves ≠ mort) |
| 61 | `state_resync.alive_missed` | `analyzer_core.py` | l'analyzer a tué une unité que le moteur garde — sur-attribution de dégâts |
| 62 | `state_resync.pos_mismatch` | `analyzer_core.py` | une figurine n'est pas là où l'analyzer la croyait — déplacement non journalisé (c'est ainsi que le pile-in muet s'est manifesté) |

Affiché en §2.8, au SUMMARY et compté dans le total d'erreurs de la CLI (`analyzer.py`).
Il est l'un des rares termes du total à ne PAS passer par `error_totals` : il ne se range dans
aucune phase, c'est un verdict sur l'ensemble de l'épisode. **Portée du verdict** : une divergence non nulle invalide, pour l'épisode concerné,
tout contrôle mesurant une distance ou une adjacence — donc §1.1 à §1.4.

### Contrôles SUPPRIMÉS (documentés dans le code, à ne pas ré-écrire à l'identique)

| Contrôle | Règle | Date | Raison |
|---|---|---|---|
| « Shoot through wall » | 06.01 | 2026-07-16 | LoS ancre-à-ancre sur ancres d'ESCOUADE ≠ prédicat moteur per-figurine. Déplacé dans `tests/unit/engine/test_shoot_los_perfig_parity.py` |
| « Fight from non-adjacent » | 12.05 | 2026-07-24 | métrique hex ≠ euclidien du moteur ; position cible pré-perte non journalisable. Déplacé dans `tests/unit/engine/test_fight_spatial_contract.py` |
| « Attaque non allouée, cible vivante » (41ter, tir ET mêlée) | 05 | 2026-08-12 | le moteur n'a qu'UN chemin laissant une blessure sans allocataire (`_mark_manual_overkill_wasted`, atteint quand `_current_live_group` ne trouve plus un seul groupe vivant) : non alloué ⟺ escouade cible anéantie. Le contrôle opposait donc la règle à l'état RECONSTRUIT et ne signalait que ses dérives — 2 et 15 signalements sur les deux runs du 2026-08-12, tous en fin d'épisode (aucun instantané `T{n} STATE:` ne recale plus l'état), zéro confirmé par les instantanés sur 1747 lignes. Déplacé dans `tests/unit/engine/test_attack_allocation_contract.py` |
| Validité `[HEAVY]` | 24.16 | 2026-07-29 | critère « aucune figurine n'a bougé > 3" » non re-dérivable (chemin géodésique par figurine) |
| `[RAPID FIRE]` per-shot | 24.30 | 2026-07-29 | le moteur résout un POOL ; « quelle attaque est la bonus » n'existe pas |
| Recalcul du contrôle d'objectif | 14.02 | — | sommait par ANCRE, ignorait le battle-shock, évaluait hors frontière de phase |

---

## 3–4–5-bis. Matrices migrées dans `config/rules_corpus.json`

Les tableaux de couverture PDF (156 lignes), armes (23 règles) et règles d'unité (35 règles)
ont été migrés dans `config/rules_corpus.json` lors du Lot 5 (2026-08-20).
Chaque règle y porte son applicabilité, ses contrôles et son statut de vérifiabilité.
Lire les données à la source : `python3 -c "import json; data=json.load(open('config/rules_corpus.json')); print(len(data['rules']), 'entrées')"`.

---

## 5. Verts vacants et pièges identifiés

Chaque ligne a été **re-vérifiée une par une sur `main` le 2026-08-10**, par lecture du prédicat ou
par absence prouvée de site d'incrémentation.

| # | Constat | Emplacement | Effet | Statut 2026-08-10 |
|---|---|---|---|---|
| ~~V1~~ | `damage_exceeds_hp` n'était **jamais incrémenté** | affiché `analyzer.py`, sommé dans les totaux | La ligne « Dmg > HP_CUR (overkill) » affichait 0 en permanence et contribuait à un ✅ dans le SUMMARY | **SUPPRIMÉ le 2026-08-17** — irréalisable par construction : `shared_utils` plafonne `dmg_dealt = min(dmg, hp_before)` avant de journaliser. Clé, affichage et entrée `first_error_lines` retirés de `analyzer.py`. Verrou : `test_bucket_damage_ne_contient_que_damage_missing_unit_hp` (`test_analyzer_error_totals.py`) |
| ~~V2~~ | `fight_from_non_adjacent` n'était **jamais incrémenté** depuis 2026-07-24 | — | — | **FERMÉ le 2026-08-10** par SUPPRESSION de la clé (déclaration, `first_error_lines`, terme du total FIGHT). Le contrôle avait été retiré comme faux positif ; garder sa clé sommée à 0 entretenait l'idée que 12.01 était surveillée. Elle l'est par `test_fight_spatial_contract.py`, fonction `test_fight_b_engagement_pool_uses_full_footprint_distance`. **Son propre verrou était vacant** : `test_analyzer_no_fight_non_adjacent_false_positive` affirmait « == 0 » sur une clé sans site d'incrémentation — vrai quoi qu'il arrive. Il surveille désormais le RETOUR de la clé, et double son assertion par le TOTAL §1.4, qui, lui, bouge |
| ~~V3~~ | `dead_unit_skipping` / `handle_skip` sont **inatteignables** | — | — | **FERMÉ le 2026-08-10** par suppression : `_STEP_LOG_TYPE_MAP` est une liste blanche qui ne porte pas `skip` — « type sans formateur -> volontairement non journalisé ». Aucune ligne `SKIP` n'existe donc dans un step.log (mesuré : 0 occurrence sur 1683 actions). La branche du parseur SURVIT, mais pour signaler la ligne en §2.7 au lieu de la laisser tomber en silence dans `other`. ⚠️ **`shoot_vs_wait['skip']` n'est PAS concerné et reste vivant** : son producteur est `handle_wait` (10.04 requalifie en skip le WAIT d'une unité ENGAGÉE). Deux « skip » homonymes, un seul était mort — le retirer avec l'autre a été tenté et rattrapé par `test_analyzer_wait_engagement.py` |
| V4 | §1.8 usage `CLOSE_QUARTERS` mesure `calculate_hex_distance(ancre_tireur, ancre_cible) == 1` | `shoot_handler.py` | Ancre au lieu du socle **et** adjacence au lieu de la zone d'engagement. À x5, `ez=10` : le compteur d'usage est quasi toujours à 0 | **OUVERT, MAIS RÉDUIT** — `c1487fcb` a corrigé les deux contrôles d'ERREUR voisins (`:644-671`), qui portaient le même défaut. Seul le compteur d'USAGE §1.8 reste ancre-à-ancre |
| ~~V5~~ | `reactive_move_abnormal` mesurait la distance à l'**ancre** | `analyzer_core.py` | — | **FERMÉ le 2026-08-10.** La mesure d'ancre est SUPPRIMÉE, pas corrigée : son jumeau immédiat `distance_over_roll` pose déjà la même question par `_per_model_move_violation` (par socle, chemin réel, budget converti). Les deux entraient dans le total §1.1 — un vrai dépassement comptait **2 fautes pour 1**, et une reformation d'ancre en déclenchait une fausse. `reactive_move_abnormal` ne pose plus que SA question (phase où le move réactif n'a rien à faire). Verrou : `test_analyzer_reactive_move_single_measure.py` |
| ~~V6~~ | `_build_move_bfs_blockers` ignore l'exemption 17.01 | `analyzer.py` | — | **FERMÉ le 2026-08-10.** 17.01 (« normal or advance move ») est passée en paramètre `monster_or_vehicle_by_unit` : un mobile M/V ne bloque plus que sur les AUTRES M/V. Le fall-back, la charge et le pile-in ne reçoivent pas la carte — la règle ne les couvre pas, et l'omission est donc la règle, pas un oubli. Le drapeau vient du MÊME champ de registre que les exemptions de tir 10.06/17.03, et un mélange de datasheets M/V et non-M/V dans une escouade LÈVE au lieu de rendre un chemin faux |
| ~~V7~~ | Le BFS de mouvement ne connaît pas le **bord du plateau** | `analyzer.py` | — | **FERMÉ le 2026-08-10.** 03.01 « Its base cannot cross the edge of the battlefield ». `cols`/`rows` sont lus dans l'entête `Board:` (`parse_board_dims_from_log`), avec le même contrat que l'échelle : leur absence REFUSE le journal. C'était un FAUX NÉGATIF — un socle coincé dans un coin trouvait toujours un contournement par l'extérieur, et le contrôle de budget se taisait sur le seul chemin que la règle interdit. Le bord borne le CENTRE en transit, exactement comme `geodesic_move_reach` côté moteur ; le débordement du socle à l'arrivée reste au contrôle de placement (§2.2) |
| V8 | `devastating_wounds` suppose que **seul un 6** est critique | `shoot_handler.py` | Faux « incorrect » dès qu'une arme [ANTI-X Y+] rend critique un Y+ < 6 | **OUVERT** — `wound_roll_value == 6` en dur |
| ~~V9~~ | Le contrôle de portée ne rend **aucun verdict** quand aucun socle de la cible n'est connu | `shoot_handler.py` | — | **FERMÉ le 2026-08-12.** Le renoncement reste délibéré (l'ancre d'une escouade ne dit rien de la distance à sa figurine la plus proche), mais il n'est plus SILENCIEUX : `shoot_range_unverifiable` compte les tirs non jugés, et §1.2 l'affiche sous la ligne de portée (`↳ portees non jugees`). Un contrôle qui renonce sans le dire affiche le même `0` qu'un contrôle qui a tout vérifié — et le compteur `total` ne le rattrapait pas, puisqu'il s'incrémente à l'entrée du handler, avant le bloc de portée |
| V12 | ~~La ligne `phase Start` est produite et jamais lue~~ | `step_logger.py` (`log_phase_transition`) | 07.02 reste non vérifié | **RÉVISÉ le 2026-08-10 — l'énoncé était FAUX, et il l'était dans le sens qui coûte le plus cher.** `log_phase_transition` n'a **aucun appelant** (grep sur `engine/`, `ai/`, `services/` → 0 hit hors définition) et la chaîne `phase Start` n'apparaît **pas une seule fois** dans un step.log de 1683 actions. La ligne n'est donc pas « produite et non lue » : elle n'est pas produite. 07.02 n'est pas ABSENT-LOGGABLE, il est **ABSENT-LOG-MANQUANT** — ou reconstructible autrement, depuis les `T{tour} P{joueur} {PHASE}` des lignes d'action, ce qui reste à faire |
| V13 | `has_line_of_sight` (ancre-à-ancre, documentée comme inexacte) classe les `WAIT` en `wait_with_los` / `wait_no_los` | `shoot_handler.py` (prédicat `:908`) | Usage assumé « métriques comportementales », mais ces métriques servent au pilotage | **OUVERT** |

### Verts vacants FERMÉS ou RÉVISÉS le 2026-08-10

| # | Ce que disait la version précédente | Ce que dit le code |
|---|---|---|
| ~~V11~~ | « PARTIELLEMENT FERMÉ le 2026-08-09 : FIGHT est entrée dans la liste des phases, 24 unités combattent deux fois » | **La moitié FIGHT était un FAUX POSITIF, et il venait de ce document.** La clé de phase confondait les deux phases de combat d'un tour ; corrigée par `c1487fcb` (`analyzer_core.py`). Zéro vrai doublon sur 12 épisodes après correction. **Le volet SHOOT — COUVERT le 2026-08-17** : `shoot_last_activator` dans `is_activation_marker` détecte le premier SHOT d'un acteur différent comme ouverture d'activation ; cf. §1 et 10.02 |
| ~~V10~~ | « `FLED` n'a AUCUN contrôle de budget ni de chemin — seul déplacement sur six sans `_per_model_move_violation` » | **FERMÉ le 2026-08-10.** Les trois volets géométriques de 09.07 sont contrôlés (#65-#67, `move_handler.py`) et entrent dans le total MOVE. Reste hors de portée, faute de donnée : le MODE de fall-back (§7 L11) — d'où `force_thru_enemy` |
| ~~V14~~ | « Le plafond de tir reste par escouade alors que celui de mêlée est par figurine » | **FERMÉ le 2026-08-10**, et par mutualisation plutôt que par copie : `analyzer_perfig.per_model_attack_cap` (`:262`) est désormais LE calcul des deux côtés, `[SHOOTER_MODELS:]` a quitté `fight_handler` pour `analyzer_perfig` (`:251`), et le X de `[RAPID FIRE]` suit la même résolution par figurine. Écrire un second exemplaire côté tir aurait rouvert le défaut à la première divergence |
| **V16** | *(trouvé et fermé le 2026-08-10, en livrant V10)* — les totaux d'erreurs existaient en DEUX exemplaires, celui du SUMMARY et celui de la CLI | **FERMÉ.** Ils avaient divergé en silence sur deux compteurs : `move_after_shooting_distance_over_limit` (§1.1) et `shoot_combi_profile_conflicts` (§1.2) manquaient au total CLI. Effet observable : un run pouvait afficher « ❌ 1.1 Erreurs en phase de move : 2 » et rendre un total d'erreurs qui n'en comptait aucune — et c'est le total, plus court, qu'on lit en premier. La review du jour a montré que le trou était plus large : **§1.6 (double-activation) et §1.7 (règles invalides) s'affichaient en ❌ sans entrer dans AUCUN total** — un run imprimait « ❌ 1.6 … : 1 » puis « ✅ Aucune erreur détectée ». `error_totals` (`analyzer.py`) porte désormais TOUS les buckets, y compris §1.5 à §2.8, et expose `['total']` = leur somme : le total de la CLI ne recompose plus rien, donc toute ligne ❌ y entre par construction et un bucket neuf aussi. Verrou : `tests/unit/ai/test_analyzer_error_totals.py` (61 tests) pose 1 dans CHAQUE compteur l'un après l'autre, vérifie que sa somme bouge, puis que `total == somme(buckets)` |
| **V17** | *(trouvé et fermé le 2026-08-10, en instruisant V16)* — `unit_id_mismatches` n'était PAS dans la structure `stats` ; `dead_unit_actions` n'avait ni producteur ni lecteur | **FERMÉ.** Mesuré : `'unit_id_mismatches' in parse_step_log(...)` rendait **False** — la clé n'apparaissait qu'au `setdefault` de `print_statistics`, 130 lignes avant le seul lecteur qui la lit sans garde. D'où trois lecteurs à trois niveaux de défensive et deux idiomes de création. Tout consommateur du `stats` rendu levait `KeyError`. La clé est déclarée avec ses voisines (`analyzer.py`), les deux créations paresseuses ont disparu, la garde `if … in stats` du total CLI aussi. `dead_unit_actions` était du code mort pur (créé, affecté à une locale, jamais relu — 1 seul hit au grep) : supprimé. Même famille que V1/V2/V3 |
| ~~V15~~ | « Cinq des six clés de `T{tour} EFFECTS:` ne sont lues par personne » | **Réduit à UNE.** `waaagh_melee_str` alimente §1.9 (`analyzer_wound.py`), `waaagh` et `oath_target` alimentent §1.7 (`analyzer_core.py`), `waaagh_melee_atk` alimentait déjà #28, `oath_wound` alimente désormais la magnitude Oath de §1.9 (2026-08-17). **Reste inexploitée : `waaagh_invul`** (5++) |

**Grep JUMEAU** (2026-08-10) `calculate_hex_distance|is_adjacent(` sur les 7 fichiers de
l'analyzer → 8 hits, **4 sites de mesure** : `analyzer.py` (distance à vol d'oiseau **par
socle**, légitime — 21.03), `analyzer.py` (`get_adjacent_enemies`, défini `:1097`,
**diagnostic seul** : n'alimente que les payloads `first_error_lines` et les traces de debug,
jamais un verdict), et les deux verts vacants V4 (`shoot_handler.py`) et V5
(`analyzer_core.py`). Les 4 autres hits sont des imports et la définition d'`is_adjacent`
(`analyzer.py`). Aucun autre résidu ancre-à-ancre. `analyzer_wound.py` n'en contient
aucun : il ne mesure pas de distance.

---

## 6. Synthèse chiffrée

### 6.1 Règles PDF (156)

| Statut | Nombre | % |
|---|---|---|
| COUVERT | 9 | 5,8 % |
| PARTIEL | 35 | 22,4 % |
| ABSENT-LOGGABLE | 7 | 4,5 % |
| ABSENT-LOG-MANQUANT | 67 | 42,9 % |
| NON-TESTABLE-OFFLINE | 38 | 24,4 % |

Quatre mouvements vers COUVERT depuis le 2026-08-09 : **05.02** (ABSENT-LOG-MANQUANT → COUVERT,
§1.9), **05.01** (ABSENT-LOGGABLE → COUVERT, §1.10), **06.03** (ABSENT-LOGGABLE → COUVERT,
2026-08-17 : branche HAZARDOUS ré-écrite dans `analyzer_core.py`), **10.02** (ABSENT-LOGGABLE →
COUVERT, 2026-08-17 : `shoot_last_activator` détecte la double-activation SHOOT). 09.07 et 04.03
restent PARTIEL mais changent de nature : leurs trous géométriques sont fermés, ce qui reste tient
à des champs absents du journal. **24.29 [PSYCHIC]** reclassé N/A — KEYWORD (2026-08-17) : keyword
d'interaction, aucun contrôle de conformité autonome à écrire.

Par famille :

| PDF | Total | COUVERT | PARTIEL | ABS-LOGGABLE | ABS-LOG-MANQ | NON-TESTABLE |
|---|---|---|---|---|---|---|
| 01 Core concepts | 7 | 1 | 0 | 1 | 2 | 3 |
| 02 Datasheets | 7 | 0 | 0 | 0 | 1 | 6 |
| 03 Moving | 4 | 1 | 2 | 1 | 0 | 0 |
| 04 Making attacks | 3 | 0 | 3 | 0 | 0 | 0 |
| 05 Attack sequence | 4 | 2 | 1 | 0 | 1 | 0 |
| 06 Other concepts | 3 | 1 | 0 | 0 | 1 | 1 |
| 07 Battle round | 3 | 0 | 0 | 1 | 0 | 2 |
| 08 Command phase | 5 | 0 | 0 | 1 | 2 | 2 |
| 09 Movement phase | 7 | 1 | 3 | 0 | 1 | 2 |
| 10 Shooting phase | 7 | 1 | 3 | 0 | 1 | 2 |
| 11 Charge phase | 4 | 0 | 2 | 0 | 0 | 2 |
| 12 Fight phase | 9 | 1 | 3 | 2 | 0 | 3 |
| 13 Terrain | 11 | 0 | 1 | 0 | 0 | 10 |
| 14 Objectives | 3 | 1 | 0 | 0 | 1 | 1 |
| 15 Stratagems | 12 | 0 | 0 | 0 | 12 | 0 |
| 16 Actions | 1 | 0 | 0 | 0 | 1 | 0 |
| 17 Monsters & vehicles | 3 | 0 | 2 | 0 | 0 | 1 |
| 18 Transports | 5 | 0 | 0 | 0 | 5 | 0 |
| 19 Attached units | 4 | 0 | 1 | 0 | 2 | 1 |
| 20 Strategic reserves | 4 | 0 | 2 | 1 | 1 | 0 |
| 21 Flying & surging | 3 | 0 | 1 | 0 | 2 | 0 |
| 22 Other rules | 5 | 0 | 1 | 0 | 3 | 1 |
| 23 Aircraft | 4 | 0 | 0 | 0 | 4 | 0 |
| 24 Core abilities | 38 | 0 | 10 | 0 | 27 | 1 |
| **Total** | **156** | **9** | **35** | **7** | **67** | **38** |

### 6.2 Règles d'armes (23) et d'unité (35)

| Corpus | Total | COUVERT | PARTIEL | ABS-LOGGABLE | ABS-LOG-MANQ | NON-TESTABLE |
|---|---|---|---|---|---|---|
| `weapon_rules.json` | 23 | 1 | 7 | 14 | 1 | 0 |
| `unit_rules.json` | 35 | 6 | 20 | 2 | 5 | 2 |

### 6.3 Tous corpus confondus (214 lignes)

| Statut | Nombre | % |
|---|---|---|
| COUVERT | 13 | 6,1 % |
| PARTIEL | 63 | 29,4 % |
| ABSENT-LOGGABLE | 11 | 5,1 % |
| ABSENT-LOG-MANQUANT | 87 | 40,7 % |
| NON-TESTABLE-OFFLINE | 40 | 18,7 % |

### 6.4 Côté analyzer

| | Nombre |
|---|---|
| Contrôles de conformité vivants | **71** (69 + `squad_coherency_violations` 03.03 + `fight_double_pile_in` 12.02, livrés le 2026-08-10) |
| dont morts / inatteignables | **0** — V1 (`damage_exceeds_hp`) supprimé le 2026-08-17 (irréalisable par construction) ; V2 et V3 supprimés le 2026-08-10 |
| Sommes d'erreurs dupliquées | 0 — un seul `error_totals` (`analyzer.py`) depuis V16 |
| Clés de `stats` créées à la volée | 0 depuis V17 — toutes déclarées dans la structure |
| Lignes ❌ du SUMMARY absentes du total | 0 — `error_totals['total']` est la somme de tous les buckets |
| dont mesurant la mauvaise grandeur | **2** (V4 usage close-quarters à l'ancre, V8 critique supposée à 6) — V5, V6, V7 et V14 fermés le 2026-08-10 |
| Contrôles supprimés, documentés, à ne pas ré-écrire | **7** (+ `fight_from_non_adjacent` et `dead_unit_skipping`/`handle_skip`, 2026-08-10) |
| Sections de rapport | 18 (§1.1–§1.10, §2.1–§2.8) — dont 4 purement diagnostiques (§2.4, §2.5, §2.6, §2.7) — **plus la table « 1.1 COUVERTURE DES REGLES »**, qui n'est pas une section d'erreurs mais le rendu du corpus |

### 6.5 Mouvement net (2026-08-08 → 2026-08-09 → 2026-08-10)

| | 08-08 | 08-09 | 08-10 (carto) | 08-10 (livraison) |
|---|---|---|---|---|
| COUVERT (tous corpus) | 10 | 11 | 12 | **13** |
| ABSENT-LOGGABLE | 13 | 13 | 12 | **11** |
| Contrôles vivants | 59 | 62 | 64 | **69** |
| Verts vacants ouverts | 13 | 14 | 13 | **11** (V10 et V14 fermés ; V16 et V17 trouvés et fermés le jour même) |
| Fichiers de l'analyzer | 6 | 6 | 7 | **8** (`analyzer_wound.py`, `analyzer_hit.py`) |

Le gain de couverture reste **modeste par construction**. Les quatre lots du 2026-08-09 avaient
surtout supprimé des **faux positifs** (2218 → 18 erreurs sur un run) et ajouté un point de
recalage (§2.8). Le lot du 2026-08-10 fait les deux : il ajoute quatre vrais contrôles (05.02,
05.01, et les trois volets de 09.07) et il retire trois sources de faux positifs
(double-activation FIGHT, close-quarters ancre-à-ancre, plafond de tir par escouade). Les
`ABSENT-LOG-MANQUANT` n'ont bougé que d'une ligne : ce lot ne fait pas grossir le journal, il
exploite ce qu'il portait déjà.

**Enseignement de méthode, à ne pas perdre.** Trois affirmations de la version du 2026-08-09 se
sont révélées fausses, et les trois pour la même raison : *elles décrivaient l'intention d'un
commit, pas ce que le code faisait*. La double-activation FIGHT était comptée mais sur une clé
fausse ; `[MODEL_TYPES:]` était émis mais rendait le type d'escouade ; `[HAZARDOUS]` était formaté
mais n'atteignait pas le fichier. Un contrôle « livré » ne vaut que si l'on a vérifié qu'il regarde
la bonne grandeur ET que sa donnée arrive jusqu'à lui.

**Lecture d'ensemble.** La couverture réelle se concentre sur la géométrie du mouvement et de
l'engagement (03, 09, 11, 12 partiels, 21) et sur l'éligibilité au tir (10). Les 41 % de
`ABSENT-LOG-MANQUANT` se répartissent en trois blocs quasi disjoints :
**(a)** les sous-systèmes non implémentés ou non journalisés (15 Stratagems, 16 Actions,
18 Transports, 23 Aircraft, 21.01–21.02 Surge) — 26 règles ;
**(b)** les abilités d'arme sans token — **bloc quasi vidé le 2026-08-12** : n'y restent que
24.19 ([INDIRECT FIRE]) et 24.21 ([LANCE]), toutes deux NON IMPLÉMENTÉES dans le moteur, plus
les abilités de datasheet de 24.26/31–35 qui ne sont pas des règles d'arme journalisables.
24.03/05/06/11/18/23/25/28/29/37 ont leur token depuis les lots des 11 et 12 août ;
**(c)** la mécanique de résolution d'attaque au niveau figurine (05.02, 05.03, 06.02, 24.12, 24.28,
02.02) et le battle-shock (01.06, 01.07, 08.03, 14.03).

---

## 7. Liste consolidée des champs manquants du StepLogger

Ordonnée par nombre de règles débloquées. « Débloque » = fait passer la règle de
`ABSENT-LOG-MANQUANT` à au moins `ABSENT-LOGGABLE`.

**Déjà livré par les lots du 2026-08-09** (retiré de la liste ci-dessous) : `AGENT_PLAYER=`
(siège de l'agent), `[MODEL_TYPES:]` (datasheet par figurine), `T{tour} STATE:` (point de recalage
d'état) et `T{tour} EFFECTS:` (effets en vigueur avec contribution chiffrée).

**L2 est CLOS depuis le 2026-08-10, et sans ajouter le champ.** La version précédente réclamait
`S` de l'arme et `T` de la cible sur chaque jet. `ai/analyzer_wound.py` a montré que le champ
n'était pas nécessaire : `[MODEL_TYPES:]` donne la datasheet de la figurine qui frappe, le registry
donne sa F, `[MODEL_TYPES:]` de la cible donne l'E des bodyguards (19.02), et `T{tour} EFFECTS:`
donne le bonus. Le seuil attendu est calculé par la fonction du MOTEUR, pas par une copie. **Leçon
transposable au reste de cette liste** : un « champ manquant » peut n'être qu'un champ
*re-dérivable* — avant de faire grossir le journal, chercher si la donnée existe déjà ailleurs.
Reste réellement bloqué par L2 : 19.02 — l'E RETENUE par le moteur, que l'analyzer recalcule au
lieu de la lire. **24.03 en est sorti le 2026-08-12** : `[ANTI-<KW>:Y+]` atteint `step.log`, et il
y porte le seuil que l'ARME DÉCLARE — donc la donnée qui manquait pour recouper le seuil de
blessure critique n'a plus à être re-dérivée du tout (cf. §1.3).

| # | Champ / ligne à ajouter | Format proposé | Débloque |
|---|---|---|---|
| ~~L1~~ | ~~**Drapeau `battle_shocked` par unité** + jet de battle-shock~~ — **LIVRÉ le 2026-08-19** : ligne produite le 2026-08-17 ; parse analyzer + `battle_shocked_by_unit` ajoutés le 2026-08-19 | — | 01.06, 01.07, 02.02 (OC='-'), 08.03, 14.02, 16.01, 15.04 |
| ~~L2~~ | ~~`S` de l'arme et `T` de la cible~~ — **CLOS le 2026-08-10 sans ajout de champ** (cf. ci-dessus) ; le reliquat utile est le `T` RETENU par le moteur, pour cesser de le recalculer | `Wound R(T+) [S<n> vs T<n>]` | 19.02 seul |
| ~~L3~~ | ~~**Figurine cible allouée** + groupe d'allocation~~ — **LIVRÉ le 2026-08-17** : `→ <mid>` sur la partie `Save`/`Dmg` | — | 05.03, 05.04, 06.02, 24.28 |
| ~~L4~~ | ~~**`AP` de l'arme, `Sv`/`InSv` du groupe**~~ — **LIVRÉ le 2026-08-17** : `Save R(<base>+ AP<n> → <eff>+)` | — | 05.04, `closest_target_penetration`, 24.18 |
| L6 | **Ligne `stratagem`** (nom, CP dépensés, cible, phase) | `P<n> STRATAGEM [<NOM>] -<n>CP → Unit M` | 15.01–15.12 (12 règles) |
| L7 | **Lignes `action_start` / `action_complete`** | `Unit N ACTION START [<nom>]` / `… COMPLETE` | 16.01, 09.06, 09.07, 10.04–10.07 (volets « AFTER: pas d'action ») |
| L8 | **Transports** : capacité, embark, disembark (mode + jet de hasard) | types `embark`, `disembark` dans `_STEP_LOG_TYPE_MAP` | 18.01–18.05 |
| L9 | **Zones de déploiement + bords de plateau utilisables** | entête `Deployment: P1=<rect> P2=<rect>` | 03.02, 20.04, 24.09, 24.20, 24.31, 24.32 |
| L10 | **Type de move / de tir / de fight EXPLICITE** (au lieu d'être déduit des tokens) | suffixe `[MOVE_TYPE:normal\|advance\|fall_back\|remain_stationary\|ingress\|surge\|scout]`, `[SHOOT_TYPE:normal\|assault\|close_quarters\|indirect]` | 09.02, 09.04, 09.07, 10.02, 10.04–10.07, 12.05, 12.06, 21.02, 24.32 |
| L11 | **Mode de fall-back** (`ordered_retreat` / `desperate_escape`) + jets de hasard associés | `FLED [DESPERATE ESCAPE] … Hazard:<n>,<n>,…` | 09.07, 06.03, 18.04 |
| L12 | **Jets Feel No Pain** | `FNP:<n>/<seuil>+ ×<n>` | 24.12 |
| L13 | **Distance tireur↔cible au Select Targets** (ou marqueur `[HALF RANGE]`) | `[HALF RANGE]` | 24.25, 24.30 |
| ~~L14~~ | ~~**Statut Fights First** de l'unité activée~~ — **LIVRÉ le 2026-08-18** : `[FIGHTS FIRST]` sur la ligne `FOUGHT` via `fightsFirst` dans l'action_log combat | 24.13, 12.04, 11.04, 15.12 |
| L15 | **Nombre d'armes [HAZARDOUS] sélectionnées** | `[HAZARDOUS:<n>] Roll:<n>,<n>,…` | 24.15 |
| L16 | **Cibles de charge multiples** (11.04 autorise plusieurs) | `CHARGED Unit M(…),Unit K(…)` | 11.04 |
| L17 | **Cibles de pile-in / mode de consolidation** | `PILED IN [targets: M,K]`, `CONSOLIDATED [ONGOING\|ENGAGING\|OBJECTIVE:<id>]` | 12.03, 12.08 |
| ~~L18~~ | ~~**Objectifs : méthode `secured`/`default` + OC par joueur**~~ — **LIVRÉ le 2026-08-19** : `ZONES=` étendu avec `:Mthd=:OC1=:OC2=` dans `step_logger.py`, câblé dans `w40k_core.py`, parsé dans `analyzer_core.py` (`objective_control_method` + `objective_oc_per_zone`) | — | 14.02, 14.03 |
| ~~L19~~ | ~~**Attached units** : lien leader/support ↔ bodyguard~~ — **LIVRÉ le 2026-08-18** : entête `Attached: <leader_id>→<bodyguard_id>` dans `log_episode_start` via `attached_info` | 19.01, 19.02, 19.04, 24.22, 24.34 |
| L20 | **Terrain** : catégorie et hauteur par hexe | entête `Terrain: <cat>@(c,r,h)…` | 13.02–13.11, 06.01, 22.05 (lève aussi 10 NON-TESTABLE) |
| L21 | **Aircraft** : keyword et placement forcé en réserves | — | 23.01–23.04 |
| ~~L22~~ | ~~**Segment `[MODELS:]` sur la ligne `REACTIVE MOVED`**~~ — **CONFIRMÉ présent** : émis via `engine/w40k_core.py` (`_build_step_log_details`) (models_segment universel) ; couvert par `test_analyzer_reactive_move_single_measure.py` | rend #7 per-figurine (03.04) et supprime V5 |
| L23 | **Type `surge` dans `_STEP_LOG_TYPE_MAP`** | — | 21.01, 21.02 |
| L24 | **Producteur pour `skip`** (le formateur existe) | — | rend #52 atteignable |
| ~~L25~~ | ~~**Capacités de commandement déclarées** (Waaagh! appelé, cible Oath of Moment)~~ — **LIVRÉ le 2026-08-18** : `P<n> COMMAND [WAAAGH!]` / `[OATH OF MOMENT] → Unit M` via `append_action_log` dans `command_handlers.py` | 08.04, 22.02, `waaagh`, `oath_of_moment` |
| L26 | **Modificateurs de touche hors HEAVY/COVER** (`hit_target_base` généralisé) | `Hit R(<base>+->_<eff>+) [<cause>]` | 10.06 (−1 M/V), 17.03, 22.05, 24.29, 15.09 |
| ~~L27~~ | ~~**Relance de sauvegarde en mêlée : nom de la capacité**~~ — **LIVRÉ le 2026-08-18** : `saveAbility` sur le shot_record via `_get_source_unit_rule_display_name_for_effect(target, "reroll_1_save_fight")` | `reroll_1_save_fight`, `preservation_imperative` |
| ~~L28~~ | ~~**Relance de charge : token**~~ — **LIVRÉ le 2026-08-18** : `[REROLLED:<jet initial>]` sur `CHARGED` via `charge_roll_initial` dans l'action_log | `reroll_charge` |

**Champs déjà présents et simplement non exploités** (aucune modification du StepLogger requise —
c'est le gisement le moins cher) :

| Champ présent | Non exploité par | Débloquerait |
|---|---|---|
| ~~`T{tour} EFFECTS: oath_wound=+X`~~ | ~~aucun contrôle~~ | **CONSOMMÉ (2026-08-17)** — magnitude lue par `_effect_bonus` dans `analyzer_wound.py`, fallback 1 pour les vieux journaux |
| `T{tour} EFFECTS: waaagh_invul` | aucun contrôle | volet 5++ de `waaagh` |
| ~~`[MODEL_TYPES:]` + `[SHOOTER_MODELS:]` côté TIR~~ | ~~`shoot_handler.py`~~ | **CONSOMMÉ le 2026-08-10** (V14) — plafond de tir par figurine, mutualisé avec la mêlée |
| `[FIGHT_SUBPHASE:<x>]` | aucun contrôle | 12.06 (overrun fight) |
| ligne `phase Start` | aucun contrôle | 07.02 (ordre des phases) |
| `CP1=` / `CP2=` | aucun contrôle | 08.02, `cp_gain_on_objective` |
| ~~`[MODELS:]` complet~~ | ~~aucun contrôle de cohérence~~ | **CONSOMMÉ** — 03.03 par #68 (mise en place + fin de déplacement) depuis le 2026-08-10, et la purge End of Turn depuis le 2026-08-12 (ligne `Unit N COHERENCY REMOVED <mid> … (03.03)`, émise par `fight_handlers._log_end_of_turn_coherency_removals`) |
| positions + `Board: cols/rows` | BFS (`analyzer.py`) | bord de plateau (V7, 03.01), `>8"` d'ingress (20.03, 20.04) |
| ~~`Hit R(T+)` + présence du segment `Wound`~~ | ~~aucun contrôle~~ | **CONSOMMÉ le 2026-08-10** (§1.10) — 05.01, jumeau de §1.9 sur le segment `Wound` |
| ~~`[HAZARDOUS] Roll:N` + `SUFFERS X MW`~~ | ~~aucun contrôle~~ | **CONSOMMÉ (2026-08-17)** — `hazardous_mortal_wounds` + vérif armurerie dans `analyzer_core.py` |

**Quatre entrées ont quitté cette liste le 2026-08-10** : `oath_target` et `waaagh_melee_str`
(cf. §1.4 et §5, V15), puis `[MODEL_TYPES:]`/`[SHOOTER_MODELS:]` côté tir et le segment `Hit`
(livraison V14 et §1.10). Les six restantes sont, à ce jour, le gisement le moins cher de la
liste : aucune ne demande de toucher au StepLogger.

**Ce que la livraison a confirmé sur la méthode.** Les trois chantiers du 2026-08-10 ont fermé
un trou de règle (09.07) et deux verts vacants **sans ajouter un seul champ au journal** — L2
comprise, réclamée depuis deux versions. Avant d'inscrire un `Lxx` dans la liste ci-dessus,
vérifier que la donnée n'est pas déjà là sous une autre forme : le verdict de touche n'était
écrit nulle part, il se déduisait de la PRÉSENCE d'un segment.

---

**`L5` a été RETIRÉE de ce tableau le 2026-08-12**, comme `L2` avant elle : elle réclamait des tokens de règles d'armes dans `step.log`, et les six derniers (`[TORRENT]`, `[LETHAL HITS]`, `[IGNORES COVER]`, `[EXTRA ATTACKS]`, `[ANTI-<KW>:Y+]`, `[PSYCHIC]`) y sont entrés, au tir comme en mêlée, verrouillés par `tests/unit/ai/test_step_log_weapon_rule_tokens.py`. Le résidu — `[INDIRECT FIRE]` 24.19 et `[LANCE]` 24.21 — **n'est pas un champ manquant du StepLogger** : la RÈGLE n'est pas implémentée dans le moteur, donc aucun token ne peut la décrire sans annoncer un effet qui n'a pas lieu. Elle est portée par §3 et §4, pas ici.

## 8. Ce qui a été vérifié, et ce qui ne l'a pas été

**Vérifié par lecture intégrale** : `ai/step_logger.py`, `ai/analyzer_perfig.py`,
`ai/analyzer_state.py`, `ai/analyzer_config.py`, `ai/analyzer_core.py`,
`ai/analyzer_phases/{move,charge,fight,shoot,episode}_handler.py`, les helpers géométriques et de
dégâts de `ai/analyzer.py` (l. 196-982) et la totalité de sa section de rapport (l. 1535-3320),
`config/weapon_rules.json`, `config/unit_rules.json`, le texte intégral des 25 PDF, et les points
d'émission `step.log` de `engine/w40k_core.py` (`_STEP_LOG_*`, `_build_step_log_details`,
`_build_shot_details`, `_models_segment_for_unit`, `_run_rules_for_step_log`,
`_record_rule_choice_action_log`) + `engine/action_log_utils.py`.

**Mise à jour du 2026-08-09** : relecture du `git diff` complet des quatre lots sur
`ai/analyzer*.py`, `ai/analyzer_phases/*`, `ai/step_logger.py` et `engine/w40k_core.py`
(`_log_effects_snapshot_if_changed`), puis re-grep de tous les sites d'incrémentation cités pour
en refixer les numéros de ligne. Les verts vacants V1–V10 et V12 ont été **re-vérifiés un par un**
sur `main` : tous encore ouverts.

### Mise à jour du 2026-08-10 — ce qui a été vérifié, et COMMENT

**Lu intégralement** : `ai/analyzer_wound.py` (251 l., module neuf) ; `_handle_fled`
(`move_handler.py`) ; `_build_move_bfs_blockers` + `_bfs_shortest_path_length` +
`_per_model_move_violation` (`analyzer.py`) ; le bloc de double-activation, le bloc
réactif et `_FACTION_ABILITY_KEYS` / `_count_faction_activations` (`analyzer_core.py`,
`:1009-1060`, `:1190-1235`, `:1300-1325`) ; le plafond de tir et le bloc close-quarters
(`shoot_handler.py`, `:630-700`, `:730-760`) ;
`_STEP_LOG_TYPE_MAP` et `_SHOT_RECORD_FIELD_MAP` (`w40k_core.py`) ;
`weapon_rule_log_tokens` (`shared_utils.py`).

**Re-dérivé par grep, sans exception** : les ~70 numéros de ligne cités en §1, §2, §5 et §5-bis.
Aucun n'a été recopié.

**Prouvé par absence** (grep exhaustif rendant 0 hit) : V1 (`damage_exceeds_hp` — aucun `+= 1`),
V2, V3 (`skip` hors de `_STEP_LOG_TYPE_MAP`), V12 (`"phase Start"`), V14
(`MODEL_TYPES` dans `shoot_handler.py`), `waaagh_invul` dans `ai/`.
`oath_wound` : **consommée désormais** (2026-08-17) — voir §1.4 et l'entrée V15 ci-dessus.

**Prouvé par le code du moteur** (pas par corrélation) : le modèle de dégâts §2.3 — le plafond
`dmg_dealt = min(int(dmg), hp_before)` est cité dans `586c0553`, qui annule un revert pris deux
fois dans le mauvais sens sur la base d'une mesure *insuffisante* (« 14 intervalles sur 14 :
somme(Dmg) == perte de PV » ne distingue pas « le journal est plafonné » de « aucun overkill n'a eu
lieu »).

### Livraison du 2026-08-10 (V10, V14, 05.01) — ce qui est PROUVÉ, et comment

**Règles lues dans les PDF avant d'écrire une ligne de code**, jamais assumées :
« 09 Movement phase.pdf » 09.07 (fall-back : distance, éligibilité, post-condition, modes) et
« 05 Attack sequence.pdf » 05.01 (table de touche, dans son ordre). Les deux sont recopiées mot
pour mot dans les docstrings des contrôles, pour que la prochaine relecture n'ait pas à rouvrir
le PDF pour vérifier que le code dit la même chose.

**Chaque test a été prouvé ROUGE avant d'être vert** — un test qui passe du premier coup n'est
pas un verrou :

| Défaut remis en place | Effet observé |
|---|---|
| appel à `_check_fall_back_move` retiré | 4 tests sur 6 tombent ; la prémisse géométrique et le cas légal restent verts (ils ne dépendent pas du contrôle) |
| les 3 termes de fall-back retirés du total MOVE | le SUMMARY affiche « ✅ 1.1 Erreurs en phase de move : 0 » là où il doit afficher 2 |
| plafond de tir remis au niveau escouade | 2 faux positifs sur 4 tirs LÉGAUX, et le vrai dépassement compté 4 au lieu de 2 |
| `check_hit_result` court-circuité après son compteur `_checked` | 3 tests tombent ; celui qui ne vérifie que « 0 faute » reste vert — c'est précisément pourquoi il porte aussi une assertion sur `_checked` |
| les 2 compteurs perdus retirés d'`error_totals` (V16) | les 2 cas paramétrés correspondants tombent, et EUX SEULS : le test désigne le compteur fautif par son nom |
| `'unit_id_mismatches'` retiré de la structure `stats` (V17) | 2 tests tombent ; et le producteur de `shoot_handler` lève `KeyError` sur le vrai chemin — ce qui prouve que la déclaration structurelle le porte réellement |
| ancienne regex `\bWound\s+\d+` remise (LETHAL HITS) | 2 tests tombent, dont le bout-en-bout : `Wound None(4+)` redevient un « échec » et la touche critique est comptée en faute |
| bucket `double_activation` retiré d'`error_totals` | 1 test tombe, et il NOMME le bucket manquant |
| ligne §1.6 réaffichant la seule somme par phase | 1 test tombe : sur un journal ne portant qu'un doublon RÉACTIF, elle imprimait « ❌ 1.6 … : 0 » — icône et nombre doivent sortir de la même grandeur |
| total de la CLI recomposé à la main (4 buckets sur 15) | le test qui relit la source le refuse — c'est ce qui interdit la reconstitution du défaut |

**Greps JUMEAU de la livraison**, tous rapportés y compris vides :
- `Hit\s|'Hit ` sur les 8 fichiers de l'analyzer → **0 hit** hors `analyzer_hit.py` : aucun autre
  lecteur du segment de touche à faire converger.
- `rng_nb_by_weapon|cc_nb_by_weapon` → 6 hits, 2 sites de plafond (les deux passent désormais par
  `per_model_attack_cap`), 4 résolutions du NB d'ESCOUADE qui servent de repli — légitimes.
- `_per_model_move_violation` → les **six** déplacements sont couverts (move, move-after-shooting,
  fall-back, advance, charge, pile-in/consolidation) plus le réactif. C'était le point du vert
  vacant V10 : il n'en manque plus.
- `_shooter_models` → 0 hit après bascule ; l'import privé croisé `shoot_handler` →
  `fight_handler._shooter_models` a disparu avec lui.

**Tests exécutés** : les 27 fichiers `tests/unit/ai/test_analyzer_*.py` et
`test_step_log_weapon_rule_tokens.py`, **308 tests, tous verts**. Ce n'est PAS la vérification
large du dépôt (suite complète, `pyright`, `check_ai_rules.py`, `biome`, `tsc`) : elle appartient
à l'utilisateur et n'a pas été lancée. Aucun verdict n'est rendu ici sur les tests d'`engine/`
ni sur l'intégration PvP.

**Non vérifié — le verdict est borné ici, et « non exploré » n'est pas « sain »** :
- Aucun `step.log` réel n'a été analysé : les statuts décrivent le CODE, pas une mesure sur un run.
  Les chiffres de run cités (2218 → 18 erreurs ; 1657 tokens Oath ; 144 faux positifs
  close-quarters ; 55 faux doublons FIGHT ; 96 lignes écartées sur 96) proviennent des rapports de
  commit, je ne les ai pas reproduits.
- **Les 25 PDF n'ont pas été relus le 2026-08-10.** Les 156 lignes de la matrice A reposent sur
  l'extraction du 2026-08-08. Seuls les statuts que le CODE a fait bouger (05.02, 05.04, 06.03,
  12.04) ont été retouchés.
- **Les statuts non touchés de §3, §4 et §5-bis n'ont pas été re-audités un par un.** Ils datent du
  2026-08-08/09. Ce qui a été vérifié aujourd'hui, c'est qu'aucun commit du 2026-08-10 ne les
  contredit — pas qu'ils étaient justes à l'origine. Trois d'entre eux ne l'étaient pas (cf. §6.5).
- Les tests ajoutés par les lots (`test_analyzer_heterogeneous_squad_hp.py`,
  `test_analyzer_fight_phase_identity.py`, `test_identical_attacks_grouping_0403.py`) n'ont **pas
  été lus** : je ne dis rien de ce qu'ils verrouillent, ni ne les ai exécutés.
- La régénération d'une référence en x1 (plateau 44×60) reste ouverte : sans elle, les compteurs
  §1.1–§1.4 d'un run x5 ne sont pas comparables au baseline historique.
- `ai/unit_registry.py` et le contenu des datasheets n'ont pas été relus : les statuts
  « NON-TESTABLE-OFFLINE (registre) » supposent que le registre porte bien ces champs. Cela vaut
  aussi pour §1.9, qui lit `cc_str_by_weapon` / `rng_str_by_weapon` dans ce registre.
- Les chemins PvP/replay (`services/`, `frontend/`) sont hors périmètre : cette matrice ne
  concerne que `step.log` → `analyzer`. Conséquence directe sur §1.3 : je constate que dix tokens
  d'arme n'ont pas d'entrée dans `_SHOT_RECORD_FIELD_MAP`, donc qu'ils n'atteignent pas step.log ;
  je n'ai pas vérifié ce que le Game Log PvP en fait.
- `target_priority` (`unit_rules.json`) : son classement PARTIEL dépend de la présence de
  `grants_rule_ids` dans les datasheets, non relues.
