import React, { useState, useEffect, useCallback } from 'react';
import * as PIXI from 'pixi.js';

// Define types inline to match your existing game types
interface Unit {
  id: number;
  name: string;
  type: string;
  player: 0 | 1;
  col: number;
  row: number;
  color: number;
  MOVE: number;
  HP_MAX: number;
  CUR_HP?: number;
  RNG_RNG: number;
  RNG_DMG: number;
  CC_DMG: number;
  ICON: string;
}

interface ReplayEvent {
  turn: number;
  action: number;
  reward: number;
  ai_units_alive: number;
  enemy_units_alive: number;
  game_over: boolean;
  units?: Unit[];
  acting_unit_idx?: number;
}

// Action mapping for display
const ACTION_NAMES: { [key: number]: string } = {
  0: "Move Closer",
  1: "Move Away", 
  2: "Move to Safety",
  3: "Shoot Closest",
  4: "Shoot Weakest",
  5: "Charge Closest",
  6: "Wait",
  7: "Attack Adjacent"
};

// Default unit positions matching WH40K game setup
const DEFAULT_POSITIONS: { [key: number]: { col: number; row: number } } = {
  0: { col: 23, row: 12 }, // P-I (Player Intercessor)
  1: { col: 1, row: 12 },  // P-A (Player Assault Intercessor)
  2: { col: 0, row: 5 },   // A-I (AI Intercessor)
  3: { col: 22, row: 3 }   // A-A (AI Assault Intercessor)
};

interface ReplayViewerProps {
  eventLog?: ReplayEvent[];
  autoPlay?: boolean;
  stepDelay?: number;
}

