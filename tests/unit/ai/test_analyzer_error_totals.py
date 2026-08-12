"""Les totaux d'erreurs sont UN seul calcul — le rapport ne peut plus se contredire lui-même.

`move_errors` / `shooting_errors` / … existaient en DEUX exemplaires : celui du SUMMARY imprimé
par `print_statistics`, et celui du total renvoyé par la CLI. Ils avaient divergé en silence sur
deux compteurs :

    §1.1  move_after_shooting_distance_over_limit   ← absent du total CLI
    §1.2  shoot_combi_profile_conflicts             ← absent du total CLI

Effet observable : un run pouvait afficher « ❌ 1.1 Erreurs en phase de move : 2 » et rendre un
total qui n'en comptait aucune. C'est le total, plus court, qu'on lit en premier.

Ce fichier verrouille les deux propriétés qui font qu'un compteur ne peut plus se perdre :

  1. `error_totals` voit RÉELLEMENT chaque compteur qu'il prétend sommer (test exhaustif : on
     pose 1 dans un compteur à la fois et on vérifie que le bucket bouge). Un compteur oublié
     dans la somme ne se voit pas autrement — c'est exactement ainsi que les deux du dessus ont
     survécu à trois relectures.
  2. Le SUMMARY et le total CLI sont bâtis sur le MÊME objet. La duplication ne peut pas
     réapparaître sans que le test 1 devienne insuffisant, donc sans qu'on le sache.
"""
from __future__ import annotations

import pytest

import ai.analyzer as an
from tests.unit.ai._fabriques import entete_step_log


#: Compteur → bucket de `error_totals` qui DOIT l'inclure. Cette table est le contrat : y ajouter
#: une ligne quand on ajoute un compteur d'erreur, et le test dira si la somme l'a oublié.
COUNTERS = {
    'move': [
        ('wall_collisions',),
        ('move_to_adjacent_enemy',),
        ('move_adjacent_before_non_flee',),
        ('move_distance_over_limit', 'move'),
        ('move_after_shooting_distance_over_limit',),
        ('move_distance_over_limit', 'flee'),
        ('flee_from_unengaged',),
        ('flee_still_engaged',),
        ('reactive_move_checks', 'to_adjacent_enemy'),
        ('reactive_move_checks', 'into_wall'),
        ('reactive_move_checks', 'distance_over_roll'),
    ],
    'shooting': [
        ('shoot_over_rng_nb',),
        ('shoot_combi_profile_conflicts',),
        ('shoot_after_flee',),
        ('shoot_at_friendly',),
        ('shoot_at_engaged_enemy',),
        ('close_quarters_shot_at_unengaged_target',),
        ('advance_after_shoot',),
        ('advance_twice_in_shoot_phase',),
        ('move_distance_over_limit', 'advance'),
        ('advance_from_adjacent',),
        ('shoot_hit_result_mismatch',),
        ('shoot_wound_threshold_mismatch',),
        # `shoot_not_allocated_target_alive` a quitté cette liste avec le compteur lui-même le
        # 2026-08-12, comme son jumeau de mêlée ci-dessous.
    ],
    'charge': [
        ('charge_from_adjacent',),
    ],
    'fight': [
        ('fight_friendly',),
        ('fight_over_cc_nb',),
        ('fight_move_invalid', 'pile_in'),
        ('fight_move_invalid', 'consolidation'),
        ('fight_hit_result_mismatch',),
        ('fight_wound_threshold_mismatch',),
        ('fight_alternation_violations',),
        # `fight_not_allocated_target_alive` : compteur retiré le 2026-08-12 (faux positifs par
        # construction ; l'invariant 05 est tenu par
        # `tests/unit/engine/test_attack_allocation_contract.py`).
    ],
    'damage': [
        ('damage_missing_unit_hp',),
        ('damage_exceeds_hp',),
    ],
    'dead_units': [
        ('dead_unit_moving',),
        ('shoot_dead_unit',),
        ('shoot_at_dead_unit',),
        ('dead_unit_advancing',),
        ('dead_unit_charging',),
        ('charge_dead_unit',),
        ('fight_dead_unit_attacker',),
        ('fight_dead_unit_target',),
        ('dead_unit_waiting',),
        # `dead_unit_skipping` a quitté cette liste avec le compteur lui-même le 2026-08-10
        # (vert vacant V3) : aucune ligne `SKIP` n'existe dans un step.log.
        ('unit_revived',),
    ],
}

