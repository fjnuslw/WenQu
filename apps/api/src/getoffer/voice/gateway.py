"""TTS Provider gateway：密钥留在服务端，失败类型化且不跨 Provider 静默降级。"""

import io
import wave
from dataclasses import dataclass
from typing import Any

import httpx

from getoffer.config import TTSProviderConfig
from getoffer.errors import NotConfigured, UpstreamError


@dataclass(frozen=True, slots=True)
class VoiceAudio:
    content: bytes
    media_type: str
    provider: str
    voice: str


_FORMAT_MEDIA_TYPES = {
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "opus": "audio/ogg",
    "aac": "audio/aac",
    "flac": "audio/flac",
}


def pcm16_mono_to_wav(content: bytes, sample_rate: int) -> bytes:
    if sample_rate < 8000 or sample_rate > 192000:
        raise ValueError(f"不支持的采样率: {sample_rate}")
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(content)
    return output.getvalue()


class VoiceGateway:
    def __init__(
        self,
        config: TTSProviderConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._config = config
        self._client: httpx.AsyncClient | None = None
        if config.provider != "disabled" and config.base_url.strip():
            self._client = httpx.AsyncClient(
                base_url=config.base_url.rstrip("/"),
                timeout=httpx.Timeout(config.timeout_seconds),
                transport=transport,
            )

    def _missing_fields(self) -> list[str]:
        if self._config.provider == "disabled":
            return ["provider"]
        missing = []
        if not self._config.base_url.strip():
            missing.append("base_url")
        if not self._config.voice.strip():
            missing.append("voice")
        if self._config.provider == "openai_compatible" and not self._config.model.strip():
            missing.append("model")
        return missing

    @property
    def configured(self) -> bool:
        return not self._missing_fields()

    def capabilities(self) -> dict[str, Any]:
        return {
            "configured": self.configured,
            "provider": self._config.provider,
            "voice": self._config.voice if self.configured else None,
            "quality": "neural" if self.configured else "browser",
        }

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()

    async def synthesize(self, text: str) -> VoiceAudio:
        missing = self._missing_fields()
        if missing or self._client is None:
            raise NotConfigured(
                "高质量 TTS 未配置，当前应使用浏览器系统语音",
                details={"provider": self._config.provider, "missing": missing},
            )
        if self._config.provider == "openai_compatible":
            return await self._openai_compatible(text)
        if self._config.provider == "cosyvoice":
            return await self._cosyvoice(text)
        raise NotConfigured(f"未知 TTS Provider: {self._config.provider}")

    async def _request(self, path: str, **kwargs: Any) -> httpx.Response:
        assert self._client is not None
        try:
            response = await self._client.post(path, **kwargs)
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            raise UpstreamError(
                f"TTS 上游返回 {exc.response.status_code}",
                details={"provider": self._config.provider, "body": exc.response.text[:300]},
            ) from exc
        except httpx.HTTPError as exc:
            raise UpstreamError(
                f"TTS 上游不可达: {exc}", details={"provider": self._config.provider}
            ) from exc

    async def _openai_compatible(self, text: str) -> VoiceAudio:
        headers = (
            {"Authorization": f"Bearer {self._config.api_key}"}
            if self._config.api_key.strip()
            else None
        )
        response = await self._request(
            "/audio/speech",
            json={
                "model": self._config.model,
                "voice": self._config.voice,
                "input": text,
                "response_format": self._config.response_format,
            },
            headers=headers,
        )
        if not response.content:
            raise UpstreamError("TTS 上游返回空音频", details={"provider": self._config.provider})
        media_type = response.headers.get("content-type", "").split(";", 1)[0]
        if not media_type or media_type == "application/octet-stream":
            media_type = _FORMAT_MEDIA_TYPES[self._config.response_format]
        return VoiceAudio(
            content=response.content,
            media_type=media_type,
            provider=self._config.provider,
            voice=self._config.voice,
        )

    async def _cosyvoice(self, text: str) -> VoiceAudio:
        # 官方 FastAPI SFT 端点返回 mono int16 raw PCM；在网关包装成浏览器可播放 WAV。
        response = await self._request(
            "/inference_sft",
            data={"tts_text": text, "spk_id": self._config.voice},
        )
        if not response.content:
            raise UpstreamError("CosyVoice 返回空音频", details={"voice": self._config.voice})
        try:
            content = pcm16_mono_to_wav(response.content, self._config.sample_rate)
        except ValueError as exc:
            raise UpstreamError(str(exc), details={"provider": self._config.provider}) from exc
        return VoiceAudio(
            content=content,
            media_type="audio/wav",
            provider=self._config.provider,
            voice=self._config.voice,
        )
