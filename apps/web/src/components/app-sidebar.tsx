"use client";

import {
  Layers,
  LayoutDashboard,
  Newspaper,
  Swords,
  UserRoundSearch,
  MessagesSquare,
  Zap,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { href: "/dashboard", label: "工作台", icon: LayoutDashboard },
  { href: "/bank", label: "题库", icon: Layers },
  { href: "/experiences", label: "面经", icon: Newspaper },
  { href: "/interview", label: "模拟面试", icon: MessagesSquare },
  { href: "/grilling", label: "项目拷打", icon: Swords },
  { href: "/resume", label: "简历工作台", icon: UserRoundSearch },
] as const;

export function AppSidebar() {
  const pathname = usePathname();
  return (
    <aside className="flex w-56 shrink-0 flex-col border-r border-line bg-surface/80 backdrop-blur">
      <div className="flex h-14 items-center gap-2.5 border-b border-line px-4">
        <span className="brand-tile grid size-7 place-items-center rounded-lg text-xs font-bold text-white">
          问
        </span>
        <div className="leading-tight">
          <div className="text-sm font-semibold tracking-wide">问渠 WenQu</div>
          <div className="text-[10px] text-ink-faint">大模型求职备战 · spec v0.3</div>
        </div>
      </div>

      <nav className="flex-1 space-y-0.5 p-2.5">
        <div className="px-3 pb-1.5 pt-1 text-[10px] font-medium uppercase tracking-[0.14em] text-ink-faint">
          备战
        </div>
        {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
          const active = pathname === href || pathname.startsWith(`${href}/`);
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "relative flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors",
                active
                  ? "bg-accent-soft text-ink"
                  : "text-ink-dim hover:bg-surface-2 hover:text-ink",
              )}
            >
              {active && (
                <span className="absolute left-0 top-1/2 h-4 w-0.5 -translate-y-1/2 rounded-full bg-accent" />
              )}
              <Icon className={cn("size-4", active ? "text-accent" : "")} />
              {label}
            </Link>
          );
        })}
      </nav>

      <div className="border-t border-line px-4 py-3">
        <div className="flex items-center gap-2 text-[11px] text-ink-faint">
          <Zap className="size-3 text-accent" />
          <span>K1 知识冷启动进行中</span>
        </div>
      </div>
    </aside>
  );
}
