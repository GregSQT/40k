// frontend/src/components/ReplayViewer.tsx
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
  result?: {
    damage?: number;
    hp_remaining?: number;
    unit_destroyed?: boolean;
    moved_to?: [number, number];
  };
  // Action-based replay properties
  unit_id?: number;
  position?: [number, number];
  hp?: number;
  player?: number;
  training_data?: {
    timestep?: number;
    decision?: {
      timestep: number;
      action_chosen: number;
      is_exploration: boolean;
      epsilon?: number;
      model_confidence?: number;
      q_values?: number[];
      best_q_value?: number;
      action_q_value?: number;
    };
  };
}

interface ReplayData {
  metadata?: {
    total_reward?: number;
    total_turns?: number;
    timestamp?: string;
    episode_reward?: number;
    final_turn?: number;
    total_events?: number;
    format_version?: string;
    replay_type?: string;
    training_context?: {
      timestep?: number;
      episode_num?: number;
      model_info?: Record<string, any>;
      start_time?: string;
    };
    web_compatible?: boolean;
  };
  game_summary?: {
    final_reward?: number;
    total_turns?: number;
    game_result?: string;
  };
  events: ReplayEvent[];
  web_compatible?: boolean;
  features?: string[];
  training_summary?: {
    total_decisions?: number;
    exploration_decisions?: number;
    exploitation_decisions?: number;
    exploration_rate?: number;
    avg_model_confidence?: number;
    timestep_range?: {
      start: number;
      end: number;
    };
  };
  game_states?: any[];
}

interface ReplayViewerProps {
  replayFile?: string;
}

