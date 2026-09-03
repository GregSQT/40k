/**
 * Verrou de CÂBLAGE : `UnitRenderer` pose réellement le badge de couvert figurine par figurine.
 *
 * `coverBadgePerModel.test.ts` verrouille la décision ; ce fichier verrouille qu'elle est
 * effectivement appelée par le rendu, avec les bonnes figurines et les bonnes couleurs. Sans lui,
 * la règle pourrait être juste et n'être jamais atteinte par le vrai chemin d'affichage.
 *
 * Scénario : escouade de 5, 4 figurines dans une terrain area et 1 à découvert (la 3e). 13.08
 * exige que CHAQUE figurine remplisse une condition → l'unité n'a pas le couvert.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

/** Graphics minimal : on retient le nom du badge et les couleurs de trait, seuls faits observés. */
class FakeGraphics {
  name = "";
  zIndex = 0;
  children: unknown[] = [];
  strokeColors: number[] = [];
  lineStyle(_width?: number, color?: number) {
    if (typeof color === "number") this.strokeColors.push(color);
    return this;
  }
  beginFill() {
    return this;
  }
  endFill() {
    return this;
  }
  drawCircle() {
    return this;
  }
  moveTo() {
    return this;
  }
  lineTo() {
    return this;
  }
  quadraticCurveTo() {
    return this;
  }
  addChild(child: unknown) {
    this.children.push(child);
    return child;
  }
  destroy() {}
}

class FakeText {
  anchor = { set: () => {} };
  position = { set: () => {} };
  constructor(public text: string) {}
}

class FakeContainer {
  children: FakeGraphics[] = [];
  addChild(child: FakeGraphics) {
    this.children.push(child);
    return child;
  }
  removeChild(child: FakeGraphics) {
    this.children = this.children.filter((c) => c !== child);
    return child;
  }
}

vi.mock("pixi.js-legacy", () => ({
  Graphics: FakeGraphics,
  Text: FakeText,
  Container: FakeContainer,
  Sprite: class {},
  Texture: { WHITE: {} },
}));

const { UnitRenderer } = await import("./UnitRenderer");

/** Gris clair de `drawHiddenEyeBadge` par défaut = couvert EFFECTIF (le -1 BS s'applique). */
const EYE_COVER = 0xc8c8c8;
/** Gris sombre = figurine protégée dans une escouade qui NE qualifie PAS (aucun bonus). */
const EYE_COVER_UNQUALIFIED = 0x6b6b6b;

const TARGET_ID = 7;
const SHOOTER_ID = 3;
/** 5 figurines alignées ; la 3e (index 2) est celle qui est à découvert. */
const MODEL_CENTERS: Array<[number, number]> = [
  [100, 100],
  [120, 100],
  [140, 100],
  [160, 100],
  [180, 100],
];

function buildRenderer(overrides: Record<string, unknown>) {
  const uiElementsContainer = new FakeContainer();
  const props = {
    unit: { id: TARGET_ID, player: 2, RNG_WEAPONS: [] },
    units: [
      { id: SHOOTER_ID, player: 1, RNG_WEAPONS: [] },
      { id: TARGET_ID, player: 2, RNG_WEAPONS: [] },
    ],
    selectedUnitId: SHOOTER_ID,
    centerX: 100,
    centerY: 100,
    HEX_RADIUS: 20,
    app: { stage: new FakeContainer() },
    uiElementsContainer,
    statusBadgePerModel: true,
    modelCenters: MODEL_CENTERS,
    modelHidden: [false, false, false, false, false],
    phase: "shoot",
    mode: "select",
    ...overrides,
  };
  // Seules les props lues par `renderHiddenBadge` sont fournies : en fabriquer quarante autres,
  // sans rapport avec le badge, rendrait le scénario du test illisible.
  const renderer = new UnitRenderer(props as never);
  return { renderer, uiElementsContainer };
}

/** Badges effectivement posés : index de figurine → couleur de l'œil. */
function drawnBadges(container: FakeContainer): Map<number, number> {
  const out = new Map<number, number>();
  for (const child of container.children) {
    const match = /^hidden-badge-\d+-(\d+)$/.exec(child.name);
    if (!match) continue;
    const eye = child.strokeColors.find((c) => c === EYE_COVER || c === EYE_COVER_UNQUALIFIED);
    if (eye !== undefined) out.set(Number(match[1]), eye);
  }
  return out;
}