_CASES = [(bucket, path) for bucket, paths in COUNTERS.items() for path in paths]


#: Journal minimal et SANS FAUTE : aucune ligne d'action, juste ce que `parse_step_log` exige.
#: Il sert à obtenir un `stats` neuf par le VRAI chemin d'initialisation — une fabrique de test
#: recopierait la structure et divergerait le jour où un compteur s'ajoute, ce qui est
#: exactement le défaut que ce fichier verrouille.
_EMPTY_LOG = entete_step_log(
    "[10:00:09] EPISODE END: Winner=1, Method=objectives, Actions=0, Steps=0, Total=0, Duration=1.000s\n",
    rosters="scale=5 AGENT_PLAYER=1 AGENT=sm (ref) OPPONENT=sm (ref)",
    objectives=None,
    ez_vertical_inches=None,
)


@pytest.fixture(scope="module")
def _empty_stats(tmp_path_factory) -> dict:
    log = tmp_path_factory.mktemp("totals") / "step.log"
    log.write_text(_EMPTY_LOG)
    return an.parse_step_log(str(log))


def _fresh_stats(_empty_stats: dict) -> dict:
    """Copie profonde du `stats` neuf : chaque test doit partir d'un état vierge."""
    import copy

    return copy.deepcopy(_empty_stats)


def _set(stats: dict, path: tuple, player: int, value: int) -> None:
    node = stats
    for key in path:
        node = node[key]
    node[player] = value


def test_un_stats_neuf_ne_compte_aucune_erreur(_empty_stats):
    """Prémisse : sans elle, tout écart mesuré plus bas pourrait venir du bruit de fond."""
    totals = an.error_totals(_fresh_stats(_empty_stats))
    assert set(totals) >= set(COUNTERS), totals
    for bucket in COUNTERS:
        assert totals[bucket] == 0, bucket


@pytest.mark.parametrize(("bucket", "path"), _CASES, ids=[f"{b}:{'.'.join(p)}" for b, p in _CASES])
def test_chaque_compteur_est_reellement_somme(bucket, path, _empty_stats):
    """Un compteur absent de sa somme est invisible : le bucket reste à 0 et personne ne le sait.

    On pose 1 chez P1 ET chez P2 : une somme qui n'additionnerait qu'un joueur (défaut jumeau,
    déjà vu ailleurs dans ce dépôt) rendrait 1 au lieu de 2 et serait donc attrapée aussi.
    """
    stats = _fresh_stats(_empty_stats)
    _set(stats, path, 1, 1)
    _set(stats, path, 2, 1)
    totals = an.error_totals(stats)
    assert totals[bucket] == 2, (
        f"{'.'.join(path)} n'entre pas (ou pas entièrement) dans le total '{bucket}' : "
        f"obtenu {totals[bucket]}, attendu 2"
    )


def test_les_compteurs_a_deux_niveaux_sont_sommes_aussi(_empty_stats):
    """`shoot_invalid` et `charge_invalid` ont une forme distincte (joueur d'abord, puis champ)."""
    stats = _fresh_stats(_empty_stats)
    for player in (1, 2):
        stats['shoot_invalid'][player]['out_of_range'] = 1
        stats['shoot_invalid'][player]['engaged_non_close_quarters'] = 1
        stats['charge_invalid'][player]['distance_over_roll'] = 1
        stats['charge_invalid'][player]['advanced'] = 1
        stats['charge_invalid'][player]['fled'] = 1
    totals = an.error_totals(stats)
    # `shoot_invalid` n'est PAS exposé comme bucket : il est déjà DANS 'shooting'. L'exposer
    # invitait un appelant à sommer les deux et à compter ces fautes deux fois.
    assert 'shoot_invalid' not in totals
    assert totals['shooting'] == 4
    assert totals['charge'] == 6


def test_les_collisions_de_position_entrent_dans_le_bucket_positions(_empty_stats):
    stats = _fresh_stats(_empty_stats)
    stats['position_log_mismatch']['move']['mismatch'] = 1
    stats['position_log_mismatch']['advance']['mismatch'] = 1
    stats['position_log_mismatch']['charge']['mismatch'] = 1
    stats['unit_position_collisions'].append({'episode': 1})
    assert an.error_totals(stats)['positions'] == 4


