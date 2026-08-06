"""Scénarios « rule-checker » : un matchup par couple de types d'unités à règle implémentée.

À QUOI ILS SERVENT — `ai/train.py --rule-checker` remplace la liste de scénarios d'entraînement /
d'évaluation par celle-ci : chaque type d'unité dont au moins une règle est marquée
`RULES_STATUS == 2` (règle implémentée, lue dans les rosters TypeScript) affronte chacun des
autres, 2 unités par camp. C'est le seul consommateur.

POURQUOI ILS NE SONT PLUS VERSIONNÉS — le produit est le carré du nombre de types retenus : 18
types donnaient 324 fichiers en mars 2026, 52 en donnent 2704. Les versionner, c'était faire
pourrir dans le dépôt des milliers d'artefacts dérivés d'une donnée qui vit ailleurs (les
`RULES_STATUS` des rosters), et qui étaient déjà devenus illisibles par le moteur (`objectives_ref`
d'avant la migration V11). Ils sont donc RÉGÉNÉRÉS à la demande, dans un dossier ignoré par git. Le dépôt ne versionne que
ce module, qui les fabrique.

UN DOSSIER PAR JEU, ET AUCUNE SUPPRESSION. Le nom du dossier dérive de tout ce dont le contenu
dépend (sélection d'unités + échelle + board + terrain) : un jeu identique est reconnu et rendu
tel quel, un jeu différent vit à côté. C'est ce qui rend la régénération sûre pendant qu'un
training rule-checker tourne — le moteur rouvre le fichier de scénario à CHAQUE épisode, et une
purge le tuait en `FileNotFoundError`.

Ce module est la source UNIQUE : `scripts/roster_matchup_stats.py --rule-checker` (génération
explicite en ligne de commande) et `ai/train.py --rule-checker` (génération implicite au
lancement) l'appellent tous les deux. Deux fabricants du même artefact divergeraient.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

from shared.data_validation import require_key

#: Défauts de génération, partagés par les deux appelants — le parseur de la CLI les référence
#: plutôt que de les redéclarer, sans quoi une régénération par `train.py` produirait un autre
#: plateau que celle par le script.
DEFAULT_SCALE = "100pts"
DEFAULT_BOARD_REF = "44x60x5"
DEFAULT_TERRAIN_REF = "terrain-mc1.json"


def output_dir(project_root: Path) -> Path:
    """Dossier des artefacts. Ignoré par git (cf. `.gitignore`) : régénérable, jamais commité."""
    return Path(project_root) / "config" / "rule_checker"


def select_units(project_root: Path) -> Tuple[List[str], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Types d'unités dont au moins une entrée `RULES_STATUS` vaut 2.

    Rend (types retenus, détails retenus, lignes d'audit des rejetés).
    """
    units_root = Path(project_root) / "frontend" / "src" / "roster"
    if not units_root.exists():
        raise FileNotFoundError(f"Units directory not found: {units_root}")

    selected_units: List[str] = []
    selected_details: List[Dict[str, Any]] = []
    rejected_rows: List[Dict[str, Any]] = []
    class_pattern = re.compile(r"export\s+class\s+(\w+)")
    rules_status_pattern = re.compile(
        r"static\s+RULES_STATUS(?:\s*:\s*[^=]+)?\s*=\s*\{([\s\S]*?)\};",
        re.MULTILINE,
    )
    rules_status_entry_pattern = re.compile(r"([A-Za-z0-9_]+)\s*:\s*([0-9]+)")

    for ts_file in sorted(units_root.glob("**/units/*.ts")):
        content = ts_file.read_text(encoding="utf-8")
        class_match = class_pattern.search(content)
        unit_type = class_match.group(1) if class_match else ts_file.stem
        status_match = rules_status_pattern.search(content)
        rel_path = str(ts_file.relative_to(project_root)).replace("\\", "/")

        # Un seul point de construction de la ligne d'audit : trois `append` du même dict à la
        # variation du seul `reason` près laissaient trois endroits à corriger le jour où l'audit
        # gagne une colonne — c'est justement ce fichier qu'on lit pour comprendre POURQUOI une
        # fiche est écartée.
        entries = (
            rules_status_entry_pattern.findall(status_match.group(1))
            if status_match is not None
            else []
        )
        implemented_rule_keys = sorted(
            rule_key for rule_key, raw_value in entries if int(raw_value) == 2
        )
        if implemented_rule_keys:
            selected_units.append(unit_type)
            selected_details.append(
                {
                    "unit_type": unit_type,
                    "file": rel_path,
                    "implemented_rules": implemented_rule_keys,
                }
            )
            continue

        if status_match is None:
            reason = "RULES_STATUS missing"
        elif not entries:
            reason = "RULES_STATUS empty or unparsable"
        else:
            reason = "RULES_STATUS has no value == 2"
        rejected_rows.append({"unit_type": unit_type, "file": rel_path, "reason": reason})

    selected_sorted = sorted(set(selected_units))
    if not selected_sorted:
        raise ValueError(
            "No unit found with at least one RULES_STATUS entry == 2 in "
            "frontend/src/roster/**/units/*.ts"
        )
    return selected_sorted, selected_details, rejected_rows


