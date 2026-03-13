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

const RuleReferenceTag: React.FC<{ label: string; description: string }> = ({ label, description }) => {
  const [isTooltipPinned, setIsTooltipPinned] = React.useState(false);
  const [isTooltipHovered, setIsTooltipHovered] = React.useState(false);
  const buttonRef = React.useRef<HTMLButtonElement | null>(null);
  const [tooltipCoords, setTooltipCoords] = React.useState<{ left: number; top: number; placeAbove: boolean }>({
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
}

export const GameLog: React.FC<GameLogProps> = ({
  events,
  availableHeight = 220,
  useStepNumbers = false,
  debugMode = false,
  onLastEntryRect,
  onHeaderRect,
}) => {
  const eventsContainerRef = React.useRef<HTMLDivElement>(null);
  const lastEntryRef = React.useRef<HTMLDivElement>(null);
  const headerRef = React.useRef<HTMLDivElement>(null);
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
      "FLY: this unit can ignore walls and units during movement pathing, but must still end on a legal destination.",
      false
    );
    setRuleDescription(
      descriptions,
      "MW",
      "Mortal Wound: degat direct qui contourne les jets de sauvegarde.",
      false
    );
    setRuleDescription(
      descriptions,
      "COVER",
      "Cover: +1 au jet de sauvegarde d'armure pour cette attaque (bonus total capé a +1, non cumulable).",
      false
    );

    return descriptions;
  }, []);

  const renderMessageWithRuleDescriptions = React.useCallback(
    (message: string, ruleHintByLabel?: Record<string, string>): React.ReactNode => {
      const nodes: React.ReactNode[] = [];
      let lastIndex = 0;
      let match: RegExpExecArray | null;
      RULE_TOKEN_REGEX.lastIndex = 0;

      for (;;) {
        match = RULE_TOKEN_REGEX.exec(message);
        if (match === null) {
          break;
        }
        const [fullToken, tokenLabel] = match;
        if (match.index > lastIndex) {
          nodes.push(message.slice(lastIndex, match.index));
        }
        const description = resolveRuleDescription(tokenLabel, ruleDescriptionByLookup, ruleHintByLabel);
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

      if (lastIndex < message.length) {
        nodes.push(message.slice(lastIndex));
      }
      return nodes;
    },
    [ruleDescriptionByLookup]
  );

  // Display all events (newest first) - sort by timestamp descending, no limit
  const displayedEvents = [...events].sort((a, b) => b.timestamp.getTime() - a.timestamp.getTime());

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

  return (
    <div className="game-log">
      <div ref={headerRef} className="game-log__header">
        <h3 className="game-log__title">Game Log</h3>
        <div className="game-log__count">{events.length} events</div>
      </div>

      <div className="game-log__content">
        {displayedEvents.length === 0 ? (
          <div className="game-log__empty">No events yet. Start playing to see the action log!</div>
        ) : (
          <div
            ref={eventsContainerRef}
            className="game-log__events"
            style={{
              maxHeight: `${availableHeight}px`, // Use full available height
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
                  ref={index === 0 ? lastEntryRef : undefined}
                  className={`game-log-entry ${getEventTypeClass(event)} ${waitClass} ${objectiveControlClass}`}
                >
                  <div className="game-log-entry__single-line">
                    <span className={`game-log-entry__icon game-log-entry__icon--${event.type}`}>
                      {getEventIcon(event.type)}
                    </span>
                    {useStepNumbers && (
                      <span className="game-log-entry__turn">
                        #
                        {events.length - displayedEvents.findIndex((e) => e.id === event.id)}
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
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
};