#: Clés de listes que le rapport lit SANS garde. Elles doivent être déclarées dans la structure,
#: pas créées à la volée par leur premier producteur.
DECLARED_LIST_KEYS = ('parse_errors', 'unit_position_collisions', 'unit_id_mismatches')


@pytest.mark.parametrize("key", DECLARED_LIST_KEYS)
def test_parse_step_log_rend_une_structure_complete(key, _empty_stats):
    """`parse_step_log` est l'API publique : son `stats` doit être lisible tel quel.

    `unit_id_mismatches` n'y était PAS : la clé n'apparaissait qu'au `setdefault` de
    `print_statistics`, si bien que le total de la CLI portait une garde `if … in stats` pour
    compenser en aval ce qui manquait en amont, et que tout autre lecteur levait KeyError.
    Mesuré le 2026-08-10 : `'unit_id_mismatches' in parse_step_log(...)` rendait False.

    La garde a disparu ; ce test est ce qui la remplace. Il tombe si la clé quitte la structure.
    """
    assert key in _empty_stats, (
        f"'{key}' absente du stats rendu par parse_step_log : le rapport la lit sans garde"
    )
    assert _empty_stats[key] == []


def test_le_producteur_ecrit_toujours_sans_sa_creation_paresseuse(tmp_path):
    """Le `if not in stats` de `shoot_handler` a été retiré : son `.append` doit tenir seul.

    « du code corrigé mais jamais appelé ne corrige rien » — ce test passe par `parse_step_log`,
    donc par le producteur réel. Un `AssaultIntercessor` (Space Marine) qui tire avec un
    `Deathspitter` (arme tyranide absente de son armurerie) est la situation exacte que le
    contrôle cherche.
    """
    log = tmp_path / "step.log"
    log.write_text(
        _EMPTY_LOG.replace(
            "[10:00:00] === ACTIONS START ===\n",
            "[10:00:00] Unit 1 (AssaultIntercessor) P1: Starting position (50,50), HP_MAX=2 base=round/6\n"
            "[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position (50,56), HP_MAX=2 base=round/6\n"
            "[10:00:00] === ACTIONS START ===\n"
            "[10:00:02] E1 T1 P1 SHOOT : Unit 1(50,50) SHOT Unit 101(50,56) with [Deathspitter]"
            " - Hit 4(3+) - Wound 5(4+) - Save 2(3+) - Dmg:1HP [R:+0.0] [SUCCESS]\n"
        )
    )
    stats = an.parse_step_log(str(log))
    assert len(stats['unit_id_mismatches']) == 1, stats['unit_id_mismatches']
    assert stats['unit_id_mismatches'][0]['weapon_logged'] == "Deathspitter"


def test_aucune_creation_paresseuse_de_compteur():
    """Un compteur créé par `setdefault` est un compteur qui n'existe pas pour ses lecteurs.

    `dead_unit_actions` en était l'aboutissement : créé par `setdefault`, affecté à une variable
    locale, JAMAIS écrit ni lu ailleurs. Aucun producteur, aucun consommateur — la même famille
    que V1/V2/V3. Supprimé le 2026-08-10.
    """
    import inspect

    source = inspect.getsource(an)
    assert "stats.setdefault(" not in source, (
        "une clé de stats est créée à la volée : elle doit être déclarée dans la structure"
    )
    assert "dead_unit_actions" not in source, "code mort réintroduit"


#: Buckets qui n'ont pas de compteur `{1:…, 2:…}` et se posent donc à la main.
SCALAR_BUCKETS = {
    'wrong_phase':          lambda st: st['action_phase_accuracy']['move'].update({'wrong': 1}),
    'double_activation':    lambda st: st['double_activation_by_phase'].update({'MOVE': 1}),
    'special_rules_invalid': lambda st: st['special_rule_usage'].__setitem__(('regle_inconnue', 'Type'), {1: 1, 2: 0}),
    'weapon_rules_invalid': lambda st: st['weapon_rule_usage'].__setitem__(('REGLE_INCONNUE', 'Arme (Type)'), {1: 1, 2: 0}),
    'episodes_ending':      lambda st: st['episodes_without_end'].append(1),
    'core_issues':          lambda st: st['parse_errors'].append({'error': 'x'}),
    'state_resync':         lambda st: st['state_resync'].update({'dead_missed': 1}),
}


