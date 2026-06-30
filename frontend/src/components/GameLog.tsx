// frontend/src/components/GameLog.tsx
// frontend/src/components/GameLog.tsx
import React from "react";
import { createPortal } from "react-dom";
import unitRulesConfig from "../../../config/unit_rules.json";
import weaponRulesConfig from "../../../config/weapon_rules.json";
import {
  type BaseLogEntry,
  getEventIcon,
  getEventTypeClass,
} from "../../../shared/gameLogStructure.ts";
import { AdvancedIcon, ChargedIcon, MovedIcon } from "./UnitStatusBadges";

const RULE_TOKEN_REGEX = /\[([^\]]+)\]/g;

const normalizeRuleLookupKey = (value: string): string => {
  return value
    .trim()
    .toUpperCase()
    .replace(/[:]+/g, " ")
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ");
};

const requireNonEmptyString = (value: unknown, errorMessage: string): string => {
  if (typeof value !== "string" || value.trim() === "") {
    throw new Error(errorMessage);
  }
  return value.trim();
};

const setRuleDescription = (
  descriptions: Map<string, string>,
  rawLookupKey: string,
  description: string,
  allowOverride: boolean
): void => {
  const lookupKey = normalizeRuleLookupKey(rawLookupKey);
  if (lookupKey === "") {
    throw new Error("Rule lookup key cannot be empty");
  }
  if (allowOverride || !descriptions.has(lookupKey)) {
    descriptions.set(lookupKey, description);
  }
};

const resolveRuleDescription = (
  tokenLabel: string,
  ruleDescriptionByLookup: Map<string, string>,
  ruleHintByLabel?: Record<string, string>
): string | undefined => {
  const direct = ruleDescriptionByLookup.get(normalizeRuleLookupKey(tokenLabel));
  if (direct) {
    return direct;
  }
  const parameterizedMatch = tokenLabel.match(/^(.+?)(?:\s*[: ]\s*\d+\+?)$/);
  if (parameterizedMatch) {
    const parameterizedDescription = ruleDescriptionByLookup.get(
      normalizeRuleLookupKey(parameterizedMatch[1])
    );
    if (parameterizedDescription) {
      return parameterizedDescription;
    }
  }
  if (ruleHintByLabel) {
    for (const [hintLabel, hintedRuleId] of Object.entries(ruleHintByLabel)) {
      if (normalizeRuleLookupKey(hintLabel) !== normalizeRuleLookupKey(tokenLabel)) {
        continue;
      }
      return ruleDescriptionByLookup.get(normalizeRuleLookupKey(hintedRuleId));
    }
  }
  return undefined;
};

const RuleReferenceTag: React.FC<{ label: string; description: string }> = ({
  label,
  description,
}) => {
  const [isTooltipPinned, setIsTooltipPinned] = React.useState(false);
  const [isTooltipHovered, setIsTooltipHovered] = React.useState(false);
  const buttonRef = React.useRef<HTMLButtonElement | null>(null);
  const [tooltipCoords, setTooltipCoords] = React.useState<{
    left: number;
    top: number;
    placeAbove: boolean;
  }>({
    left: 0,
    top: 0,
    placeAbove: false,
  });
  const tooltipVisible = isTooltipPinned || isTooltipHovered;
  const updateTooltipPosition = React.useCallback(() => {
    const button = buttonRef.current;
    if (!button) {
      return;
    }
    const rect = button.getBoundingClientRect();
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;
    const tooltipWidth = 320;
    const horizontalPadding = 10;
    const left = Math.max(
      horizontalPadding,
      Math.min(rect.left, viewportWidth - tooltipWidth - horizontalPadding)
    );
    const preferAbove = rect.bottom > viewportHeight - 180;
    const top = preferAbove ? rect.top - 8 : rect.bottom + 8;
    setTooltipCoords({ left, top, placeAbove: preferAbove });
  }, []);

  React.useEffect(() => {
    if (!tooltipVisible) {
      return;
    }
    updateTooltipPosition();
    const handleViewportChange = () => {
      updateTooltipPosition();
    };
    window.addEventListener("scroll", handleViewportChange, true);
    window.addEventListener("resize", handleViewportChange);
    return () => {
      window.removeEventListener("scroll", handleViewportChange, true);
      window.removeEventListener("resize", handleViewportChange);
    };
  }, [tooltipVisible, updateTooltipPosition]);

  return (
    <span className="game-log-rule-ref">
      <button
        ref={buttonRef}
        type="button"
        className={`game-log-rule-ref__button ${tooltipVisible ? "game-log-rule-ref__button--active" : ""}`}
        onMouseEnter={() => {
          setIsTooltipHovered(true);
          updateTooltipPosition();
        }}
        onMouseLeave={() => setIsTooltipHovered(false)}
        onFocus={() => {
          setIsTooltipHovered(true);
          updateTooltipPosition();
        }}
        onBlur={() => setIsTooltipHovered(false)}
        onClick={() => {
          updateTooltipPosition();
          setIsTooltipPinned((prev) => !prev);
        }}
        aria-label={`Afficher la description de la regle ${label}`}
      >
        [{label}]
      </button>
      {tooltipVisible &&
        createPortal(
          <span
            className={`game-log-rule-ref__tooltip game-log-rule-ref__tooltip--floating ${
              tooltipCoords.placeAbove ? "game-log-rule-ref__tooltip--above" : ""
            }`}
            style={{ left: `${tooltipCoords.left}px`, top: `${tooltipCoords.top}px` }}
          >
            {description}
          </span>,
          document.body
        )}
    </span>
  );
};

