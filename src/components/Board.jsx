"use strict";
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", { value: true });
exports.default = Board;
// src/components/Board.tsx
const react_1 = require("react");
const PIXI = __importStar(require("pixi.js"));
const Intercessor_1 = require("../roster/space_marine/Intercessor");
const AssaultIntercessor_1 = require("../roster/space_marine/AssaultIntercessor");
const BOARD_WIDTH = 10;
const BOARD_HEIGHT = 8;
const CELL_SIZE = 48;
const initialUnits = [
    new Intercessor_1.Intercessor("I1", [2, 2]),
    new AssaultIntercessor_1.AssaultIntercessor("A1", [5, 3]),
    new Intercessor_1.Intercessor("I2", [3, 5]),
];
function Board() {
    const containerRef = (0, react_1.useRef)(null);
    const [selectedId, setSelectedId] = (0, react_1.useState)(null);
    const [units, setUnits] = (0, react_1.useState)(initialUnits);
    // Helper: Get a display letter for a unit type
    function getIconLetter(unit) {
        if (unit.constructor.NAME === "Intercessor")
            return "I";
        if (unit.constructor.NAME === "Assault Intercessor")
            return "A";
        return "?";
    }
    // Helper: Get a color for a unit type
    function getColor(unit) {
        if (unit.constructor.NAME === "Assault Intercessor")
            return 0xff3333;
        return 0x0078ff;
    }
    // Move the selected unit to a new (x, y)
    function moveSelectedUnit(x, y) {
        if (selectedId == null)
            return;
        setUnits(units => units.map((u, i) => i === selectedId ? Object.assign(Object.create(Object.getPrototypeOf(u)), Object.assign(Object.assign({}, u), { pos: [x, y] })) : u));
        setSelectedId(null);
    }
    (0, react_1.useEffect)(() => {
        if (!containerRef.current)
            return;
        containerRef.current.innerHTML = "";
        const app = new PIXI.Application({
            width: BOARD_WIDTH * CELL_SIZE,
            height: BOARD_HEIGHT * CELL_SIZE,
            backgroundColor: 0x222222,
            antialias: true,
            resolution: window.devicePixelRatio || 1,
            autoDensity: true,
        });
        containerRef.current.appendChild(app.view);
        // Draw grid with clickable cells
        for (let x = 0; x < BOARD_WIDTH; x++) {
            for (let y = 0; y < BOARD_HEIGHT; y++) {
                const cell = new PIXI.Graphics();
                cell.lineStyle(1, 0x555555, 1);
                cell.beginFill(0x000000, 0.01);
                cell.drawRect(0, 0, CELL_SIZE, CELL_SIZE);
                cell.endFill();
                cell.x = x * CELL_SIZE;
                cell.y = y * CELL_SIZE;
                cell.interactive = true;
                cell.buttonMode = true;
                cell.on("pointerdown", () => {
                    moveSelectedUnit(x, y);
                });
                app.stage.addChild(cell);
            }
        }
        // Draw units
        units.forEach((unit, i) => {
            const container = new PIXI.Container();
            container.x = unit.pos[0] * CELL_SIZE;
            container.y = unit.pos[1] * CELL_SIZE;
            // Highlight if selected
            if (selectedId === i) {
                const highlight = new PIXI.Graphics();
                highlight.lineStyle(3, 0xffd700, 1);
                highlight.drawCircle(CELL_SIZE / 2, CELL_SIZE / 2, CELL_SIZE / 2 - 2);
                container.addChild(highlight);
            }
            // Draw unit circle
            const circle = new PIXI.Graphics();
            circle.beginFill(getColor(unit));
            circle.drawCircle(CELL_SIZE / 2, CELL_SIZE / 2, CELL_SIZE / 2 - 6);
            circle.endFill();
            circle.interactive = true;
            circle.buttonMode = true;
            circle.on("pointerdown", () => setSelectedId(i));
            container.addChild(circle);
            // Draw icon letter
            const label = new PIXI.Text(getIconLetter(unit), {
                fontFamily: "Arial",
                fontSize: 22,
                fill: 0xffffff,
                align: "center",
                fontWeight: "bold",
            });
            label.anchor.set(0.5);
            label.x = CELL_SIZE / 2;
            label.y = CELL_SIZE / 2;
            container.addChild(label);
            // Draw HP
            const hpLabel = new PIXI.Text(`HP: ${unit.hp}`, {
                fontFamily: "Arial",
                fontSize: 14,
                fill: 0x00ff00,
                align: "center",
            });
            hpLabel.anchor.set(0.5);
            hpLabel.x = CELL_SIZE / 2;
            hpLabel.y = CELL_SIZE - 10;
            container.addChild(hpLabel);
            app.stage.addChild(container);
        });
        return () => {
            app.destroy(true, { children: true });
            if (containerRef.current)
                containerRef.current.innerHTML = "";
        };
    }, [units, selectedId]);
    return <div ref={containerRef}/>;
}
