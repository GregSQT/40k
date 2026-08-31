"""Tests pour les corrections d'analyzer_config.py / analyzer_core.py / analyzer.py."""
import pytest
from typing import Any, cast
from ai.analyzer_config import (
    _numeric,
    set_run_rules,
    get_run_rule,
    get_run_rule_optional,
    reset_run_state,
)


# ---------------------------------------------------------------------------
# _numeric : '--5' ne doit pas lever ValueError (finding 2)
# ---------------------------------------------------------------------------

class TestNumeric:
    def test_entier_positif(self):
        assert _numeric(4) == 4

    def test_entier_negatif_str(self):
        assert _numeric("-3") == -3

    def test_double_tiret_est_none(self):
        # '--5'.lstrip('-') = '5', isdigit OK, mais int('--5') levait ValueError
        assert _numeric("--5") is None

    def test_symbolique_est_none(self):
        assert _numeric("LieutenantPowerFistPlasmaPistol.T") is None

    def test_bool_est_none(self):
        assert _numeric(True) is None
        assert _numeric(False) is None

    def test_vide_est_none(self):
        assert _numeric("") is None


# ---------------------------------------------------------------------------
# set_run_rules : valeurs non-str rejetées (finding 5)
# ---------------------------------------------------------------------------

class TestSetRunRulesTypes:
    def setup_method(self):
        reset_run_state()

    def test_str_accepte(self):
        set_run_rules({"k": "v"})
        assert get_run_rule("k") == "v"

    def test_int_leve(self):
        with pytest.raises(TypeError, match="doit être str"):
            set_run_rules({"twin_linked_uses": 2})  # type: ignore[arg-type]

    def test_none_leve(self):
        with pytest.raises(TypeError, match="doit être str"):
            set_run_rules({"k": None})  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# get_run_rule_optional : None si clé absente, lève si run non initialisé (finding 4/6)
# ---------------------------------------------------------------------------

class TestGetRunRuleOptional:
    def setup_method(self):
        reset_run_state()

    def test_leve_si_non_initialise(self):
        with pytest.raises(RuntimeError):
            get_run_rule_optional("whatever")

    def test_none_si_cle_absente(self):
        set_run_rules({"a": "1"})
        assert get_run_rule_optional("b") is None

    def test_valeur_si_cle_presente(self):
        set_run_rules({"a": "1"})
        assert get_run_rule_optional("a") == "1"


# ---------------------------------------------------------------------------
# load_analyzer_config : conflit move_after_shooting ne lève plus à x5 (finding 1)
# Seul un vrai registre dual-rule peut exercer le bug ; on vérifie le scénario
# en simulant la logique directement (unité test isolée).
# ---------------------------------------------------------------------------

class TestMoveAfterShootingConflictCheck:
    """Vérifie que comparer scaled == scaled évite le faux conflit."""

    def _simulate(self, distances: list, inches_to_subhex: int) -> int:
        """Reproduit le bloc conflit de load_analyzer_config pour N distances identiques."""
        stored: dict = {}
        unit = "TestUnit"
        for dist in distances:
            scaled = dist * inches_to_subhex
            existing = stored.get(unit)
            if existing is not None and existing != scaled:
                raise ValueError(f"Conflicting distances: {existing} vs {scaled}")
            stored[unit] = scaled
        return stored[unit]

    def test_deux_regles_identiques_x5(self):
        # Avant le fix, stored=30, comparaison 30 != 6 levait ValueError.
        result = self._simulate([6, 6], inches_to_subhex=5)
        assert result == 30

    def test_deux_regles_identiques_x1(self):
        result = self._simulate([6, 6], inches_to_subhex=1)
        assert result == 6

    def test_distances_differentes_leve(self):
        with pytest.raises(ValueError, match="Conflicting distances"):
            self._simulate([6, 9], inches_to_subhex=5)


# ---------------------------------------------------------------------------
# _check_line_coherency : skip si clés cohesion absentes (finding 4)
# Utilise parse_step_log sur un log minimal pour exercer le chemin réel.
# ---------------------------------------------------------------------------

def _entete_sans_cohesion() -> str:
    """Entête via entete_step_log avec les clés cohesion.* purgées de la ligne Run rules:."""
    from tests.unit.ai._fabriques import entete_step_log
    header = entete_step_log(
        units="[10:00:00] Unit 1 (Intercessor) P1: Starting position (-1,-1), HP_MAX=2 base=round/1\n",
        inches_to_subhex=1,
        board="cols=40 rows=40",
        walls="none",
        objectives=";".join(f"(30,{r})" for r in range(30, 33)),
        rosters="scale=1 AGENT_PLAYER=1 AGENT=sm (ref) OPPONENT=sm (ref)",
    )
    # Retirer les 3 clés cohesion.* de la ligne Run rules: pour simuler un vieux journal.
    import re as _re
    header = _re.sub(r'\bcohesion\.\w+=\S+\s*', '', header)
    return header


