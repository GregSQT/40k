"""Verrou — la graine d'une évaluation contre checkpoints est tirée au hasard ET ANNONCÉE.

Deux exigences distinctes, et c'est la seconde qui manquait.

TIRÉE AU HASARD (2026-09-07) : `base_seed` valait 42 en dur, donc deux évaluations d'un même
modèle rejouaient les mêmes parties et rendaient le même score au bit près (vérifié le
2026-09-07 : 16/24/0 aux deux appels). Les décisions du curriculum se prenant désormais sur des
MOYENNES, moyenner trois blocs à graine fixe moyennait trois fois le même échantillon.

ANNONCÉE : la trace du tirage passait par `logging.info`, et le dépôt ne configure aucun handler
de logging — root logger à WARNING, zéro handler, `isEnabledFor(INFO)` faux. La ligne n'était
donc **jamais émise**. Une trace morte ne se voit pas : elle n'échoue pas, elle se tait. C'est la
raison d'être de ce fichier, et la raison pour laquelle `resolve_checkpoint_eval_seed` a été
extraite de `evaluate_against_checkpoints` — au milieu de cette dernière, la vérifier aurait exigé
un modèle, un pool de workers et des scénarios sur disque.
"""

from __future__ import annotations

import pytest

from ai.bot_evaluation import resolve_checkpoint_eval_seed


def test_a_supplied_seed_is_returned_untouched() -> None:
    """Un appelant qui veut rejouer une mesure passe sa graine, et elle ne bouge pas."""
    assert resolve_checkpoint_eval_seed(42) == 42
    assert resolve_checkpoint_eval_seed(0) == 0


def test_none_draws_a_seed_in_range() -> None:
    assert 0 <= resolve_checkpoint_eval_seed(None) < 2**31


def test_two_draws_differ() -> None:
    """Le tirage doit VARIER : c'est tout l'objet du changement.

    Une graine constante rendrait ce test vert par accident une fois sur 2**31 ; sur vingt
    tirages, une implémentation figée est certaine de le faire rougir.
    """
    draws = {resolve_checkpoint_eval_seed(None) for _ in range(20)}
    assert len(draws) > 1, f"vingt tirages ont rendu la même valeur : {draws}"


def test_the_draw_is_actually_printed(capsys) -> None:
    """LE VERROU DE CE FICHIER : la trace doit sortir, pas seulement être écrite.

    `logging.info` ne sortait pas — root logger à WARNING sans handler. Un test qui se
    contenterait de `caplog` passerait au vert sur l'implémentation morte, parce que `caplog`
    installe son propre handler et abaisse le niveau : il mesurerait l'enregistrement du message,
    pas son émission. `capsys` mesure ce que l'utilisateur voit.
    """
    seed = resolve_checkpoint_eval_seed(None)
    sortie = capsys.readouterr().out
    assert str(seed) in sortie, f"la graine tirée n'apparaît pas dans la sortie : {sortie!r}"
    assert "base_seed" in sortie


def test_nothing_is_printed_for_a_supplied_seed(capsys) -> None:
    """Rien à annoncer quand l'appelant décide : la ligne documente un TIRAGE."""
    resolve_checkpoint_eval_seed(7)
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("mauvais", [-1, 1.5, True, "42"])
def test_an_invalid_seed_is_refused(mauvais) -> None:
    with pytest.raises(ValueError, match="base_seed"):
        resolve_checkpoint_eval_seed(mauvais)
