"""V11 §9.3 P2 — toute DÉCISION D'AGENT résolue laisse une ligne dans `step.log`.

TROU RÉPARÉ (2026-09-10) : la branche qui applique la déclaration de réserves 20.01
(`W40KEngine._dispatch_agent_decision_action`) construisait un résultat
`{"action": "agent_decision", ..., "declaredInReserves": ...}` mais n'appelait AUCUN
`append_action_log`. `grep -rn "decision" ai/step_logger.py` rendait 0 hit : le SEUL type de
décision journalisé était `rule_choice`, par un appel direct. Conséquence mesurable : impossible
de savoir si l'agent déclarait ses réserves ou déclinait systématiquement, alors que l'étape
20.01 précède désormais tout déploiement et pose une décision par unité déclarable.

CE QUE CE FICHIER VERROUILLE :
  - la ligne `DECISION [<type>] CHOICE_<i> [<libellé>]` atteint step.log par le chemin de
    PRODUCTION (`engine.step()` → flush des `action_logs`), et non par un appel direct au
    formateur ;
  - `CHOICE_0` (déclarer en réserves) et `CHOICE_1` (garder pour la mise en place) produisent
    deux lignes DISTINCTES, la seconde marquée `[DECLINED]` — c'est ce qui rend le taux de
    déclaration comptable ;
  - la ligne porte le type, l'index du candidat, l'unité, le joueur, le tour et l'épisode ;
  - `agent_decision` n'incrémente PAS le compteur de steps du StepLogger : le step gym consommé
    par `CHOICE_i` est déjà compté par la ligne d'effet quand le type en produit une ;
  - la ligne ne porte AUCUNE position par socle : un relevé de choix n'observe rien, et c'est le
    TYPE qui le déclare (`W40KEngine._TYPES_SANS_SEGMENT_MODELS`), au point de traduction unique ;
  - l'entrée d'`action_logs` ne peut être produite QUE par son constructeur dédié
    (`action_log_utils.append_agent_decision_log`) : le goulot `append_action_log` refuse le type,
    et les deux fonctions d'écriture sont gardées par NOM — import sous alias compris. La sonde
    statique par dictionnaire est conservée à côté, parce qu'elle seule voit une branche jamais
    exécutée, que la garde d'exécution ne peut pas atteindre.
"""
from __future__ import annotations

import ast
import re

from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]

SCENARIO = (
    PROJECT_ROOT / "config" / "agents" / "ArmageddonAgent_x1" / "scenarios" / "training"
    / "reserves_20_fixture1.json"
)

#: Type porté par l'entrée d'`action_logs` du relevé, et par elle seule.
_TYPE_JOURNAL = "agent_decision"

#: `[hh:mm:ss] E<ep> T<turn> P<player> <PHASE> : Unit <id> DECISION [<type>] CHOICE_<i> [<label>]`
_LINE_RE = re.compile(
    r"^\[\d\d:\d\d:\d\d\] E(\d+) T(\d+) P(\d+) ([A-Z_]+) : "
    r"Unit (\S+) DECISION \[([A-Za-z0-9_]+)\] CHOICE_(\d+) \[([^\]]*)\]"
    r"(?P<declined> \[DECLINED\])? \[SUCCESS\]$"
)


@pytest.fixture(autouse=True)
def _pin_board(board_x5):
    pass


def _engine(tmp_path, seed: int = 0):
    from ai.step_logger import StepLogger
    from ai.unit_registry import UnitRegistry
    from engine.w40k_core import W40KEngine

    eng = W40KEngine(
        rewards_config="ArmageddonAgent_x1", training_config_name="x1_debug",
        controlled_agent="ArmageddonAgent_x1", scenario_file=str(SCENARIO),
        unit_registry=UnitRegistry(), quiet=True, gym_training_mode=True,
    )
    # Le scheduler par-épisode peut rejouer le scénario en 'fixed' : la question 20.01 n'est
    # posée que dans un déploiement ACTIF.
    assert eng.training_config is not None
    sched = eng.training_config.get("deployment_mode_schedule")
    if isinstance(sched, dict):
        sched["enabled"] = False
    # buffer_size=1 : la ligne est sur le disque dès qu'elle est écrite, aucun flush à oublier.
    eng.step_logger = StepLogger(
        output_file=str(tmp_path / "step.log"), enabled=True, buffer_size=1
    )
    eng.reset(seed=seed)
    return eng


def _drive_deployment(eng, *, declare_first: bool) -> str:
    """Déroule le déploiement. Rend l'id de l'escouade déclarée en réserves ('' si aucune).

    POLITIQUE : `CHOICE_0` (déclarer) pour la PREMIÈRE question quand `declare_first`, `CHOICE_1`
    (garder) pour toutes les autres — ce qui garantit au moins une ligne de chaque forme.
    """
    from engine.agent_decision import read_pending_agent_decision
    from engine.macro_intents import CHOICE_SLOTS

    gs = eng.game_state
    declared = ""
    steps = 0
    while gs.get("phase") == "deployment" and steps < 1000:
        mask = eng.get_action_mask()  # c'est la construction du masque qui POSE la question
        pending = read_pending_agent_decision(gs)
        if pending is not None:
            assert str(pending["type"]) == "reserves_declaration", pending["type"]
            take_zero = bool(declare_first and not declared)
            if take_zero:
                declared = str(pending["unit_id"])
            eng.step(int(CHOICE_SLOTS.start + (0 if take_zero else 1)))
        else:
            deploy_actions = [a for a in range(4, 9) if mask[a]]
            assert deploy_actions, f"aucune action de déploiement au step {steps}"
            eng.step(int(deploy_actions[0]))
        steps += 1
    assert gs.get("phase") != "deployment", "déploiement non terminé"
    return declared


