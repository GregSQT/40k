# Analyzer — Tâches ouvertes

Découpage en 6 lots des trois sujets ci-dessous (ordre séquentiel imposé : tous éditent `ai/analyzer*.py`) → `Documentation/Archives/chantiers/analyzer_conformite_lots.md` ✅ TOUS LIVRÉS

---

## ✅ Compteur d'exercices câblé — les verdicts « JAMAIS EXERCÉE » disent enfin quelque chose {#compteur-exercices}

**✅ LIVRÉ (2026-09-07)** — `note_rule_usage` n'était appelé que pour **14** des **62 règles du
corpus qui déclarent des `controls`** ; les 48 autres ne pouvaient afficher que `ERREURS` ou
`JAMAIS EXERCÉE`, jamais `OK`. Les **46 règles `always`** manquantes sont câblées : le rapport
passe de **48 à 15 verdicts « JAMAIS EXERCÉE »**.

✅ **Les deux câblages inopérants sont réparés le 2026-09-07** (suite de revue), et l'applicabilité
des règles d'armes est désormais dérivée : **15 → 7 verdicts « JAMAIS EXERCÉE »** sur le même
journal. Détail dans la section suivante.

1. `PROJ.1.2.advance_post_tir` était gardé par `if phase == 'SHOOT'` dans `shoot_handler.py`. Or
   l'Advance est un **type de mouvement de la phase MOVE** (09.02) — la table
   `expected_phase_by_action` d'`ai/analyzer.py` documente précisément cette correction
   (« advance etait attendu en SHOOT — FAUX »). Mesuré sur `step.log` : 10849 lignes `ADVANCED`,
   10849 en phase MOVE, **zéro** en SHOOT. L'exercice est posé au site du contrôle, sans garde.
2. `PROJ.1.2.double_advance` **est supprimée avec son compteur** `advance_twice_in_shoot_phase` :
   inatteignable pour la même raison, et la faute qu'elle visait (deux sélections de mouvement
   dans la même phase, 09.02) est déjà mesurée par `double_activation_by_phase['MOVE']` — mesuré,
   un journal à double `ADVANCED` rend `double_activation_by_phase['MOVE'] == 1`. Ce compteur
   n'appartenait à **aucune** règle du corpus : il est rattaché à `09.02`, et son jumeau de charge
   à `11.02`.
3. La justification écrite pour 10.02 / 12.07 (« leur verdict est calculé avant la branche qui le
   lit ») était fausse quand leur compteur d'erreurs est non nul : `coverage_rows` force
   `applicable = True` dès que `errors > 0`, puis rend `ERREURS` avec `exercised == 0`. Les quatre
   règles PDF de double-activation ont maintenant leur site d'exercice, au bloc qui juge le
   doublon.
4. Même défaut, troisième forme : les trois règles `PROJ.2.8.*` du recalage notaient leur exercice
   sous `unit_player is not None` alors que leurs compteurs d'erreurs s'incrémentent sans lui. Le
   garde est retiré, le camp se replie sur P1 — §2.8 est scalaire, comme l'assume déjà
   `PROJ.2.8.alloc_inconnue`.

Chaque appel est posé **au site où le contrôle regarde vraiment**, après ses renoncements, jamais
à l'entrée du handler — la règle que pose le docstring de `note_rule_usage`. Preuve de placement :
`PROJ.1.2.portee` rend **51509** exercices, soit exactement les 66956 lignes `SHOT` moins les
15447 abstentions que le rapport comptait déjà séparément (`shoot_range_unverifiable`).

**Défaut trouvé en chemin et corrigé** : `PROJ.1.3.apres_repli` pointait sur
`charge_invalid['fled']`, une sous-clé **sans aucun écrivain**. La ligne « Charges after flee » du
rapport affichait donc 0 quoi qu'il arrive, et le bucket `charge` ignorait ces fautes ; la vraie
faute vit dans `charge_after_flee`. Câbler l'exercice sans réparer le compteur aurait produit un
« OK » permanent, incapable de virer au rouge. Un test qui lisait la clé morte était vert par
construction.

