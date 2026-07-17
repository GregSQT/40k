# Analyzer — contrôle LoS de tir ancre-à-ancre vs LoS per-figurine du moteur

Découvert le 2026-07-16 pendant V11 T6, dès que `ai/analyzer.py` a pu tourner sur le pipeline
squad. **VERDICT ÉTABLI le 2026-07-16 : hypothèse (A)** — faux positifs de l'analyzer.
Pas de bug moteur, **backend non modifié**.

**TRAITÉ le 2026-07-16** (option (c), voir « Décision ») : contrôle supprimé de l'analyzer,
vérification déplacée en test unitaire moteur. `1.2 Erreurs en phase de shooting` : 12 → **0**.
Deux dettes découvertes restent ouvertes (voir « RESTE À FAIRE »).

## VERDICT : (A), établi par le code ET par la règle 06.01

**Règle 06.01 (« 06 Other concepts.pdf », lue)** : « For an observing model to have line of
sight, it must be possible to draw an imaginary straight line, 1 mm wide, **from any part of
that model to any part of the model being observed** ». La LoS est donc socle-à-socle, PAR
FIGURINE. Un test ancre-à-ancre (un point contre un point) contredit la règle : il est
strictement plus restrictif que « any part to any part ».

**Preuve reproductible** (tir litigieux E7 T3 P1 `Unit 4(215,155) SHOT Unit 104(116,66)`,
murs relus depuis la dernière ligne `Walls:` précédant le tir, board 44x60 `inches_to_subhex=5`) :

Empreintes obtenues via la primitive DU MOTEUR (`_compute_unit_occupied_hexes`) : un socle
`round/6` = **19 hexes (rayon 2)** sur le board actif (`engagement_zone=2 > 1`, donc les
empreintes multi-hex sont bien calculées — sur un board `engagement_zone <= 1` elles
retomberaient à 1 cellule et per-fig == ancre).

| Test | Résultat |
|---|---|
| `compute_los_state(215,155,116,66, walls+bordure)` | `ratio=0.0`, `can_see=False` |
| idem sans la bordure | `can_see=False` (⇒ suspect « bordure » écarté) |
| Cellules de l'empreinte du socle tireur (19 hexes) qui VOIENT l'ancre cible | **3 / 19** |
| Paires (socle tireur × socle cible) avec LoS | **66 / 361** |

Aucune exception n'est levée (`compute_los_state` brut et `has_line_of_sight` rendent le même
`False`) ⇒ **suspect `except Exception: return False` écarté**. La ligne `Walls:` est complète
(557 murs) et l'ajout de bordure ne change pas le verdict ⇒ **suspect « murs incomplets » écarté**.

