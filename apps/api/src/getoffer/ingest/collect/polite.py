"""合规 HTTP 客户端：真实 UA + 每渠道最小间隔限速 + robots 门禁（spec §10）。

失败显式（spec §7）：网络错误、非 200、robots 拒绝、robots 不可判都是类型化异常，
不做"失败就跳过/降级"的静默兜底。robots 解析用标准库 urllib.robotparser，不自写规则解析。
"""

import asyncio
import time
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from getoffer.errors import ComplianceViolation, UpstreamError

# 真实浏览器 UA：低频访问且只抓公开页
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


class PoliteClient:
    def __init__(self, *, proxy: str = "", min_interval: float = 8.0) -> None:
        self._client = httpx.AsyncClient(
            proxy=proxy or None,
            headers={"User-Agent": USER_AGENT},
            timeout=httpx.Timeout(30.0),
            follow_redirects=True,
        )
        self._min_interval = min_interval
        self._last_request_monotonic = 0.0
        # host robots 缓存；None 表示该站无 robots.txt（默认允许）
        self._robots: dict[str, RobotFileParser | None] = {}

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _throttle(self) -> None:
        wait = self._min_interval - (time.monotonic() - self._last_request_monotonic)
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_request_monotonic = time.monotonic()

    async def _request_raw(self, url: str) -> httpx.Response:
        await self._throttle()
        try:
            return await self._client.get(url)
        except httpx.HTTPError as exc:
            raise UpstreamError(f"采集请求失败: {url}", details={"error": str(exc)}) from exc

    async def ensure_allowed(self, url: str) -> None:
        """robots 门禁：请求前判定；Disallow 抛 ComplianceViolation（我们的闸门，不是上游的）。"""
        parts = urlsplit(url)
        robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
        if robots_url not in self._robots:
            response = await self._request_raw(robots_url)
            if response.status_code == 404:
                self._robots[robots_url] = None  # 无 robots.txt：默认允许（RFC 9309）
            elif response.status_code != 200:
                # 无法确认合规性时拒绝采集，而不是默认放行
                raise UpstreamError(
                    f"无法获取 robots.txt（合规性不可判定，拒绝采集）: {robots_url}",
                    details={"status": response.status_code},
                )
            else:
                parser = RobotFileParser()
                parser.parse(response.text.splitlines())
                self._robots[robots_url] = parser
        parser = self._robots[robots_url]
        if parser is not None and not parser.can_fetch(USER_AGENT, url):
            raise ComplianceViolation(
                f"robots.txt 禁止采集该路径: {url}",
                details={"robots": robots_url},
            )

    async def get_raw(self, url: str) -> httpx.Response:
        """限速 + robots 门禁后的原始响应（状态码由渠道自行判定，如 Cloudflare 挑战识别）。"""
        await self.ensure_allowed(url)
        return await self._request_raw(url)

    async def get(self, url: str) -> httpx.Response:
        response = await self.get_raw(url)
        if response.status_code != 200:
            raise UpstreamError(
                f"采集源返回非 200: {url}",
                details={"status": response.status_code, "body_head": response.text[:200]},
            )
        return response
