import { cn } from "@/lib/utils";

/** 厂商 logo（public/logos/{slug}.png），缺素材时首字占位。 */
export function CompanyLogo({
  name,
  logo,
  size = "md",
}: {
  name: string;
  logo: string | null;
  size?: "xs" | "sm" | "md";
}) {
  const box = size === "md" ? "size-14" : size === "sm" ? "size-5" : "size-4";
  if (logo) {
    return (
      <span className={cn("inline-block shrink-0 overflow-hidden rounded-md bg-white/95 p-0.5", box)}>
        <img src={logo} alt={name} className="size-full object-contain" />
      </span>
    );
  }
  return (
    <span
      className={cn(
        "grid shrink-0 place-items-center rounded-md bg-surface-2 text-sm font-semibold text-ink-dim",
        box,
      )}
    >
      {name.slice(0, 1)}
    </span>
  );
}