def require_pending_unit(eng) -> str:
    """Id de l'unité dont la décision 20.01 est POSÉE — lève si aucune ne l'est."""
    from engine.agent_decision import read_pending_agent_decision

    pending = read_pending_agent_decision(eng.game_state)
    if pending is None:
        raise AssertionError("aucune decision agent en attente : le scenario ne prouve rien")
    return str(pending["unit_id"])


def _decision_lines(eng) -> List[Tuple[Dict[str, Any], str]]:
    eng.step_logger._flush_buffer()
    out: List[Tuple[Dict[str, Any], str]] = []
    for raw in Path(eng.step_logger.output_file).read_text(encoding="utf-8").splitlines():
        match = _LINE_RE.match(raw)
        if match is None:
            assert " DECISION [" not in raw, f"ligne DECISION au format inattendu : {raw!r}"
            continue
        out.append(
            (
                {
                    "episode": int(match.group(1)),
                    "turn": int(match.group(2)),
                    "player": int(match.group(3)),
                    "phase": match.group(4),
                    "unit_id": match.group(5),
                    "decision_type": match.group(6),
                    "option_index": int(match.group(7)),
                    "label": match.group(8),
                    "declined": match.group("declined") is not None,
                },
                raw,
            )
        )
    return out


def test_reserves_declaration_writes_one_step_log_line_per_decision(tmp_path):
    """VERROU : retirer l'appel à `_record_agent_decision_action_log` rend ce test ROUGE."""
    eng = _engine(tmp_path)
    declared_id = _drive_deployment(eng, declare_first=True)
    assert declared_id, "aucune escouade déclarée : le scénario ne pose aucune question 20.01"

    lines = _decision_lines(eng)
    reserves = [row for row, _ in lines if row["decision_type"] == "reserves_declaration"]
    assert reserves, (
        "aucune ligne DECISION [reserves_declaration] dans step.log alors que le déploiement "
        "a répondu à au moins une question 20.01"
    )

    declaring = [row for row in reserves if row["option_index"] == 0]
    assert len(declaring) == 1, f"attendu 1 CHOICE_0, trouvé {len(declaring)} : {declaring}"
    assert declaring[0]["unit_id"] == declared_id
    assert declaring[0]["declined"] is False, "CHOICE_0 DÉCLARE : ce n'est pas le candidat qui passe"
    assert declaring[0]["phase"] == "DEPLOYMENT"
    assert declaring[0]["player"] in (1, 2)
    assert declaring[0]["turn"] >= 1
    assert declaring[0]["episode"] >= 1
    assert declaring[0]["label"], "le libellé du candidat joué doit être nommé"

    # Le second candidat est celui qui PASSE : sans ce marqueur, deux lignes de déclinaison et
    # deux lignes de déclaration se ressembleraient au caractère près hors de l'index.
    keeping = [row for row in reserves if row["option_index"] == 1]
    assert keeping, "aucune ligne CHOICE_1 : le déploiement n'a gardé aucune unité"
    assert all(row["declined"] for row in keeping), (
        "CHOICE_1 garde l'unité pour la mise en place : c'est le candidat `declines`"
    )


def test_declining_every_reserve_leaves_no_choice_zero_line(tmp_path):
    """VERT VACANT écarté : sans déclaration, il ne reste QUE des `CHOICE_1 [DECLINED]`.

    Si le relevé écrivait un index constant (ou omettait `declines`), le test précédent passerait
    quand même — c'est celui-ci qui prouve que la ligne SUIT le candidat réellement joué.
    """
    eng = _engine(tmp_path)
    assert _drive_deployment(eng, declare_first=False) == ""
    reserves = [
        row for row, _ in _decision_lines(eng)
        if row["decision_type"] == "reserves_declaration"
    ]
    assert reserves, "aucune question 20.01 posée : le scénario ne prouve rien"
    assert all(row["option_index"] == 1 and row["declined"] for row in reserves), (
        f"des CHOICE_0 apparaissent alors qu'aucune réserve n'a été déclarée : {reserves}"
    )