def build_scenario_payload(
    p1_unit: str, p2_unit: str, scale: str, board_ref: str, terrain_ref: str
) -> Dict[str, Any]:
    """Un matchup 2v2. Même contrat V11 que les autres scénarios générés du dépôt.

    Murs, objectifs et zones de déploiement viennent TOUS du `terrain_ref` : les clés legacy
    (`objectives_ref`, `wall_ref`, `deployment_zone`) sont refusées par le moteur.
    """
    return {
        "deployment_type": "active",
        # Clause de detachement d'Oath of Moment : champ OBLIGATOIRE des qu'une armee ADEPTUS
        # ASTARTES est en jeu (`game_state.uses_codex_detachment` leve sinon), et ces scenarios
        # croisent tous les rosters, marines compris.
        "uses_codex_detachment": {"1": True, "2": True},
        "scale": scale,
        "primary_objectives": ["objectives_control"],
        "board_ref": board_ref,
        "terrain_ref": terrain_ref,
        "units": [
            {"id": 1, "unit_type": p1_unit, "player": 1},
            {"id": 2, "unit_type": p1_unit, "player": 1},
            {"id": 101, "unit_type": p2_unit, "player": 2},
            {"id": 102, "unit_type": p2_unit, "player": 2},
        ],
    }


@dataclass(frozen=True)
class GenerationParams:
    """Ce qui définit un JEU de scénarios, hors sélection d'unités.

    Figées ensemble parce qu'elles voyagent ensemble : générer à 500pts puis entraîner avec les
    défauts, c'est jouer sur un autre plateau que celui qu'on croit — et le scénario porte le
    plateau, pas le lanceur.
    """

    scale: str = DEFAULT_SCALE
    board_ref: str = DEFAULT_BOARD_REF
    terrain_ref: str = DEFAULT_TERRAIN_REF


def _params_path(project_root: Path) -> Path:
    return output_dir(project_root) / "params.json"


def resolve_params(project_root: Path) -> GenerationParams:
    """Les paramètres de la DERNIÈRE génération, ou les défauts si aucune.

    `ai/train.py --rule-checker` régénère sans rien demander à l'utilisateur : sans cette
    résolution il imposerait ses défauts et écraserait en silence un jeu produit à d'autres
    paramètres par `scripts/roster_matchup_stats.py --rule-checker`.
    """
    path = _params_path(project_root)
    if not path.is_file():
        return GenerationParams()
    stored = json.loads(path.read_text(encoding="utf-8"))
    return GenerationParams(
        scale=require_key(stored, "scale"),
        board_ref=require_key(stored, "board_ref"),
        terrain_ref=require_key(stored, "terrain_ref"),
    )


