# Analyzer — Tâches ouvertes

Découpage en 6 lots des trois sujets ci-dessous (ordre séquentiel imposé : tous éditent `ai/analyzer*.py`) → `Documentation/Archives/chantiers/analyzer_conformite_lots.md` ✅ TOUS LIVRÉS

---

## Compteur d'exercices non câblé — les verdicts « JAMAIS EXERCÉE » sont du bruit {#compteur-exercices}

`note_rule_usage` (`ai/analyzer_rules.py`) n'est appelé que pour **14** des **62 règles du corpus
qui déclarent des `controls`**. Les **48 autres** ne peuvent afficher que `ERREURS` ou
`JAMAIS EXERCÉE` — jamais `OK` : leur colonne `Exercices` est nulle par construction. Le rapport
du 2026-09-07 affiche exactement 48 verdicts « JAMAIS EXERCÉE ».

Conséquence directe : l'avertissement « ⚠️ Applicable(s) et jamais exercee(s) — la situation s'est
presentee et aucun controle n'a rien juge » est du bruit pour la quasi-totalité de ses entrées,
alors qu'il est **la** raison d'être du module (détecter le motif 17.01 : une règle que le moteur
n'applique jamais ne produit aucune ligne fautive, donc aucun compteur ne bouge, donc le rapport
affiche un vert franc — mesuré le 2026-08-10).

Cinq règles ont été câblées le 2026-09-07 (celles dont les contrôles étaient corrigés le même
jour) : `PROJ.2.1.dead_shot_at` (11232 exercices), `PROJ.1.2.surcharge_atk` (66956),
`PROJ.1.3.budget` (1472), `PROJ.1.4.consolidation` (297), `PROJ.1.4.pile_in` (1525). Sans ce
câblage, corriger leurs faux positifs les faisait passer de « ERREURS » à « JAMAIS EXERCÉE » —
un second mensonge à la place du premier.

**Reste à faire** : poser un `note_rule_usage` au site d'évaluation des 48 règles restantes, et
verrouiller l'invariant par un test de corpus (toute règle `applicability.kind == "always"` avec
des `controls` non vides doit avoir au moins un site d'incrément). Interdire aussi l'état
incohérent `exercised == 0 and errors > 0` dans `coverage_rows`.

⚡ Peut démarrer pendant un entraînement (ne touche ni `config/**/*.json` ni le moteur).

---

## Faux positifs `shoot_over_rng_nb` {#faux-positifs-plafond-tir}

**✅ LIVRÉ (2026-09-02)** — Run de 300 épisodes : **5187 → 2243 erreurs**, dont `surcharge_atk` 4879 → 1935.

Deux causes traitées, toutes deux dans le calcul de `max_allowed_shots` (`shoot_handler.py`) :

1. **Gate `oath_target` erroné** (régression du jour même) — le bonus Hail of Bolts avait été conditionné à `target_id == oath_target` sur la foi d'un finding de code review. Le moteur dit l'inverse, explicitement : « la cible de l intent EST la cible designee » (`shared_utils.py`), sans aucun filtre. Le gate faisait tomber le plafond dès qu'une escouade répartissait son tir sur une seconde cible. **2432 faux positifs.**
2. **Capacités d'unité non propagées aux personnages rattachés (19.04)** — `atk_bonus_by_weapon` était résolu par datasheet individuelle, comme le NB. Or 19.04 : « abilities/rules that affect a unit apply to EVERY model in an attached unit ». Un Ancient rattaché à une escouade Intercessor tire donc son Bolt Rifle avec +2 A, ce que le moteur lui accorde déjà. **512 faux positifs.**

Nouveau `unit_ability_attack_cap` (`analyzer_perfig.py`), jumeau INVERSE de `per_model_attack_cap` : ce qui est intrinsèque à l'arme (NB, RAPID FIRE, BLAST, CLEAVE, SUSTAINED HITS) reste par-figurine ; ce qui vient d'une capacité d'unité se propage à tout le socle attaché.

Verrous : `test_analyzer_unit_ability_attached_19_04.py`, `test_analyzer_hail_of_bolts.py`.

**✅ LIVRÉ (2026-09-02) — 1935 → 0 `surcharge_atk` restants** : deux capacités Primitive B absentes de `max_allowed_shots` :

3. **`weapon_attacks_bonus_vs_keyword` (Dakkablitz / BigMekDakkarig)** — +6 A au Blitzcannon si cible hors MONSTER/VEHICLE. `excluded_keywords` absent du registre JSON (tableau TS silencieusement ignoré par le parseur). Fix : `unit_registry.py` parse désormais les tableaux de chaînes dans `rule_args`. Nouveau `unit_ability_atk_bonus_vs_keyword_cap` dans `analyzer_perfig.py`.
4. **`grant_weapon_rule_vs_designated_target` (Overlapping Detonations / EradicatorHeavyBolter×2+Sergent)** — +`target_size//5` A au Heavy Bolter vs non-MONSTER/VEHICLE. Nouveau `unit_blast_per5_nonmv_bonus` dans `analyzer_perfig.py`. `unit_upper_keywords_by_type` ajouté à `AnalyzerConfig` pour vérifier les mots-clés de la cible.

Verrous : `test_analyzer_dakkablitz.py` (4 verts), `test_analyzer_overlapping_detonations.py` (6 verts).

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
