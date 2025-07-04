﻿// frontend/src/components/ReplayViewer.tsx
import React, { useState, useEffect, useRef, useCallback } from 'react';
import * as PIXI from "pixi.js-legacy";
import { Unit } from '../types/game';
import { Intercessor } from '../roster/spaceMarine/Intercessor';
import { AssaultIntercessor } from '../roster/spaceMarine/AssaultIntercessor';
import { useGameConfig } from '../hooks/useGameConfig';

// Extended Unit interface for replay viewer with alive property
interface ReplayUnit {
  id: number;
  name: string;
  type: string;
  player: 0 | 1;
  col: number;
  row: number;
  color: number;
  MOVE: number;
  HP_MAX: number;
  CUR_HP: number;
  cur_hp: number;
  RNG_RNG: number;
  RNG_DMG: number;
  CC_DMG: number;
  ICON: string;
  alive: boolean;
  unit_type: string;
}

interface ScenarioConfig {
  board: {
    cols: number;
    rows: number;
    hex_radius: number;
    margin: number;
  };
  colors: {
    [key: string]: number;
  };
  units: Array<{
    id: number;
    unit_type: string;
    player: number;
    col: number;
    row: number;
  }>;
  boardConfig?: {
    cols: number;
    rows: number;
    hex_radius: number;
    margin: number;
    colors: Record<string, string>;
  };
  gameConfig?: {
    game_rules: {
      max_turns: number;
      board_size: [number, number];
    };
    gameplay: {
      phase_order: string[];
    };
  };
}

interface ReplayEvent {
  turn: number;
  phase?: string;
  current_phase?: string;
  action?: any;
  units?: Array<{
    id: number;
    player: number;
    unit_type: string;
    col: number;
    row: number;
    alive: boolean;
    cur_hp: number;
  }>;
  game_state?: {
    turn: number;
    ai_units_alive?: number;
    enemy_units_alive?: number;
    game_over?: boolean;
  };
  acting_unit_idx?: number;
  ai_units_alive?: number;
  enemy_units_alive?: number;
  game_over?: boolean;
  reward?: number;
}

interface ReplayData {
  metadata?: {
    total_reward?: number;
    total_turns?: number;
    timestamp?: string;
    episode_reward?: number;
    final_turn?: number;
    total_events?: number;
  };
  game_summary?: {
    final_reward?: number;
    total_turns?: number;
    game_result?: string;
  };
  events: ReplayEvent[];
  web_compatible?: boolean;
  features?: string[];
}

interface ReplayViewerProps {
  replayFile?: string;
}

// Config-driven unit registry - AI_INSTRUCTIONS.md compliance
const buildConfigUnitRegistry = async () => {
  try {
    // Load unit definitions from config - AI_INSTRUCTIONS.md compliance
    const unitDefinitionsResponse = await fetch('/config/unit_definitions.json');
    if (!unitDefinitionsResponse.ok) {
      throw new Error(`Failed to load unit_definitions.json: ${unitDefinitionsResponse.status}`);
    }
    const unitDefinitions = await unitDefinitionsResponse.json();
    
    const registry: Record<string, typeof Intercessor | typeof AssaultIntercessor> = {};
    
    // TypeScript class mapping
    const classMapping: Record<string, typeof Intercessor | typeof AssaultIntercessor> = {
      'Intercessor': Intercessor,
      'AssaultIntercessor': AssaultIntercessor
    };
    
    // Build registry from config - single canonical name per unit
    Object.entries(unitDefinitions.units || {}).forEach(([configName, definition]: [string, any]) => {
      const UnitClass = classMapping[definition.class_name];
      if (UnitClass) {
        registry[configName] = UnitClass;
        
        // AI_INSTRUCTIONS.md: Validate required properties
        const requiredProps = unitDefinitions.required_properties || ['HP_MAX', 'MOVE', 'RNG_RNG', 'RNG_DMG', 'CC_DMG', 'ICON'];
        requiredProps.forEach((prop: string) => {
          if (UnitClass[prop as keyof typeof UnitClass] === undefined) {
            throw new Error(`AI_INSTRUCTIONS.md violation: Unit ${configName} missing required property: ${prop}`);
          }
        });
      } else {
        console.warn(`⚠️ Unknown unit class: ${definition.class_name} for unit ${configName}`);
      }
    });
    
    console.log(`✅ Loaded ${Object.keys(registry).length} unit types from config`);
    return registry;
  } catch (error) {
    throw new Error(`AI_INSTRUCTIONS.md violation: Failed to load unit registry from config: ${error}`);
  }
};

// Initialize config-driven registry
let UNIT_REGISTRY: Record<string, typeof Intercessor | typeof AssaultIntercessor> = {};

// Load registry on component mount
const initializeUnitRegistry = async () => {
  try {
    UNIT_REGISTRY = await buildConfigUnitRegistry();
  } catch (error) {
    console.error('Failed to initialize unit registry:', error);
    throw error;
  }
};

// Validate unit registry consistency
const validateUnitRegistry = () => {
  const requiredProps = ['HP_MAX', 'MOVE', 'RNG_RNG', 'RNG_DMG', 'CC_DMG', 'ICON'];
  Object.entries(UNIT_REGISTRY).forEach(([unitType, UnitClass]) => {
    requiredProps.forEach(prop => {
      if (UnitClass[prop as keyof typeof UnitClass] === undefined) {
        throw new Error(`Unit ${unitType} missing required property: ${prop}`);
      }
    });
  });
};

