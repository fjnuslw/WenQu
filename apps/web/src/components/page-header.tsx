import { cn } from "@/lib/utils";

/** 统一页头：标题 + 说明 + 右侧附加内容。 */
export function PageHeader({
  title,
  description,
  extra,
  className,
}: {
  title: string;
  description?: string;
  extra?: React.ReactNode;
  className?: string;
}) {
  return (
    <header className={cn("mb-6 flex items-end justify-between gap-4", className)}>
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-1 max-w-2xl text-sm leading-relaxed text-ink-dim">{description}</p>}
      </div>
      {extra && <div className="shrink-0">{extra}</div>}
    </header>
  );
}
