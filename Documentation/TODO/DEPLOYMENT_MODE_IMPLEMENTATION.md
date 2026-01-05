# Implémentation : Mode Déploiement et Menu de Configuration (Hybride V2+V3)

## Vue d'ensemble

Ce document décrit l'implémentation complète du système de configuration pré-partie et du mode de déploiement interactif pour le jeu Warhammer 40K Tactics. Ce document combine les meilleurs éléments de V2 (types complets, structure claire) et V3 (code Python complet, structure React).

## 1. Structure des Fichiers de Configuration

### 1.1. Configuration des Boards (`config/board/`)

**Format :** `{boardName}.json`

```json
{
  "name": "Urban Combat",
  "description": "Zone urbaine avec ruines et objectifs stratégiques",
  "cols": 25,
  "rows": 21,
  "hex_radius": 25,
  "wall_hexes": [[2,5], [2,6], [3,5], [3,6]],
  "objectives": [
    {"id": "obj1", "hex": [12, 10], "type": "control"},
    {"id": "obj2", "hex": [5, 5], "type": "control"}
  ],
  "deployment_zones": {
    "attacker": [[0,0], [0,1], [1,0], [1,1], [2,0]],
    "defender": [[23,20], [24,20], [24,19], [23,19], [22,20]]
  },
  "colors": {}
}
```

### 1.2. Configuration des Teams (`config/teams/`)

**Format :** `{faction}_{unitType}{count}.json`

**Exemple :** `spaceMarine_intercessor2.json`

```json
{
  "faction": "Space Marine",
  "name": "Intercessor Squad x2",
  "units": [
    {
      "unitType": "Intercessor",
      "count": 1,
      "player": 0
    },
    {
      "unitType": "Intercessor",
      "count": 1,
      "player": 0
    }
  ],
  "totalPoints": 200,
  "description": "Deux escouades d'Intercessors Space Marines"
}
```

### 1.3. Configuration des Primaires (`config/primary/`)

**Format :** `{primaryName}.json`

```json
{
  "name": "Take and Hold",
  "description": "Contrôler les objectifs à la fin de chaque round",
  "rules": {
    "scoring": "endOfRound",
    "pointsPerObjective": 5,
    "maxPoints": 15
  }
}
```

### 1.4. Templates Prédéfinis (`config/templates/`)

**Format :** `{templateName}.json`

```json
{
  "name": "Quick Start",
  "description": "Configuration rapide pour débuter",
  "gameMode": "pvp",
  "board": "urban_combat",
  "team1": "spaceMarine_intercessor2",
  "team2": "chaos_marine_squad",
  "primary": "take_and_hold"
}
```

### 1.5. Configurations Sauvegardées (`config/saved_setups/`)

**Format :** `{userId}_{setupName}.json` (ou `local_{setupName}.json` pour local)

```json
{
  "name": "My Favorite Setup",
  "createdAt": "2024-01-15T10:30:00Z",
  "gameMode": "pve",
  "board": "urban_combat",
  "team1": "spaceMarine_intercessor2",
  "team2": "chaos_marine_squad",
  "primary": "take_and_hold"
}
```

## 2. Types TypeScript

### 2.1. Types de Configuration (`frontend/src/types/deployment.ts`)

```typescript
// Types pour les configurations
export interface BoardConfig {
  name: string;
  description: string;
  cols: number;
  rows: number;
  hex_radius: number;
  wall_hexes: Array<[number, number]>;
  objectives: Array<{
    id: string;
    hex: [number, number];
    type: string;
  }>;
  deployment_zones: {
    attacker: Array<[number, number]>;
    defender: Array<[number, number]>;
  };
  colors?: Record<string, any>;
}

export interface TeamConfig {
  faction: string;
  name: string;
  units: Array<{
    unitType: string;
    count: number;
    player: 0 | 1;
  }>;
  totalPoints: number;
  description: string;
}

export interface PrimaryConfig {
  name: string;
  description: string;
  rules: {
    scoring: string;
    pointsPerObjective: number;
    maxPoints: number;
  };
}

export interface GameSetup {
  gameMode: "pvp" | "pve";
  board: string;
  team1: string;
  team2: string;
  primary: string;
}

export interface DeploymentState {
  deployedUnits: Array<{
    unitId: number;
    col: number;
    row: number;
    player: 0 | 1;
  }>;
  playerReady: {
    0: boolean;
    1: boolean;
  };
  currentDeployer: 0 | 1;
  history: Array<DeploymentAction>;
  historyIndex: number;
}

export interface DeploymentAction {
  type: "deploy" | "undeploy";
  unitId: number;
  col: number;
  row: number;
  player: 0 | 1;
  timestamp: number;
}

export interface AttackerDefenderResult {
  playerRoll: number;
  aiRoll: number;
  playerIsAttacker: boolean;
}
```

## 3. Composants Frontend

### 3.1. GameSetupPage (`frontend/src/pages/GameSetupPage.tsx`)

**Responsabilités :**
- Afficher les 5 menus déroulants (Mode, Board, Team1, Team2, Primary)
- Charger les listes de configurations disponibles
- Prévisualiser le board sélectionné
- Afficher les unités des teams sélectionnées
- Gérer les templates et configurations sauvegardées
- Afficher le bouton "Commencer la partie" quand tout est sélectionné

**Implémentation complète :**