def _run_key(selected_units: List[str], params: GenerationParams) -> str:
    """Nom du dossier d'un jeu de scénarios : ce dont son contenu dépend ENTIÈREMENT.

    Deux jeux différents ne se marchent donc jamais dessus, et un jeu identique se reconnaît sans
    être réécrit. C'est ce qui remplace la purge : RIEN n'est supprimé, donc rien ne peut
    disparaître sous un training rule-checker en cours (le moteur rouvre le fichier de scénario à
    chaque épisode), ni laisser un dossier vide si la sélection échoue à mi-chemin.
    """
    digest = hashlib.sha256(
        json.dumps(
            {
                "units": selected_units,
                "scale": params.scale,
                "board_ref": params.board_ref,
                "terrain_ref": params.terrain_ref,
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()[:12]
    return f"{params.scale}_{params.board_ref}_{Path(params.terrain_ref).stem}_{digest}"


def generate(
    project_root: Path,
    agent_key: str,
    params: GenerationParams | None = None,
    generated_at: str | None = None,
) -> List[str]:
    """Écrit (si besoin) un jeu de scénarios + son manifeste, et rend les chemins.

    Rien n'est jamais supprimé : un jeu déjà complet est RENDU TEL QUEL. Les jeux devenus inutiles
    restent sur le disque, inertes et ignorés par git ; `rm -rf config/rule_checker` les balaie.
    """
    from ai.unit_registry import UnitRegistry

    root = Path(project_root)
    params = params or GenerationParams()

    # VALIDER D'ABORD, écrire ensuite : une sélection qui lève laissait auparavant un dossier vidé
    # et un manifeste survivant qui désignait des fichiers effacés.
    selected_units, selected_details, rejected_rows = select_units(root)
    unit_registry = UnitRegistry()
    missing_in_registry = [u for u in selected_units if u not in unit_registry.units]
    if missing_in_registry:
        raise KeyError(f"Selected unit_type not found in UnitRegistry: {missing_in_registry}")

    run_dir = output_dir(root) / "scenarios" / _run_key(selected_units, params)
    expected_count = len(selected_units) ** 2
    existing = sorted(run_dir.glob("scenario_rule_checker_bot-*.json"))
    if len(existing) == expected_count:
        return [str(p) for p in existing]

    run_dir.mkdir(parents=True, exist_ok=True)
    scenario_paths: List[str] = []
    for index, (p1_unit, p2_unit) in enumerate(
        ((p1, p2) for p1 in selected_units for p2 in selected_units), start=1
    ):
        scenario_path = run_dir / f"scenario_rule_checker_bot-{index:04d}.json"
        scenario_path.write_text(
            json.dumps(
                build_scenario_payload(
                    p1_unit, p2_unit, params.scale, params.board_ref, params.terrain_ref
                ),
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        scenario_paths.append(str(scenario_path))

    manifest = {
        "mode": "rule_checker",
        "agent": agent_key,
        "scale": params.scale,
        "board_ref": params.board_ref,
        "terrain_ref": params.terrain_ref,
        "generated_at": generated_at
        or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rule_filter": {"mode": "any_rule_status_equals", "required_value": 2},
        "selected_unit_types": selected_units,
        "selected_details": selected_details,
        "scenario_count": len(scenario_paths),
        "scenario_paths": scenario_paths,
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (run_dir / "audit_rejected.json").write_text(
        json.dumps(rejected_rows, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    # Écrit EN DERNIER : ces paramètres sont ceux d'une génération réussie, et c'est eux que
    # `ai/train.py --rule-checker` reprendra au lieu de réimposer les défauts.
    _params_path(root).parent.mkdir(parents=True, exist_ok=True)
    _params_path(root).write_text(
        json.dumps(
            {
                "scale": params.scale,
                "board_ref": params.board_ref,
                "terrain_ref": params.terrain_ref,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return scenario_paths
