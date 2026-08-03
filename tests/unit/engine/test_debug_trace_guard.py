"""La garde des traces `[TRAIN DEBUG]` — V11 §0.46 point 3, axes B et C.

CE QUE CE FICHIER EMPÊCHE. Les 37 traces sont gratuites en production PAR CONSTRUCTION :
préfixe, formatage et `flush` vivent derrière la garde de `debug_trace.trace`. Rien
n'obligeait cette propriété à se maintenir — une trace future écrite en f-string
(`trace(CH, dbg, f"x={x}")`) formaterait AVANT l'appel, donc hors garde, et déplacerait le
coût sur le chemin de `step`. Le défaut serait invisible : même sortie, même tests verts.

Deux verrous, l'un dynamique (rien n'est écrit), l'autre statique (personne ne peut plus
écrire un site en f-string).
"""

import ast
import io
import pathlib
import contextlib

import pytest

from engine.debug_trace import (
    CH_BOT_LOOP,
    CH_DEPLOY_CACHE,
    CH_STEP,
    CH_TRAIN,
    TRACE_CHANNELS,
    channel_enabled,
    trace,
)

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]

#: Les fichiers qui portent des traces. Si un cinquième s'y met, il DOIT être ajouté ici —
#: sinon l'analyse statique ci-dessous ne le couvre pas et le verrou devient décoratif.
_TRACED_FILES = (
    "engine/w40k_core.py",
    "engine/action_decoder.py",
    "ai/env_wrappers.py",
    "ai/train.py",
)


def test_trace_writes_nothing_when_debug_is_off():
    """La garde maîtresse : `debug_mode=False` n'écrit rien, quel que soit le canal."""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        for channel in TRACE_CHANNELS:
            trace(channel, False, "ceci ne doit jamais sortir %s", object())
    assert buffer.getvalue() == ""


def test_trace_writes_when_debug_is_on():
    """CONTRE LE VERT VACANT : le test précédent ne vaut que si la trace sait écrire."""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        trace(CH_STEP, True, "valeur=%s", 42)
    out = buffer.getvalue()
    assert "[TRAIN DEBUG]" in out and "valeur=42" in out


def test_engine_step_writes_nothing_on_the_production_path():
    """Le vrai chemin : un `step` complet en `debug_mode=False` n'écrit pas un octet.

    C'est le test que réclamait §0.46 — il porte sur `W40KEngine.step`, pas sur le helper,
    donc il couvre aussi une trace qui contournerait `debug_trace`.
    """
    from ai.unit_registry import UnitRegistry
    from engine.w40k_core import W40KEngine

    eng = W40KEngine(
        rewards_config="ArmageddonAgent",
        training_config_name="x1_debug",
        controlled_agent="ArmageddonAgent",
        scenario_file="config/agents/ArmageddonAgent/scenarios/holdout_regular/scenario_bot-01.json",
        unit_registry=UnitRegistry(),
        quiet=True,
        gym_training_mode=True,
    )
    eng.reset(seed=1)
    assert eng.debug_mode is False, "ce test n'a de sens qu'avec le mode debug ETEINT"

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        for _ in range(30):
            mask = eng.get_action_mask()
            legal = [i for i, ok in enumerate(mask) if ok]
            if not legal:
                break
            _obs, _rew, terminated, truncated, _info, _m = eng.step_with_mask(legal[0])
            if terminated or truncated:
                break
    assert buffer.getvalue() == "", (
        "le chemin de production a ecrit sur stdout :\n" + buffer.getvalue()[:2000]
    )


@pytest.mark.parametrize("relative_path", _TRACED_FILES)
def test_no_trace_site_formats_its_message_before_the_call(relative_path: str):
    """Analyse statique : aucun appel à `trace(...)` ne passe une f-string ni une concaténation.

    Un littéral implicitement concaténé (« "a" "b" ») reste UN littéral et donc gratuit :
    c'est une `ast.Constant`, pas un `JoinedStr`. Ce qui est refusé ici, ce sont les
    `f"..."` (`ast.JoinedStr`), les `%` et les `+` appliqués au format — trois façons de
    faire le travail avant que la garde ne puisse l'éviter.
    """
    source = (_REPO_ROOT / relative_path).read_text(encoding="utf-8")
    tree = ast.parse(source)

    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if name != "trace" or not node.args:
            continue
        # trace(channel, debug_mode, fmt, *args) -> le format est le 3e argument
        if len(node.args) < 3:
            continue
        fmt = node.args[2]
        if isinstance(fmt, ast.JoinedStr):
            offenders.append((node.lineno, "f-string"))
        elif isinstance(fmt, ast.BinOp) and isinstance(fmt.op, (ast.Mod, ast.Add)):
            offenders.append((node.lineno, "formatage applique avant l'appel"))

    assert not offenders, (
        f"{relative_path} : le format est construit AVANT la garde, "
        f"donc payé en production — {offenders}"
    )


