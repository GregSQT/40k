# Archives Hygiène documentaire — Chantiers livrés

| Date | Chantier | Détail |
|---|---|---|
| 2026-08-18 | Passe liens : l'ancre `#fragment` confrontée | `scripts/check_doc_references.py` coupait le fragment avant résolution : 45 des 48 liens du corpus en portent un, donc 94 % des liens n'étaient vérifiés qu'à moitié et un titre renommé gardait son lien vert. Le fragment est désormais confronté aux ancres offertes par le `.md` visé (ancres déclarées `{#slug}` + slugs des titres) ; `#L123` reste à la passe 4 ; compteur `fragments` dans le rapport |
| 2026-08-18 | Partition roadmap finalisée + direction | `ROADMAP_INDEX.md` reçoit le fil (cap démo, jalons J1→J5) ; 6 items perdus par la partition réintégrés (MCTS §10.7, dette G1/G2/G4, corpus-regles, bandeaux §0bis, LoS mur/étage, bcKey) ; renvois en chemins complets depuis la racine (arbitrage A) ; `scripts/check_doc_references.py` rebranché sur l'index + fichiers sujets ; fossile `archives/ROADMAP.md` gelé ; `indirect_fire_10_07.md` déplacé en `Implémenté/` |
| 2026-08-17 | Partition du ROADMAP monolithique | `Documentation/Implémentation/ROADMAP.md` (1 459 lignes) → `ROADMAP_INDEX.md` + 10 fichiers sujets + `archives/<sujet>.md` |
| 2026-08-13 | Formes uniques extraites | `shared/json_atomic.py` (écriture JSON atomique, 28 sites, verrou statique global `tests/unit/shared/test_json_atomic.py`) ; `tests/_chargeur_script.py` (6 copies de `spec_from_file_location` remplacées) |
| 2026-08-12 | Porte de fusion durcie | `scripts/check_roadmap_declared.py` : 6 passes `/code-review`, verrous prouvés rouges ; calibrage en tête du script (source unique) ; désarmement `ROADMAP_GATE=off` ; l'index vaut déclaration |
| 2026-08-10/12 | Contrôle documentaire outillé | `scripts/check_doc_references.py` : 5 passes (renvois, liens, valeurs, ancres, sortes) ; convention « le symbole, jamais la ligne » |
| 2026-08-10 | Hygiène doc (dissolution 2_Various) | 497 liens réparés ; → `Documentation/Implémentation/Implémenté/hygiene_doc_2026-08-10.md` |
