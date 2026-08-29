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
        // 逐块转发（SSE 的生命线）：thinking/text 增量必须实时到达浏览器，
        // 不能整包缓冲——否则 max 思考的 40s 里用户面对空气泡，计时也会归零。
        // new Uint8Array(chunk) 显式拷贝：Buffer 是池化 ArrayBuffer 的视图，不能直接引用。
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

export { proxy as GET, proxy as POST };
