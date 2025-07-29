// frontend/src/components/BoardReplay.tsx
import React, { useEffect, useRef, useState, useCallback } from 'react';
import * as PIXI from 'pixi.js-legacy';
import { useGameConfig } from '../hooks/useGameConfig';
import type { Unit } from '../types/game';
import SharedLayout from './SharedLayout';
import { TurnPhaseTracker } from './TurnPhaseTracker';
import { renderUnit } from './UnitRenderer';
import { drawBoard } from './BoardDisplay';

// AI_GAME.md: Strict type definitions following game mechanisms
interface ReplayEvent {
  turn: number;
  phase: 'move' | 'shoot' | 'charge' | 'combat';
  player: 0 | 1;
  action: {
    type: string;
    unit_id?: number;
    from_pos?: [number, number];
    to_pos?: [number, number];
    target_id?: number;
    damage?: number;
    result?: string;
  };
  description: string;
  timestamp?: string;
}

interface ReplayUnit {
  id: number;
  unit_type: string;
  player: 0 | 1;
  col: number;
  row: number;
  hp_max: number;
  hp_current: number;
  move: number;
  rng_rng: number;
  rng_dmg: number;
  cc_dmg: number;
  is_ranged: boolean;
  is_melee: boolean;
  alive: boolean;
  COLOR: number;
  MOVE: number;
  HP_MAX: number;
  CUR_HP: number;
  cur_hp: number;
  RNG_RNG: number;
  RNG_DMG: number;
  CC_DMG: number;
  ICON: string;
}

interface ReplayData {
  game_info: {
    scenario: string;
    ai_behavior: string;
    total_turns: number;
    winner: 0 | 1;
    ai_units_final: number;
    enemy_units_final: number;
  };
  initial_state: {
    units: ReplayUnit[];
    board_size: [number, number];
  };
  actions: ReplayEvent[];
}

// Removed ScenarioConfig interface - using BoardConfig directly

interface ReplayViewerProps {
  replayFile?: string;
}

