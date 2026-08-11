import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from ai import replay_converter
from shared.data_validation import require_present


# Les deux tests qui occupaient cette place verrouillaient `extract_scenario_name_for_replay` :
# ils posaient eux-memes `_current_template_name` / `_detected_template_name` sur les objets
# fonction, puis verifiaient que la fonction les relisait. Aucun code de production n'ecrivait
# ces attributs — les tests etaient le seul producteur, donc la seule assurance qu'ils donnaient
# etait sur eux-memes. Fonction et attributs supprimes ; le nom de sortie est constant.


def test_parse_action_message_handles_move_shoot_combat_charge_wait() -> None:
    ctx = {"turn": 1, "phase": "move", "player": 1, "timestamp": "t"}

    move = require_present(replay_converter.parse_action_message(
        "Unit 1(1, 1) MOVED from (1, 1) to (2, 1)", ctx
    ), "move")
    assert move["type"] == "move"
    assert move["startHex"] == "(1, 1)"
    assert move["endHex"] == "(2, 1)"

    shoot = require_present(replay_converter.parse_action_message("Unit 1(1, 1) SHOT Unit 2", ctx), "shoot")
    assert shoot["type"] == "shoot"
    assert shoot["targetUnitId"] == 2

    combat = require_present(replay_converter.parse_action_message("Unit 3(3, 3) FOUGHT Unit 4", ctx), "combat")
    assert combat["type"] == "combat"

    charge = require_present(replay_converter.parse_action_message("Unit 5(4, 4) CHARGED Unit 6", ctx), "charge")
    assert charge["type"] == "charge"

    wait = require_present(replay_converter.parse_action_message("Unit 7(6, 6) WAIT", ctx), "wait")
    assert wait["type"] == "wait"

    assert replay_converter.parse_action_message("unknown message", ctx) is None


def test_parse_action_message_accepts_the_real_step_logger_format() -> None:
    """Le parser doit lire ce que `ai/step_logger.py` ECRIT, pas une variante d'il y a deux formats.

    Trois ecarts mesures, chacun suffisant a rendre la ligne invisible :
      - marqueurs de capacite entre le verbe et la suite (`[WAAAGH!]` 24.xx, `[FLY]` 21.03) ;
      - coordonnees SANS espace apres la virgule (`(5,48)`) — c'est la forme reellement ecrite ;
      - aiguillage litteral (`"SHOT Unit" in message`) qui excluait les lignes a marqueur AVANT
        meme d'atteindre la regex, laquelle les tolerait deja.
    """
    ctx = {"turn": 1, "phase": "charge", "player": 1, "timestamp": "t"}
    _parse = replay_converter.parse_action_message

    for line in (
        "Unit 5(4,4) CHARGED [WAAAGH!] Unit 6 from (0,0) to (3,0)",
        "Unit 5(4,4) CHARGED [WAAAGH!] [FLY] Unit 6 from (0,0) to (3,0)",
    ):
        charge = require_present(_parse(line, ctx), "charge")
        assert charge["type"] == "charge" and charge["targetUnitId"] == 6, line

    shoot = require_present(_parse("Unit 1(1,1) SHOT [ASSAULT] Unit 2 with [Bolter]", ctx), "shoot")
    assert shoot["targetUnitId"] == 2

    # Coordonnees collees + `[FLY]` : la forme exacte de `step_logger` sur un move volant.
    move = require_present(_parse("Unit 3(5,48) MOVED [FLY] from (3,58) to (5,48)[R:+0.0]", ctx), "move")
    assert move["startHex"] == "(3, 58)" and move["endHex"] == "(5, 48)"


