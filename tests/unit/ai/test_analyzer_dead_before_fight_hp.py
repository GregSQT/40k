"""DEAD-before-FIGHT : les attaques post-mortem ne doivent pas restaurer unit_hp.

Régression verrouillée (2026-09-02). Lorsque le moteur journalise l'événement DEAD avant
les lignes d'attaque létales (§12.04 / §05), le DEAD handler met unit_hp[target_id] = 0
(clé présente). Sans garde, les attaques suivantes passaient le check `target_id not in
unit_hp` et appelaient `_apply_damage_to_named_model` qui, sur la branche non-létale,
appelait `_sync_front_hp_mirror` → unit_hp[target_id] restauré à une valeur > 0. Les
snapshots de tour suivant incluaient alors l'unité morte dans `positions_at_movement_filtered`,
déclenchant de faux `move_adjacent_before_non_flee`.

Fix : `_apply_damage_and_handle_death` retourne immédiatement si `unit_hp[target_id] <= 0`.
"""
from __future__ import annotations

from ai.analyzer import _apply_damage_and_handle_death


def _make_ordered_living(unit_model_hp: dict):
    """Fermeture sur unit_model_hp, miroir du comportement réel de _ordered_living_mids.

    Retourne les clés de unit_model_hp[unit_id] dans l'ordre naturel. Sans ce comportement
    réel, _sync_front_hp_mirror ne met jamais à jour unit_hp (liste vide → branche `if _living`
    jamais empruntée) et la restauration fautive est invisible dans les tests.
    """
    def _fn(unit_id: str) -> list[str]:
        return sorted(unit_model_hp.get(unit_id, {}).keys())
    return _fn


def _make_stats() -> dict:
    return {
        "state_resync": {"alloc_model_unknown": 0},
        "wounded_enemies": {1: set(), 2: set()},
        "damage_missing_unit_hp": {1: 0, 2: 0},
        "first_error_lines": {"damage_missing_unit_hp": {1: None, 2: None}},
        "current_episode_deaths": [],
    }


def _call_damage(
    *,
    unit_hp: dict,
    unit_model_hp: dict,
    unit_models_alive: dict,
    damage: int = 1,
    alloc_model_id: str | None = "105#0",
) -> dict:
    """Appelle _apply_damage_and_handle_death sur l'unité 105 avec ordered_living_mids réel.

    Retourne le dict stats pour que les tests puissent inspecter current_episode_deaths.
    """
    stats = _make_stats()
    _apply_damage_and_handle_death(
        target_id="105",
        attacker_id="1",
        damage=damage,
        player=1,
        turn=1,
        phase="FIGHT",
        line_number=10,
        current_episode_num=1,
        line_text="Unit 1(100,150) FOUGHT Unit 105(105,150) ...",
        dead_units_current_episode=set(),
        unit_hp=unit_hp,
        unit_models_alive=unit_models_alive,
        unit_model_hp=unit_model_hp,
        ordered_living_mids=_make_ordered_living(unit_model_hp),
        unit_hp_squad_max={"105": 2},
        unit_types={"105": "AssaultIntercessor"},
        unit_positions={"105": (105, 150)},
        unit_deaths=[],
        unit_kill_context={},
        stats=stats,
        alloc_model_id=alloc_model_id,
        dead_model_ids_episode={"105": {"105#0"}} if alloc_model_id is not None else None,
    )
    return stats


class TestDeadBeforeFightHp:
    """Attaques post-DEAD (unit_hp = 0, clé présente) : unit_hp doit rester 0."""

    def test_non_lethal_attack_does_not_restore_hp(self) -> None:
        """Branche non-létale (hp_before - damage > 0) : unit_hp reste 0.

        C'est LE cas observé en production : unit_hp['105']=0 après DEAD event, mais
        unit_model_hp['105']['105#0']=2 (non vidé). Une attaque post-DEAD avec damage=1 donne
        hp_before - damage = 2-1 = 1 > 0 → _sync_front_hp_mirror → unit_hp['105'] = 1. FAUX.
        """
        unit_hp = {"105": 0}
        unit_model_hp = {"105": {"105#0": 2}}
        unit_models_alive = {"105": 1}  # valeur stale — unité déclarée morte par DEAD event

        _call_damage(unit_hp=unit_hp, unit_model_hp=unit_model_hp,
                     unit_models_alive=unit_models_alive, damage=1)

        assert unit_hp["105"] == 0, (
            "Attaque post-DEAD : _sync_front_hp_mirror ne doit pas restaurer unit_hp à 1"
        )

    def test_alive_unit_with_hp_positive_is_not_blocked(self) -> None:
        """La garde ne bloque PAS une unité vivante (hp > 0).

        Régression inverse : une unité à 2 PV encaissant 1 dégât non-létal doit bien
        voir unit_hp descendre à 1 (via _sync_front_hp_mirror sur la branche non-létale).
        """
        unit_hp = {"105": 2}
        unit_model_hp = {"105": {"105#0": 2}}
        unit_models_alive = {"105": 1}

        _call_damage(unit_hp=unit_hp, unit_model_hp=unit_model_hp,
                     unit_models_alive=unit_models_alive, damage=1)

        assert unit_hp["105"] == 1

    def test_unnamed_path_post_dead_does_not_double_count(self) -> None:
        """Chemin non-nommé (alloc_model_id=None, grammaire 1) post-DEAD : la garde bloque.

        Sans la garde `unit_hp[target_id] <= 0`, le chemin unnamed calculerait
        front_hp = 0 - damage = -damage → branche létale → unit_models_alive décrémenté
        à -1 et current_episode_deaths incrémenté une seconde fois. La garde doit
        retourner avant d'atteindre cette branche.
        """
        unit_hp = {"105": 0}
        unit_model_hp: dict = {}
        unit_models_alive = {"105": 0}  # déjà décrémenté par le DEAD handler

        stats = _call_damage(
            unit_hp=unit_hp,
            unit_model_hp=unit_model_hp,
            unit_models_alive=unit_models_alive,
            damage=1,
            alloc_model_id=None,
        )

        assert unit_hp["105"] == 0, "unit_hp ne doit pas être supprimé ni restauré"
        assert unit_models_alive["105"] == 0, "unit_models_alive ne doit pas descendre à -1"
        assert stats["current_episode_deaths"] == [], "pas de double-comptage dans deaths"
