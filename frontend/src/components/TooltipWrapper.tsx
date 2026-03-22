import { useCallback, useRef, useState } from "react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";

interface TooltipWrapperProps {
  text?: string | null;
  children: ReactNode;
  as?: "span" | "div";
  className?: string;
}

export default function TooltipWrapper({
  text,
  children,
  as = "span",
  className,
}: TooltipWrapperProps) {
  const wrapperRef = useRef<HTMLElement | null>(null);
  const [isHovered, setIsHovered] = useState(false);
  const [tooltipAnchor, setTooltipAnchor] = useState<{ left: number; top: number } | null>(null);

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
      }}
    >
      {children}
      {isHovered && tooltipAnchor
        ? createPortal(
            <span
              className="rule-tooltip rule-tooltip--floating"
              style={{
                left: `${tooltipAnchor.left}px`,
                top: `${tooltipAnchor.top}px`,
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