// Use shared interface as base, add frontend-specific fields
export interface GameLogEvent extends BaseLogEntry {
  id: string;
  timestamp: Date;
  action_name?: string;
  actionName?: string;
  is_ai_action?: boolean;
  reward?: number;
  ruleHintByLabel?: Record<string, string>;
}
/** Rect viewport pour halo tutoriel (dernière ligne du log). */
export type GameLogLastEntryRect = {
  shape: "rect";
  left: number;
  top: number;
  width: number;
  height: number;
};

interface GameLogProps {
  events: GameLogEvent[];
  maxEvents?: number;
  availableHeight?: number;
  useStepNumbers?: boolean;
  currentTurn?: number;
  debugMode?: boolean;
  /** Tutoriel 2-1 : rapporter le rect de la dernière ligne (la plus récente) pour halo. */
  onLastEntryRect?: (rect: GameLogLastEntryRect | null) => void;
  /** Tutoriel 2-1 : rapporter le rect du titre (header) du Game Log pour halo. */
  onHeaderRect?: (rect: GameLogLastEntryRect | null) => void;
  /** Tutoriel : rapporter les rects des 2 lignes supérieures (entrées les plus récentes). */
  onTopTwoEntriesRects?: (rects: GameLogLastEntryRect[]) => void;
}