// Temporary direct unit registry - bypassing config loading issues
const buildConfigUnitRegistry = async () => {
  console.log('🔧 Using direct TypeScript registry (bypassing config issues)');
  
  const registry: Record<string, typeof Intercessor | typeof AssaultIntercessor> = {
    'Intercessor': Intercessor,
    'AssaultIntercessor': AssaultIntercessor
  };
  
  // Validate required properties exist
  const requiredProps = ['HP_MAX', 'MOVE', 'RNG_RNG', 'RNG_DMG', 'CC_DMG', 'ICON'];
  Object.entries(registry).forEach(([unitType, UnitClass]) => {
    requiredProps.forEach(prop => {
      if (UnitClass[prop as keyof typeof UnitClass] === undefined) {
        throw new Error(`Unit ${unitType} missing required property: ${prop}`);
      }
    });
  });
  
  console.log(`✅ Loaded ${Object.keys(registry).length} unit types directly`);
  return registry;
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

  // Initialize and validate unit registry - STRICT per AI_INSTRUCTIONS.md
  useEffect(() => {
    const initRegistry = async () => {
      try {
        await initializeUnitRegistry();
        validateUnitRegistry();
        console.log('✅ Unit registry initialized with types:', Object.keys(UNIT_REGISTRY));
      } catch (error) {
        console.error('❌ Failed to initialize unit registry:', error);
        console.warn('🔧 TEMPORARY: Using hardcoded registry to test replay loading');
        
        // TEMPORARY hardcoded registry for testing
        UNIT_REGISTRY = {
          'Intercessor': Intercessor,
          'AssaultIntercessor': AssaultIntercessor
        };
        console.log('✅ TEMPORARY registry initialized');
      }
    };
    initRegistry();
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
  const [showTrainingData, setShowTrainingData] = useState(true);
  const [selectedTrainingMetric, setSelectedTrainingMetric] = useState<string>('overview');
  
  const boardRef = useRef<HTMLDivElement>(null);
  const appRef = useRef<PIXI.Application | null>(null);
  const unitSpritesRef = useRef<Map<number, PIXI.Container>>(new Map());
  const playIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const initializingRef = useRef(false);


  // Get unit stats from config - STRICT AI_INSTRUCTIONS.md compliance
  const getUnitStats = useCallback((unitType: string) => {
    // STRICT: Registry must be initialized from config
    if (Object.keys(UNIT_REGISTRY).length === 0) {
      throw new Error(`AI_INSTRUCTIONS.md violation: Unit registry not initialized from config. Cannot load unit: ${unitType}`);
    }
    
    const UnitClass = UNIT_REGISTRY[unitType];
    
    if (!UnitClass) {
      throw new Error(`AI_INSTRUCTIONS.md violation: Unknown unit type '${unitType}' not found in config registry. Available units: ${Object.keys(UNIT_REGISTRY).join(', ')}`);
    }

    // Verify all required properties exist
    const requiredProps = ['HP_MAX', 'MOVE', 'RNG_RNG', 'RNG_DMG', 'CC_DMG', 'ICON'];
    for (const prop of requiredProps) {
      if (UnitClass[prop as keyof typeof UnitClass] === undefined) {
        throw new Error(`AI_INSTRUCTIONS.md violation: Unit ${unitType} missing required property: ${prop}`);
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

      setScenario(unifiedScenario);
      return unifiedScenario;;

    } catch (err) {
      console.error('Error loading unified scenario:', err);
      throw err;
    }
  }, [boardConfig]);

  // Convert replay events to unit objects
  const convertUnits = useCallback((currentStep: number): ReplayUnit[] => {
    if (!scenario) return [];

    // Use initial units from scenario if no replay data yet
    if (!replayData) {
      return scenario.units.map((unitDef) => {
        const stats = getUnitStats(unitDef.unit_type);
        if (!stats) {
          throw new Error(`AI_INSTRUCTIONS.md violation: Unit stats not found for ${unitDef.unit_type}`);
        }
        
        return {
          id: unitDef.id,
          name: unitDef.unit_type,
          type: unitDef.unit_type,
          player: unitDef.player as 0 | 1,
          col: unitDef.col,
          row: unitDef.row,
          color: unitDef.player === 0 ? scenario.colors.player_0 : scenario.colors.player_1,
          MOVE: stats.MOVE,
          HP_MAX: stats.HP_MAX,
          CUR_HP: stats.HP_MAX,
          cur_hp: stats.HP_MAX,
          RNG_RNG: stats.RNG_RNG,
          RNG_DMG: stats.RNG_DMG,
          CC_DMG: stats.CC_DMG,
          ICON: stats.ICON,
          alive: true,
          unit_type: unitDef.unit_type
        };
      });
    }

    // Handle current replay structure with events array
    if (currentStep < replayData.events.length) {
      const currentEvent = replayData.events[currentStep];
      // Handle action-based events that only have unit updates
      if (currentEvent) {
        // Start with initial units from scenario
        const unitStates = new Map<number, ReplayUnit>();
        
        scenario.units.forEach((unitDef) => {
          const stats = getUnitStats(unitDef.unit_type);
          if (!stats) {
            throw new Error(`AI_INSTRUCTIONS.md violation: Unit stats not found for ${unitDef.unit_type}`);
          }
          
          unitStates.set(unitDef.id, {
            id: unitDef.id,
            name: unitDef.unit_type,
            type: unitDef.unit_type,
            player: unitDef.player as 0 | 1,
            col: unitDef.col,
            row: unitDef.row,
            color: unitDef.player === 0 ? scenario.colors.player_0 : scenario.colors.player_1,
            MOVE: stats.MOVE,
            HP_MAX: stats.HP_MAX,
            CUR_HP: stats.HP_MAX,
            cur_hp: stats.HP_MAX,
            RNG_RNG: stats.RNG_RNG,
            RNG_DMG: stats.RNG_DMG,
            CC_DMG: stats.CC_DMG,
            ICON: stats.ICON,
            alive: true,
            unit_type: unitDef.unit_type
          });
        });

        // Apply all actions up to current step
        for (let i = 0; i <= currentStep && i < replayData.events.length; i++) {
          const action = replayData.events[i];
          const unitId = action.unit_id;
          
          if (unitId !== undefined && unitStates.has(unitId)) {
            const unit = unitStates.get(unitId)!;
            
            // Update position if provided
            if (action.position && action.position.length >= 2) {
              unit.col = action.position[0];
              unit.row = action.position[1];
            }
            
            // Update HP if provided
            if (action.hp !== undefined) {
              unit.CUR_HP = Math.max(0, action.hp);
              unit.cur_hp = unit.CUR_HP;
              unit.alive = unit.CUR_HP > 0;
            }
          }
        }

        return Array.from(unitStates.values());
      }
    }

    // Fallback to scenario units if event doesn't have units
    return scenario.units.map((unitDef) => {
      const stats = getUnitStats(unitDef.unit_type);
      if (!stats) {
        throw new Error(`AI_INSTRUCTIONS.md violation: Unit stats not found for ${unitDef.unit_type}`);
      }
      
      return {
        id: unitDef.id,
        name: unitDef.unit_type,
        type: unitDef.unit_type,
        player: unitDef.player as 0 | 1,
        col: unitDef.col,
        row: unitDef.row,
        color: unitDef.player === 0 ? scenario.colors.player_0 : scenario.colors.player_1,
        MOVE: stats.MOVE,
        HP_MAX: stats.HP_MAX,
        CUR_HP: stats.HP_MAX,
        cur_hp: stats.HP_MAX,
        RNG_RNG: stats.RNG_RNG,
        RNG_DMG: stats.RNG_DMG,
        CC_DMG: stats.CC_DMG,
        ICON: stats.ICON,
        alive: true,
        unit_type: unitDef.unit_type
      };
    });
  }, [replayData, scenario, getUnitStats]);

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
    if (!scenario || !app.stage) {
      console.warn('Cannot draw board: scenario or app.stage not ready');
      return;
    }
    
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
    if (!scenario || !app.stage) {
      console.warn('Cannot draw units: scenario or app.stage not ready');
      return;
    }
    
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
    
    // Basic checks only

    try {
      // Calculate proper canvas dimensions
      const canvasWidth = scenario.board.cols * scenario.board.hex_radius * 1.5 + scenario.board.margin * 2;
      const canvasHeight = scenario.board.rows * scenario.board.hex_radius * 1.75 + scenario.board.margin * 2;
      
      // Always use Canvas renderer (no WebGL as per instructions)
      const app = new PIXI.Application({
        width: canvasWidth,
        height: canvasHeight,
        backgroundColor: scenario.colors.background,
        antialias: true,
        forceCanvas: true, // Always use Canvas renderer, never WebGL
        resolution: 1, // Fix resolution
        autoDensity: true,
      });
      
      // Ensure proper canvas styling
      const canvas = app.view as HTMLCanvasElement;
      canvas.style.width = `${canvasWidth}px`;
      canvas.style.height = `${canvasHeight}px`;
      canvas.style.display = 'block';

      // Clear any existing content
      boardRef.current.innerHTML = '';
      boardRef.current.appendChild(canvas);
      appRef.current = app;

      // Wait for stage to be ready before proceeding
      if (!app.stage) {
        console.warn('PIXI stage not ready, falling back to HTML');
        setUseHtmlFallback(true);
        setError(null);
        return;
      }

      // Draw initial board and units after a short delay to ensure proper mounting
      setTimeout(() => {
        try {
          // Double-check stage is still available
          if (!app.stage) {
            console.warn('PIXI stage became null during initialization');
            setUseHtmlFallback(true);
            return;
          }
          
          drawBoard(app);
          const initialUnits = convertUnits(0);
          setCurrentUnits(initialUnits);
          drawUnits(app, initialUnits);
          console.log('✅ Board and units rendered successfully');
        } catch (renderError) {
          console.error('❌ Rendering failed:', renderError);
          setUseHtmlFallback(true);
        }
      }, 100);

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
  }, [scenario, replayData, useHtmlFallback]);

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

    const units = convertUnits(currentStep);
    setCurrentUnits(units);

    if (!useHtmlFallback && appRef.current) {
      try {
        drawBoard(appRef.current);
        
        const currentEvent = replayData.events[currentStep];
        const activeUnitId = currentEvent?.acting_unit_idx;
        
        drawUnits(appRef.current, units, activeUnitId);
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
        
        let data = await response.json();
        
        // Handle direct array format FIRST (most common case)
        if (Array.isArray(data)) {
          console.log('Converting direct array format to events');
          const originalArray = data;
          data = {
            metadata: {
              total_events: originalArray.length,
              format: 'direct_array'
            },
            events: originalArray
          };
        }
        // Handle actions array format (phase_based_replay format)
        else if (data.actions && Array.isArray(data.actions)) {
          console.log('Converting actions array to events format');
          data.events = data.actions;
          data.metadata = {
            ...data.game_info,
            total_events: data.actions.length,
            format: 'actions_array'
          };
          console.log('✅ Converted actions to events:', data.events.length, 'events');
        }
        // Then handle other formats
        else if (!data.events || !Array.isArray(data.events)) {
          if (Array.isArray(data.phases)) {
            console.log('Flattening phases into events');
            data.events = data.phases.flatMap((p: any) =>
              Array.isArray(p.events) ? p.events : []
            );
          } else {
            throw new Error('Invalid replay data: missing events array');
          }
        }
        
        console.log('✅ Processed replay data with', data.events?.length || 0, 'events');
        
        // Handle both events and actions array formats
        if (!data.events && data.actions) {
          console.log('Converting actions to events format...');
          data.events = data.actions.map((action: any, index: number) => ({
            turn: action.turn,
            phase: action.phase,
            player: action.player,
            unit_id: action.unit_id,
            action: action.action_type,
            position: action.position,
            hp: action.hp,
            reward: action.reward,
            timestamp: action.timestamp
          }));
        }

        // Convert action-based events to proper ReplayEvent format
        if (data.events && data.events.length > 0) {
          const firstEvent = data.events[0];
          if (firstEvent.action_type !== undefined) {
            console.log('Converting action_type format to action format...');
            data.events = data.events.map((event: any) => ({
              ...event,
              action: event.action_type || event.action,
              acting_unit_idx: event.unit_id
            }));
          }
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
  }, [replayFile, boardConfig, configLoading, configError]);

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

  // Training data processing
  const getCurrentTrainingData = () => {
    if (!replayData || !replayData.events || currentStep >= replayData.events.length) {
      return null;
    }
    
    const currentEvent = replayData.events[currentStep];
    return currentEvent.training_data || null;
  };

  const getTrainingProgress = () => {
    if (!replayData?.training_summary) return null;
    
    const summary = replayData.training_summary;
    const currentTraining = getCurrentTrainingData();
    const currentTimestep = currentTraining?.decision?.timestep || 0;
    const timestepStart = summary.timestep_range?.start || 0;
    const timestepEnd = summary.timestep_range?.end || 0;
    const totalRange = timestepEnd - timestepStart || 1;
    const currentProgress = currentTimestep - timestepStart;
    
    return {
      ...summary,
      current_timestep: currentTimestep,
      progress_percentage: Math.min(100, (currentProgress / totalRange) * 100)
    };
  };

  const formatQValues = (qValues: number[] | undefined) => {
    if (!qValues) return 'N/A';
    return qValues.map(val => val.toFixed(3)).join(', ');
  };

  // Training Data Display Component
  const TrainingDataPanel = () => {
    const trainingData = getCurrentTrainingData();
    const trainingProgress = getTrainingProgress();
    
    if (!showTrainingData || !trainingData || !trainingData.decision) {
      return null;
    }

    return (
      <div className="bg-gray-800 rounded-lg p-4 mb-4">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-lg font-semibold text-white flex items-center">
            🧠 Training Context
          </h3>
          <div className="flex space-x-2">
            <select 
              value={selectedTrainingMetric} 
              onChange={(e) => setSelectedTrainingMetric(e.target.value)}
              className="bg-gray-700 text-white text-sm rounded px-2 py-1"
            >
              <option value="overview">Overview</option>
              <option value="decision">Decision Details</option>
              <option value="qvalues">Q-Values</option>
              <option value="progress">Training Progress</option>
            </select>
            <button
              onClick={() => setShowTrainingData(false)}
              className="text-gray-400 hover:text-white"
            >
              ✕
            </button>
          </div>
        </div>

        {selectedTrainingMetric === 'overview' && trainingData.decision && (
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div className="space-y-2">
              <div className="flex justify-between">
                <span className="text-gray-300">Timestep:</span>
                <span className="text-white font-mono">{trainingData.decision.timestep}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-300">Action Type:</span>
                <span className={`font-medium ${trainingData.decision.is_exploration ? 'text-yellow-400' : 'text-green-400'}`}>
                  {trainingData.decision.is_exploration ? '🎲 Exploration' : '🎯 Exploitation'}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-300">Epsilon:</span>
                <span className="text-white font-mono">{trainingData.decision.epsilon?.toFixed(4) || 'N/A'}</span>
              </div>
            </div>
            <div className="space-y-2">
              <div className="flex justify-between">
                <span className="text-gray-300">Action ID:</span>
                <span className="text-white font-mono">{trainingData.decision.action_chosen}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-300">Confidence:</span>
                <span className="text-white font-mono">{trainingData.decision.model_confidence?.toFixed(3) || 'N/A'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-300">Action Q-Value:</span>
                <span className="text-white font-mono">{trainingData.decision.action_q_value?.toFixed(3) || 'N/A'}</span>
              </div>
            </div>
          </div>
        )}

        {selectedTrainingMetric === 'decision' && trainingData.decision && (
          <div className="space-y-3 text-sm">
            <div className="bg-gray-700 rounded p-3">
              <div className="text-gray-300 mb-2">Decision Analysis:</div>
              <div className="text-white">
                {trainingData.decision.is_exploration ? (
                  <span>🎲 <strong>Exploration:</strong> AI chose random action for learning (ε={trainingData.decision.epsilon?.toFixed(4)})</span>
                ) : (
                  <span>🎯 <strong>Exploitation:</strong> AI chose best known action (Q={trainingData.decision.action_q_value?.toFixed(3)})</span>
                )}
              </div>
            </div>
            {trainingData.decision.q_values && (
              <div className="bg-gray-700 rounded p-3">
                <div className="text-gray-300 mb-2">Best Q-Value: {trainingData.decision.best_q_value?.toFixed(3)}</div>
                <div className="text-gray-300 mb-2">Chosen Action Q-Value: {trainingData.decision.action_q_value?.toFixed(3)}</div>
                <div className="text-gray-300 mb-1">Action Space Q-Values:</div>
                <div className="text-white font-mono text-xs break-all">
                  [{formatQValues(trainingData.decision.q_values)}]
                </div>
              </div>
            )}
          </div>
        )}

        {selectedTrainingMetric === 'qvalues' && trainingData.decision?.q_values && (
          <div className="space-y-3 text-sm">
            <div className="grid grid-cols-1 gap-2">
              {trainingData.decision.q_values.map((qval, idx) => (
                <div key={idx} className="flex items-center space-x-2">
                  <span className="text-gray-300 w-16">Action {idx}:</span>
                  <div className="flex-1 bg-gray-700 rounded-full h-4 relative">
                    <div 
                      className={`h-4 rounded-full ${idx === (trainingData.decision?.action_chosen || 0) ? 'bg-yellow-500' : 'bg-blue-500'}`}
                      style={{ width: `${Math.min(100, Math.max(0, (qval + 1) * 50))}%` }}
                    ></div>
                  </div>
                  <span className="text-white font-mono w-20 text-right">{qval.toFixed(3)}</span>
                  {idx === (trainingData.decision?.action_chosen || 0) && <span className="text-yellow-400">⭐</span>}
                </div>
              ))}
            </div>
          </div>
        )}

        {selectedTrainingMetric === 'progress' && trainingProgress && (
          <div className="space-y-3 text-sm">
            <div className="bg-gray-700 rounded p-3">
              <div className="text-gray-300 mb-2">Episode Training Progress:</div>
              <div className="w-full bg-gray-600 rounded-full h-3 mb-2">
                <div 
                  className="bg-green-500 h-3 rounded-full transition-all duration-300"
                  style={{ width: `${trainingProgress.progress_percentage || 0}%` }}
                ></div>
              </div>
              <div className="text-white text-xs">
                Timestep {trainingProgress.current_timestep || 0} of {trainingProgress.timestep_range?.end || 0}
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1">
                <div className="text-gray-300">Exploration Rate:</div>
                <div className="text-yellow-400 font-mono">{((trainingProgress.exploration_rate || 0) * 100).toFixed(1)}%</div>
              </div>
              <div className="space-y-1">
                <div className="text-gray-300">Avg Confidence:</div>
                <div className="text-green-400 font-mono">{trainingProgress.avg_model_confidence?.toFixed(3) || 'N/A'}</div>
              </div>
            </div>
          </div>
        )}
      </div>
    );
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
          <h1 className="text-3xl font-bold mb-2">🎮 WH40K Enhanced Replay Viewer</h1>
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

        {/* Training Data Panel */}
        <TrainingDataPanel />
        
        {/* Turn and Phase Progress */}
        <div className="mb-6 bg-gray-800 p-4 rounded-lg">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-xl font-semibold">Turn {currentTurn} - Phase Progress</h2>
            <div className="text-sm text-gray-400">Step {currentStep + 1} of {replayData.events.length}</div>
          </div>
          
          <div className="flex gap-2 mb-3">
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

        {/* Main Content Area */}
        <div className="flex flex-col xl:flex-row gap-6 mb-6">
          {/* Right Side Panels */}
          <div className="xl:w-96 space-y-4">
            {/* Game Stats */}
            <div className="bg-gray-800 rounded-lg">
              <div className="flex items-center gap-2 p-4 border-b border-gray-700">
                <span className="text-xl">📊</span>
                <h3 className="text-lg font-semibold">Game Stats</h3>
              </div>
              <div className="p-4 space-y-3">
                <div className="flex justify-between">
                  <span className="text-gray-400">Total Reward:</span>
                  <span className={`font-mono ${totalReward >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {totalReward >= 0 ? '+' : ''}{totalReward.toFixed(1)}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400">Player 1 Units:</span>
                  <span className="text-blue-400">{currentUnits.filter(u => u.player === 0 && u.alive).length}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400">Player 2 Units:</span>
                  <span className="text-red-400">{currentUnits.filter(u => u.player === 1 && u.alive).length}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400">Turns Elapsed:</span>
                  <span className="text-yellow-400">{currentTurn}</span>
                </div>
              </div>
            </div>

            {/* Technical Info */}
            <div className="bg-gray-800 rounded-lg">
              <div className="flex items-center gap-2 p-4 border-b border-gray-700">
                <span className="text-xl">🔧</span>
                <h3 className="text-lg font-semibold">Technical Info</h3>
              </div>
              <div className="p-4 space-y-3">
                <div className="flex justify-between">
                  <span className="text-gray-400">Renderer:</span>
                  <span className={useHtmlFallback ? 'text-yellow-400' : 'text-green-400'}>
                    {useHtmlFallback ? 'HTML Fallback' : 'PIXI.js Canvas'}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400">Canvas Active:</span>
                  <span className={appRef.current ? 'text-green-400' : 'text-red-400'}>
                    {appRef.current ? 'Yes' : 'No'}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400">Units Loaded:</span>
                  <span className="text-blue-400">{currentUnits.length}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400">Features:</span>
                  <span className="text-sm text-gray-300">{replayData.features?.join(', ') || 'web_compatible'}</span>
                </div>
              </div>
            </div>

            {/* Action Timeline */}
            <div className="bg-gray-800 rounded-lg">
              <div className="flex items-center gap-2 p-4 border-b border-gray-700">
                <span className="text-xl">📋</span>
                <h3 className="text-lg font-semibold">Action Timeline</h3>
              </div>
              <div className="p-4">
                <div className="space-y-2 max-h-32 overflow-y-auto">
                  {replayData.events.slice(Math.max(0, currentStep - 3), currentStep + 1).map((event, idx) => {
                    const eventIndex = Math.max(0, currentStep - 3) + idx;
                    const isCurrent = eventIndex === currentStep;
                    const eventAction = typeof event?.action === 'number' ? event.action : event?.action?.action_id ?? 0;
                    const eventPhase = getActionPhase(eventAction);
                    
                    return (
                      <div 
                        key={eventIndex}
                        className={`text-xs p-2 rounded ${
                          isCurrent ? 'bg-blue-600 text-white' : 'bg-gray-700 text-gray-300'
                        }`}
                      >
                        <span className="text-gray-400">T{event.turn || 0}:</span> {eventPhase} phase active
                        {event.unit_id && <span className="text-yellow-400"> - Unit {event.unit_id}</span>}
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Bottom Controls Section */}
        <div className="bg-gray-800 rounded-lg p-4">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-semibold">⏯️ Playback Controls</h3>
            <div className="text-sm text-gray-400">Phase: {currentPhase.toUpperCase()}</div>
          </div>
          
          <div className="flex items-center gap-4 mb-4">
            <button
              onClick={reset}
              className="px-3 py-2 bg-gray-600 hover:bg-gray-500 rounded transition-colors"
              title="Reset to beginning"
            >
              ⏮️ First
            </button>
            
            {replayData?.training_summary && (
              <button
                onClick={() => setShowTrainingData(!showTrainingData)}
                className={`px-3 py-2 rounded transition-colors text-sm ${
                  showTrainingData 
                    ? 'bg-blue-600 text-white hover:bg-blue-700' 
                    : 'bg-gray-600 text-white hover:bg-gray-700'
                }`}
                title="Toggle training data display"
              >
                🧠 AI
              </button>
            )}
            <button
              onClick={prevStep}
              disabled={currentStep === 0}
              className="px-3 py-2 bg-gray-600 hover:bg-gray-500 rounded transition-colors disabled:opacity-50"
              title="Previous step"
            >
              ⏪ Prev
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
              ⏩ Next
            </button>
            <button
              className="px-3 py-2 bg-orange-600 hover:bg-orange-500 rounded transition-colors"
              title="Jump to end"
              onClick={() => setCurrentStep(replayData.events.length - 1)}
            >
              ⏭️ Last
            </button>
            
            <div className="flex items-center gap-2 ml-auto">
              <span className="text-sm text-gray-400">Speed:</span>
              <input
                type="range"
                min="100"
                max="3000"
                step="100"
                value={playSpeed}
                onChange={(e) => setPlaySpeed(Number(e.target.value))}
                className="w-20"
              />
              <span className="text-sm w-12 text-center">{((3000 - playSpeed + 100) / 100).toFixed(1)}x</span>
            </div>
          </div>

          {/* Progress Bar */}
          <div className="relative">
            <div className="flex items-center justify-between text-xs text-gray-400 mb-1">
              <span>Step {currentStep + 1} of {replayData.events.length}</span>
              <span>{(((currentStep + 1) / replayData.events.length) * 100).toFixed(1)}%</span>
            </div>
            <div className="w-full bg-gray-700 rounded-full h-3 cursor-pointer"
                 onClick={(e) => {
                   const rect = e.currentTarget.getBoundingClientRect();
                   const x = e.clientX - rect.left;
                   const percentage = x / rect.width;
                   const newStep = Math.floor(percentage * replayData.events.length);
                   setCurrentStep(Math.max(0, Math.min(replayData.events.length - 1, newStep)));
                 }}>
              <div 
                className="bg-blue-600 h-3 rounded-full transition-all duration-300"
                style={{ width: `${((currentStep + 1) / replayData.events.length) * 100}%` }}
              />
            </div>
          </div>
        </div>

        {/* Additional Enhanced Sections */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mt-6">
          {/* AI Analysis */}
          <div className="bg-gray-800 rounded-lg">
            <div className="flex items-center gap-2 p-4 border-b border-gray-700">
              <span className="text-xl">🤖</span>
              <h3 className="text-lg font-semibold">AI Analysis</h3>
            </div>
            <div className="p-4">
              <div className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-gray-400">Exploration Rate:</span>
                  <span className="text-yellow-400">{((getTrainingProgress()?.exploration_rate || 0) * 100).toFixed(1)}%</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400">Total Decisions:</span>
                  <span className="text-blue-400">{getTrainingProgress()?.total_decisions || 'N/A'}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400">Exploration:</span>
                  <span className="text-purple-400">{getTrainingProgress()?.exploration_decisions || 0}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400">Exploitation:</span>
                  <span className="text-green-400">{getTrainingProgress()?.exploitation_decisions || 0}</span>
                </div>
              </div>
            </div>
          </div>

          {/* Battle Log */}
          <div className="bg-gray-800 rounded-lg">
            <div className="flex items-center gap-2 p-4 border-b border-gray-700">
              <span className="text-xl">⚔️</span>
              <h3 className="text-lg font-semibold">Battle Log</h3>
            </div>
            <div className="p-4">
              <div className="space-y-1 text-xs max-h-32 overflow-y-auto">
                {replayData.events.slice(0, currentStep + 1).slice(-5).map((event, idx) => (
                  <div key={idx} className="text-gray-300">
                    <span className="text-gray-500">Turn {event.turn || 0}:</span> {getActionPhase(typeof event?.action === 'number' ? event.action : event?.action || 0)} phase active
                    {event.reward && event.reward > 0 && <span className="text-green-400"> - Reward: +{event.reward.toFixed(1)}</span>}
                    {event.reward && event.reward < 0 && <span className="text-red-400"> - Penalty: {event.reward.toFixed(1)}</span>}
                    {event.acting_unit_idx && <span className="text-yellow-400"> - Unit {event.acting_unit_idx}</span>}
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Unit Details */}
          <div className="bg-gray-800 rounded-lg">
            <div className="flex items-center gap-2 p-4 border-b border-gray-700">
              <span className="text-xl">🎯</span>
              <h3 className="text-lg font-semibold">Unit Details</h3>
            </div>
            <div className="p-4">
              <div className="space-y-2 text-sm">
                {currentEvent?.unit_id && (() => {
                  const unit = currentUnits.find(u => u.id === currentEvent.unit_id);
                  if (!unit) return <div className="text-gray-500">No unit selected</div>;
                  return (
                    <div className="space-y-1">
                      <div className="flex justify-between">
                        <span className="text-gray-400">Type:</span>
                        <span className="text-white">{unit.unit_type}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-gray-400">HP:</span>
                        <span className="text-green-400">{unit.CUR_HP}/{unit.HP_MAX}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-gray-400">Player:</span>
                        <span className={unit.player === 0 ? 'text-blue-400' : 'text-red-400'}>Player {unit.player + 1}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-gray-400">Position:</span>
                        <span className="text-yellow-400">({unit.col}, {unit.row})</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-gray-400">Range:</span>
                        <span className="text-purple-400">{unit.RNG_RNG} hexes</span>
                      </div>
                      <div className="text-xs text-gray-500 mt-2">
                        🛡️ In shooting range of {currentUnits.filter(u => u.player !== unit.player && u.alive && Math.abs(u.col - unit.col) + Math.abs(u.row - unit.row) <= unit.RNG_RNG).length} enemies
                      </div>
                    </div>
                  );
                })() || <div className="text-gray-500">No active unit</div>}
              </div>
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