@pytest.mark.parametrize("bucket", sorted(SCALAR_BUCKETS))
def test_les_sections_hors_phase_entrent_aussi_dans_le_total(bucket, _empty_stats):
    """Toute ligne ❌ du SUMMARY doit peser dans le TOTAL — c'est le second défaut trouvé.

    §1.6 (double-activation) et §1.7 (règles invalides) s'affichaient en ❌ et n'entraient dans
    aucun total : un run imprimait « ❌ 1.6 Double-activation par phase : 1 » puis
    « ✅ Aucune erreur détectée ». Deux verdicts contradictoires dans le même rapport, et c'est
    le second — le plus court — qu'on lit.
    """
    stats = _fresh_stats(_empty_stats)
    before = an.error_totals(stats)['total']
    SCALAR_BUCKETS[bucket](stats)
    after = an.error_totals(stats)
    assert after[bucket] > 0, f"le bucket '{bucket}' ne voit pas sa propre donnée"
    assert after['total'] == before + after[bucket], (
        f"'{bucket}' n'entre pas dans le TOTAL : {after['total']} au lieu de {before + after[bucket]}"
    )


def test_la_ligne_16_du_summary_affiche_la_grandeur_qui_entre_dans_le_total(_empty_stats):
    """Icône et NOMBRE doivent sortir de la même grandeur, sinon la contradiction revient.

    Le bucket `double_activation` compte la double-activation par phase ET le move réactif
    (les deux ont leur ligne dans la section 1.6 détaillée). Afficher la seule somme par phase
    imprimait « ❌ 1.6 … : 0 » sur un journal ne portant qu'un doublon réactif.
    """
    stats = _fresh_stats(_empty_stats)
    stats['double_activation_reactive_move'] = 1          # réactif seul, aucune phase
    assert an.error_totals(stats)['double_activation'] == 1
    lines: list = []
    an.print_statistics(stats, output_lines=lines, emit_console=False)
    row = [l for l in lines if l.strip().startswith(("✅ 1.6", "❌ 1.6"))]
    assert len(row) == 1, lines[-40:]
    assert row[0].startswith("❌"), row[0]
    assert row[0].rstrip().endswith(" 1"), row[0]


def test_le_total_est_la_somme_de_tous_les_buckets(_empty_stats):
    """Aucun terme ne s'ajoute au total hors des buckets, et aucun bucket n'en est exclu.

    C'est cette propriété — et non une liste à maintenir — qui garantit qu'un bucket NEUF entre
    dans le total sans qu'on ait à y penser.
    """
    stats = _fresh_stats(_empty_stats)
    stats['wall_collisions'][1] = 3
    stats['double_activation_by_phase']['FIGHT'] = 2
    totals = an.error_totals(stats)
    assert totals['total'] == sum(v for k, v in totals.items() if k != 'total')


def test_le_summary_et_le_total_cli_lisent_le_meme_calcul():
    """La propriété qui rend la divergence impossible, vérifiée sur le CODE et non sur un run.

    Les deux sites doivent APPELER `error_totals`. Tant qu'ils le font, ils ne peuvent pas
    diverger ; s'ils cessent, ce test le dit avant que le rapport ne se contredise à nouveau.
    """
    import inspect

    source = inspect.getsource(an)
    # Une seule DÉFINITION, et au moins deux APPELS (SUMMARY + total CLI).
    assert source.count("def error_totals(") == 1
    assert source.count("error_totals(stats)") >= 2, "un des deux sites a cessé d'appeler le calcul partagé"
    # Et surtout : plus aucune somme écrite à la main sous ces noms.
    # Le total de la CLI ne doit plus RECOMPOSER quoi que ce soit : il lit `['total']`.
    assert "total_errors = error_totals(stats)['total']" in source, (
        "le total de la CLI est de nouveau recomposé à la main"
    )
    for name in ("move_errors", "shooting_errors", "charge_errors", "fight_errors"):
        for line in source.split("\n"):
            stripped = line.strip()
            if stripped.startswith(f"{name} = ") and "_totals[" not in stripped:
                pytest.fail(f"somme recopiée à la main : {stripped}")