// AI_GAME.md behavioral compliance validation
const validatePhaseBehavior = (event: ReplayEvent, phaseConfig: any) => {
  const phase = event.phase || event.current_phase || 'move';
  const actionType = typeof event.action === 'object' && event.action?.type ? event.action.type : undefined;
  
  // AI_GAME.md: Strict phase action validation
  switch(phase) {
    case 'move':
      // AI_GAME.md: "The only available action in this phase is moving"
      if (actionType && !['move', 'skip_move', 'pass_move'].includes(actionType)) {
        throw new Error(`AI_GAME.md violation: Invalid action '${actionType}' in movement phase. Only movement actions allowed.`);
      }
      break;
    case 'shoot':
      // AI_GAME.md: "The only available action in this phase is shooting"
      if (actionType && !['shoot', 'skip_shoot', 'pass_shoot'].includes(actionType)) {
        throw new Error(`AI_GAME.md violation: Invalid action '${actionType}' in shooting phase. Only shooting actions allowed.`);
      }
      break;
    case 'charge':
      // AI_GAME.md: Charge phase validation
      if (actionType && !['charge', 'skip_charge', 'pass_charge'].includes(actionType)) {
        throw new Error(`AI_GAME.md violation: Invalid action '${actionType}' in charge phase. Only charge actions allowed.`);
      }
      break;
    case 'combat':
      // AI_GAME.md: "The only available action in this phase is attacking"  
      if (actionType && !['attack', 'skip_attack', 'pass_attack'].includes(actionType)) {
        throw new Error(`AI_GAME.md violation: Invalid action '${actionType}' in combat phase. Only attack actions allowed.`);
      }
      break;
    default:
      throw new Error(`AI_GAME.md violation: Unknown phase '${phase}'. Must be one of: move, shoot, charge, combat`);
  }
  return true;
};

// Enhanced phase validation according to AI_GAME.md - STRICT CONFIG ONLY
const validatePhaseOrder = (phases: string[], configPhases: string[]) => {
  // AI_INSTRUCTIONS.md: No hardcoded fallbacks allowed
  if (!configPhases || configPhases.length === 0) {
    throw new Error('CRITICAL: Phase order not loaded from config. AI_INSTRUCTIONS.md violation - must use config files only.');
  }
  
  // AI_GAME.md: Exact sequence enforcement
  const expectedSequence = configPhases.join(' → ');
  if (JSON.stringify(phases) !== JSON.stringify(configPhases)) {
    console.error('🚨 Phase order violation of AI_GAME.md rules:', phases);
    console.error('📋 Expected phases:', configPhases);
    console.error('❌ Received phases:', phases);
    throw new Error(`Invalid phase order. AI_GAME.md requires exact sequence: ${expectedSequence}`);
  }
  console.log('✅ Phase order validates against AI_GAME.md');
  return true;
};

// Turn structure validation according to AI_GAME.md
const validateTurnStructure = (event: ReplayEvent, expectedPhase: string, validPhases: string[]) => {
  // Handle different action formats
  const actionType = typeof event.action === 'object' && event.action?.type ? event.action.type : undefined;
  
  if (actionType && validPhases && !validPhases.includes(actionType)) {
    throw new Error(`Invalid action type: ${actionType}. Must match config phases: ${validPhases.join(', ')}`);
  }
  return true;
};

