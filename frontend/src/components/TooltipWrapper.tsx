import type { ReactNode } from "react";

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
  if (!text || text.trim().length === 0) {
    return <>{children}</>;
  }

  const Tag = as;
  const wrapperClassName = ["rule-badge-wrapper", className].filter(Boolean).join(" ");

  return (
    <Tag className={wrapperClassName}>
      {children}
      <span className="rule-tooltip">{text}</span>
    </Tag>
  );
}
