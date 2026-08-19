// @vitest-environment jsdom
/**
 * T10 — WeaponDropdown : menu d'armes de tir (quantités, max, unassign, Cancel/Shoot).
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { WeaponOption } from "../types/game";
import { WeaponDropdown } from "./WeaponDropdown";

afterEach(cleanup);

function makeWeapon(index: number, name: string, canUse = true, assigned = false): WeaponOption {
  return {
    index,
    weapon: {
      display_name: name,
      NB: 2,
      ATK: 4,
      STR: 4,
      AP: 1,
      DMG: 1,
      RNG: 240,
    },
    canUse,
    assigned,
  };
}

const BASE_PROPS = {
  position: { x: 100, y: 100 },
  onSelectWeapon: vi.fn(),
  onClose: vi.fn(),
};

// ---------------------------------------------------------------------------
// Rendu de base
// ---------------------------------------------------------------------------

describe("WeaponDropdown — rendu des armes", () => {
  it("affiche le nom de chaque arme dans les lignes du tableau", () => {
    render(
      <WeaponDropdown
        {...BASE_PROPS}
        weapons={[makeWeapon(0, "Bolt Rifle"), makeWeapon(1, "Plasma Pistol")]}
      />
    );
    expect(screen.getByText("Bolt Rifle")).toBeTruthy();
    expect(screen.getByText("Plasma Pistol")).toBeTruthy();
  });

  it("affiche les stats (ATK, STR, AP, DMG)", () => {
    render(<WeaponDropdown {...BASE_PROPS} weapons={[makeWeapon(0, "Bolt Rifle")]} />);
    expect(screen.getByText("4+")).toBeTruthy(); // ATK
    expect(screen.getByText("4")).toBeTruthy(); // STR
    // AP=1 et DMG=1 : deux cellules "1", donc getAllByText
    expect(screen.getAllByText("1").length).toBeGreaterThanOrEqual(1); // AP / DMG
  });

  it("convertit la portée en pouces avec inchesToSubhex", () => {
    render(
      <WeaponDropdown {...BASE_PROPS} weapons={[makeWeapon(0, "Bolt Rifle")]} inchesToSubhex={10} />
    );
    // RNG=240, inchesToSubhex=10 → 24"
    expect(screen.getByText('24"')).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// Sélection d'arme
// ---------------------------------------------------------------------------

describe("WeaponDropdown — sélection", () => {
  it("onSelectWeapon(index) appelé au clic sur une ligne activée", () => {
    const onSelect = vi.fn();
    render(
      <WeaponDropdown
        {...BASE_PROPS}
        weapons={[makeWeapon(0, "Bolt Rifle"), makeWeapon(1, "Plasma Pistol")]}
        onSelectWeapon={onSelect}
      />
    );
    // Clic sur le nom de l'arme (td dans la ligne)
    fireEvent.click(screen.getByText("Plasma Pistol"));
    expect(onSelect).toHaveBeenCalledWith(1);
  });

  it("onSelectWeapon non appelé pour une arme désactivée (canUse=false)", () => {
    const onSelect = vi.fn();
    render(
      <WeaponDropdown
        {...BASE_PROPS}
        weapons={[makeWeapon(0, "Disabled Weapon", false)]}
        onSelectWeapon={onSelect}
      />
    );
    fireEvent.click(screen.getByText("Disabled Weapon"));
    expect(onSelect).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// Boutons Cancel / Shoot (showActions)
// ---------------------------------------------------------------------------

describe("WeaponDropdown — showActions", () => {
  it("affiche Cancel et Shoot quand showActions=true", () => {
    render(
      <WeaponDropdown
        {...BASE_PROPS}
        weapons={[makeWeapon(0, "Bolt Rifle")]}
        showActions
        onCancel={vi.fn()}
        onFire={vi.fn()}
        canValidate
      />
    );
    expect(screen.getByRole("button", { name: "Cancel" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Shoot" })).toBeTruthy();
  });

  it("n'affiche PAS Cancel/Shoot si showActions est absent", () => {
    render(<WeaponDropdown {...BASE_PROPS} weapons={[makeWeapon(0, "Bolt Rifle")]} />);
    expect(screen.queryByRole("button", { name: "Cancel" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Shoot" })).toBeNull();
  });

  it("onCancel appelé au clic Cancel", () => {
    const onCancel = vi.fn();
    render(
      <WeaponDropdown
        {...BASE_PROPS}
        weapons={[makeWeapon(0, "Bolt Rifle")]}
        showActions
        onCancel={onCancel}
        onFire={vi.fn()}
        canValidate
      />
    );
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("bouton Shoot est désactivé quand canValidate=false", () => {
    render(
      <WeaponDropdown
        {...BASE_PROPS}
        weapons={[makeWeapon(0, "Bolt Rifle")]}
        showActions
        onCancel={vi.fn()}
        onFire={vi.fn()}
        canValidate={false}
      />
    );
    const shootBtn = screen.getByRole("button", { name: "Shoot" }) as HTMLButtonElement;
    expect(shootBtn.disabled).toBe(true);
  });

  it("onFire appelé au clic Shoot quand canValidate=true", () => {
    const onFire = vi.fn();
    render(
      <WeaponDropdown
        {...BASE_PROPS}
        weapons={[makeWeapon(0, "Bolt Rifle")]}
        showActions
        onCancel={vi.fn()}
        onFire={onFire}
        canValidate
      />
    );
    fireEvent.click(screen.getByRole("button", { name: "Shoot" }));
    expect(onFire).toHaveBeenCalledTimes(1);
  });
});

// ---------------------------------------------------------------------------
// Lignes de quantité (openTargets + targetData)
// ---------------------------------------------------------------------------

describe("WeaponDropdown — lignes de quantité", () => {
  // code = w.code ?? "" = "" (makeWeapon ne définit pas code)
  const WEAPON_ENTRY = {
    code: "",
    weapon: { display_name: "Bolt Rifle", NB: 2, ATK: 4, STR: 4, AP: 1, DMG: 1, RNG: 240 },
    m: 3,
    x: 1,
  };

  it("openTargets + targetData → affiche la ligne de quantité avec compteur x/m", () => {
    render(
      <WeaponDropdown
        {...BASE_PROPS}
        weapons={[makeWeapon(0, "Bolt Rifle")]}
        openTargets={["t1"]}
        targetData={{ t1: [WEAPON_ENTRY] }}
      />
    );
    expect(screen.getByText("1/3")).toBeTruthy();
  });

  it("clic − → onSetQty appelé avec x-1", () => {
    const onQty = vi.fn();
    render(
      <WeaponDropdown
        {...BASE_PROPS}
        weapons={[makeWeapon(0, "Bolt Rifle")]}
        openTargets={["t1"]}
        targetData={{ t1: [WEAPON_ENTRY] }}
        onSetQty={onQty}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: "−" }));
    expect(onQty).toHaveBeenCalledWith("", 0, "t1");
  });

  it("clic + → onSetQty appelé avec x+1", () => {
    const onQty = vi.fn();
    render(
      <WeaponDropdown
        {...BASE_PROPS}
        weapons={[makeWeapon(0, "Bolt Rifle")]}
        openTargets={["t1"]}
        targetData={{ t1: [WEAPON_ENTRY] }}
        onSetQty={onQty}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: "+" }));
    expect(onQty).toHaveBeenCalledWith("", 2, "t1");
  });

  it("clic Max → onSetQty appelé avec m", () => {
    const onQty = vi.fn();
    render(
      <WeaponDropdown
        {...BASE_PROPS}
        weapons={[makeWeapon(0, "Bolt Rifle")]}
        openTargets={["t1"]}
        targetData={{ t1: [WEAPON_ENTRY] }}
        onSetQty={onQty}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: "Max" }));
    expect(onQty).toHaveBeenCalledWith("", 3, "t1");
  });

  it("− désactivé quand x=0 (activeTargetId requis pour afficher la ligne)", () => {
    render(
      <WeaponDropdown
        {...BASE_PROPS}
        weapons={[makeWeapon(0, "Bolt Rifle")]}
        openTargets={["t1"]}
        targetData={{ t1: [{ ...WEAPON_ENTRY, x: 0 }] }}
        activeTargetId="t1"
      />
    );
    const minusBtn = screen.getByRole("button", { name: "−" }) as HTMLButtonElement;
    expect(minusBtn.disabled).toBe(true);
  });

  it("+ et Max désactivés quand x >= m", () => {
    render(
      <WeaponDropdown
        {...BASE_PROPS}
        weapons={[makeWeapon(0, "Bolt Rifle")]}
        openTargets={["t1"]}
        targetData={{ t1: [{ ...WEAPON_ENTRY, x: 3, m: 3 }] }}
      />
    );
    const plusBtn = screen.getByRole("button", { name: "+" }) as HTMLButtonElement;
    const maxBtn = screen.getByRole("button", { name: "Max" }) as HTMLButtonElement;
    expect(plusBtn.disabled).toBe(true);
    expect(maxBtn.disabled).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Arme assigned (fond vert foncé)
// ---------------------------------------------------------------------------

describe("WeaponDropdown — arme assigned", () => {
  it("la ligne de l'arme assignée a un fond vert foncé", () => {
    render(
      <WeaponDropdown {...BASE_PROPS} weapons={[makeWeapon(0, "Assigned Gun", true, true)]} />
    );
    // L'arme assignée est dans un <tr> avec background vert
    const rows = document.querySelectorAll("tr");
    // jsdom normalise rgba sans espaces ou avec espaces selon la version
    const assignedRow = Array.from(rows).find((r) => {
      const bg = r.style.backgroundColor.replace(/\s+/g, "");
      return bg.includes("rgba(20,83,45");
    });
    expect(assignedRow).toBeTruthy();
  });
});