3 cellules sur 19 **de l'empreinte du socle tireur** voient la cible alors que l'ancre exacte
ne la voit pas : c'est mot pour mot le faux positif décrit par le docstring de
`_attacker_model_can_reach_squad` (« une grosse base dont le centre est masqué par un terrain,
mais dont un bord voit la cible »). La distance (139 subhex = 27.8") est dans la portée du
Heavy Bolter (36") — la portée n'est pas en cause.

## ROOT CAUSE — plus profonde que « ancre-à-ancre »

`engine/phase_handlers/shared_utils.py:5758-5761` (`_emit_squad_shoot_log`) :

```python
ac = int(sq_uc.get("col", 0))   # units_cache du SQUAD attaquant
ar = int(sq_uc.get("row", 0))
tc = int(tgt_uc.get("col", 0))  # units_cache du SQUAD cible
tr = int(tgt_uc.get("row", 0))
```

Le step.log journalise **ancre d'escouade ↔ ancre d'escouade**. Or le moteur décide la LoS
per-figurine : `_attacker_model_can_reach_squad(game_state, attacker_model, ac, ar, ...)`
(shared_utils:4483 et :5299) où `ac,ar` est l'ancre de **la figurine qui tire**, contre
l'empreinte de **chaque figurine cible**.

⇒ **Les points que l'analyzer teste ne sont PAS les points que le moteur a testés.** L'ancre
d'escouade peut n'être la position d'aucune figurine tireuse. Le contrôle de l'analyzer ne
re-litige donc même pas la décision du moteur : il évalue un prédicat sur des entrées que le
moteur n'a jamais utilisées. Les 6 `shoot_through_wall` + 6 `shoot_invalid.no_los` (les mêmes
6 tirs) sont des faux positifs.

Deux violations CLAUDE.md au passage, mêmes lignes : `.get("col", 0)` — valeur par défaut qui
masque une clé manquante — et `has_line_of_sight` (`ai/analyzer.py:630`) `except Exception:
return False`, qui refuse la LoS silencieusement.

⚠️ Corollaire : l'affirmation « la journalisation V11 T6 est fidèle et exacte » (plus bas) est
**fausse pour les coordonnées**. Les jets (Hit/Wound/Save/Dmg) sont exacts ; les coords non.

## Décision — option (c) : contrôle SUPPRIMÉ, vérification DÉPLACÉE (faite le 2026-07-16)

Trois options étaient sur la table. Les deux premières sont rejetées :

**(i) « le StepLogger loggue le verdict LoS du moteur, l'analyzer ne recalcule plus » —
REJETÉE : circulaire.** Un tir ne peut PAS être résolu sans avoir passé le gate
`_attacker_model_can_reach_squad` (shared_utils:4483/:5299). Le verdict loggué vaudrait `true`
par construction sur 100 % des lignes. Le contrôle deviendrait « le moteur dit que c'est bon,
donc c'est bon » : valeur de détection nulle, incapable par construction d'attraper le bug
moteur qu'il est censé attraper.

**(ii) « l'analyzer recalcule depuis une géométrie per-figurine loggée » — REJETÉE : le coût
réel est prohibitif et l'énoncé « importer les primitives du moteur, zéro ré-implémentation »
est faux.** Vérifié : `_compute_unit_occupied_hexes` exige `game_state`
(`ConfigurationError: Required key 'config'`), et `_compute_visibility_with_obscuring` exige en
plus `obscuring_by_hex`, `floor_occluders`, `z_start/z_end` (terrain obscurcissant 13.10 + LoS
3D). Rien de tout ça n'est dans step.log. Fidèle ⇒ il faudrait logger de quoi reconstruire un
game_state quasi complet (dérive garantie) ; dégradé (sans obscuring/3D) ⇒ plus permissif,
détecte seulement le grossier, et re-dérive.

**(c) RETENUE.** Un contrôle post-hoc sur step.log est *structurellement* incapable d'être
correct : le log ne portera jamais l'état 3D complet. Et le tir est déjà gaté à la source ;
pour détecter un bug *dans* ce gate il faut un test indépendant qui dispose de `game_state` —
donc un test unitaire, pas un parseur de log. Ce n'est pas masquer l'erreur (CLAUDE.md) : la
vérification n'est pas supprimée, elle est déplacée là où elle peut être juste.

Fait :
1. `ai/analyzer_phases/shoot_handler.py` : bloc `shoot_through_wall` / `shoot_invalid['no_los']`
   supprimé (commentaire explicatif en place).
2. `ai/analyzer.py` : compteurs `shoot_through_wall` et clé `no_los` retirés (init, agrégats,
   rapport). `has_line_of_sight` CONSERVÉE — elle sert encore à deux métriques
   comportementales (shoot_handler:514 « a vu une cible blessée », :627 « a attendu sans vue »),
   où une approximation est sans conséquence ; son docstring dit désormais explicitement de ne
   PAS l'utiliser pour un contrôle de règle.
3. `except Exception: return False` supprimé (CLAUDE.md).
4. Vérification déplacée : `tests/unit/engine/test_shoot_los_perfig_parity.py` (4 tests, dont un
   garde-fou « l'empreinte est bien multi-hex » et une contre-épreuve « mur plein → 0 visible »).
   Régression analyzer verrouillée : `tests/unit/ai/test_analyzer_no_anchor_los_false_positive.py`.

Résultat sur le step.log réel : `✅ 1.2 Erreurs en phase de shooting : 0` (était 12), sans
erreur résiduelle. Suite unitaire verte, `smoke_t5_bare.py` = `(A) OK | (B) OK`.

## RESTE À FAIRE — deux dettes découvertes, non traitées

1. **Fidélité des coords du step.log** (`_emit_squad_shoot_log`, shared_utils:5758) : logguer la
   figurine tireuse au lieu de l'ancre d'escouade, et supprimer les `.get("col", 0)`. Non fait
   ici car ça change la sémantique des coords pour TOUS les contrôles de l'analyzer qui les
   consomment (adjacence, portée, `hidden_action_finder`) → chantier à part entière.
   Contrainte identifiée : `weapon_groups` est clé par profil d'arme × cible
   (shared_utils:6354) et agrège plusieurs tireuses ⇒ l'estampille doit être PAR JET, à
   `g["shots"].extend(r["shot_records"])` (shared_utils:6377), où `attacker_mid` est disponible ;
   les `shot_records` n'en portent aucune trace aujourd'hui.
2. **`shoot_invalid['out_of_range']` a le même défaut latent** : distance ancre-à-ancre alors
   que le moteur mesure bord-à-bord (`ranged_edge_distance`, règle 01.04). Il rend 0 sur ce run
   faute de tir à la limite de portée, pas parce qu'il est correct.

---

⚠️ **Il n'y a AUCUNE divergence training/PvP** : le moteur est unique et pilote les deux.
Le soupçon porte sur le **vérificateur**, pas sur le jeu.

---

## Prompt d'origine (archivé)

Le prompt initial d'investigation a été retiré : le travail est fait et son contenu induirait en
erreur (il posait les voies (i)/(ii) comme le chemin de correction — toutes deux rejetées, voir
« Décision »). Son exigence utile a été respectée : trancher (A)/(B) AVANT toute correction.

## Repro

```bash
# 1) produire un step.log réel (le run est coupé par le timeout : c'est normal, pas une erreur)
source /home/greg/40k/.venv/bin/activate
rm -f step.log
timeout 900 python3 ai/train.py --agent CoreAgent --scenario bot --new \
    --training-config x1_debug --step

# 2) analyser
python3 ai/analyzer.py step.log --n
grep -E "^(✅|❌) 1\.2" analyzer.log
#   AVANT le fix -> ❌ 1.2 Erreurs en phase de shooting : 12
#   APRÈS le fix -> ✅ 1.2 Erreurs en phase de shooting : 0

# 3) décomposer
python3 - <<'EOF'
import sys; sys.path.insert(0,'.')
import ai.analyzer as an
s = an.parse_step_log("step.log")
print("shoot_invalid :", s['shoot_invalid'])
#   -> P1 {'total': 9, 'out_of_range': 0, 'adjacent_non_pistol': 0}
EOF
```

⚠️ Les clés `shoot_through_wall` et `shoot_invalid[...]['no_los']` **n'existent plus** : le
script de décomposition d'origine (qui les lisait) lèverait un `KeyError`.

⚠️ `--step` force `n_envs=1` (le StepLogger n'est branché que sur le chemin mono-env) : c'est un
mode de VALIDATION, pas d'entraînement rapide. `--new` écrase `ai/models/CoreAgent/model_CoreAgent.zip`
(modèle obsolète, écrasement autorisé par l'utilisateur le 2026-07-16 — `ai/models/` est gitignoré,
aucune récupération git possible : re-confirmer avant de relancer).

## Cas concret observé (2026-07-16)

```
[15:13:51] E7 T3 P1 SHOOT : Unit 4(215,155) SHOT Unit 104(116,66) with [Heavy Bolter]
           - Hit 2(3+) [R:+0.0] [SUCCESS]
```
Hypothèse (A) **DÉMONTRÉE** sur ce tir (voir « VERDICT ») : l'ancre ne voit pas, 3 des 19
cellules de l'empreinte du socle voient. La distance (139 subhex = 27.8") est dans les 36" du
Heavy Bolter — ce n'est PAS un tir « de bout en bout du board » comme supposé initialement.

## Ce qui n'est PAS en cause

- **La LoS du jeu** : moteur unique, mêmes règles en training et en PvP. Le tir passe par
  `_attacker_model_can_reach_squad` dans les deux cas. Confirmé : aucun bug moteur, backend
  non modifié.
- **La journalisation V11 T6, pour les JETS uniquement** : `Hit 6(3+) - Wound 5(5+) -
  Save 1(4+) - Dmg:2HP` ; un MISS ne rend que `Hit 2(3+)`. Fidèle et exact.

⚠️ **En revanche les COORDONNÉES de la journalisation V11 T6 sont fausses** (ancre d'escouade au
lieu de la figurine) — l'affirmation d'origine « les lignes produites sont fidèles et exactes »
ne vaut que pour les jets. C'est la dette n°1 de « RESTE À FAIRE ».

## Lien

`Documentation/Implémentation/V11_agent_rework.md` — section T6-c (résultat sur le vrai run) et
rupture R8 (chantier LoS 3D, `spatial_relations.py:186-189` « câblage incomplet »).
