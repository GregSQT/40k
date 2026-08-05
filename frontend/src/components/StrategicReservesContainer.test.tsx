// @vitest-environment jsdom
/**
 * 20.01/20.04 — le siège des réserves après la refonte :
 *
 *   - le DÉPÔT est un bouton porté par la ligne de l'escouade dans la liste à déployer
 *     (`StrategicReserveButton`) : vert quand le moteur accepte, gris sinon, et un bouton gris
 *     n'appelle rien — c'est la seule réponse rendue au joueur sur le plafond de 50 % ;
 *   - le CONTENEUR ne dépose plus rien : il montre les escouades hors table du joueur, au format
 *     commun `UnitRosterRow` (figurines, nom, points, nb de figurines, id) ;
 *   - `UnitStatusTable` ne le porte plus du tout — il vit SOUS elle, rendu par `BoardWithAPI`.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { StrategicReservesPlayerSummary, Unit } from "../types/game";
import {
  ResetPlacementButton,
  StrategicReserveButton,
  StrategicReservesContainer,
} from "./StrategicReservesContainer";
import { UnitRosterRow } from "./UnitRosterRow";
import { UnitStatusTable } from "./UnitStatusTable";

afterEach(cleanup);

const SUMMARY: StrategicReservesPlayerSummary = {
  used_points: 120,
  cap_points: 500,
  placeable_unit_ids: ["7"],
};

/** Escouade minimale : seuls les champs que la ligne et `selectReserveUnits` lisent. */
function reserveUnit(id: number): Unit {
  return {
    id,
    player: 1,
    HP_CUR: 10,
    VALUE: 120,
    DISPLAY_NAME: `Squad ${id}`,
    ICON: "/icons/squad.webp",
    BASE_SIZE: 32,
    BASE_SHAPE: "circle",
    in_strategic_reserves: true,
  } as unknown as Unit;
}

const CONTAINER_PROPS = {
  player: 1 as const,
  unitsCache: undefined,
  boundIconSize: true,
  borderColor: "#fff",
  haloGlow: "none",
  phase: "move",
};

describe("StrategicReserveButton", () => {
  it("dépose au clic quand le moteur accepte", () => {
    const onDrop = vi.fn();
    render(<StrategicReserveButton canDrop={true} onDrop={onDrop} />);
    const button = screen.getByTestId("strategic-reserves-drop") as HTMLButtonElement;
    expect(button.disabled).toBe(false);
    // Vert = le dépôt tient sous le plafond ; la couleur EST la réponse rendue au joueur.
    expect(button.style.background).toContain("--ui-green-validate");
    fireEvent.click(button);
    expect(onDrop).toHaveBeenCalledTimes(1);
  });

  it("est gris et inerte quand le moteur refuse", () => {
    const onDrop = vi.fn();
    render(<StrategicReserveButton canDrop={false} onDrop={onDrop} />);
    const button = screen.getByTestId("strategic-reserves-drop") as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(button.style.background).toContain("--ui-gray-cancel");
    fireEvent.click(button);
    expect(onDrop).not.toHaveBeenCalled();
  });
});

describe("StrategicReservesContainer", () => {
  it("affiche le ratio LU du moteur et une ligne par escouade hors table", () => {
    render(
      <StrategicReservesContainer
        {...CONTAINER_PROPS}
        reserveUnits={[reserveUnit(7)]}
        summary={SUMMARY}
        canSelectReserveUnit={false}
      />
    );
    expect(screen.getByTestId("strategic-reserves-ratio-1").textContent).toBe("120/500");
    expect(screen.getByTestId("strategic-reserves-unit-7")).toBeTruthy();
    // Même format que la liste à déployer : la valeur en points est sur la ligne.
    expect(screen.getByTestId("roster-row-points-7").textContent).toBe("120 pts");
  });

  it("ne porte plus aucun bouton de dépôt — le dépôt vit dans la liste à déployer", () => {
    render(
      <StrategicReservesContainer
        {...CONTAINER_PROPS}
        reserveUnits={[reserveUnit(7)]}
        summary={SUMMARY}
        canSelectReserveUnit={false}
      />
    );
    expect(screen.queryByTestId("strategic-reserves-drop")).toBeNull();
  });

  it("demande l'aire d'arrivée au clic quand la phase l'autorise (20.04)", () => {
    const onSelect = vi.fn();
    render(
      <StrategicReservesContainer
        {...CONTAINER_PROPS}
        reserveUnits={[reserveUnit(7)]}
        summary={SUMMARY}
        canSelectReserveUnit={true}
        onSelectReserveUnit={onSelect}
      />
    );
    fireEvent.click(screen.getByTestId("roster-row-select-7"));
    expect(onSelect).toHaveBeenCalledWith(7);
  });

  it("n'appelle rien hors phase de mouvement", () => {
    const onSelect = vi.fn();
    render(
      <StrategicReservesContainer
        {...CONTAINER_PROPS}
        reserveUnits={[reserveUnit(7)]}
        summary={SUMMARY}
        canSelectReserveUnit={false}
        onSelectReserveUnit={onSelect}
      />
    );
    fireEvent.click(screen.getByTestId("roster-row-select-7"));
    expect(onSelect).not.toHaveBeenCalled();
  });
});

