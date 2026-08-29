/** api 服务同源代理（node:http 版，与 agents 代理同构）。

  弃用 next.config rewrites 的原因：长 POST（备课 95s/采集 120s+）经 rewrites 的
  undici fetch 会在 ~30s 被 ECONNRESET（web.err.log 实锤，短请求无事）；
  node:http + keepAlive:false 的代理在 SSE 40s+ 场景已验证稳定（续二/续七）。
*/

import http from "node:http";
import { Readable } from "node:stream";

const target = process.env.API_PROXY_TARGET ?? "http://127.0.0.1:23480";
const agent = new http.Agent({ keepAlive: false, maxSockets: 32 });

function proxy(req: Request): Promise<Response> {
  const url = new URL(req.url);
  // 本路由挂在 /api/[...path]，pathname 本就是上游需要的 /api/... 原样路径
  const upstreamPath = url.pathname + url.search;

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
        const body = new ReadableStream<Uint8Array>({
          start(controller) {
            upstreamRes.on("data", (chunk: Buffer) => controller.enqueue(new Uint8Array(chunk)));
            upstreamRes.on("end", () => controller.close());
            upstreamRes.on("error", (error) => controller.error(error));
          },
          cancel() {
            upstreamRes.destroy();
          },
        });
        resolve(new Response(body, { status: upstreamRes.statusCode ?? 502, headers: responseHeaders }));
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

export { proxy as GET, proxy as POST, proxy as PUT, proxy as DELETE, proxy as PATCH };
