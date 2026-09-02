"""TTS 同源网关：浏览器不接触上游密钥或地址。"""

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field, field_validator

from getoffer.api.deps import get_voice_gateway
from getoffer.voice import VoiceGateway

router = APIRouter(prefix="/api/voice", tags=["voice"])


class TTSRequest(BaseModel):
    text: str = Field(min_length=1, max_length=700)

    @field_validator("text")
    @classmethod
    def text_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("朗读文本不能为空")
        return stripped


@router.get("/capabilities")
async def capabilities(gateway: VoiceGateway = Depends(get_voice_gateway)) -> dict:
    return gateway.capabilities()


@router.post("/tts")
async def synthesize(
    request: TTSRequest,
    gateway: VoiceGateway = Depends(get_voice_gateway),
) -> Response:
    audio = await gateway.synthesize(request.text)
    return Response(
        content=audio.content,
        media_type=audio.media_type,
        headers={
            "Cache-Control": "no-store",
            "X-Voice-Provider": audio.provider,
        },
    )
