import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";

interface TooltipWrapperProps {
  text?: string | null;
  children: ReactNode;
  as?: "span" | "div";
  className?: string;
}

const GAP = 6;
const VIEWPORT_PAD = 8;

function clampTooltipInViewport(
  trigger: DOMRectReadOnly,
  tipW: number,
  tipH: number
): { left: number; top: number } {
  const vw = window.innerWidth;
  const vh = window.innerHeight;

  let left = trigger.left;
  let top = trigger.top - GAP - tipH;

  if (top < VIEWPORT_PAD) {
    top = trigger.bottom + GAP;
  }

  if (left + tipW > vw - VIEWPORT_PAD) {
    left = vw - tipW - VIEWPORT_PAD;
  }
  if (left < VIEWPORT_PAD) {
    left = VIEWPORT_PAD;
  }

  if (top + tipH > vh - VIEWPORT_PAD) {
    top = vh - tipH - VIEWPORT_PAD;
  }
  if (top < VIEWPORT_PAD) {
    top = VIEWPORT_PAD;
  }

  return { left, top };
}

export default function TooltipWrapper({
  text,
  children,
  as = "span",
  className,
}: TooltipWrapperProps) {
  const wrapperRef = useRef<HTMLElement | null>(null);
  const tooltipRef = useRef<HTMLSpanElement | null>(null);
  const [isHovered, setIsHovered] = useState(false);
  const [tooltipAnchor, setTooltipAnchor] = useState<{ left: number; top: number } | null>(null);
  const [floatingPos, setFloatingPos] = useState<{ left: number; top: number } | null>(null);

  const updateTooltipAnchor = useCallback(() => {
    const wrapperElement = wrapperRef.current;
    if (!wrapperElement) {
      return;
    }
    const rect = wrapperElement.getBoundingClientRect();
    setTooltipAnchor({
      left: rect.left,
      top: rect.top,
    });
  }, []);

  const recalcFloatingPosition = useCallback(() => {
    const wrap = wrapperRef.current;
    const tip = tooltipRef.current;
    if (!wrap || !tip) {
      return;
    }
    const w = tip.offsetWidth;
    const h = tip.offsetHeight;
    if (w === 0 || h === 0) {
      return;
    }
    const trigger = wrap.getBoundingClientRect();
    setFloatingPos(clampTooltipInViewport(trigger, w, h));
  }, []);

  useLayoutEffect(() => {
    if (!isHovered || !tooltipAnchor) {
      setFloatingPos(null);
      return;
    }
    recalcFloatingPosition();
  }, [isHovered, tooltipAnchor, text, recalcFloatingPosition]);

  useEffect(() => {
    if (!isHovered) {
      return;
    }
    const onScrollOrResize = () => {
      updateTooltipAnchor();
    };
    window.addEventListener("scroll", onScrollOrResize, true);
    window.addEventListener("resize", onScrollOrResize);
    return () => {
      window.removeEventListener("scroll", onScrollOrResize, true);
      window.removeEventListener("resize", onScrollOrResize);
    };
  }, [isHovered, updateTooltipAnchor]);

  if (!text || text.trim().length === 0) {
    return <>{children}</>;
  }

  const Tag = as;
  const wrapperClassName = ["rule-badge-wrapper", className].filter(Boolean).join(" ");

  return (
    <Tag
      className={wrapperClassName}
      ref={(node: HTMLElement | null) => {
        wrapperRef.current = node;
      }}
      onMouseEnter={() => {
        updateTooltipAnchor();
        setIsHovered(true);
      }}
      onMouseMove={updateTooltipAnchor}
      onMouseLeave={() => {
        setIsHovered(false);
        setFloatingPos(null);
      }}
    >
      {children}
      {isHovered && tooltipAnchor
        ? createPortal(
            <span
              ref={tooltipRef}
              className="rule-tooltip rule-tooltip--floating"
              style={{
                position: "fixed",
                left: floatingPos ? `${floatingPos.left}px` : "-9999px",
                top: floatingPos ? `${floatingPos.top}px` : "0px",
                transform: "none",
                visibility: floatingPos ? "visible" : "hidden",
              }}
            >
              {text}
            </span>,
            document.body
          )
        : null}
    </Tag>
  );
}
