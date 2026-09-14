// @vitest-environment jsdom
/**
 * 20.01/20.04 — le siège des réserves après la refonte :
 *
 *   - la DÉCLARATION se compose PAR CAMP, sans ordre ni question : `Reserve` sur la ligne
 *     sélectionnée d'une escouade déclarable, `Cancel` sur une escouade du conteneur tant que le
 *     camp n'a pas validé, et un bandeau (`ReservesDeclarationBanner`) qui dit QUI déclare et
 *     porte `Validate` — toujours actif, déclarer zéro réserve étant légal (« can select ») ;
 *   - le CONTENEUR ne dépose plus rien : il montre les escouades hors table du joueur, au format
 *     commun `UnitRosterRow` (figurines, nom, points, nb de figurines, id), et le `Cancel` 20.01
 *     sur celles que le moteur dit annulables ;
 *   - `UnitStatusTable` ne le porte plus du tout — il vit SOUS elle, rendu par `BoardWithAPI`.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { StrategicReservesPlayerSummary, Unit } from "../types/game";
import {
  CancelReserveButton,
  ReserveButton,
  ReservesDeclarationBanner,
  ResetPlacementButton,
  StrategicReservesContainer,
} from "./StrategicReservesContainer";
import { UnitRosterRow } from "./UnitRosterRow";
import { UnitStatusTable } from "./UnitStatusTable";

afterEach(cleanup);

const SUMMARY: StrategicReservesPlayerSummary = {
  used_points: 120,
  cap_points: 500,
};

/** Escouade sur le plateau (pas en réserves) : HP_MAX requis par UnitRow. */
function onTableUnit(id: number): Unit {
  return {
    id,
    player: 1,
    col: 0,
    row: 0,
    HP_CUR: 5,
    HP_MAX: 5,
    MOVE: 60,
    DISPLAY_NAME: `Unit ${id}`,
    RNG_WEAPONS: [],
    CC_WEAPONS: [],
    ICON: "",
    ILLUSTRATION_RATIO: 1,
    UNIT_RULES: [],
    UNIT_KEYWORDS: [],
  } as unknown as Unit;
}

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