```typescript
import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { GameSetup, BoardConfig, TeamConfig, PrimaryConfig } from '../types/deployment';

const GameSetupPage: React.FC = () => {
  const navigate = useNavigate();
  const [setup, setSetup] = useState<Partial<GameSetup>>({});
  const [boards, setBoards] = useState<Record<string, BoardConfig>>({});
  const [teams, setTeams] = useState<Record<string, TeamConfig>>({});
  const [primaries, setPrimaries] = useState<Record<string, PrimaryConfig>>({});
  const [selectedBoardPreview, setSelectedBoardPreview] = useState<BoardConfig | null>(null);
  const [selectedTeam1Units, setSelectedTeam1Units] = useState<TeamConfig | null>(null);
  const [selectedTeam2Units, setSelectedTeam2Units] = useState<TeamConfig | null>(null);
  const [templates, setTemplates] = useState<Array<{name: string, config: GameSetup}>>([]);
  const [savedSetups, setSavedSetups] = useState<Array<{name: string, config: GameSetup}>>([]);
  
  // Charger les listes disponibles
  useEffect(() => {
    loadConfigurationLists();
  }, []);
  
  const loadConfigurationLists = async () => {
    try {
      const [boardsRes, teamsRes, primariesRes, templatesRes, savedRes] = await Promise.all([
        fetch('/api/config/boards'),
        fetch('/api/config/teams'),
        fetch('/api/config/primaries'),
        fetch('/api/config/templates'),
        fetch('/api/config/saved-setups')
      ]);
      
      const boardsData = await boardsRes.json();
      const teamsData = await teamsRes.json();
      const primariesData = await primariesRes.json();
      const templatesData = await templatesRes.json();
      const savedData = await savedRes.json();
      
      setBoards(boardsData);
      setTeams(teamsData);
      setPrimaries(primariesData);
      setTemplates(templatesData);
      setSavedSetups(savedData);
    } catch (error) {
      console.error('Error loading configurations:', error);
    }
  };
  
  const handleBoardSelect = async (boardName: string) => {
    setSetup(prev => ({ ...prev, board: boardName }));
    const boardConfig = await fetch(`/api/config/board/${boardName}`).then(r => r.json());
    setSelectedBoardPreview(boardConfig);
  };
  
  const handleTeam1Select = async (teamName: string) => {
    setSetup(prev => ({ ...prev, team1: teamName }));
    const teamConfig = await fetch(`/api/config/team/${teamName}`).then(r => r.json());
    setSelectedTeam1Units(teamConfig);
  };
  
  const handleTeam2Select = async (teamName: string) => {
    setSetup(prev => ({ ...prev, team2: teamName }));
    const teamConfig = await fetch(`/api/config/team/${teamName}`).then(r => r.json());
    setSelectedTeam2Units(teamConfig);
  };
  
  const handleSaveSetup = async () => {
    if (!isSetupComplete()) return;
    const setupName = prompt('Nom de la configuration:');
    if (setupName) {
      await fetch('/api/config/save-setup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: setupName, ...setup })
      });
      loadConfigurationLists();
    }
  };
  
  const handleLoadTemplate = (templateName: string) => {
    const template = templates.find(t => t.name === templateName);
    if (template) {
      setSetup(template.config);
      handleBoardSelect(template.config.board);
      handleTeam1Select(template.config.team1);
      handleTeam2Select(template.config.team2);
    }
  };
  
  const isSetupComplete = () => {
    return setup.gameMode && setup.board && setup.team1 && setup.team2 && setup.primary;
  };
  
  const handleStartGame = async () => {
    if (!isSetupComplete()) return;
    
    // Initialiser le déploiement
    const response = await fetch('/api/deployment/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ setup })
    });
    
    const { sessionId } = await response.json();
    navigate('/deployment', { state: { ...setup, sessionId } });
  };
  
  return (
    <div className="game-setup-page" style={{ height: '100vh', display: 'flex', flexDirection: 'column' }}>
      {/* Ligne des menus déroulants à 25% de la hauteur */}
      <div className="setup-menu-bar" style={{ height: '25%', display: 'flex', gap: '16px', padding: '16px' }}>
        <select value={setup.gameMode || ''} onChange={(e) => setSetup(prev => ({ ...prev, gameMode: e.target.value as "pvp" | "pve" }))}>
          <option value="">Mode de jeu</option>
          <option value="pvp">PvP</option>
          <option value="pve">PvE</option>
        </select>
        
        <select value={setup.board || ''} onChange={(e) => handleBoardSelect(e.target.value)}>
          <option value="">Board</option>
          {Object.keys(boards).map(name => (
            <option key={name} value={name}>{name}</option>
          ))}
        </select>
        
        <select value={setup.team1 || ''} onChange={(e) => handleTeam1Select(e.target.value)}>
          <option value="">Team 1</option>
          {Object.keys(teams).map(name => (
            <option key={name} value={name}>{name}</option>
          ))}
        </select>
        
        <select value={setup.team2 || ''} onChange={(e) => handleTeam2Select(e.target.value)}>
          <option value="">Team 2</option>
          {Object.keys(teams).map(name => (
            <option key={name} value={name}>{name}</option>
          ))}
        </select>
        
        <select value={setup.primary || ''} onChange={(e) => setSetup(prev => ({ ...prev, primary: e.target.value }))}>
          <option value="">Primary</option>
          {Object.keys(primaries).map(name => (
            <option key={name} value={name}>{name}</option>
          ))}
        </select>
      </div>
      
      {/* Prévisualisations */}
      <div style={{ flex: 1, padding: '16px', overflow: 'auto' }}>
        {selectedBoardPreview && (
          <div>
            <h3>{selectedBoardPreview.name}</h3>
            <p>{selectedBoardPreview.description}</p>
            <p>Taille: {selectedBoardPreview.cols}x{selectedBoardPreview.rows}</p>
            <p>Objectifs: {selectedBoardPreview.objectives.length}</p>
          </div>
        )}
        
        {selectedTeam1Units && (
          <div>
            <h4>Team 1 Units:</h4>
            <ul>
              {selectedTeam1Units.units.map((unit, idx) => (
                <li key={idx}>{unit.unitType} x{unit.count}</li>
              ))}
            </ul>
          </div>
        )}
        
        {selectedTeam2Units && (
          <div>
            <h4>Team 2 Units:</h4>
            <ul>
              {selectedTeam2Units.units.map((unit, idx) => (
                <li key={idx}>{unit.unitType} x{unit.count}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
      
      {/* Menu Templates/Save */}
      <div className="setup-actions" style={{ padding: '16px', borderTop: '1px solid #ccc' }}>
        <select onChange={(e) => handleLoadTemplate(e.target.value)}>
          <option value="">Charger un template</option>
          {templates.map(t => (
            <option key={t.name} value={t.name}>{t.name}</option>
          ))}
        </select>
        <button onClick={handleSaveSetup}>Sauvegarder</button>
      </div>
      
      {/* Bouton Commencer */}
      {isSetupComplete() && (
        <button 
          className="start-game-button" 
          onClick={handleStartGame}
          style={{ padding: '16px', fontSize: '18px', margin: '16px' }}
        >
          Commencer la partie
        </button>
      )}
    </div>
  );
};

export default GameSetupPage;
```

### 3.2. DeploymentPage (`frontend/src/pages/DeploymentPage.tsx`)

**Responsabilités :**
- Afficher le board avec zones de déploiement (hexagones rouges/verts)
- Gérer le module Army Roster (remplace Game Log)
- Gérer le déploiement click-click
- Gérer l'historique Undo/Redo
- Gérer le bouton "Ready!"
- Synchroniser avec le backend en PvP

**Implémentation complète :**

