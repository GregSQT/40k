#!/usr/bin/env bash
#
# Analyse statique de sécurité — Documentation/Implémentation/Security.md, étape 6 (F5).
#
# Enchaîne bandit (code Python), pip-audit (dépendances Python) et npm audit
# (dépendances front). Sort en code NON NUL dès qu'un finding critique/haut subsiste.
#
# CE QUI FAIT ÉCHOUER :
#   bandit    : sévérité HIGH, toutes confiances confondues — ou un fichier que bandit
#               n'a pas su analyser (un scan partiel ne doit pas se lire comme un scan
#               propre), ou un échec de l'outil lui-même.
#   pip-audit : toute vulnérabilité de la surface de PRODUCTION, hors exceptions
#               justifiées une par une dans scripts/security_audit_ignore.txt.
#   npm audit : --audit-level=high (donc high + critical).
#
# CE QUI EST AFFICHÉ MAIS NE BLOQUE PAS :
#   - bandit LOW/MEDIUM. La sortie du script fait foi sur le détail — ce bloc n'est pas un
#     inventaire, il justifie les familles qui reviennent. Aujourd'hui côté MEDIUM :
#     B301 (pickle, ci-dessous), B108 (`/tmp` en dur dans les bancs `scripts/ab_bench*`),
#     B310 (`urlopen` vers 127.0.0.1 dans `scripts/pvp_smoke_test.py`), B302 (`marshal` dans
#     un script de profilage) — tous hors chemin serveur.
#     DEUX cas pickle distincts, à ne pas confondre :
#     * services/game_saves.py — `import pickle` (B403, LOW) et RIEN d'autre : bandit ne
#       voit pas de `pickle.load` parce que le dépickle passe par une sous-classe
#       `pickle.Unpickler` (`_safe_loads`, liste blanche de classes, Security.md étape 2
#       / F7). Le format pickle est CONSERVÉ, c'est `_safe_loads` qui ferme le vecteur.
#       B403 tire sur 5 fichiers au total ; les 4 autres sont ceux de la ligne suivante.
#     * les 4 `pickle.load` réels (B301, MEDIUM) sont AILLEURS et ne passent PAS par
#       `_safe_loads` : ai/bot_evaluation.py, ai/vec_normalize_utils.py,
#       engine/action_decoder.py, engine/pve_controller.py. Ils lisent des artefacts
#       d'ENTRAÎNEMENT écrits localement (stats VecNormalize, cache de décodeur), jamais
#       une donnée reçue du réseau. C'est ce qui les maintient sous le seuil bloquant.
#     Dans les deux cas : aucun `# nosec` n'est posé, les findings réapparaissent à
#     chaque exécution, ils sont seulement sous le seuil.
#   - pip-audit sur le venv de DÉVELOPPEMENT. Ce venv contient l'outillage local
#     (jupyter, aider, pytest…) qui ne part pas dans l'image Docker ; le gate porte
#     sur requirements.runtime.txt. Ce fichier n'est représentatif de l'image QUE
#     parce que toutes ses lignes sont épinglées : une contrainte lâche (>=) ferait
#     auditer une résolution du jour, pas ce que le build a installé.
#
# Prérequis : venv actif + pip install -r requirements-dev.txt
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IGNORE_FILE="$REPO_ROOT/scripts/security_audit_ignore.txt"
RUNTIME_REQS="$REPO_ROOT/requirements.runtime.txt"
cd "$REPO_ROOT"

for required_tool in bandit pip-audit npm python3; do
  command -v "$required_tool" >/dev/null 2>&1 || {
    echo "ERROR: '$required_tool' introuvable. Active le venv puis: pip install -r requirements-dev.txt" >&2
    exit 1
  }
done
[[ -f "$IGNORE_FILE" ]] || { echo "ERROR: fichier d'exceptions manquant: $IGNORE_FILE" >&2; exit 1; }
[[ -f "$RUNTIME_REQS" ]] || { echo "ERROR: fichier de dépendances manquant: $RUNTIME_REQS" >&2; exit 1; }

WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

FAILURES=()

