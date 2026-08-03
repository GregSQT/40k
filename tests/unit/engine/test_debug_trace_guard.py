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

#: Fonctions dont le 3ᵉ argument est un format relayé tel quel à `trace`. Sans elles, le garde
#: ne verrait que les appels directs : `_debug_train_marker` a justement vécu un temps avec une
#: signature `(message)` que ses 12 appelants nourrissaient de f-strings — le canal `train`
#: était intégralement hors garde pendant que ce fichier déclarait le contraire.
_TRACE_RELAYS = ("trace", "_debug_train_marker")


def _traced_files() -> "list[str]":
    """Fichiers qui importent `engine.debug_trace`, DÉCOUVERTS et non listés à la main.

    Une liste-miroir tenue à la main rétrécit en silence : le jour où un cinquième fichier se
    met à tracer, il échappe au garde sans que rien ne rougisse. C'est le mode d'échec n°1 de
    ce dépôt (JUMEAU) appliqué à son propre verrou.
    """
    found = []
    for package in ("engine", "ai", "services", "scripts"):
        for path in sorted((_REPO_ROOT / package).rglob("*.py")):
            if path.name == "debug_trace.py":
                continue
            if "engine.debug_trace" in path.read_text(encoding="utf-8"):
                found.append(str(path.relative_to(_REPO_ROOT)))
    return found


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


def test_engine_step_writes_nothing_on_the_production_path(make_active_deployment_engine):
    """Le vrai chemin : un `step` complet en `debug_mode=False` n'écrit pas un octet.

    C'est le test que réclamait §0.46 — il porte sur `W40KEngine.step`, pas sur le helper,
    donc il couvre aussi une trace qui contournerait `debug_trace`.
    """
    eng = make_active_deployment_engine(seed=1)
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


def test_the_traced_file_discovery_finds_the_known_sites():
    """CONTRE LE VERT VACANT : une découverte qui ne trouve rien rendrait le garde muet."""
    discovered = _traced_files()
    for expected in ("engine/w40k_core.py", "engine/action_decoder.py", "ai/env_wrappers.py", "ai/train.py"):
        assert expected in discovered, f"{expected} n'est plus vu comme fichier trace"


@pytest.mark.parametrize("relative_path", _traced_files())
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
        if name not in _TRACE_RELAYS or not node.args:
            continue
        # trace(channel, debug_mode, fmt, *args) -> format en 3e position ;
        # _debug_train_marker(fmt, *args) -> format en 1re. On prend le premier argument
        # litteral-ou-format, c'est-a-dire le dernier avant les valeurs interpolees.
        fmt_index = 2 if name == "trace" else 0
        if len(node.args) <= fmt_index:
            continue
        fmt = node.args[fmt_index]
        if isinstance(fmt, ast.JoinedStr):
            offenders.append((node.lineno, "f-string"))
        elif isinstance(fmt, ast.BinOp) and isinstance(fmt.op, (ast.Mod, ast.Add)):
            offenders.append((node.lineno, "formatage applique avant l'appel"))
        # `trace` n'accepte AUCUN mot-cle : sa signature est (channel, debug_mode, fmt, *args).
        # Un `flush=True` oublie en migrant un `print` leve un TypeError — mais seulement quand
        # la trace s'allume, donc jamais en run normal, jamais dans un test qui n'active pas ce
        # canal. C'est exactement ce qui est passe entre les mailles ici : le site fautif etait
        # dans `BotControlledEnv`, qu'aucun smoke sur moteur nu n'atteint.
        for keyword in node.keywords:
            offenders.append((node.lineno, f"mot-cle interdit : {keyword.arg}"))

    assert not offenders, (
        f"{relative_path} : le format est construit AVANT la garde, "
        f"donc payé en production — {offenders}"
    )


def test_channel_selection_restricts_output_to_the_named_channels(monkeypatch):
    """`W40K_TRACE=bot_loop` éteint les autres canaux — la raison d'être de l'axe C.

    Un simple `monkeypatch.setenv` suffit : la sélection est RELUE à chaque appel, jamais
    mémoïsée. C'est le patron de `engine/mask_verification.py` (« la valeur n'est PAS
    memoisee ici : elle reste relue a chaque appel, sinon les tests ne pourraient plus
    l'armer dynamiquement »), et il évite à ces tests la cérémonie d'un `importlib.reload`.
    """
    monkeypatch.setenv("W40K_TRACE", "bot_loop")
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        trace(CH_BOT_LOOP, True, "retenu")
        trace(CH_STEP, True, "ecarte")
        trace(CH_DEPLOY_CACHE, True, "ecarte")
    out = buffer.getvalue()
    assert "retenu" in out
    assert "ecarte" not in out


