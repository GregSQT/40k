// frontend/src/components/ReplayViewer.tsx
import React, { useEffect, useRef, useState, useCallback } from 'react';
import * as PIXI from 'pixi.js-legacy';
import { useGameConfig } from '../hooks/useGameConfig';
import type { Unit } from '../types/game';

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

interface ScenarioConfig {
  board: {
    cols: number;
    rows: number;
    hex_radius: number;
    margin: number;
  };
  colors: {
    background: number;
    cell_even: number;
    cell_odd: number;
    cell_border: number;
    player_0: number;
    player_1: number;
    hp_full: number;
    hp_damaged: number;
  };
}

interface ReplayViewerProps {
  replayFile?: string;
}

export const ReplayViewer: React.FC<ReplayViewerProps> = ({ 
  replayFile = 'ai/event_log/train_best_game_replay.json' 
}) => {
  // AI_INSTRUCTIONS.md: Use same config hook as Board.tsx
  const { boardConfig, loading: configLoading, error: configError } = useGameConfig();
  
  // State management
  const [replayData, setReplayData] = useState<ReplayData | null>(null);
  const [scenario, setScenario] = useState<ScenarioConfig | null>(null);
  const [loading, setLoading] = useState(true);
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

// Dynamic unit registry initialization
const initializeUnitRegistry = async () => {
  try {
    // Load unit registry configuration
    const registryResponse = await fetch('/config/unit_registry.json');
    if (!registryResponse.ok) {
      throw new Error(`Failed to load unit registry: ${registryResponse.statusText}`);
    }
    const unitConfig = await registryResponse.json();
    
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
      console.log(`🔄 Loading new replay file: ${replayFile}`);
      
      try {
        setLoading(true);
        
        // AI_INSTRUCTIONS.md: Use config files - load scenario first
        const scenarioResponse = await fetch('/config/scenario.json');
        if (!scenarioResponse.ok) {
          throw new Error(`Failed to load scenario: ${scenarioResponse.statusText}`);
        }
        const scenarioData = await scenarioResponse.json();
        
        // Ensure scenario has required board config
        if (!scenarioData.board && boardConfig) {
          scenarioData.board = {
            cols: boardConfig.cols,
            rows: boardConfig.rows,
            hex_radius: boardConfig.hex_radius,
            margin: boardConfig.margin
          };
          scenarioData.colors = {
            background: parseInt(boardConfig.colors.background.replace('0x', ''), 16),
            cell_even: parseInt(boardConfig.colors.cell_even.replace('0x', ''), 16),
            cell_odd: parseInt(boardConfig.colors.cell_odd.replace('0x', ''), 16),
            cell_border: parseInt(boardConfig.colors.cell_border.replace('0x', ''), 16),
            player_0: parseInt(boardConfig.colors.player_0.replace('0x', ''), 16),
            player_1: parseInt(boardConfig.colors.player_1.replace('0x', ''), 16),
            hp_full: parseInt(boardConfig.colors.hp_full?.replace('0x', '') || 'ffffff', 16),
            hp_damaged: parseInt(boardConfig.colors.hp_damaged?.replace('0x', '') || 'ff0000', 16)
          };
        }
        setScenario(scenarioData);
        
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
              color: unit.player === 0 ? scenarioData.colors.player_0 : scenarioData.colors.player_1,
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
              COLOR: unit.player === 0 ? scenarioData.colors.player_0 : scenarioData.colors.player_1,
              MOVE: stats.MOVE,
              HP_MAX: stats.HP_MAX,
              RNG_RNG: stats.RNG_RNG,
              RNG_DMG: stats.RNG_DMG,
              CC_DMG: stats.CC_DMG,
              ICON: `icons/${unit.unit_type}${unit.player === 0 ? '_red' : ''}.webp`
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
  }, [replayFile, configLoading, configError, getUnitStats, registryInitialized]);

  // AI_INSTRUCTIONS.md: Same hex calculations as Board.tsx
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

  // AI_INSTRUCTIONS.md: Same board rendering as Board.tsx - PIXI.js Canvas only
  const drawBoard = useCallback((app: PIXI.Application) => {
    if (!scenario || !app.stage) return;
    
    try {
      // Clear previous board drawings
      app.stage.children.filter(child => child.name === 'hex').forEach(hex => {
        app.stage.removeChild(hex);
      });
      
      // Draw hex grid using same logic as Board.tsx
      for (let row = 0; row < scenario.board.rows; row++) {
        for (let col = 0; col < scenario.board.cols; col++) {
          const center = getHexCenter(col, row);
          const hexGraphics = new PIXI.Graphics();
          hexGraphics.name = 'hex';
          
          // Same hex styling as Board.tsx
          const isEven = (col + row) % 2 === 0;
          hexGraphics.beginFill(isEven ? scenario.colors.cell_even : scenario.colors.cell_odd);
          hexGraphics.lineStyle(1, scenario.colors.cell_border);
          hexGraphics.drawPolygon(getHexPolygonPoints(scenario.board.hex_radius));
          hexGraphics.endFill();
          
          hexGraphics.position.set(center.x, center.y);
          app.stage.addChild(hexGraphics);
        }
      }
      
      console.log(`✅ Board drawn: ${scenario.board.rows}x${scenario.board.cols} hexes`);
    } catch (error) {
      console.error('❌ Error drawing board:', error);
      throw error;
    }
  }, [scenario, getHexCenter, getHexPolygonPoints]);

  // Draw units with Board.tsx layout
  const drawUnits = useCallback((app: PIXI.Application, units: ReplayUnit[]) => {
    if (!scenario || !app.stage) return;
    
    try {
      // Clear previous unit sprites
      unitSpritesRef.current.forEach(sprite => {
        app.stage.removeChild(sprite);
        sprite.destroy();
      });
      unitSpritesRef.current.clear();
      
      // Draw each alive unit using Board.tsx style
      units.filter(unit => unit.alive).forEach(unit => {
        const center = getHexCenter(unit.col, unit.row);
        
        // Unit circle background
        const unitCircle = new PIXI.Graphics();
        unitCircle.beginFill(unit.player === 0 ? scenario.colors.player_0 : scenario.colors.player_1);
        unitCircle.lineStyle(2, 0x000000);
        unitCircle.drawCircle(center.x, center.y, scenario.board.hex_radius * 0.6);
        unitCircle.endFill();
        app.stage.addChild(unitCircle);
        
        // Icon rendering from Board.tsx with error handling
        if (unit.ICON) {
          try {
            const texture = PIXI.Texture.from(unit.ICON);
            const sprite = new PIXI.Sprite(texture);
            sprite.anchor.set(0.5);
            sprite.position.set(center.x, center.y);
            sprite.width = scenario.board.hex_radius * 1.2; // Icon scale from Board.tsx
            sprite.height = scenario.board.hex_radius * 1.2;
            app.stage.addChild(sprite);
          } catch (iconError) {
            console.warn(`Failed to load icon ${unit.ICON}:`, iconError);
            // Fallback to text if icon fails - show unit type clearly
            const displayText = unit.unit_type.length > 8 ? unit.unit_type.substring(0, 8) : unit.unit_type;
            const unitText = new PIXI.Text(displayText, {
              fontSize: 8,
              fill: 0xffffff,
              align: "center",
              fontWeight: "bold",
            });
            unitText.anchor.set(0.5);
            unitText.position.set(center.x, center.y);
            app.stage.addChild(unitText);
          }
        } else {
          // No icon - use text fallback
          const displayText = unit.unit_type.length > 8 ? unit.unit_type.substring(0, 8) : unit.unit_type;
          const unitText = new PIXI.Text(displayText, {
            fontSize: 8,
            fill: 0xffffff,
            align: "center",
            fontWeight: "bold",
          });
          unitText.anchor.set(0.5);
          unitText.position.set(center.x, center.y);
          app.stage.addChild(unitText);
        }
        
        // HP bar using Board.tsx HP slices
        const currentHP = unit.CUR_HP !== undefined ? unit.CUR_HP : unit.hp_current;
        const maxHP = unit.HP_MAX !== undefined ? unit.HP_MAX : unit.hp_max;
        
        if (maxHP > 0) {
          const HP_BAR_WIDTH = scenario.board.hex_radius * 1.4;
          const HP_BAR_HEIGHT = 7;
          const HP_BAR_Y_OFFSET = scenario.board.hex_radius * 0.85;

          const barX = center.x - HP_BAR_WIDTH / 2;
          const barY = center.y - HP_BAR_Y_OFFSET - HP_BAR_HEIGHT;

          // Draw background (gray)
          const barBg = new PIXI.Graphics();
          barBg.beginFill(0x222222, 1);
          barBg.drawRoundedRect(barX, barY, HP_BAR_WIDTH, HP_BAR_HEIGHT, 3);
          barBg.endFill();
          app.stage.addChild(barBg);
          
          // Draw HP slices like Board.tsx
          const hp = Math.max(0, currentHP);
          const sliceWidth = HP_BAR_WIDTH / maxHP;
          
          for (let i = 0; i < maxHP; i++) {
            const slice = new PIXI.Graphics();
            const color = i < hp ? 0x00ff00 : 0x444444; // Green if current HP, dark gray if lost
            
            slice.beginFill(color, 1);
            slice.drawRoundedRect(
              barX + i * sliceWidth + 1, // Small gap between slices
              barY + 1,
              sliceWidth - 2, // Slightly smaller to create gaps
              HP_BAR_HEIGHT - 2,
              2
            );
            slice.endFill();
            app.stage.addChild(slice);
          }
        }
      });
      
      console.log(`✅ Drew ${units.filter(u => u.alive).length} units`);
    } catch (error) {
      console.error('❌ Error drawing units:', error);
      throw error;
    }
  }, [scenario, getHexCenter]);

  // Initialize PIXI application - AI_INSTRUCTIONS.md: PIXI.js Canvas renderer
  useEffect(() => {
    if (!boardRef.current || !scenario?.board || !replayData) return;
    
    try {
      // Calculate canvas dimensions
      const canvasWidth = scenario.board.cols * scenario.board.hex_radius * 1.5 + scenario.board.margin * 2;
      const canvasHeight = scenario.board.rows * scenario.board.hex_radius * 1.75 + scenario.board.margin * 2;
      
      // AI_INSTRUCTIONS.md: Always use Canvas renderer, never WebGL
      const app = new PIXI.Application({
        width: canvasWidth,
        height: canvasHeight,
        backgroundColor: scenario.colors.background,
        antialias: true,
        forceCanvas: true, // Enforce Canvas renderer
        resolution: 1,
        autoDensity: true,
      });
      
      // Setup canvas styling
      const canvas = app.view as HTMLCanvasElement;
      canvas.style.width = '100%';
      canvas.style.height = 'auto';
      canvas.style.maxWidth = '800px';
      canvas.style.border = '1px solid #333';
      
      // Clear container and append canvas
      boardRef.current.innerHTML = '';
      boardRef.current.appendChild(canvas);
      
      // Store app reference
      pixiAppRef.current = app;
      
      // Draw initial board and units
      drawBoard(app);
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
  }, [scenario, replayData, drawBoard, drawUnits, currentUnits]);

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
          color: unit.player === 0 ? scenario?.colors.player_0 || 0x0000ff : scenario?.colors.player_1 || 0xff0000,
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
          COLOR: unit.player === 0 ? scenario?.colors.player_0 || 0x0000ff : scenario?.colors.player_1 || 0xff0000,
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

  const getCurrentPhase = (): string => {
    if (!currentEvent) return 'move';
    return currentEvent.phase || 'move';
  };

  const getCurrentTurn = (): number => {
    if (!currentEvent) return 1;
    return currentEvent.turn || 1;
  };

  // Phase button styling with proper active state
  const getPhaseButtonClass = (phase: string) => {
    const baseClass = "px-3 py-1 text-sm font-medium rounded transition-colors ";
    const currentPhase = getCurrentPhase();
    const isActive = currentPhase === phase;
    
    // Show completed phases with checkmark
    const isCompleted = isPhaseCompleted(phase, getCurrentTurn(), currentStep);
    
    if (isActive) {
      return baseClass + "bg-blue-600 text-white font-bold";
    } else if (isCompleted) {
      return baseClass + "bg-green-600 text-white";
    } else {
      return baseClass + "bg-gray-200 text-gray-700 hover:bg-gray-300";
    }
  };

  // Helper function to check if a phase is completed in current turn
  const isPhaseCompleted = (phase: string, currentTurn: number, currentStep: number): boolean => {
    if (!replayData?.actions) return false;
    
    // Check if there are any actions of this phase type in the current turn that are before or at current step
    const phaseActionsInTurn = replayData.actions.slice(0, currentStep + 1).filter(action => 
      action.turn === currentTurn && action.phase === phase
    );
    
    return phaseActionsInTurn.length > 0;
  };

  // Loading state
  if (loading) {
    return (
      <div className="flex items-center justify-center h-96">
        <div className="text-lg">Loading replay...</div>
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div className="flex items-center justify-center h-96">
        <div className="text-red-600">Error: {error}</div>
      </div>
    );
  }

  // Main render - Layout matching replay layout image
  return (
    <div className="h-screen bg-gray-100" style={{display: 'flex'}}>
      {/* Left Column: Game Board */}
      <div className="flex flex-col overflow-hidden bg-white" style={{flex: '0 0 auto', width: 'calc(100vw - 450px)', maxWidth: '800px'}}>
        {/* Top Section: Turn and Phase Progress */}
        <div className="bg-white p-4 border-b shadow-sm">
          <div className="flex items-center justify-between mb-3">
            <div>
              <h2 className="text-lg font-semibold">
                Turn {getCurrentTurn()} - Phase Progress
              </h2>
              <div className="text-xs text-gray-500 mt-1">
                {replayFile?.split('/').pop()?.replace('.json', '') || 'Unknown replay'}
              </div>
            </div>
            <div className="text-sm text-gray-600">
              Step {currentStep + 1} of {replayData?.actions.length || 0}
            </div>
          </div>
          
          {/* Phase Buttons - AI_GAME.md: move → shoot → charge → combat */}
          <div className="flex space-x-2">
            <button className={getPhaseButtonClass('move')}>
              {isPhaseCompleted('move', getCurrentTurn(), currentStep) ? '✓' : ''} MOVE
            </button>
            <button className={getPhaseButtonClass('shoot')}>
              {isPhaseCompleted('shoot', getCurrentTurn(), currentStep) ? '✓' : ''} SHOOT
            </button>
            <button className={getPhaseButtonClass('charge')}>
              {isPhaseCompleted('charge', getCurrentTurn(), currentStep) ? '✓' : ''} CHARGE
            </button>
            <button className={getPhaseButtonClass('combat')}>
              {isPhaseCompleted('combat', getCurrentTurn(), currentStep) ? '✓' : ''} COMBAT
            </button>
          </div>
        </div>
        
        {/* Board Section - AI_INSTRUCTIONS.md: Same board as game feature */}
        <div className="flex-1 p-4 overflow-auto bg-gray-50">
          <div 
            ref={boardRef} 
            className="w-full h-full flex items-center justify-center"
            style={{ minHeight: '600px' }}
          />
        </div>
        
        {/* Bottom Section: Control Panel */}
        <div className="bg-white p-4 border-t shadow-sm">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center space-x-2">
              <button
                onClick={prevStep}
                disabled={currentStep === 0}
                className="px-3 py-1 bg-gray-200 text-gray-700 rounded hover:bg-gray-300 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                ← Prev
              </button>
              
              <button
                onClick={togglePlay}
                className={`px-4 py-2 rounded font-medium ${
                  isPlaying 
                    ? 'bg-red-600 text-white hover:bg-red-700' 
                    : 'bg-green-600 text-white hover:bg-green-700'
                }`}
              >
                {isPlaying ? '⏸ Pause' : '▶ Play'}
              </button>
              
              <button
                onClick={nextStep}
                disabled={!replayData || currentStep >= replayData.actions.length - 1}
                className="px-3 py-1 bg-gray-200 text-gray-700 rounded hover:bg-gray-300 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                Next →
              </button>
            </div>
            
            <div className="flex items-center space-x-2">
              <label className="text-sm text-gray-600">Speed:</label>
              <select
                value={playSpeed}
                onChange={(e) => setPlaySpeed(Number(e.target.value))}
                className="px-2 py-1 border rounded text-sm"
              >
                <option value={2000}>0.5x</option>
                <option value={1000}>1x</option>
                <option value={500}>2x</option>
                <option value={250}>4x</option>
              </select>
            </div>
          </div>
          
          {/* Progress Bar */}
          <div className="w-full bg-gray-200 rounded-full h-2">
            <div
              className="bg-blue-600 h-2 rounded-full transition-all duration-200"
              style={{
                width: replayData ? `${((currentStep + 1) / replayData.actions.length) * 100}%` : '0%'
              }}
            />
          </div>
        </div>
      </div>
      
        {/* Right Column: Battle Log - Clean dedicated column */}
        <div className="flex flex-col bg-gray-700 text-white" style={{width: '450px', flexShrink: 0}}>
          {/* Header - Dark style matching image */}
          <div className="p-3 bg-gray-800 border-b border-gray-600">
            <h3 className="text-lg font-semibold flex items-center">
              <span className="mr-2">✕</span>
              Battle Log
            </h3>
          </div>
          
          {/* Battle Log Content - Full height scrollable */}
          <div className="flex-1 overflow-y-auto p-3">
            {(() => {
              console.log('🔍 Debug battleLog:', battleLog.length, 'currentStep:', currentStep, 'battleLog data:', battleLog);
              return null;
            })()}
            {battleLog.length === 0 ? (
              <div className="text-gray-400 text-sm">No actions yet...</div>
            ) : (
              <div className="space-y-4">
                {/* Table format for battle log */}
                <div className="bg-gray-800 rounded-lg border border-gray-600 overflow-hidden">
                  <table className="w-full text-xs">
                    <thead className="bg-gray-900 border-b border-gray-600">
                      <tr>
                        <th className="text-center p-1 font-semibold text-gray-300 w-8">Turn</th>
                        <th className="text-center p-1 font-semibold text-gray-300 w-8">Player</th>
                        <th className="text-center p-1 font-semibold text-gray-300 w-10">Phase</th>
                        <th className="text-center p-1 font-semibold text-gray-300 w-8">Unit</th>
                        <th className="text-center p-1 font-semibold text-gray-300 w-12">Type</th>
                        <th className="text-center p-1 font-semibold text-gray-300 w-16">Reward</th>
                        <th className="text-center p-1 font-semibold text-gray-300" style={{width: '600px', minWidth: '200px'}}>Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {battleLog.slice(0, currentStep + 1).map((event, index) => (
                        <tr 
                          key={index}
                          className={`border-b border-gray-600 cursor-pointer transition-colors ${
                            index === currentStep 
                              ? 'bg-blue-600 font-medium' 
                              : 'hover:bg-gray-600'
                          }`}
                          onClick={() => setCurrentStep(index)}
                        >
                          <td className="p-1 text-gray-300 text-center">{event.turn || 'N/A'}</td>
                          <td className="p-1 text-gray-300 text-center">{event.player}</td>
                          <td className="p-1 text-gray-300 capitalize">{event.phase || 'unknown'}</td>
                          <td className="p-1 text-gray-300 text-center">{(event as any).unit_id}</td>
                          <td className="p-1 text-gray-300">{(event as any).unit_type}</td>
                          <td className="p-1 text-gray-300 text-right">
                            {((event as any).reward !== undefined || (event as any).penalty_amount !== undefined) ? (
                              <span className={((event as any).reward || (event as any).penalty_amount || 0) >= 0 ? 'text-green-400' : 'text-red-400'}>
                                {((event as any).reward || (event as any).penalty_amount || 0) >= 0 ? '+' : ''}{((event as any).reward || (event as any).penalty_amount || 0)?.toFixed(1)}
                              </span>
                            ) : (
                              <span className="text-gray-500">-</span>
                            )}
                          </td>
                          <td className="p-1 text-gray-300" style={{width: '600px', minWidth: '200px'}}>
                            <div className="text-white" style={{wordWrap: 'break-word'}}>
                              {event.description || (event as any).penalty_type || `Action ${(event as any).action_type} by unit ${(event as any).unit_id}`}
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
          
          {/* Game Info Footer */}
          {replayData && (
            <div className="p-3 border-t border-gray-600 bg-gray-800">
              <div className="grid grid-cols-2 gap-2 text-xs text-gray-300 mb-2">
                <div>Winner: Player {replayData.game_info?.winner}</div>
                <div>Total Turns: {replayData.game_info?.total_turns}</div>
                <div>AI Units: {replayData.game_info?.ai_units_final}</div>
                <div>Enemy Units: {replayData.game_info?.enemy_units_final}</div>
              </div>
              <div className="text-xs text-gray-400 pt-2 border-t border-gray-700 whitespace-nowrap overflow-hidden text-ellipsis">
                Log file: {replayFile}
              </div>
            </div>
          )}
        </div>
    </div>
  );
};