def test_parse_steplog_file_reads_the_episode_numbered_format(tmp_path: Path) -> None:
    """`E<n>` precede `T<n>` dans le format courant : sans lui, ZERO action n'etait convertie.

    La detection du debut des actions cherchait `"] T"` litteral, jamais present quand le
    numero d'episode s'intercale — le fichier entier etait alors traite comme de l'en-tete.
    """
    steplog = tmp_path / "step.log"
    steplog.write_text(
        "\n".join(
            [
                "=== STEP-BY-STEP ACTION LOG ===",
                "[18:03:59] E1 T1 P1 MOVE : Unit 3(5,48) MOVED from (3,58) to (5,48)"
                "[R:+0.0] [MODELS: 3#0@(5,48)] [SUCCESS]",
                "[18:04:04] E1 T5 P2 CHARGE : Unit 103(19,28) CHARGED [WAAAGH!] Unit 1(19,29) "
                "from (22,27) to (19,28) [Roll: 7] [R:+0.0] [SUCCESS]",
            ]
        ),
        encoding="utf-8",
    )
    parsed = replay_converter.parse_steplog_file(str(steplog))
    assert [a["type"] for a in parsed["actions"]] == ["move", "charge"]
    assert parsed["max_turn"] == 5
    # La position doit etre relue depuis la ligne : `Unit 3(5,48)` n'a pas d'espace non plus.
    assert parsed["units_positions"][3] == {"col": 5, "row": 48, "last_seen_turn": 1}


def test_toute_la_famille_move_est_parsee_pas_seulement_moved() -> None:
    """`step_logger` ecrit plusieurs verbes sur la meme forme ; seul `MOVED` etait reconnu.

    Une escouade qui ne fait qu'avancer ou se replier ne produisait aucune entree de replay ET
    aucune mise a jour de position : tout ce qui suivait etait rejoue contre un fantome.
    L'ordre de la table compte — `MOVED` mordrait le debut de `MOVED AFTER SHOOTING`.

    Le `type` reprend le vocabulaire deja rendu par le frontend (`replayParser.ts`) : un replay
    qui confond un repli avec un move normal perd l'information, et un champ maison ne serait lu
    par personne.
    """
    ctx = {"turn": 1, "phase": "move", "player": 1, "timestamp": "t"}
    attendu = {
        "Unit 1(1,1) MOVED from (0,0) to (3,0)": "move",
        "Unit 1(1,1) ADVANCED [FLY] from (0,0) to (3,0) [Roll: 4]": "advance",
        "Unit 1(1,1) FLED from (0,0) to (3,0)": "flee",
        "Unit 1(1,1) REACTIVE MOVED [FIRE OVERWATCH] from (0,0) to (3,0) [Roll: 5]"
        " - trigger: Unit 2->(1,1)": "reactive_move",
        "Unit 1(1,1) MOVED AFTER SHOOTING [ASSAULT] from (0,0) to (3,0)": "move",
        "Unit 1(1,1) DEPLOYED from (0,0) to (3,0)": "deploy",
        # Forme SANS depart (step_logger.py:454 et :514) : elle etait perdue elle aussi.
        "Unit 1(1,1) MOVED to (3,0)": "move",
        "Unit 1(1,1) FLED to (3,0)": "flee",
    }
    for ligne, type_attendu in attendu.items():
        parsed = require_present(replay_converter.parse_action_message(ligne, ctx), type_attendu)
        assert parsed["type"] == type_attendu, ligne
        assert parsed["endHex"] == "(3, 0)", ligne


