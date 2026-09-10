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
    TYPE qui le déclare (`W40KEngine._TYPES_SANS_SEGMENT_MODELS`), au point de traduction unique.
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


class _SondeParFonction(ast.NodeVisitor):
    """Relève EN UN PASSAGE qui NOMME les symboles gardés et qui ÉCRIT l'entrée de journal.

    Trois questions, un seul parcours : trois sondes séparées redescendaient les mêmes 664 875
    nœuds pour trois prédicats indépendants — 1,04 s au total, mesuré, contre 0,34 s en un
    passage, à résultat strictement identique.

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
        """
        if node.attr in _SYMBOLES_GARDES:
            self._releve(node.attr)
        self.generic_visit(node)

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
            cle: set() for cle in (*_SYMBOLES_GARDES, _TYPE_JOURNAL)
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
    """Toutes les fonctions qui NOMMENT le symbole, appel ou simple référence."""
    assert symbole in _SYMBOLES_GARDES, f"{symbole!r} n'est pas relevé par la sonde"
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
    """Un seul producteur construit l'entrée `agent_decision` — sous sa forme LITTÉRALE.

    Le verrou d'appelant ci-dessus ne barre pas ce chemin : une branche qui poste elle-même
    `{"type": "agent_decision", ...}` n'appelle ni l'application ni le relevé, et passe les deux
    paramétrages — mutation appliquée, vérifié vert. Ce qu'une telle entrée casserait, depuis que
    le segment de socles est une propriété du TYPE (`_TYPES_SANS_SEGMENT_MODELS`) et non plus une
    clé posée par ce producteur : plus les positions — elles sont hors d'atteinte d'un producteur
    — mais la MESURE. Une seconde entrée porte les quatre champs de décision ou elle fait lever le
    formateur ; si elle les porte, l'analyzer compte un choix que l'agent n'a jamais joué, et le
    taux de déclaration 20.01 devient faux sans qu'aucune ligne ne paraisse anormale.

    ⚠️ CE QUE CE TEST NE VOIT PAS, dit ici plutôt que sous-entendu : le type doit être un
    LITTÉRAL au point de construction du dict (cf. `_SondeParFonction.visit_Dict`). Une entrée
    dont le type est posé par affectation, par `dict(type=...)` ou par une valeur calculée passe.
    Fermer ces formes-là ne se fait pas en énumérant des motifs : le seul goulot réel est
    `append_action_log` (`engine/action_log_utils.py`), unique chemin vers `action_logs` en
    production — vérifié, aucun `action_logs.append` direct hors des tests.
    """
    attendu = {("engine/w40k_core.py", "_record_agent_decision_action_log")}
    assert _producteurs_d_entree_journal() == attendu, (
        "une entree d'action_log de type 'agent_decision' est construite hors de "
        "`_record_agent_decision_action_log` : le site unique ne garantit plus ni le libelle "
        "partage avec le Game Log, ni le segment [MODELS:] vide."
    )
