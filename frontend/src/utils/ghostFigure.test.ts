// @vitest-environment jsdom
// Verrou structurel de buildGhostFigure : forme et dimensions du socle, rotation, nombre
// d'enfants, masque et dimensions du portrait, variante d'icône par joueur. PIXI est mocké : le
// test observe les appels de dessin (nom + arguments) et la structure du container, pas le rendu.
import { beforeEach, describe, expect, it, vi } from "vitest";
import { orientationStepToRadians } from "../constants/gameConfig";
import type { Unit } from "../types/game";
import {
  getNonRoundBasePixelLayout,
  getNonRoundIconRadius,
  getSquareCornerRadiusPx,
} from "./unitBaseDisplay";

vi.mock("pixi.js-legacy", () => {
  class Container {
    children: unknown[] = [];
    addChild(child: unknown): unknown {
      this.children.push(child);
      return child;
    }
    getChildByName(name: string): unknown {
      return this.children.find((c) => (c as { name?: string }).name === name) ?? null;
    }
  }
  class Graphics {
    name = "";
    rotation = 0;
    calls: Array<{ name: string; args: unknown[] }> = [];
    beginFill(...args: unknown[]): this {
      this.calls.push({ name: "beginFill", args });
      return this;
    }
    endFill(...args: unknown[]): this {
      this.calls.push({ name: "endFill", args });
      return this;
    }
    drawCircle(...args: unknown[]): this {
      this.calls.push({ name: "drawCircle", args });
      return this;
    }
    drawEllipse(...args: unknown[]): this {
      this.calls.push({ name: "drawEllipse", args });
      return this;
    }
    drawRoundedRect(...args: unknown[]): this {
      this.calls.push({ name: "drawRoundedRect", args });
      return this;
    }
  }
  class Sprite {
    anchor = { set: vi.fn() };
    width = 0;
    height = 0;
    mask: unknown = null;
    texture: unknown;
    constructor(texture: unknown) {
      this.texture = texture;
    }
  }
  const Texture = { from: vi.fn((path: string) => ({ path })) };
  return { Container, Graphics, Sprite, Texture };
});

import * as PIXI from "pixi.js-legacy";
import { buildGhostFigure, GHOST_BASE_SHAPE_NAME } from "./ghostFigure";

type GraphicsCall = { name: string; args: unknown[] };
type MockGraphics = PIXI.Graphics & { calls: GraphicsCall[] };
type MockSprite = PIXI.Sprite & { texture: { path: string } };

const HEX_RADIUS = 20;

function makeUnit(overrides: Partial<Unit>): Unit {
  return {
    id: 1,
    player: 1,
    col: 0,
    row: 0,
    HP_CUR: 1,
    MOVE: 6,
    RNG_WEAPONS: [],
    CC_WEAPONS: [],
    ...overrides,
  } as Unit;
}

function callNames(g: PIXI.Graphics): string[] {
  return (g as MockGraphics).calls.map((c) => c.name);
}

function callArgs(g: PIXI.Graphics, name: string): unknown[] {
  const call = (g as MockGraphics).calls.find((c) => c.name === name);
  if (!call) throw new Error(`Graphics.${name} never called`);
  return call.args;
}