def test_un_seul_episode_est_converti(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Un replay decrit UNE partie. Les N episodes de `--test-episodes` vont dans le MEME
    steplog et les tours repartent a T1 : les concatener empilait plusieurs parties dans un
    seul `combat_log`, avec des positions qui sautent et un `total_turns` pris sur le max.

    La segmentation lit le DELIMITEUR `=== EPISODE n START ===` que `step_logger` ecrit pour ca.
    Filtrer sur le prefixe `E<n>` des lignes d'action ne peut pas segmenter : les transitions de
    phase sont ecrites SANS ce prefixe (step_logger.py:1006), donc la ligne `phase Start` de E2
    ci-dessous serait restee dans le replay du premier episode.
    """
    steplog = tmp_path / "step.log"
    steplog.write_text(
        "\n".join(
            [
                "=== STEP-BY-STEP ACTION LOG ===",
                "[18:03:58] T1 OBJECTIVE CONTROL: aucun",
                "[18:03:59] === EPISODE 1 START ===",
                "[18:03:59] === ACTIONS START ===",
                "[18:03:59] E1 T1 P1 MOVE : Unit 3(5,48) MOVED from (3,58) to (5,48) [SUCCESS]",
                "[18:04:00] E1 T2 P1 MOVE : Unit 3(4,49) MOVED from (5,48) to (4,49) [SUCCESS]",
                # Episode suivant : meme unite, repartie de sa case de deploiement, tour remis a 1.
                "[18:04:20] === EPISODE 2 START ===",
                "[18:04:20] === ACTIONS START ===",
                "[18:04:20] T1 P1 MOVE phase Start",
                "[18:04:20] E2 T1 P1 MOVE : Unit 3(3,58) MOVED from (3,58) to (7,50) [SUCCESS]",
                "[18:04:25] E2 T9 P1 MOVE : Unit 3(7,50) MOVED from (7,50) to (9,44) [SUCCESS]",
            ]
        ),
        encoding="utf-8",
    )
    parsed = replay_converter.parse_steplog_file(str(steplog))

    assert len(parsed["actions"]) == 2, (
        "seules les deux actions de l'episode 1 doivent entrer dans le replay — y compris la "
        "transition de phase de E2, qui n'a pas de prefixe d'episode a filtrer"
    )
    assert not any(a.get("type") == "phase_change" for a in parsed["actions"])
    assert parsed["max_turn"] == 2, (
        "T9 vient de E2 : le compte de tours doit decrire la partie rejouee, pas le maximum "
        "sur toutes les parties du steplog"
    )
    assert parsed["units_positions"][3] == {"col": 4, "row": 49, "last_seen_turn": 2}
    # Rien n'est avale en silence (CLAUDE.md : pas de troncature muette).
    assert "1 ecarte(s)" in capsys.readouterr().out


def test_initial_state_porte_les_positions_de_depart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`initial_state` decrivait le plateau de FIN : il etait bati sur `units_positions`, la
    DERNIERE position vue. Le frontend rejoue `combat_log` PAR-DESSUS cet etat, donc chaque
    deplacement y etait applique une seconde fois, depuis son point d'arrivee.

    Le bloc etait inatteignable avant la correction du parser (`units_positions` restait vide,
    donc le `raise` partait toujours) : c'est la correction qui l'a mis en service.
    """
    scenario_file = tmp_path / "scenario.json"
    scenario_file.write_text(
        json.dumps({"units": [
            {"id": 1, "unit_type": "Intercessor", "player": 1, "col": 1, "row": 1},
            {"id": 2, "unit_type": "Termagant", "player": 2, "col": 2, "row": 1},
        ]}),
        encoding="utf-8",
    )

    class DummyRegistry:
        def get_unit_data(self, unit_type):
            _ = unit_type
            return {"HP_MAX": 2, "MOVE": 6}

    class DummyConfig:
        config_dir = str(tmp_path)

        @staticmethod
        def get_board_size():
            return (20, 20)

    monkeypatch.setattr("ai.unit_registry.UnitRegistry", DummyRegistry)
    monkeypatch.setattr("ai.replay_converter.get_config_loader", lambda: DummyConfig())

    # L'unite 1 a fini en (9, 9) ; l'unite 2 n'a jamais bouge.
    steplog_data = {
        "actions": [{"type": "move", "unitId": 1}],
        "max_turn": 3,
        "units_positions": {1: {"col": 9, "row": 9}},
    }
    replay = replay_converter.convert_to_replay_format(steplog_data, str(scenario_file))
    par_id = {u["id"]: (u["col"], u["row"]) for u in replay["initial_state"]["units"]}
    assert par_id == {1: (1, 1), 2: (2, 1)}, (
        "l'etat initial doit etre celui du scenario ; melanger la position finale de l'unite "
        "qui a agi avec la position de depart de l'autre decrit un plateau qui n'a jamais existe"
    )


def test_calculate_episode_reward_from_actions_bounds_efficiency_bonus() -> None:
    actions = [{"type": "move"}] * 200
    reward = replay_converter.calculate_episode_reward_from_actions(actions, winner=0)
    assert reward == 5.0  # 10 + max(-5, ...)
    assert replay_converter.calculate_episode_reward_from_actions([], winner=None) == 0.0


def test_parse_steplog_file_parses_actions_and_phase_changes(tmp_path: Path) -> None:
    steplog = tmp_path / "step.log"
    steplog.write_text(
        "\n".join(
            [
                "header line",
                "[12:00:00] T1 P1 MOVE : Unit 1(1, 1) MOVED from (1, 1) to (2, 1) [SUCCESS] [STEP: YES]",
                "[12:00:01] T1 P1 SHOOT : Unit 1(2, 1) SHOT Unit 2 [SUCCESS] [STEP: YES]",
                "[12:00:02] T1 P1 MOVE phase Start",
            ]
        ),
        encoding="utf-8",
    )
    parsed = replay_converter.parse_steplog_file(str(steplog))
    assert parsed["max_turn"] == 1
    assert len(parsed["actions"]) >= 2
    assert any(a.get("type") == "phase_change" for a in parsed["actions"])


def test_convert_to_replay_format_builds_initial_state_from_scenario(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    scenario_file = tmp_path / "scenario.json"
    scenario_file.write_text(
        json.dumps(
            {
                "units": [
                    {"id": 1, "unit_type": "Intercessor", "player": 1, "col": 1, "row": 1},
                    {"id": 2, "unit_type": "Termagant", "player": 2, "col": 2, "row": 1},
                ]
            }
        ),
        encoding="utf-8",
    )

    class DummyRegistry:
        def get_unit_data(self, unit_type):
            if unit_type == "Intercessor":
                return {"HP_MAX": 2, "MOVE": 6}
            return {"HP_MAX": 1, "MOVE": 6}

    class DummyConfig:
        config_dir = str(tmp_path)

        @staticmethod
        def get_board_size():
            return (20, 20)

    monkeypatch.setattr("ai.unit_registry.UnitRegistry", DummyRegistry)
    monkeypatch.setattr("ai.replay_converter.get_config_loader", lambda: DummyConfig())

    steplog_data = {
        "actions": [{"type": "move", "unitId": 1}],
        "max_turn": 3,
        "units_positions": {1: {"col": 3, "row": 3}, 2: {"col": 2, "row": 1}},
    }

    replay = replay_converter.convert_to_replay_format(steplog_data, str(scenario_file))
    assert replay["game_info"]["total_turns"] == 3
    assert replay["initial_state"]["board_size"] == [20, 20]
    assert len(replay["initial_state"]["units"]) == 2
    assert replay["episode_steps"] == 1


def test_convert_to_replay_format_raises_when_units_positions_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class DummyRegistry:
        def get_unit_data(self, unit_type):
            _ = unit_type
            return {"HP_MAX": 2}

    class DummyConfig:
        config_dir = str(tmp_path)

        @staticmethod
        def get_board_size():
            return (10, 10)

    scenario_file = tmp_path / "scenario.json"
    scenario_file.write_text(json.dumps({"units": []}), encoding="utf-8")
    monkeypatch.setattr("ai.unit_registry.UnitRegistry", DummyRegistry)
    monkeypatch.setattr("ai.replay_converter.get_config_loader", lambda: DummyConfig())

    with pytest.raises(ValueError, match=r"No unit position data found"):
        replay_converter.convert_to_replay_format(
            {"actions": [], "max_turn": 1, "units_positions": {}}, str(scenario_file)
        )


def test_convert_steplog_to_replay_raises_when_input_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match=r"Steplog file not found"):
        replay_converter.convert_steplog_to_replay(str(tmp_path / "missing.log"), str(tmp_path / "s.json"))


def test_convert_steplog_to_replay_writes_output_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    steplog = tmp_path / "step.log"
    steplog.write_text("dummy", encoding="utf-8")
    monkeypatch.setattr(replay_converter, "parse_steplog_file", lambda p: {"actions": [], "max_turn": 1, "units_positions": {1: {"col": 1, "row": 1}}})
    monkeypatch.setattr(
        replay_converter,
        "convert_to_replay_format",
        lambda data, scenario_file: {"combat_log": [], "game_states": [], "game_info": {"total_turns": 1}},
    )
    monkeypatch.chdir(tmp_path)
    assert replay_converter.convert_steplog_to_replay(str(steplog), str(tmp_path / "s.json")) is True
    out_file = tmp_path / "ai" / "event_log" / "replay_scenario.json"
    assert out_file.exists()


def test_two_conversions_in_one_process_each_use_their_own_scenario(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Le scenario ne fuit pas d'une conversion a la suivante (ex-attribut de fonction).

    Avant correction, `convert_to_replay_format._scenario_file` etait pose une fois et jamais
    remis a zero par le bloc de nettoyage : la seconde conversion du meme processus relisait le
    scenario de la premiere — un chemin par ailleurs efface par ce meme nettoyage.
    """
    class DummyRegistry:
        def get_unit_data(self, unit_type):
            _ = unit_type
            return {"HP_MAX": 1, "MOVE": 6}

    class DummyConfig:
        config_dir = str(tmp_path)

        @staticmethod
        def get_board_size():
            return (10, 10)

    monkeypatch.setattr("ai.unit_registry.UnitRegistry", DummyRegistry)
    monkeypatch.setattr("ai.replay_converter.get_config_loader", lambda: DummyConfig())

    def _write(name: str, unit_id: int) -> Path:
        path = tmp_path / name
        path.write_text(
            json.dumps({"units": [{"id": unit_id, "unit_type": "Intercessor", "player": 1, "col": 1, "row": 1}]}),
            encoding="utf-8",
        )
        return path

    first = _write("scenario_a.json", 11)
    second = _write("scenario_b.json", 22)
    steplog_data = {"actions": [], "max_turn": 1, "units_positions": {11: {"col": 1, "row": 1}}}

    replay_a = replay_converter.convert_to_replay_format(steplog_data, str(first))
    replay_b = replay_converter.convert_to_replay_format(steplog_data, str(second))

    assert [u["id"] for u in replay_a["initial_state"]["units"]] == [11]
    assert [u["id"] for u in replay_b["initial_state"]["units"]] == [22]


_OBS = {"global_cont": np.zeros(2, dtype=np.float32)}


def _rig_one_shot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, step_obs):
    """Gree le workflow one-shot avec des doubles ; `step_obs` = observation rendue par `step`.

    `step_obs=_OBS` reproduit le moteur reel (`W40KEngine.step` ne rend `None` que si l'appelant
    a arme `defer_observation`, ce que ce workflow ne fait pas : moteur NU, sans wrapper
    d'entrainement). `step_obs=None` simule la violation de ce contrat.
    """
    scenario = tmp_path / "scenario_bot.json"
    scenario.write_text(json.dumps({"units": []}), encoding="utf-8")
    model_file = tmp_path / "models" / "CoreAgent" / "model_CoreAgent.zip"
    model_file.parent.mkdir(parents=True, exist_ok=True)
    model_file.write_text("dummy", encoding="utf-8")

    closed: list = []

    class _Engine:
        def __init__(self, **kwargs):
            _ = kwargs
            self.step_logger = None

        def reset(self):
            return _OBS, {}

        def step(self, action):
            _ = action
            return step_obs, 0.0, True, False, {}

        def close(self):
            closed.append(True)

    class _Model:
        @staticmethod
        def load(path, env):
            _ = path, env
            return _Model()

        def predict(self, obs, deterministic):
            _ = obs, deterministic
            return 0, None

    class _Cfg:
        def load_agent_training_config(self, agent, training_config):
            _ = agent, training_config
            return {"step_log_buffer_size": 1}

        def get_models_root(self):
            return str(tmp_path / "models")

        def get_max_turns(self):
            return 5

    converted: list = []
    monkeypatch.setattr(replay_converter, "resolve_agent_bot_scenario", lambda config, agent: str(scenario))
    monkeypatch.setattr(replay_converter, "setup_imports", lambda: (_Engine, None))
    monkeypatch.setattr(replay_converter, "MaskablePPO", _Model)
    monkeypatch.setattr("ai.unit_registry.UnitRegistry", lambda: object())
    monkeypatch.setattr(
        replay_converter,
        "convert_steplog_to_replay",
        lambda steplog, scenario_file: converted.append(scenario_file) or True,
    )
    monkeypatch.chdir(tmp_path)

    args = SimpleNamespace(
        agent="CoreAgent",
        training_config="default",
        rewards_config="CoreAgent",
        model=None,
        test_episodes=1,
    )
    return SimpleNamespace(
        args=args, cfg=_Cfg(), scenario=scenario, converted=converted, closed=closed
    )


def test_generate_steplog_and_replay_keeps_the_bot_scenario_on_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Le scenario bot est un fichier versionne : le workflow ne doit jamais l'effacer.

    Le bloc de nettoyage appelait `os.remove` dessus, heritage du temps ou le scenario etait
    genere a la volee. Depuis `get_scenario_list_for_phase`, le chemin designe un vrai fichier
    de config/agents/<agent>/scenarios/training/ : le supprimer amputait le jeu d'entrainement.
    """
    rig = _rig_one_shot(tmp_path, monkeypatch, step_obs=_OBS)
    assert replay_converter.generate_steplog_and_replay(config=rig.cfg, args=rig.args) is True
    assert rig.converted == [str(rig.scenario)]
    assert rig.scenario.exists(), "le scenario bot versionne a ete efface par le nettoyage"


def test_none_observation_is_refused_instead_of_producing_a_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Une observation `None` doit arreter le workflow, jamais produire un replay silencieux.

    Ce chemin pilote un `W40KEngine` NU : `defer_observation` n'y est jamais arme, donc `None`
    signale un contrat rompu. Sans le garde, `None` partait dans `model.predict` a l'iteration
    suivante — et selon la politique, un replay tronque ou faux pouvait en sortir.
    """
    rig = _rig_one_shot(tmp_path, monkeypatch, step_obs=None)
    assert replay_converter.generate_steplog_and_replay(config=rig.cfg, args=rig.args) is False
    assert rig.converted == [], "aucun replay ne doit etre produit sur contrat rompu"
    assert "contrat de _step_observation rompu" in capsys.readouterr().out


def test_env_is_closed_even_when_the_workflow_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`env.close()` doit etre appele meme en cas d'echec.

    Le `except Exception` final convertit toute erreur en `return False` : tant que le
    `env.close()` vivait dans le chemin nominal, une erreur levee dans la boucle d'episodes
    fuyait le moteur.
    """
    rig = _rig_one_shot(tmp_path, monkeypatch, step_obs=None)

    assert replay_converter.generate_steplog_and_replay(config=rig.cfg, args=rig.args) is False
    assert rig.closed == [True], "env.close() saute quand le workflow echoue"


def test_resolve_agent_bot_scenario_requires_an_agent() -> None:
    with pytest.raises(ValueError, match=r"--agent required"):
        replay_converter.resolve_agent_bot_scenario(SimpleNamespace(), None)


def test_generate_steplog_and_replay_returns_false_without_agent() -> None:
    args = SimpleNamespace(
        agent=None,
        training_config="default",
        rewards_config="CoreAgent",
        model=None,
        test_episodes=1,
    )
    assert replay_converter.generate_steplog_and_replay(config=SimpleNamespace(), args=args) is False


def test_generate_steplog_and_replay_returns_false_when_model_missing(tmp_path: Path) -> None:
    class _Cfg:
        def load_agent_training_config(self, agent, training_config):
            _ = agent, training_config
            return {"step_log_buffer_size": 1, "max_turns_per_episode": 2}

        def get_models_root(self):
            return str(tmp_path / "models")

    args = SimpleNamespace(
        agent="CoreAgent",
        training_config="default",
        rewards_config="CoreAgent",
        model=None,
        test_episodes=1,
    )
    assert replay_converter.generate_steplog_and_replay(config=_Cfg(), args=args) is False