```typescript
import React, { useState, useEffect } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import BoardPvp from '../components/BoardPvp';
import { ArmyRoster } from '../components/ArmyRoster';
import { AttackerDefenderModal } from '../components/AttackerDefenderModal';
import { GameSetup, DeploymentState, AttackerDefenderResult } from '../types/deployment';

const DeploymentPage: React.FC = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const { setup, sessionId } = location.state as { setup: GameSetup; sessionId: string };
  
  const [deploymentState, setDeploymentState] = useState<DeploymentState | null>(null);
  const [selectedUnitId, setSelectedUnitId] = useState<number | null>(null);
  const [showAttackerDefender, setShowAttackerDefender] = useState(false);
  const [attackerPlayer, setAttackerPlayer] = useState<0 | 1 | null>(null);
  
  useEffect(() => {
    initializeDeployment();
  }, []);
  
  // Polling pour PvP (toutes les 2 secondes)
  useEffect(() => {
    if (setup.gameMode === 'pvp') {
      const interval = setInterval(() => {
        fetchDeploymentState();
      }, 2000);
      return () => clearInterval(interval);
    }
  }, [setup.gameMode]);
  
  const initializeDeployment = async () => {
    if (setup.gameMode === 'pve') {
      setShowAttackerDefender(true);
    } else {
      // PvP : joueur 1 commence (attacker)
      setAttackerPlayer(0);
      await fetchDeploymentState();
    }
  };
  
  const fetchDeploymentState = async () => {
    try {
      const response = await fetch(`/api/deployment/state?sessionId=${sessionId}`);
      const state = await response.json();
      setDeploymentState(state);
      
      // Vérifier si tous les joueurs sont prêts
      if (state.playerReady[0] && state.playerReady[1]) {
        navigate('/game', { state: { setup, deploymentState: state } });
      }
    } catch (error) {
      console.error('Error fetching deployment state:', error);
    }
  };
  
  const handleRollDice = async () => {
    const response = await fetch('/api/deployment/roll-attacker', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sessionId })
    });
    const result: AttackerDefenderResult = await response.json();
    setAttackerPlayer(result.playerIsAttacker ? 0 : 1);
    return result;
  };
  
  const handleUnitClick = (unitId: number) => {
    setSelectedUnitId(unitId);
  };
  
  const handleHexClick = async (col: number, row: number) => {
    if (!selectedUnitId || !deploymentState) return;
    
    const currentPlayer = deploymentState.currentDeployer;
    
    // Valider que l'hex est dans la zone de déploiement du joueur
    // (validation côté backend aussi)
    
    const response = await fetch('/api/deployment/deploy', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        sessionId,
        unitId: selectedUnitId,
        col,
        row,
        player: currentPlayer
      })
    });
    
    if (response.ok) {
      const updatedState = await response.json();
      setDeploymentState(updatedState.deploymentState);
      setSelectedUnitId(null);
    }
  };
  
  const handleUndo = async () => {
    const response = await fetch('/api/deployment/undo', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sessionId })
    });
    if (response.ok) {
      const updatedState = await response.json();
      setDeploymentState(updatedState.deploymentState);
    }
  };
  
  const handleRedo = async () => {
    const response = await fetch('/api/deployment/redo', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sessionId })
    });
    if (response.ok) {
      const updatedState = await response.json();
      setDeploymentState(updatedState.deploymentState);
    }
  };
  
  const handleReady = async () => {
    if (!deploymentState) return;
    
    const currentPlayer = deploymentState.currentDeployer;
    const response = await fetch('/api/deployment/ready', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sessionId, player: currentPlayer })
    });
    
    if (response.ok) {
      const updatedState = await response.json();
      setDeploymentState(updatedState.deploymentState);
      
      // Si les deux joueurs sont prêts, la navigation se fera via fetchDeploymentState
      if (updatedState.deploymentState.playerReady[0] && updatedState.deploymentState.playerReady[1]) {
        navigate('/game', { state: { setup, deploymentState: updatedState.deploymentState } });
      }
    }
  };
  
  return (
    <div className="deployment-page" style={{ display: 'flex', height: '100vh' }}>
      <div className="deployment-board" style={{ flex: 1 }}>
        <BoardPvp 
          boardConfig={setup.board}
          deploymentZones={deploymentState?.deployment_zones}
          deployedUnits={deploymentState?.deployedUnits}
          onHexClick={handleHexClick}
          selectedUnitId={selectedUnitId}
        />
      </div>
      
      <div className="deployment-sidebar" style={{ width: '300px', borderLeft: '1px solid #ccc' }}>
        <ArmyRoster 
          team1Config={setup.team1}
          team2Config={setup.team2}
          deploymentState={deploymentState}
          onUnitClick={handleUnitClick}
          selectedUnitId={selectedUnitId}
          onUndo={handleUndo}
          onRedo={handleRedo}
          canUndo={deploymentState ? deploymentState.historyIndex >= 0 : false}
          canRedo={deploymentState ? deploymentState.historyIndex < deploymentState.history.length - 1 : false}
          allUnitsDeployed={false} // À calculer selon les unités déployées
          onReady={handleReady}
          isReady={deploymentState ? deploymentState.playerReady[deploymentState.currentDeployer] : false}
        />
      </div>
      
      {showAttackerDefender && (
        <AttackerDefenderModal
          isOpen={showAttackerDefender}
          onComplete={(result) => {
            setAttackerPlayer(result.playerIsAttacker ? 0 : 1);
            setShowAttackerDefender(false);
          }}
          onRollDice={handleRollDice}
        />
      )}
    </div>
  );
};

export default DeploymentPage;
```

### 3.3. ArmyRoster (`frontend/src/components/ArmyRoster.tsx`)

**Responsabilités :**
- Afficher les icônes des unités non déployées
- Gérer la sélection d'unité (click pour sélectionner)
- Afficher les boutons Undo/Redo
- Afficher le bouton "Ready!" quand toutes les unités sont déployées
- Indiquer visuellement les unités déployées vs non déployées

**Props :**
```typescript
interface ArmyRosterProps {
  team1Config: string;
  team2Config: string;
  deploymentState: DeploymentState | null;
  onUnitClick: (unitId: number) => void;
  selectedUnitId: number | null;
  onUndo: () => void;
  onRedo: () => void;
  canUndo: boolean;
  canRedo: boolean;
  allUnitsDeployed: boolean;
  onReady: () => void;
  isReady: boolean;
}
```

### 3.4. AttackerDefenderModal (`frontend/src/components/AttackerDefenderModal.tsx`)

**Responsabilités :**
- Afficher le popup de détermination Attacker/Defender (PvE uniquement)
- Gérer le lancer de dés
- Afficher les résultats
- Afficher le bouton "Deploy Armies"

**Implémentation :**

```typescript
import React, { useState } from 'react';
import { AttackerDefenderResult } from '../types/deployment';

interface AttackerDefenderModalProps {
  isOpen: boolean;
  onComplete: (result: AttackerDefenderResult) => void;
  onRollDice: () => Promise<AttackerDefenderResult>;
}

export const AttackerDefenderModal: React.FC<AttackerDefenderModalProps> = ({ 
  isOpen, 
  onComplete, 
  onRollDice 
}) => {
  const [playerRoll, setPlayerRoll] = useState<number | null>(null);
  const [aiRoll, setAiRoll] = useState<number | null>(null);
  const [isRolling, setIsRolling] = useState(false);
  const [result, setResult] = useState<AttackerDefenderResult | null>(null);
  
  const handleDiceClick = async () => {
    setIsRolling(true);
    const rollResult = await onRollDice();
    setPlayerRoll(rollResult.playerRoll);
    setAiRoll(rollResult.aiRoll);
    setResult(rollResult);
    setIsRolling(false);
  };
  
  if (!isOpen) return null;
  
  return (
    <div style={{
      position: 'fixed',
      top: '50%',
      left: '50%',
      transform: 'translate(-50%, -50%)',
      background: 'white',
      padding: '32px',
      borderRadius: '8px',
      boxShadow: '0 4px 6px rgba(0,0,0,0.1)',
      zIndex: 1000
    }}>
      <h2>Determine Attacker and Defender</h2>
      <div style={{ textAlign: 'center', margin: '24px 0' }}>
        <button 
          onClick={handleDiceClick} 
          disabled={isRolling}
          style={{ fontSize: '48px', padding: '16px', cursor: 'pointer' }}
        >
          🎲
        </button>
        {playerRoll && (
          <div>
            <p>Player Roll: {playerRoll}</p>
            <p>AI Roll: {aiRoll}</p>
          </div>
        )}
      </div>
      {result && (
        <div style={{ textAlign: 'center' }}>
          <p style={{ fontSize: '18px', fontWeight: 'bold' }}>
            {result.playerIsAttacker ? "You are the Attacker !" : "You are the Defender !"}
          </p>
          <button 
            onClick={() => onComplete(result)}
            style={{ marginTop: '16px', padding: '12px 24px', fontSize: '16px' }}
          >
            Deploy Armies
          </button>
        </div>
      )}
    </div>
  );
};
```