describe("Reserve / Cancel — 20.01", () => {
  it("`Reserve` est actif et appelle son geste, sans `Deploy` en face", () => {
    // Le bouton n'apparaît que sur une escouade que le moteur liste comme déclarable :
    // l'éligibilité est déjà tranchée, il n'y a rien à griser. Ne pas réserver, c'est déployer —
    // aucun second bouton n'existe pour ça.
    const onReserve = vi.fn();
    render(<ReserveButton onReserve={onReserve} />);

    const reserve = screen.getByTestId("strategic-reserves-declare") as HTMLButtonElement;
    expect(reserve.disabled).toBe(false);
    expect(screen.queryByTestId("strategic-reserves-keep")).toBeNull();

    fireEvent.click(reserve);
    expect(onReserve).toHaveBeenCalledTimes(1);
  });

  it("`Cancel` est actif et appelle son geste", () => {
    const onCancel = vi.fn();
    render(<CancelReserveButton onCancel={onCancel} />);

    const cancel = screen.getByTestId("strategic-reserves-cancel") as HTMLButtonElement;
    expect(cancel.disabled).toBe(false);
    fireEvent.click(cancel);
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("le clic ne remonte pas à la ligne, qui est elle-même cliquable", () => {
    // Sans `stopPropagation`, réserver rejouerait aussi la sélection de l'escouade dont le
    // bouton vient de disparaître — et annuler, celle d'une ligne du conteneur.
    const onRowClick = vi.fn();
    // Le guetteur est un écouteur NATIF posé au-dessus de la racine React : c'est exactement ce
    // que la ligne cliquable du panneau verrait remonter. Un `<div onClick>` de doublure aurait
    // été un élément statique rendu interactif — ce que le lint refuse, à raison.
    render(
      <>
        <ReserveButton onReserve={vi.fn()} />
        <CancelReserveButton onCancel={vi.fn()} />
      </>
    );
    document.body.addEventListener("click", onRowClick);
    try {
      fireEvent.click(screen.getByTestId("strategic-reserves-declare"));
      fireEvent.click(screen.getByTestId("strategic-reserves-cancel"));
      expect(onRowClick).not.toHaveBeenCalled();
    } finally {
      document.body.removeEventListener("click", onRowClick);
    }
  });
});

describe("ReservesDeclarationBanner — 20.01", () => {
  it("nomme le camp déclarant et porte un `Validate` TOUJOURS actif", () => {
    // Déclarer zéro réserve est une déclaration légale (« can select »), et c'est le cas
    // majoritaire : un `Validate` grisé sur un conteneur vide dirait au joueur qu'il doit
    // réserver quelque chose, ce qui est faux.
    const onValidate = vi.fn();
    render(<ReservesDeclarationBanner playerLabel="Player 2" onValidate={onValidate} />);

    expect(screen.getByTestId("strategic-reserves-declaration-banner").textContent).toContain(
      "Player 2"
    );
    const validate = screen.getByTestId("strategic-reserves-validate") as HTMLButtonElement;
    expect(validate.disabled).toBe(false);
    fireEvent.click(validate);
    expect(onValidate).toHaveBeenCalledTimes(1);
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

  it("ne porte aucun `Reserve` — ce geste vit dans la liste à déployer", () => {
    render(
      <StrategicReservesContainer
        {...CONTAINER_PROPS}
        reserveUnits={[reserveUnit(7)]}
        summary={SUMMARY}
        canSelectReserveUnit={false}
      />
    );
    expect(screen.queryByTestId("strategic-reserves-declare")).toBeNull();
    expect(screen.queryByTestId("strategic-reserves-keep")).toBeNull();
    // Rien d'annulable non plus : la liste du moteur est vide par défaut.
    expect(screen.queryByTestId("strategic-reserves-cancel")).toBeNull();
  });

  it("porte `Cancel` sur les seules escouades que le moteur dit annulables", () => {
    // La liste `strategic_reserves.cancellable` est LUE, jamais déduite de `in_strategic_reserves` :
    // après validation, une escouade réservée reste dans le conteneur sans `Cancel`.
    const onCancelReserve = vi.fn();
    render(
      <StrategicReservesContainer
        {...CONTAINER_PROPS}
        reserveUnits={[reserveUnit(7), reserveUnit(9)]}
        summary={SUMMARY}
        canSelectReserveUnit={false}
        cancellableUnitIds={["7"]}
        onCancelReserve={onCancelReserve}
      />
    );
    expect(screen.getAllByTestId("strategic-reserves-cancel")).toHaveLength(1);
    expect(
      screen
        .getByTestId("strategic-reserves-unit-7")
        .querySelector("[data-testid='strategic-reserves-cancel']")
    ).toBeTruthy();
    fireEvent.click(screen.getByTestId("strategic-reserves-cancel"));
    expect(onCancelReserve).toHaveBeenCalledWith(7);
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

  it("victoryPoints défini → affiche 'VP : <n>'", () => {
    render(
      <UnitStatusTable
        units={[onTableUnit(10)]}
        player={1}
        selectedUnitId={null}
        onSelectUnit={() => {}}
        playerTypes={{ "1": "human", "2": "human" }}
        victoryPoints={7}
      />
    );
    expect(screen.getByText("VP : 7")).toBeTruthy();
  });

  it("commandPoints défini → affiche 'CP : <n>'", () => {
    render(
      <UnitStatusTable
        units={[onTableUnit(10)]}
        player={1}
        selectedUnitId={null}
        onSelectUnit={() => {}}
        playerTypes={{ "1": "human", "2": "human" }}
        commandPoints={3}
      />
    );
    expect(screen.getByText("CP : 3")).toBeTruthy();
  });

  it("victoryPoints absent → aucun texte VP", () => {
    render(
      <UnitStatusTable
        units={[onTableUnit(10)]}
        player={1}
        selectedUnitId={null}
        onSelectUnit={() => {}}
        playerTypes={{ "1": "human", "2": "human" }}
      />
    );
    expect(screen.queryByText(/VP :/)).toBeNull();
  });
});