# ---------------------------------------------------------------------------------
# Périmètre = TOUT le Python du dépôt, moins une liste noire courte. C'est volontairement une
# liste NOIRE et pas une liste blanche : une liste blanche laisse hors scan tout fichier ou
# paquet créé plus tard (`config/__init__.py` l'était), donc un `shell=True` ajouté là passerait
# la porte en vert. Avec une liste noire, le neuf est couvert par défaut.
# Chaque exclusion porte sa raison, et elles sont annoncées à chaque exécution.
BANDIT_EXCLUDES=(
  ./tests            # exclu de l'image par .dockerignore, jamais exécuté par le conteneur
  ./node_modules ./frontend/node_modules ./frontend/dist   # dépendances et build front (npm audit)
  ./.venv ./.claude ./Documentation                        # hors image, hors code exécutable
)
# `--exclude` REMPLACE la liste par défaut de bandit, il ne s'y ajoute pas. Sans ce rappel
# explicite, un venv nommé `venv/` (layout que .dockerignore anticipe), un `.tox/` ou un
# `.pytest_cache/` retomberaient DANS le scan : mesuré, `bandit -r .venv/.../site-packages/pip`
# rend 11 findings HIGH, et la porte échouerait sur du code tiers que personne n'a écrit ici.
BANDIT_DEFAULT_EXCLUDES=(.svn CVS .bzr .hg .git __pycache__ .tox .eggs '*.egg')
# Variantes hors liste par défaut de bandit mais courantes dans ce dépôt et chez les
# contributeurs : venv alternatif, caches d'outillage.
BANDIT_EXTRA_EXCLUDES=(./venv ./.pytest_cache ./.mypy_cache ./.ruff_cache)
BANDIT_EXCLUDE_ALL=(
  "${BANDIT_DEFAULT_EXCLUDES[@]}" "${BANDIT_EXTRA_EXCLUDES[@]}" "${BANDIT_EXCLUDES[@]}"
)
BANDIT_EXCLUDE_ARG="$(IFS=,; echo "${BANDIT_EXCLUDE_ALL[*]}")"

echo "==> bandit — code Python (dépôt entier)"
echo "    hors périmètre : ${BANDIT_EXCLUDES[*]}"
echo "    + exclusions par défaut de bandit et caches d'outillage, réinjectés explicitement"
BANDIT_JSON="$WORK_DIR/bandit.json"
# Codes de sortie bandit : 0 = rien, 1 = findings, >1 = échec de l'outil. Ne jamais avaler
# le >1 : un scan planté rend un rapport à 0 finding, qui se lirait comme un feu vert.
BANDIT_SCAN_RC=0
bandit -q -r . --exclude "$BANDIT_EXCLUDE_ARG" -f json -o "$BANDIT_JSON" >/dev/null 2>&1 || BANDIT_SCAN_RC=$?
[[ $BANDIT_SCAN_RC -le 1 ]] || { echo "ERROR: bandit a échoué (code $BANDIT_SCAN_RC)" >&2; exit 1; }
[[ -s "$BANDIT_JSON" ]] || { echo "ERROR: bandit n'a produit aucun rapport" >&2; exit 1; }

BANDIT_RC=0
python3 - "$BANDIT_JSON" <<'PY' || BANDIT_RC=$?
import collections
import json
import sys

with open(sys.argv[1], encoding="utf-8") as report_file:
    report = json.load(report_file)
results = report["results"]

# Un fichier que bandit n'a pas su analyser n'apparaît PAS dans `results` : sans ce contrôle,
# un scan aveugle sur la moitié du code s'afficherait comme un scan propre.
scan_errors = report.get("errors") or []
for scan_error in scan_errors:
    print(f"    [ERREUR] bandit n'a pas pu analyser {scan_error.get('filename')} : "
          f"{scan_error.get('reason')}")

counts = collections.Counter(finding["issue_severity"] for finding in results)
print(f"    {len(results)} finding(s) : "
      f"HIGH={counts['HIGH']} MEDIUM={counts['MEDIUM']} LOW={counts['LOW']}")