## 4. Hooks Frontend

### 4.1. useGameSetup (`frontend/src/hooks/useGameSetup.ts`)

**Responsabilités :**
- Charger les listes de configurations disponibles
- Gérer l'état de sélection
- Valider que toutes les sélections sont complètes
- Charger/sauvegarder les templates et setups

```typescript
import { useState, useEffect } from 'react';
import { GameSetup, BoardConfig, TeamConfig, PrimaryConfig } from '../types/deployment';

export function useGameSetup() {
  const [setup, setSetup] = useState<Partial<GameSetup>>({});
  const [availableBoards, setAvailableBoards] = useState<string[]>([]);
  const [availableTeams, setAvailableTeams] = useState<string[]>([]);
  const [availablePrimaries, setAvailablePrimaries] = useState<string[]>([]);
  const [templates, setTemplates] = useState<Array<{name: string, config: GameSetup}>>([]);
  const [savedSetups, setSavedSetups] = useState<Array<{name: string, config: GameSetup}>>([]);
  
  useEffect(() => {
    loadLists();
  }, []);
  
  const loadLists = async () => {
    try {
      const [boardsRes, teamsRes, primariesRes, templatesRes, savedRes] = await Promise.all([
        fetch('/api/config/boards'),
        fetch('/api/config/teams'),
        fetch('/api/config/primaries'),
        fetch('/api/config/templates'),
        fetch('/api/config/saved-setups')
      ]);
      
      setAvailableBoards(Object.keys(await boardsRes.json()));
      setAvailableTeams(Object.keys(await teamsRes.json()));
      setAvailablePrimaries(Object.keys(await primariesRes.json()));
      setTemplates(await templatesRes.json());
      setSavedSetups(await savedRes.json());
    } catch (error) {
      console.error('Error loading lists:', error);
    }
  };
  
  const loadBoardConfig = async (boardName: string): Promise<BoardConfig> => {
    const response = await fetch(`/api/config/board/${boardName}`);
    return response.json();
  };
  
  const loadTeamConfig = async (teamName: string): Promise<TeamConfig> => {
    const response = await fetch(`/api/config/team/${teamName}`);
    return response.json();
  };
  
  const loadPrimaryConfig = async (primaryName: string): Promise<PrimaryConfig> => {
    const response = await fetch(`/api/config/primary/${primaryName}`);
    return response.json();
  };
  
  const loadTemplate = async (templateName: string): Promise<GameSetup> => {
    const response = await fetch(`/api/config/template/${templateName}`);
    const template = await response.json();
    return template;
  };
  
  const saveSetup = async (setupName: string, setupToSave: GameSetup): Promise<void> => {
    await fetch('/api/config/save-setup', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: setupName, ...setupToSave })
    });
  };
  
  const loadSavedSetup = async (setupName: string): Promise<GameSetup> => {
    const response = await fetch(`/api/config/saved-setup/${setupName}`);
    return response.json();
  };
  
  const isSetupComplete = (): boolean => {
    return !!(setup.gameMode && setup.board && setup.team1 && setup.team2 && setup.primary);
  };
  
  return {
    setup,
    setSetup,
    availableBoards,
    availableTeams,
    availablePrimaries,
    templates,
    savedSetups,
    loadBoardConfig,
    loadTeamConfig,
    loadPrimaryConfig,
    loadTemplate,
    saveSetup,
    loadSavedSetup,
    isSetupComplete
  };
}
```

### 4.2. useDeployment (`frontend/src/hooks/useDeployment.ts`)

**Responsabilités :**
- Gérer l'état de déploiement
- Gérer l'historique Undo/Redo (10 dernières actions)
- Synchroniser avec le backend en PvP (polling toutes les 2 secondes)
- Valider les positions de déploiement

```typescript
import { useState, useEffect, useCallback } from 'react';
import { GameSetup, BoardConfig, TeamConfig, DeploymentState } from '../types/deployment';

export function useDeployment(
  setup: GameSetup,
  boardConfig: BoardConfig,
  team1Config: TeamConfig,
  team2Config: TeamConfig,
  isPvP: boolean,
  sessionId: string
) {
  const [deploymentState, setDeploymentState] = useState<DeploymentState>({
    deployedUnits: [],
    playerReady: { 0: false, 1: false },
    currentDeployer: 0,
    history: [],
    historyIndex: -1
  });
  
  const [selectedUnitId, setSelectedUnitId] = useState<number | null>(null);
  
  // Synchronisation PvP
  useEffect(() => {
    if (isPvP) {
      const interval = setInterval(() => {
        syncDeploymentState();
      }, 2000);
      return () => clearInterval(interval);
    }
  }, [isPvP, sessionId]);
  
  const syncDeploymentState = async () => {
    try {
      const response = await fetch(`/api/deployment/state?sessionId=${sessionId}`);
      const state = await response.json();
      setDeploymentState(state);
    } catch (error) {
      console.error('Error syncing deployment state:', error);
    }
  };
  
  const deployUnit = useCallback(async (unitId: number, col: number, row: number, player: 0 | 1) => {
    if (!isValidDeploymentHex(col, row, player)) {
      return false;
    }
    
    const response = await fetch('/api/deployment/deploy', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sessionId, unitId, col, row, player })
    });
    
    if (response.ok) {
      const result = await response.json();
      setDeploymentState(result.deploymentState);
      return true;
    }
    return false;
  }, [sessionId, deploymentState]);
  
  const undeployUnit = useCallback(async (unitId: number) => {
    // Implémenter le retrait d'unité
  }, [sessionId]);
  
  const undo = useCallback(async () => {
    const response = await fetch('/api/deployment/undo', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sessionId })
    });
    if (response.ok) {
      const result = await response.json();
      setDeploymentState(result.deploymentState);
    }
  }, [sessionId]);
  
  const redo = useCallback(async () => {
    const response = await fetch('/api/deployment/redo', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sessionId })
    });
    if (response.ok) {
      const result = await response.json();
      setDeploymentState(result.deploymentState);
    }
  }, [sessionId]);
  
  const setReady = useCallback(async (player: 0 | 1) => {
    const response = await fetch('/api/deployment/ready', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sessionId, player })
    });
    if (response.ok) {
      const result = await response.json();
      setDeploymentState(result.deploymentState);
    }
  }, [sessionId]);
  
  const isValidDeploymentHex = (col: number, row: number, player: 0 | 1): boolean => {
    if (!boardConfig) return false;
    
    const zone = player === 0 ? boardConfig.deployment_zones.attacker : boardConfig.deployment_zones.defender;
    const hexInZone = zone.some(h => h[0] === col && h[1] === row);
    
    if (!hexInZone) return false;
    
    // Vérifier si l'hex est occupé
    const isOccupied = deploymentState.deployedUnits.some(
      u => u.col === col && u.row === row
    );
    
    return !isOccupied;
  };
  
  const isHexOccupied = (col: number, row: number): boolean => {
    return deploymentState.deployedUnits.some(
      u => u.col === col && u.row === row
    );
  };
  
  const getAllDeployedUnits = () => deploymentState.deployedUnits;
  
  const getUndeployedUnits = (player: 0 | 1) => {
    const teamConfig = player === 0 ? team1Config : team2Config;
    const deployedUnitIds = deploymentState.deployedUnits
      .filter(u => u.player === player)
      .map(u => u.unitId);
    
    return teamConfig.units.filter((_, idx) => !deployedUnitIds.includes(idx));
  };
  
  return {
    deploymentState,
    selectedUnitId,
    setSelectedUnitId,
    deployUnit,
    undeployUnit,
    undo,
    redo,
    setReady,
    isValidDeploymentHex,
    isHexOccupied,
    getAllDeployedUnits,
    getUndeployedUnits
  };
}
```