def test_agent_decision_does_not_double_count_a_gym_step(tmp_path):
    """`agent_decision` est non-incrémentant : une réponse 20.01 = un step moteur, un step logué.

    L'y compter doublerait `episode_step_count` face à `episode_steps` du moteur pour tout type
    dont l'effet produit déjà une ligne (charge, tir, move_after_shooting, rule_choice).
    """
    from engine.agent_decision import read_pending_agent_decision
    from engine.macro_intents import CHOICE_SLOTS
    from engine.w40k_core import W40KEngine

    assert _TYPE_JOURNAL in W40KEngine._STEP_LOG_TYPE_MAP, (
        "sans cette entrée, la ligne n'atteint jamais step.log (liste blanche)"
    )
    assert _TYPE_JOURNAL in W40KEngine._STEP_LOG_NON_INCREMENTING_TYPES

    eng = _engine(tmp_path)
    logger = eng.step_logger
    assert logger is not None
    eng.get_action_mask()
    assert read_pending_agent_decision(eng.game_state) is not None
    steps_before = int(eng.game_state["episode_steps"])
    logged_before = int(logger.episode_step_count)
    eng.step(int(CHOICE_SLOTS.start + 1))
    assert int(eng.game_state["episode_steps"]) == steps_before + 1
    assert int(logger.episode_step_count) == logged_before, (
        "la ligne de relevé ne doit pas incrémenter le compteur de steps du StepLogger"
    )


def test_la_ligne_de_decision_ne_porte_aucune_position_par_socle(tmp_path):
    """20.01 se joue AVANT toute mise en place : la ligne de décision ne porte AUCUN socle.

    VERT VACANT écarté par la mesure, et c'est tout l'objet du test : au moment où la décision
    est jouée, les positions LIVE de l'unité interrogée EXISTENT — six socles à (-1,-1), hors
    plateau. Un segment vide ne prouverait donc rien si on ne vérifiait pas d'abord que le repli
    avait quelque chose à mettre à la place ; les deux assertions de tête paient ce prix.

    L'enjeu n'est pas cosmétique : `analyzer_core` applique le segment de CHAQUE ligne à
    `positions_by_model` sans filtrer par type, donc ces six socles deviendraient l'état de
    positions du lecteur jusqu'à la ligne de déploiement de l'unité.
    """
    from engine.agent_decision import read_pending_agent_decision
    from engine.macro_intents import CHOICE_SLOTS

    eng = _engine(tmp_path)
    eng.get_action_mask()
    pending = read_pending_agent_decision(eng.game_state)
    assert pending is not None
    unit_id = str(pending["unit_id"])

    live = eng._models_segment_for_unit(unit_id)
    assert live.startswith("[MODELS:"), (
        f"positions LIVE absentes du cache : un segment vide ne prouverait plus rien ({live!r})"
    )
    assert "(-1,-1" in live, (
        f"unité déjà posée : le scénario ne joue plus 20.01 avant la mise en place ({live!r})"
    )

    eng.step(int(CHOICE_SLOTS.start + 0))
    lignes = [raw for _, raw in _decision_lines(eng)]
    assert len(lignes) == 1
    assert "[MODELS:" not in lignes[0], (
        f"la ligne de décision porte des positions par socle : {lignes[0]!r}"
    )


def test_le_type_tranche_le_segment_meme_quand_le_repli_aurait_de_quoi_ecrire(tmp_path):
    """C'est le TYPE qui décide du segment vide, pas l'absence de données à mettre dedans.

    `waaagh_call` et `oath_selection` (08.04) portent un `unitId` de la forme `P<n>` : en
    production leur segment est déjà vide, mais par ACCIDENT — `P1` est absent d'`units_cache`.
    Ce test leur passe donc un `unitId` d'unité RÉELLE, cas qu'aucun producteur ne produit :
    c'est le seul montage où l'accident et l'intention donnent des résultats différents, donc le
    seul qui prouve que la déclaration porte quelque chose.

    ⚠️ Les trois types sont écrits ICI, en clair, et NON lus depuis le frozenset de production.
    Les lire là-bas rendait le test vert-vacant, mesuré : retirer `waaagh_call` de la déclaration
    retirait du même geste le contrôle qui l'aurait vu partir, et les neuf tests restaient verts.
    L'égalité stricte ci-dessous force alors toute évolution de l'inventaire à être écrite des
    deux côtés — c'est-à-dire décidée, pas subie.
    """
    from engine.w40k_core import W40KEngine

    attendus = ("agent_decision", "oath_selection", "waaagh_call")
    assert tuple(sorted(W40KEngine._TYPES_SANS_SEGMENT_MODELS)) == attendus, (
        "l'inventaire des types qui n'observent aucune position a change : le mettre a jour ici "
        "aussi, apres avoir verifie que le nouveau type ne rend PAS compte d'un acte d'une unite "
        "posee (cf. `strategic_reserves_timeout`, volontairement absent)."
    )

    eng = _engine(tmp_path)
    eng.get_action_mask()
    unit_id = str(require_pending_unit(eng))
    assert eng._models_segment_for_unit(unit_id).startswith("[MODELS:"), (
        "le repli n'a rien à écrire : le test ne distinguerait pas le type de l'accident"
    )

    for type_declare in attendus:
        details = eng._build_step_log_details(
            {"type": type_declare, "unitId": unit_id, "turn": 1}, 1
        )
        assert details["models_segment"] == "", (
            f"le type {type_declare!r} est déclaré sans position, mais le point de traduction "
            f"lui a écrit {details['models_segment']!r}"
        )

    # Contre-épreuve : un type NON déclaré passe bien par le repli, sinon l'assertion ci-dessus
    # serait vraie pour n'importe quel type et ne dirait rien de la déclaration.
    temoin = eng._build_step_log_details({"type": "wait", "unitId": unit_id, "turn": 1}, 1)
    assert temoin["models_segment"].startswith("[MODELS:"), (
        f"le repli ne s'applique plus aux types non déclarés : {temoin['models_segment']!r}"
    )