**Décision** : l'état `exercised == 0 and errors > 0` reste rendu en `ERREURS`. Le nommer
autrement masquerait une faute réelle derrière un défaut d'outil, à rebours du principe déjà acté
dans `coverage_rows` — une erreur est un FAIT, elle prime sur la prédiction. Le défaut
d'instrumentation se voit plus tôt, en CI, par le verrou ci-dessous. Un site d'erreur peut
légitimement n'avoir pas son site d'exercice (`wall_collisions` a trois sites d'incrément pour un
seul site d'exercice, cf. `test_the_fall_back_site_also_counts_an_exercise_of_03_01`).

Verrous : `test_toute_regle_applicable_a_controles_est_instrumentee`,
`test_aucun_identifiant_instrumente_n_est_inconnu_du_corpus` et
`test_aucun_site_note_rule_usage_n_a_d_identifiant_indechiffrable`
(`tests/unit/ai/test_analyzer_rules_corpus.py`), lecture par **AST** et non par regex — un site
légitime choisit son identifiant selon la ligne traitée
(`"PROJ.1.4.pile_in" if kind == "pile_in" else …`), qu'un regex déclarerait orphelin. Le troisième
verrou est né d'un trou des deux premiers : `fight_handler.py` notait deux règles depuis une
**variable de boucle**, forme que le décodeur AST rend vide — une faute de frappe y passait la CI
et n'aurait levé qu'en production. Le remède est côté SITE (identifiant écrit en clair), pas côté
décodeur : apprendre au test à interpréter des formes toujours plus larges déplace le trou sans
le fermer.

---

## ✅ Applicabilité des règles d'armes — l'avertissement cesse de mentir {#applicabilite-armes}

**✅ LIVRÉ (2026-09-07)** — Une règle conditionnée à un token d'arme était déclarée `always` dans
le corpus. Le rapport la rendait alors sous « ⚠️ Applicable(s) et jamais exercee(s) — **la
situation s'est presentee** et aucun controle n'a rien juge », alors que la situation ne s'était
jamais présentée : aucune arme jouée ne porte TORRENT, BLAST ni INDIRECT FIRE. Cet avertissement
est la raison d'être du module ; six lignes fausses sur quinze le rendaient illisible.

Prédicat `weapon_rule_in_roster`, **jumeau exact** d'`unit_rule_in_roster` : le token croisé avec
les types réellement vus dans le journal, dérivé de l'armurerie et de rien d'autre. Registre
`AnalyzerConfig.weapon_rule_to_units` (`token -> profil -> types porteurs`).

**Le profil (`ranged`/`melee`) n'est pas décoratif.** Mesuré sur l'armurerie : HAZARDOUS est porté
par **21 armes de tir et zéro de mêlée**, LETHAL_HITS par **3 de tir et 1 de mêlée**. Un prédicat
sans profil aurait déclaré `PROJ.1.4.hazardous` (mêlée) applicable parce qu'un pistolet plasma
porte le token — le faux avertissement qu'on retire, réintroduit par la porte de derrière. Verrou :
`test_le_profil_separe_le_tir_de_la_melee` et `test_le_registre_reel_porte_le_grain_des_deux_cotes`
(`tests/unit/ai/test_analyzer_applicabilite_armes.py`), le second contre le vert vacant d'un
registre jamais rempli.

`COMBI` est une clé **synthétique** de ce registre, dérivée d'`unit_combi_by_weapon` — la table que
lit le contrôle lui-même. Ce n'est pas un token d'armurerie, et c'est dit à sa déclaration.

Ce contrôle était **MORT** jusqu'au 2026-09-07 : `unit_combi_by_weapon` est indexé par la datasheet
qui PORTE l'arme, mais il était interrogé sous le type d'ESCOUADE, qui ne déclare pas le combi.
Résolu depuis par les model-types de `[SHOOTER_MODELS:]` — **0 → 2004 exercices, 0 → 500 erreurs**.
Le grain est la FIGURINE : le profil engage le socle qui tire, pas l'escouade. `[SHOOTER_MODELS:]`
étant un segment de GROUPE, ce grain se vérifie à plusieurs porteurs et non à un seul :
`test_multi_bearer_group_each_violation_counted_per_bearer` tient les deux porteurs fautifs à
2 conflits et 4 exercices, le seul test qui exerce la boucle avec N>1.

Ces **500 erreurs n'étaient pas des faux positifs** : le moteur déclarait réellement les deux
profils d'un même combi dans une seule activation. Cause corrigée le 2026-09-07 dans
`squad_declare_shoot` (cf. `ROADMAP_INDEX.md`, correctifs hors chantier du jour) — comme tout bug
moteur, **invisible sur un journal déjà écrit** : à re-mesurer au prochain run, attendu 0.

**Ce que ce prédicat ne ferme pas, et pourquoi.** Les lignes restantes ne dépendent pas d'un
roster mais d'un ÉVÉNEMENT qui ne s'est pas produit : personne ne s'est replié PUIS n'a tiré
(`PROJ.1.2.apres_repli`), aucune unité n'est ressuscitée, aucune réserve n'a été détruite au 3e
round. Les dire honnêtement demanderait de compter les occasions OFFERTES en plus des occasions
JUGÉES — un second point de comptage dans 46 endroits, deux compteurs à tenir d'accord,
c'est-à-dire le défaut V16 qu'on paie déjà ailleurs. Écarté sciemment.

**`PROJ.1.3.apres_advance` n'en faisait PAS partie — la prémisse « personne n'a avancé PUIS
chargé » était fausse (corrigé le 2026-09-12).** Mesuré sur le run holdout du 2026-09-11 : 114
unités avaient avancé puis lancé leur jet de charge, toutes orkes, toutes en FAILED CHARGE. Le
site d'exercice ne vivait que dans la branche CHARGED (`ai/analyzer_phases/charge_handler.py`) ;
la branche FAILED CHARGE ne contrôlait que les bornes du jet. Or 11.02 : la DÉCLARATION précède
le jet — un jet raté est une déclaration au même titre. Le verdict est désormais UNIQUE
(`def _judge_charge_after_advance`) pour les deux issues, et RE-DÉRIVÉ de l'état plutôt que lu
sur le marqueur `[WAAAGH!]` que le moteur écrit lui-même (et que FAILED CHARGE ne porte pas) :
capacité de datasheet `charge_after_advance` sur les socles vivants (19.04), sinon Waaagh! actif
pour le camp (`T{n} EFFECTS:`) ET mot-clé ORKS du type (`rule_to_units["waaagh"]`), sinon
`charge_invalid.advanced`. Le marqueur est contre-contrôlé : `[WAAAGH!]` sans Waaagh! actif est
une incohérence entre deux sorties du moteur (`parse_errors`). Verrou :
`tests/unit/ai/test_analyzer_charge_apres_advance.py`.

---

## Faux positifs `shoot_over_rng_nb` {#faux-positifs-plafond-tir}

**✅ LIVRÉ (2026-09-02)** — Run de 300 épisodes : **5187 → 2243 erreurs**, dont `surcharge_atk` 4879 → 1935.

Deux causes traitées, toutes deux dans le calcul de `max_allowed_shots` (`shoot_handler.py`) :

1. **Gate `oath_target` erroné** (régression du jour même) — le bonus Hail of Bolts avait été conditionné à `target_id == oath_target` sur la foi d'un finding de code review. Le moteur dit l'inverse, explicitement : « la cible de l intent EST la cible designee » (`shared_utils.py`), sans aucun filtre. Le gate faisait tomber le plafond dès qu'une escouade répartissait son tir sur une seconde cible. **2432 faux positifs.**
2. **Capacités d'unité non propagées aux personnages rattachés (19.04)** — `atk_bonus_by_weapon` était résolu par datasheet individuelle, comme le NB. Or 19.04 : « abilities/rules that affect a unit apply to EVERY model in an attached unit ». Un Ancient rattaché à une escouade Intercessor tire donc son Bolt Rifle avec +2 A, ce que le moteur lui accorde déjà. **512 faux positifs.**

Nouveau `unit_ability_attack_cap` (`analyzer_perfig.py`), jumeau INVERSE de `per_model_attack_cap` : ce qui est intrinsèque à l'arme (NB, RAPID FIRE, BLAST, CLEAVE, SUSTAINED HITS) reste par-figurine ; ce qui vient d'une capacité d'unité se propage à tout le socle attaché.

Verrous : `test_analyzer_unit_ability_attached_19_04.py`, `test_analyzer_hail_of_bolts.py`.

**✅ LIVRÉ (2026-09-11) — §1.7, MÊME cause 19.04, autre registre : 2 `INVALID` → 0.** Le registre
de validité `rule_to_units` (`analyzer_config.py`) est bâti sur les datasheets d'ESCOUADE : il ne
voyait pas la capacité du personnage replié dedans. Sur le run holdout du 2026-09-11,
`mortal_wounds_on_fight_activation` (Chaplain dans un Vanguard, 90 usages) et
`mortal_wounds_on_critical_wound` (PainBoy dans des Boyz, 4 usages) sortaient donc `INVALID`,
soit **4 des 4 erreurs du run**. Le moteur, lui, applique 19.04 — vérifié en reconstruisant le
scénario : `unit 1 (Boyz)` porte bien la règle via `_ATTACHED_RULE_GROUPS['_inline_1_11']`.
Le verdict juge sur la composition OBSERVÉE (`[MODEL_TYPES:]`) et non sur `CAN_LEAD` — ce dernier
décrit les attachements LÉGAUX, un sur-ensemble qui blanchirait un usage réellement invalide.

**✅ ITÉRATION (2026-09-11, suite 80) — le verdict passe du post-traitement au RELEVÉ.** Jugé a
posteriori sur la clé `(règle, type d'escouade)`, il se prononçait sur la composition de
DÉPLOIEMENT, unionnée par type et sur les deux camps : une capacité restait `OK` après la mort de
sa source (19.04 l'arrête là), et une seule escouade attachée blanchissait ses homonymes (sur le
step.log du jour, `Unit 4 (Intercessor)` mène un `Librarian`, `Unit 5 (Intercessor)` un
`CaptainRelicShield`). `note_special_rule_usage` (`ai/analyzer_rules.py`) est désormais le SITE
UNIQUE d'écriture de `special_rule_usage` : il reçoit l'`unit_id`, lit le vivant dans
`unit_model_hp` (`living_datasheets`), et accumule les relevés fautifs dans
`stats['special_rule_usage_invalid']` — que `error_totals` SOMME (90 usages illégaux comptent 90)
et que le tableau §1.7 rend en `INVALID(n)`. `stats['model_types_by_unit_id']` remplace
`model_types_by_unit_type`. Deux abstentions assumées : la règle de la datasheet d'ESCOUADE reste
valide (le journal ne dit pas quel socle est natif ; l'exiger serait plus strict que la règle), et
un socle vivant de datasheet inconnue suspend le verdict — cas des figurines RENDUES (`#r<n>`, que
19.04 réhabilite). Verrou : `test_analyzer_attached_rule_validity.py` (8 verts, 3 mutations
rouge→vert) ; `test_analyzer_faction_ability_validity.py` APPELLE le prédicat au lieu de recopier
son critère. Re-dépouillement du même step.log : 1909 utilisations, 0 `INVALID`.

**✅ LIVRÉ (2026-09-02) — 1935 → 0 `surcharge_atk` restants** : deux capacités Primitive B absentes de `max_allowed_shots` :

3. **`weapon_attacks_bonus_vs_keyword` (Dakkablitz / BigMekDakkarig)** — +6 A au Blitzcannon si cible hors MONSTER/VEHICLE. `excluded_keywords` absent du registre JSON (tableau TS silencieusement ignoré par le parseur). Fix : `unit_registry.py` parse désormais les tableaux de chaînes dans `rule_args`. Nouveau `unit_ability_atk_bonus_vs_keyword_cap` dans `analyzer_perfig.py`.
4. **`grant_weapon_rule_vs_designated_target` (Overlapping Detonations / EradicatorHeavyBolter×2+Sergent)** — +`target_size//5` A au Heavy Bolter vs non-MONSTER/VEHICLE. Nouveau `unit_blast_per5_nonmv_bonus` dans `analyzer_perfig.py`. `unit_upper_keywords_by_type` ajouté à `AnalyzerConfig` pour vérifier les mots-clés de la cible.

Verrous : `test_analyzer_dakkablitz.py` (4 verts), `test_analyzer_overlapping_detonations.py` (6 verts).

---

## ✅ Allocation à un CHARACTER — 05.03 / 06.02 / 24.28 (2026-09-18) {#alloc-character}

Livré avec le chantier « chaîne d'attaque 100 % » (`Documentation/Archives/chantiers/chaine_attaque_100.md`).
Contrôle `alloc_character_over_bodyguard[<bucket>]` (`analyzer_core._note_character_allocation_in_lot`
+ `_flush_character_allocation` pour `SHOT`/`FOUGHT`, `_judge_character_allocation` pour `SUFFERS`,
verdict `analyzer_rules.character_allocation_fault`) : figurine allouée (`[ALLOC_MODEL:]`) CHARACTER
alors qu'un non-CHARACTER de l'unité est vivant **à la fin du lot** — verdict PAR LOT depuis le
2026-09-18 (bis) : l'ordre des lignes d'un lot est celui des jets, pas de l'allocation (pool trié par
sauvegarde, `_roll_batch`), le verdict ligne à ligne comptait une fausse 05.03 dès que la ligne du
CHARACTER précédait celles des bodyguards tués avant lui. Légal sous `[PRECISION]` pour une blessure
normale ; pour une blessure MORTELLE, la clé `alloc.precision_mw_to_character` de l'entête `Run rules:`
(miroir de `game_rules.precision_mortal_wounds_to_character`) tranche, journal sans la clé =
indécidable. Corpus : `PROJ.1.1/1.2/1.3/1.4.alloc_character` ; 05.03, 06.02, 24.28 passent
d'`ABSENT_LOG_MANQUANT` à `COUVERT`. 20 verrous (`test_analyzer_alloc_character.py`). Non
vérifié : priorité « figurine déjà blessée », ordre des groupes W/Sv/InSv (non journalisés).
Nouveaux jetons lus : `DID NOT ATTACK … N attack(s) not made` (métrique
`shoot_cross_weapon_attacks_lost`), `[ENGAGED TARGET]` (17.03, seuil effectif imprimé) ; Deadly
Demise repositionnée après les attaques (`dead_models_since_explosion`).

---

## ✅ Effets défensifs — 05.04 / 24.12 / InSv conférées (2026-09-18) {#effets-defensifs}

Livré avec le lot « Capacités Armageddon → décisions d'agent » (prompt 7, `moteur.md#capacites-decisions-agent`).
Module `ai/analyzer_save.py`, deux compteurs du bucket §2.3 « dégâts », un par entrée du corpus :
`save_threshold_mismatch` (PROJ.2.3.save_threshold) — `Save R(<base>+ AP<n> → <eff>+)` recalculé
par le `save_threshold` du moteur, InSv effective = meilleure entre datasheet de la figurine allouée,
`invul_save_override` des sources PRÉSENTES au Select Targets step (`SelectTargetsFreeze.models`,
donc 19.04 avec sa dernière clause) et `waaagh_invul` LU dans `T{tour} EFFECTS:` (clé ajoutée au
producteur `_log_effects_snapshot` ; Waaagh! actif sans la clé = abstention) ; pas de plafond à 6+
(un 5+ sous AP−4 s'imprime 9+, insauvable, et c'est exact) ; `fnp_threshold_mismatch` (PROJ.2.3.fnp)
— `[FNP:s/t+ ×n]` : seuil = meilleur seuil des sources présentes (24.02), Dok's Toolz 5+, Psychic
Hood 4+ si `[PSYCHIC]` ou Da Jump, Unbreakable Resolve 4+ si l'Ancient alloué est dans une aire
d'objectif (`state.objective_cells`, entête `Objectives:`) ou à 6" du centre — mesuré depuis le
2026-09-18 du BORD du socle (01.04) par `ranged_edge_distance_to_cell` et la métrique `metric.ranged`
du run, donc jugé à TOUTE résolution ; l'abstention x5 est levée ; présence sans source, absence avec
source et `Dmg>0` (jugé sans garde de version depuis le 2026-09-19 : la compatibilité avec les
journaux antérieurs à la garantie est abandonnée, et la garde qui les protégeait est retirée), compte
`Dmg ≠ n − s` ; sur les lignes SUFFERS, **`[FNP_ROLLS:]` depuis la grammaire 17** rend le même
jugement PAR FIGURINE (jet manquant alors qu'une source s'applique, jet sans source, seuil faux,
sauvés > blessures, attribué > déclaré, et attribué < déclaré avec un socle encore listé dans le `[MODELS:]` de la ligne — 06.02 n'autorise l'arrêt anticipé que sur la destruction), le verdict de SOURCE étant suspendu sur les tags qui
peuvent tomber dans le sursis 19.04 d'une allocation d'attaque. Corpus : 24.12 → COUVERT
(la note « jet et seuil absents » était périmée), PROJ.1.9.feel_no_pain/_vs_psychic/_near_objective
→ COUVERT via 24.12, unit.invul_save_override et unit.waaagh → COUVERT, unit.toughness_bonus_while_waaagh
→ COUVERT via PROJ.1.4.blessure (contrôlé depuis `analyzer_wound.target_bodyguard_toughness`).
Nouveau : `_counter_row` du rapport imprime aussi `reserves_too_early`, `da_jump_invalid` et
`suppression_without_hit`, qui entraient dans les totaux sans ligne. 18 verrous
(`test_analyzer_fnp.py`, `test_analyzer_save_threshold.py`) ; 0 erreur sur un journal réel du moteur
(4 puis 14 épisodes à actions aléatoires, rosters Armageddon, 229 seuils et 159 FNP jugés, 32 instantanés Waaagh! actif ; journal produit par un script jetable, non conservé au dépôt).

---

## ✅ Objectifs et restitution — 14.02 / 14.03 / Relic Banner / REVIVED (2026-09-18) {#objectifs-restitution}

Livré avec le lot « Capacités Armageddon → décisions d'agent » (prompt 8). Module
`ai/analyzer_objectives.py`, trois compteurs du bucket §2.3, un par entrée du corpus :
`objective_control_mismatch` (PROJ.2.3.objective_control) — à chaque instantané `T{tour} OBJECTIVE
CONTROL:`, l'OC de chaque camp est resommé par zone depuis les socles vivants (`unit_model_hp` ×
`positions_by_model`, empreinte réelle du socle ∩ aire — 14.02 « within that terrain area »), OC de
datasheet par figurine (02.02) + `oc_bonus` par figurine si un porteur vit (Relic Banner, 19.04), 0 si
l'escouade est battle-shocked (01.07/08.03) ; contrôleur attendu = miroir de
`_resolve_objective_controller` (égalité = personne sauf sécurisé) ; `objective_secured_invalid`
(PROJ.2.3.objective_secured) — **grammaire 15** : `:Sec=<1|2|none>` par zone (producteur
`log_objective_control_snapshot`, `secured_objectives` entre dans la clé de déduplication) et ligne
`Unit N(c,r) SECURES <zone> [<capacité>]` (action_log `secure_objective` d'`apply_secure_objective_on_control`,
enrichi de la zone et de la capacité) : une sécurisation n'apparaît qu'après une ligne SECURES du
camp en phase COMMAND, sur une escouade vivante présente dans l'aire et porteuse (19.04 par
`note_special_rule_usage`), le contrôle lui revenant ; perte — et depuis le 2026-09-18 REPRISE par
l'adversaire sans `Sec=none` intermédiaire, ce que le moteur produit en fin de phase de commandement —
seulement sur niveau adverse strictement supérieur ; `returned_models_invalid` (PROJ.2.3.returned_models) — chaque ligne RETURNED : k ≤ D3,
k ≤ figurines mortes rendables (`dead_model_ids_episode`), une par escouade et par partie, phase
COMMAND du propriétaire, types ⊆ mortes non rendues, aucun leader/support (`_model_is_character`).
Corpus : unit.secure_objective_on_control, unit.oc_bonus, unit.return_destroyed_models → COUVERT.
Au passage : le découpage de `ZONES=` par blancs rangeait l'OC sous le dernier mot du nom de zone
(« rect b NW » → `NW`) — découpé par `|` (`parse_zones`) ; le parseur de replay
(`frontend/src/utils/replayParser.ts`) rejetait TOUTE zone suivie de `:Mthd=` (donc tout journal
depuis L18, 2026-08-19) — champs optionnels acceptés, +1 vitest. Verrous : `test_analyzer_objective_control.py`
(7), `test_analyzer_objective_secured.py` (5), `test_analyzer_returned_models.py` (+6, puis +3
le 2026-09-19 : la ligne `RETURNED` produite par le VRAI moteur donnée au vrai `parse_step_log`),
`test_step_log_objective_secured.py` (producteur), `test_squad_step_logging.py` (+1 dédup).