## 5. Endpoints Backend

### 5.1. Configuration Endpoints (`services/api_server.py`)

**Code Python complet avec implémentation :**

```python
import os
import json
import time
import random
from flask import request, jsonify
from typing import Dict, Any, Tuple

# Variable globale pour stocker les sessions de déploiement (en mémoire pour MVP)
deployment_sessions: Dict[str, Dict[str, Any]] = {}

def get_project_root():
    """Retourne le chemin racine du projet."""
    return os.path.join(os.path.dirname(__file__), '..')

@app.route('/api/config/boards', methods=['GET'])
def get_available_boards():
    """Retourne la liste des boards disponibles."""
    boards_dir = os.path.join(get_project_root(), 'config', 'board')
    boards = {}
    if os.path.exists(boards_dir):
        for file in os.listdir(boards_dir):
            if file.endswith('.json'):
                board_name = file[:-5]
                with open(os.path.join(boards_dir, file), 'r', encoding='utf-8') as f:
                    boards[board_name] = json.load(f)
    return jsonify(boards)

@app.route('/api/config/board/<board_name>', methods=['GET'])
def get_board_config(board_name):
    """Retourne la configuration d'un board spécifique."""
    board_file = os.path.join(get_project_root(), 'config', 'board', f'{board_name}.json')
    if not os.path.exists(board_file):
        return jsonify({"error": "Board not found"}), 404
    with open(board_file, 'r', encoding='utf-8') as f:
        return jsonify(json.load(f))

@app.route('/api/config/teams', methods=['GET'])
def get_available_teams():
    """Retourne la liste des teams disponibles."""
    teams_dir = os.path.join(get_project_root(), 'config', 'teams')
    teams = {}
    if os.path.exists(teams_dir):
        for file in os.listdir(teams_dir):
            if file.endswith('.json'):
                team_name = file[:-5]
                with open(os.path.join(teams_dir, file), 'r', encoding='utf-8') as f:
                    teams[team_name] = json.load(f)
    return jsonify(teams)

@app.route('/api/config/team/<team_name>', methods=['GET'])
def get_team_config(team_name):
    """Retourne la configuration d'une team spécifique."""
    team_file = os.path.join(get_project_root(), 'config', 'teams', f'{team_name}.json')
    if not os.path.exists(team_file):
        return jsonify({"error": "Team not found"}), 404
    with open(team_file, 'r', encoding='utf-8') as f:
        return jsonify(json.load(f))

@app.route('/api/config/primaries', methods=['GET'])
def get_available_primaries():
    """Retourne la liste des primaires disponibles."""
    primaries_dir = os.path.join(get_project_root(), 'config', 'primary')
    primaries = {}
    if os.path.exists(primaries_dir):
        for file in os.listdir(primaries_dir):
            if file.endswith('.json'):
                primary_name = file[:-5]
                with open(os.path.join(primaries_dir, file), 'r', encoding='utf-8') as f:
                    primaries[primary_name] = json.load(f)
    return jsonify(primaries)

@app.route('/api/config/primary/<primary_name>', methods=['GET'])
def get_primary_config(primary_name):
    """Retourne la configuration d'une primary."""
    primary_file = os.path.join(get_project_root(), 'config', 'primary', f'{primary_name}.json')
    if not os.path.exists(primary_file):
        return jsonify({"error": "Primary not found"}), 404
    with open(primary_file, 'r', encoding='utf-8') as f:
        return jsonify(json.load(f))

@app.route('/api/config/templates', methods=['GET'])
def get_available_templates():
    """Retourne la liste des templates disponibles."""
    templates_dir = os.path.join(get_project_root(), 'config', 'templates')
    templates = []
    if os.path.exists(templates_dir):
        for file in os.listdir(templates_dir):
            if file.endswith('.json'):
                with open(os.path.join(templates_dir, file), 'r', encoding='utf-8') as f:
                    templates.append(json.load(f))
    return jsonify(templates)

@app.route('/api/config/template/<template_name>', methods=['GET'])
def get_template(template_name):
    """Retourne un template spécifique."""
    template_file = os.path.join(get_project_root(), 'config', 'templates', f'{template_name}.json')
    if not os.path.exists(template_file):
        return jsonify({"error": "Template not found"}), 404
    with open(template_file, 'r', encoding='utf-8') as f:
        return jsonify(json.load(f))

@app.route('/api/config/saved-setups', methods=['GET'])
def get_saved_setups():
    """Retourne la liste des setups sauvegardés pour l'utilisateur."""
    saved_dir = os.path.join(get_project_root(), 'config', 'saved_setups')
    setups = []
    if os.path.exists(saved_dir):
        for file in os.listdir(saved_dir):
            if file.endswith('.json'):
                with open(os.path.join(saved_dir, file), 'r', encoding='utf-8') as f:
                    setups.append(json.load(f))
    return jsonify(setups)

@app.route('/api/config/saved-setup/<setup_name>', methods=['GET'])
def get_saved_setup(setup_name):
    """Retourne un setup sauvegardé."""
    setup_file = os.path.join(get_project_root(), 'config', 'saved_setups', f'{setup_name}.json')
    if not os.path.exists(setup_file):
        return jsonify({"error": "Saved setup not found"}), 404
    with open(setup_file, 'r', encoding='utf-8') as f:
        return jsonify(json.load(f))

@app.route('/api/config/save-setup', methods=['POST'])
def save_setup():
    """Sauvegarde un setup."""
    data = request.get_json()
    setup_name = data.get('name', f"setup_{int(time.time())}")
    saved_dir = os.path.join(get_project_root(), 'config', 'saved_setups')
    os.makedirs(saved_dir, exist_ok=True)
    
    setup_file = os.path.join(saved_dir, f'{setup_name}.json')
    with open(setup_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
    
    return jsonify({"success": True, "name": setup_name})
```

### 5.2. Deployment Endpoints (`services/api_server.py`)

**Code Python complet avec implémentation :**

