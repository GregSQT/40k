// @vitest-environment jsdom
/**
 * T9 — boardClickHandler : routage clic → callback selon phase/mode.
 *
 * On dispatche des CustomEvents sur window (comme PIXI le fait en production) et on vérifie
 * que le callback approprié est appelé — et que les autres ne le sont pas.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setupBoardClickHandler } from "./boardClickHandler";

function makeCallbacks() {
  return {
    onSelectUnit: vi.fn(),
    onSkipUnit: vi.fn(),
    onSkipShoot: vi.fn(),
    onSkipFight: vi.fn(),
    onStartAttackPreview: vi.fn(),
    onShoot: vi.fn(),
    onCombatAttack: vi.fn(),
    onConfirmMove: vi.fn(),
    onCancelMove: vi.fn(),
    onCancelCharge: vi.fn(),
    onCancelAdvance: vi.fn(),
    onActivateCharge: vi.fn(),
    onValidateCharge: vi.fn(),
    onMoveCharger: vi.fn(),
    onChargeEnemyUnit: vi.fn(),
    onStartMovePreview: vi.fn(),
    onDirectMove: vi.fn(),
    onStartSquadModelMove: vi.fn(),
    onMoveModelInPlan: vi.fn(),
    onMoveModelInChargePlan: vi.fn(),
    onCancelChargeModelMove: vi.fn(),
    onChargeFocusTargetClick: vi.fn(),
    onMovePileInModel: vi.fn(),
    onCancelPileInModelMove: vi.fn(),
    onMoveConsolidationModel: vi.fn(),
    onCancelConsolidationModelMove: vi.fn(),
    onAdvanceMove: vi.fn(),
    onDeployUnit: vi.fn(),
  };
}

function unitClick(detail: {
  unitId: number;
  phase: string;
  mode: string;
  selectedUnitId: number | null;
  clickType?: "left" | "right";
}) {
  window.dispatchEvent(new CustomEvent("boardUnitClick", { detail }));
}

function hexClick(detail: {
  col: number;
  row: number;
  phase: string;
  mode: string;
  selectedUnitId: number | null;
  orientation?: number;
  activeModelId?: string | null;
}) {
  window.dispatchEvent(new CustomEvent("boardHexClick", { detail }));
}

let cbs: ReturnType<typeof makeCallbacks>;

beforeEach(() => {
  cbs = makeCallbacks();
  setupBoardClickHandler(cbs);
});

afterEach(() => {
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// Phase move + mode select
// ---------------------------------------------------------------------------

describe("move + select", () => {
  it("clic gauche sur unité non sélectionnée → onSelectUnit(unitId)", () => {
    unitClick({ unitId: 5, phase: "move", mode: "select", selectedUnitId: null });
    expect(cbs.onSelectUnit).toHaveBeenCalledWith(5);
    expect(cbs.onSkipUnit).not.toHaveBeenCalled();
  });

  it("clic gauche sur unité DÉJÀ sélectionnée → onSelectUnit(null) (désélection)", () => {
    unitClick({ unitId: 5, phase: "move", mode: "select", selectedUnitId: 5 });
    expect(cbs.onSelectUnit).toHaveBeenCalledWith(null);
  });

  it("clic DROIT sur unité sélectionnée → onSkipUnit(unitId)", () => {
    unitClick({ unitId: 5, phase: "move", mode: "select", selectedUnitId: 5, clickType: "right" });
    expect(cbs.onSkipUnit).toHaveBeenCalledWith(5);
    expect(cbs.onSelectUnit).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// Phase move + mode movePreview
// ---------------------------------------------------------------------------

describe("move + movePreview", () => {
  it("clic gauche sur l'unité ACTIVE → onConfirmMove()", () => {
    unitClick({
      unitId: 7,
      phase: "move",
      mode: "movePreview",
      selectedUnitId: 7,
      clickType: "left",
    });
    expect(cbs.onConfirmMove).toHaveBeenCalledTimes(1);
    expect(cbs.onCancelMove).not.toHaveBeenCalled();
  });

  it("clic gauche sur AUTRE unité → onCancelMove()", () => {
    unitClick({ unitId: 8, phase: "move", mode: "movePreview", selectedUnitId: 7 });
    expect(cbs.onCancelMove).toHaveBeenCalledTimes(1);
    expect(cbs.onConfirmMove).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// Phase shoot + mode select
// ---------------------------------------------------------------------------

describe("shoot + select", () => {
  it("clic gauche sur unité non sélectionnée → onSelectUnit(unitId)", () => {
    unitClick({ unitId: 3, phase: "shoot", mode: "select", selectedUnitId: null });
    expect(cbs.onSelectUnit).toHaveBeenCalledWith(3);
  });

  it("clic DROIT sur unité sélectionnée → onSkipShoot(unitId, 'action')", () => {
    unitClick({
      unitId: 3,
      phase: "shoot",
      mode: "select",
      selectedUnitId: 3,
      clickType: "right",
    });
    expect(cbs.onSkipShoot).toHaveBeenCalledWith(3, "action");
    expect(cbs.onSelectUnit).not.toHaveBeenCalled();
  });

  it("clic DROIT sur unité sans sélection active → onSkipShoot(unitId, 'action')", () => {
    unitClick({
      unitId: 3,
      phase: "shoot",
      mode: "select",
      selectedUnitId: null,
      clickType: "right",
    });
    expect(cbs.onSkipShoot).toHaveBeenCalledWith(3, "action");
  });
});

// ---------------------------------------------------------------------------
// Phase charge + mode chargeTargetSelect
// ---------------------------------------------------------------------------

describe("charge + chargeTargetSelect", () => {
  it("clic gauche sur ennemi → onChargeEnemyUnit(selectedId, targetId)", () => {
    unitClick({
      unitId: 99,
      phase: "charge",
      mode: "chargeTargetSelect",
      selectedUnitId: 10,
    });
    expect(cbs.onChargeEnemyUnit).toHaveBeenCalledWith(10, 99);
    expect(cbs.onSelectUnit).not.toHaveBeenCalled();
  });

  it("clic DROIT sur l'unité active → onCancelCharge()", () => {
    unitClick({
      unitId: 10,
      phase: "charge",
      mode: "chargeTargetSelect",
      selectedUnitId: 10,
      clickType: "right",
    });
    expect(cbs.onCancelCharge).toHaveBeenCalledTimes(1);
    expect(cbs.onChargeEnemyUnit).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// Phase fight + mode select
// ---------------------------------------------------------------------------

describe("fight + select", () => {
  it("clic gauche → onSelectUnit(unitId)", () => {
    unitClick({ unitId: 42, phase: "fight", mode: "select", selectedUnitId: null });
    expect(cbs.onSelectUnit).toHaveBeenCalledWith(42);
  });
});

// ---------------------------------------------------------------------------
// Phase fight + mode attackPreview
// ---------------------------------------------------------------------------

describe("fight + attackPreview", () => {
  it("clic droit sur l'attaquant actif → onSkipFight(unitId)", () => {
    unitClick({
      unitId: 42,
      phase: "fight",
      mode: "attackPreview",
      selectedUnitId: 42,
      clickType: "right",
    });
    expect(cbs.onSkipFight).toHaveBeenCalledWith(42);
  });

  it("clic gauche sur une cible → onSelectUnit(targetId)", () => {
    unitClick({
      unitId: 99,
      phase: "fight",
      mode: "attackPreview",
      selectedUnitId: 42,
      clickType: "left",
    });
    expect(cbs.onSelectUnit).toHaveBeenCalledWith(99);
  });
});

// ---------------------------------------------------------------------------
// Clic hexagone — boardHexClick
// ---------------------------------------------------------------------------

describe("boardHexClick — move + select avec unité sélectionnée", () => {
  it("clic hex → onDirectMove(selectedId, col, row, orientation)", () => {
    hexClick({
      col: 5,
      row: 8,
      phase: "move",
      mode: "select",
      selectedUnitId: 10,
      orientation: 2,
    });
    expect(cbs.onDirectMove).toHaveBeenCalledWith(10, 5, 8, 2);
  });
});

describe("boardHexClick — movePreview + move", () => {
  it("clic hex en movePreview → onConfirmMove()", () => {
    hexClick({ col: 5, row: 8, phase: "move", mode: "movePreview", selectedUnitId: 10 });
    expect(cbs.onConfirmMove).toHaveBeenCalledTimes(1);
  });
});

describe("boardHexClick — perModelMove", () => {
  it("clic hex avec activeModelId → onMoveModelInPlan(modelId, col, row)", () => {
    hexClick({
      col: 3,
      row: 4,
      phase: "move",
      mode: "perModelMove",
      selectedUnitId: 10,
      activeModelId: "10#0",
    });
    expect(cbs.onMoveModelInPlan).toHaveBeenCalledWith("10#0", 3, 4);
  });

  it("clic hex sans activeModelId → ne rien appeler", () => {
    hexClick({
      col: 3,
      row: 4,
      phase: "move",
      mode: "perModelMove",
      selectedUnitId: 10,
      activeModelId: null,
    });
    expect(cbs.onMoveModelInPlan).not.toHaveBeenCalled();
  });
});

describe("boardHexClick — deployment", () => {
  it("clic hex en deployment avec unité sélectionnée → onDeployUnit(unitId, col, row)", () => {
    hexClick({
      col: 2,
      row: 3,
      phase: "deployment",
      mode: "select",
      selectedUnitId: 5,
    });
    expect(cbs.onDeployUnit).toHaveBeenCalledWith(5, 2, 3);
  });
});
