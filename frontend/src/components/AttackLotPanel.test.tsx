// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AttackLotRequest, ManualAllocation } from "../hooks/useEngineAPI";
import { AttackLotPanel, lotsByTarget } from "./AttackLotPanel";

afterEach(cleanup);

const unitLabel = (id: string) => `Unit #${id}`;

const LOT_NO_POLICY: AttackLotRequest["lots"][number] = {
  lot_id: 0,
  target_unit_id: "2",
  weapon_name: "Bolt rifle",
  weapon_code: "bolt_rifle",
  n_models: 3,
  n_attacks: 6,
  reroll_choices: { hit: false, wound: false },
};
const LOT_HIT_POLICY: AttackLotRequest["lots"][number] = {
  lot_id: 1,
  target_unit_id: "3",
  weapon_name: "Plasma gun",
  weapon_code: "plasma_gun",
  n_models: 1,
  n_attacks: 1,
  reroll_choices: { hit: true, wound: false },
};
const LOT_WOUND_POLICY: AttackLotRequest["lots"][number] = {
  lot_id: 2,
  target_unit_id: "2",
  weapon_name: "Melta",
  weapon_code: "melta",
  n_models: 1,
  n_attacks: 1,
  reroll_choices: { hit: false, wound: true },
};

function request(lots: AttackLotRequest["lots"], extra: Partial<AttackLotRequest> = {}) {
  return {
    kind: "shoot" as const,
    attacker_unit_id: "1",
    locked_target_unit_id: null,
    policy_only: false,
    lots,
    ...extra,
  };
}

describe("lotsByTarget", () => {
  it("regroupe les lots par unité cible en gardant l'ordre reçu", () => {
    expect(
      lotsByTarget([LOT_NO_POLICY, LOT_HIT_POLICY, LOT_WOUND_POLICY]).map(([t, lots]) => [
        t,
        lots.map((l) => l.lot_id),
      ])
    ).toEqual([
      ["2", [0, 2]],
      ["3", [1]],
    ]);
  });
});