```python
import uuid

def generate_session_id() -> str:
    """Génère un ID de session unique."""
    return str(uuid.uuid4())

def load_board_config(board_name: str) -> Dict[str, Any]:
    """Charge la configuration d'un board."""
    board_file = os.path.join(get_project_root(), 'config', 'board', f'{board_name}.json')
    with open(board_file, 'r', encoding='utf-8') as f:
        return json.load(f)

def load_team_config(team_name: str) -> Dict[str, Any]:
    """Charge la configuration d'une team."""
    team_file = os.path.join(get_project_root(), 'config', 'teams', f'{team_name}.json')
    with open(team_file, 'r', encoding='utf-8') as f:
        return json.load(f)

@app.route('/api/deployment/start', methods=['POST'])
def start_deployment():
    """Initialise une session de déploiement avec la configuration choisie."""
    data = request.get_json()
    setup = data.get('setup')
    
    if not setup:
        return jsonify({"error": "Setup configuration required"}), 400
    
    # Charger les configurations
    board_config = load_board_config(setup['board'])
    team1_config = load_team_config(setup['team1'])
    team2_config = load_team_config(setup['team2'])
    
    # Créer l'état de déploiement initial
    deployment_state = {
        "deployedUnits": [],
        "playerReady": {0: False, 1: False},
        "currentDeployer": 0,  # Attacker commence
        "history": [],
        "historyIndex": -1,
        "boardConfig": board_config,
        "team1Config": team1_config,
        "team2Config": team2_config,
        "attackerPlayer": None  # Sera déterminé en PvE
    }
    
    # Générer un ID de session
    session_id = data.get('sessionId', generate_session_id())
    deployment_sessions[session_id] = deployment_state
    
    return jsonify({
        "success": True,
        "sessionId": session_id,
        "deploymentState": deployment_state
    })

@app.route('/api/deployment/state', methods=['GET'])
def get_deployment_state():
    """Récupère l'état actuel du déploiement (pour synchronisation PvP)."""
    session_id = request.args.get('sessionId')
    if not session_id:
        return jsonify({"error": "sessionId required"}), 400
    
    deployment_state = deployment_sessions.get(session_id)
    if not deployment_state:
        return jsonify({"error": "Session not found"}), 404
    
    return jsonify(deployment_state)

@app.route('/api/deployment/deploy', methods=['POST'])
def deploy_unit():
    """Déploie une unité à une position donnée."""
    data = request.get_json()
    session_id = data.get('sessionId')
    unit_id = data.get('unitId')
    col = data.get('col')
    row = data.get('row')
    player = data.get('player')
    
    if not all([session_id, unit_id is not None, col is not None, row is not None, player is not None]):
        return jsonify({"error": "Missing required parameters"}), 400
    
    deployment_state = deployment_sessions.get(session_id)
    if not deployment_state:
        return jsonify({"error": "Session not found"}), 404
    
    # Valider la position
    if not is_valid_deployment_hex(deployment_state, col, row, player):
        return jsonify({"error": "Invalid deployment hex"}), 400
    
    # Ajouter l'unité déployée
    deployed_unit = {
        "unitId": unit_id,
        "col": col,
        "row": row,
        "player": player
    }
    deployment_state["deployedUnits"].append(deployed_unit)
    
    # Ajouter à l'historique (limiter à 10 actions)
    action = {
        "type": "deploy",
        "unitId": unit_id,
        "col": col,
        "row": row,
        "player": player,
        "timestamp": time.time()
    }
    deployment_state["history"].append(action)
    
    # Limiter l'historique à 10 actions
    if len(deployment_state["history"]) > 10:
        deployment_state["history"] = deployment_state["history"][-10:]
    
    deployment_state["historyIndex"] = len(deployment_state["history"]) - 1
    
    # Alterner le joueur si nécessaire
    switch_deploying_player(deployment_state)
    
    return jsonify({
        "success": True,
        "deploymentState": deployment_state
    })

@app.route('/api/deployment/ready', methods=['POST'])
def set_player_ready():
    """Marque un joueur comme prêt."""
    data = request.get_json()
    session_id = data.get('sessionId')
    player = data.get('player')
    
    if not session_id or player is None:
        return jsonify({"error": "sessionId and player required"}), 400
    
    deployment_state = deployment_sessions.get(session_id)
    if not deployment_state:
        return jsonify({"error": "Session not found"}), 404
    
    deployment_state["playerReady"][player] = True
    
    return jsonify({
        "success": True,
        "deploymentState": deployment_state
    })

@app.route('/api/deployment/roll-attacker', methods=['POST'])
def roll_attacker_defender():
    """Lance les dés pour déterminer Attacker/Defender (PvE)."""
    data = request.get_json()
    session_id = data.get('sessionId')
    
    player_roll = random.randint(1, 6)
    ai_roll = random.randint(1, 6)
    
    player_is_attacker = player_roll > ai_roll
    
    # Mettre à jour l'état de déploiement si session existe
    if session_id and session_id in deployment_sessions:
        deployment_sessions[session_id]["attackerPlayer"] = 0 if player_is_attacker else 1
        deployment_sessions[session_id]["currentDeployer"] = 0 if player_is_attacker else 1
    
    return jsonify({
        "playerRoll": player_roll,
        "aiRoll": ai_roll,
        "playerIsAttacker": player_is_attacker
    })

@app.route('/api/deployment/undo', methods=['POST'])
def deployment_undo():
    """Annule la dernière action de déploiement."""
    data = request.get_json()
    session_id = data.get('sessionId')
    
    if not session_id:
        return jsonify({"error": "sessionId required"}), 400
    
    deployment_state = deployment_sessions.get(session_id)
    if not deployment_state:
        return jsonify({"error": "Session not found"}), 404
    
    if deployment_state["historyIndex"] < 0:
        return jsonify({"error": "Nothing to undo"}), 400
    
    # Récupérer la dernière action
    last_action = deployment_state["history"][deployment_state["historyIndex"]]
    
    # Retirer l'unité déployée
    deployment_state["deployedUnits"] = [
        u for u in deployment_state["deployedUnits"]
        if not (u["unitId"] == last_action["unitId"] and 
                u["col"] == last_action["col"] and 
                u["row"] == last_action["row"])
    ]
    
    # Décrémenter l'index d'historique
    deployment_state["historyIndex"] -= 1
    
    return jsonify({
        "success": True,
        "deploymentState": deployment_state
    })

@app.route('/api/deployment/redo', methods=['POST'])
def deployment_redo():
    """Refait l'action annulée."""
    data = request.get_json()
    session_id = data.get('sessionId')
    
    if not session_id:
        return jsonify({"error": "sessionId required"}), 400
    
    deployment_state = deployment_sessions.get(session_id)
    if not deployment_state:
        return jsonify({"error": "Session not found"}), 404
    
    if deployment_state["historyIndex"] >= len(deployment_state["history"]) - 1:
        return jsonify({"error": "Nothing to redo"}), 400
    
    # Incrémenter l'index et réappliquer l'action
    deployment_state["historyIndex"] += 1
    next_action = deployment_state["history"][deployment_state["historyIndex"]]
    
    # Ajouter l'unité déployée
    deployed_unit = {
        "unitId": next_action["unitId"],
        "col": next_action["col"],
        "row": next_action["row"],
        "player": next_action["player"]
    }
    deployment_state["deployedUnits"].append(deployed_unit)
    
    return jsonify({
        "success": True,
        "deploymentState": deployment_state
    })
```

### 5.3. Handlers de Déploiement (`engine/deployment_handlers.py`)

**Code Python complet :**