export const GameLog: React.FC<GameLogProps> = ({
  events,
  availableHeight: _availableHeight = 152,
  useStepNumbers = false,
  debugMode = false,
  onLastEntryRect,
  onHeaderRect,
  onTopTwoEntriesRects,
}) => {
  const eventsContainerRef = React.useRef<HTMLDivElement>(null);
  const lastEntryRef = React.useRef<HTMLDivElement>(null);
  const headerRef = React.useRef<HTMLDivElement>(null);
  const topEntryRefs = React.useRef<Array<HTMLDivElement | null>>([]);
  const [expandedEntries, setExpandedEntries] = React.useState<Set<string>>(new Set());

  const toggleExpanded = React.useCallback((id: string) => {
    setExpandedEntries((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }, []);
  const [_gameLogScrollTick, setGameLogScrollTick] = React.useState(0);

  React.useLayoutEffect(() => {
    const el = eventsContainerRef.current;
    if (!el) return;
    if (!onLastEntryRect && !onHeaderRect && !onTopTwoEntriesRects) return;
    const onContainerScroll = () => {
      setGameLogScrollTick((n) => n + 1);
    };
    el.addEventListener("scroll", onContainerScroll, { passive: true });
    return () => {
      el.removeEventListener("scroll", onContainerScroll);
    };
  }, [onLastEntryRect, onHeaderRect, onTopTwoEntriesRects]);
  const ruleDescriptionByLookup = React.useMemo(() => {
    const descriptions = new Map<string, string>();

    // 1) Unit rules have priority over weapon rules on collisions.
    const rawUnitRules = unitRulesConfig as Record<string, unknown>;
    for (const [entryKey, entryValue] of Object.entries(rawUnitRules)) {
      if (typeof entryValue !== "object" || entryValue === null) {
        throw new Error(`Invalid unit_rules.json entry '${entryKey}': expected object`);
      }
      const ruleEntry = entryValue as Record<string, unknown>;
      const id = requireNonEmptyString(
        ruleEntry.id,
        `Invalid unit_rules.json entry '${entryKey}': missing non-empty 'id'`
      );
      const description = requireNonEmptyString(
        ruleEntry.description,
        `Invalid unit_rules.json entry '${entryKey}': missing non-empty 'description'`
      );
      setRuleDescription(descriptions, entryKey, description, true);
      setRuleDescription(descriptions, id, description, true);
      if (typeof ruleEntry.name === "string" && ruleEntry.name.trim() !== "") {
        setRuleDescription(descriptions, ruleEntry.name, description, true);
      }
      if (typeof ruleEntry.alias === "string" && ruleEntry.alias.trim() !== "") {
        setRuleDescription(descriptions, ruleEntry.alias, description, true);
      }
    }

    // 2) Weapon rules are fallback candidates only (no override).
    const rawWeaponRules = weaponRulesConfig as Record<string, unknown>;
    for (const [entryKey, entryValue] of Object.entries(rawWeaponRules)) {
      if (typeof entryValue !== "object" || entryValue === null) {
        throw new Error(`Invalid weapon_rules.json entry '${entryKey}': expected object`);
      }
      const ruleEntry = entryValue as Record<string, unknown>;
      const description = requireNonEmptyString(
        ruleEntry.description,
        `Invalid weapon_rules.json entry '${entryKey}': missing non-empty 'description'`
      );
      const name = requireNonEmptyString(
        ruleEntry.name,
        `Invalid weapon_rules.json entry '${entryKey}': missing non-empty 'name'`
      );
      setRuleDescription(descriptions, entryKey, description, false);
      setRuleDescription(descriptions, name, description, false);
    }

    // Explicit labels used in logs that must always expose tooltips.
    const chargeImpactDescription = descriptions.get(normalizeRuleLookupKey("charge_impact"));
    if (chargeImpactDescription) {
      setRuleDescription(descriptions, "HAMMER OF WRATH", chargeImpactDescription, false);
    }
    setRuleDescription(
      descriptions,
      "FLY",
      "This unit can ignore walls and units during movement pathing, but must still end on a legal destination.",
      false
    );
    setRuleDescription(
      descriptions,
      "MW",
      "Direct damages, no save roll.",
      false
    );
    setRuleDescription(
      descriptions,
      "COVER",
      "-1 BS for the shooter against this target.",
      false
    );
    setRuleDescription(
      descriptions,
      "HAZARD",
      "Roll one D6 for each model in the unit: on a 1-2, the unit suffers 1 (or 3 if it is a MONSTER or VEHICLE) Mortal Wound.",
      false
    );

    return descriptions;
  }, []);

  const renderMessageWithRuleDescriptions = React.useCallback(
    (message: string | undefined, ruleHintByLabel?: Record<string, string>): React.ReactNode => {
      const safeMessage = typeof message === "string" ? message : "";
      if (safeMessage.length === 0) {
        return "";
      }
      const nodes: React.ReactNode[] = [];
      let lastIndex = 0;
      let match: RegExpExecArray | null;
      RULE_TOKEN_REGEX.lastIndex = 0;

      for (;;) {
        match = RULE_TOKEN_REGEX.exec(safeMessage);
        if (match === null) {
          break;
        }
        const [fullToken, tokenLabel] = match;
        if (match.index > lastIndex) {
          nodes.push(safeMessage.slice(lastIndex, match.index));
        }
        const description = resolveRuleDescription(
          tokenLabel,
          ruleDescriptionByLookup,
          ruleHintByLabel
        );
        if (description) {
          nodes.push(
            <RuleReferenceTag
              key={`${match.index}-${tokenLabel}`}
              label={tokenLabel}
              description={description}
            />
          );
        } else {
          nodes.push(fullToken);
        }
        lastIndex = RULE_TOKEN_REGEX.lastIndex;
      }

      if (lastIndex < safeMessage.length) {
        nodes.push(safeMessage.slice(lastIndex));
      }
      return nodes;
    },
    [ruleDescriptionByLookup]
  );

  // Display all events (newest first) - sort by timestamp descending, no limit
  const displayedEvents = [...events].sort((a, b) => b.timestamp.getTime() - a.timestamp.getTime());
  topEntryRefs.current = [];

  // Keep newest entry visible when new events arrive
  React.useEffect(() => {
    if (eventsContainerRef.current) {
      eventsContainerRef.current.scrollTop = 0;
    }
  }, []);

  // Tutoriel : rapporter les rects pour les halos. lastEntryRef = 1re entrée (index 0 = plus récente, en haut).
  // Le parent utilise "Header" pour la ligne du HAUT en 1-25 : on envoie donc la 1re ligne (lastEntryRef) vers onHeaderRect.
  React.useLayoutEffect(() => {
    if (!onLastEntryRect) return;
    if (!headerRef.current) {
      onLastEntryRect(null);
      return;
    }
    const rect = headerRef.current.getBoundingClientRect();
    onLastEntryRect({
      shape: "rect",
      left: rect.left,
      top: rect.top,
      width: rect.width,
      height: rect.height,
    });
    return () => onLastEntryRect(null);
  }, [onLastEntryRect]);

  React.useLayoutEffect(() => {
    if (!onHeaderRect) return;
    if (!lastEntryRef.current || displayedEvents.length === 0) {
      onHeaderRect(null);
      return;
    }
    const rect = lastEntryRef.current.getBoundingClientRect();
    onHeaderRect({
      shape: "rect",
      left: rect.left,
      top: rect.top,
      width: rect.width,
      height: rect.height,
    });
    return () => onHeaderRect(null);
  }, [onHeaderRect, displayedEvents.length]);

  React.useLayoutEffect(() => {
    if (!onTopTwoEntriesRects) return;
    const topEntryCount = Math.min(2, displayedEvents.length);
    const topTwo = topEntryRefs.current
      .slice(0, topEntryCount)
      .filter((node): node is HTMLDivElement => node != null)
      .map((node) => {
        const rect = node.getBoundingClientRect();
        return {
          shape: "rect" as const,
          left: rect.left,
          top: rect.top,
          width: rect.width,
          height: rect.height,
        };
      });
    onTopTwoEntriesRects(topTwo);
    return () => onTopTwoEntriesRects([]);
  }, [onTopTwoEntriesRects, displayedEvents.length]);

  return (
    <div className="game-log">
      <div
        ref={headerRef}
        className="game-log__header"
        style={{
          backgroundColor: "#059669",
          borderRadius: "6px",
          padding: "4px 8px",
          position: "relative",
        }}
      >
        <h3 className="game-log__title" style={{ color: "#FFFFFF", flex: 1, textAlign: "left" }}>
          Game Log
        </h3>
        <div
          className="game-log__count"
          style={{
            alignItems: "center",
            display: "inline-flex",
            justifyContent: "center",
            minHeight: "24px",
            position: "absolute",
            right: "8px",
          }}
        >
          {events.length} events
        </div>
      </div>

      <div className="game-log__content" style={{ flex: "1 1 auto", minHeight: 0 }}>
        {displayedEvents.length === 0 ? (
          <div className="game-log__empty" style={{ height: "100%" }}>
            No events yet. Start playing to see the action log!
          </div>
        ) : (
          <div
            ref={eventsContainerRef}
            className="game-log__events"
            style={{
              height: "100%",
              overflow: "auto",
            }}
          >
            {displayedEvents.map((event, index) => {
              // Check if this is a wait/skip action
              // Multiple detection methods:
              // 1. Check action_name field
              const actionName = event.action_name || event.actionName;
              const hasWaitActionName =
                actionName &&
                (actionName.toLowerCase() === "wait" || actionName.toLowerCase() === "skip");

              // 2. Check event type (backend logs wait actions differently - check message instead)
              const isWaitType = false; // 'wait' is not a valid type in BaseLogEntry, check message instead

              // 3. Check message content (frontend logs "chose not to move")
              const message = event.message || "";
              const hasWaitMessage =
                message.toLowerCase().includes("chose not to move") ||
                message.toLowerCase().includes("chose not to charge") ||
                message.toLowerCase().endsWith(" wait");

              const isWaitAction = hasWaitActionName || isWaitType || hasWaitMessage;
              const waitClass = isWaitAction ? "game-log-entry--wait" : "";
              const isObjectiveControl = actionName === "objective_control";
              const objectiveControlClass = isObjectiveControl
                ? event.player === 1
                  ? "game-log-entry--objective-control-p1"
                  : event.player === 2
                    ? "game-log-entry--objective-control-p2"
                    : "game-log-entry--objective-control-neutral"
                : "";

              return (
                <div
                  key={event.id}
                  ref={(node) => {
                    if (index === 0) {
                      lastEntryRef.current = node;
                    }
                    if (index < 2) {
                      topEntryRefs.current[index] = node;
                    }
                  }}
                  className={`game-log-entry ${getEventTypeClass(event)} ${waitClass} ${objectiveControlClass}`}
                >
                  <div className="game-log-entry__single-line">
                    {((event.shootDetails && event.shootDetails.length > 0) ||
                      (event.moveDetails && event.moveDetails.length > 0) ||
                      (event.hazardDetails && event.hazardDetails.length > 0)) && (
                      <button
                        type="button"
                        className="game-log-entry__expand-btn"
                        onClick={() => toggleExpanded(event.id)}
                        aria-label={
                          expandedEntries.has(event.id) ? "Réduire le détail" : "Voir le détail"
                        }
                      >
                        {expandedEntries.has(event.id) ? "−" : "+"}
                      </button>
                    )}
                    <span className={`game-log-entry__icon game-log-entry__icon--${event.type}`}>
                      {event.type === "battle_shock" ? (
                        event.result === "SUCCESS" ? (
                          <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
                            <circle cx="12" cy="12" r="10" fill="#bbf7d0" stroke="#166534" strokeWidth="1.5" />
                            <polyline points="6,14.5 12,8.5 18,14.5" fill="none" stroke="#166534" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
                          </svg>
                        ) : (
                          <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
                            <circle cx="12" cy="12" r="10" fill="#f4c81f" stroke="#991b1b" strokeWidth="1.5" />
                            <polyline points="6,9.5 12,15.5 18,9.5" fill="none" stroke="#991b1b" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
                          </svg>
                        )
                      ) : event.type === "advance" || event.action_name === "ADVANCED" ? (
                        <AdvancedIcon />
                      ) : event.type === "move" ? (
                        <MovedIcon />
                      ) : event.type === "charge" ? (
                        <ChargedIcon />
                      ) : (
                        getEventIcon(event.type)
                      )}
                    </span>
                    {useStepNumbers && (
                      <span className="game-log-entry__turn">
                        #{events.length - displayedEvents.findIndex((e) => e.id === event.id)}
                      </span>
                    )}
                    {event.turnNumber && (
                      <span className="game-log-entry__turn">T{event.turnNumber}</span>
                    )}
                    {event.player !== undefined && (
                      <span
                        className={`game-log-entry__player ${event.player === 1 ? "game-log-entry__player--blue" : "game-log-entry__player--red"}`}
                      >
                        {event.player === 1 ? "P1" : "P2"}
                      </span>
                    )}
                    <span className="game-log-entry__message">
                      {renderMessageWithRuleDescriptions(event.message, event.ruleHintByLabel)}
                    </span>
                    {/* NEW: Debug mode reward display for AI actions */}
                    {debugMode && event.is_ai_action && event.reward !== undefined && (
                      <span className="game-log-entry__reward">
                        {" "}
                        <span className="game-log-entry__reward-action">
                          {(event.action_name || "").toLowerCase()}
                        </span>{" "}
                        <span className="game-log-entry__reward-value">
                          {typeof event.reward === "number"
                            ? event.reward.toFixed(2)
                            : String(event.reward)}
                        </span>
                      </span>
                    )}
                  </div>
                  {expandedEntries.has(event.id) &&
                    event.shootDetails &&
                    event.shootDetails.length > 0 && (
                      <div className="game-log-entry__shot-details">
                        {(() => {
                          const allShots = event.shootDetails!;
                          const total = allShots.length;
                          const visibleShots = allShots.filter((s) => !s.wasted);
                          const wastedCount = total - visibleShots.length;
                          return (
                            <>
                              {visibleShots.map((shot) => {
                                const parts: string[] = [`${shot.shotNumber}/${total}`];
                                if (event.weaponName) parts.push(event.weaponName);
                                const targetType = shot.targetUnitType ?? event.targetUnitType;
                                if (targetType) parts.push(targetType);
                                parts.push(
                                  `Tir: ${shot.hitResult === "HIT" ? "✓" : "✗"}${shot.attackRoll !== undefined ? ` (${shot.attackRoll})` : ""}`
                                );
                                if (shot.hitResult === "HIT") {
                                  parts.push(
                                    `Bless: ${shot.strengthResult === "SUCCESS" ? "✓" : "✗"}${shot.strengthRoll !== undefined ? ` (${shot.strengthRoll})` : ""}`
                                  );
                                }
                                if (shot.strengthResult === "SUCCESS") {
                                  if (shot.saveRoll !== undefined) {
                                    parts.push(
                                      `Svg: ${shot.saveSuccess ? "✓" : "✗"} (${shot.saveRoll})`
                                    );
                                  }
                                  if (!shot.saveSuccess && shot.damageDealt !== undefined) {
                                    parts.push(`Dmg: ${shot.damageDealt}`);
                                    if (
                                      shot.targetCol !== undefined &&
                                      shot.targetRow !== undefined
                                    ) {
                                      parts.push(`(${shot.targetCol},${shot.targetRow})`);
                                    }
                                  }
                                  if (shot.targetDied) {
                                    parts.push("💀");
                                  }
                                }
                                return (
                                  <div
                                    key={shot.shotNumber}
                                    className="game-log-entry__shot-detail-row"
                                  >
                                    {parts.join(" | ")}
                                  </div>
                                );
                              })}
                              {wastedCount > 0 && (
                                <div className="game-log-entry__shot-detail-row game-log-entry__shot-detail-row--wasted">
                                  {`No more target - shots remaining: ${wastedCount}/${total}`}
                                </div>
                              )}
                            </>
                          );
                        })()}
                      </div>
                    )}
                  {expandedEntries.has(event.id) &&
                    event.moveDetails &&
                    event.moveDetails.length > 0 && (
                      <div className="game-log-entry__shot-details">
                        {(() => {
                          const verb =
                            event.type === "charge"
                              ? "CHARGED"
                              : event.type === "pile_in"
                                ? "PILED IN"
                                : event.type === "consolidation"
                                  ? "CONSOLIDATED"
                                  : event.action_name === "ADVANCED"
                                    ? "ADVANCED"
                                    : event.action_name === "FLED"
                                      ? "FLED"
                                      : "MOVED";
                          return event.moveDetails!.map((m) => {
                            const [squadId, modelIdx] = m.modelId.split("#");
                            return (
                              <div
                                key={m.modelId}
                                className="game-log-entry__shot-detail-row"
                              >
                                {`Unit ${squadId} # Model ${modelIdx} ${verb} from (${m.fromCol},${m.fromRow}) to (${m.toCol},${m.toRow})`}
                              </div>
                            );
                          });
                        })()}
                      </div>
                    )}
                  {expandedEntries.has(event.id) &&
                    event.hazardDetails &&
                    event.hazardDetails.length > 0 && (
                      <div className="game-log-entry__shot-details">
                        {(() => {
                          const all = event.hazardDetails!;
                          const seen = new Map<string, number>();
                          return all.map((h, i) => {
                            const [squadId, modelIdx] = h.modelId.split("#");
                            const occ = (seen.get(h.modelId) ?? 0) + 1;
                            seen.set(h.modelId, occ);
                            return (
                              <div
                                key={`${h.modelId}#mw${occ}`}
                                className="game-log-entry__shot-detail-row"
                              >
                                {`${i + 1}/${all.length} | Unit ${squadId} # Model ${modelIdx} - 1 MW at (${h.col},${h.row})${h.died ? " 💀" : ""}`}
                              </div>
                            );
                          });
                        })()}
                      </div>
                    )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
};
