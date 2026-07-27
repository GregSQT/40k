"""Verrou : le « Structure Overview » / « Section Breakdown » d'AI_OBSERVATION.md dit vrai.

Ce depot a ete mordu trois fois en deux jours par une doc d'observation perimee : les
« 12 unit-rule flags » du layout `obs[314:346]`, les features calculees `favorite_target`, et des
tailles figees (20 166) devenues fausses. La cause est toujours la meme — une doc qui RECOPIE le
schema derive du code sans que rien ne le signale.

Ce test ferme la boucle : la doc doit mentionner CHAQUE feature du schema d'entites, et les
tailles qu'elle affiche doivent etre celles que le code calcule. Ajouter une feature sans
documenter fait echouer ce fichier, exactement comme une regression de code.

Il ne verifie PAS la prose (elle doit rester libre) — seulement que chaque nom de feature et
chaque cardinalite y figurent.
"""

from __future__ import annotations

import os
import re

import numpy as np

from engine.observation_builder import ObservationBuilder
from engine.observation_entities import (
    GLOBAL_BIN_FIELDS,
    GLOBAL_CONT_FIELDS,
    MODEL_TYPE_BIN_FIELDS,
    MODEL_TYPE_CONT_FIELDS,
    SELF_MODEL_BIN_FIELDS,
    SELF_MODEL_CONT_FIELDS,
    UNIT_BIN_FIELDS,
    UNIT_CONT_FIELDS,
)
from engine.observation_weapon_profiles import ANTI_KEYWORDS, WEAPON_RULE_BITS, WEAPON_RULE_PARAMS

DOC = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "Documentation",
    "AI_OBSERVATION.md",
)


def _doc() -> str:
    with open(DOC, encoding="utf-8") as handle:
        return handle.read()


def test_every_schema_field_is_documented():
    """Chaque nom de feature du schema apparait dans la doc."""
    text = _doc()
    groups = {
        "global_cont": GLOBAL_CONT_FIELDS,
        "global_bin": GLOBAL_BIN_FIELDS,
        "unit_cont": UNIT_CONT_FIELDS,
        "unit_bin": UNIT_BIN_FIELDS,
        "model_type_cont": MODEL_TYPE_CONT_FIELDS,
        "model_type_bin": MODEL_TYPE_BIN_FIELDS,
        "self_model_cont": SELF_MODEL_CONT_FIELDS,
        "self_model_bin": SELF_MODEL_BIN_FIELDS,
    }
    missing = []
    for group, fields in groups.items():
        for field in fields:
            # Les series indexees sont documentees par leur forme abregee (`objective_distance_0..4`,
            # `objective_dir_cos/sin_0..4`) : on accepte le nom exact OU sa racine.
            root = re.sub(r"_\d+$", "", field)
            if field not in text and root not in text:
                missing.append(f"{group}.{field}")
    assert not missing, (
        "features absentes d'AI_OBSERVATION.md (Section Breakdown a mettre a jour) : "
        + ", ".join(missing)
    )


def test_weapon_profile_rules_are_documented():
    """Les bits et parametres de regles d'armes, et les keywords ANTI, sont documentes."""
    text = _doc()
    missing = [b for b in WEAPON_RULE_BITS if b not in text]
    missing += [p for p, _ in WEAPON_RULE_PARAMS if p not in text]
    missing += [k for k in ANTI_KEYWORDS if k not in text]
    assert not missing, "regles d'armes absentes de la doc : " + ", ".join(missing)


def _structure_overview() -> str:
    """Le seul bloc « Structure Overview », isole.

    Verifier les tailles sur le fichier ENTIER ne mord PAS : l'historique d'`obs_size` cite
    toutes les valeurs passees, donc n'importe quel total s'y trouve. Constate par mutation —
    la doc annoncait 20 166 et le test restait vert. On isole donc le bloc, seul endroit qui
    doit dire la verite COURANTE.
    """
    text = _doc()
    start = text.index("### Structure Overview")
    end = text.index("### Section Breakdown", start)
    return text[start:end]


def test_documented_sizes_match_the_computed_schema():
    """Les tailles du Structure Overview sont celles que le code calcule.

    C'est le controle qui aurait attrape les « 20 166 » restes dans quatre documents.
    """
    block = _structure_overview()
    shapes = ObservationBuilder.squad_obs_shapes()
    total = sum(int(np.prod(s)) for s in shapes.values())

    assert total == ObservationBuilder.SQUAD_OBS_SIZE_TARGET, "incoherence interne du schema"

    variants = {str(total), f"{total:,}".replace(",", " ")}
    assert any(v in block for v in variants), (
        f"le total {total} n'apparait pas dans le Structure Overview (teste : {variants})"
    )

    # Chaque cle, sa forme ET son nombre de scalaires.
    for key, shape in shapes.items():
        assert key in block, f"cle {key} absente du Structure Overview"
        loose = r"\(\s*" + r"\s*,\s*".join(str(d) for d in shape) + r"\s*,?\s*\)"
        assert re.search(loose, block), (
            f"forme de {key} absente ou fausse : attendu ({', '.join(str(d) for d in shape)})"
        )
        count = int(np.prod(shape))
        count_variants = {str(count), f"{count:,}".replace(",", " ")}
        assert any(c in block for c in count_variants), (
            f"nombre de scalaires de {key} absent ou faux : attendu {count}"
        )


def test_documented_cardinalities_match_the_code():
    """Les K annonces (slots amis/ennemis/armes/types/figurines) sont ceux du code."""
    text = _doc()
    for name, value in (
        ("K_ALLY_SLOTS", ObservationBuilder.K_ALLY_SLOTS),
        ("K_ENEMY_SLOTS", ObservationBuilder.K_ENEMY_SLOTS),
        ("SQUAD_TOP_K", ObservationBuilder.SQUAD_TOP_K),
    ):
        assert re.search(rf"{name}\s*=\s*{value}\b", text), (
            f"{name} = {value} n'est pas annonce tel quel dans la doc"
        )
