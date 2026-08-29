/** 后端访问层：类型化错误，禁止静默兜底（spec §7）。 */

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:23480";
export const AGENTS_URL = process.env.NEXT_PUBLIC_AGENTS_URL ?? "http://127.0.0.1:23481";

interface ErrorBody {
  error?: { code?: string; message?: string };
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    cache: "no-store",
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as ErrorBody | null;
    throw new ApiError(
      response.status,
      body?.error?.code ?? "unknown",
      body?.error?.message ?? `请求失败: ${response.status}`,
    );
  }
  return (await response.json()) as T;
}