def _reload_debug_trace(monkeypatch, env_value):
    """Recharge le module avec `W40K_TRACE` positionnée : la sélection est résolue AU CHARGEMENT.

    Elle l'est volontairement (relire `os.environ` à chaque trace mettrait un accès
    d'environnement sur le chemin de `step`), donc un test qui se contenterait de poser la
    variable ne changerait rien — il testerait le module déjà chargé et passerait au vert
    sans rien vérifier.
    """
    import importlib

    import engine.debug_trace as module

    if env_value is None:
        monkeypatch.delenv("W40K_TRACE", raising=False)
    else:
        monkeypatch.setenv("W40K_TRACE", env_value)
    return importlib.reload(module)


def test_channel_selection_restricts_output_to_the_named_channels(monkeypatch):
    """`W40K_TRACE=bot_loop` éteint les autres canaux — la raison d'être de l'axe C."""
    module = _reload_debug_trace(monkeypatch, "bot_loop")
    try:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            module.trace(module.CH_BOT_LOOP, True, "retenu")
            module.trace(module.CH_STEP, True, "ecarte")
            module.trace(module.CH_DEPLOY_CACHE, True, "ecarte")
        out = buffer.getvalue()
        assert "retenu" in out
        assert "ecarte" not in out
    finally:
        _reload_debug_trace(monkeypatch, None)


def test_absent_variable_keeps_every_channel_on(monkeypatch):
    """Sans `W40K_TRACE`, `--debug` allume tout : le comportement historique est préservé."""
    module = _reload_debug_trace(monkeypatch, None)
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        for channel in module.TRACE_CHANNELS:
            module.trace(channel, True, "canal_%s", channel)
    for channel in module.TRACE_CHANNELS:
        assert f"canal_{channel}" in buffer.getvalue()


def test_none_switches_every_channel_off_even_under_debug(monkeypatch):
    """`W40K_TRACE=none` : le mode debug reste actif pour le reste, les traces se taisent."""
    module = _reload_debug_trace(monkeypatch, "none")
    try:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            for channel in module.TRACE_CHANNELS:
                module.trace(channel, True, "rien")
        assert buffer.getvalue() == ""
    finally:
        _reload_debug_trace(monkeypatch, None)


def test_an_empty_variable_raises_instead_of_silently_muting_everything(monkeypatch):
    """`W40K_TRACE=` (définie mais vide) lève : son intention est ambiguë.

    Trouvé en exerçant le vrai chemin, pas en test : la lecture naïve donnait « aucun canal »,
    donc un `export W40K_TRACE=` — ou une substitution de shell qui ne rend rien — éteignait
    TOUTES les traces sans le dire. C'est le défaut que ce module existe pour empêcher.
    """
    with pytest.raises(ValueError):
        _reload_debug_trace(monkeypatch, "")
    _reload_debug_trace(monkeypatch, None)


def test_a_typo_in_the_variable_raises_at_load_instead_of_going_quiet(monkeypatch):
    """Un canal mal orthographié dans `W40K_TRACE` lève au chargement.

    Sans cela, `W40K_TRACE=botloop` produirait un run parfaitement silencieux : on
    conclurait que le chemin n'est pas emprunté alors qu'il l'est.
    """
    with pytest.raises(ValueError):
        _reload_debug_trace(monkeypatch, "botloop")
    _reload_debug_trace(monkeypatch, None)


def test_unknown_channel_raises_rather_than_staying_silent():
    """Un canal mal orthographié lève. Une trace qu'on croit allumée et qui ne l'est pas est pire
    que pas de trace du tout — c'est le diagnostic lui-même qui devient faux."""
    with pytest.raises(ValueError):
        channel_enabled("bot-loop", True)


def test_every_declared_channel_is_actually_used():
    """Un canal déclaré et jamais posé sur un site est un canal mort : il ferait croire à une
    couverture qui n'existe pas quand on écrit `W40K_TRACE=<ce canal>`."""
    used = set()
    for relative_path in _TRACED_FILES:
        source = (_REPO_ROOT / relative_path).read_text(encoding="utf-8")
        for channel_const in ("CH_STEP", "CH_BOT_LOOP", "CH_DEPLOY_CACHE", "CH_TRAIN"):
            if channel_const in source:
                used.add(channel_const)
    assert used == {"CH_STEP", "CH_BOT_LOOP", "CH_DEPLOY_CACHE", "CH_TRAIN"}, (
        f"canaux declares mais jamais poses sur un site : "
        f"{ {'CH_STEP', 'CH_BOT_LOOP', 'CH_DEPLOY_CACHE', 'CH_TRAIN'} - used }"
    )
    assert set(TRACE_CHANNELS) == {CH_STEP, CH_BOT_LOOP, CH_DEPLOY_CACHE, CH_TRAIN}
