#!/usr/bin/env bash
# Génère des versions HTML lisibles des fiches .md du mémoire.
# Usage : depuis la racine du projet : ./Documentation/Memoire/export_memoire_fiches.sh
# Les .html sont créés dans Documentation/Memoire/ et s'ouvrent dans le navigateur.

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
CSS="memoire_fiches.css"

for f in Presentation_contexte_formation.md Maquettes_enchainement_ecrans.md Schema_BDD_MEA_et_physique.md \
         Jeu_essai_complet.md Annexe_tableau_routes_API.md Annexe_extraits_code.md \
         Captures_et_code.md REAC_eco_conception_et_tests.md Emplacements_modifications_memoire.pdf.md \
         COMMENT_EXPLOITER_LES_MD.md README_fiches_memoire.md; do
  if [ -f "$f" ]; then
    out="${f%.md}.html"
    pandoc -s -o "$out" "$f" --css="$CSS" -M title:"${f%.md}"
    echo "Generated: $out"
  fi
done

# Un seul ODT avec tout (optionnel) : décommenter les 3 lignes ci-dessous
# LIST="Presentation_contexte_formation.md Schema_BDD_MEA_et_physique.md Jeu_essai_complet.md Annexe_tableau_routes_API.md Annexe_extraits_code.md"
# pandoc $LIST -o Memoire_fiches_tout.odt
# echo "Generated: Memoire_fiches_tout.odt"

echo "Done. Open the .html files in your browser."
