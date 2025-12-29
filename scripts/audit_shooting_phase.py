#!/usr/bin/env python3
"""
Script d'audit pour comparer shooting_handlers.py avec shoot_refactor.md

Ce script identifie les écarts fonctionnels entre l'implémentation actuelle
et la spécification optimisée dans shoot_refactor.md
"""

import re
import ast
from pathlib import Path
from typing import Dict, List, Tuple, Set, Optional
from dataclasses import dataclass

@dataclass
class FunctionSpec:
    """Représente une fonction dans la spécification"""
    name: str
    params: List[str]
    purpose: str
    returns: str
    logic_steps: List[str]
    section: str

@dataclass
class CodeFunction:
    """Représente une fonction dans le code"""
    name: str
    params: List[str]
    file: str
    line: int
    docstring: str

@dataclass
class AuditResult:
    """Résultat d'un audit"""
    spec_function: FunctionSpec
    code_function: Optional[CodeFunction]
    status: str  # "MATCH", "PARTIAL", "MISSING", "DIFFERENT"
    issues: List[str]
    recommendations: List[str]


class ShootingPhaseAuditor:
    def __init__(self, code_path: str, spec_path: str):
        self.code_path = Path(code_path)
        self.spec_path = Path(spec_path)
        self.spec_functions: List[FunctionSpec] = []
        self.code_functions: List[CodeFunction] = []
        self.audit_results: List[AuditResult] = []
        
    def extract_spec_functions(self) -> List[FunctionSpec]:
        """Extrait les fonctions de la spécification"""
        spec_content = self.spec_path.read_text()
        functions = []
        
        # Pattern pour trouver les fonctions dans la spec
        # Format: #### Function: function_name(...)
        function_pattern = r'#### Function: ([^(]+)\(([^)]*)\)'
        
        current_section = ""
        for line in spec_content.split('\n'):
            # Détecter les sections
            if line.startswith('### '):
                current_section = line.replace('### ', '').strip()
            
            # Détecter les fonctions
            match = re.search(function_pattern, line)
            if match:
                func_name = match.group(1).strip()
                params_str = match.group(2).strip()
                params = [p.strip() for p in params_str.split(',') if p.strip()]
                
                # Extraire le purpose et returns des lignes suivantes
                purpose = ""
                returns = ""
                logic_steps = []
                
                lines = spec_content.split('\n')
                idx = spec_content.split('\n').index(line)
                
                for i in range(idx + 1, min(idx + 20, len(lines))):
                    if '**Purpose**:' in lines[i]:
                        purpose = lines[i].split('**Purpose**:')[1].strip()
                    elif '**Returns**:' in lines[i]:
                        returns = lines[i].split('**Returns**:')[1].strip()
                    elif lines[i].strip().startswith('ascript'):
                        # Extraire la logique jusqu'à la fermeture du bloc
                        for j in range(i + 1, len(lines)):
                            if lines[j].strip() == '```':
                                break
                            logic_steps.append(lines[j])
                        break
                
                functions.append(FunctionSpec(
                    name=func_name,
                    params=params,
                    purpose=purpose,
                    returns=returns,
                    logic_steps=logic_steps,
                    section=current_section
                ))
        
        return functions
    
    def extract_code_functions(self) -> List[CodeFunction]:
        """Extrait les fonctions du code Python"""
        code_content = self.code_path.read_text()
        functions = []
        
        try:
            tree = ast.parse(code_content)
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    params = [arg.arg for arg in node.args.args]
                    docstring = ast.get_docstring(node) or ""
                    
                    # Trouver la ligne
                    line = node.lineno
                    
                    functions.append(CodeFunction(
                        name=node.name,
                        params=params,
                        file=str(self.code_path),
                        line=line,
                        docstring=docstring
                    ))
        except SyntaxError as e:
            print(f"Erreur de syntaxe dans {self.code_path}: {e}")
        
        return functions
    
    def find_code_equivalent(self, spec_func: FunctionSpec) -> Optional[CodeFunction]:
        """Trouve l'équivalent d'une fonction spec dans le code"""
        # Mapping des noms de fonctions spec -> code
        name_mapping = {
            "weapon_availability_check": ["_get_available_weapons_for_selection", 
                                         "_get_available_weapons_after_advance"],
            "valid_target_pool_build": ["shooting_build_valid_target_pool"],
            "shoot_action": ["shooting_attack_controller", "_attack_sequence_rng"],
            "player_advance": ["_handle_advance_action"],
            "weapon_selection": ["shooting_click_handler"],  # Partiellement
            "POSTPONE_ACTIVATION": ["shooting_click_handler"],  # Logique intégrée
        }
        
        # Chercher par nom exact d'abord
        for code_func in self.code_functions:
            if code_func.name == spec_func.name:
                return code_func
        
        # Chercher par mapping
        if spec_func.name in name_mapping:
            for mapped_name in name_mapping[spec_func.name]:
                for code_func in self.code_functions:
                    if code_func.name == mapped_name:
                        return code_func
        
        # Chercher par mots-clés dans le docstring
        keywords = spec_func.name.lower().replace('_', ' ')
        for code_func in self.code_functions:
            if keywords in code_func.docstring.lower() or keywords in code_func.name.lower():
                return code_func
        
        return None
    
    def compare_function_params(self, spec_func: FunctionSpec, code_func: CodeFunction) -> List[str]:
        """Compare les paramètres et retourne les différences"""
        issues = []
        
        # La spec utilise arg1, arg2, arg3 mais le code peut avoir des noms différents
        # On vérifie plutôt la logique que les noms exacts
        spec_param_count = len(spec_func.params)
        code_param_count = len(code_func.params)
        
        # Exclure 'self' des paramètres Python
        if code_func.params and code_func.params[0] == 'self':
            code_param_count -= 1
        
        # weapon_availability_check devrait avoir 3 args (arg1, arg2, arg3)
        if spec_func.name == "weapon_availability_check":
            if code_param_count < 3:
                issues.append(f"Nombre de paramètres insuffisant: {code_param_count} au lieu de 3")
        
        return issues
    
    def check_spec_logic_in_code(self, spec_func: FunctionSpec, code_func: CodeFunction) -> List[str]:
        """Vérifie si la logique de la spec est présente dans le code"""
        issues = []
        code_content = self.code_path.read_text()
        
        # Extraire le contenu de la fonction
        lines = code_content.split('\n')
        func_start = code_func.line - 1
        func_end = func_start + 1
        
        # Trouver la fin de la fonction (approximatif)
        indent_level = len(lines[func_start]) - len(lines[func_start].lstrip())
        for i in range(func_start + 1, min(func_start + 500, len(lines))):
            if lines[i].strip() and not lines[i].startswith(' ' * (indent_level + 1)):
                if lines[i].strip().startswith('def ') or lines[i].strip().startswith('class '):
                    func_end = i
                    break
        
        func_code = '\n'.join(lines[func_start:func_end])
        
        # Vérifier les points clés de la logique selon la spec
        if spec_func.name == "weapon_availability_check":
            checks = [
                ("ASSAULT", "Vérification de la règle ASSAULT après advance"),
                ("PISTOL", "Vérification de la règle PISTOL quand adjacent"),
                ("weapon.shot", "Vérification du flag weapon.shot"),
                ("RNG", "Vérification de la portée weapon.RNG"),
            ]
            for keyword, description in checks:
                if keyword not in func_code:
                    issues.append(f"Logique manquante: {description}")
        
        elif spec_func.name == "valid_target_pool_build":
            checks = [
                ("HP_CUR", "Vérification HP_CUR > 0"),
                ("player", "Vérification player != current_player"),
                ("adjacent", "Vérification adjacent to friendly"),
                ("line of sight", "Vérification Line of Sight"),
            ]
            for keyword, description in checks:
                if keyword.lower() not in func_code.lower() and "los" not in func_code.lower():
                    issues.append(f"Logique manquante: {description}")
        
        elif spec_func.name == "shoot_action":
            checks = [
                ("SHOOT_LEFT", "Décrémentation de SHOOT_LEFT"),
                ("weapon.shot", "Marquage weapon.shot = 1"),
                ("valid_target_pool", "Mise à jour valid_target_pool"),
            ]
            for keyword, description in checks:
                if keyword.lower() not in func_code.lower():
                    issues.append(f"Logique manquante: {description}")
        
        return issues
    
    def audit(self) -> List[AuditResult]:
        """Effectue l'audit complet"""
        print("🔍 Extraction des fonctions de la spécification...")
        self.spec_functions = self.extract_spec_functions()
        print(f"   ✓ {len(self.spec_functions)} fonctions trouvées dans la spec")
        
        print("🔍 Extraction des fonctions du code...")
        self.code_functions = self.extract_code_functions()
        print(f"   ✓ {len(self.code_functions)} fonctions trouvées dans le code")
        
        print("\n🔍 Comparaison des fonctions...")
        results = []
        
        for spec_func in self.spec_functions:
            code_func = self.find_code_equivalent(spec_func)
            
            if code_func is None:
                results.append(AuditResult(
                    spec_function=spec_func,
                    code_function=None,
                    status="MISSING",
                    issues=[f"Fonction '{spec_func.name}' non trouvée dans le code"],
                    recommendations=[
                        f"Implémenter {spec_func.name} selon la spec",
                        f"Vérifier si la logique est intégrée dans une autre fonction"
                    ]
                ))
            else:
                # Comparer les paramètres
                param_issues = self.compare_function_params(spec_func, code_func)
                
                # Vérifier la logique
                logic_issues = self.check_spec_logic_in_code(spec_func, code_func)
                
                all_issues = param_issues + logic_issues
                
                if not all_issues:
                    status = "MATCH"
                    recommendations = []
                elif len(all_issues) <= 2:
                    status = "PARTIAL"
                    recommendations = [
                        "Vérifier que tous les points de la spec sont couverts",
                        "Ajouter des commentaires référençant shoot_refactor.md"
                    ]
                else:
                    status = "DIFFERENT"
                    recommendations = [
                        "Réviser l'implémentation pour correspondre à la spec",
                        "Consulter shoot_refactor.md pour les détails"
                    ]
                
                results.append(AuditResult(
                    spec_function=spec_func,
                    code_function=code_func,
                    status=status,
                    issues=all_issues,
                    recommendations=recommendations
                ))
        
        self.audit_results = results
        return results
    
    def generate_report(self, output_path: Optional[str] = None) -> str:
        """Génère un rapport d'audit"""
        report = []
        report.append("# 🔍 AUDIT DE CONFORMITÉ: shooting_handlers.py vs shoot_refactor.md\n")
        report.append(f"**Date**: {Path(__file__).stat().st_mtime}")
        report.append(f"**Code analysé**: {self.code_path}")
        report.append(f"**Spec analysée**: {self.spec_path}\n")
        
        # Statistiques
        total = len(self.audit_results)
        match = sum(1 for r in self.audit_results if r.status == "MATCH")
        partial = sum(1 for r in self.audit_results if r.status == "PARTIAL")
        different = sum(1 for r in self.audit_results if r.status == "DIFFERENT")
        missing = sum(1 for r in self.audit_results if r.status == "MISSING")
        
        report.append("## 📊 Statistiques\n")
        report.append(f"- **Total fonctions spec**: {total}")
        report.append(f"- ✅ **MATCH**: {match} ({match*100//total if total > 0 else 0}%)")
        report.append(f"- ⚠️ **PARTIAL**: {partial} ({partial*100//total if total > 0 else 0}%)")
        report.append(f"- ❌ **DIFFERENT**: {different} ({different*100//total if total > 0 else 0}%)")
        report.append(f"- 🚫 **MISSING**: {missing} ({missing*100//total if total > 0 else 0}%)\n")
        
        # Détails par fonction
        report.append("## 📋 Détails par fonction\n")
        
        for result in self.audit_results:
            status_emoji = {
                "MATCH": "✅",
                "PARTIAL": "⚠️",
                "DIFFERENT": "❌",
                "MISSING": "🚫"
            }[result.status]
            
            report.append(f"### {status_emoji} {result.spec_function.name}")
            report.append(f"**Section**: {result.spec_function.section}")
            report.append(f"**Status**: {result.status}")
            report.append(f"**Purpose**: {result.spec_function.purpose}")
            
            if result.code_function:
                report.append(f"**Code équivalent**: `{result.code_function.name}` (ligne {result.code_function.line})")
            else:
                report.append("**Code équivalent**: ❌ Non trouvé")
            
            if result.issues:
                report.append("\n**Issues détectées**:")
                for issue in result.issues:
                    report.append(f"- ⚠️ {issue}")
            
            if result.recommendations:
                report.append("\n**Recommandations**:")
                for rec in result.recommendations:
                    report.append(f"- 💡 {rec}")
            
            report.append("")
        
        # Points critiques
        report.append("## 🚨 Points critiques\n")
        critical = [r for r in self.audit_results if r.status in ["MISSING", "DIFFERENT"]]
        if critical:
            for result in critical:
                report.append(f"- **{result.spec_function.name}**: {result.status}")
                if result.issues:
                    report.append(f"  - {result.issues[0]}")
        else:
            report.append("✅ Aucun point critique détecté")
        
        report.append("\n## 📝 Notes\n")
        report.append("- Ce rapport compare la structure et la logique, pas l'exactitude fonctionnelle")
        report.append("- Les fonctions peuvent être implémentées différemment mais correctement")
        report.append("- Vérifier manuellement les cas limites et les edge cases")
        
        report_text = "\n".join(report)
        
        if output_path:
            Path(output_path).write_text(report_text)
            print(f"\n📄 Rapport sauvegardé dans: {output_path}")
        
        return report_text