def test_absent_variable_keeps_every_channel_on(monkeypatch):
    """Sans `W40K_TRACE`, `--debug` allume tout : le comportement historique est préservé."""
    monkeypatch.delenv("W40K_TRACE", raising=False)
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        for channel in TRACE_CHANNELS:
            trace(channel, True, "canal_%s", channel)
    for channel in TRACE_CHANNELS:
        assert f"canal_{channel}" in buffer.getvalue()


def test_none_switches_every_channel_off_even_under_debug(monkeypatch):
    """`W40K_TRACE=none` : le mode debug reste actif pour le reste, les traces se taisent."""
    monkeypatch.setenv("W40K_TRACE", "none")
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        for channel in TRACE_CHANNELS:
            trace(channel, True, "rien")
    assert buffer.getvalue() == ""


def test_an_empty_variable_raises_instead_of_silently_muting_everything(monkeypatch):
    """`W40K_TRACE=` (définie mais vide) lève : son intention est ambiguë.

    Trouvé en exerçant le vrai chemin, pas en test : la lecture naïve donnait « aucun canal »,
    donc un `export W40K_TRACE=` — ou une substitution de shell qui ne rend rien — éteignait
    TOUTES les traces sans le dire. C'est le défaut que ce module existe pour empêcher.
    """
    monkeypatch.setenv("W40K_TRACE", "")
    with pytest.raises(ValueError):
        channel_enabled(CH_STEP, True)


def test_a_typo_in_the_variable_raises_instead_of_going_quiet(monkeypatch):
    """Un canal mal orthographié dans `W40K_TRACE` lève.

    Sans cela, `W40K_TRACE=botloop` produirait un run parfaitement silencieux : on
    conclurait que le chemin n'est pas emprunté alors qu'il l'est.
    """
    monkeypatch.setenv("W40K_TRACE", "botloop")
    with pytest.raises(ValueError):
        channel_enabled(CH_STEP, True)


def test_the_variable_is_validated_at_import_too(monkeypatch):
    """La faute de frappe lève AUSSI au chargement du module, pas seulement au 1er appel.

    Les deux temps comptent : à l'import pour échouer avant que le run ne démarre, à l'appel
    pour rester armable dynamiquement. Vérifier l'un sans l'autre laisserait retirer celui
    qu'on ne teste pas.
    """
    import importlib

    monkeypatch.setenv("W40K_TRACE", "botloop")
    with pytest.raises(ValueError):
        importlib.reload(__import__("engine.debug_trace", fromlist=["_selected_channels"]))
    monkeypatch.delenv("W40K_TRACE", raising=False)
    importlib.reload(__import__("engine.debug_trace", fromlist=["_selected_channels"]))


def test_unknown_channel_raises_rather_than_staying_silent():
    """Un canal mal orthographié lève. Une trace qu'on croit allumée et qui ne l'est pas est pire
    que pas de trace du tout — c'est le diagnostic lui-même qui devient faux."""
    with pytest.raises(ValueError):
        channel_enabled("bot-loop", True)


def test_every_declared_channel_is_actually_used():
    """Un canal déclaré et jamais posé sur un site est un canal mort : il ferait croire à une
    couverture qui n'existe pas quand on écrit `W40K_TRACE=<ce canal>`."""
    used = set()
    for relative_path in _traced_files():
        source = (_REPO_ROOT / relative_path).read_text(encoding="utf-8")
        for channel_const in ("CH_STEP", "CH_BOT_LOOP", "CH_DEPLOY_CACHE", "CH_TRAIN"):
            if channel_const in source:
                used.add(channel_const)
    assert used == {"CH_STEP", "CH_BOT_LOOP", "CH_DEPLOY_CACHE", "CH_TRAIN"}, (
        f"canaux declares mais jamais poses sur un site : "
        f"{ {'CH_STEP', 'CH_BOT_LOOP', 'CH_DEPLOY_CACHE', 'CH_TRAIN'} - used }"
    )
    assert set(TRACE_CHANNELS) == {CH_STEP, CH_BOT_LOOP, CH_DEPLOY_CACHE, CH_TRAIN}
