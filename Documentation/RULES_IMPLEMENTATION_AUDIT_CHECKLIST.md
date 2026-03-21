# Rules Implementation Audit Checklist

Objectif: déterminer si une regle declaree (`config/unit_rules.json`) peut etre marquee `2 (IMPLEMENTED)` de maniere fiable.

## Statuts

- `0` = `NOT_IMPLEMENTED`
- `1` = `NOT_IMPLEMENTABLE_YET`
- `2` = `IMPLEMENTED`

## Methode de validation (obligatoire)

Une regle passe en `2` seulement si les 3 couches sont validees:

1. **Statique (code)**: la regle est consommee dans les handlers moteur et modifie le gameplay (pas seulement UI/log).
2. **Completeness**: les cas attendus (positifs + negatifs + limites) sont couverts.
3. **Runtime**: scenario(s) de validation reproductibles passes.

---

## Audit statique actuel (preliminaire)

Ce tableau est un **pre-audit statique** base sur le code moteur actuel.
Il donne une proposition, a confirmer par tests runtime.

| ruleId | Preuve statique (handlers) | Statut propose (statique) | Notes |
|---|---|---:|---|
| `charge_after_advance` | `engine/phase_handlers/charge_handlers.py` | 2 | Verifie eligibility/applique exception apres advance |
| `charge_after_flee` | `engine/phase_handlers/charge_handlers.py` | 2 | Verifie eligibility/applique exception apres flee |
| `charge_impact` | `engine/phase_handlers/charge_handlers.py`, `engine/w40k_core.py` | 2 | Effet post-charge + logs action |
| `closest_target_penetration` | `engine/phase_handlers/shooting_handlers.py` | 2 | AP modifiee sur cible eligibile la plus proche |
| `reactive_move` | `engine/phase_handlers/shared_utils.py`, `movement_handlers.py`, `shooting_handlers.py`, `w40k_core.py` | 2 | Fenetre reactive complete + invalidation caches |
| `reroll_1_save_fight` | `engine/phase_handlers/fight_handlers.py` | 2 | Reroll save de 1 en fight |
| `reroll_1_tohit_fight` | `engine/phase_handlers/fight_handlers.py` | 2 | Reroll hit de 1 en fight |
| `reroll_1_towound` | `engine/phase_handlers/fight_handlers.py`, `shooting_handlers.py` | 2 | Reroll wound de 1 en tir + fight |
| `reroll_towound_target_on_objective` | `engine/phase_handlers/fight_handlers.py`, `shooting_handlers.py` | 2 | Full reroll wound si condition objectif |
| `shoot_after_advance` | `engine/phase_handlers/shooting_handlers.py` | 2 | Exception explicite dans check tir apres advance |
| `shoot_after_flee` | `engine/phase_handlers/shooting_handlers.py` | 2 | Exception explicite dans check tir apres flee |
| `move_after_shooting` | `engine/phase_handlers/shooting_handlers.py`, `engine/phase_handlers/charge_handlers.py` | 2 | Mouvement post-tir + blocage charge jusqu'a la fin du tour |
| `adaptable_predators` | grants -> `shoot_after_flee`, `charge_after_flee` | 2 | Regle composee; depend du systeme grants |
| `adaptable_predators_shoot_after_flee` | alias -> `shoot_after_flee` | 2 | Alias d'affichage |
| `adaptable_predators_charge_after_flee` | alias -> `charge_after_flee` | 2 | Alias d'affichage |
| `adrenalised_onslaught` | grants `or` + `choice_timing` via `w40k_core.py` | 2 | Selection runtime d'une option en phase fight |
| `aggression_imperative` | alias -> `reroll_1_tohit_fight` | 2 | Alias d'affichage |
| `preservation_imperative` | alias -> `reroll_1_save_fight` | 2 | Alias d'affichage |
| `cunning_hunters` | grants -> `shoot_after_advance`, `shoot_after_flee` | 2 | Regle composee |
| `cunning_hunters_shoot_after_advance` | alias -> `shoot_after_advance` | 2 | Alias d'affichage |
| `cunning_hunters_shoot_after_flee` | alias -> `shoot_after_flee` | 2 | Alias d'affichage |
| `targeted_intercession` | grants -> reroll wound rules | 2 | Regle composee |
| `targeted_intercession_reroll_1_towound` | alias -> `reroll_1_towound` | 2 | Alias d'affichage |
| `targeted_intercession_reroll_towound_target_on_objective` | alias -> `reroll_towound_target_on_objective` | 2 | Alias d'affichage |

---

## Checklist runtime par famille de regles

### A. Permissions d'action

Regles: `shoot_after_advance`, `shoot_after_flee`, `charge_after_advance`, `charge_after_flee`

- [ ] Cas positif: action autorisee quand la regle est presente
- [ ] Cas negatif: action refusee sans la regle
- [ ] Cas limite: interaction avec autres restrictions de phase
- [ ] Log explicite present (source display rule)

### B. Modificateurs de combat

Regles: `closest_target_penetration`, `reroll_1_towound`, `reroll_towound_target_on_objective`, `reroll_1_tohit_fight`, `reroll_1_save_fight`

- [ ] Cas positif: modificateur applique
- [ ] Cas negatif: modificateur non applique hors condition
- [ ] Cas limite: cible sur/ hors objectif, combat vs tir, cible la plus proche vs autre
- [ ] Verification des logs de source de regle

### C. Reactions / effets post-action

Regles: `reactive_move`, `charge_impact`

- [ ] Cas positif: effet declenche dans la fenetre attendue
- [ ] Cas negatif: pas de declenchement hors fenetre
- [ ] Cas limite: refus joueur/IA, destination invalide, cache refresh
- [ ] Verification action logs + coherence des positions

### D. Regles composees (grants/alias/choice)

Regles: `adaptable_predators*`, `cunning_hunters*`, `targeted_intercession*`, `adrenalised_onslaught`, `aggression_imperative`, `preservation_imperative`

- [ ] `alias` resolu vers regle technique correcte
- [ ] `grants_rule_ids` actifs selon `usage` (`and` / `or` / `unique`)
- [ ] `choice_timing` declenche au bon moment
- [ ] Option selectionnee effectivement appliquee

---

## Regles en alerte

Aucune alerte ouverte dans l'etat actuel du pre-audit statique.

