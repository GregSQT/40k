// frontend/src/components/BoardInteractions.tsx
import * as PIXI from 'pixi.js-legacy';
import type { Unit } from "../types/game";

interface BoardConfig {
  cols: number;
  rows: number;
  hex_radius: number;
  margin: number;
  colors: {
    [key: string]: string;
  };
  wall_hexes?: [number, number][];
}

interface InteractionOptions {
  phase: "move" | "shoot" | "charge" | "combat";
  mode: "select" | "movePreview" | "attackPreview" | "chargePreview";
  selectedUnitId: number | null;
  units: Unit[];
  availableCells?: { col: number; row: number }[];
  attackCells?: { col: number; row: number }[];
  coverCells?: { col: number; row: number }[];
  chargeCells?: { col: number; row: number }[];
  onCancelCharge?: () => void;
  onCancelMove?: () => void;
  targetPreview?: any;
  onCancelTargetPreview?: () => void;
}

/**
 * Sets up ALL board interactions - extracted from Board.tsx
 * Includes: hex clicks, right-click cancels, charge cancellation, event system
 */
export const setupBoardInteractions = (
  app: PIXI.Application, 
  boardConfig: BoardConfig, 
  options: InteractionOptions
): void => {
  if (!app || !app.stage || !boardConfig) return;
  
  try {
    const {
      phase,
      mode,
      selectedUnitId,
      units,
      availableCells = [],
      attackCells = [],
      coverCells = [],
      chargeCells = [],
      onCancelCharge,
      onCancelMove,
      targetPreview,
      onCancelTargetPreview
    } = options;

    // Extract board configuration values
    const BOARD_COLS = boardConfig.cols;
    const BOARD_ROWS = boardConfig.rows;
    const HEX_RADIUS = boardConfig.hex_radius;
    const MARGIN = boardConfig.margin;
    const HEX_WIDTH = 1.5 * HEX_RADIUS;
    const HEX_HEIGHT = Math.sqrt(3) * HEX_RADIUS;
    const HEX_HORIZ_SPACING = HEX_WIDTH;
    const HEX_VERT_SPACING = HEX_HEIGHT;

    // Pre-compute wallHexSet
    const wallHexSet = new Set<string>(
      (boardConfig.wall_hexes || []).map(([c, r]: [number, number]) => `${c},${r}`)
    );

    // Find containers created by BoardDisplay
    const baseHexContainer = app.stage.getChildByName('baseHexes') as PIXI.Container;
    const highlightContainer = app.stage.getChildByName('highlights') as PIXI.Container;

    if (!baseHexContainer || !highlightContainer) {
      console.warn('⚠️ Board containers not found - interactions may not work properly');
      return;
    }

    // EXACT hex interaction logic from Board.tsx
    for (let col = 0; col < BOARD_COLS; col++) {
      for (let row = 0; row < BOARD_ROWS; row++) {
        const isWallHex = wallHexSet.has(`${col},${row}`);
        
        // Check highlight states - EXACT from Board.tsx
        const isAvailable = availableCells.some(cell => cell.col === col && cell.row === row);
        const isAttackable = attackCells.some(cell => cell.col === col && cell.row === row);
        const isInCover = coverCells.some(cell => cell.col === col && cell.row === row);
        const isChargeable = chargeCells.some(cell => cell.col === col && cell.row === row);

        // Calculate hex index to find the correct graphics object
        const hexIndex = row * BOARD_COLS + col;
        
        // Find corresponding base hex - each hex has 2 children (graphics + text)
        const baseHex = baseHexContainer.getChildAt(hexIndex * 2) as PIXI.Graphics;
        
        // Find highlight hex using sequential mapping based on highlight cells
        let highlightHex: PIXI.Graphics | null = null;
        if (isChargeable || isAttackable || isInCover || isAvailable) {
          // Calculate which highlight index this hex should be at
          let highlightSeqIndex = 0;
          for (let checkCol = 0; checkCol < BOARD_COLS; checkCol++) {
            for (let checkRow = 0; checkRow < BOARD_ROWS; checkRow++) {
              const checkAvailable = availableCells.some(cell => cell.col === checkCol && cell.row === checkRow);
              const checkAttackable = attackCells.some(cell => cell.col === checkCol && cell.row === checkRow);
              const checkInCover = coverCells.some(cell => cell.col === checkCol && cell.row === checkRow);
              const checkChargeable = chargeCells.some(cell => cell.col === checkCol && cell.row === checkRow);
              
              if (checkChargeable || checkAttackable || checkInCover || checkAvailable) {
                if (checkCol === col && checkRow === row) {
                  highlightHex = highlightContainer.getChildAt(highlightSeqIndex) as PIXI.Graphics;
                  break;
                }
                highlightSeqIndex++;
              }
            }
            if (highlightHex) break;
          }
        }

        // Setup base hex interactions - EXACT from Board.tsx
        if (baseHex) {
          // Cancel charge on re-click of active unit during charge preview
          if (mode === "chargePreview" && selectedUnitId !== null) {
            const unit = units.find(u => u.id === selectedUnitId);
            if (unit && col === unit.col && row === unit.row) {
              baseHex.eventMode = isWallHex ? 'none' : 'static';
              baseHex.cursor = "pointer";
              baseHex.on("pointerdown", (e: PIXI.FederatedPointerEvent) => {
                if (e.button === 0) onCancelCharge?.();
              });
            }
          }

          // Base cell clicks for unit position (charge cancel) and general hex clicks - EXACT from Board.tsx
          baseHex.eventMode = 'static';
          baseHex.cursor = "pointer";
          baseHex.on("pointerdown", (e: PIXI.FederatedPointerEvent) => {
            if (e.button === 0) {
              const unit = units.find(u => u.id === selectedUnitId);
              if (mode === "chargePreview" && unit?.col === col && unit.row === row) {
                onCancelCharge?.();
              } else {
                window.dispatchEvent(new CustomEvent('boardHexClick', {
                  detail: { col, row, phase, mode, selectedUnitId }
                }));
              }
            }
            if (e.button === 2) {
              onCancelMove?.();
            }
          });
        }

        // Setup highlight hex interactions - EXACT from Board.tsx
        if (highlightHex) {
          highlightHex.eventMode = isWallHex ? 'none' : 'static';
          highlightHex.cursor = "pointer";
          
          // Use global event system for all hex clicks - EXACT from Board.tsx
          highlightHex.on("pointerdown", (e: PIXI.FederatedPointerEvent) => {
            if (e.button === 0) {
              window.dispatchEvent(new CustomEvent('boardHexClick', {
                detail: { col, row, phase, mode, selectedUnitId }
              }));
            }
          });
        }
      }
    }

    // Right click cancels move/attack preview - EXACT from Board.tsx
    if (app.view && app.view.addEventListener) {
      const canvas = app.view as HTMLCanvasElement;
      const contextMenuHandler = (e: Event) => {
        e.preventDefault();
        
        if (phase === "shoot") {
          // During shooting phase, only cancel target preview if one exists
          if (targetPreview) {
            onCancelTargetPreview?.();
          }
          // If no target preview, do nothing (don't cancel the whole shooting)
        } else if (mode === "movePreview" || mode === "attackPreview") {
          onCancelMove?.();
        }
      };

      // Add context menu listener
      canvas.addEventListener("contextmenu", contextMenuHandler);
      
      // Store reference for cleanup
      (canvas as any)._boardContextMenuHandler = contextMenuHandler;
    }

  } catch (error) {
    console.error('❌ Error setting up board interactions:', error);
    throw error;
  }
};

/**
 * Cleanup board interactions - important for memory management
 */
export const cleanupBoardInteractions = (app: PIXI.Application): void => {
  if (!app || !app.view) return;
  
  try {
    const canvas = app.view as HTMLCanvasElement;
    const handler = (canvas as any)._boardContextMenuHandler;
    
    if (handler) {
      canvas.removeEventListener("contextmenu", handler);
      delete (canvas as any)._boardContextMenuHandler;
    }
    
  } catch (error) {
    console.error('❌ Error cleaning up board interactions:', error);
  }
};