class TestCoherencyGuardMissingKeys:
    def test_parse_sans_cohesion_ne_leve_pas(self, tmp_path):
        """parse_step_log d'un log SANS cohesion.* + ligne MOVED ne lève pas KeyError."""
        from tests.unit.ai._fabriques import entete_step_log
        import ai.analyzer as an
        models_seg = "1#0@(20,20,z0) 1#1@(20,22,z0)"
        header = _entete_sans_cohesion()
        body = (
            "[10:00:00] T1 MOVEMENT PHASE: P1\n"
            f"[10:00:01] E1 T1 P1 MOVEMENT : Unit 1(20,20) MOVED from (0,0) to (20,20) "
            f"[R:+0.0] [MODELS: {models_seg}] [SUCCESS]\n"
            "[10:00:02] T2 OBJECTIVE CONTROL: VP1=0 VP2=0 CP1=0 CP2=0 ZONES=rect b NW:Ctrl=none\n"
            "[10:00:03] EPISODE END: Winner=1, Method=objectives, "
            "Actions=0, Steps=0, Total=0, Duration=1.000s\n"
        )
        log_file = tmp_path / "step.log"
        log_file.write_text(header + body)
        # Avant le fix, cette ligne levait KeyError('cohesion.model_subhex absent...')
        result = an.parse_step_log(str(log_file))
        assert result is not None

    def test_parse_avec_cohesion_ne_leve_pas(self, tmp_path):
        """parse_step_log d'un log AVEC cohesion.* + formation saine ne lève pas."""
        from tests.unit.ai._fabriques import entete_step_log
        import ai.analyzer as an
        models_seg = "1#0@(20,20,z0) 1#1@(20,22,z0)"
        header = entete_step_log(
            units="[10:00:00] Unit 1 (Intercessor) P1: Starting position (-1,-1), HP_MAX=2 base=round/1\n",
            inches_to_subhex=1,
            board="cols=40 rows=40",
            walls="none",
            objectives=";".join(f"(30,{r})" for r in range(30, 33)),
            rosters="scale=1 AGENT_PLAYER=1 AGENT=sm (ref) OPPONENT=sm (ref)",
        )
        body = (
            "[10:00:00] T1 MOVEMENT PHASE: P1\n"
            f"[10:00:01] E1 T1 P1 MOVEMENT : Unit 1(20,20) MOVED from (0,0) to (20,20) "
            f"[R:+0.0] [MODELS: {models_seg}] [SUCCESS]\n"
            "[10:00:02] T2 OBJECTIVE CONTROL: VP1=0 VP2=0 CP1=0 CP2=0 ZONES=rect b NW:Ctrl=none\n"
            "[10:00:03] EPISODE END: Winner=1, Method=objectives, "
            "Actions=0, Steps=0, Total=0, Duration=1.000s\n"
        )
        log_file = tmp_path / "step.log"
        log_file.write_text(header + body)
        result = an.parse_step_log(str(log_file))
        assert result is not None


# ---------------------------------------------------------------------------
# _analyzer_engagement_zone_vertical : None si clé absente (finding 6)
# ---------------------------------------------------------------------------

class TestEngagementZoneVertical:
    def setup_method(self):
        reset_run_state()

    def test_none_si_cle_absente(self):
        from tests.unit.ai._fabriques import pose_etat_du_run
        from ai.analyzer import _analyzer_engagement_zone_vertical

        # ez_vertical_inches=None omet la clé
        pose_etat_du_run(5, ez_subhex=10, ez_vertical_inches=None)
        assert _analyzer_engagement_zone_vertical() is None

    def test_float_si_cle_presente(self):
        from tests.unit.ai._fabriques import pose_etat_du_run
        from ai.analyzer import _analyzer_engagement_zone_vertical

        pose_etat_du_run(5, ez_subhex=10, ez_vertical_inches=5.0)
        assert _analyzer_engagement_zone_vertical() == pytest.approx(5.0)

    def test_leve_si_run_non_initialise(self):
        from ai.analyzer import _analyzer_engagement_zone_vertical
        with pytest.raises(RuntimeError):
            _analyzer_engagement_zone_vertical()