function renderBadges(overrides: Record<string, unknown>): Map<number, number> {
  const { renderer, uiElementsContainer } = buildRenderer(overrides);
  (renderer as unknown as { renderHiddenBadge: (s: number) => void }).renderHiddenBadge(1);
  return drawnBadges(uiElementsContainer);
}

describe("UnitRenderer — badge de couvert par figurine (4 dans le terrain, 1 dehors)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("ne pose AUCUN badge sur la figurine à découvert", () => {
    const badges = renderBadges({
      shootingTargetInCover: false,
      movePreviewShootingTargetInCoverByUnitId: { [TARGET_ID]: false },
      movePreviewShootingTargetCoverConditionsByUnitId: {
        [TARGET_ID]: ["a", "a", "", "a", "a"],
      },
    });
    expect(badges.has(2)).toBe(false);
  });

  it("pose un badge sur les 4 figurines protégées, alors que l'unité n'a pas le couvert", () => {
    // C'EST le défaut corrigé : avec le booléen d'unité répliqué, ces 4 figurines n'avaient
    // aucun badge alors qu'elles sont visiblement dans le terrain.
    const badges = renderBadges({
      shootingTargetInCover: false,
      movePreviewShootingTargetInCoverByUnitId: { [TARGET_ID]: false },
      movePreviewShootingTargetCoverConditionsByUnitId: {
        [TARGET_ID]: ["a", "a", "", "a", "a"],
      },
    });
    expect([...badges.keys()].sort()).toEqual([0, 1, 3, 4]);
  });

  it("ne prétend PAS que ces figurines bénéficient du -1 BS : badge atténué, jamais plein", () => {
    const badges = renderBadges({
      shootingTargetInCover: false,
      movePreviewShootingTargetInCoverByUnitId: { [TARGET_ID]: false },
      movePreviewShootingTargetCoverConditionsByUnitId: {
        [TARGET_ID]: ["a", "a", "", "a", "a"],
      },
    });
    expect([...badges.values()]).toEqual([
      EYE_COVER_UNQUALIFIED,
      EYE_COVER_UNQUALIFIED,
      EYE_COVER_UNQUALIFIED,
      EYE_COVER_UNQUALIFIED,
    ]);
    expect([...badges.values()]).not.toContain(EYE_COVER);
  });
});

describe("UnitRenderer — badge de couvert par figurine, unité qui qualifie", () => {
  it("pose le badge PLEIN sur les 5 figurines quand toutes remplissent une condition", () => {
    const badges = renderBadges({
      shootingTargetInCover: true,
      movePreviewShootingTargetInCoverByUnitId: { [TARGET_ID]: true },
      movePreviewShootingTargetCoverConditionsByUnitId: {
        [TARGET_ID]: ["a", "b", "a", "b", "a"],
      },
    });
    expect([...badges.keys()].sort()).toEqual([0, 1, 2, 3, 4]);
    expect(new Set(badges.values())).toEqual(new Set([EYE_COVER]));
  });
});

describe("UnitRenderer — repli quand le moteur ne fournit pas le détail par figurine", () => {
  it("garde le comportement historique : booléen d'unité répliqué sur chaque figurine", () => {
    // Couvert calculé côté WASM : aucune condition par figurine n'est transmise.
    const badges = renderBadges({
      shootingTargetInCover: true,
      movePreviewShootingTargetInCoverByUnitId: undefined,
      movePreviewShootingTargetCoverConditionsByUnitId: undefined,
    });
    expect([...badges.keys()].sort()).toEqual([0, 1, 2, 3, 4]);
    expect(new Set(badges.values())).toEqual(new Set([EYE_COVER]));
  });

  it("ne pose aucun badge quand l'unité n'a pas le couvert et qu'aucun détail n'est fourni", () => {
    const badges = renderBadges({
      shootingTargetInCover: false,
      movePreviewShootingTargetInCoverByUnitId: undefined,
      movePreviewShootingTargetCoverConditionsByUnitId: undefined,
    });
    expect(badges.size).toBe(0);
  });
});