export const ReplayViewer: React.FC<ReplayViewerProps> = ({ 
  replayFile = 'ai/event_log/train_best_game_replay.json' 
}) => {
  // Use same config hook as Board.tsx
  const { boardConfig, loading: configLoading, error: configError } = useGameConfig();
  // All hooks must be at the top level of the component
  const [actionDefinitions, setActionDefinitions] = useState<{[key: string]: {name: string, phase: string, type: string}} | null>(null);
  const [scenario, setScenario] = useState<ScenarioConfig | null>(null);
  // ... other existing useState calls

  // Validate environment setup
  useEffect(() => {
    validateUnitRegistry();
  }, []);

  // Load action definitions from config file
  useEffect(() => {
    const loadActionDefinitions = async () => {
      try {
        const response = await fetch('/config/action_definitions.json');
        if (!response.ok) throw new Error('Failed to load action definitions');
        const data = await response.json();
        setActionDefinitions(data.action_mappings);
      } catch (err) {
        console.error('Error loading action definitions:', err);
        throw new Error('Failed to load action definitions from config');
      }
    };
    loadActionDefinitions();
  }, []);

  // Action to phase mapping loaded from config
  const getActionPhase = (actionId: number): string => {
    if (!actionDefinitions) return "move";
    const actionDef = actionDefinitions[actionId.toString()];
    return actionDef?.phase || "move";
  };

  // Action names loaded from config
  const getActionName = (actionId: number): string => {
    if (!actionDefinitions) return `Action ${actionId}`;
    const actionDef = actionDefinitions[actionId.toString()];
    return actionDef?.name || `Action ${actionId}`;
  };
  const [replayData, setReplayData] = useState<ReplayData | null>(null);
  const [currentStep, setCurrentStep] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [playSpeed, setPlaySpeed] = useState(1000);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [currentUnits, setCurrentUnits] = useState<ReplayUnit[]>([]);
  const [useHtmlFallback, setUseHtmlFallback] = useState(false);
  
  const boardRef = useRef<HTMLDivElement>(null);
  const appRef = useRef<PIXI.Application | null>(null);
  const unitSpritesRef = useRef<Map<number, PIXI.Container>>(new Map());
  const playIntervalRef = useRef<NodeJS.Timeout | null>(null);

  // Get unit stats from config files - NO HARDCODING
  const getUnitStats = useCallback((unitType: string) => {
    const UnitClass = UNIT_REGISTRY[unitType as keyof typeof UNIT_REGISTRY];
    
    if (!UnitClass) {
      throw new Error(`Unknown unit type: ${unitType}. Available types: ${Object.keys(UNIT_REGISTRY).join(', ')}`);
    }

    // Verify all required properties exist
    const requiredProps = ['HP_MAX', 'MOVE', 'RNG_RNG', 'RNG_DMG', 'CC_DMG', 'ICON'];
    for (const prop of requiredProps) {
      if (UnitClass[prop as keyof typeof UnitClass] === undefined) {
        throw new Error(`Missing required property ${prop} in unit class ${unitType}`);
      }
    }

    return {
      HP_MAX: UnitClass.HP_MAX,
      MOVE: UnitClass.MOVE,
      RNG_RNG: UnitClass.RNG_RNG,
      RNG_DMG: UnitClass.RNG_DMG,
      CC_DMG: UnitClass.CC_DMG,
      ICON: UnitClass.ICON
    };
  }, []);

  // Load scenario using unified config system like Board.tsx
  const loadScenario = useCallback(async (): Promise<ScenarioConfig> => {
    try {
      console.log('Loading scenario with unified board config...');

      // Wait for board config to load first
      if (!boardConfig) {
        throw new Error('Board configuration not loaded');
      }

      // Load scenario units from /config/scenario.json
      const scenarioResponse = await fetch('/config/scenario.json');
      if (!scenarioResponse.ok) {
        throw new Error(`Failed to load scenario: ${scenarioResponse.statusText}`);
      }

      const scenarioData = await scenarioResponse.json() as {
        units: ScenarioConfig['units'];
      };

      // Build unified scenario using board config + scenario units
      const unifiedScenario: ScenarioConfig = {
        board: {
          cols: boardConfig.cols,
          rows: boardConfig.rows,
          hex_radius: boardConfig.hex_radius,
          margin: boardConfig.margin
        },
        colors: {
          background: parseInt(boardConfig.colors.background.replace('0x', ''), 16),
          cell_even: parseInt(boardConfig.colors.cell_even.replace('0x', ''), 16),
          cell_odd: parseInt(boardConfig.colors.cell_odd.replace('0x', ''), 16),
          cell_border: parseInt(boardConfig.colors.cell_border.replace('0x', ''), 16),
          player_0: parseInt(boardConfig.colors.player_0.replace('0x', ''), 16),
          player_1: parseInt(boardConfig.colors.player_1.replace('0x', ''), 16),
          hp_full: parseInt(boardConfig.colors.hp_full.replace('0x', ''), 16),
          hp_damaged: parseInt(boardConfig.colors.hp_damaged.replace('0x', ''), 16),
          highlight: parseInt(boardConfig.colors.highlight.replace('0x', ''), 16),
          current_unit: parseInt(boardConfig.colors.current_unit.replace('0x', ''), 16)
        },
        units: scenarioData.units
      };

      console.log('✅ Unified scenario loaded with board config');
      console.log('🎨 DEBUG - Scenario colors:', unifiedScenario.colors);
      console.log('🎨 DEBUG - Background color:', unifiedScenario.colors.background);
      console.log('🎨 DEBUG - Cell even:', unifiedScenario.colors.cell_even);
      console.log('🎨 DEBUG - Cell odd:', unifiedScenario.colors.cell_odd);
      console.log('🎨 DEBUG - Original boardConfig colors:', boardConfig?.colors);
      setScenario(unifiedScenario);
      return unifiedScenario;;

    } catch (err) {
      console.error('Error loading unified scenario:', err);
      throw err;
    }
  }, [boardConfig]);

  // Convert replay events to unit objects
  const convertUnits = useCallback((event: ReplayEvent): ReplayUnit[] => {
    if (!event || !scenario) return [];

    // Handle different event formats
    if (event.units && Array.isArray(event.units)) {
      return event.units.map(unit => ({
        id: unit.id,
        name: unit.unit_type || 'Unknown',
        type: unit.unit_type || 'Unknown',
        player: unit.player as 0 | 1,
        col: unit.col,
        row: unit.row,
        color: unit.player === 0 ? scenario.colors.player_0 : scenario.colors.player_1,
        MOVE: 6,
        HP_MAX: 4,
        CUR_HP: unit.cur_hp || 4,
        cur_hp: unit.cur_hp || 4,
        RNG_RNG: 4,
        RNG_DMG: 1,
        CC_DMG: 1,
        ICON: '●',
        alive: unit.alive !== false && unit.cur_hp > 0,
        unit_type: unit.unit_type
      }));
    }

    // Generate units from scenario if no units in event
    return scenario.units.map((unitDef, index) => {
      const stats = getUnitStats(unitDef.unit_type);
      return {
        id: unitDef.id,
        name: unitDef.unit_type,
        type: unitDef.unit_type,
        player: unitDef.player as 0 | 1,
        col: unitDef.col,
        row: unitDef.row,
        color: unitDef.player === 0 ? scenario.colors.player_0 : scenario.colors.player_1,
        MOVE: stats?.MOVE || 6,
        HP_MAX: stats?.HP_MAX || 4,
        CUR_HP: stats?.HP_MAX || 4,
        cur_hp: stats?.HP_MAX || 4,
        RNG_RNG: stats?.RNG_RNG || 4,
        RNG_DMG: stats?.RNG_DMG || 1,
        CC_DMG: stats?.CC_DMG || 1,
        ICON: stats?.ICON || '●',
        alive: true,
        unit_type: unitDef.unit_type
      };
    });
  }, [scenario, getUnitStats]);

  // PIXI.js hex coordinate calculation
  const getHexCenter = useCallback((col: number, row: number): { x: number, y: number } => {
    if (!scenario) return { x: 0, y: 0 };
    
    const hexWidth = 1.5 * scenario.board.hex_radius;
    const hexHeight = Math.sqrt(3) * scenario.board.hex_radius;
    
    const x = scenario.board.margin + col * hexWidth + scenario.board.hex_radius;
    const y = scenario.board.margin + row * hexHeight + (col % 2) * (hexHeight / 2) + scenario.board.hex_radius;
    
    return { x, y };
  }, [scenario]);

  // Generate hex polygon points for PIXI graphics
  const getHexPolygonPoints = useCallback((radius: number): number[] => {
    const points: number[] = [];
    for (let i = 0; i < 6; i++) {
      const angle = (Math.PI / 3) * i;
      points.push(radius * Math.cos(angle), radius * Math.sin(angle));
    }
    return points;
  }, []);

  // Draw board with PIXI.js Canvas (NO WebGL)
  const drawBoard = useCallback((app: PIXI.Application) => {
    if (!scenario) return;
    
    try {
      // Clear previous board drawings (keep units)
      app.stage.children.filter(child => child.name === 'hex').forEach(hex => {
        app.stage.removeChild(hex);
      });
      
      // Draw hex grid
      for (let row = 0; row < scenario.board.rows; row++) {
        for (let col = 0; col < scenario.board.cols; col++) {
          const center = getHexCenter(col, row);
          const hexGraphics = new PIXI.Graphics();
          hexGraphics.name = 'hex';
          
          // Hex background
          const isEven = (col + row) % 2 === 0;
          hexGraphics.beginFill(isEven ? scenario.colors.cell_even : scenario.colors.cell_odd);
          hexGraphics.lineStyle(1, scenario.colors.cell_border);
          hexGraphics.drawPolygon(getHexPolygonPoints(scenario.board.hex_radius));
          hexGraphics.endFill();
          
          hexGraphics.position.set(center.x, center.y);
          app.stage.addChild(hexGraphics);
        }
      }
      
      console.log(`Board drawn with ${scenario.board.rows * scenario.board.cols} hexes`);
    } catch (drawError) {
      console.error('Error during board drawing:', drawError);
      throw drawError;
    }
  }, [scenario, getHexCenter, getHexPolygonPoints]);

  // Draw units with PIXI.js Canvas
  const drawUnits = useCallback((app: PIXI.Application, units: ReplayUnit[], activeUnitId?: number) => {
    if (!scenario) return;
    
    try {
      // Clear previous unit drawings
      unitSpritesRef.current.forEach(container => {
        app.stage.removeChild(container);
        container.destroy();
      });
      unitSpritesRef.current.clear();
      
      // Draw units
      units.filter(unit => unit.alive !== false).forEach(unit => {
        const center = getHexCenter(unit.col, unit.row);
        const unitContainer = new PIXI.Container();
        unitContainer.name = 'unit';
        
        // Unit background circle
        const unitGraphics = new PIXI.Graphics();
        const isActive = activeUnitId !== undefined && unit.id === activeUnitId;
        const unitColor = isActive ? scenario.colors.current_unit : unit.color;
        
        unitGraphics.beginFill(unitColor);
        unitGraphics.lineStyle(2, 0x000000);
        unitGraphics.drawCircle(0, 0, scenario.board.hex_radius * 0.6);
        unitGraphics.endFill();
        unitContainer.addChild(unitGraphics);
        
        // Unit icon text
        const iconTexture = PIXI.Texture.from(unit.ICON);
        const iconSprite = new PIXI.Sprite(iconTexture);
        iconSprite.anchor.set(0.5);
        // Scale sprite to fit inside the hex cell
        const maxDim = Math.max(iconTexture.width, iconTexture.height);
        const scale = (scenario.board.hex_radius * 1.2) / maxDim;
        iconSprite.scale.set(scale, scale);
        unitContainer.addChild(iconSprite);
        unitContainer.addChild(iconSprite);
        // Draw HP bar (background + green foreground)
        
        
        // HP text with null safety
        const currentHP = unit.CUR_HP ?? unit.HP_MAX;
        const hpText = new PIXI.Text(`${currentHP}/${unit.HP_MAX}`, {
          fontFamily: 'Arial',
          fontSize: 12,
          fill: currentHP <= unit.HP_MAX * 0.3 ? scenario.colors.hp_damaged : scenario.colors.hp_full,
          align: 'center'
        });
        hpText.anchor.set(0.5);
        hpText.position.set(0, scenario.board.hex_radius * 0.8);
        unitContainer.addChild(hpText);
        
        // Position the unit container
        unitContainer.position.set(center.x, center.y);
        app.stage.addChild(unitContainer);
        
        // Store reference for future updates
        unitSpritesRef.current.set(unit.id, unitContainer);
      });
      
      console.log(`Drew ${units.filter(u => u.alive !== false).length} units on board`);
    } catch (drawError) {
      console.error('Error during unit drawing:', drawError);
      throw drawError;
    }
  }, [scenario, getHexCenter]);

  // Initialize PIXI application with Canvas renderer (no WebGL)
  useEffect(() => {
    if (!boardRef.current || !scenario || !replayData || useHtmlFallback) return;

    try {
      // Always use Canvas renderer (no WebGL as per instructions)
      const app = new PIXI.Application({
        width: scenario.board.cols * scenario.board.hex_radius * 1.5 + scenario.board.margin * 2,
        height: scenario.board.rows * scenario.board.hex_radius * 1.75 + scenario.board.margin * 2,
        backgroundColor: scenario.colors.background,
        antialias: true,
        forceCanvas: true, // Always use Canvas renderer, never WebGL
      });

      boardRef.current.appendChild(app.view as HTMLCanvasElement);
      appRef.current = app;

      // Draw initial board
      drawBoard(app);
      
      // Draw initial units
      if (replayData.events[0]) {
        const initialUnits = convertUnits(replayData.events[0]);
        setCurrentUnits(initialUnits);
        drawUnits(app, initialUnits);
      }

    } catch (err) {
      console.error('Error initializing PIXI Canvas:', err);
      console.log('PIXI Canvas failed, using HTML fallback...');
      setUseHtmlFallback(true);
      setError(null); // Clear error, we have HTML fallback
    }

    return () => {
      if (appRef.current) {
        appRef.current.destroy(true);
        appRef.current = null;
      }
    };
  }, [scenario, replayData, convertUnits, drawBoard, drawUnits, useHtmlFallback]);

  // HTML Fallback Renderer using simplified HTML grid
  const renderHTMLBoard = useCallback(() => {
    if (!scenario || !currentUnits) return null;

    return (
      <div className="relative bg-gray-800 border border-gray-600 rounded p-4">
        <div className="text-center mb-2 text-yellow-400 text-sm">
          HTML Fallback Mode (PIXI Canvas unavailable)
        </div>
        <div 
          className="relative bg-gray-900 border border-gray-500 rounded mx-auto"
          style={{
            width: `${scenario.board.cols * 40}px`,
            height: `${scenario.board.rows * 35}px`,
            maxWidth: '100%'
          }}
        >
          {/* Grid cells */}
          {Array.from({ length: scenario.board.rows }, (_, row) =>
            Array.from({ length: scenario.board.cols }, (_, col) => (
              <div
                key={`${col}-${row}`}
                className="absolute border border-gray-600 opacity-30"
                style={{
                  left: `${(col / scenario.board.cols) * 100}%`,
                  top: `${(row / scenario.board.rows) * 100}%`,
                  width: `${100 / scenario.board.cols}%`,
                  height: `${100 / scenario.board.rows}%`
                }}
              />
            ))
          )}

          {/* Units */}
          {currentUnits.map(unit => (
            unit.alive !== false && (
              <div
                key={unit.id}
                className="absolute rounded-full border-2 border-white flex items-center justify-center text-xs font-bold text-white shadow-lg"
                style={{
                  left: `${(unit.col / scenario.board.cols) * 100}%`,
                  top: `${(unit.row / scenario.board.rows) * 100}%`,
                  width: '30px',
                  height: '30px',
                  backgroundColor: unit.player === 0 ? 
                    `#${scenario.colors.player_0.toString(16).padStart(6, '0')}` : 
                    `#${scenario.colors.player_1.toString(16).padStart(6, '0')}`,
                  transform: 'translate(-50%, -50%)'
                }}
                title={`${unit.name} (${unit.CUR_HP ?? unit.HP_MAX}/${unit.HP_MAX} HP)`}
              >
                {unit.ICON.charAt(0)}
              </div>
            )
          ))}
        </div>
      </div>
    );
  }, [scenario, currentUnits]);

  // Update display when step changes
  useEffect(() => {
    if (!replayData || !scenario || currentStep >= replayData.events.length) return;

    const currentEvent = replayData.events[currentStep];
    if (!currentEvent) return;

    const units = convertUnits(currentEvent);
    setCurrentUnits(units);

    if (!useHtmlFallback && appRef.current) {
      try {
        drawBoard(appRef.current);
        drawUnits(appRef.current, units, currentEvent.acting_unit_idx);
      } catch (err) {
        console.error('Error updating display:', err);
        console.log('Switching to HTML fallback due to display error');
        setUseHtmlFallback(true);
      }
    }
  }, [currentStep, replayData, scenario, useHtmlFallback, convertUnits, drawBoard, drawUnits]);

  // Load scenario and replay data
  useEffect(() => {
    const loadData = async () => {
      try {
        setLoading(true);
        setError(null);

        // Wait for config to load first
        if (configLoading) {
          console.log('⏳ Waiting for configuration to load...');
          return;
        }

        if (configError) {
          throw new Error(`Configuration error: ${configError}`);
        }

        if (!boardConfig) {
          throw new Error('Board configuration not available');
        }
        
        console.log('Loading scenario...');
        await loadScenario();
        
        console.log(`Loading replay from /${replayFile}...`);
        const response = await fetch(`/${replayFile}`);
        if (!response.ok) {
          throw new Error(`Failed to load replay file: ${response.statusText}`);
        }
        
        const data = await response.json();
        
        // Validate JSON structure
        if (!data.events || !Array.isArray(data.events)) {
          throw new Error('Invalid replay data: missing events array');
        }
        
        console.log('Replay data loaded:', data);
        setReplayData(data);
        setCurrentStep(0);
        
      } catch (err) {
        console.error('Error loading data:', err);
        setError(err instanceof Error ? err.message : 'Unknown error');
      } finally {
        setLoading(false);
      }
    };

    loadData();
  }, [replayFile, loadScenario, boardConfig, configLoading, configError]);

  // Auto-play functionality
  useEffect(() => {
    if (isPlaying && replayData && currentStep < replayData.events.length - 1) {
      playIntervalRef.current = setTimeout(() => {
        setCurrentStep((prev: number) => prev + 1);
      }, playSpeed);
    } else {
      setIsPlaying(false);
    }

    return () => {
      if (playIntervalRef.current) {
        clearTimeout(playIntervalRef.current);
      }
    };
  }, [isPlaying, currentStep, replayData, playSpeed]);

  // Control functions
  const play = () => setIsPlaying(true);
  const pause = () => setIsPlaying(false);
  const reset = () => {
    setIsPlaying(false);
    setCurrentStep(0);
  };
  const nextStep = () => {
    if (replayData && currentStep < replayData.events.length - 1) {
      setCurrentStep((prev: number) => prev + 1);
    }
  };
  const prevStep = () => {
    if (currentStep > 0) {
      setCurrentStep((prev: number) => prev - 1);
    }
  };

  // Force HTML fallback function
  const forceHtmlFallback = () => {
    console.log('Forcing HTML fallback mode...');
    setUseHtmlFallback(true);
    if (appRef.current) {
      appRef.current.destroy(true);
      appRef.current = null;
    }
  };

  // Retry PIXI function
  const retryPixi = () => {
    console.log('Retrying PIXI mode...');
    setUseHtmlFallback(false);
    setError(null);
    window.location.reload();
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-900 text-white">
        <div className="text-center">
          <div className="animate-spin rounded-full h-16 w-16 border-b-2 border-blue-500 mx-auto mb-4"></div>
          <div className="text-lg">Loading replay...</div>
          <div className="text-sm text-gray-400 mt-2">
            Loading scenario and replay data...
          </div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-900 text-white">
        <div className="text-center max-w-md">
          <div className="text-red-500 text-xl mb-4">⚠️ Error</div>
          <div className="text-red-400 mb-4">{error}</div>
          <div className="space-x-4">
            <button 
              onClick={forceHtmlFallback}
              className="px-4 py-2 bg-yellow-600 hover:bg-yellow-700 rounded transition-colors"
            >
              Use HTML Fallback
            </button>
            <button 
              onClick={() => window.location.reload()}
              className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded transition-colors"
            >
              Refresh Page
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (!replayData || !scenario) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-900 text-white">
        <div className="text-red-500">
          Missing required data: {!replayData ? 'replay data' : ''} {!scenario ? 'scenario configuration' : ''}
        </div>
      </div>
    );
  }

  if (!replayData.events || replayData.events.length === 0) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-900 text-white">
        <div className="text-red-500">No replay events found in data</div>
      </div>
    );
  }

  // Get current event info for display
  const currentEvent = replayData.events[currentStep];
  const currentAction = typeof currentEvent?.action === 'number' ? currentEvent.action : currentEvent?.action?.action_id ?? 0;
  const currentPhase = getActionPhase(currentAction);
  const metadata = replayData.metadata || replayData.game_summary || {};
  const totalReward = (metadata as any)?.episode_reward ?? (metadata as any)?.final_reward ?? (metadata as any)?.total_reward ?? 0;
  const totalTurns = (metadata as any)?.final_turn ?? (metadata as any)?.total_turns ?? 0;

  // Calculate phase progress for visual indicators
  const currentTurn = currentEvent?.turn ?? 0;
  const phases = ["move", "shoot", "charge", "combat"];
  const currentPhaseIndex = phases.indexOf(currentPhase);

  return (
    <div className="min-h-screen bg-gray-900 text-white p-4">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="mb-6">
          <h1 className="text-3xl font-bold mb-2">WH40K Game Replay Viewer</h1>
          <div className="text-gray-400 flex flex-wrap gap-4">
            <span>{useHtmlFallback ? '🔄 HTML Fallback Mode' : '🎮 PIXI.js Canvas Mode'}</span>
            <span>Step {currentStep + 1} of {replayData.events.length}</span>
            <span>Turn: {currentTurn}</span>
            <span>Phase: <span className="text-blue-400 font-semibold">{currentPhase.toUpperCase()}</span></span>
          </div>
        </div>

        {/* Renderer Toggle Controls */}
        <div className="mb-4 flex flex-wrap gap-2">
          {useHtmlFallback ? (
            <button 
              onClick={retryPixi}
              className="px-3 py-1 bg-blue-600 hover:bg-blue-700 rounded text-sm transition-colors"
            >
              🎮 Try PIXI.js Mode
            </button>
          ) : (
            <button 
              onClick={forceHtmlFallback}
              className="px-3 py-1 bg-yellow-600 hover:bg-yellow-700 rounded text-sm transition-colors"
            >
              🔄 Force HTML Mode
            </button>
          )}
          {replayData.web_compatible && (
            <div className="px-3 py-1 bg-green-900 text-green-200 rounded text-sm">
              ✅ Web Compatible
            </div>
          )}
        </div>

        {/* Phase Progress Indicator - AI_GAME.md compliance */}
        <div className="mb-6 bg-gray-800 p-4 rounded-lg">
          <h3 className="text-lg font-semibold mb-3">Turn {currentTurn} - Phase Progress</h3>
          <div className="flex space-x-2">
            {phases.map((phase, index) => {
              const isActive = index === currentPhaseIndex;
              const isCompleted = index < currentPhaseIndex;
              
              return (
                <div
                  key={phase}
                  className={`px-3 py-2 rounded text-sm font-medium transition-colors ${
                    isActive 
                      ? 'bg-blue-600 text-white' 
                      : isCompleted 
                        ? 'bg-green-700 text-green-200' 
                        : 'bg-gray-700 text-gray-400'
                  }`}
                >
                  {phase.toUpperCase()}
                </div>
              );
            })}
          </div>
        </div>

        {/* Game Board */}
        <div className="flex flex-col lg:flex-row gap-6">
          <div className="flex-1">
            {useHtmlFallback ? (
              <div className="p-4 bg-gray-800 rounded-lg">
                {renderHTMLBoard()}
              </div>
            ) : (
              <div className="bg-gray-800 p-4 rounded-lg">
                <div className="mb-2 text-sm text-green-400">
                  🎮 PIXI.js Canvas Renderer Active
                </div>
                <div 
                  ref={boardRef} 
                  className="border border-gray-700 rounded-lg overflow-hidden"
                  style={{ minHeight: '400px' }}
                />
              </div>
            )}
          </div>

          {/* Controls Panel */}
          <div className="lg:w-80 space-y-4">
            {/* Playback Controls */}
            <div className="bg-gray-800 p-4 rounded-lg">
              <h3 className="text-lg font-semibold mb-3">Playback Controls</h3>
              
              <div className="flex gap-2 mb-4">
                <button
                  onClick={reset}
                  className="px-3 py-2 bg-gray-600 hover:bg-gray-500 rounded transition-colors"
                  title="Reset to beginning"
                >
                  ⏮️
                </button>
                <button
                  onClick={prevStep}
                  disabled={currentStep === 0}
                  className="px-3 py-2 bg-gray-600 hover:bg-gray-500 rounded transition-colors disabled:opacity-50"
                  title="Previous step"
                >
                  ⏪
                </button>
                <button
                  onClick={isPlaying ? pause : play}
                  disabled={currentStep >= replayData.events.length - 1}
                  className={`px-4 py-2 rounded transition-colors ${
                    isPlaying 
                      ? 'bg-red-600 hover:bg-red-500' 
                      : 'bg-green-600 hover:bg-green-500'
                  } disabled:opacity-50`}
                  title={isPlaying ? 'Pause' : 'Play'}
                >
                  {isPlaying ? '⏸️ Pause' : '▶️ Play'}
                </button>
                <button
                  onClick={nextStep}
                  disabled={currentStep >= replayData.events.length - 1}
                  className="px-3 py-2 bg-gray-600 hover:bg-gray-500 rounded transition-colors disabled:opacity-50"
                  title="Next step"
                >
                  ⏩
                </button>
              </div>

              {/* Progress Bar */}
              <div className="w-full bg-gray-700 rounded-full h-3 mb-4">
                <div 
                  className="bg-blue-600 h-3 rounded-full transition-all duration-300"
                  style={{ width: `${((currentStep + 1) / replayData.events.length) * 100}%` }}
                />
              </div>

              {/* Speed Control */}
              <div className="flex items-center justify-between">
                <span className="text-sm">Speed:</span>
                <div className="flex items-center space-x-2">
                  <input
                    type="range"
                    min="100"
                    max="3000"
                    step="100"
                    value={playSpeed}
                    onChange={(e) => setPlaySpeed(Number(e.target.value))}
                    className="w-20"
                  />
                  <span className="text-sm w-8">{((3000 - playSpeed + 100) / 100).toFixed(1)}x</span>
                </div>
              </div>
            </div>

            {/* Current Event Info */}
            <div className="bg-gray-800 p-4 rounded-lg">
              <h3 className="text-lg font-semibold mb-3">Current Event</h3>
              <div className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-gray-400">Turn:</span>
                  <span>{currentEvent?.turn ?? 'N/A'}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400">Action:</span>
                  <span>{getActionName(currentAction)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400">Phase:</span>
                  <span className={`px-2 py-1 rounded text-xs ${
                    currentPhase === 'move' ? 'bg-blue-900' :
                    currentPhase === 'shoot' ? 'bg-red-900' :
                    currentPhase === 'charge' ? 'bg-orange-900' :
                    currentPhase === 'combat' ? 'bg-purple-900' : 'bg-gray-900'
                  }`}>
                    {currentPhase.toUpperCase()}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400">Acting Unit:</span>
                  <span>{currentEvent?.acting_unit_idx ?? 'None'}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400">Reward:</span>
                  <span className={currentEvent?.reward ? 
                    (currentEvent.reward > 0 ? 'text-green-400' : 'text-red-400') : ''
                  }>
                    {currentEvent?.reward?.toFixed(2) ?? '0.00'}
                  </span>
                </div>
              </div>
            </div>

            {/* Game Summary */}
            <div className="bg-gray-800 p-4 rounded-lg">
              <h3 className="text-lg font-semibold mb-3">Game Summary</h3>
              <div className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-gray-400">Total Reward:</span>
                  <span className={totalReward >= 0 ? 'text-green-400' : 'text-red-400'}>
                    {typeof totalReward === 'number' ? totalReward.toFixed(2) : '0.00'}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400">Total Turns:</span>
                  <span>{totalTurns || 'N/A'}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400">Events:</span>
                  <span>{replayData.events.length}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400">AI Units:</span>
                  <span>{currentEvent?.ai_units_alive ?? currentUnits.filter(u => u.player === 1).length ?? 'N/A'}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400">Enemy Units:</span>
                  <span>{currentEvent?.enemy_units_alive ?? currentUnits.filter(u => u.player === 0).length ?? 'N/A'}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400">Game Over:</span>
                  <span className={currentEvent?.game_over ? 'text-red-400' : 'text-green-400'}>
                    {currentEvent?.game_over ? 'Yes' : 'No'}
                  </span>
                </div>
                {(metadata as any)?.timestamp && (
                  <div className="flex justify-between">
                    <span className="text-gray-400">Recorded:</span>
                    <span className="text-xs">{new Date((metadata as any).timestamp).toLocaleDateString()}</span>
                  </div>
                )}
                {replayData.web_compatible && (
                  <div className="mt-2 p-2 bg-green-900 rounded text-center">
                    <span className="text-green-200 text-xs">✅ Web Compatible</span>
                  </div>
                )}
              </div>
            </div>

            {/* Unit Information */}
            <div className="bg-gray-800 p-4 rounded-lg">
              <h3 className="text-lg font-semibold mb-3">Unit Information</h3>
              <div className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-gray-400">Total Units:</span>
                  <span>{currentUnits.length}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400">Alive Units:</span>
                  <span className="text-green-400">{currentUnits.filter(u => u.alive !== false).length}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400">Dead Units:</span>
                  <span className="text-red-400">{currentUnits.filter(u => u.alive === false).length}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400">Player 0 Units:</span>
                  <span className="text-blue-400">{currentUnits.filter(u => u.player === 0 && u.alive !== false).length}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400">Player 1 Units:</span>
                  <span className="text-red-400">{currentUnits.filter(u => u.player === 1 && u.alive !== false).length}</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Action Legend */}
          <div className="mt-6 bg-gray-800 p-4 rounded-lg">
            <h3 className="text-lg font-semibold mb-3">Action Legend</h3>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-sm">
              {actionDefinitions ? Object.entries(actionDefinitions).map(([id, actionDef]) => (
                <div 
                  key={id} 
                  className={`p-2 rounded ${currentAction === parseInt(id) ?
                    'bg-blue-600 text-white' 
                    : 'bg-gray-700 text-gray-400'
                  }`}
                >
                  <span className="text-gray-400">{id}:</span> {actionDef.name}
                </div>
              )) : (
                <div className="text-gray-500">Loading actions...</div>
              )}
            </div>
          </div>

        {/* Technical Info */}
        <div className="mt-6 bg-gray-800 p-4 rounded-lg">
          <h3 className="text-lg font-semibold mb-3">Technical Info</h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            <div>
              <span className="text-gray-400">Renderer:</span><br/>
              <span>{useHtmlFallback ? 'HTML Fallback' : 'PIXI.js Canvas'}</span>
            </div>
            <div>
              <span className="text-gray-400">Canvas Active:</span><br/>
              <span className={appRef.current ? 'text-green-400' : 'text-red-400'}>
                {appRef.current ? 'Yes' : 'No'}
              </span>
            </div>
            <div>
              <span className="text-gray-400">Units Loaded:</span><br/>
              <span>{currentUnits.length}</span>
            </div>
            <div>
              <span className="text-gray-400">Features:</span><br/>
              <span>{replayData.features?.join(', ') || 'None'}</span>
            </div>
            <div>
              <span className="text-gray-400">Board Size:</span><br/>
              <span>{scenario.board.cols}×{scenario.board.rows}</span>
            </div>
            <div>
              <span className="text-gray-400">Hex Radius:</span><br/>
              <span>{scenario.board.hex_radius}px</span>
            </div>
            <div>
              <span className="text-gray-400">File Path:</span><br/>
              <span className="text-xs">{replayFile}</span>
            </div>
            <div>
              <span className="text-gray-400">Registry Valid:</span><br/>
              <span className="text-green-400">✅ Validated</span>
            </div>
          </div>
        </div>

        {/* Debug Info (Development Only) */}
        {process.env.NODE_ENV === 'development' && (
          <div className="mt-6 bg-gray-800 p-4 rounded-lg">
            <h3 className="text-lg font-semibold mb-3">Debug Info</h3>
            <div className="text-xs font-mono bg-gray-900 p-3 rounded overflow-auto max-h-40">
              <div className="mb-2">Current Event:</div>
              <pre>{JSON.stringify(currentEvent, null, 2)}</pre>
              <div className="mt-4 mb-2">Current Units Sample:</div>
              <pre>{JSON.stringify(currentUnits.slice(0, 2), null, 2)}</pre>
              <div className="mt-4 mb-2">Scenario Config:</div>
              <pre>{JSON.stringify(scenario?.board, null, 2)}</pre>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

// Default export for the replay viewer
export default ReplayViewer;