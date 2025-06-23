"use strict";
var __assign = (this && this.__assign) || function () {
    __assign = Object.assign || function(t) {
        for (var s, i = 1, n = arguments.length; i < n; i++) {
            s = arguments[i];
            for (var p in s) if (Object.prototype.hasOwnProperty.call(s, p))
                t[p] = s[p];
        }
        return t;
    };
    return __assign.apply(this, arguments);
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.default = Board;
// src/components/Board.tsx
var react_1 = require("react");
var PIXI = require("pixi.js");
var Intercessor_1 = require("../roster/space_marine/Intercessor");
var AssaultIntercessor_1 = require("../roster/space_marine/AssaultIntercessor");
var BOARD_WIDTH = 10;
var BOARD_HEIGHT = 8;
var CELL_SIZE = 48;
var initialUnits = [
    new Intercessor_1.Intercessor("I1", [2, 2]),
    new AssaultIntercessor_1.AssaultIntercessor("A1", [5, 3]),
    new Intercessor_1.Intercessor("I2", [3, 5]),
];
function Board() {
    var containerRef = (0, react_1.useRef)(null);
    var _a = (0, react_1.useState)(null), selectedId = _a[0], setSelectedId = _a[1];
    var _b = (0, react_1.useState)(initialUnits), units = _b[0], setUnits = _b[1];
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
        setUnits(function (units) {
            return units.map(function (u, i) {
                return i === selectedId ? Object.assign(Object.create(Object.getPrototypeOf(u)), __assign(__assign({}, u), { pos: [x, y] })) : u;
            });
        });
        setSelectedId(null);
    }
    (0, react_1.useEffect)(function () {
        if (!containerRef.current)
            return;
        containerRef.current.innerHTML = "";
        var app = new PIXI.Application({
            width: BOARD_WIDTH * CELL_SIZE,
            height: BOARD_HEIGHT * CELL_SIZE,
            backgroundColor: 0x222222,
            antialias: true,
            resolution: window.devicePixelRatio || 1,
            autoDensity: true,
        });
        containerRef.current.appendChild(app.view);
        var _loop_1 = function (x) {
            var _loop_2 = function (y) {
                var cell = new PIXI.Graphics();
                cell.lineStyle(1, 0x555555, 1);
                cell.beginFill(0x000000, 0.01);
                cell.drawRect(0, 0, CELL_SIZE, CELL_SIZE);
                cell.endFill();
                cell.x = x * CELL_SIZE;
                cell.y = y * CELL_SIZE;
                cell.interactive = true;
                cell.buttonMode = true;
                cell.on("pointerdown", function () {
                    moveSelectedUnit(x, y);
                });
                app.stage.addChild(cell);
            };
            for (var y = 0; y < BOARD_HEIGHT; y++) {
                _loop_2(y);
            }
        };
        // Draw grid with clickable cells
        for (var x = 0; x < BOARD_WIDTH; x++) {
            _loop_1(x);
        }
        // Draw units
        units.forEach(function (unit, i) {
            var container = new PIXI.Container();
            container.x = unit.pos[0] * CELL_SIZE;
            container.y = unit.pos[1] * CELL_SIZE;
            // Highlight if selected
            if (selectedId === i) {
                var highlight = new PIXI.Graphics();
                highlight.lineStyle(3, 0xffd700, 1);
                highlight.drawCircle(CELL_SIZE / 2, CELL_SIZE / 2, CELL_SIZE / 2 - 2);
                container.addChild(highlight);
            }
            // Draw unit circle
            var circle = new PIXI.Graphics();
            circle.beginFill(getColor(unit));
            circle.drawCircle(CELL_SIZE / 2, CELL_SIZE / 2, CELL_SIZE / 2 - 6);
            circle.endFill();
            circle.interactive = true;
            circle.buttonMode = true;
            circle.on("pointerdown", function () { return setSelectedId(i); });
            container.addChild(circle);
            // Draw icon letter
            var label = new PIXI.Text(getIconLetter(unit), {
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
            var hpLabel = new PIXI.Text("HP: ".concat(unit.hp), {
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
        return function () {
            app.destroy(true, { children: true });
            if (containerRef.current)
                containerRef.current.innerHTML = "";
        };
    }, [units, selectedId]);
    return <div ref={containerRef}/>;
}
