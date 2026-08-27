# L'empreinte d'une figurine se mesure à SON socle — pile-in et consolidation (2026-08-12)

Sorti de l'arbitrage du chantier [« une primitive commune poser un plan par
figurine »](primitive_poser_plan_par_figurine_2026-08-11.md), relevé par une `/code-review` : la
« source unique » y était atteinte pour le NIVEAU, pas pour l'EMPREINTE.

## Le défaut

Le pile-in et la consolidation sont des mouvements **par figurine**. Leurs six fonctions
préparaient pourtant leurs offsets d'empreinte avec `_charge_prepare_footprint_offsets(unit, …)`,
c'est-à-dire au socle de l'**escouade**. Un personnage attaché — socle plus large que la troupe
qu'il rejoint — y était donc **sous-empreinté** : le pool lui proposait des cases calculées sur une
fraction de la place qu'il occupe, et le commit, qui mesure par-figurine, les refusait ensuite.
C'est la divergence pool/commit que ce dépôt a déjà payée plusieurs fois.

Deux commentaires disaient littéralement « Empreintes par-figurine du plan » **juste au-dessus** du
calcul au socle d'escouade : le code contredisait sa propre docstring.

## Ce que la mesure a donné, et ce qu'elle a corrigé dans le discours

| Mesure | Résultat |
|---|---|
| Figurines au socle ≠ escouade (14 scénarios) | **67 / 684**, dans 11 scénarios dont un d'entraînement |
| dont l'empreinte change réellement | **67 / 67** |
| dont **sous**-empreintées | **67 / 67** |
| Écart d'empreinte | 19 hex → 43 hex (×2,3), jusqu'à 61 (×3,2) |
| **Effet sur le POOL** (personnage attaché) | **3 cases sur 330** proposées à tort, 0 perdue |

La dernière ligne est celle qui compte pour juger le chantier : le facteur ×2,3 sur l'empreinte ne
se traduit **pas** par ×2,3 sur les destinations. Seules les cases proches d'un obstacle
discriminent — 0,9 % du pool. Le défaut est réel et va toujours dans le même sens (des cases
offertes que le commit refuse), mais son ampleur en jeu est modeste. Annoncer « l'empreinte
double » sans ce chiffre aurait été trompeur.

## La forme livrée

`_fight_model_fp_pair(game_state, model_entry)` — source unique côté fight — rend les offsets au
socle de la figurine, via `_charge_offsets_for_base`, dont le cache est indexé par **socle**
(forme, taille, orientation) et non par unité : deux figurines de même socle le partagent.

Les **21 sites** de `fight_handlers` y passent : 13 empreintes et 8 préparations, sur six
fonctions — pool, preview et état de plan, pour le pile-in comme pour la consolidation. Les offsets
restent préparés **une fois hors boucle** là où une seule figurine est en jeu ; ils le sont par
figurine seulement dans les boucles qui en parcourent plusieurs.

⚠️ **Le routage par `_charge_model_footprint` a été essayé et écarté** : cette enveloppe refait un
accès de cache à chaque cellule, dans des BFS qui en balaient des milliers. Mesuré sur 20 000
empreintes : 1,05× le coût de la forme préparée. Faible, mais évitable gratuitement.

## Ce qui n'est PAS touché, et pourquoi

Les 21 sites équivalents de `charge_handlers` restent au socle d'escouade. Ils appartiennent tous
au pool d'**ancres** du bloc — aperçu d'empreinte, résolution du clic, contacts socle-à-socle de
l'ancre, BFS inverse, validation de destination — où aucune figurine individuelle ne circule. Les
13 empreintes et 8 préparations ont été lues une par une pour l'établir, pas extrapolées.

## Verrous (tests/unit/engine/test_pile_in_empreinte_par_figurine.py)

Six tests, un par fonction migrée, sur `scenario_attached_unit_test.json`. Défaut remis dans
`_fight_model_fp_pair` → **les six rougissent** ; rétabli → verts.

⚠️ Mis à jour le 2026-08-12 par le chantier d'ENGAGEMENT : l'espion ne surveillait que
`_candidate_footprint_charge`, et le preview de pile-in ne l'appelle plus (l'entrée d'engagement
recalcule son empreinte au socle de la figurine). Il surveille désormais **les deux** sources
d'empreinte par-figurine, `_candidate_footprint_charge` et `_synth_model_entry`.

**Aucun test du dépôt ne couvrait ce cas** : les 84 tests de pile-in et de combat passaient avec le
défaut en place. C'est ce qui a rendu le chantier possible sans que rien ne signale jamais rien.

Deux pièges rencontrés en écrivant ces verrous, tous deux attrapés par l'assertion « aucune
empreinte calculée » — sans elle, deux tests auraient été verts en ne regardant rien :

- le preview de consolidation attend `mode="engaging"` ; un mode inconnu le fait sortir avant tout
  calcul ;
- l'état de plan de consolidation n'a de mode — donc de calcul — que dans une situation de jeu
  réelle (12.08). Le test met donc un ennemi au contact (branche `ongoing`) **et le retire
  ensuite** : le `game_state` est partagé par le module, une mise en scène non défaite ferait
  dépendre les tests suivants de l'ordre d'exécution.

## ⚠️ Ce que ce chantier NE corrige PAS — les VERDICTS d'engagement

Relevé par la `/code-review` de la livraison, puis **confirmé par mesure** : les empreintes
par-figurine calculées ici sont passées à `_charge_synthetic_charger_cache_entry`, qui construit
son entrée en copiant la ligne `units_cache` de l'**escouade**. Le test d'engagement reconstruit
alors le socle depuis la base de cette entrée et **ne lit jamais** l'`occupied_hexes` fourni.

Mesuré sur le personnage attaché de `scenario_attached_unit_test.json`, à 13 distances de la
cible : le verdict est **identique** que l'empreinte transmise fasse 19 ou 43 hexes. 0 divergence
sur 13.

Autrement dit, ce chantier corrige les **destinations proposées** (le pool), pas les **verdicts
d'engagement** — `kept_engagements`, `unit_engaged`, `engaged`, le voile vert. Un personnage
attaché y reste mesuré au socle du bloc.

La voie est identifiée et déjà dans le dépôt : `shared_utils._synth_model_entry`, documentée comme
la SOURCE UNIQUE de l'engagement par-figurine (« la géométrie de base provient du MODÈLE, pas du
squad — seul choix correct pour une unité à bases mixtes »), déjà importée par `fight_handlers` et
utilisée à un seul endroit. **Onze** sites de `fight_handlers` construisent une entrée
d'engagement de figurine avec le socle d'escouade, plus deux au niveau unité
(`_fight_synth_cache_entry_at_footprint`) à examiner, et `charge_handlers` porte probablement les
mêmes. Chantier distinct : il touche la sémantique de l'engagement (12.03 / 12.08), pas une
géométrie de pool.

→ **Livré le même jour** : [« l'ENGAGEMENT d'une figurine se mesure à SON
socle »](engagement_par_figurine_socle_2026-08-12.md). Le compte final est de 13 sites par-figurine
(11 fight + 2 charge) et 3 sites de niveau unité ; les verdicts basculent sur 3,7 % des positions.

## Ce qui n'est pas mesuré

L'effet sur l'agent entraîné. L'espace de décision du pile-in change, comme l'a fait le chantier
« socle vs mur » du 2026-08-11 ; seul un run le dirait.

Aucun exercice PvP en conditions réelles du pile-in d'un personnage attaché : la vérification
s'arrête aux appels directs des six fonctions migrées.
