/** 后端访问层：全部走同源代理（next.config.ts rewrites），无跨域、无系统代理干扰。 */

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

interface ErrorBody {
  error?: { code?: string; message?: string };
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
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

/** agents 服务同源前缀（Next rewrite → agents 服务根路径）。 */
export function agentsUrl(path: string): string {
  return `/agents${path}`;
}