for severity in ("MEDIUM", "LOW"):
    by_test = collections.Counter(
        (finding["test_id"], finding["test_name"])
        for finding in results if finding["issue_severity"] == severity
    )
    for (test_id, test_name), count in sorted(by_test.items()):
        print(f"    [{severity:6}] {test_id} {test_name} x{count} (non bloquant)")

blocking = [finding for finding in results if finding["issue_severity"] == "HIGH"]
for finding in blocking:
    print(f"    [HIGH  ] {finding['test_id']} "
          f"{finding['filename']}:{finding['line_number']} — {finding['issue_text']}")
sys.exit(1 if (blocking or scan_errors) else 0)
PY
[[ $BANDIT_RC -eq 0 ]] || FAILURES+=("bandit: finding(s) de sévérité HIGH, ou fichier non analysé")

# ---------------------------------------------------------------------------------
echo "==> pip-audit — surface de production ($(basename "$RUNTIME_REQS"))"
IGNORE_ARGS=()
# `|| [[ -n "$ignore_line" ]]` : sans ça, une dernière ligne dépourvue de saut de ligne final
# est lue mais jamais traitée — l'exception documentée ne serait pas passée à pip-audit, qui
# échouerait alors sur une vulnérabilité pourtant justifiée.
while IFS= read -r ignore_line || [[ -n "$ignore_line" ]]; do
  # Retirer espaces ET tabulations aux deux bouts avant de décider : sans ça, un commentaire
  # indenté ou une ligne de tabulations est lu comme une exception sans justification et
  # tue le script avant pip-audit et npm audit.
  ignore_line="${ignore_line#"${ignore_line%%[![:space:]]*}"}"
  ignore_line="${ignore_line%"${ignore_line##*[![:space:]]}"}"
  [[ -z "$ignore_line" || "$ignore_line" == \#* ]] && continue
  [[ "$ignore_line" =~ ^([A-Za-z0-9-]+)[[:space:]]+#[[:space:]]*(.+)$ ]] || {
    echo "ERROR: ligne sans justification dans $IGNORE_FILE : $ignore_line" >&2
    exit 1
  }
  IGNORE_ARGS+=(--ignore-vuln "${BASH_REMATCH[1]}")
  echo "    accepté : ${BASH_REMATCH[1]} — ${BASH_REMATCH[2]}"
done < "$IGNORE_FILE"

PIP_AUDIT_RC=0
# --strict : sans lui, une dépendance dont la collecte échoue est simplement « skippée »
# (message de spinner, invisible hors terminal) et l'audit sort 0 sur une surface partielle.
# Même trou que celui fermé côté bandit avec `errors`.
pip-audit --strict -r "$RUNTIME_REQS" "${IGNORE_ARGS[@]}" || PIP_AUDIT_RC=$?
[[ $PIP_AUDIT_RC -eq 0 ]] || FAILURES+=("pip-audit: vulnérabilité non justifiée dans la surface de production")

# ---------------------------------------------------------------------------------
echo "==> pip-audit — venv de développement (informatif, non bloquant)"
DEV_JSON="$WORK_DIR/pip-audit-dev.json"
pip-audit -f json -o "$DEV_JSON" >/dev/null 2>&1 || true
if [[ -s "$DEV_JSON" ]]; then
  # Bloc informatif : un rapport tronqué (pip-audit interrompu) ne doit ni faire échouer
  # l'analyse, ni tuer le script avant npm audit — mais il se voit.
  DEV_RC=0
  python3 - "$DEV_JSON" <<'PY' || DEV_RC=$?
import json
import sys

with open(sys.argv[1], encoding="utf-8") as report_file:
    dependencies = json.load(report_file)["dependencies"]

vulnerable = [dep for dep in dependencies if dep.get("vulns")]
total = sum(len(dep["vulns"]) for dep in vulnerable)
print(f"    {total} vulnérabilité(s) dans {len(vulnerable)} paquet(s) du venv local")
for dep in sorted(vulnerable, key=lambda d: d["name"]):
    print(f"    - {dep['name']} {dep['version']} : {len(dep['vulns'])}")
PY
  [[ $DEV_RC -eq 0 ]] || echo "    (rapport pip-audit du venv local illisible — bloc informatif ignoré)"
else
  echo "    (pip-audit n'a produit aucun rapport sur le venv local)"
fi

# ---------------------------------------------------------------------------------
echo "==> npm audit — frontend (seuil: high)"
[[ -d frontend ]] || { echo "ERROR: répertoire frontend/ introuvable" >&2; exit 1; }
# npm sort en non-zéro aussi bien pour « j'ai trouvé des vulnérabilités » que pour « je n'ai
# pas pu auditer » (registre injoignable, lockfile absent). Confondre les deux, c'est afficher
# un problème de dépendances là où il y a une panne d'outil — et l'inverse. On lit donc le
# rapport JSON, comme pour bandit : un rapport valide décide, une absence de rapport arrête.
# UN SEUL appel : afficher un second audit à côté de celui qui décide, c'est montrer à
# l'opérateur un tableau qui peut diverger de la porte. Le détail lisible est rendu à partir
# du même JSON que celui qui tranche.
NPM_JSON="$WORK_DIR/npm-audit.json"
(cd frontend && npm audit --audit-level=high --json) > "$NPM_JSON" 2>/dev/null || true

NPM_RC=0
python3 - "$NPM_JSON" <<'PY' || NPM_RC=$?
import json
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as report_file:
        report = json.load(report_file)
except (OSError, json.JSONDecodeError) as parse_error:
    print(f"    [ERREUR] npm audit n'a pas rendu de rapport exploitable : {parse_error}")
    sys.exit(2)

if "error" in report:
    print(f"    [ERREUR] npm audit a échoué : {report['error'].get('summary', report['error'])}")
    sys.exit(2)

counts = report.get("metadata", {}).get("vulnerabilities")
if counts is None:
    print("    [ERREUR] rapport npm audit sans metadata.vulnerabilities")
    sys.exit(2)

blocking = counts.get("high", 0) + counts.get("critical", 0)
print(f"    critical={counts.get('critical', 0)} high={counts.get('high', 0)} "
      f"moderate={counts.get('moderate', 0)} low={counts.get('low', 0)}")

for name, entry in sorted(report.get("vulnerabilities", {}).items()):
    severity = entry.get("severity", "?")
    marker = "BLOQUANT" if severity in ("high", "critical") else "non bloquant"
    origin = "direct" if entry.get("isDirect") else "transitif"
    affected = entry.get("range") or "?"

    fix = entry.get("fixAvailable")
    if fix is True:
        fix_text = "correctif: npm audit fix"
    elif isinstance(fix, dict):
        major = " (montée MAJEURE)" if fix.get("isSemVerMajor") else ""
        fix_text = f"correctif: {fix.get('name')}@{fix.get('version')}{major}"
    else:
        fix_text = "AUCUN correctif publié"

    # `via` porte soit les avis (dicts), soit les paquets intermédiaires (chaînes) : les deux
    # disent d'où vient la vulnérabilité, c'est ce que le tableau humain de npm montrait.
    causes = []
    for cause in entry.get("via", []):
        causes.append(cause.get("title", "?") if isinstance(cause, dict) else str(cause))

    print(f"    [{severity:8}] {name} {affected} ({origin}) — {marker} — {fix_text}")
    for cause in causes:
        print(f"                 via {cause}")

sys.exit(1 if blocking else 0)
PY
case $NPM_RC in
  0) ;;
  1) FAILURES+=("npm audit: vulnérabilité high/critical dans frontend/") ;;
  *) echo "ERROR: npm audit n'a pas pu auditer frontend/ — audit incomplet" >&2; exit 1 ;;
esac

# ---------------------------------------------------------------------------------
if [[ ${#FAILURES[@]} -gt 0 ]]; then
  echo "==> ÉCHEC — findings critiques/hauts subsistants :"
  for failure in "${FAILURES[@]}"; do
    echo "    - $failure"
  done
  exit 1
fi

echo "==> Aucun finding critique/haut. Analyse statique OK."
