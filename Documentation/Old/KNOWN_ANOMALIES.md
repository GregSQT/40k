# Known Anomalies

Objectif: tracer explicitement les comportements anormaux detectes par les tests, sans les perdre entre iterations.

## Convention de suivi (generalisee)

- Identifiant obligatoire: `ANOM-XXX` (ex: `ANOM-001`)
- Chaque anomalie doit avoir:
  - un test sentinelle (`pytest.mark.anomaly`)
  - un `xfail` avec `reason` contenant l'identifiant
  - un statut clair (`ouvert`, `en_cours`, `corrige`)
- Quand une anomalie est corrigee:
  - retirer le `xfail` du test sentinelle
  - mettre le statut de l'entree a `corrige`
  - garder l'entree pour l'historique (ne pas supprimer)

## Template d'entree

Copier-coller:

```text
## ANOM-XXX - <titre court>
- Module: `<chemin_module>`
- Zone: <zone/fonction concernee>
- Symptome: <comportement observe>
- Impact: <impact metier/technique>
- Reproduction: <fichier test sentinelle>
- Statut: ouvert | en_cours | corrige
- Priorite: basse | moyenne | haute
- Detection: <contexte de decouverte>
```

## ANOM-001 - Dice expression `D6+1` tronquee en `D6` au parsing armory

- Module: `engine/weapons/parser.py`
- Zone: extraction des champs `NB` / `DMG` depuis les fichiers `armory.ts`
- Symptome:
  - une valeur comme `DMG: D6+1` est interpretee comme `D6`
  - effet probable: sous-estimation des degats attendus pour certaines armes
- Impact:
  - divergence entre la definition TypeScript (source de verite) et le comportement Python en runtime
  - peut biaiser IA, simulation, et affichage derive des stats
- Reproduction:
  - test sentinelle: `tests/unit/engine/test_weapon_parser.py` (`test_parse_armory_file_extracts_weapon_and_resolves_dice_constant`)
- Statut: corrige
- Priorite: haute
- Detection:
  - detecte pendant la mise en place des tests unitaires (lot parser/rules)

## ANOM-002 - Crash `I/O operation on closed file` dans `hidden_action_finder.main()`

- Module: `ai/hidden_action_finder.py`
- Zone: fonction `main()` (retours anticipes + bloc `finally`)
- Symptome:
  - quand `debug.log` ou `step.log` est absent, la fonction fermait `output_f` avant le `finally`
  - `log_print()` tentait ensuite d'ecrire dans un fichier deja ferme (`ValueError`)
- Impact:
  - faux crash en fin d'execution qui masque le vrai message d'erreur metier (`debug.log introuvable`/`step.log introuvable`)
- Reproduction:
  - test sentinelle: `tests/unit/ai/test_hidden_action_finder.py` (`test_main_reports_missing_debug_log`)
- Statut: corrige
- Priorite: moyenne
- Detection:
  - detecte pendant l'extension de couverture unitaire du module `hidden_action_finder`