---

## Champs manquants `step.log` {#champs-step-log}

**6** entrées restantes (L6–L28, hors L1/L2/L3/L4/L9/L10/L11/L12/L13/L14/L15/L16/L17/L18/L19/L22/L24/L25/L26/L27/L28 résolues). Chaque champ se livre seul et fait passer des règles de « non vérifiable » à « vérifiable ».

Livré (2026-08-20) :
- L11 `[DESPERATE ESCAPE]/[ORDERED RETREAT]` + `Hazard:rolls` sur FLED (09.07/06.03) — 6 verrous.
- L12 `[FNP:saves/seuil+ ×tentatives]` sur Dmg: (24.12) — 4 verrous.
- L15 `[HAZARDOUS:n] Roll:dice` (24.15) — 5 verrous.
- L26 `[POINT-BLANK]` + `base+->eff+` généralisé pour tout `hit_rule_modifier` (10.06 M/V) — 5 verrous.

Bloqués sans implémentation moteur : L20 (terrain — 0 terrain dans scénarios), L21 (Aircraft — 0 hit engine), L23 (surge — 0 hit engine).

À piocher quand un contrôle analyzer manque de données.

→ `Documentation/Chantiers/analyzer_couverture.md` §7

---

## Corpus de règles vérifiable {#corpus-regles}

**✅ LIVRÉ Lot 5 (2026-08-20)** — 267 entrées dans `config/rules_corpus.json` (60 existantes + 207 migrées). Matrices §3/§4/§5-bis supprimées du Markdown. VERROU : `test_aucun_compteur_en_double_dans_le_corpus` + `test_tous_les_chemins_de_controle_sont_lisibles` (64 verts).

**✅ LIVRÉ Lot 6 (2026-08-20)** — V4/V8/V13 fermés ; 10.02/12.07 câblés ; `wait_with_shootable_target` ; `analyzer_couverture.md` vrai : 0 vert vacant ouvert, COUVERT 65/267. Verrous : 64 verts.

**✅ LIVRÉ Lot 7 (2026-08-25)** — 5 règles ABSENT_LOGGABLE câblées : TORRENT 24.37, LETHAL HITS 24.23, BLAST 24.05, 20.03 (réserves round 1), unit.charge_impact (corpus seul). Compteurs dédiés remplacent parse_errors. COUVERT 81/273. Invariants §1.1 (13→14), §1.2 (16→19), §1.4 (9→11). 13 verrous rouges→verts.

→ `Documentation/Archives/chantiers/analyzer_conformite_lots.md`
