"""Dépickle restreint des saves (F7) — `Documentation/Implémentation/A_faire/Security.md`.

Verrouille l'invariant : un fichier de save falsifié ne peut PAS exécuter de code au chargement.
Tout gadget d'exécution (`os.system`, `subprocess.Popen`, …) passe par `find_class` ; la liste
blanche l'en prive. Les tests couvrent les deux côtés : le refus, et le fait que les données
réellement produites par le jeu se relisent toujours.
"""

from __future__ import annotations

import os
import pickle
import struct

import pytest

from services.game_saves import SaveStore, _pack_record, _safe_loads


class _RceGadget:
    """Objet dont le dépickle exécuterait une commande — c'est le payload d'un attaquant."""

    def __reduce__(self):
        return (os.system, ("touch /tmp/w40k_pwned",))


class TestGadgetIsRefused:

    def test_os_system_payload_is_refused(self):
        with pytest.raises(pickle.UnpicklingError, match="classe interdite"):
            _safe_loads(pickle.dumps(_RceGadget()))

    def test_the_payload_would_really_execute_without_the_guard(self, tmp_path, monkeypatch):
        """Contre-épreuve : sans la liste blanche, CE payload s'exécute vraiment.

        Sans ce test, `test_os_system_payload_is_refused` prouverait seulement qu'un objet
        exotique est refusé — pas qu'on a bloqué une exécution de code réelle.
        """
        executed = tmp_path / "temoin"

        class _RealPayload:
            def __reduce__(self):
                return (os.system, (f"touch {executed}",))

        pickle.loads(pickle.dumps(_RealPayload()))  # dépickle NON restreint, volontairement
        assert executed.exists(), "le gadget de référence n'exécute rien : le test ne prouve rien"

    def test_arbitrary_class_is_refused_by_name(self):
        """Le message nomme la classe refusée : un type légitime nouveau doit être diagnosticable
        d'un coup d'œil, pas provoquer un échec opaque."""
        with pytest.raises(pickle.UnpicklingError, match="subprocess.Popen"):
            _safe_loads(_forged_global(b"subprocess", b"Popen"))


def _forged_global(module: bytes, name: bytes) -> bytes:
    """Pickle minimal réduit à un STACK_GLOBAL : le cas exact que `find_class` doit refuser."""
    return (
        b"\x80\x04"
        + b"\x8c" + bytes([len(module)]) + module
        + b"\x8c" + bytes([len(name)]) + name
        + b"\x93."
    )


class TestLegitimateDataStillLoads:

    def test_plain_state_shapes_round_trip(self):
        """Les formes réellement présentes dans un état capturé (mesurées sur un vrai fichier) :
        dicts à clés tuple (`occupation_map`), tuples, sets, clés int (`victory_points`)."""
        payload = {
            "occupation_map": {(1, 2): "u1", (3, 4): "u2"},
            "tuples": [(1, 2, 3)],
            "scored_turns": {1, 2, 3},
            "victory_points": {1: 10, 2: 5},
            "frozen": frozenset({"a"}),
        }
        assert _safe_loads(pickle.dumps(payload)) == payload

    def test_parsed_weapon_rule_is_allowed(self):
        """`ParsedWeaponRule` est capturé par centaines dans l'état (armes des unités) : le
        refuser casserait tout chargement de partie."""
        from engine.weapons.rules import ParsedWeaponRule

        rules = [r for r in _sample_parsed_rules()]
        restored = _safe_loads(pickle.dumps(rules))
        assert len(restored) == len(rules)
        assert all(isinstance(r, ParsedWeaponRule) for r in restored)


def _sample_parsed_rules():
    """Instances réelles, construites par le parseur du moteur (pas des stubs) : c'est bien
    l'objet que le jeu met dans l'état capturé qui doit traverser le dépickle restreint."""
    from engine.weapons.rules import WeaponRulesRegistry, parse_weapon_rules

    registry = WeaponRulesRegistry()
    names = [n for n, d in registry.get_all_rules().items() if not d.get("has_parameter")][:2]
    assert names, "registre de règles d'armes vide : l'échantillon ne prouverait rien"
    return parse_weapon_rules(names, registry)


class TestStoreReadPathIsGuarded:
    """Le garde doit être sur le chemin de PRODUCTION, pas seulement dans un helper : une save
    falsifiée doit être refusée par le `SaveStore` lui-même."""

    def test_forged_row_in_a_real_party_file_is_refused(self, tmp_path):
        """`point()` est le chemin qui désérialise VRAIMENT un state (Select / view / Resume) ;
        `list_all_rows` saute les states sans les lire, un piège y resterait invisible."""
        store = SaveStore(str(tmp_path / "parties"))
        os.makedirs(store._dir, exist_ok=True)
        meta_bytes = pickle.dumps({"id": "20260101-000000", "kind": "manual"})
        forged_state = pickle.dumps(_RceGadget())
        length = struct.Struct(">Q")
        with open(os.path.join(store._dir, "partie_piegee.pkl"), "wb") as f:
            f.write(b"W40KTL03")
            f.write(length.pack(len(meta_bytes)) + meta_bytes)
            f.write(length.pack(len(forged_state)) + forged_state)
        store.set_current("partie_piegee")

        with pytest.raises(pickle.UnpicklingError, match="classe interdite"):
            store.point("20260101-000000")

    def test_a_normal_party_file_still_reads(self, tmp_path):
        """Contre-épreuve : le fichier écrit par le jeu lui-même se relit sans erreur."""
        store = SaveStore(str(tmp_path / "parties"))
        os.makedirs(store._dir, exist_ok=True)
        row = {
            "meta": {"id": "20260101-000000", "kind": "manual", "turn": 1},
            "state": {"game_state": {"occupation_map": {(1, 2): "u1"}}, "engine_attrs": {}},
        }
        with open(os.path.join(store._dir, "partie_saine.pkl"), "wb") as f:
            f.write(b"W40KTL03")
            f.write(_pack_record(row))
        store.set_current("partie_saine")

        loaded = store.point("20260101-000000")
        assert loaded["meta"]["id"] == "20260101-000000"
        assert loaded["state"]["game_state"]["occupation_map"] == {(1, 2): "u1"}
