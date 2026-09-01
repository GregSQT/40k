# Analyzer — Tâches ouvertes

Découpage en 6 lots des trois sujets ci-dessous (ordre séquentiel imposé : tous éditent `ai/analyzer*.py`) → `Documentation/Archives/chantiers/analyzer_conformite_lots.md` ✅ TOUS LIVRÉS

---

## Faux positifs `shoot_over_rng_nb` {#faux-positifs-plafond-tir}

**✅ LIVRÉ (2026-09-02)** — Run de 300 épisodes : **5187 → 2243 erreurs**, dont `surcharge_atk` 4879 → 1935.

Deux causes traitées, toutes deux dans le calcul de `max_allowed_shots` (`shoot_handler.py`) :

1. **Gate `oath_target` erroné** (régression du jour même) — le bonus Hail of Bolts avait été conditionné à `target_id == oath_target` sur la foi d'un finding de code review. Le moteur dit l'inverse, explicitement : « la cible de l intent EST la cible designee » (`shared_utils.py`), sans aucun filtre. Le gate faisait tomber le plafond dès qu'une escouade répartissait son tir sur une seconde cible. **2432 faux positifs.**
2. **Capacités d'unité non propagées aux personnages rattachés (19.04)** — `atk_bonus_by_weapon` était résolu par datasheet individuelle, comme le NB. Or 19.04 : « abilities/rules that affect a unit apply to EVERY model in an attached unit ». Un Ancient rattaché à une escouade Intercessor tire donc son Bolt Rifle avec +2 A, ce que le moteur lui accorde déjà. **512 faux positifs.**

Nouveau `unit_ability_attack_cap` (`analyzer_perfig.py`), jumeau INVERSE de `per_model_attack_cap` : ce qui est intrinsèque à l'arme (NB, RAPID FIRE, BLAST, CLEAVE, SUSTAINED HITS) reste par-figurine ; ce qui vient d'une capacité d'unité se propage à tout le socle attaché.

Verrous : `test_analyzer_unit_ability_attached_19_04.py`, `test_analyzer_hail_of_bolts.py`.

**Reste ouvert** : 1935 `surcharge_atk` de cause DIFFÉRENTE — armes à [SUSTAINED HITS] (Heavy Bolter, Blitzcannon). Piste : le gate `is_sustained_hit_line` qui doit exclure du comptage les lignes de touche additionnelle. Non diagnostiqué.

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
