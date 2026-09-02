import io
import json
import wave
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import ValidationError

from getoffer.api.routers.voice import TTSRequest
from getoffer.config import TTSProviderConfig
from getoffer.errors import NotConfigured
from getoffer.voice.gateway import VoiceGateway, pcm16_mono_to_wav


def test_pcm16_is_wrapped_as_browser_playable_mono_wav() -> None:
    pcm = b"\x01\x00\x02\x00\x03\x00"
    payload = pcm16_mono_to_wav(pcm, 22050)

    with wave.open(io.BytesIO(payload), "rb") as audio:
        assert audio.getnchannels() == 1
        assert audio.getsampwidth() == 2
        assert audio.getframerate() == 22050
        assert audio.readframes(3) == pcm


def test_tts_request_rejects_blank_text_and_config_rejects_invalid_sample_rate() -> None:
    with pytest.raises(ValidationError, match="朗读文本不能为空"):
        TTSRequest(text="   ")
    with pytest.raises(ValidationError):
        TTSProviderConfig(sample_rate=1000)


async def test_disabled_provider_is_explicit_and_does_not_expose_secrets() -> None:
    gateway = VoiceGateway(TTSProviderConfig(api_key="must-not-leak"))

    assert gateway.capabilities() == {
        "configured": False,
        "provider": "disabled",
        "voice": None,
        "quality": "browser",
    }
    with pytest.raises(NotConfigured, match="浏览器系统语音"):
        await gateway.synthesize("你好")


async def test_openai_compatible_contract_and_octet_stream_media_type_mapping() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/audio/speech"
        assert request.headers["authorization"] == "Bearer synthetic-secret"
        assert json.loads(request.content) == {
            "model": "synthetic-tts",
            "voice": "interviewer-zh",
            "input": "请介绍你的项目。",
            "response_format": "mp3",
        }
        return httpx.Response(
            200,
            content=b"synthetic-mp3",
            headers={"content-type": "application/octet-stream"},
        )

    gateway = VoiceGateway(
        TTSProviderConfig(
            provider="openai_compatible",
            base_url="https://voice.invalid/v1",
            api_key="synthetic-secret",
            model="synthetic-tts",
            voice="interviewer-zh",
        ),
        transport=httpx.MockTransport(handler),
    )
    try:
        audio = await gateway.synthesize("请介绍你的项目。")
    finally:
        await gateway.aclose()

    assert audio.content == b"synthetic-mp3"
    assert audio.media_type == "audio/mpeg"
    assert audio.provider == "openai_compatible"


async def test_cosyvoice_contract_wraps_official_raw_pcm_response() -> None:
    pcm = b"\x10\x00\x20\x00"

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/inference_sft"
        assert parse_qs(request.content.decode()) == {
            "tts_text": ["请继续说明。"],
            "spk_id": ["中文女"],
        }
        return httpx.Response(200, content=pcm)

    gateway = VoiceGateway(
        TTSProviderConfig(
            provider="cosyvoice",
            base_url="http://voice.invalid",
            voice="中文女",
            sample_rate=24000,
        ),
        transport=httpx.MockTransport(handler),
    )
    try:
        audio = await gateway.synthesize("请继续说明。")
    finally:
        await gateway.aclose()

    assert audio.media_type == "audio/wav"
    with wave.open(io.BytesIO(audio.content), "rb") as decoded:
        assert decoded.getframerate() == 24000
        assert decoded.readframes(2) == pcm