const ReplayViewer: React.FC<ReplayViewerProps> = ({ 
  eventLog, 
  autoPlay = false, 
  stepDelay = 1000 
}) => {
  const [currentStep, setCurrentStep] = useState(0);
  const [isPlaying, setIsPlaying] = useState(autoPlay);
  const [playbackSpeed, setPlaybackSpeed] = useState(1.0);
  const [replayData, setReplayData] = useState<ReplayEvent[]>([]);
  const [units, setUnits] = useState<Unit[]>([]);
  const boardRef = React.useRef<HTMLDivElement>(null);

  // Board configuration - matching your Board.tsx exactly
  const BOARD_COLS = 24;
  const BOARD_ROWS = 18;
  const HEX_RADIUS = 24;
  const MARGIN = 32;
  const HEX_WIDTH = 1.5 * HEX_RADIUS;
  const HEX_HEIGHT = Math.sqrt(3) * HEX_RADIUS;
  const HEX_HORIZ_SPACING = HEX_WIDTH;
  const HEX_VERT_SPACING = HEX_HEIGHT;
  const HIGHLIGHT_COLOR = 0x80ff80;
  const ATTACK_COLOR = 0xff4444;

  // Initialize replay data
  useEffect(() => {
    if (!eventLog || eventLog.length === 0) {
      throw new Error('No replay data provided. Please provide eventLog prop.');
    }
    setReplayData(eventLog);
    setCurrentStep(0);
  }, [eventLog]);

  // Get current event and selected unit
  const currentEvent = replayData.length > 0 ? replayData[currentStep] : null;
  const selectedUnitId = currentEvent?.acting_unit_idx ?? null;

  // Hex utility functions - exactly from your Board.tsx
  const offsetToCube = (col: number, row: number) => {
    const x = col;
    const z = row - ((col - (col & 1)) >> 1);
    const y = -x - z;
    return { x, y, z };
  };

  const hexCorner = (cx: number, cy: number, size: number, i: number) => {
    const angle_deg = 60 * i;
    const angle_rad = Math.PI / 180 * angle_deg;
    return [
      cx + size * Math.cos(angle_rad),
      cy + size * Math.sin(angle_rad),
    ];
  };

  const getHexPolygonPoints = (cx: number, cy: number, size: number) => {
    return Array.from({ length: 6 }, (_, i) => hexCorner(cx, cy, size, i)).flat();
  };

  // Create units based on current event
  const createUnitsFromEvent = useCallback((event: ReplayEvent): Unit[] => {
    if (event.units && Array.isArray(event.units)) {
      // If full unit data is available, use it
      return event.units.map(unit => ({
        ...unit,
        CUR_HP: unit.CUR_HP ?? unit.HP_MAX
      }));
    }

    // Otherwise, create units based on alive counts and default positions
    const units: Unit[] = [];
    const aiAlive = event.ai_units_alive || 0;
    const playerAlive = event.enemy_units_alive || 0;

    // Create AI units (player 1, red)
    for (let i = 0; i < 2; i++) {
      const defaultPos = DEFAULT_POSITIONS[i + 2] || { col: 0, row: 0 };
      units.push({
        id: i + 2,
        name: `A-${i === 0 ? 'I' : 'A'}`,
        type: i === 0 ? 'Intercessor' : 'AssaultIntercessor',
        player: 1,
        col: defaultPos.col,
        row: defaultPos.row,
        color: i === 0 ? 0x882222 : 0x6633cc,
        MOVE: i === 0 ? 4 : 6,
        HP_MAX: i === 0 ? 3 : 4,
        CUR_HP: i < aiAlive ? (i === 0 ? 3 : 4) : 0,
        RNG_RNG: i === 0 ? 8 : 4,
        RNG_DMG: i === 0 ? 2 : 1,
        CC_DMG: i === 0 ? 1 : 2,
        ICON: i === 0 ? '/icons/Intercessor.webp' : '/icons/AssaultIntercessor.webp'
      });
    }

    // Create Player units (player 0, blue)
    for (let i = 0; i < 2; i++) {
      const defaultPos = DEFAULT_POSITIONS[i] || { col: 0, row: 0 };
      units.push({
        id: i,
        name: `P-${i === 0 ? 'I' : 'A'}`,
        type: i === 0 ? 'Intercessor' : 'AssaultIntercessor',
        player: 0,
        col: defaultPos.col,
        row: defaultPos.row,
        color: i === 0 ? 0x244488 : 0xff3333,
        MOVE: i === 0 ? 4 : 6,
        HP_MAX: i === 0 ? 3 : 4,
        CUR_HP: i < playerAlive ? (i === 0 ? 3 : 4) : 0,
        RNG_RNG: i === 0 ? 8 : 4,
        RNG_DMG: i === 0 ? 2 : 1,
        CC_DMG: i === 0 ? 1 : 2,
        ICON: i === 0 ? '/icons/Intercessor.webp' : '/icons/AssaultIntercessor.webp'
      });
    }

    return units;
  }, []);

  // Update units when step changes
  useEffect(() => {
    if (replayData.length > 0 && currentStep < replayData.length && currentEvent) {
      setUnits(createUnitsFromEvent(currentEvent));
    }
  }, [currentStep, replayData, currentEvent, createUnitsFromEvent]);

  // Create hexagonal board with PixiJS - matching your Board.tsx
  const createHexBoard = React.useCallback(() => {
    if (!boardRef.current) return;

    // Clear existing content
    boardRef.current.innerHTML = '';

    // Check if PIXI is available
    const PIXI = (window as any).PIXI;
    if (!PIXI.Application) {
  boardRef.current.innerHTML = `
    <div style="color: #ff4444; padding: 40px; text-align: center; background: rgba(0,0,0,0.8); border-radius: 8px;">
      <h3>PixiJS Import Error</h3>
      <p>Failed to load PixiJS properly</p>
    </div>
  `;
  return;
}

    const gridWidth = (BOARD_COLS - 1) * HEX_HORIZ_SPACING + HEX_WIDTH;
    const gridHeight = (BOARD_ROWS - 1) * HEX_VERT_SPACING + HEX_HEIGHT;
    const width = gridWidth + 2 * MARGIN;
    const height = gridHeight + 2 * MARGIN;

    const app = new PIXI.Application({
      width,
      height,
      backgroundColor: 0x000000,
      antialias: true,
      resolution: window.devicePixelRatio || 1,
      autoDensity: true,
    });

    boardRef.current.appendChild(app.view);

    // Draw hex grid - exactly like Board.tsx
    for (let col = 0; col < BOARD_COLS; col++) {
      for (let row = 0; row < BOARD_ROWS; row++) {
        const centerX = col * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
        const centerY = row * HEX_VERT_SPACING + ((col % 2) * HEX_VERT_SPACING / 2) + HEX_HEIGHT / 2 + MARGIN;
        const points = getHexPolygonPoints(centerX, centerY, HEX_RADIUS);
        
        const cell = new PIXI.Graphics();
        cell.lineStyle(1, 0x333333, 0.5);
        cell.beginFill(0x000000, 0.1);
        cell.drawPolygon(points);
        cell.endFill();
        
        app.stage.addChild(cell);
      }
    }

    // Draw units - exactly like Board.tsx
    units.forEach(unit => {
      const centerX = unit.col * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
      const centerY = unit.row * HEX_VERT_SPACING + ((unit.col % 2) * HEX_VERT_SPACING / 2) + HEX_HEIGHT / 2 + MARGIN;

      // HP Bar - exactly like Board.tsx
      if (unit.HP_MAX) {
        const HP_BAR_WIDTH = HEX_RADIUS * 1.4;
        const HP_BAR_HEIGHT = 7;
        const HP_BAR_Y_OFFSET = HEX_RADIUS * 0.85;

        const barX = centerX - HP_BAR_WIDTH / 2;
        const barY = centerY - HP_BAR_Y_OFFSET - HP_BAR_HEIGHT;

        // Draw background (gray)
        const barBg = new PIXI.Graphics();
        barBg.beginFill(0x222222, 1);
        barBg.drawRoundedRect(barX, barY, HP_BAR_WIDTH, HP_BAR_HEIGHT, 3);
        barBg.endFill();
        app.stage.addChild(barBg);

        // Draw HP slices - exactly like Board.tsx
        const hp = Math.max(0, unit.CUR_HP ?? unit.HP_MAX);
        for (let i = 0; i < unit.HP_MAX; i++) {
          const sliceWidth = (HP_BAR_WIDTH - (unit.HP_MAX - 1)) / unit.HP_MAX;
          const sliceX = barX + i * (sliceWidth + 1);
          const color = i < hp ? 0x36e36b : 0x444444;
          const slice = new PIXI.Graphics();
          slice.beginFill(color, 1);
          slice.drawRoundedRect(sliceX, barY + 1, sliceWidth, HP_BAR_HEIGHT - 2, 2);
          slice.endFill();
          app.stage.addChild(slice);
        }
      }

      // Unit circle - exactly like Board.tsx
      const isSelected = unit.id === selectedUnitId;
      const unitCircle = new PIXI.Graphics();
      unitCircle.beginFill(unit.color, 1);
      unitCircle.drawCircle(centerX, centerY, HEX_RADIUS * 0.6);
      unitCircle.endFill();

      // Selected unit outline
      if (isSelected) {
        unitCircle.lineStyle(3, HIGHLIGHT_COLOR, 1);
        unitCircle.drawCircle(centerX, centerY, HEX_RADIUS * 0.7);
      }

      app.stage.addChild(unitCircle);

      // Unit icon or label - exactly like Board.tsx
      if (unit.ICON) {
        const ICON_SIZE = HEX_RADIUS * 1.5;
        try {
          const iconSprite = PIXI.Sprite.from(unit.ICON);
          iconSprite.x = centerX - ICON_SIZE / 2;
          iconSprite.y = centerY - ICON_SIZE / 2;
          iconSprite.width = ICON_SIZE;
          iconSprite.height = ICON_SIZE;
          app.stage.addChild(iconSprite);
        } catch (e) {
          // Fallback to text if icon fails to load
          const label = new PIXI.Text(unit.name, {
            fontFamily: "Arial",
            fontWeight: "bold",
            fontSize: 14,
            fill: 0xffffff,
            align: "center",
          });
          label.anchor.set(0.5);
          label.x = centerX;
          label.y = centerY;
          app.stage.addChild(label);
        }
      } else {
        const label = new PIXI.Text(unit.name, {
          fontFamily: "Arial",
          fontWeight: "bold",
          fontSize: 14,
          fill: 0xffffff,
          align: "center",
        });
        label.anchor.set(0.5);
        label.x = centerX;
        label.y = centerY;
        app.stage.addChild(label);
      }
    });

    // Cleanup function
    return () => {
      app.destroy(true);
    };
  }, [units, selectedUnitId, BOARD_COLS, BOARD_ROWS, HEX_RADIUS, HEX_HORIZ_SPACING, HEX_VERT_SPACING, HEX_WIDTH, HEX_HEIGHT, MARGIN, HIGHLIGHT_COLOR, getHexPolygonPoints]);

  // Redraw board when units change
  React.useEffect(() => {
    createHexBoard();
  }, [createHexBoard]);

  // Auto-play logic
  useEffect(() => {
    if (!isPlaying || currentStep >= replayData.length - 1) return;
    
    const timer = setTimeout(() => {
      setCurrentStep(prev => Math.min(prev + 1, replayData.length - 1));
    }, stepDelay / playbackSpeed);

    return () => clearTimeout(timer);
  }, [isPlaying, currentStep, replayData.length, stepDelay, playbackSpeed]);

  // Control functions
  const togglePlayPause = () => setIsPlaying(!isPlaying);
  const nextStep = () => setCurrentStep(prev => Math.min(prev + 1, replayData.length - 1));
  const previousStep = () => setCurrentStep(prev => Math.max(prev - 1, 0));
  const resetReplay = () => {
    setCurrentStep(0);
    setIsPlaying(false);
  };

  const loadReplayFile = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file) {
      const reader = new FileReader();
      reader.onload = (e) => {
        try {
          const data = JSON.parse(e.target?.result as string);
          setReplayData(Array.isArray(data) ? data : [data]);
          setCurrentStep(0);
          setIsPlaying(false);
        } catch (error) {
          alert('Error parsing JSON file: ' + (error as Error).message);
        }
      };
      reader.readAsText(file);
    }
  };

  if (!replayData || replayData.length === 0 || !currentEvent) {
    return (
      <div style={{ 
        padding: '40px', 
        textAlign: 'center',
        background: 'linear-gradient(135deg, #0a0a0a 0%, #1a1a2e 50%, #0a0a0a 100%)',
        color: '#ff4444',
        borderRadius: '8px'
      }}>
        <h3>❌ No Replay Data</h3>
        <p>Please provide eventLog prop to the ReplayViewer component.</p>
      </div>
    );
  }

  return (
    <div style={{ 
      fontFamily: 'Courier New, monospace', 
      background: 'linear-gradient(135deg, #0a0a0a 0%, #1a1a2e 50%, #0a0a0a 100%)',
      color: '#00ff00',
      minHeight: '100vh',
      padding: '20px'
    }}>
      {/* Header */}
      <div style={{ 
        textAlign: 'center', 
        marginBottom: '20px',
        padding: '15px',
        background: 'rgba(0, 0, 0, 0.8)',
        borderRadius: '8px',
        border: '2px solid #00ff00'
      }}>
        <h1 style={{ 
          margin: '0 0 10px 0', 
          color: '#ffd700', 
          fontSize: '2em',
          textShadow: '0 0 10px #ffd700'
        }}>
          ⚔️ WH40K AI Battle Replay ⚔️
        </h1>
        <div style={{ display: 'flex', justifyContent: 'center', gap: '15px', alignItems: 'center' }}>
          <input 
            type="file" 
            accept=".json" 
            onChange={loadReplayFile} 
            style={{ 
              background: '#002200', 
              color: '#00ff00', 
              border: '1px solid #00ff00', 
              padding: '8px 12px',
              borderRadius: '4px',
              fontSize: '12px'
            }} 
          />
          <span style={{ fontSize: '12px', color: '#888' }}>
            Upload your replay JSON file
          </span>
        </div>
      </div>

      {/* Game Info HUD */}
      <div style={{ 
        display: 'grid', 
        gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', 
        gap: '15px', 
        marginBottom: '20px',
        padding: '15px',
        background: 'rgba(0, 34, 0, 0.6)',
        borderRadius: '8px',
        border: '1px solid rgba(0, 255, 0, 0.3)'
      }}>
        <div style={{ 
          padding: '12px', 
          background: 'rgba(36, 68, 136, 0.3)', 
          borderRadius: '6px', 
          borderLeft: '4px solid #ffd700' 
        }}>
          <div style={{ fontSize: '0.8em', color: '#aaa', marginBottom: '4px' }}>Turn</div>
          <div style={{ fontSize: '1.4em', fontWeight: 'bold', color: '#00ff00' }}>
            {currentEvent.turn}
          </div>
        </div>
        
        <div style={{ 
          padding: '12px', 
          background: 'rgba(36, 68, 136, 0.3)', 
          borderRadius: '6px', 
          borderLeft: '4px solid #ffd700' 
        }}>
          <div style={{ fontSize: '0.8em', color: '#aaa', marginBottom: '4px' }}>Action</div>
          <div style={{ fontSize: '1.1em', fontWeight: 'bold', color: '#00ff00' }}>
            {ACTION_NAMES[currentEvent.action] || `Action ${currentEvent.action}`}
          </div>
        </div>
        
        <div style={{ 
          padding: '12px', 
          background: 'rgba(36, 68, 136, 0.3)', 
          borderRadius: '6px', 
          borderLeft: '4px solid #ffd700' 
        }}>
          <div style={{ fontSize: '0.8em', color: '#aaa', marginBottom: '4px' }}>Reward</div>
          <div style={{ 
            fontSize: '1.4em', 
            fontWeight: 'bold',
            color: currentEvent.reward > 0 ? '#4ade80' : currentEvent.reward < 0 ? '#f87171' : '#ffff00'
          }}>
            {currentEvent.reward?.toFixed(2) || '0.00'}
          </div>
        </div>
        
        <div style={{ 
          padding: '12px', 
          background: 'rgba(36, 68, 136, 0.3)', 
          borderRadius: '6px', 
          borderLeft: '4px solid #4488ff' 
        }}>
          <div style={{ fontSize: '0.8em', color: '#aaa', marginBottom: '4px' }}>Player Units</div>
          <div style={{ fontSize: '1.4em', fontWeight: 'bold', color: '#4488ff' }}>
            {currentEvent.enemy_units_alive}
          </div>
        </div>
        
        <div style={{ 
          padding: '12px', 
          background: 'rgba(36, 68, 136, 0.3)', 
          borderRadius: '6px', 
          borderLeft: '4px solid #ff4444' 
        }}>
          <div style={{ fontSize: '0.8em', color: '#aaa', marginBottom: '4px' }}>AI Units</div>
          <div style={{ fontSize: '1.4em', fontWeight: 'bold', color: '#ff4444' }}>
            {currentEvent.ai_units_alive}
          </div>
        </div>
        
        <div style={{ 
          padding: '12px', 
          background: 'rgba(36, 68, 136, 0.3)', 
          borderRadius: '6px', 
          borderLeft: '4px solid #ffd700' 
        }}>
          <div style={{ fontSize: '0.8em', color: '#aaa', marginBottom: '4px' }}>Progress</div>
          <div style={{ fontSize: '1.2em', fontWeight: 'bold', color: '#00ff00' }}>
            {currentStep + 1} / {replayData.length}
          </div>
        </div>
      </div>

      {/* Hexagonal Game Board - Matching your Board.tsx implementation */}
      <div style={{ 
        marginBottom: '20px',
        position: 'relative',
        display: 'flex',
        justifyContent: 'center'
      }}>
        <div 
          ref={boardRef}
          style={{
            background: '#000',
            borderRadius: '8px',
            border: '2px solid #00ff00'
          }}
        />
        
        {/* Game Over Overlay */}
        {currentEvent.game_over && (
          <div style={{
            position: 'absolute',
            top: '50%',
            left: '50%',
            transform: 'translate(-50%, -50%)',
            background: 'rgba(255, 0, 0, 0.95)',
            color: 'white',
            padding: '30px 50px',
            borderRadius: '12px',
            fontSize: '28px',
            fontWeight: 'bold',
            textAlign: 'center',
            border: '4px solid #ff0000',
            boxShadow: '0 0 30px rgba(255, 0, 0, 0.8)',
            zIndex: 1000
          }}>
            🔴 GAME OVER 🔴
            <div style={{ fontSize: '16px', marginTop: '10px', fontWeight: 'normal' }}>
              Battle concluded on turn {currentEvent.turn}
            </div>
          </div>
        )}
      </div>

      {/* Controls */}
      <div style={{ 
        display: 'flex', 
        justifyContent: 'center', 
        alignItems: 'center',
        gap: '15px',
        padding: '20px',
        background: 'rgba(0, 0, 0, 0.8)',
        borderRadius: '8px',
        border: '1px solid rgba(0, 255, 0, 0.3)',
        flexWrap: 'wrap'
      }}>
        <button 
          onClick={togglePlayPause}
          style={{
            background: isPlaying 
              ? 'linear-gradient(145deg, #ff9900, #cc7700)' 
              : 'linear-gradient(145deg, #00ff00, #00cc00)',
            color: '#000',
            border: 'none',
            padding: '12px 24px',
            borderRadius: '6px',
            cursor: 'pointer',
            fontFamily: 'inherit',
            fontWeight: 'bold',
            fontSize: '14px',
            textTransform: 'uppercase',
            letterSpacing: '1px',
            transition: 'all 0.3s ease',
            boxShadow: '0 4px 8px rgba(0, 0, 0, 0.3)'
          }}
        >
          {isPlaying ? '⏸️ PAUSE' : '▶️ PLAY'}
        </button>
        
        <button 
          onClick={previousStep} 
          disabled={currentStep === 0}
          style={{ 
            background: currentStep === 0 ? '#333' : 'linear-gradient(145deg, #244488, #1a3366)', 
            color: currentStep === 0 ? '#666' : '#fff', 
            border: 'none', 
            padding: '10px 20px', 
            borderRadius: '6px', 
            cursor: currentStep === 0 ? 'not-allowed' : 'pointer',
            fontFamily: 'inherit',
            fontSize: '12px',
            textTransform: 'uppercase',
            transition: 'all 0.3s ease'
          }}
        >
          ⏮️ PREV
        </button>
        
        <button 
          onClick={nextStep} 
          disabled={currentStep === replayData.length - 1}
          style={{ 
            background: currentStep === replayData.length - 1 ? '#333' : 'linear-gradient(145deg, #244488, #1a3366)', 
            color: currentStep === replayData.length - 1 ? '#666' : '#fff', 
            border: 'none', 
            padding: '10px 20px', 
            borderRadius: '6px', 
            cursor: currentStep === replayData.length - 1 ? 'not-allowed' : 'pointer',
            fontFamily: 'inherit',
            fontSize: '12px',
            textTransform: 'uppercase',
            transition: 'all 0.3s ease'
          }}
        >
          ⏭️ NEXT
        </button>
        
        <button 
          onClick={resetReplay}
          style={{ 
            background: 'linear-gradient(145deg, #882222, #661111)', 
            color: '#fff', 
            border: 'none', 
            padding: '10px 20px', 
            borderRadius: '6px', 
            cursor: 'pointer',
            fontFamily: 'inherit',
            fontSize: '12px',
            textTransform: 'uppercase',
            transition: 'all 0.3s ease'
          }}
        >
          ⏹️ RESET
        </button>

        <div style={{ 
          display: 'flex', 
          alignItems: 'center', 
          gap: '10px', 
          marginLeft: '20px',
          padding: '8px 16px',
          background: 'rgba(0, 255, 0, 0.1)',
          borderRadius: '6px',
          border: '1px solid rgba(0, 255, 0, 0.3)'
        }}>
          <span style={{ fontSize: '12px', fontWeight: 'bold', color: '#00ff00' }}>SPEED:</span>
          <input 
            type="range" 
            min="0.2" 
            max="3" 
            step="0.2" 
            value={playbackSpeed} 
            onChange={(e) => setPlaybackSpeed(parseFloat(e.target.value))}
            style={{ 
              width: '100px',
              height: '4px',
              background: '#333',
              borderRadius: '2px',
              outline: 'none'
            }}
          />
          <span style={{ 
            fontSize: '12px', 
            fontWeight: 'bold', 
            color: '#ffd700',
            minWidth: '40px'
          }}>
            {playbackSpeed.toFixed(1)}x
          </span>
        </div>
      </div>

      {/* Action History */}
      <div style={{ 
        marginTop: '20px',
        padding: '15px',
        background: 'rgba(0, 0, 0, 0.6)',
        borderRadius: '8px',
        border: '1px solid rgba(0, 255, 0, 0.3)'
      }}>
        <h3 style={{ 
          margin: '0 0 15px 0', 
          color: '#ffd700', 
          fontSize: '1.2em',
          textAlign: 'center'
        }}>
          📋 Current Action
        </h3>
        <div style={{ 
          textAlign: 'center',
          fontSize: '16px',
          lineHeight: '1.5'
        }}>
          <div style={{ marginBottom: '8px' }}>
            <strong style={{ color: '#00ff00' }}>
              {ACTION_NAMES[currentEvent.action] || `Unknown Action ${currentEvent.action}`}
            </strong>
          </div>
          <div style={{ 
            color: currentEvent.reward > 0 ? '#4ade80' : currentEvent.reward < 0 ? '#f87171' : '#ffff00',
            fontSize: '14px'
          }}>
            Reward: <strong>{currentEvent.reward?.toFixed(2) || '0.00'}</strong>
          </div>
          {currentEvent.game_over && (
            <div style={{ 
              marginTop: '10px',
              color: '#ff4444',
              fontWeight: 'bold',
              fontSize: '16px'
            }}>
              🚨 BATTLE CONCLUDED 🚨
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default ReplayViewer;