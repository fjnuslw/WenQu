/** agents 服务同源代理（node:http 版）。

  不用 next.config rewrites / undici fetch 代理的原因：SSE 流式响应结束后，
  keep-alive 连接被复用时上游会判为坏请求（400 空响应，且成功/失败交替出现）。
  这里用 http.Agent({ keepAlive: false }) 保证每次请求独立 socket、用完即毁，
  流式与普通请求一视同仁（spec 2026-08-29 续二）。
*/

import http from "node:http";
import { Readable } from "node:stream";

const target = process.env.AGENTS_PROXY_TARGET ?? "http://127.0.0.1:23481";
const agent = new http.Agent({ keepAlive: false, maxSockets: 32 });

function proxy(req: Request): Promise<Response> {
  const url = new URL(req.url);
  const upstreamPath = url.pathname.replace(/^\/agents/, "") + url.search;

  return new Promise<Response>((resolve, reject) => {
    const headers: Record<string, string | string[] | undefined> = {};
    req.headers.forEach((value, key) => {
      if (["host", "connection", "keep-alive", "transfer-encoding", "upgrade", "content-length"].includes(key)) {
        return; // 逐跳头不转发
      }
      headers[key] = value;
    });
    headers.connection = "close";

    const upstreamReq = http.request(
      `${target}${upstreamPath}`,
      { method: req.method, headers, agent },
      (upstreamRes) => {
        const responseHeaders = new Headers();
        for (const [key, value] of Object.entries(upstreamRes.headers)) {
          if (value === undefined) continue;
          responseHeaders.set(key, Array.isArray(value) ? value.join(", ") : value);
        }
        responseHeaders.set("connection", "close");
        const chunks: Uint8Array[] = [];
        upstreamRes.on("data", (chunk: Buffer) => chunks.push(new Uint8Array(chunk)));
        upstreamRes.on("end", () => {
          const body = Buffer.concat(chunks.map((c) => Buffer.from(c)));
          resolve(new Response(new Uint8Array(body), { status: upstreamRes.statusCode ?? 502, headers: responseHeaders }));
        });
        upstreamRes.on("error", (error) => reject(error));
      },
    );
    upstreamReq.on("error", (error) => reject(error));
    if (req.body) {
      Readable.fromWeb(req.body as Parameters<typeof Readable.fromWeb>[0]).pipe(upstreamReq);
    } else {
      upstreamReq.end();
    }
  });
}

export const dynamic = "force-dynamic";

export { proxy as GET, proxy as POST };
