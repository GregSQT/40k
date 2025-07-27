// Simple Node.js test to verify frontend shared rule imports work
// Run this from project root: node test_frontend_integration.js

const path = require('path');
const fs = require('fs');

console.log('🧪 Testing Frontend Shared Rules Integration');
console.log('='.repeat(50));

// Test 1: Check if shared rules file exists
const sharedRulesPath = path.join(__dirname, 'shared', 'gameRules.ts');
if (fs.existsSync(sharedRulesPath)) {
    console.log('✅ shared/gameRules.ts exists');
} else {
    console.log('❌ shared/gameRules.ts not found');
    process.exit(1);
}

// Test 2: Check if updated files have correct imports
const filesToCheck = [
    'frontend/src/utils/ShootingSequenceManager.ts',
    'frontend/src/utils/CombatSequenceManager.ts',
    'frontend/src/hooks/useGameActions.ts'
];

for (const filePath of filesToCheck) {
    const fullPath = path.join(__dirname, filePath);
    if (fs.existsSync(fullPath)) {
        const content = fs.readFileSync(fullPath, 'utf8');
        
        // Check for shared imports
        if (content.includes("from '../../../shared/gameRules'") || 
            content.includes("from '../../../shared/gameRules';")) {
            console.log(`✅ ${filePath} has correct shared import`);
        } else {
            console.log(`❌ ${filePath} missing shared import`);
        }
        
        // Check for removed duplicate functions (should not contain local implementations)
        const hasDuplicateRollD6 = content.includes('rollD6(): number') || 
                                  content.includes('private rollD6()');
        const hasDuplicateWoundCalc = content.includes('calculateWoundTarget(') && 
                                     content.includes('private calculateWoundTarget');
        const hasDuplicateSaveCalc = content.includes('calculateSaveTarget(') && 
                                    content.includes('private calculateSaveTarget');
        
        if (hasDuplicateRollD6 || hasDuplicateWoundCalc || hasDuplicateSaveCalc) {
            console.log(`❌ ${filePath} still contains duplicate functions`);
        } else {
            console.log(`✅ ${filePath} duplicate functions removed`);
        }
        
    } else {
        console.log(`❌ ${filePath} not found`);
    }
}

// Test 3: Check TypeScript configuration
const tsconfigPath = path.join(__dirname, 'frontend', 'tsconfig.json');
if (fs.existsSync(tsconfigPath)) {
    try {
        const tsconfig = JSON.parse(fs.readFileSync(tsconfigPath, 'utf8'));
        if (tsconfig.compilerOptions && tsconfig.compilerOptions.baseUrl === '../') {
            console.log('✅ TypeScript baseUrl configured correctly');
        } else {
            console.log('❌ TypeScript baseUrl not set to "../"');
        }
    } catch (e) {
        console.log(`❌ Error reading tsconfig.json: ${e.message}`);
    }
} else {
    console.log('❌ frontend/tsconfig.json not found');
}

console.log('\n📋 Integration Test Summary:');
console.log('- Run "cd frontend && npm run build" to test TypeScript compilation');
console.log('- Run "python test_shared_rules.py" to test Python functionality');
console.log('- Check console for any import errors when running the frontend');

console.log('\n✅ Frontend integration tests completed');