def main():
    """Point d'entrée principal"""
    code_path = "engine/phase_handlers/shooting_handlers.py"
    spec_path = "Documentation/shoot_refactor.md"
    
    print("=" * 70)
    print("🔍 AUDIT DE CONFORMITÉ: shooting_handlers.py vs shoot_refactor.md")
    print("=" * 70)
    print()
    
    auditor = ShootingPhaseAuditor(code_path, spec_path)
    results = auditor.audit()
    
    print(f"\n✅ Audit terminé: {len(results)} fonctions analysées")
    
    # Générer le rapport
    report = auditor.generate_report("Documentation/SHOOTING_AUDIT_REPORT.md")
    
    print("\n" + "=" * 70)
    print("📊 RÉSUMÉ")
    print("=" * 70)
    
    match = sum(1 for r in results if r.status == "MATCH")
    partial = sum(1 for r in results if r.status == "PARTIAL")
    different = sum(1 for r in results if r.status == "DIFFERENT")
    missing = sum(1 for r in results if r.status == "MISSING")
    
    print(f"✅ MATCH: {match}")
    print(f"⚠️  PARTIAL: {partial}")
    print(f"❌ DIFFERENT: {different}")
    print(f"🚫 MISSING: {missing}")
    
    if missing > 0 or different > 0:
        print("\n⚠️  Des écarts ont été détectés. Consultez le rapport pour les détails.")
    else:
        print("\n✅ Aucun écart critique détecté.")


if __name__ == "__main__":
    main()