describe("UnitRosterRow", () => {
  it("sélectionne depuis TOUTE la ligne, points et id compris", () => {
    const onClick = vi.fn();
    render(
      <UnitRosterRow
        unit={reserveUnit(7)}
        player={1}
        unitsCache={undefined}
        boundIconSize={true}
        selected={false}
        interactive={true}
        onClick={onClick}
        borderColor="#fff"
        haloGlow="none"
      />
    );
    // Le bout DROIT de la ligne : c'est lui qui devenait inerte quand la zone cliquable se
    // limitait à « icônes + nom ».
    fireEvent.click(screen.getByTestId("roster-row-points-7"));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("ne sélectionne pas quand la ligne n'est pas actionnable", () => {
    const onClick = vi.fn();
    render(
      <UnitRosterRow
        unit={reserveUnit(7)}
        player={1}
        unitsCache={undefined}
        boundIconSize={true}
        selected={false}
        interactive={false}
        onClick={onClick}
        borderColor="#fff"
        haloGlow="none"
      />
    );
    fireEvent.click(screen.getByTestId("roster-row-points-7"));
    expect(onClick).not.toHaveBeenCalled();
  });
});

describe("ResetPlacementButton", () => {
  it("annule la mise en place au clic, sans consommer le geste", () => {
    const onReset = vi.fn();
    render(<ResetPlacementButton onReset={onReset} />);
    fireEvent.click(screen.getByTestId("placement-reset"));
    expect(onReset).toHaveBeenCalledTimes(1);
  });

  it("n'est PAS désactivé — se dédire reste toujours possible", () => {
    render(<ResetPlacementButton onReset={() => {}} />);
    expect((screen.getByTestId("placement-reset") as HTMLButtonElement).disabled).toBe(false);
  });
});

describe("StrategicReservesContainer — Reset d'une arrivée", () => {
  it("porte le Reset sur la ligne de l'escouade en cours de placement, et sur elle seule", () => {
    const onCancel = vi.fn();
    render(
      <StrategicReservesContainer
        {...CONTAINER_PROPS}
        reserveUnits={[reserveUnit(7), reserveUnit(9)]}
        summary={SUMMARY}
        canSelectReserveUnit={true}
        placingUnitId={7}
        onCancelPlacement={onCancel}
      />
    );
    const rows = screen.getAllByTestId(/^strategic-reserves-unit-/);
    expect(rows).toHaveLength(2);
    // Une seule ligne porte le bouton : celle dont l'arrivée est en cours.
    expect(screen.getAllByTestId("placement-reset")).toHaveLength(1);
    expect(
      screen
        .getByTestId("strategic-reserves-unit-7")
        .querySelector("[data-testid='placement-reset']")
    ).toBeTruthy();
    fireEvent.click(screen.getByTestId("placement-reset"));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("ne porte aucun Reset quand aucune arrivée n'est en cours", () => {
    render(
      <StrategicReservesContainer
        {...CONTAINER_PROPS}
        reserveUnits={[reserveUnit(7)]}
        summary={SUMMARY}
        canSelectReserveUnit={true}
        placingUnitId={null}
        onCancelPlacement={() => {}}
      />
    );
    expect(screen.queryByTestId("placement-reset")).toBeNull();
  });
});

describe("StrategicReservesContainer — conteneur vide", () => {
  it("ne s'affiche pas hors déploiement quand le joueur n'a aucune réserve", () => {
    const { container } = render(
      <StrategicReservesContainer
        {...CONTAINER_PROPS}
        reserveUnits={[]}
        summary={SUMMARY}
        canSelectReserveUnit={false}
      />
    );
    expect(container.innerHTML).toBe("");
  });

  it("s'affiche vide PENDANT le déploiement : son ratio est la lecture du plafond restant", () => {
    render(
      <StrategicReservesContainer
        {...CONTAINER_PROPS}
        phase="deployment"
        reserveUnits={[]}
        summary={SUMMARY}
        canSelectReserveUnit={false}
      />
    );
    expect(screen.getByTestId("strategic-reserves-ratio-1").textContent).toBe("120/500");
  });

  it("ne s'affiche pas tant qu'aucune partie n'est chargée", () => {
    const { container } = render(
      <StrategicReservesContainer
        {...CONTAINER_PROPS}
        phase={undefined}
        reserveUnits={[]}
        summary={null}
        canSelectReserveUnit={false}
      />
    );
    expect(container.innerHTML).toBe("");
  });
});

describe("UnitStatusTable", () => {
  it("ne porte plus le conteneur de réserves, à aucune phase", () => {
    render(
      <UnitStatusTable
        units={[reserveUnit(7)]}
        player={1}
        selectedUnitId={7}
        onSelectUnit={() => {}}
        playerTypes={{ "1": "human", "2": "human" }}
      />
    );
    // VERT VACANT : la table a bien été rendue, ce n'est pas un rendu vide qui fait passer.
    expect(document.querySelector(".unit-status-table-container")).toBeTruthy();
    expect(screen.queryByTestId("strategic-reserves-container-1")).toBeNull();
  });

  it("une armée ENTIÈREMENT en réserves n'est pas annoncée comme éliminée (20.01)", () => {
    render(
      <UnitStatusTable
        units={[reserveUnit(7)]}
        player={1}
        selectedUnitId={null}
        onSelectUnit={() => {}}
        playerTypes={{ "1": "human", "2": "human" }}
      />
    );
    const empty = document.querySelector(".unit-status-table-empty");
    expect(empty?.textContent).toContain("All units in strategic reserves");
    expect(empty?.textContent).not.toContain("No units remaining");
  });

  it("annonce l'élimination quand il ne reste vraiment rien", () => {
    render(
      <UnitStatusTable
        units={[]}
        player={1}
        selectedUnitId={null}
        onSelectUnit={() => {}}
        playerTypes={{ "1": "human", "2": "human" }}
      />
    );
    expect(document.querySelector(".unit-status-table-empty")?.textContent).toContain(
      "No units remaining"
    );
  });
});
