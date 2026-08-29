export default function Loading() {
  return (
    <div className="flex h-full items-center justify-center gap-2 py-24 text-sm text-ink-faint">
      <span className="size-4 animate-spin rounded-full border-2 border-line-strong border-t-accent" />
      加载中…
    </div>
  );
}