```python
from typing import Dict, Any, Tuple, List

def is_valid_deployment_hex(deployment_state: Dict[str, Any], col: int, row: int, player: int) -> bool:
    """Vérifie si un hex est valide pour le déploiement."""
    board_config = deployment_state.get("boardConfig")
    if not board_config:
        return False
    
    # Déterminer la zone de déploiement
    attacker_player = deployment_state.get("attackerPlayer", 0)
    zone_key = "attacker" if player == attacker_player else "defender"
    deployment_zone = board_config.get("deployment_zones", {}).get(zone_key, [])
    
    # Vérifier si l'hex est dans la zone (format: [[col, row], ...])
    hex_in_zone = any(h[0] == col and h[1] == row for h in deployment_zone)
    if not hex_in_zone:
        return False
    
    # Vérifier si l'hex est déjà occupé
    all_deployed = deployment_state.get("deployedUnits", [])
    hex_occupied = any(u.get("col") == col and u.get("row") == row for u in all_deployed)
    
    return not hex_occupied

def switch_deploying_player(deployment_state: Dict[str, Any]):
    """Change le joueur qui déploie (alternance)."""
    current = deployment_state.get("currentDeployer", 0)
    team1_config = deployment_state.get("team1Config", {})
    team2_config = deployment_state.get("team2Config", {})
    
    # Compter les unités déployées par joueur
    deployed_units_p0 = len([u for u in deployment_state.get("deployedUnits", []) if u.get("player") == 0])
    deployed_units_p1 = len([u for u in deployment_state.get("deployedUnits", []) if u.get("player") == 1])
    
    total_units_p0 = len(team1_config.get("units", []))
    total_units_p1 = len(team2_config.get("units", []))
    
    # Si le joueur actuel a fini, l'autre continue
    if current == 0 and deployed_units_p0 >= total_units_p0:
        deployment_state["currentDeployer"] = 1
    elif current == 1 and deployed_units_p1 >= total_units_p1:
        deployment_state["currentDeployer"] = 0
    else:
        # Alterner normalement
        deployment_state["currentDeployer"] = 1 - current

def convert_deployment_to_game_state(deployment_state: Dict[str, Any]) -> Dict[str, Any]:
    """Convertit l'état de déploiement en game_state initial."""
    # Cette fonction sera appelée pour initialiser le jeu après le déploiement
    # Elle doit créer les unités aux positions déployées
    
    board_config = deployment_state.get("boardConfig", {})
    team1_config = deployment_state.get("team1Config", {})
    team2_config = deployment_state.get("team2Config", {})
    deployed_units = deployment_state.get("deployedUnits", [])
    
    # Créer les unités depuis les configs et les placer aux positions déployées
    units = []
    unit_id_counter = 0
    
    # Unités du joueur 0
    for unit_config in team1_config.get("units", []):
        deployed_unit = next(
            (u for u in deployed_units if u.get("unitId") == unit_id_counter and u.get("player") == 0),
            None
        )
        if deployed_unit:
            units.append({
                "id": unit_id_counter,
                "player": 0,
                "col": deployed_unit.get("col"),
                "row": deployed_unit.get("row"),
                # ... autres propriétés de l'unité depuis unit_config
            })
        unit_id_counter += 1
    
    # Unités du joueur 1
    for unit_config in team2_config.get("units", []):
        deployed_unit = next(
            (u for u in deployed_units if u.get("unitId") == unit_id_counter and u.get("player") == 1),
            None
        )
        if deployed_unit:
            units.append({
                "id": unit_id_counter,
                "player": 1,
                "col": deployed_unit.get("col"),
                "row": deployed_unit.get("row"),
                # ... autres propriétés de l'unité depuis unit_config
            })
        unit_id_counter += 1
    
    return {
        "units": units,
        "board": board_config,
        "phase": "command",
        "turn": 1,
        "current_player": 0
    }
```

## 6. Intégration avec le Système Existant

### 6.1. Modification de Routes (`frontend/src/Routes.tsx`)

```typescript
import GameSetupPage from './pages/GameSetupPage';
import DeploymentPage from './pages/DeploymentPage';

// Ajouter les routes
<Route path="/setup" element={<GameSetupPage />} />
<Route path="/deployment" element={<DeploymentPage />} />
<Route path="/game" element={<BoardWithAPI />} />
```

### 6.2. Modification de HomePage (`frontend/src/pages/HomePage.tsx`)

Rediriger vers `/setup` au lieu de `/game` directement.

### 6.3. Modification de BoardWithAPI (`frontend/src/components/BoardWithAPI.tsx`)

Accepter un paramètre `deploymentState` pour initialiser le jeu avec les unités déjà déployées.

### 6.4. Modification de l'Engine (`engine/w40k_core.py`)

Ajouter une méthode pour initialiser le jeu avec un état de déploiement :

```python
def initialize_from_deployment(
    self,
    board_config: Dict[str, Any],
    team1_config: Dict[str, Any],
    team2_config: Dict[str, Any],
    deployment_state: Dict[str, Any],
    primary_config: Dict[str, Any]
):
    """Initialise le jeu avec un état de déploiement pré-existant."""
    from engine.deployment_handlers import convert_deployment_to_game_state
    
    # Convertir deployment_state en game_state
    game_state = convert_deployment_to_game_state(deployment_state)
    
    # Initialiser le moteur avec ce game_state
    self.game_state = game_state
    self.config["board"] = board_config
    self.config["primary"] = primary_config
    
    # Phase initiale = command (déploiement terminé)
    self.game_state["phase"] = "command"
```

## 7. Flux de Données

### 7.1. Flux de Configuration

```
HomePage → GameSetupPage
  ↓
Sélection Mode/Board/Teams/Primary
  ↓
Validation complète
  ↓
Bouton "Commencer la partie" apparaît
  ↓
POST /api/deployment/start avec GameSetup
  ↓
Redirection vers DeploymentPage avec sessionId
```

### 7.2. Flux de Déploiement (PvE)

```
DeploymentPage s'affiche
  ↓
AttackerDefenderModal apparaît (PvE uniquement)
  ↓
Lancer les dés (POST /api/deployment/roll-attacker)
  ↓
Résultat affiché
  ↓
Clic sur "Deploy Armies"
  ↓
Modal disparaît, Army Roster visible
  ↓
Déploiement click-click (POST /api/deployment/deploy)
  ↓
Toutes les unités déployées
  ↓
Bouton "Ready!" apparaît
  ↓
Clic sur "Ready!" (POST /api/deployment/ready)
  ↓
Redirection vers BoardWithAPI avec deploymentState
```

### 7.3. Flux de Déploiement (PvP)

```
DeploymentPage s'affiche (les deux joueurs)
  ↓
Army Roster visible immédiatement
  ↓
Déploiement click-click (POST /api/deployment/deploy)
  ↓
Polling toutes les 2s (GET /api/deployment/state)
  ↓
Toutes les unités déployées
  ↓
Bouton "Ready!" apparaît
  ↓
Clic sur "Ready!" (POST /api/deployment/ready)
  ↓
Quand les deux sont prêts → Redirection vers BoardWithAPI
```

## 8. Intégration avec le Training

### 8.1. Phase de Déploiement dans le Training

Le système de training devra inclure une phase de déploiement avant la phase "command".

**Modification de `engine/w40k_core.py` :**

```python
def reset(self, **kwargs):
    # ... code existant ...
    
    # Si en mode training avec déploiement
    if self.config.get("enable_deployment_phase", False):
        self.game_state["phase"] = "deployment"
    else:
        self.game_state["phase"] = "command"
    
    # ... reste du code ...
```

### 8.2. Handler de Déploiement (`engine/phase_handlers/deployment_handler.py`)

