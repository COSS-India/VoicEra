"use client";

import { ReactNode, useState } from "react";
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { LogoMark } from "@/components/ui/VoicEraMark";

export interface NavItem {
  key: string;
  label: string;
  icon?: ReactNode;
  active?: boolean;
  onClick?: () => void;
  accent?: boolean;
  /** Right-aligned mono count badge, e.g. the live-agent count on "Agents". */
  count?: number;
  /** Walkthrough target id — set as `data-tour="<tourId>"` so the sidebar tour can spotlight this item. */
  tourId?: string;
}

export interface NavGroup {
  label: string;
  items: NavItem[];
}

interface NavRailProps {
  groups?: NavGroup[];
  footer?: ReactNode;
  onBrandClick?: () => void;
  expanded: boolean;
  onToggleExpanded: () => void;
}

export function NavRail({
  groups = [],
  footer,
  onBrandClick,
  expanded,
  onToggleExpanded,
}: NavRailProps) {
  return (
    <nav
      data-tour="sidebar-rail"
      className={`flex h-full flex-col gap-4 border-r border-v-line bg-v-panel px-4 py-[22px] transition-[width] duration-200 ${
        expanded ? "w-[236px]" : "w-16"
      }`}
    >
      <div className="flex items-center gap-1 px-1">
        <button
          type="button"
          onClick={onBrandClick}
          className="flex min-w-0 flex-1 cursor-pointer items-center gap-2.5 text-v-fg"
          title="VoicEra"
        >
          <LogoMark size={26} />
          {expanded ? (
            <span className="truncate text-[17px] font-extrabold tracking-[-.3px] text-v-fg">VoicEra</span>
          ) : null}
        </button>
        {expanded ? (
          <button
            type="button"
            onClick={onToggleExpanded}
            aria-label="Collapse sidebar"
            title="Collapse sidebar"
            className="flex size-7 shrink-0 cursor-pointer items-center justify-center rounded-v-md text-v-muted transition-colors duration-[120ms] hover:bg-v-soft hover:text-v-fg"
          >
            <PanelLeftClose className="size-4" strokeWidth={1.8} />
          </button>
        ) : null}
      </div>

      {!expanded ? (
        <button
          type="button"
          onClick={onToggleExpanded}
          aria-label="Expand sidebar"
          title="Expand sidebar"
          className="flex size-8 shrink-0 cursor-pointer items-center justify-center self-center rounded-v-md text-v-muted transition-colors duration-[120ms] hover:bg-v-soft hover:text-v-fg"
        >
          <PanelLeftOpen className="size-4" strokeWidth={1.8} />
        </button>
      ) : null}

      <div className="flex flex-1 flex-col gap-3 overflow-y-auto overflow-x-hidden">
        {groups.map((group) => (
          <div key={group.label} className="flex flex-col gap-1">
            {expanded ? (
              <span className="px-[11px] pb-2 font-mono text-[10px] font-semibold tracking-[.14em] uppercase text-v-dim">
                {group.label}
              </span>
            ) : null}
            {group.items.map((item) => {
              const isActive = item.active ?? false;
              return (
                <button
                  key={item.key}
                  data-tour={item.tourId}
                  onClick={item.onClick}
                  title={item.label}
                  className={`flex cursor-pointer items-center gap-[11px] rounded-v-md px-[11px] py-[9px] text-left text-[13.5px] font-medium transition-colors duration-[120ms] ${
                    isActive
                      ? "bg-v-pale font-semibold text-v-accent"
                      : item.accent
                        ? "text-v-accent hover:bg-v-soft"
                        : "text-v-body hover:bg-v-soft hover:text-v-fg"
                  }`}
                >
                  <span className="flex size-[17px] shrink-0 items-center justify-center [&>svg]:size-[17px]">
                    {item.icon}
                  </span>
                  {expanded ? <span className="min-w-0 flex-1 truncate">{item.label}</span> : null}
                  {expanded && item.count !== undefined ? (
                    <span className="shrink-0 font-mono text-[11px] font-semibold text-v-dim">{item.count}</span>
                  ) : null}
                </button>
              );
            })}
          </div>
        ))}
      </div>

      {footer ? <div className="flex flex-col gap-2 border-t border-v-line pt-3">{footer}</div> : null}
    </nav>
  );
}

/** Self-contained demo for the component gallery — manages its own expand/collapse state. */
export function NavRailDemo() {
  const [expanded, setExpanded] = useState(true);
  return (
    <NavRail
      expanded={expanded}
      onToggleExpanded={() => setExpanded((v) => !v)}
      groups={[
        {
          label: "Build",
          items: [
            { key: "agents", label: "Agents", active: true, count: 3 },
            { key: "integrations", label: "Integrations" },
          ],
        },
      ]}
    />
  );
}
