// @vitest-environment jsdom
// Verrou structurel de buildGhostFigure : forme du socle, rotation, nombre d'enfants, masque du
// portrait et variante d'icône par joueur. PIXI est mocké : le test observe les appels de dessin
// et la structure du container, pas le rendu.
import { beforeEach, describe, expect, it, vi } from "vitest";
import { orientationStepToRadians } from "../constants/gameConfig";
import type { Unit } from "../types/game";

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
    calls: string[] = [];
    beginFill(): this {
      this.calls.push("beginFill");
      return this;
    }
    endFill(): this {
      this.calls.push("endFill");
      return this;
    }
    drawCircle(): this {
      this.calls.push("drawCircle");
      return this;
    }
    drawEllipse(): this {
      this.calls.push("drawEllipse");
      return this;
    }
    drawRoundedRect(): this {
      this.calls.push("drawRoundedRect");
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

type MockGraphics = PIXI.Graphics & { calls: string[] };
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

describe("buildGhostFigure", () => {
  beforeEach(() => {
    vi.mocked(PIXI.Texture.from).mockClear();
  });

  it("socle rond : cercle, rotation nulle, socle + portrait sans masque", () => {
    const unit = makeUnit({ BASE_SHAPE: "round", BASE_SIZE: 1, ICON: "a.webp" });
    const { container, base } = buildGhostFigure(unit, 1, HEX_RADIUS, 3);

    expect(base.name).toBe(GHOST_BASE_SHAPE_NAME);
    expect(container.getChildByName(GHOST_BASE_SHAPE_NAME)).toBe(base);
    expect((base as MockGraphics).calls).toContain("drawCircle");
    expect((base as MockGraphics).calls).not.toContain("drawEllipse");
    expect(base.rotation).toBe(0);
    expect(container.children).toHaveLength(2);
    const sprite = container.children[1] as MockSprite;
    expect(sprite.mask).toBeNull();
    expect(sprite.anchor.set).toHaveBeenCalledWith(0.5);
    expect(PIXI.Texture.from).toHaveBeenCalledWith("a.webp");
  });

  it("socle ovale joueur 2 : ellipse, rotation du pas, masque circulaire, icône _red", () => {
    const unit = makeUnit({ BASE_SHAPE: "oval", BASE_SIZE: [4, 2], ICON: "a.webp" });
    const { container, base } = buildGhostFigure(unit, 2, HEX_RADIUS, 3);

    expect((base as MockGraphics).calls).toContain("drawEllipse");
    expect(base.rotation).toBeCloseTo(orientationStepToRadians(3));
    expect(container.children).toHaveLength(3);
    expect(container.children[0]).toBe(base);
    const maskG = container.children[1] as MockGraphics;
    expect(maskG.calls).toContain("drawCircle");
    const sprite = container.children[2] as MockSprite;
    expect(sprite.mask).toBe(maskG);
    expect(PIXI.Texture.from).toHaveBeenCalledWith("a_red.webp");
    expect(sprite.texture.path).toBe("a_red.webp");
  });

  it("sans ICON : le container ne porte que le socle", () => {
    const unit = makeUnit({ BASE_SHAPE: "round", BASE_SIZE: 1 });
    const { container, base } = buildGhostFigure(unit, 1, HEX_RADIUS, 3);

    expect(container.children).toHaveLength(1);
    expect(container.children[0]).toBe(base);
    expect(PIXI.Texture.from).not.toHaveBeenCalled();
  });
});
