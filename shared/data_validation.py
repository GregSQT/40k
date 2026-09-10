"""
Validation helpers for enforcing strict configuration and data requirements.

These helpers centralize the "raise on missing / invalid" behavior required by
the AI coding rules so that all modules can share a single, explicit pattern.
"""

from __future__ import annotations

from typing import Any, Mapping, TypeVar


T = TypeVar("T")
_KT = TypeVar("_KT")


class ConfigurationError(RuntimeError):
    """Raised when required configuration or structural data is missing."""


def require_present(value: T | None, name: str) -> T:
    """
    Ensure that a value is present (not None).

    This is the preferred way to validate externally provided values, such as
    data loaded from JSON, environment variables, or external services.
    """
    if value is None:
        raise ConfigurationError(f"Required value '{name}' is missing.")
    return value


def require_key(mapping: Mapping[_KT, Any], key: _KT) -> Any:
    """
    Ensure that a key exists in a mapping (typically configuration dictionaries).

    This helper must be used instead of direct dictionary access whenever
    a key is required by design. It raises immediately if the key is absent.
    """
    if key not in mapping:
        raise ConfigurationError(f"Required key '{key}' is missing from mapping.")
    return mapping[key]


def require_non_negative_int(value: Any, name: str) -> int:
    """Ensure that a value is an integer >= 0 (booleans excluded)."""
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConfigurationError(
            f"'{name}' must be an integer (got {type(value).__name__}: {value!r})"
        )
    if value < 0:
        raise ConfigurationError(f"'{name}' must be >= 0 (got {value})")
    return value


def require_positive_int(value: Any, name: str) -> int:
    """
    Ensure that a value is a strictly positive integer (booleans excluded).

    `bool` is a subclass of `int` : sans l'exclusion explicite, `True` passerait pour `1`. Ce
    detail etait recopie a la main sur chaque garde, donc voue a etre oublie quelque part.
    """
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConfigurationError(
            f"'{name}' must be an integer (got {type(value).__name__}: {value!r})"
        )
    if value <= 0:
        raise ConfigurationError(f"'{name}' must be > 0 (got {value})")
    return value


# Valeur du champ `hazardContext` émis par step_logger pour un Desperate Escape (09.07).
# Partagée entre ai/step_logger.py et engine/phase_handlers/shared_utils.py pour éviter
# toute divergence silencieuse entre l'émetteur et le lecteur du tag [DESPERATE ESCAPE].
HAZARD_CONTEXT_DESPERATE_ESCAPE = "Desperate Escape"

# Blessures mortelles infligées par une CAPACITÉ de datasheet (06.02), pas par un jet de hasard
# (24.15 / 09.07). Elles empruntent la ligne `SUFFERS N Mortal Wounds <tag>` — c'est déjà la
# ligne générique des blessures mortelles, Desperate Escape n'étant pas non plus une arme
# [HAZARDOUS] — mais leur tag doit rester DISTINCT : l'analyzer ne déclenche le contrôle
# d'armurerie [HAZARDOUS] que sur le tag de 24.15, et compter ces blessures là fausserait §1.8.
HAZARD_CONTEXT_HOLD_STILL = "Hold Still and Say Aargh"
HAZARD_CONTEXT_EXHORTATION = "Exhortation de Rage"

#: `hazardContext` -> tag écrit dans step.log. Table UNIQUE : l'émetteur (moteur) pose le
#: contexte, le formateur (step_logger) y lit le tag et l'analyzer y lit la liste des tags
#: qu'il doit reconnaître, si bien qu'aucun des trois ne peut en ignorer un que les autres
#: connaissent. Un contexte hors table est une erreur, jamais un tag par défaut.
HAZARD_CONTEXT_TAGS = {
    HAZARD_CONTEXT_DESPERATE_ESCAPE: "[DESPERATE ESCAPE]",
    HAZARD_CONTEXT_HOLD_STILL: "[HOLD STILL AND SAY AARGH]",
    HAZARD_CONTEXT_EXHORTATION: "[EXHORTATION DE RAGE]",
}