def test_game_log_message_and_step_log_line_say_the_same_thing(tmp_path):
    """Le Game Log PvP et `step.log` partagent le MÊME constructeur de libellé.

    Deux formateurs séparés auraient divergé au premier ajustement, et l'analyzer ne lit QUE
    `step.log` : la divergence serait passée inaperçue jusqu'à un verdict faux.
    """
    from engine.agent_decision import read_pending_agent_decision
    from engine.macro_intents import CHOICE_SLOTS

    eng = _engine(tmp_path)
    eng.get_action_mask()
    assert read_pending_agent_decision(eng.game_state) is not None
    eng.step(int(CHOICE_SLOTS.start + 0))

    entries = [
        entry for entry in eng.game_state["action_logs"]
        if entry.get("type") == _TYPE_JOURNAL
    ]
    assert len(entries) == 1, f"attendu UNE entree action_log, trouve {len(entries)}"
    message = entries[0]["message"]
    assert message, "l'entree du Game Log PvP doit porter un libelle, pas une case vide"

    lines = [raw for _, raw in _decision_lines(eng)]
    assert len(lines) == 1
    assert lines[0].endswith(f"{message} [SUCCESS]"), (
        f"step.log dit {lines[0]!r}, le Game Log dit {message!r}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# NON-CONTOURNEMENT — le relevé est pris dans UN encadrement, à appelant unique
# ─────────────────────────────────────────────────────────────────────────────

#: Racines où un chemin de production peut vivre. Le front n'applique aucune décision : il envoie
#: une action, et c'est `_process_semantic_action` qui la route.
_RACINES_PRODUCTION: Tuple[str, ...] = ("engine", "ai", "services")


#: Les DEUX symboles de l'encadrement, gardés ensemble : l'application n'a de valeur mesurable
#: que suivie de son relevé, et le relevé n'a de sens que collé à l'application.
_SYMBOLES_GARDES: Tuple[str, str] = (
    "_dispatch_agent_decision_action", "_record_agent_decision_action_log"
)


#: Les deux fonctions MODULE-LEVEL d'écriture, et le seul endroit d'où chacune peut être nommée.
#: `append_agent_decision_log` est le constructeur dédié — `append_action_log` refuse le type, donc
#: c'est le SEUL chemin restant vers une entrée `agent_decision` ; `_append_entry` est l'écriture
#: nue qui contourne cette garde, partagée par les deux façades. Un nom se garde, alors qu'une
#: forme de dictionnaire ne se garde pas : c'est tout l'objet du déplacement.
#:
#: L'entrée `<module>` est la ligne d'`import` : elle est relevée exprès, de sorte qu'un fichier
#: qui importerait le symbole — fût-ce sous un alias, que l'appel rendrait invisible à un relevé
#: par nom — rougisse sur son import.
_SITES_D_ECRITURE: Dict[str, Set[Tuple[str, str]]] = {
    "append_agent_decision_log": {
        ("engine/w40k_core.py", "<module>"),
        ("engine/w40k_core.py", "_record_agent_decision_action_log"),
    },
    "_append_entry": {
        ("engine/action_log_utils.py", "append_action_log"),
        ("engine/action_log_utils.py", "append_agent_decision_log"),
    },
}


class _SondeParFonction(ast.NodeVisitor):
    """Relève EN UN PASSAGE qui NOMME les symboles gardés et qui ÉCRIT l'entrée de journal.

    Quatre prédicats, un seul parcours : des sondes séparées redescendraient les mêmes 664 875
    nœuds pour des prédicats indépendants — trois d'entre elles coûtaient déjà 1,04 s, mesuré,
    contre 0,34 s en un passage, à résultat strictement identique.

    `ast.walk` ne convient pas : il perd le contexte englobant, et c'est précisément le contexte
    qui est contrôlé ici — savoir QUI nomme et QUI écrit, pas combien de fois.
    """

    def __init__(self, chemin: str, releves: Dict[str, Set[Tuple[str, str]]]) -> None:
        self._chemin = chemin
        self._releves = releves
        self._pile: List[str] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._pile.append(node.name)
        self.generic_visit(node)
        self._pile.pop()

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

    def _releve(self, cle: str) -> None:
        self._releves[cle].add((self._chemin, self._pile[-1] if self._pile else "<module>"))

    def visit_Attribute(self, node: ast.Attribute) -> None:
        """L'ATTRIBUT, et non `Call.func` : une référence liée est un appel différé.

        `applique = self._dispatch_agent_decision_action` puis `applique(action)` applique une
        décision sans son relevé et n'apparaît dans AUCUN `ast.Call` visant le symbole — mutation
        appliquée, la sonde par appel restait VERTE.

        Le prédicat couvre AUSSI les fonctions d'écriture, et c'est le dernier chemin d'accès au
        constructeur dédié : `from engine import action_log_utils` puis
        `action_log_utils.append_agent_decision_log(gs, ...)` ne nomme aucun `Name` gardé et
        n'importe aucun symbole gardé — mesuré sur la sonde d'avant, 0 relevé sur les cinq clés.

        C'est le NOM DE L'ATTRIBUT qui est gardé, jamais le module qui le porte : interdire le
        handle du seul `engine.action_log_utils` laisserait ouvert
        `engine.w40k_core.append_agent_decision_log`, que le module réexporte (vérifié par import
        réel : les deux références rendent le même objet fonction).
        """
        if node.attr in _SYMBOLES_GARDES or node.attr in _SITES_D_ECRITURE:
            self._releve(node.attr)
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        """Les fonctions d'écriture sont MODULE-LEVEL : elles se nomment par `Name`, pas `Attribute`.

        Sans ce visiteur, déplacer la construction de l'entrée dans `action_log_utils` n'aurait
        rien fermé : `append_agent_decision_log(gs, ...)` appelé depuis n'importe quelle branche
        rendait 0 relevé, mesuré sur la sonde d'avant.
        """
        if node.id in _SITES_D_ECRITURE:
            self._releve(node.id)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """L'IMPORT du symbole, alias compris — un alias rend l'appel invisible, pas l'import.

        `from engine.action_log_utils import append_agent_decision_log as f` puis `f(gs, ...)` :
        aucun `Name` ne porte le nom gardé, mais l'import, lui, le nomme toujours. C'est le seul
        contrôle qui tienne quel que soit le nom local.
        """
        for alias in node.names:
            if alias.name in _SITES_D_ECRITURE:
                self._releve(alias.name)

    def visit_Dict(self, node: ast.Dict) -> None:
        """Le LITTÉRAL, et non l'appel à `append_action_log` : le dict porte le type.

        Un dict littéral relié à une variable avant d'être posté est relevé quand même — c'est la
        forme qu'emploient déjà quatre appelants de production. Ce qui ÉCHAPPE à ce contrôle, et
        qui n'est donc pas couvert : un type qui n'est pas un littéral au point de construction
        (`entree["type"] = ...` par affectation, `dict(type=...)`, valeur calculée).
        """
        if any(
            isinstance(cle, ast.Constant) and cle.value == "type"
            and isinstance(valeur, ast.Constant) and valeur.value == _TYPE_JOURNAL
            for cle, valeur in zip(node.keys, node.values)
        ):
            self._releve(_TYPE_JOURNAL)
        self.generic_visit(node)


#: Relevés de production, calculés UNE fois. Les ARBRES, eux, ne sont pas retenus : les garder
#: coûtait 171,8 MiB et 984 000 objets suivis par le GC pour la vie du worker pytest — un
#: `gc.collect(2)` y passait de 0,48 ms à 254,9 ms, mesuré. Un passage unique n'en a plus besoin.
_RELEVES: Dict[str, Set[Tuple[str, str]]] = {}


def _releves_production() -> Dict[str, Set[Tuple[str, str]]]:
    """`{clé -> {(chemin relatif, fonction englobante)}}` pour les deux symboles et le type."""
    if not _RELEVES:
        releves: Dict[str, Set[Tuple[str, str]]] = {
            cle: set() for cle in (*_SYMBOLES_GARDES, *_SITES_D_ECRITURE, _TYPE_JOURNAL)
        }
        fichiers = 0
        for racine in _RACINES_PRODUCTION:
            for chemin in sorted((PROJECT_ROOT / racine).rglob("*.py")):
                arbre = ast.parse(chemin.read_text(encoding="utf-8"), filename=str(chemin))
                _SondeParFonction(str(chemin.relative_to(PROJECT_ROOT)), releves).visit(arbre)
                fichiers += 1
        assert fichiers, f"aucun fichier de production sous {_RACINES_PRODUCTION} — sonde muette"
        _RELEVES.update(releves)
    return _RELEVES


def _referents(symbole: str) -> Set[Tuple[str, str]]:
    """Toutes les fonctions qui NOMMENT le symbole, appel, import ou simple référence."""
    assert symbole in _SYMBOLES_GARDES or symbole in _SITES_D_ECRITURE, (
        f"{symbole!r} n'est pas relevé par la sonde"
    )
    return _releves_production()[symbole]


def _producteurs_d_entree_journal() -> Set[Tuple[str, str]]:
    """Toutes les fonctions qui construisent un littéral d'entrée `agent_decision`."""
    return _releves_production()[_TYPE_JOURNAL]


@pytest.mark.parametrize("symbole", _SYMBOLES_GARDES)
def test_l_encadrement_du_releve_n_a_qu_un_appelant(symbole: str):
    """L'application d'une décision et son relevé ne s'appellent que depuis LE MÊME encadrement.

    CE QUE CE TEST VAUT, et pas plus : c'est du gardiennage contre un contournement, pas un
    verrou de mesure. Le mode de panne « un type de plus qui n'est pas journalisé » n'existe pas
    structurellement — la garde `NotImplementedError` de `_dispatch_agent_decision_action` force
    toute branche nouvelle à vivre DANS le dispatch, donc sous l'encadrement qui relève, et
    `ai/analyzer.py` compte les types par `defaultdict` sans en câbler aucun. Le douzième type
    (`reactive_move`) l'a vérifié en pratique : il est arrivé journalisé sans qu'une ligne de
    relevé ait été écrite pour lui. Ce qui reste possible, et que ce test barre, c'est un chemin
    qui appellerait l'application SANS son encadrement — la divergence que le site unique existe
    pour empêcher. La branche qui écrirait son propre relevé À CÔTÉ, elle, n'appelle ni l'un ni
    l'autre : elle passe ce test, et c'est
    `test_aucune_entree_agent_decision_n_est_ecrite_hors_du_site_unique` qui la barre.

    ⚠️ EXCEPTION LÉGITIME, à ne pas confondre avec un contournement :
    `_resolve_faction_decisions_for_ai_seats` applique `returned_models_profile`,
    `returned_models_placement` et `waaagh_call` en appelant les `apply_*_decision` des handlers
    DIRECTEMENT, sans relevé. Ce sont les sièges bot / PvE hors gym, dont les choix viennent des
    heuristiques `_select_ai_*` et non de la politique : les journaliser comme des décisions
    d'agent fausserait le taux mesuré. En gym, cette méthode sort immédiatement — les deux sièges
    répondent par le masque, donc par l'encadrement contrôlé ici.

    ⚠️ Pas de test paramétré sur les douze `AGENT_DECISION_TYPE_IDS` : les branches du dispatch
    exigent un état riche (contexte de tir, plan de charge, file 20.01,
    `_pending_exhortation_fight`, `pending_rule_choice_queue`, fenêtre réactive), et neutraliser
    le dispatch pour les atteindre rendrait le test vert pour n'importe quel type, y compris un
    type qui n'y serait pas branché.
    """
    attendu = {("engine/w40k_core.py", "_handle_agent_decision_action")}
    assert _referents(symbole) == attendu, (
        f"'{symbole}' ne doit etre nomme que dans `_handle_agent_decision_action` : une "
        f"application sans son releve fait diverger le journal des decisions de ce que l'agent a "
        f"reellement joue. Une reference liee ailleurs compte comme un appel — c'en est un, "
        f"differe."
    )


def test_aucune_entree_agent_decision_n_est_ecrite_hors_du_site_unique():
    """Un seul producteur construit l'entrée `agent_decision`, et c'est le constructeur dédié.

    Le verrou d'appelant ci-dessus ne barre pas ce chemin : une branche qui poste elle-même
    `{"type": "agent_decision", ...}` n'appelle ni l'application ni le relevé, et passe les deux
    paramétrages — mutation appliquée, vérifié vert. Ce qu'une telle entrée casserait, depuis que
    le segment de socles est une propriété du TYPE (`_TYPES_SANS_SEGMENT_MODELS`) et non plus une
    clé posée par ce producteur : plus les positions — elles sont hors d'atteinte d'un producteur
    — mais la MESURE. Une seconde entrée porte les quatre champs de décision ou elle fait lever le
    formateur ; si elle les porte, l'analyzer compte un choix que l'agent n'a jamais joué, et le
    taux de déclaration 20.01 devient faux sans qu'aucune ligne ne paraisse anormale.

    ⚠️ CE QUE CETTE SONDE-CI NE VOIT PAS, et qui n'est plus laissé ouvert pour autant : le type
    doit être un LITTÉRAL au point de construction (cf. `_SondeParFonction.visit_Dict`), donc une
    entrée dont le type est posé par affectation, par `dict(type=...)` ou par une valeur calculée
    lui échappe. Ces formes-là ne se ferment pas en énumérant des motifs — elles se ferment au
    GOULOT : `append_action_log` refuse désormais le type (`_TYPES_A_CONSTRUCTEUR_DEDIE`), et
    `_append_entry`, seul chemin qui contourne ce refus, est gardé par nom. La sonde par
    dictionnaire est conservée parce qu'elle voit ce qu'une garde d'exécution ne voit pas : une
    branche jamais atteinte, celle des mutations `if False:`.
    """
    attendu = {("engine/action_log_utils.py", "append_agent_decision_log")}
    assert _producteurs_d_entree_journal() == attendu, (
        "une entree d'action_log de type 'agent_decision' est construite hors de "
        "`append_agent_decision_log` : le site unique ne garantit plus ni le libelle partage avec "
        "le Game Log, ni le segment [MODELS:] vide."
    )


@pytest.mark.parametrize("symbole", sorted(_SITES_D_ECRITURE))
def test_les_fonctions_d_ecriture_ne_sont_nommees_qu_a_leur_site(symbole: str):
    """Le constructeur dédié et l'écriture nue ne se nomment QUE là où c'est prévu.

    C'est ce qui rend le déplacement de la construction utile plutôt que cosmétique. Sans ce
    test, `append_agent_decision_log` serait appelable depuis n'importe quelle branche : elle
    produirait une entrée BIEN formée — donc invisible à tous les contrôles de champs — que
    l'analyzer compterait comme un choix joué. Mesuré sur la sonde d'avant : un appel par `Name`
    et un import sous alias rendaient tous deux 0 relevé, comme la pose du type par affectation.

    `_append_entry` est gardée pour la même raison en sens inverse : c'est le chemin qui
    CONTOURNE la garde d'`append_action_log`, et une façade de plus l'ouvrirait à tout le monde.
    """
    assert _referents(symbole) == _SITES_D_ECRITURE[symbole], (
        f"'{symbole}' est nomme hors de son site : l'entree 'agent_decision' redeviendrait "
        f"productible ailleurs, et le taux de decisions mesure par l'analyzer compterait un "
        f"choix que l'agent n'a jamais joue. Un import, meme sous alias, compte comme un usage."
    )


def test_le_goulot_refuse_une_entree_de_decision_construite_a_la_main(tmp_path):
    """La garde d'exécution voit ce que la sonde par dictionnaire ne voit pas : le type calculé.

    Le dictionnaire est monté ici comme le monterait un contournement — clé posée par
    AFFECTATION, forme précisément invisible à `visit_Dict`. Sans la garde, cet appel écrit une
    seconde entrée sans que rien ne le signale.
    """
    from engine.action_log_utils import append_action_log

    eng = _engine(tmp_path)
    avant = len(eng.game_state["action_logs"])
    entree: Dict[str, Any] = {"message": "Unit 1 DECISION [x] CHOICE_0 [y]"}
    entree["type"] = _TYPE_JOURNAL
    with pytest.raises(ValueError, match="constructeur dedie"):
        append_action_log(eng.game_state, entree)
    assert len(eng.game_state["action_logs"]) == avant, (
        "l'entree refusee a quand meme ete ecrite : la garde doit lever AVANT l'append"
    )

    # Contre-épreuve : le goulot accepte tout autre type, sinon le refus ci-dessus serait celui
    # d'un goulot cassé et non celui d'un type réservé.
    temoin: Dict[str, Any] = {"type": "wait", "message": "Unit 1 WAIT"}
    append_action_log(eng.game_state, temoin)
    assert eng.game_state["action_logs"][-1] is temoin
    assert temoin["logSeq"] > 0, "l'entree acceptee doit recevoir son logSeq"


def test_le_constructeur_dedie_pose_exactement_les_clefs_attendues(tmp_path):
    """Les clés de l'entrée, verrouillées une par une — `reward` et `logSeq` compris.

    Ces deux-là sont lues avec un DÉFAUT (`w40k_core._build_step_log_details` : `raw_log.get(
    "reward", 0.0)`) : les perdre ne casse rien de visible, ni ligne manquante ni exception, et
    aucun autre test du dépôt ne les nomme. Le déplacement de la construction hors de
    `w40k_core` est exactement le geste qui pouvait les laisser tomber en silence.
    """
    from engine.action_log_utils import append_agent_decision_log

    eng = _engine(tmp_path)
    eng.get_action_mask()
    unit_id = require_pending_unit(eng)
    eng.game_state["action_logs"].clear()

    append_agent_decision_log(
        eng.game_state,
        decision_type="reserves_declaration",
        player=1,
        unit_id=unit_id,
        option_index=1,
        option_label="Garder pour la mise en place",
        declines=True,
    )
    entree = eng.game_state["action_logs"][-1]
    assert set(entree) == {
        "type", "message", "unitId", "player", "turn", "phase", "decision_type",
        "decision_option_index", "decision_option_label", "decision_option_declines",
        "reward", "logSeq",
    }, f"clefs de l'entree 'agent_decision' modifiees : {sorted(entree)}"
    assert entree["type"] == _TYPE_JOURNAL
    assert entree["reward"] == 0.0
    assert entree["decision_option_declines"] is True
    assert entree["turn"] == eng.game_state["turn"]
    assert entree["phase"] == str(eng.game_state["phase"])
    assert entree["message"].endswith("DECISION [reserves_declaration] CHOICE_1 "
                                      "[Garder pour la mise en place] [DECLINED]")
    assert "models_segment" not in entree, (
        "le segment de socles est une propriete du TYPE : le poser ici en ferait un jumeau"
    )


# ─────────────────────────────────────────────────────────────────────────────
# NON-CONTOURNEMENT — ce que la sonde statique ne peut PAS nommer, l'exécution le compte
# ─────────────────────────────────────────────────────────────────────────────


def test_une_entree_de_decision_ecrite_hors_encadrement_fait_lever_le_drainage(tmp_path):
    """Le drainage confronte les entrées transférées aux décisions RÉELLEMENT résolues.

    CE QUE CE TEST FERME, et qu'aucune sonde AST ne peut fermer : un accès dont le nom n'est
    écrit nulle part — `getattr(module, "append_" + "agent_decision_log")` — ou un type posé par
    affectation. Toutes ces formes finissent au MÊME endroit : une entrée de plus dans
    `action_logs`, sans que l'encadrement ait résolu quoi que ce soit. L'entrée est BIEN formée,
    donc invisible à tout contrôle de champs ; c'est le COMPTE qui la trahit, et il la trahit
    avant que `ai/analyzer.py` ne compte un choix que l'agent n'a jamais joué.

    L'entrée est écrite ici par le constructeur dédié, appelé hors de
    `W40KEngine._handle_agent_decision_action` : exactement ce que ferait la branche pirate.
    """
    from engine.action_log_utils import append_agent_decision_log
    from engine.macro_intents import CHOICE_SLOTS

    eng = _engine(tmp_path)
    eng.get_action_mask()
    unit_id = require_pending_unit(eng)
    append_agent_decision_log(
        eng.game_state,
        decision_type="reserves_declaration",
        player=1,
        unit_id=unit_id,
        option_index=0,
        option_label="Declarer en reserves",
        declines=False,
    )
    with pytest.raises(ValueError, match="agent_decision"):
        eng.step(int(CHOICE_SLOTS.start + 1))


def test_le_compteur_de_decisions_ne_survit_pas_a_un_episode(tmp_path):
    """Le compteur est purgé par `reset`, comme le curseur de drainage dont il est le jumeau.

    `reset` fait `game_state.update()` : le dict SURVIT d'un épisode à l'autre, et c'est pour
    cela que le curseur y est explicitement `pop`é. Le compteur est monté à la main ici, parce
    qu'un épisode qui le laisse non nul suppose une décision résolue sans drainage — le cas PvE
    hors StepLogger, qu'un test gym ne peut pas jouer. Ce qui est verrouillé est la conséquence :
    `reset` vide `action_logs`, donc un compteur survivant ferait lever le PREMIER drainage de
    l'épisode suivant, pour une divergence dont cet épisode n'est pas l'auteur.
    """
    from engine.w40k_core import W40KEngine

    eng = _engine(tmp_path)
    eng.game_state[W40KEngine.AGENT_DECISION_RESOLVED_KEY] = 3
    eng.reset(seed=1)
    assert W40KEngine.AGENT_DECISION_RESOLVED_KEY not in eng.game_state, (
        "le compteur de decisions resolues survit a `reset` : le premier drainage de l'episode "
        "suivant leverait sur une divergence heritee"
    )
    # Contre-épreuve : l'épisode suivant se déroule entièrement, donc le drainage ne lève pas.
    assert _drive_deployment(eng, declare_first=True)


def test_le_compte_tient_quand_une_fenetre_de_drainage_porte_plusieurs_decisions(tmp_path):
    """Versant PERMISSIF de l'invariant : deux décisions dans la MÊME fenêtre ne lèvent pas.

    ÉTAT MONTÉ À LA MAIN, et il le faut : mesuré sur un déploiement complet, l'histogramme des
    entrées `agent_decision` par fenêtre de drainage vaut `{1: 6, 0: 9}` — jamais 2. Le chemin
    gym résout UNE décision par step, et le seul producteur d'une rafale,
    `W40KEngine._resolve_reactive_move_decision_for_ai_seats`, sort immédiatement sous
    `gym_training_mode` — que branchent TOUS les chemins installant un StepLogger. Le cas ≥ 2 est
    donc inatteignable en gym, et un test qui se contenterait d'un déroulé réel serait VERT
    VACANT : il ne verrouillerait rien.

    L'état est monté exactement comme l'encadrement le monte — une entrée et une décision comptée
    par décision — parce que c'est la FORMULE qui est verrouillée ici. Sans ce test, revenir à
    « une action égale une entrée » ne ferait rougir personne, et cette formule-là fait lever une
    fenêtre réactive PvE parfaitement légitime.
    """
    from engine.action_log_utils import append_agent_decision_log
    from engine.w40k_core import W40KEngine

    eng = _engine(tmp_path)
    eng.get_action_mask()
    unit_id = require_pending_unit(eng)
    assert eng.game_state.get(W40KEngine.AGENT_DECISION_RESOLVED_KEY, 0) == 0, (
        "compteur deja non nul avant la mise en scene : ce test ne prouverait pas son cas"
    )
    for option_index in (0, 1):
        append_agent_decision_log(
            eng.game_state,
            decision_type="reserves_declaration",
            player=1,
            unit_id=unit_id,
            option_index=option_index,
            option_label="Declarer en reserves" if option_index == 0 else "Garder",
            declines=bool(option_index),
        )
    eng.game_state[W40KEngine.AGENT_DECISION_RESOLVED_KEY] = 2

    eng._flush_squad_action_logs_to_step_logger(eng.game_state["turn"])

    lignes = [row for row, _ in _decision_lines(eng)]
    assert len(lignes) == 2, (
        f"la fenetre devait transferer les DEUX entrees, step.log en porte {len(lignes)}"
    )
    assert eng.game_state[W40KEngine.AGENT_DECISION_RESOLVED_KEY] == 0, (
        "le compteur n'est pas remis a zero par le drainage : la fenetre suivante compterait a "
        "nouveau ces deux decisions et leverait a tort"
    )
