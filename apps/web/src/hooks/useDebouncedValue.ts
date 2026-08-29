"use client";

import { useEffect, useState } from "react";

/** 输入防抖：300ms 内无新输入才放行（ TanStack Query 社区标准模式，见 search/前端性能优化调研.md）。 */
export function useDebouncedValue<T>(value: T, delayMs = 300): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);
  return debounced;
}
