// frontend/src/components/UnitStatusTable.tsx
import {
  memo,
  type RefObject,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import unitRules from "../../../config/unit_rules.json";
import weaponRules from "../../../config/weapon_rules.json";
import type { Unit, UnitId } from "../types/game";
import TooltipWrapper from "./TooltipWrapper";
import { useTutorial } from "../contexts/TutorialContext";

const UNIT_RULE_DESCRIPTIONS: Record<string, string> = {
  charge_after_advance: "Allows a unit to charge in the same turn it advanced.",
  adaptable_predators: "This unit can shoot and charge in a turn in which it fell back.",
  shoot_after_flee: "Allows a unit to shoot in a turn in which it fell back.",
  charge_after_flee: "Allows a unit to charge in a turn in which it fell back.",
};

const getUnitRuleTooltip = (ruleId: string): string => {
  const configDescription = unitRules[ruleId as keyof typeof unitRules]?.description;
  return configDescription ?? UNIT_RULE_DESCRIPTIONS[ruleId] ?? ruleId;
};

const getWeaponRuleDisplay = (ruleId: string): { displayName: string; tooltipText: string } => {
  const [baseRuleId, parameter] = ruleId.split(":");
  const ruleData = weaponRules[baseRuleId as keyof typeof weaponRules];
  const baseDisplayName = ruleData?.name ?? baseRuleId;
  const displayName = parameter ? `${baseDisplayName}:${parameter}` : baseDisplayName;
  const tooltipText = ruleData?.description ?? ruleId;
  return { displayName, tooltipText };
};

interface UnitStatusTableProps {
  units: Unit[];
  player: 1 | 2;
  playerTypes?: Record<string, "human" | "ai" | "bot">;
  selectedUnitId: UnitId | null;
  guidedFocusUnitId?: UnitId | null;
  clickedUnitId?: UnitId | null;
  onSelectUnit: (unitId: UnitId) => void;
  gameMode?: "pvp" | "pvp_test" | "pve" | "training" | "tutorial";
  isReplay?: boolean;
  victoryPoints?: number;
  onCollapseChange?: (collapsed: boolean) => void;
  /** En mode tutoriel : forcer la table dépliée pour voir les colonnes. */
  tutorialForceTableExpanded?: boolean;
  /** En mode tutoriel : forcer ces unités à avoir la ligne stats dépliée (ex. Intercessor id 1). */
  tutorialForceUnitIdsExpanded?: UnitId[];
  /** En mode tutoriel (étape 2-11) : forcer ces unités à avoir la ligne stats repliée (ex. Hormagaunts id 2 et 3). */
  tutorialForceUnitIdsCollapsed?: UnitId[];
  /** En mode tutoriel : rapporter les positions viewport [colonne Name, colonne M] pour les halos. */
  onNameMColumnsRect?:
    | ((
        positions: Array<{
          shape: "rect";
          left: number;
          top: number;
          width: number;
          height: number;
        }> | null
      ) => void)
    | null;
  /** En mode tutoriel (étape 1-6) : forcer ces unités à avoir la section RANGED WEAPON(S) dépliée. */
  tutorialForceRangedExpandedForUnitIds?: UnitId[];
  /** En mode tutoriel (étape 1-6) : rapporter le rect viewport de la section RANGED WEAPON(S) pour les halos. */
  onRangedWeaponsSectionRect?:
    | ((
        positions: Array<{
          shape: "rect";
          left: number;
          top: number;
          width: number;
          height: number;
        }> | null
      ) => void)
    | null;
  /** En mode tutoriel (étape 2-2) : rapporter le rect viewport ligne attributs + titre pour une unité cible (ex. Termagant). */
  onUnitAttributesSectionRect?:
    | ((
        positions: Array<{
          shape: "rect";
          left: number;
          top: number;
          width: number;
          height: number;
        }> | null
      ) => void)
    | null;
  /** En mode tutoriel (étape 2-2) : ids des unités pour lesquelles rapporter la section attributs (titre + ligne). */
  tutorialReportAttributesForUnitIds?: UnitId[];
  /** En mode tutoriel (étape 2-11/2-12) : rapporter les rects des lignes des unités P2 pour halos. */
  onP2UnitRowRects?:
    | ((
        positions: Array<{
          shape: "rect";
          left: number;
          top: number;
          width: number;
          height: number;
        }> | null
      ) => void)
    | null;
  /** En mode tutoriel (étape 2-11/2-12) : activer le rapport des rects P2. */
  tutorialReportP2UnitRowRects?: boolean;
}

interface UnitRowProps {
  unit: Unit;
  isSelected: boolean;
  isClicked: boolean;
  onSelect: (unitId: UnitId) => void;
  isUnitExpanded: boolean;
  onToggleUnitExpand: (unitId: UnitId) => void;
  isRangedExpanded: boolean;
  onToggleRangedExpand: (unitId: UnitId) => void;
  isMeleeExpanded: boolean;
  onToggleMeleeExpand: (unitId: UnitId) => void;
  /** Tutoriel : rapporter les positions viewport [colonne Name, colonne M] pour deux halos (unité ciblée, ex. Intercessor id 1). */
  reportNameMRect?:
    | ((
        positions: Array<{
          shape: "rect";
          left: number;
          top: number;
          width: number;
          height: number;
        }> | null
      ) => void)
    | null;
  /** Refs des cellules d'en-tête Name et M (pour étendre le halo sur la ligne de titre). */
  nameHeaderRef?: RefObject<HTMLTableCellElement | null>;
  mHeaderRef?: RefObject<HTMLTableCellElement | null>;
  /** Tutoriel 1-6 : rapporter le rect viewport de la table RANGED WEAPON(S) pour le halo. */
  reportRangedWeaponsRect?:
    | ((
        positions: Array<{
          shape: "rect";
          left: number;
          top: number;
          width: number;
          height: number;
        }> | null
      ) => void)
    | null;
  /** Tutoriel 2-11/2-12 : rapporter le rect viewport de la ligne unité pour halo P2. Signature (unitId, rect) pour éviter recréation de callback par unité. */
  reportUnitRowRect?:
    | ((
        unitId: UnitId,
        rect: {
          shape: "rect";
          left: number;
          top: number;
          width: number;
          height: number;
        } | null
      ) => void)
    | null;
  /** Tutoriel 2-2 : rapporter le rect viewport (ligne titre + ligne attributs) pour le halo. */
  reportUnitAttributesRect?:
    | ((
        positions: Array<{
          shape: "rect";
          left: number;
          top: number;
          width: number;
          height: number;
        }> | null
      ) => void)
    | null;
  /** Ref de la ligne d'en-tête du tableau (pour union avec la ligne unité). */
  tableHeaderRowRef?: RefObject<HTMLTableRowElement | null>;
}

function unionRect(
  a: DOMRect,
  b: DOMRect
): { left: number; top: number; width: number; height: number } {
  const left = Math.min(a.left, b.left);
  const top = Math.min(a.top, b.top);
  const right = Math.max(a.right, b.right);
  const bottom = Math.max(a.bottom, b.bottom);
  return { left, top, width: right - left, height: bottom - top };
}

const UnitRow = memo<UnitRowProps>(
  ({
    unit,
    isSelected,
    isClicked,
    onSelect,
    isUnitExpanded,
    onToggleUnitExpand,
    isRangedExpanded,
    onToggleRangedExpand,
    isMeleeExpanded,
    onToggleMeleeExpand,
    reportNameMRect,
    nameHeaderRef,
    mHeaderRef,
    reportRangedWeaponsRect,
    reportUnitRowRect,
    reportUnitAttributesRect,
    tableHeaderRowRef,
  }) => {
    const tutorial = useTutorial();
    const spotlightLayoutTick = tutorial?.spotlightLayoutTick ?? 0;
    const nameCellRef = useRef<HTMLTableCellElement>(null);
    const mCellRef = useRef<HTMLTableCellElement>(null);
    const unitRowRef = useRef<HTMLTableRowElement>(null);

    const reportRect = useCallback(() => {
      if (!reportNameMRect) return;
      const nameEl = nameCellRef.current;
      const mEl = mCellRef.current;
      if (!nameEl || !mEl) {
        reportNameMRect(null);
        return;
      }
      const padding = 6;
      const nameData = nameEl.getBoundingClientRect();
      const mData = mEl.getBoundingClientRect();
      const nameHead = nameHeaderRef?.current?.getBoundingClientRect();
      const mHead = mHeaderRef?.current?.getBoundingClientRect();
      const nameRect = nameHead
        ? unionRect(nameData, nameHead)
        : {
            left: nameData.left,
            top: nameData.top,
            width: nameData.width,
            height: nameData.height,
          };
      const mRect = mHead
        ? unionRect(mData, mHead)
        : { left: mData.left, top: mData.top, width: mData.width, height: mData.height };
      // Ne pas envoyer de rects invalides (éléments cachés/collapsed → getBoundingClientRect 0,0,0,0)
      const minSize = 4;
      if (
        nameRect.width < minSize ||
        nameRect.height < minSize ||
        mRect.width < minSize ||
        mRect.height < minSize
      ) {
        reportNameMRect(null);
        return;
      }
      reportNameMRect([
        {
          shape: "rect",
          left: nameRect.left - padding,
          top: nameRect.top - padding,
          width: nameRect.width + padding * 2,
          height: nameRect.height + padding * 2,
        },
        {
          shape: "rect",
          left: mRect.left - padding,
          top: mRect.top - padding,
          width: mRect.width + padding * 2,
          height: mRect.height + padding * 2,
        },
      ]);
    }, [reportNameMRect, nameHeaderRef, mHeaderRef]);

    useLayoutEffect(() => {
      if (!reportNameMRect) return;
      reportRect();
      let t1: number;
      let t2: number | undefined;
      t1 = requestAnimationFrame(() => {
        reportRect();
        t2 = requestAnimationFrame(() => reportRect());
      });
      const t = setTimeout(() => reportRect(), 30);
      return () => {
        cancelAnimationFrame(t1);
        if (t2 != null) cancelAnimationFrame(t2);
        clearTimeout(t);
        reportNameMRect(null);
      };
    }, [reportNameMRect, reportRect, spotlightLayoutTick]);

    const rangedTableRef = useRef<HTMLTableElement>(null);
    useLayoutEffect(() => {
      if (!reportRangedWeaponsRect || !isUnitExpanded || !isRangedExpanded) {
        if (reportRangedWeaponsRect) reportRangedWeaponsRect(null);
        return;
      }
      const el = rangedTableRef.current;
      if (!el) {
        reportRangedWeaponsRect(null);
        return;
      }
      let cancelled = false;
      const measure = () => {
        if (cancelled) return;
        const r = el.getBoundingClientRect();
        if (r.width < 2 || r.height < 2) {
          reportRangedWeaponsRect(null);
          return;
        }
        reportRangedWeaponsRect([
          { shape: "rect", left: r.left, top: r.top, width: r.width, height: r.height },
        ]);
      };
      measure();
      const raf = requestAnimationFrame(() => {
        if (!cancelled) measure();
        requestAnimationFrame(() => {
          if (!cancelled) measure();
        });
      });
      const t = setTimeout(() => {
        if (!cancelled) measure();
      }, 30);
      return () => {
        cancelled = true;
        cancelAnimationFrame(raf);
        clearTimeout(t);
        reportRangedWeaponsRect(null);
      };
    }, [reportRangedWeaponsRect, isUnitExpanded, isRangedExpanded, spotlightLayoutTick]);

    // Tutoriel 2-2 : rapporter union (ligne titre + ligne attributs) pour halo
    const reportAttributesRect = useCallback(() => {
      if (!reportUnitAttributesRect || !tableHeaderRowRef?.current || !unitRowRef.current) {
        if (reportUnitAttributesRect) reportUnitAttributesRect(null);
        return;
      }
      const headerR = tableHeaderRowRef.current.getBoundingClientRect();
      const rowR = unitRowRef.current.getBoundingClientRect();
      const u = unionRect(headerR, rowR);
      const padding = 4;
      const minSize = 4;
      if (u.width < minSize || u.height < minSize) {
        reportUnitAttributesRect(null);
        return;
      }
      reportUnitAttributesRect([
        {
          shape: "rect",
          left: u.left - padding,
          top: u.top - padding,
          width: u.width + padding * 2,
          height: u.height + padding * 2,
        },
      ]);
    }, [reportUnitAttributesRect, tableHeaderRowRef]);
    useLayoutEffect(() => {
      if (!reportUnitAttributesRect) return;
      reportAttributesRect();
      const t1 = requestAnimationFrame(() => {
        reportAttributesRect();
        requestAnimationFrame(reportAttributesRect);
      });
      const t = setTimeout(reportAttributesRect, 30);
      return () => {
        cancelAnimationFrame(t1);
        clearTimeout(t);
        reportUnitAttributesRect(null);
      };
    }, [reportUnitAttributesRect, reportAttributesRect, spotlightLayoutTick]);

    // Tutoriel 2-11/2-12 : rapporter le rect de la ligne unité pour halo P2
    const reportRowRect = useCallback(() => {
      if (!reportUnitRowRect || !unitRowRef.current) return;
      const r = unitRowRef.current.getBoundingClientRect();
      const pad = 4;
      const minSize = 4;
      if (r.width < minSize || r.height < minSize) {
        reportUnitRowRect(unit.id, null);
        return;
      }
      reportUnitRowRect(unit.id, {
        shape: "rect",
        left: r.left - pad,
        top: r.top - pad,
        width: r.width + pad * 2,
        height: r.height + pad * 2,
      });
    }, [reportUnitRowRect, unit.id]);
    useLayoutEffect(() => {
      if (!reportUnitRowRect) return;
      reportRowRect();
      const t1 = requestAnimationFrame(() => {
        reportRowRect();
        requestAnimationFrame(reportRowRect);
      });
      const t = setTimeout(reportRowRect, 30);
      return () => {
        cancelAnimationFrame(t1);
        clearTimeout(t);
        reportUnitRowRect(unit.id, null);
      };
    }, [reportUnitRowRect, reportRowRect, unit.id, spotlightLayoutTick]);

    if (!unit.HP_MAX) {
      throw new Error(`Unit ${unit.id} missing required HP_MAX field`);
    }
    const currentHP = unit.HP_CUR ?? unit.HP_MAX;

    const rngWeapons = unit.RNG_WEAPONS || [];
    const ccWeapons = unit.CC_WEAPONS || [];

    const unitName = unit.DISPLAY_NAME || unit.name || unit.type || `Unit ${unit.id}`;
    const unitRules = unit.UNIT_RULES || [];

    return (
      <div style={{ marginBottom: "2px" }}>
        {/* Unit Attributes Table */}
        <table style={{ width: "100%", borderCollapse: "collapse", tableLayout: "fixed" }}>
          <colgroup>
            <col style={{ width: "40px" }} />
            <col style={{ width: "40px" }} />
            <col style={{ width: "auto" }} />
            <col style={{ width: "70px" }} />
            <col style={{ width: "70px" }} />
            <col style={{ width: "70px" }} />
            <col style={{ width: "70px" }} />
            <col style={{ width: "70px" }} />
            <col style={{ width: "70px" }} />
            <col style={{ width: "70px" }} />
          </colgroup>
          <tbody>
            <tr
              ref={unitRowRef}
              className={`unit-status-row ${isSelected ? "unit-status-row--selected" : ""} ${isClicked ? "unit-status-row--clicked" : ""}`}
              onClick={() => onSelect(unit.id)}
              style={{
                cursor: "pointer",
                backgroundColor: isSelected
                  ? "rgba(100, 150, 255, 0.15)"
                  : isClicked
                    ? "rgba(255, 200, 100, 0.1)"
                    : "transparent",
              }}
            >
              {/* Expand/Collapse Button for Unit */}
              <td
                className="unit-status-cell unit-status-cell--expand"
                style={{ textAlign: "center", padding: "4px 8px", backgroundColor: "#222" }}
              >
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    onToggleUnitExpand(unit.id);
                  }}
                  style={{
                    background: "rgba(70, 130, 200, 0.2)",
                    border: "1px solid rgba(70, 130, 200, 0.4)",
                    color: "#4682c8",
                    fontSize: "14px",
                    fontWeight: "bold",
                    cursor: "pointer",
                    padding: "2px 6px",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    minWidth: "24px",
                    minHeight: "24px",
                    borderRadius: "3px",
                    transition: "all 0.2s ease",
                    margin: "0 auto",
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.background = "rgba(70, 130, 200, 0.4)";
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.background = "rgba(70, 130, 200, 0.2)";
                  }}
                  aria-label={isUnitExpanded ? "Collapse unit" : "Expand unit"}
                >
                  {isUnitExpanded ? "−" : "+"}
                </button>
              </td>

              {/* ID */}
              <td
                className="unit-status-cell unit-status-cell--number"
                style={{
                  textAlign: "center",
                  fontWeight: "bold",
                  padding: "4px 8px",
                  backgroundColor: "#222",
                  borderRight: "1px solid #333",
                  fontSize: "12px",
                }}
              >
                {unit.id}
              </td>

              {/* Name */}
              <td
                ref={nameCellRef}
                className="unit-status-cell unit-status-cell--type"
                style={{
                  fontWeight: "bold",
                  textAlign: "left",
                  padding: "4px 8px",
                  backgroundColor: "#222",
                  fontSize: "12px",
                }}
              >
                <div
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "6px",
                    flexWrap: "wrap",
                  }}
                >
                  <span>{unitName}</span>
                  {unitRules.map((rule) => {
                    const tooltipText = getUnitRuleTooltip(rule.ruleId);
                    return (
                      <span key={`${unit.id}-${rule.ruleId}`} className="rule-badge-wrapper">
                        <span className="rule-badge">{rule.displayName}</span>
                        <span className="rule-tooltip">{tooltipText}</span>
                      </span>
                    );
                  })}
                </div>
              </td>

              {/* HP */}
              <td
                className="unit-status-cell unit-status-cell--hp"
                style={{
                  textAlign: "center",
                  padding: "4px 8px",
                  backgroundColor: "#222",
                  fontSize: "12px",
                }}
              >
                {currentHP}/{unit.HP_MAX}
              </td>

              {/* M (Movement) */}
              <td
                ref={mCellRef}
                className="unit-status-cell unit-status-cell--stat"
                style={{
                  textAlign: "center",
                  padding: "4px 8px",
                  backgroundColor: "#222",
                  borderRight: "1px solid #333",
                  fontSize: "12px",
                }}
              >
                {unit.MOVE}
              </td>

              {/* T (Toughness) */}
              <td
                className="unit-status-cell unit-status-cell--stat"
                style={{
                  textAlign: "center",
                  padding: "4px 8px",
                  backgroundColor: "#222",
                  fontSize: "12px",
                }}
              >
                {unit.T || "-"}
              </td>

              {/* SV (Save Value) */}
              <td
                className="unit-status-cell unit-status-cell--stat"
                style={{
                  textAlign: "center",
                  padding: "4px 8px",
                  backgroundColor: "#222",
                  fontSize: "12px",
                }}
              >
                {unit.ARMOR_SAVE ? `${unit.ARMOR_SAVE}+` : "-"}
              </td>

              {/* LD (Leadership) */}
              <td
                className="unit-status-cell unit-status-cell--stat"
                style={{
                  textAlign: "center",
                  padding: "4px 8px",
                  backgroundColor: "#222",
                  fontSize: "12px",
                }}
              >
                {unit.LD || "-"}
              </td>

              {/* OC (Objective Control) */}
              <td
                className="unit-status-cell unit-status-cell--stat"
                style={{
                  textAlign: "center",
                  padding: "4px 8px",
                  backgroundColor: "#222",
                  fontSize: "12px",
                }}
              >
                {unit.OC || "-"}
              </td>

              {/* VALUE */}
              <td
                className="unit-status-cell unit-status-cell--stat"
                style={{
                  textAlign: "center",
                  padding: "4px 8px",
                  backgroundColor: "#222",
                  fontSize: "12px",
                }}
              >
                {unit.VALUE || "-"}
              </td>
            </tr>
          </tbody>
        </table>

        {/* Weapons Tables - Separate and Independent */}
        {isUnitExpanded && (
          <div style={{ marginTop: "4px", marginLeft: "16px" }}>
            {/* RANGE WEAPON(S) Table */}
            {rngWeapons.length > 0 && (
              <table
                ref={rangedTableRef}
                style={{
                  width: "calc(100% - 16px)",
                  borderCollapse: "collapse",
                  marginBottom: "4px",
                  tableLayout: "fixed",
                }}
              >
                <colgroup>
                  <col style={{ width: "200px" }} />
                  <col style={{ width: "48px" }} />
                  <col style={{ width: "48px" }} />
                  <col style={{ width: "48px" }} />
                  <col style={{ width: "48px" }} />
                  <col style={{ width: "48px" }} />
                  <col style={{ width: "48px" }} />
                </colgroup>
                <thead>
                  <tr
                    className="unit-status-row unit-status-row--section-header"
                    style={{
                      backgroundColor: "rgba(50, 150, 200, 0.2)",
                      fontWeight: "bold",
                      fontSize: "0.9em",
                    }}
                  >
                    <th
                      className="unit-status-cell"
                      style={{
                        backgroundColor: "rgba(50, 150, 200, 0.2)",
                        color: "#ffffff",
                        textAlign: "left",
                        padding: "4px 8px",
                      }}
                    >
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          onToggleRangedExpand(unit.id);
                        }}
                        style={{
                          background: "rgba(100, 150, 200, 0.3)",
                          border: "1px solid rgba(100, 150, 200, 0.5)",
                          color: "#6496c8",
                          fontSize: "12px",
                          fontWeight: "bold",
                          cursor: "pointer",
                          padding: "2px 5px",
                          display: "inline-flex",
                          alignItems: "center",
                          justifyContent: "center",
                          minWidth: "20px",
                          minHeight: "20px",
                          borderRadius: "3px",
                          transition: "all 0.2s ease",
                          marginRight: "8px",
                          verticalAlign: "middle",
                        }}
                        onMouseEnter={(e) => {
                          e.currentTarget.style.background = "rgba(100, 150, 200, 0.5)";
                        }}
                        onMouseLeave={(e) => {
                          e.currentTarget.style.background = "rgba(100, 150, 200, 0.3)";
                        }}
                        aria-label={
                          isRangedExpanded ? "Collapse ranged weapons" : "Expand ranged weapons"
                        }
                      >
                        {isRangedExpanded ? "−" : "+"}
                      </button>
                      <span style={{ fontSize: "11px" }}>RANGE WEAPON(S)</span>
                    </th>
                    <th
                      className="unit-status-cell"
                      style={{
                        textAlign: "center",
                        padding: "4px 8px",
                        color: "#aee6ff",
                        fontWeight: "bold",
                        fontSize: "11px",
                        backgroundColor: "rgba(50, 150, 200, 0.2)",
                      }}
                    >
                      Rng
                    </th>
                    <th
                      className="unit-status-cell"
                      style={{
                        textAlign: "center",
                        padding: "4px 8px",
                        color: "#aee6ff",
                        fontWeight: "bold",
                        fontSize: "11px",
                        backgroundColor: "rgba(50, 150, 200, 0.2)",
                      }}
                    >
                      A
                    </th>
                    <th
                      className="unit-status-cell"
                      style={{
                        textAlign: "center",
                        padding: "4px 8px",
                        color: "#aee6ff",
                        fontWeight: "bold",
                        fontSize: "11px",
                        backgroundColor: "rgba(50, 150, 200, 0.2)",
                      }}
                    >
                      BS
                    </th>
                    <th
                      className="unit-status-cell"
                      style={{
                        textAlign: "center",
                        padding: "4px 8px",
                        color: "#aee6ff",
                        fontWeight: "bold",
                        fontSize: "11px",
                        backgroundColor: "rgba(50, 150, 200, 0.2)",
                      }}
                    >
                      S
                    </th>
                    <th
                      className="unit-status-cell"
                      style={{
                        textAlign: "center",
                        padding: "4px 8px",
                        color: "#aee6ff",
                        fontWeight: "bold",
                        fontSize: "11px",
                        backgroundColor: "rgba(50, 150, 200, 0.2)",
                      }}
                    >
                      AP
                    </th>
                    <th
                      className="unit-status-cell"
                      style={{
                        textAlign: "center",
                        padding: "4px 8px",
                        color: "#aee6ff",
                        fontWeight: "bold",
                        fontSize: "11px",
                        backgroundColor: "rgba(50, 150, 200, 0.2)",
                      }}
                    >
                      DMG
                    </th>
                  </tr>
                </thead>
                {isRangedExpanded && (
                  <tbody>
                    {rngWeapons.map((weapon, idx) => (
                      <tr
                        key={`rng-${unit.id}-${weapon.display_name}-${idx}`}
                        className="unit-status-row unit-status-row--weapon"
                        style={{
                          backgroundColor: idx === 0 ? "#222" : "#2a2a2a",
                        }}
                      >
                        <td
                          className="unit-status-cell unit-status-cell--type"
                          style={{
                            padding: "4px 8px",
                            textAlign: "left",
                            fontSize: "12px",
                            overflow: "visible",
                            textOverflow: "clip",
                          }}
                        >
                          {weapon.display_name}
                          {weapon.WEAPON_RULES?.map((ruleId) => {
                            const { displayName, tooltipText } = getWeaponRuleDisplay(ruleId);
                            return (
                              <span
                                key={`${unit.id}-rng-${idx}-${ruleId}`}
                                className="rule-badge-wrapper"
                              >
                                <span className="rule-badge">{displayName}</span>
                                <span className="rule-tooltip">{tooltipText}</span>
                              </span>
                            );
                          })}
                          {idx === (unit.selectedRngWeaponIndex ?? 0) && (
                            <span
                              style={{ marginLeft: "8px", color: "#64c8ff", fontSize: "0.9em" }}
                            >
                              ●
                            </span>
                          )}
                        </td>
                        <td
                          className="unit-status-cell"
                          style={{ textAlign: "center", padding: "4px 8px", fontSize: "12px" }}
                        >
                          {weapon.RNG ? `${weapon.RNG}"` : "/"}
                        </td>
                        <td
                          className="unit-status-cell"
                          style={{ textAlign: "center", padding: "4px 8px", fontSize: "12px" }}
                        >
                          {weapon.NB || 0}
                        </td>
                        <td
                          className="unit-status-cell"
                          style={{ textAlign: "center", padding: "4px 8px", fontSize: "12px" }}
                        >
                          {weapon.ATK ? `${weapon.ATK}+` : "-"}
                        </td>
                        <td
                          className="unit-status-cell"
                          style={{ textAlign: "center", padding: "4px 8px", fontSize: "12px" }}
                        >
                          {weapon.STR || "-"}
                        </td>
                        <td
                          className="unit-status-cell"
                          style={{
                            textAlign: "center",
                            padding: "4px 8px",
                            fontSize: "12px",
                            borderRight: "1px solid #333",
                          }}
                        >
                          {weapon.AP || "-"}
                        </td>
                        <td
                          className="unit-status-cell"
                          style={{ textAlign: "center", padding: "4px 8px", fontSize: "12px" }}
                        >
                          {weapon.DMG || "-"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                )}
              </table>
            )}

            {/* MELEE WEAPON(S) Table */}
            {ccWeapons.length > 0 && (
              <table
                style={{
                  width: "calc(100% - 16px)",
                  borderCollapse: "collapse",
                  tableLayout: "fixed",
                }}
              >
                <colgroup>
                  <col style={{ width: "200px" }} />
                  <col style={{ width: "48px" }} />
                  <col style={{ width: "48px" }} />
                  <col style={{ width: "48px" }} />
                  <col style={{ width: "48px" }} />
                  <col style={{ width: "48px" }} />
                  <col style={{ width: "48px" }} />
                </colgroup>
                <thead>
                  <tr
                    className="unit-status-row unit-status-row--section-header"
                    style={{
                      backgroundColor: "rgba(200, 50, 50, 0.2)",
                      fontWeight: "bold",
                      fontSize: "0.9em",
                    }}
                  >
                    <th
                      className="unit-status-cell"
                      style={{
                        backgroundColor: "rgba(200, 50, 50, 0.2)",
                        color: "#ffffff",
                        textAlign: "left",
                        padding: "4px 8px",
                      }}
                    >
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          onToggleMeleeExpand(unit.id);
                        }}
                        style={{
                          background: "rgba(200, 100, 150, 0.3)",
                          border: "1px solid rgba(200, 100, 150, 0.5)",
                          color: "#c86496",
                          fontSize: "12px",
                          fontWeight: "bold",
                          cursor: "pointer",
                          padding: "2px 5px",
                          display: "inline-flex",
                          alignItems: "center",
                          justifyContent: "center",
                          minWidth: "20px",
                          minHeight: "20px",
                          borderRadius: "3px",
                          transition: "all 0.2s ease",
                          marginRight: "8px",
                          verticalAlign: "middle",
                        }}
                        onMouseEnter={(e) => {
                          e.currentTarget.style.background = "rgba(200, 100, 150, 0.5)";
                        }}
                        onMouseLeave={(e) => {
                          e.currentTarget.style.background = "rgba(200, 100, 150, 0.3)";
                        }}
                        aria-label={
                          isMeleeExpanded ? "Collapse melee weapons" : "Expand melee weapons"
                        }
                      >
                        {isMeleeExpanded ? "−" : "+"}
                      </button>
                      <span style={{ fontSize: "11px" }}>MELEE WEAPON(S)</span>
                    </th>
                    <th
                      className="unit-status-cell"
                      style={{
                        textAlign: "center",
                        padding: "4px 8px",
                        color: "#aee6ff",
                        fontWeight: "bold",
                        fontSize: "11px",
                        backgroundColor: "rgba(200, 50, 50, 0.2)",
                      }}
                    >
                      Rng
                    </th>
                    <th
                      className="unit-status-cell"
                      style={{
                        textAlign: "center",
                        padding: "4px 8px",
                        color: "#aee6ff",
                        fontWeight: "bold",
                        fontSize: "11px",
                        backgroundColor: "rgba(200, 50, 50, 0.2)",
                      }}
                    >
                      A
                    </th>
                    <th
                      className="unit-status-cell"
                      style={{
                        textAlign: "center",
                        padding: "4px 8px",
                        color: "#aee6ff",
                        fontWeight: "bold",
                        fontSize: "11px",
                        backgroundColor: "rgba(200, 50, 50, 0.2)",
                      }}
                    >
                      CC
                    </th>
                    <th
                      className="unit-status-cell"
                      style={{
                        textAlign: "center",
                        padding: "4px 8px",
                        color: "#aee6ff",
                        fontWeight: "bold",
                        fontSize: "11px",
                        backgroundColor: "rgba(200, 50, 50, 0.2)",
                      }}
                    >
                      S
                    </th>
                    <th
                      className="unit-status-cell"
                      style={{
                        textAlign: "center",
                        padding: "4px 8px",
                        color: "#aee6ff",
                        fontWeight: "bold",
                        fontSize: "11px",
                        backgroundColor: "rgba(200, 50, 50, 0.2)",
                      }}
                    >
                      AP
                    </th>
                    <th
                      className="unit-status-cell"
                      style={{
                        textAlign: "center",
                        padding: "4px 8px",
                        color: "#aee6ff",
                        fontWeight: "bold",
                        fontSize: "11px",
                        backgroundColor: "rgba(200, 50, 50, 0.2)",
                      }}
                    >
                      DMG
                    </th>
                  </tr>
                </thead>
                {isMeleeExpanded && (
                  <tbody>
                    {ccWeapons.map((weapon, idx) => (
                      <tr
                        key={`cc-${unit.id}-${weapon.display_name}-${idx}`}
                        className="unit-status-row unit-status-row--weapon"
                        style={{
                          backgroundColor: idx === 0 ? "#222" : "#2a2a2a",
                        }}
                      >
                        <td
                          className="unit-status-cell unit-status-cell--type"
                          style={{
                            padding: "4px 8px",
                            textAlign: "left",
                            fontSize: "12px",
                            overflow: "visible",
                            textOverflow: "clip",
                          }}
                        >
                          {weapon.display_name}
                          {weapon.WEAPON_RULES?.map((ruleId) => {
                            const { displayName, tooltipText } = getWeaponRuleDisplay(ruleId);
                            return (
                              <span
                                key={`${unit.id}-cc-${idx}-${ruleId}`}
                                className="rule-badge-wrapper"
                              >
                                <span className="rule-badge">{displayName}</span>
                                <span className="rule-tooltip">{tooltipText}</span>
                              </span>
                            );
                          })}
                          {idx === (unit.selectedCcWeaponIndex ?? 0) && (
                            <span
                              style={{ marginLeft: "8px", color: "#ff96c8", fontSize: "0.9em" }}
                            >
                              ●
                            </span>
                          )}
                        </td>
                        <td
                          className="unit-status-cell"
                          style={{ textAlign: "center", padding: "4px 8px", fontSize: "12px" }}
                        >
                          /
                        </td>
                        <td
                          className="unit-status-cell"
                          style={{ textAlign: "center", padding: "4px 8px", fontSize: "12px" }}
                        >
                          {weapon.NB || 0}
                        </td>
                        <td
                          className="unit-status-cell"
                          style={{ textAlign: "center", padding: "4px 8px", fontSize: "12px" }}
                        >
                          {weapon.ATK ? `${weapon.ATK}+` : "-"}
                        </td>
                        <td
                          className="unit-status-cell"
                          style={{ textAlign: "center", padding: "4px 8px", fontSize: "12px" }}
                        >
                          {weapon.STR || "-"}
                        </td>
                        <td
                          className="unit-status-cell"
                          style={{
                            textAlign: "center",
                            padding: "4px 8px",
                            fontSize: "12px",
                            borderRight: "1px solid #333",
                          }}
                        >
                          {weapon.AP || "-"}
                        </td>
                        <td
                          className="unit-status-cell"
                          style={{ textAlign: "center", padding: "4px 8px", fontSize: "12px" }}
                        >
                          {weapon.DMG || "-"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                )}
              </table>
            )}
          </div>
        )}
      </div>
    );
  }
);

UnitRow.displayName = "UnitRow";

export const UnitStatusTable = memo<UnitStatusTableProps>(
  ({
    units,
    player,
    playerTypes,
    selectedUnitId,
    guidedFocusUnitId = null,
    clickedUnitId,
    onSelectUnit,
    gameMode = "pvp",
    isReplay = false,
    victoryPoints,
    onCollapseChange,
    tutorialForceTableExpanded = false,
    tutorialForceUnitIdsExpanded,
    tutorialForceUnitIdsCollapsed,
    onNameMColumnsRect,
    tutorialForceRangedExpandedForUnitIds,
    onRangedWeaponsSectionRect,
    onUnitAttributesSectionRect,
    tutorialReportAttributesForUnitIds,
    onP2UnitRowRects,
    tutorialReportP2UnitRowRects = false,
  }) => {
    const nameHeaderRef = useRef<HTMLTableCellElement>(null);
    const mHeaderRef = useRef<HTMLTableCellElement>(null);
    const tableHeaderRowRef = useRef<HTMLTableRowElement>(null);
    const p2UnitRectsRef = useRef<Map<UnitId, { shape: "rect"; left: number; top: number; width: number; height: number }>>(new Map());

    const handleP2UnitRowRect = useCallback(
      (unitId: UnitId, rect: { shape: "rect"; left: number; top: number; width: number; height: number } | null) => {
        if (!onP2UnitRowRects) return;
        if (rect) {
          p2UnitRectsRef.current.set(unitId, rect);
        } else {
          p2UnitRectsRef.current.delete(unitId);
        }
        onP2UnitRowRects(Array.from(p2UnitRectsRef.current.values()));
      },
      [onP2UnitRowRects]
    );

    useEffect(() => {
      if (!tutorialReportP2UnitRowRects && onP2UnitRowRects) {
        p2UnitRectsRef.current.clear();
        onP2UnitRowRects(null);
      }
    }, [tutorialReportP2UnitRowRects, onP2UnitRowRects]);

    // Collapse/expand state for entire table
    const [isCollapsed, setIsCollapsed] = useState(true);

    // Expanded units state (per unit expand/collapse for weapons)
    const [expandedUnits, setExpandedUnits] = useState<Set<UnitId>>(new Set());
    const [expandedRanged, setExpandedRanged] = useState<Set<UnitId>>(new Set());
    const [expandedMelee, setExpandedMelee] = useState<Set<UnitId>>(new Set());
    const guidedLayoutSnapshotRef = useRef<{
      isCollapsed: boolean;
      expandedUnits: Set<UnitId>;
      expandedRanged: Set<UnitId>;
      expandedMelee: Set<UnitId>;
    } | null>(null);
    const guidedAppliedRef = useRef(false);

    const toggleUnitExpand = (unitId: UnitId) => {
      setExpandedUnits((prev) => {
        const next = new Set(prev);
        const isCurrentlyExpanded = next.has(unitId);
        if (isCurrentlyExpanded) {
          next.delete(unitId);
          // Also collapse weapons when collapsing unit
          setExpandedRanged((prevRng) => {
            const nextRng = new Set(prevRng);
            nextRng.delete(unitId);
            return nextRng;
          });
          setExpandedMelee((prevMelee) => {
            const nextMelee = new Set(prevMelee);
            nextMelee.delete(unitId);
            return nextMelee;
          });
        } else {
          next.add(unitId);
          // Also expand weapons when expanding unit
          setExpandedRanged((prevRng) => {
            const nextRng = new Set(prevRng);
            nextRng.add(unitId);
            return nextRng;
          });
          setExpandedMelee((prevMelee) => {
            const nextMelee = new Set(prevMelee);
            nextMelee.add(unitId);
            return nextMelee;
          });
        }
        return next;
      });
    };

    const toggleRangedExpand = (unitId: UnitId) => {
      setExpandedRanged((prev) => {
        const next = new Set(prev);
        if (next.has(unitId)) {
          next.delete(unitId);
        } else {
          next.add(unitId);
        }
        return next;
      });
    };

    const toggleMeleeExpand = (unitId: UnitId) => {
      setExpandedMelee((prev) => {
        const next = new Set(prev);
        if (next.has(unitId)) {
          next.delete(unitId);
        } else {
          next.add(unitId);
        }
        return next;
      });
    };

    // Tutoriel : forcer table dépliée et unités ciblées dépliées (voir attributs Intercessor)
    // État dérivé : quand la prop est true, on affiche toujours la table dépliée (évite les soucis de timing)
    const effectiveCollapsed = tutorialForceTableExpanded ? false : isCollapsed;

    useEffect(() => {
      if (tutorialForceTableExpanded && isCollapsed) {
        setIsCollapsed(false);
        onCollapseChange?.(false);
      }
    }, [tutorialForceTableExpanded, isCollapsed, onCollapseChange]);

    useEffect(() => {
      if (tutorialForceUnitIdsExpanded && tutorialForceUnitIdsExpanded.length > 0) {
        setExpandedUnits((prev) => {
          const next = new Set(prev);
          for (const id of tutorialForceUnitIdsExpanded) {
            next.add(id);
          }
          return next;
        });
      }
    }, [tutorialForceUnitIdsExpanded]);

    useEffect(() => {
      if (tutorialForceUnitIdsCollapsed && tutorialForceUnitIdsCollapsed.length > 0) {
        setExpandedUnits((prev) => {
          const next = new Set(prev);
          for (const id of tutorialForceUnitIdsCollapsed) {
            next.delete(id);
          }
          return next;
        });
      }
    }, [tutorialForceUnitIdsCollapsed]);

    useEffect(() => {
      if (
        tutorialForceRangedExpandedForUnitIds &&
        tutorialForceRangedExpandedForUnitIds.length > 0 &&
        player === 1
      ) {
        setExpandedRanged((prev) => {
          const next = new Set(prev);
          for (const id of tutorialForceRangedExpandedForUnitIds) {
            next.add(id);
          }
          return next;
        });
      }
    }, [tutorialForceRangedExpandedForUnitIds, player]);

    // Filter units for this player and exclude dead units
    const playerUnits = useMemo(() => {
      return units.filter((unit) => unit.player === player && (unit.HP_CUR ?? unit.HP_MAX) > 0);
    }, [units, player]);

    useEffect(() => {
      const targetUnitInThisTable =
        guidedFocusUnitId !== null &&
        playerUnits.some((unit) => String(unit.id) === String(guidedFocusUnitId));

      if (targetUnitInThisTable) {
        if (guidedLayoutSnapshotRef.current === null) {
          guidedLayoutSnapshotRef.current = {
            isCollapsed: effectiveCollapsed,
            expandedUnits: new Set(expandedUnits),
            expandedRanged: new Set(expandedRanged),
            expandedMelee: new Set(expandedMelee),
          };
        }
        if (effectiveCollapsed) {
          setIsCollapsed(false);
          onCollapseChange?.(false);
        }
        setExpandedUnits((prev) => {
          if (prev.has(guidedFocusUnitId)) {
            return prev;
          }
          const next = new Set(prev);
          next.add(guidedFocusUnitId);
          return next;
        });
        setExpandedRanged((prev) => {
          if (prev.has(guidedFocusUnitId)) {
            return prev;
          }
          const next = new Set(prev);
          next.add(guidedFocusUnitId);
          return next;
        });
        setExpandedMelee((prev) => {
          if (prev.has(guidedFocusUnitId)) {
            return prev;
          }
          const next = new Set(prev);
          next.add(guidedFocusUnitId);
          return next;
        });
        guidedAppliedRef.current = true;
        return;
      }

      if (!guidedAppliedRef.current || guidedLayoutSnapshotRef.current === null) {
        return;
      }

      const snapshot = guidedLayoutSnapshotRef.current;
      setIsCollapsed(snapshot.isCollapsed);
      onCollapseChange?.(snapshot.isCollapsed);
      setExpandedUnits(new Set(snapshot.expandedUnits));
      setExpandedRanged(new Set(snapshot.expandedRanged));
      setExpandedMelee(new Set(snapshot.expandedMelee));
      guidedLayoutSnapshotRef.current = null;
      guidedAppliedRef.current = false;
    }, [
      guidedFocusUnitId,
      playerUnits,
      effectiveCollapsed,
      expandedUnits,
      expandedRanged,
      expandedMelee,
      onCollapseChange,
    ]);

    const getPlayerTypeLabel = (playerNumber: 1 | 2): string => {
      if (!playerTypes) {
        throw new Error("UnitStatusTable requires game_state.player_types for player header labels");
      }
      const runtimePlayerType = playerTypes[String(playerNumber)];
      if (runtimePlayerType === "human") {
        return `Player ${playerNumber} - Human`;
      }
      if (runtimePlayerType === "ai") {
        if (gameMode === "training" || isReplay) {
          return `Player ${playerNumber} - AI/Bot`;
        }
        return `Player ${playerNumber} - AI`;
      }
      if (runtimePlayerType === "bot") {
        return `Player ${playerNumber} - Bot`;
      }
      throw new Error(
        `Invalid player type for player ${playerNumber}: ${String(runtimePlayerType)}. ` +
          "Expected 'human', 'ai', or 'bot'."
      );
    };

    if (playerUnits.length === 0) {
      return (
        <div className="unit-status-table-container">
          <div className="unit-status-table-empty">
            {getPlayerTypeLabel(player)}: No units remaining
          </div>
        </div>
      );
    }

    return (
      <div className="unit-status-table-container">
        <div className="unit-status-table-wrapper">
          {/* Player Header */}
          <div
            className={`unit-status-player-header ${player === 2 ? "unit-status-player-header--red" : ""}`}
            style={{
              backgroundColor: player === 2 ? "var(--hp-bar-player2)" : "var(--hp-bar-player1)",
              padding: "4px 8px",
              textAlign: "left",
              fontWeight: "bold",
              border: "1px solid rgba(0, 0, 0, 0.2)",
              marginBottom: "4px",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <button
                  type="button"
                  onClick={() => {
                    if (tutorialForceTableExpanded) return;
                    const newCollapsed = !isCollapsed;
                    setIsCollapsed(newCollapsed);
                    onCollapseChange?.(newCollapsed);
                  }}
                  style={{
                    background: "rgba(0, 0, 0, 0.2)",
                    border: "1px solid rgba(0, 0, 0, 0.3)",
                    color: "inherit",
                    fontSize: "16px",
                    fontWeight: "bold",
                    cursor: "pointer",
                    padding: "4px 8px",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    minWidth: "24px",
                    minHeight: "24px",
                    borderRadius: "4px",
                    transition: "all 0.2s ease",
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.background = "rgba(0, 0, 0, 0.3)";
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.background = "rgba(0, 0, 0, 0.2)";
                  }}
                  aria-label={effectiveCollapsed ? "Expand table" : "Collapse table"}
                >
                  {effectiveCollapsed ? "+" : "−"}
                </button>
                <span style={{ fontSize: "16px" }}>{getPlayerTypeLabel(player)}</span>
              </div>
              {victoryPoints !== undefined && (
                <span style={{ fontSize: "14px" }}>{`VP : ${victoryPoints}`}</span>
              )}
            </div>
          </div>

          {/* Column Headers */}
          {!effectiveCollapsed && (
            <table
              style={{
                width: "100%",
                borderCollapse: "collapse",
                marginBottom: "2px",
                tableLayout: "fixed",
              }}
            >
              <colgroup>
                <col style={{ width: "40px" }} />
                <col style={{ width: "40px" }} />
                <col style={{ width: "auto" }} />
                <col style={{ width: "70px" }} />
                <col style={{ width: "70px" }} />
                <col style={{ width: "70px" }} />
                <col style={{ width: "70px" }} />
                <col style={{ width: "70px" }} />
                <col style={{ width: "70px" }} />
                <col style={{ width: "70px" }} />
              </colgroup>
              <thead>
                <tr ref={tableHeaderRowRef} className="unit-status-header">
                  <th
                    className="unit-status-header-cell"
                    style={{
                      padding: "6px 8px",
                      textAlign: "center",
                      backgroundColor: "rgba(0, 0, 0, 0.05)",
                      border: "1px solid rgba(0, 0, 0, 0.1)",
                      fontSize: "14px",
                    }}
                  ></th>
                  <th
                    className="unit-status-header-cell"
                    style={{
                      padding: "6px 8px",
                      textAlign: "center",
                      backgroundColor: "rgba(0, 0, 0, 0.05)",
                      border: "1px solid rgba(0, 0, 0, 0.1)",
                      borderRight: "1px solid rgba(0, 0, 0, 0.1)",
                      fontSize: "14px",
                    }}
                  >
                    ID
                  </th>
                  <th
                    ref={nameHeaderRef}
                    className="unit-status-header-cell"
                    style={{
                      padding: "6px 8px",
                      textAlign: "center",
                      backgroundColor: "rgba(0, 0, 0, 0.05)",
                      border: "1px solid rgba(0, 0, 0, 0.1)",
                      fontSize: "14px",
                    }}
                  >
                    Name
                  </th>
                  <th
                    className="unit-status-header-cell"
                    style={{
                      padding: "6px 8px",
                      textAlign: "center",
                      backgroundColor: "rgba(0, 0, 0, 0.05)",
                      border: "1px solid rgba(0, 0, 0, 0.1)",
                      fontSize: "14px",
                    }}
                  >
                    HP
                  </th>
                  <th
                    ref={mHeaderRef}
                    className="unit-status-header-cell"
                    style={{
                      padding: "6px 8px",
                      textAlign: "center",
                      backgroundColor: "rgba(0, 0, 0, 0.05)",
                      border: "1px solid rgba(0, 0, 0, 0.1)",
                      borderRight: "1px solid rgba(0, 0, 0, 0.1)",
                      fontSize: "14px",
                    }}
                  >
                    <TooltipWrapper text="Movement">M</TooltipWrapper>
                  </th>
                  <th
                    className="unit-status-header-cell"
                    style={{
                      padding: "6px 8px",
                      textAlign: "center",
                      backgroundColor: "rgba(0, 0, 0, 0.05)",
                      border: "1px solid rgba(0, 0, 0, 0.1)",
                      fontSize: "14px",
                    }}
                  >
                    <TooltipWrapper text="Toughness">T</TooltipWrapper>
                  </th>
                  <th
                    className="unit-status-header-cell"
                    style={{
                      padding: "6px 8px",
                      textAlign: "center",
                      backgroundColor: "rgba(0, 0, 0, 0.05)",
                      border: "1px solid rgba(0, 0, 0, 0.1)",
                      fontSize: "14px",
                    }}
                  >
                    <TooltipWrapper text="Save Value">SV</TooltipWrapper>
                  </th>
                  <th
                    className="unit-status-header-cell"
                    style={{
                      padding: "6px 8px",
                      textAlign: "center",
                      backgroundColor: "rgba(0, 0, 0, 0.05)",
                      border: "1px solid rgba(0, 0, 0, 0.1)",
                      fontSize: "14px",
                    }}
                  >
                    <TooltipWrapper text="Leadership">LD</TooltipWrapper>
                  </th>
                  <th
                    className="unit-status-header-cell"
                    style={{
                      padding: "6px 8px",
                      textAlign: "center",
                      backgroundColor: "rgba(0, 0, 0, 0.05)",
                      border: "1px solid rgba(0, 0, 0, 0.1)",
                      fontSize: "14px",
                    }}
                  >
                    <TooltipWrapper text="Objective Control">OC</TooltipWrapper>
                  </th>
                  <th
                    className="unit-status-header-cell"
                    style={{
                      padding: "6px 8px",
                      textAlign: "center",
                      backgroundColor: "rgba(0, 0, 0, 0.05)",
                      border: "1px solid rgba(0, 0, 0, 0.1)",
                      fontSize: "14px",
                    }}
                  >
                    <TooltipWrapper text="Unit Value">VAL</TooltipWrapper>
                  </th>
                </tr>
              </thead>
            </table>
          )}

          {/* Units List */}
          {!effectiveCollapsed &&
            playerUnits.map((unit) => (
              <UnitRow
                key={unit.id}
                unit={unit}
                isSelected={selectedUnitId === unit.id}
                isClicked={clickedUnitId === unit.id && selectedUnitId !== unit.id}
                onSelect={onSelectUnit}
                isUnitExpanded={expandedUnits.has(unit.id)}
                onToggleUnitExpand={toggleUnitExpand}
                isRangedExpanded={expandedRanged.has(unit.id)}
                onToggleRangedExpand={toggleRangedExpand}
                isMeleeExpanded={expandedMelee.has(unit.id)}
                onToggleMeleeExpand={toggleMeleeExpand}
                reportNameMRect={
                  player === 1 && onNameMColumnsRect && (String(unit.id) === "1" || unit.id === 1)
                    ? onNameMColumnsRect
                    : undefined
                }
                nameHeaderRef={nameHeaderRef}
                mHeaderRef={mHeaderRef}
                reportRangedWeaponsRect={
                  player === 1 &&
                  onRangedWeaponsSectionRect &&
                  tutorialForceRangedExpandedForUnitIds?.some(
                    (id) => String(unit.id) === String(id) || unit.id === id
                  )
                    ? onRangedWeaponsSectionRect
                    : undefined
                }
                reportUnitAttributesRect={
                  onUnitAttributesSectionRect &&
                  tutorialReportAttributesForUnitIds?.some(
                    (id) => String(unit.id) === String(id) || unit.id === id
                  )
                    ? onUnitAttributesSectionRect
                    : undefined
                }
                reportUnitRowRect={
                  player === 2 && tutorialReportP2UnitRowRects && onP2UnitRowRects
                    ? handleP2UnitRowRect
                    : undefined
                }
                tableHeaderRowRef={tableHeaderRowRef}
              />
            ))}
        </div>
      </div>
    );
  }
);

UnitStatusTable.displayName = "UnitStatusTable";