export const BoardReplay: React.FC<ReplayViewerProps> = ({ 
  replayFile: propReplayFile = null
}) => {
  // AI_INSTRUCTIONS.md: Use same config hook as Board.tsx
  const { boardConfig, loading: configLoading, error: configError } = useGameConfig();
  
  // File selection state
  const [replayFile, setReplayFile] = useState<string | null>(propReplayFile);
  const [selectedFileName, setSelectedFileName] = useState<string | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  
  // State management
  const [replayData, setReplayData] = useState<ReplayData | null>(null);
  const [scenario, setScenario] = useState<typeof boardConfig | null>(null);
  const [loading, setLoading] = useState(!!propReplayFile);
  const [error, setError] = useState<string | null>(null);
  const [currentStep, setCurrentStep] = useState(0);
  const [currentUnits, setCurrentUnits] = useState<ReplayUnit[]>([]);
  const [currentEvent, setCurrentEvent] = useState<ReplayEvent | null>(null);
  const [battleLog, setBattleLog] = useState<ReplayEvent[]>([]);
  const [isPlaying, setIsPlaying] = useState(false);
  const [playSpeed, setPlaySpeed] = useState(1000); // ms per step
  const [registryInitialized, setRegistryInitialized] = useState(false);
  
  // PIXI.js refs - AI_INSTRUCTIONS.md: Use PIXI.js Canvas
  const boardRef = useRef<HTMLDivElement>(null);
  const pixiAppRef = useRef<PIXI.Application | null>(null);
  const unitSpritesRef = useRef<Map<number, PIXI.Container>>(new Map());
  
  // Auto-play interval
  const intervalRef = useRef<NodeJS.Timeout | null>(null);

// Action type mapping from the replay file format
const ACTION_TYPE_MAPPING: Record<string, { name: string; type: string }> = {
  "0": { name: "Move North", type: "move" },
  "1": { name: "Move South", type: "move" },
  "2": { name: "Move East", type: "move" },
  "3": { name: "Move West", type: "move" },
  "4": { name: "Ranged Attack", type: "shoot" },
  "5": { name: "Charge Enemy", type: "charge" },
  "6": { name: "Melee Attack", type: "combat" },
  "7": { name: "Wait/End turn", type: "move" },
  "-1": { name: "Phase Penalty", type: "penalty" }
};
const UNIT_REGISTRY: Record<string, any> = {};

// Component to show board preview without replay data
const EmptyBoardPreview: React.FC<{ boardConfig: any }> = ({ boardConfig }) => {
  const boardRef = useRef<HTMLDivElement>(null);
  const pixiAppRef = useRef<PIXI.Application | null>(null);

  useEffect(() => {
    if (!boardRef.current || !boardConfig) return;

    try {
      // Calculate canvas dimensions - same as main board
      const BOARD_COLS = boardConfig.cols;
      const BOARD_ROWS = boardConfig.rows;
      const HEX_RADIUS = boardConfig.hex_radius;
      const MARGIN = boardConfig.margin;
      const HEX_WIDTH = 1.5 * HEX_RADIUS;
      const HEX_HEIGHT = Math.sqrt(3) * HEX_RADIUS;
      const HEX_HORIZ_SPACING = HEX_WIDTH;
      const HEX_VERT_SPACING = HEX_HEIGHT;
      
      const gridWidth = (BOARD_COLS - 1) * HEX_HORIZ_SPACING + HEX_WIDTH;
      const gridHeight = (BOARD_ROWS - 1) * HEX_VERT_SPACING + HEX_HEIGHT;
      const canvasWidth = gridWidth + 2 * MARGIN;
      const canvasHeight = gridHeight + 2 * MARGIN;
      
      // Create PIXI app
      const displayConfig = boardConfig?.display;
      const pixiConfig = {
        width: canvasWidth,
        height: canvasHeight,
        backgroundColor: parseInt(boardConfig.colors.background.replace('0x', ''), 16),
        antialias: displayConfig?.antialias ?? true,
        powerPreference: "high-performance" as WebGLPowerPreference,
        resolution: displayConfig?.resolution === "auto" ? 
          (window.devicePixelRatio || 1) : (displayConfig?.resolution ?? 1),
        autoDensity: displayConfig?.autoDensity ?? true,
      };
      
      const app = new PIXI.Application(pixiConfig);
      app.stage.sortableChildren = true;
      
      // Setup canvas styling
      const canvas = app.view as HTMLCanvasElement;
      canvas.style.display = 'block';
      canvas.style.maxWidth = '100%';
      canvas.style.height = 'auto';
      canvas.style.border = displayConfig?.canvas_border ?? '1px solid #333';
      
      // Clear container and append canvas
      boardRef.current.innerHTML = '';
      boardRef.current.appendChild(canvas);
      
      // Store app reference
      pixiAppRef.current = app;
      
      // Draw board using shared BoardRenderer
      drawBoard(app, boardConfig as any);
      
      console.log('✅ Board preview initialized');
      
      // Cleanup function
      return () => {
        if (pixiAppRef.current) {
          pixiAppRef.current.destroy(true);
          pixiAppRef.current = null;
        }
      };
      
    } catch (error) {
      console.error('❌ Error initializing board preview:', error);
    }
  }, [boardConfig]);

  if (!boardConfig) {
    return (
      <div style={{ 
        display: 'flex', 
        alignItems: 'center', 
        justifyContent: 'center', 
        height: '400px',
        color: '#888'
      }}>
        Loading board...
      </div>
    );
  }

  return <div ref={boardRef} className="board" />;
};

// File selection handlers
const handleFileSelect = (event: React.ChangeEvent<HTMLInputElement>) => {
  const file = event.target.files?.[0];
  if (file) {
    // Validate file type
    if (!file.name.endsWith('.json')) {
      setFileError('Please select a JSON file');
      return;
    }

    // Check if it's a replay file based on naming patterns
    const isReplayFile = file.name.startsWith('training_replay_') ||
                        file.name.startsWith('phase_based_replay_') ||
                        file.name.includes('_vs_') ||
                        file.name.startsWith('replay_') ||
                        file.name.startsWith('training_');

    if (!isReplayFile) {
      setFileError('Please select a valid replay JSON file');
      return;
    }

    // Create file URL for local file access
    const fileUrl = URL.createObjectURL(file);
    setReplayFile(fileUrl);
    setSelectedFileName(file.name);
    setFileError(null);
    setCurrentStep(0);
    console.log(`✅ Selected replay file: ${file.name}`);
  }
};

const openFileBrowser = () => {
  fileInputRef.current?.click();
};

// Dynamic unit registry initialization
const initializeUnitRegistry = async () => {
  try {
    // Load unit registry configuration
    console.log('🔍 Fetching unit registry from /config/unit_registry.json');
    const registryResponse = await fetch('/config/unit_registry.json');
    console.log('🔍 Registry response status:', registryResponse.status, registryResponse.statusText);
    
    if (!registryResponse.ok) {
      throw new Error(`Failed to load unit registry: ${registryResponse.statusText}`);
    }
    
    const text = await registryResponse.text();
    console.log('🔍 Raw registry response (first 200 chars):', text.substring(0, 200));
    
    const unitConfig = JSON.parse(text);
    
    // Dynamically import each unit class
    for (const [unitType, unitPath] of Object.entries(unitConfig.units)) {
      try {
        const module = await import(/* @vite-ignore */ `../roster/${unitPath}.ts`);
        const UnitClass = module[unitType] || module.default;
        
        if (!UnitClass) {
          throw new Error(`Unit class ${unitType} not found in ${unitPath}`);
        }
        
        // Validate required properties
        const requiredProps = ['HP_MAX', 'MOVE', 'RNG_RNG', 'RNG_DMG', 'CC_DMG', 'ICON'];
        requiredProps.forEach(prop => {
          if (UnitClass[prop] === undefined) {
            throw new Error(`Unit ${unitType} missing required property: ${prop}`);
          }
        });
        
        UNIT_REGISTRY[unitType] = UnitClass;
        console.log(`✅ Registered unit: ${unitType}`);
        
      } catch (importError) {
        console.error(`❌ Failed to import unit ${unitType}:`, importError);
        throw importError;
      }
    }
    
    console.log('✅ Unit registry initialized with types:', Object.keys(UNIT_REGISTRY));
  } catch (error) {
    console.error('❌ Failed to initialize unit registry:', error);
    throw error;
  }
};

const validateUnitRegistry = () => {
  if (Object.keys(UNIT_REGISTRY).length === 0) {
    throw new Error('Unit registry not initialized');
  }
};

    // AI_INSTRUCTIONS.md: Initialize unit registry first
  useEffect(() => {
    const initRegistry = async () => {
      try {
        await initializeUnitRegistry();
        validateUnitRegistry();
        console.log('✅ Unit registry initialized for replay');
        // Trigger replay loading with registry state
        setRegistryInitialized(true);
      } catch (error) {
        console.error('❌ Failed to initialize unit registry:', error);
        setError('Failed to initialize unit registry');
      }
    };
    initRegistry();
  }, []);

  // Get unit stats from registry like UnitFactory.ts
  const getUnitStats = useCallback((unitType: string) => {
    const UnitClass = UNIT_REGISTRY[unitType];
    if (!UnitClass) {
      throw new Error(`Unknown unit type: ${unitType}. Available types: ${Object.keys(UNIT_REGISTRY).join(', ')}`);
    }
    
    return {
      MOVE: UnitClass.MOVE,
      HP_MAX: UnitClass.HP_MAX,
      RNG_RNG: UnitClass.RNG_RNG,
      RNG_DMG: UnitClass.RNG_DMG,
      CC_DMG: UnitClass.CC_DMG,
      ICON: UnitClass.ICON
    };
  }, []);
  useEffect(() => {
    const loadReplayData = async () => {
      if (configLoading) return;
      if (configError) {
        setError(`Config error: ${configError}`);
        setLoading(false);
        return;
      }
      
      // Wait for unit registry to be initialized before loading replay
      if (!registryInitialized) {
        console.log('⏳ Waiting for unit registry to initialize...');
        return;
      }
      
      // Reset state when file changes
      setCurrentStep(0);
      setBattleLog([]);
      setCurrentEvent(null);
      
      // Skip loading if no file selected
      if (!replayFile) {
        setLoading(false);
        return;
      }
      
      console.log(`🔄 Loading new replay file: ${replayFile}`);
      
      try {
        setLoading(true);
        
        // Use boardConfig directly - same as Board.tsx for perfect consistency
        setScenario(boardConfig);
        
        // Load replay file - handle both blob URLs and file paths
        let replay;
        if (replayFile.startsWith('blob:')) {
          // Handle blob URL from file selection
          console.log('🔄 Loading blob URL:', replayFile);
          const replayResponse = await fetch(replayFile);
          if (!replayResponse.ok) {
            throw new Error(`Failed to load replay file: ${replayResponse.statusText}`);
          }
          const text = await replayResponse.text();
          console.log('📦 Raw blob text (first 200 chars):', text.substring(0, 200));
          replay = JSON.parse(text);
        } else {
          // Handle regular file path
          console.log('🔄 Loading file path:', replayFile);
          const replayResponse = await fetch(`/${replayFile}`);
          if (!replayResponse.ok) {
            throw new Error(`Failed to load replay file: ${replayResponse.statusText}`);
          }
          replay = await replayResponse.json();
        }
        
        console.log('📦 Raw replay data:', replay);
        console.log('📦 Initial state units:', replay.initial_state?.units);
        console.log('📦 Actions:', replay.actions?.length);
        
        setReplayData(replay);
        
        // Process initial units with proper mapping
        if (replay.initial_state?.units) {
          const processedUnits: ReplayUnit[] = replay.initial_state.units.map((unit: any) => {
            console.log('Processing unit:', unit);
            const stats = getUnitStats(unit.unit_type);
            return {
              id: unit.id,
              name: unit.unit_type,
              type: unit.unit_type,
              unit_type: unit.unit_type,
              player: unit.player,
              col: unit.col,
              row: unit.row,
              color: unit.player === 0 ? parseInt(boardConfig!.colors.player_0.replace('0x', ''), 16) : parseInt(boardConfig!.colors.player_1.replace('0x', ''), 16),
              alive: true,
              hp_max: unit.hp_max,
              hp_current: unit.hp_max,
              move: stats.MOVE,
              rng_rng: stats.RNG_RNG,
              rng_dmg: stats.RNG_DMG,
              cc_dmg: stats.CC_DMG,
              is_ranged: unit.is_ranged || false,
              is_melee: unit.is_melee || false,
              CUR_HP: unit.hp_max,
              cur_hp: unit.hp_max,
              COLOR: unit.player === 0 ? parseInt(boardConfig!.colors.player_0.replace('0x', ''), 16) : parseInt(boardConfig!.colors.player_1.replace('0x', ''), 16),
              MOVE: stats.MOVE,
              HP_MAX: stats.HP_MAX,
              RNG_RNG: stats.RNG_RNG,
              RNG_DMG: stats.RNG_DMG,
              CC_DMG: stats.CC_DMG,
              ICON: `icons/${unit.unit_type}${unit.player === 0 ? '_red' : ''}.webp`,
              BASE: stats.HP_MAX  // Add missing BASE property
            };
          });
          console.log('✅ Processed units:', processedUnits);
          setCurrentUnits(processedUnits);
        } else {
          console.error('❌ No initial_state.units found in replay data');
        }
        
        setBattleLog([]);
        setCurrentStep(0);
        
        console.log('✅ Replay data loaded successfully');
      } catch (err) {
        console.error('❌ Error loading replay:', err);
        setError(err instanceof Error ? err.message : 'Failed to load replay');
      } finally {
        setLoading(false);
      }
    };
    
    loadReplayData();
  }, [replayFile, configLoading, configError, getUnitStats, registryInitialized, boardConfig]);

  // Same hex calculations as Board.tsx
  const getHexCenter = useCallback((col: number, row: number): { x: number, y: number } => {
    if (!boardConfig) return { x: 0, y: 0 };
    
    const HEX_RADIUS = boardConfig.hex_radius;
    const MARGIN = boardConfig.margin;
    const HEX_WIDTH = 1.5 * HEX_RADIUS;
    const HEX_HEIGHT = Math.sqrt(3) * HEX_RADIUS;
    const HEX_HORIZ_SPACING = HEX_WIDTH;
    const HEX_VERT_SPACING = HEX_HEIGHT;
    
    const x = col * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
    const y = row * HEX_VERT_SPACING + ((col % 2) * HEX_VERT_SPACING / 2) + HEX_HEIGHT / 2 + MARGIN;
    
    return { x, y };
  }, [scenario]);

  // Removed duplicate getHexPolygonPoints function

  // Parse colors from config - same as Board.tsx
  const parseColor = useCallback((colorStr: string): number => {
    return parseInt(colorStr.replace('0x', ''), 16);
  }, []);

  // Helper to get hex polygon points
  const getHexPolygonPoints = useCallback((centerX: number, centerY: number, radius: number): number[] => {
    const points: number[] = [];
    for (let i = 0; i < 6; i++) {
      const angle = (Math.PI / 3) * i;
      points.push(centerX + radius * Math.cos(angle), centerY + radius * Math.sin(angle));
    }
    return points;
  }, []);

  // Using shared BoardRenderer - no duplicate code!

  // Draw units using UnitRenderer - same as Board.tsx
  const drawUnits = useCallback((app: PIXI.Application, units: ReplayUnit[]) => {
    if (!scenario || !app.stage || !boardConfig?.display) return;
    
    try {
      // Clear previous unit sprites
      unitSpritesRef.current.forEach(sprite => {
        app.stage.removeChild(sprite);
        sprite.destroy();
      });
      unitSpritesRef.current.clear();
      
      const displayConfig = boardConfig.display;
      const HEX_RADIUS = boardConfig.hex_radius;
      const MARGIN = boardConfig.margin;
      const HEX_WIDTH = 1.5 * HEX_RADIUS;
      const HEX_HEIGHT = Math.sqrt(3) * HEX_RADIUS;
      const HEX_HORIZ_SPACING = HEX_WIDTH;
      const HEX_VERT_SPACING = HEX_HEIGHT;
      
      // Extract all needed constants like Board.tsx
      const ICON_SCALE = displayConfig.icon_scale || 1;
      const ELIGIBLE_OUTLINE_WIDTH = displayConfig.eligible_outline_width || 2;
      const ELIGIBLE_COLOR = parseColor(boardConfig.colors.eligible || '0x00FF00');
      const ELIGIBLE_OUTLINE_ALPHA = displayConfig.eligible_outline_alpha || 0.8;
      const HP_BAR_WIDTH_RATIO = displayConfig.hp_bar_width_ratio || 1.4;
      const HP_BAR_HEIGHT = displayConfig.hp_bar_height || 7;
      const UNIT_CIRCLE_RADIUS_RATIO = displayConfig.unit_circle_radius_ratio || 0.6;
      const UNIT_TEXT_SIZE = displayConfig.unit_text_size || 8;
      const SELECTED_BORDER_WIDTH = displayConfig.selected_border_width || 3;
      const CHARGE_TARGET_BORDER_WIDTH = displayConfig.charge_target_border_width || 2;
      const DEFAULT_BORDER_WIDTH = displayConfig.default_border_width || 1;
      
      // Draw each alive unit using UnitRenderer
      units.filter(unit => unit.alive).forEach(unit => {
        const centerX = unit.col * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
        const centerY = unit.row * HEX_VERT_SPACING + ((unit.col % 2) * HEX_VERT_SPACING / 2) + HEX_HEIGHT / 2 + MARGIN;
        
        const unitForRenderer = {
          ...unit,
          name: unit.unit_type,
          type: unit.unit_type,
          color: unit.COLOR,
          BASE: unit.HP_MAX
        };

        renderUnit({
          unit: unitForRenderer, centerX, centerY, app,
          isPreview: false,
          previewType: undefined,
          isEligible: false,
          boardConfig, HEX_RADIUS, ICON_SCALE, ELIGIBLE_OUTLINE_WIDTH, ELIGIBLE_COLOR, ELIGIBLE_OUTLINE_ALPHA,
          HP_BAR_WIDTH_RATIO, HP_BAR_HEIGHT, UNIT_CIRCLE_RADIUS_RATIO, UNIT_TEXT_SIZE,
          SELECTED_BORDER_WIDTH, CHARGE_TARGET_BORDER_WIDTH, DEFAULT_BORDER_WIDTH,
          phase: 'move', mode: 'normal', currentPlayer: 0, selectedUnitId: null, 
          unitsMoved: [], unitsCharged: [], unitsAttacked: [], unitsFled: [],
          combatSubPhase: undefined, combatActivePlayer: undefined,
          units: units.map(u => ({
            ...u,
            name: u.unit_type,
            type: u.unit_type,
            color: u.COLOR,
            BASE: u.HP_MAX
          })), chargeTargets: [], combatTargets: [], targetPreview: null,
          onConfirmMove: () => {}, parseColor
        });
      });
      
      console.log(`✅ Drew ${units.filter(u => u.alive).length} units using UnitRenderer`);
    } catch (error) {
      console.error('❌ Error drawing units:', error);
      throw error;
    }
  }, [scenario, boardConfig, parseColor]);

  // Initialize PIXI application - AI_INSTRUCTIONS.md: PIXI.js Canvas renderer
  useEffect(() => {
    if (!boardRef.current || !boardConfig || !replayData) return;
    
    try {
      // Calculate canvas dimensions - same as Board.tsx
      const BOARD_COLS = boardConfig!.cols;
      const BOARD_ROWS = boardConfig!.rows;
      const HEX_RADIUS = boardConfig!.hex_radius;
      const MARGIN = boardConfig!.margin;
      const HEX_WIDTH = 1.5 * HEX_RADIUS;
      const HEX_HEIGHT = Math.sqrt(3) * HEX_RADIUS;
      const HEX_HORIZ_SPACING = HEX_WIDTH;
      const HEX_VERT_SPACING = HEX_HEIGHT;
      
      const gridWidth = (BOARD_COLS - 1) * HEX_HORIZ_SPACING + HEX_WIDTH;
      const gridHeight = (BOARD_ROWS - 1) * HEX_VERT_SPACING + HEX_HEIGHT;
      const canvasWidth = gridWidth + 2 * MARGIN;
      const canvasHeight = gridHeight + 2 * MARGIN;
      
      // Use same PIXI config as Board.tsx for consistent appearance
      const displayConfig = boardConfig?.display;
      const pixiConfig = {
        width: canvasWidth,
        height: canvasHeight,
        backgroundColor: parseInt(boardConfig!.colors.background.replace('0x', ''), 16),
        antialias: displayConfig?.antialias ?? true,
        powerPreference: "high-performance" as WebGLPowerPreference,
        resolution: displayConfig?.resolution === "auto" ? 
          (window.devicePixelRatio || 1) : (displayConfig?.resolution ?? 1),
        autoDensity: displayConfig?.autoDensity ?? true,
      };
      
      const app = new PIXI.Application(pixiConfig);
      app.stage.sortableChildren = true;
      
      // Setup canvas styling - same as Board.tsx
      const canvas = app.view as HTMLCanvasElement;
      canvas.style.display = 'block';
      canvas.style.maxWidth = '100%';
      canvas.style.height = 'auto';
      canvas.style.border = displayConfig?.canvas_border ?? '1px solid #333';
      
      // Clear container and append canvas
      boardRef.current.innerHTML = '';
      boardRef.current.appendChild(canvas);
      
      // Store app reference
      pixiAppRef.current = app;
      
      // Draw initial board and units using shared BoardRenderer
      drawBoard(app, boardConfig! as any);
      drawUnits(app, currentUnits);
      
      console.log('✅ PIXI Canvas application initialized for replay');
      
      // Cleanup function
      return () => {
        if (pixiAppRef.current) {
          pixiAppRef.current.destroy(true);
          pixiAppRef.current = null;
        }
        unitSpritesRef.current.clear();
      };
      
    } catch (error) {
      console.error('❌ Error initializing PIXI application:', error);
      setError('Failed to initialize board display');
    }
  }, [scenario, replayData, drawUnits, currentUnits]);

  // Update game state based on current step
  useEffect(() => {
    if (!replayData || currentStep < 0) return;
    
    console.log('🔄 Updating game state for step:', currentStep);
    console.log('🔄 Available actions:', replayData.actions?.length);
    
    try {
      // Reset to initial state
      if (!replayData.initial_state?.units) {
        console.error('❌ No initial state units available');
        return;
      }
      
      let newUnits: ReplayUnit[] = replayData.initial_state.units.map((unit: any) => {
        const stats = getUnitStats(unit.unit_type);
        return {
          id: unit.id,
          name: unit.unit_type,
          type: unit.unit_type,
          unit_type: unit.unit_type,
          player: unit.player,
          col: unit.col,
          row: unit.row,
          color: unit.player === 0 ? parseInt(boardConfig!.colors.player_0.replace('0x', ''), 16) : parseInt(boardConfig!.colors.player_1.replace('0x', ''), 16),
          alive: true,
          hp_max: unit.hp_max,
          hp_current: unit.hp_max,
          move: stats.MOVE,
          rng_rng: stats.RNG_RNG,
          rng_dmg: stats.RNG_DMG,
          cc_dmg: stats.CC_DMG,
          is_ranged: unit.is_ranged || false,
          is_melee: unit.is_melee || false,
          CUR_HP: unit.hp_max,
          cur_hp: unit.hp_max,
          COLOR: unit.player === 0 ? parseInt(boardConfig!.colors.player_0.replace('0x', ''), 16) : parseInt(boardConfig!.colors.player_1.replace('0x', ''), 16),
          MOVE: stats.MOVE,
          HP_MAX: stats.HP_MAX,
          RNG_RNG: stats.RNG_RNG,
          RNG_DMG: stats.RNG_DMG,
          CC_DMG: stats.CC_DMG,
          ICON: unit.player === 0 ? `icons/${unit.unit_type}_red.webp` : stats.ICON
        };
      });
      
      let newBattleLog: ReplayEvent[] = [];
      
      // Apply actions up to current step
      for (let i = 0; i <= currentStep && i < (replayData.actions?.length || 0); i++) {
        const event = replayData.actions[i];
        console.log('📝 Processing event:', i, event);
        
        // Apply action effects based on the actual replay format
        if ((event as any).action_type !== undefined && (event as any).position) {
          const actionInfo = ACTION_TYPE_MAPPING[(event as any).action_type];
          
          // Handle movement actions (0, 1, 2)
          if ([0, 1, 2].includes((event as any).action_type)) {
            const unit = newUnits.find(u => u.id === (event as any).unit_id);
            if (unit && (event as any).position) {
              console.log(`🚶 Moving unit ${unit.id} from (${unit.col},${unit.row}) to (${(event as any).position[0]},${(event as any).position[1]})`);
              unit.col = (event as any).position[0];
              unit.row = (event as any).position[1];
            }
          }
          
          // Handle HP changes from the replay data
          if ((event as any).hp !== undefined) {
            const unit = newUnits.find(u => u.id === (event as any).unit_id);
            if (unit && (event as any).hp !== unit.CUR_HP) {
              const damage = unit.CUR_HP - (event as any).hp;
              if (damage > 0) {
                console.log(`💥 Unit ${unit.id} takes ${damage} damage: ${unit.CUR_HP} -> ${(event as any).hp}`);
              }
              unit.CUR_HP = (event as any).hp;
              unit.cur_hp = (event as any).hp;
              unit.hp_current = (event as any).hp;
              if ((event as any).hp <= 0) {
                unit.alive = false;
                console.log(`💀 Unit ${unit.id} is killed`);
              }
            }
          }
        }
        
        newBattleLog.push({
          ...event,
          description: `${(event as any).player === 1 ? 'AI' : 'Bot'}: ${ACTION_TYPE_MAPPING[(event as any).action_type]?.name || `Action ${(event as any).action_type}`}`,
          action: {
            type: ACTION_TYPE_MAPPING[(event as any).action_type]?.type || 'unknown',
            unit_id: (event as any).unit_id,
            to_pos: (event as any).position
          }
        });
      }
      
      console.log('✅ Final units state:', newUnits);
      setCurrentUnits(newUnits);
      setBattleLog(newBattleLog);
      setCurrentEvent(replayData.actions?.[currentStep] || null);
      
      // Update PIXI display
      if (pixiAppRef.current) {
        console.log('🎨 Updating PIXI display');
        drawUnits(pixiAppRef.current, newUnits);
      }
      
    } catch (error) {
      console.error('❌ Error updating game state:', error);
      setError('Failed to update game state');
    }
  }, [currentStep, replayData, drawUnits, scenario, getUnitStats]);

  // Auto-play functionality
  useEffect(() => {
    if (isPlaying && replayData) {
      intervalRef.current = setInterval(() => {
        setCurrentStep(prev => {
          if (prev >= replayData.actions.length - 1) {
            setIsPlaying(false);
            return prev;
          }
          return prev + 1;
        });
      }, playSpeed);
    } else {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    }
    
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
    };
  }, [isPlaying, playSpeed, replayData]);

  // Navigation functions
  const goToStep = (step: number) => {
    if (replayData && step >= 0 && step < replayData.actions.length) {
      setCurrentStep(step);
      setIsPlaying(false);
    }
  };

  const nextStep = () => {
    if (replayData && currentStep < replayData.actions.length - 1) {
      setCurrentStep(prev => prev + 1);
    }
  };

  const prevStep = () => {
    if (currentStep > 0) {
      setCurrentStep(prev => prev - 1);
    }
  };

  const togglePlay = () => {
    setIsPlaying(prev => !prev);
  };

  const goToTurn = (targetTurn: number) => {
    if (!replayData?.actions) return;
    
    // Find the first action of the target turn
    const actionIndex = replayData.actions.findIndex(action => action.turn === targetTurn);
    if (actionIndex !== -1) {
      setCurrentStep(actionIndex);
      setIsPlaying(false);
    }
  };

  const goToStart = () => {
    setCurrentStep(0);
    setIsPlaying(false);
  };

  const goToEnd = () => {
    if (replayData && replayData.actions.length > 0) {
      setCurrentStep(replayData.actions.length - 1);
      setIsPlaying(false);
    }
  };

  const getCurrentPhase = (): string => {
    if (!currentEvent) return 'move';
    return currentEvent.phase || 'move';
  };

  const getCurrentTurn = (): number => {
    if (!currentEvent) return 1;
    return currentEvent.turn || 1;
  };

  // Remove these unused functions

  // No file selected state - show board preview
  if (!replayFile) {
    const noFileRightContent = (
      <div className="unit-status-table-container">
        <div style={{ padding: '12px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '8px' }}>
            <button
              onClick={openFileBrowser}
              style={{
                padding: '8px 16px',
                backgroundColor: '#1e40af',
                color: 'white',
                border: 'none',
                borderRadius: '4px',
                cursor: 'pointer',
                fontWeight: 'bold'
              }}
            >
              📁 Browse Replay Files
            </button>
            {selectedFileName && (
              <span style={{ fontSize: '12px', color: '#888' }}>
                {selectedFileName}
              </span>
            )}
          </div>
          {fileError && (
            <div style={{ fontSize: '12px', color: '#ff4444', marginTop: '4px' }}>
              {fileError}
            </div>
          )}
          <div style={{ marginTop: '16px', padding: '12px', backgroundColor: '#333', borderRadius: '8px' }}>
            <div style={{ fontSize: '14px', color: '#888', marginBottom: '8px' }}>Board Preview</div>
            <div style={{ fontSize: '12px', color: '#666' }}>
              Select a replay file to see AI training in action on this board
            </div>
          </div>
        </div>
        <input
          ref={fileInputRef}
          type="file"
          accept=".json"
          onChange={handleFileSelect}
          style={{ display: 'none' }}
        />
      </div>
    );

    // Show board preview when no file is selected
    return (
      <SharedLayout rightColumnContent={noFileRightContent}>
        <EmptyBoardPreview boardConfig={boardConfig} />
      </SharedLayout>
    );
  }

  // Loading state
  if (loading) {
    return (
      <SharedLayout rightColumnContent={
        <div className="flex items-center justify-center h-96">
          <div className="text-lg">Loading replay...</div>
        </div>
      }>
        <div className="flex items-center justify-center h-96">
          <div className="text-lg">Loading replay...</div>
        </div>
      </SharedLayout>
    );
  }

  // Error state
  if (error) {
    return (
      <SharedLayout rightColumnContent={
        <div className="flex items-center justify-center h-96">
          <div className="text-red-600">Error: {error}</div>
        </div>
      }>
        <div className="flex items-center justify-center h-96">
          <div className="text-red-600">Error: {error}</div>
        </div>
      </SharedLayout>
    );
  }

  // Merge all controls into a single column like the right side version
  const rightColumnContent = (
    <>
      {/* File Browser Controls */}
      <div className="unit-status-table-container" style={{ marginBottom: '16px' }}>
        <div style={{ padding: '12px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '8px' }}>
            <button
              onClick={openFileBrowser}
              style={{
                padding: '8px 16px',
                backgroundColor: '#1e40af',
                color: 'white',
                border: 'none',
                borderRadius: '4px',
                cursor: 'pointer',
                fontWeight: 'bold'
              }}
            >
              📁 Browse Replay Files
            </button>
            {selectedFileName && (
              <span style={{ fontSize: '12px', color: '#888' }}>
                {selectedFileName}
              </span>
            )}
          </div>
          {fileError && (
            <div style={{ fontSize: '12px', color: '#ff4444', marginTop: '4px' }}>
              {fileError}
            </div>
          )}
        </div>
        <input
          ref={fileInputRef}
          type="file"
          accept=".json"
          onChange={handleFileSelect}
          style={{ display: 'none' }}
        />
      </div>

      {/* Combined Replay Controls with Turn/Phase Navigation */}
      <div className="replay-controls">
        {/* Playback Controls */}
        <div className="replay-controls__buttons">
          <button 
            className="btn btn--secondary" 
            onClick={goToStart} 
            disabled={currentStep === 0}
            title="Back to the start"
          >
            ⏮⏮
          </button>
          <button 
            className="btn btn--secondary" 
            onClick={prevStep} 
            disabled={currentStep === 0}
            title="Previous step"
          >
            ⏮
          </button>
          <button 
            className="btn btn--primary" 
            onClick={togglePlay}
            title={isPlaying ? 'Pause' : 'Play'}
          >
            {isPlaying ? '⏸' : '▶'}
          </button>
          <button 
            className="btn btn--secondary" 
            onClick={nextStep} 
            disabled={!replayData || currentStep >= replayData.actions.length - 1}
            title="Next step"
          >
            ⏭
          </button>
          <button 
            className="btn btn--secondary" 
            onClick={goToEnd} 
            disabled={!replayData || currentStep >= replayData.actions.length - 1}
            title="Last step"
          >
            ⏭⏭
          </button>
        </div>
        
        {/* Progress Info */}
        <div className="replay-controls__info">
          Step {currentStep + 1} of {replayData?.actions.length || 0}
        </div>
        
        {/* Progress Bar */}
        <div className="replay-controls__progress-bar">
          <div
            className="replay-controls__progress-fill"
            style={{
              width: replayData ? `${((currentStep + 1) / replayData.actions.length) * 100}%` : '0%'
            }}
          />
        </div>
      </div>

      {/* Turn and Phase Tracker - Same as main game */}
      <TurnPhaseTracker 
        currentTurn={getCurrentTurn()} 
        currentPhase={getCurrentPhase()}
        className="turn-phase-tracker-right"
        maxTurns={5}
      />

      {/* Training Log - Same format as PvP Game Log */}
      <div className="game-log">
        <div className="game-log__header">
          <h3 className="game-log__title">Training Log</h3>
          <div className="game-log__count">
            {battleLog.length} actions
          </div>
        </div>
        <div className="game-log__content">
          {battleLog.length === 0 ? (
            <div className="game-log__empty">No actions yet...</div>
          ) : (
            <div className="game-log__events">
              {battleLog.slice(0, currentStep + 1).reverse().map((event, reverseIndex) => {
                const originalIndex = currentStep - reverseIndex;
                const rawEvent = event as any;
                
                // Determine event type for proper icon and styling
                const getEventIcon = (actionType: number): string => {
                  const iconMap: Record<number, string> = {
                    0: '👟', // Move North
                    1: '👟', // Move South  
                    2: '👟', // Move East
                    3: '👟', // Move West
                    4: '🎯', // Ranged Attack
                    5: '⚡', // Charge Enemy
                    6: '⚔️', // Melee Attack
                    7: '⏸️', // Wait/End turn
                  };
                  return iconMap[actionType] || '📝';
                };
                
                const getEventTypeClass = (actionType: number): string => {
                  const classMap: Record<number, string> = {
                    0: 'game-log-entry--move',
                    1: 'game-log-entry--move',
                    2: 'game-log-entry--move',
                    3: 'game-log-entry--move',
                    4: 'game-log-entry--shoot',
                    5: 'game-log-entry--charge',
                    6: 'game-log-entry--combat',
                    7: 'game-log-entry--phase',
                  };
                  return classMap[actionType] || 'game-log-entry--default';
                };
                
                return (
                  <div 
                    key={originalIndex}
                    className={`game-log-entry ${getEventTypeClass(rawEvent.action_type)} ${originalIndex === currentStep ? 'game-log-entry--active' : ''}`}
                    onClick={() => setCurrentStep(originalIndex)}
                    style={{ cursor: 'pointer' }}
                  >
                    <div className="game-log-entry__single-line">
                      <span className="game-log-entry__icon">{getEventIcon(rawEvent.action_type)}</span>
                      <span className="game-log-entry__turn">T{event.turn}</span>
                      <span className={`game-log-entry__player ${event.player === 0 ? 'game-log-entry__player--blue' : 'game-log-entry__player--red'}`}>
                        P{event.player}
                      </span>
                      <span className="game-log-entry__message">
                        {event.description || `${ACTION_TYPE_MAPPING[rawEvent.action_type]?.name || `Action ${rawEvent.action_type}`} by unit ${rawEvent.unit_id}`}
                      </span>
                      <span className="game-log-entry__reward">
                        {(rawEvent.reward !== undefined) ? (
                          <span 
                            className={`game-log-entry__reward-value ${(rawEvent.reward || 0) >= 0 ? 'game-log-entry__reward-value--positive' : 'game-log-entry__reward-value--negative'}`}
                          >
                            {(rawEvent.reward || 0) >= 0 ? '+' : ''}{(rawEvent.reward || 0)?.toFixed(1)}
                          </span>
                        ) : (
                          <span className="game-log-entry__reward-value--none">-</span>
                        )}
                      </span>
                      <span style={{ fontSize: '11px', color: '#888', marginLeft: '8px' }}>
                        {ACTION_TYPE_MAPPING[rawEvent.action_type]?.name || `action_${rawEvent.action_type}`}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </>
  );

  return (
    <SharedLayout rightColumnContent={rightColumnContent}>
      <div 
        ref={boardRef} 
        className="board"
      />
    </SharedLayout>
  );
};