describe("AttackLotPanel — attente de lot (04.03)", () => {
  it("rien à attendre → rien de rendu", () => {
    const { container } = render(
      <AttackLotPanel
        lotRequest={null}
        allocation={null}
        unitLabel={unitLabel}
        onSelectLot={vi.fn()}
        onAllocateModel={vi.fn()}
      />
    );
    expect(container.querySelector('[data-testid="attack-lot-panel"]')).toBeNull();
  });

  it("un lot sans question de relance → clic = choix immédiat, sans politique", () => {
    const onSelectLot = vi.fn();
    render(
      <AttackLotPanel
        lotRequest={request([LOT_NO_POLICY, LOT_HIT_POLICY])}
        allocation={null}
        unitLabel={unitLabel}
        onSelectLot={onSelectLot}
        onAllocateModel={vi.fn()}
      />
    );
    expect(screen.getByText(/choisir l'unité à résoudre/)).toBeTruthy();
    fireEvent.click(screen.getByTestId("lot-0"));
    expect(onSelectLot).toHaveBeenCalledWith(0);
  });

  it("un lot avec question de relance → popup, coche « non-critiques » → politique envoyée", () => {
    const onSelectLot = vi.fn();
    render(
      <AttackLotPanel
        lotRequest={request([LOT_NO_POLICY, LOT_HIT_POLICY])}
        allocation={null}
        unitLabel={unitLabel}
        onSelectLot={onSelectLot}
        onAllocateModel={vi.fn()}
      />
    );
    fireEvent.click(screen.getByTestId("lot-1"));
    expect(onSelectLot).not.toHaveBeenCalled();
    expect(screen.getByText(/RELANCES — Plasma gun → Unit #3/)).toBeTruthy();
    // Seule la question de TOUCHE est posée pour ce lot.
    const boxes = screen.getAllByRole("checkbox");
    expect(boxes).toHaveLength(1);
    fireEvent.click(boxes[0]);
    fireEvent.click(screen.getByRole("button", { name: /Résoudre ce lot/ }));
    expect(onSelectLot).toHaveBeenCalledWith(1, { hit: true, wound: false });
  });

  it("décoché = échecs seulement (false explicite sur la question posée)", () => {
    const onSelectLot = vi.fn();
    render(
      <AttackLotPanel
        lotRequest={request([LOT_WOUND_POLICY], { policy_only: true, locked_target_unit_id: "2" })}
        allocation={null}
        unitLabel={unitLabel}
        onSelectLot={onSelectLot}
        onAllocateModel={vi.fn()}
      />
    );
    // policy_only + un seul lot : la popup s'ouvre d'elle-même, sans clic sur un lot.
    expect(screen.getByText(/RELANCES — Melta → Unit #2/)).toBeTruthy();
    expect(screen.getByText(/DEVASTATING WOUNDS/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Résoudre ce lot/ }));
    expect(onSelectLot).toHaveBeenCalledWith(2, { hit: false, wound: false });
  });

  it("unité en cours imposée → titre nommant l'unité", () => {
    render(
      <AttackLotPanel
        lotRequest={request([LOT_NO_POLICY, LOT_WOUND_POLICY], { locked_target_unit_id: "2" })}
        allocation={null}
        unitLabel={unitLabel}
        onSelectLot={vi.fn()}
        onAllocateModel={vi.fn()}
      />
    );
    expect(screen.getByText(/LOT SUIVANT — Unit #2 \(unité en cours\)/)).toBeTruthy();
    expect(screen.getByTestId("lot-0")).toBeTruthy();
    expect(screen.getByTestId("lot-2")).toBeTruthy();
  });
});

describe("AttackLotPanel — allocation du défenseur (05.04 / 06.02)", () => {
  const allocation: ManualAllocation = {
    kind: "shoot",
    attacker_unit_id: "1",
    target_unit_id: "2",
    defender_player: 2,
    choices: [
      { model_id: "2#0", col: 0, row: 0, HP_CUR: 2, HP_MAX: 2 },
      { model_id: "2#1", col: 1, row: 0, HP_CUR: 1, HP_MAX: 2 },
    ],
    wounds_remaining: 3,
    weapon_name: "Bolt rifle",
    weapon_names: ["Bolt rifle", "Bolt pistol"],
  };

  it("liste l'arme, les blessures restantes et les candidates ; clic = allocation", () => {
    const onAllocateModel = vi.fn();
    render(
      <AttackLotPanel
        lotRequest={null}
        allocation={allocation}
        unitLabel={unitLabel}
        onSelectLot={vi.fn()}
        onAllocateModel={onAllocateModel}
      />
    );
    expect(screen.getByText(/ALLOCATION — Unit #2 encaisse/)).toBeTruthy();
    expect(screen.getByText(/3 blessure\(s\) restante\(s\)/)).toBeTruthy();
    expect(screen.getByText("Bolt rifle")).toBeTruthy();
    expect(screen.getByText("Bolt pistol")).toBeTruthy();
    fireEvent.click(screen.getByTestId("alloc-2#1"));
    expect(onAllocateModel).toHaveBeenCalledWith("2#1");
  });

  it("lot mortel → « sans sauvegarde (06.02) », pas d'arme", () => {
    render(
      <AttackLotPanel
        lotRequest={null}
        allocation={{
          ...allocation,
          damage_type: "mortal",
          weapon_name: undefined,
          weapon_names: undefined,
        }}
        unitLabel={unitLabel}
        onSelectLot={vi.fn()}
        onAllocateModel={vi.fn()}
      />
    );
    expect(
      screen.getByText(/blessure\(s\) mortelle\(s\) restante\(s\) — sans sauvegarde \(06.02\)/)
    ).toBeTruthy();
    expect(screen.getByText("Mortal Wounds")).toBeTruthy();
    expect(screen.queryByText("Bolt rifle")).toBeNull();
  });
});