```python
class DeploymentHandler:
    """Gère la phase de déploiement pour le training."""
    
    def execute_deployment_action(self, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """Exécute une action de déploiement."""
        from engine.deployment_handlers import is_valid_deployment_hex
        
        unit_id = action.get("unitId")
        col = action.get("col")
        row = action.get("row")
        player = action.get("player")
        
        # Valider la position
        if not is_valid_deployment_hex(self.game_state, col, row, player):
            return False, {"error": "Invalid deployment hex"}
        
        # Ajouter l'unité déployée
        deployed_unit = {
            "unitId": unit_id,
            "col": col,
            "row": row,
            "player": player
        }
        self.game_state.setdefault("deployedUnits", []).append(deployed_unit)
        
        # Vérifier si le déploiement est complet
        deployment_complete = self.is_deployment_complete()
        
        return True, {
            "deployment_complete": deployment_complete,
            "next_phase": "command" if deployment_complete else "deployment"
        }
    
    def get_deployment_observation(self) -> Dict[str, Any]:
        """Retourne l'observation pour l'agent."""
        return {
            "board": self.game_state.get("board"),
            "deployment_zones": self.game_state.get("board", {}).get("deployment_zones"),
            "deployed_units": self.game_state.get("deployedUnits", []),
            "current_deployer": self.game_state.get("currentDeployer", 0)
        }
    
    def is_deployment_complete(self) -> bool:
        """Vérifie si le déploiement est terminé."""
        # Vérifier que toutes les unités sont déployées
        # (logique à implémenter selon les configs de teams)
        return False  # Placeholder
```

### 8.3. Rewards pour le Déploiement

Ajouter des rewards pour encourager des déploiements stratégiques :

```python
def calculate_deployment_reward(
    deployment_state: Dict[str, Any],
    board_config: Dict[str, Any]
) -> float:
    """Calcule la récompense pour un déploiement."""
    reward = 0.0
    
    # Bonus pour couvrir les objectifs
    objectives = board_config.get("objectives", [])
    deployed_units = deployment_state.get("deployedUnits", [])
    
    for objective in objectives:
        objective_hex = objective.get("hex", [])  # Format: [col, row]
        units_on_objective = [
            u for u in deployed_units
            if objective_hex[0] == u.get("col") and objective_hex[1] == u.get("row")
        ]
        if units_on_objective:
            reward += 0.5  # Bonus par objectif couvert
    
    # Bonus pour utiliser le terrain (murs pour couverture)
    wall_hexes = board_config.get("wall_hexes", [])
    units_near_walls = [
        u for u in deployed_units
        if any(abs(w[0] - u.get("col")) <= 1 and abs(w[1] - u.get("row")) <= 1
               for w in wall_hexes)
    ]
    reward += len(units_near_walls) * 0.2
    
    # Malus pour déploiement trop agressif (trop près de l'ennemi)
    # (logique à implémenter)
    
    return reward
```

## 9. Points Techniques à Implémenter

### 9.1. Validation des Zones de Déploiement

- Vérifier que l'hex est dans la zone de déploiement du joueur
- Vérifier que l'hex n'est pas occupé
- Vérifier que l'unité appartient au bon joueur

### 9.2. Historique Undo/Redo

- Limiter à 10 actions
- Stocker : type d'action, unitId, position, timestamp
- Implémenter avec une pile (stack) et un index

### 9.3. Synchronisation PvP

- Polling toutes les 2 secondes
- Utiliser un `sessionId` pour identifier la session
- Gérer les conflits (si deux joueurs déploient en même temps)

### 9.4. Affichage des Zones de Déploiement

- Hexagones rouges pour Attacker
- Hexagones verts pour Defender
- Utiliser le système de rendu existant (PIXI.js)

### 9.5. Gestion des Icônes d'Unités

- Charger les icônes depuis les définitions d'unités
- Afficher dans Army Roster
- Indiquer visuellement les unités déployées (grisées ou avec checkmark)

## 10. Ordre d'Implémentation Recommandé

1. **Phase 1 : Structure de base**
   - Créer les dossiers de configuration
   - Créer les types TypeScript
   - Créer les endpoints backend de base (GET /api/config/*)

2. **Phase 2 : GameSetupPage**
   - Implémenter les menus déroulants
   - Implémenter le chargement des configurations
   - Implémenter la prévisualisation du board
   - Implémenter la gestion des templates/sauvegardes

3. **Phase 3 : DeploymentPage (base)**
   - Créer le layout (board + Army Roster)
   - Implémenter l'affichage des zones de déploiement
   - Implémenter le module Army Roster

4. **Phase 4 : Déploiement click-click**
   - Implémenter la sélection d'unité
   - Implémenter le déploiement sur hex
   - Implémenter la validation

5. **Phase 5 : AttackerDefenderModal (PvE)**
   - Implémenter le popup
   - Implémenter le lancer de dés
   - Implémenter la logique Attacker/Defender

6. **Phase 6 : Historique et Ready**
   - Implémenter Undo/Redo
   - Implémenter le bouton Ready
   - Implémenter la transition vers le jeu

7. **Phase 7 : Synchronisation PvP**
   - Implémenter les endpoints de déploiement
   - Implémenter le polling
   - Gérer les conflits

8. **Phase 8 : Intégration Training**
   - Ajouter la phase de déploiement au training
   - Implémenter le handler de déploiement
   - Ajouter les rewards de déploiement

## 11. Tests à Prévoir

### 11.1. Tests Frontend

- Test de chargement des configurations
- Test de validation de setup complet
- Test de déploiement click-click
- Test d'Undo/Redo
- Test de synchronisation PvP

### 11.2. Tests Backend

- Test de chargement des fichiers de configuration
- Test de validation des zones de déploiement
- Test de gestion des sessions PvP
- Test de détermination Attacker/Defender
- Test des endpoints Undo/Redo

### 11.3. Tests d'Intégration

- Test du flux complet Setup → Deployment → Game
- Test de la synchronisation PvP entre deux clients
- Test de l'intégration avec le training

## 12. Notes de Performance

- **Polling PvP :** Limiter à toutes les 2 secondes pour éviter la surcharge
- **Cache des configurations :** Mettre en cache les configs chargées côté frontend
- **Historique :** Limiter à 10 actions pour éviter la consommation mémoire
- **Rendu des zones :** Utiliser des sprites PIXI.js optimisés pour les hexagones de déploiement
- **Sessions de déploiement :** Utiliser un dictionnaire en mémoire pour le MVP, considérer Redis pour la production
- **Validation :** Toujours valider côté serveur, même si la validation frontend existe
- **Gestion d'erreurs :** Gérer les cas où un joueur se déconnecte pendant le déploiement

## 13. Notes d'Implémentation

### 13.1. Format JSON des Configurations

**Important :** Le format JSON utilise `cols`, `rows`, `hex_radius` directement (pas `boardSize`), `wall_hexes` et `deployment_zones` avec des tuples `[col, row]`, et `objectives` avec `{id, hex: [col, row], type}`.

### 13.2. Compatibilité avec l'Existant

- Les types TypeScript doivent être compatibles avec les types existants dans `frontend/src/types/`
- Les hooks doivent suivre les patterns existants (comme `useEngineAPI`, `useGameState`)
- Les endpoints doivent suivre la structure existante dans `services/api_server.py`

### 13.3. Gestion des Sessions

Pour le MVP, les sessions sont stockées en mémoire dans `deployment_sessions`. Pour la production, considérer :
- Redis pour le stockage des sessions
- Expiration automatique des sessions inactives
- Gestion des déconnexions