describe("buildGhostFigure", () => {
  beforeEach(() => {
    vi.mocked(PIXI.Texture.from).mockClear();
  });

  it("socle rond : cercle au diamètre ICON_SCALE, rotation nulle, socle + portrait sans masque", () => {
    const unit = makeUnit({ BASE_SHAPE: "round", BASE_SIZE: 1, ICON: "a.webp", ICON_SCALE: 1.4 });
    const { container, base } = buildGhostFigure(unit, 1, HEX_RADIUS, 3);

    expect(base.name).toBe(GHOST_BASE_SHAPE_NAME);
    expect(container.getChildByName(GHOST_BASE_SHAPE_NAME)).toBe(base);
    expect(callNames(base)).toContain("drawCircle");
    expect(callNames(base)).not.toContain("drawEllipse");
    expect(callArgs(base, "drawCircle")).toEqual([0, 0, 14]);
    expect(base.rotation).toBe(0);
    expect(container.children).toHaveLength(2);
    const sprite = container.children[1] as MockSprite;
    expect(sprite.mask).toBeNull();
    expect(sprite.width).toBe(28);
    expect(sprite.height).toBe(28);
    expect(sprite.anchor.set).toHaveBeenCalledWith(0.5);
    expect(PIXI.Texture.from).toHaveBeenCalledWith("a.webp");
  });

  it("socle ovale joueur 2 : ellipse aux rayons du layout, rotation du pas, masque circulaire, icône _red", () => {
    const unit = makeUnit({ BASE_SHAPE: "oval", BASE_SIZE: [4, 2], ICON: "a.webp" });
    const { container, base } = buildGhostFigure(unit, 2, HEX_RADIUS, 3);

    const nr = getNonRoundBasePixelLayout(unit, HEX_RADIUS);
    if (!nr) throw new Error("layout ovale attendu");
    expect(callArgs(base, "beginFill")).toEqual([0x882222, 0.7]);
    expect(callArgs(base, "drawEllipse")).toEqual([0, 0, nr.outerRx, nr.outerRy]);
    expect(base.rotation).toBeCloseTo(orientationStepToRadians(3));
    expect(container.children).toHaveLength(3);
    expect(container.children[0]).toBe(base);
    const maskG = container.children[1] as MockGraphics;
    expect(callNames(maskG)).toContain("drawCircle");
    const sprite = container.children[2] as MockSprite;
    expect(sprite.mask).toBe(maskG);
    const iconR = getNonRoundIconRadius(unit, HEX_RADIUS);
    if (iconR == null) throw new Error("rayon d'icône non rond attendu");
    expect(sprite.width).toBe(iconR * 2);
    expect(sprite.height).toBe(sprite.width);
    expect(PIXI.Texture.from).toHaveBeenCalledWith("a_red.webp");
    expect(sprite.texture.path).toBe("a_red.webp");
  });

  it("socle carré joueur 1 : rectangle arrondi aux dimensions du layout, rotation du pas, portrait masqué", () => {
    const unit = makeUnit({ BASE_SHAPE: "square", BASE_SIZE: 2, ICON: "a.webp" });
    const { container, base } = buildGhostFigure(unit, 1, HEX_RADIUS, 2);

    expect(callArgs(base, "beginFill")).toEqual([0x1d4ed8, 0.7]);
    expect(callArgs(base, "drawRoundedRect")).toEqual([
      -30,
      -30,
      60,
      60,
      getSquareCornerRadiusPx(),
    ]);
    expect(callNames(base)).not.toContain("drawEllipse");
    expect(base.rotation).toBeCloseTo(orientationStepToRadians(2));
    expect(container.children).toHaveLength(3);
    const maskG = container.children[1] as MockGraphics;
    const sprite = container.children[2] as MockSprite;
    expect(sprite.mask).toBe(maskG);
    const iconR = getNonRoundIconRadius(unit, HEX_RADIUS);
    if (iconR == null) throw new Error("rayon d'icône non rond attendu");
    expect(callArgs(maskG, "drawCircle")).toEqual([0, 0, iconR]);
    expect(sprite.width).toBe(iconR * 2);
    expect(sprite.height).toBe(sprite.width);
    expect(PIXI.Texture.from).toHaveBeenCalledWith("a.webp");
  });

  it("sans ICON : le container ne porte que le socle", () => {
    const unit = makeUnit({ BASE_SHAPE: "round", BASE_SIZE: 1 });
    const { container, base } = buildGhostFigure(unit, 1, HEX_RADIUS, 3);

    expect(container.children).toHaveLength(1);
    expect(container.children[0]).toBe(base);
    expect(PIXI.Texture.from).not.toHaveBeenCalled();
  });
});
