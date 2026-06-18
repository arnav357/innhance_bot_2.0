"""Language detection router. Owner: Ridhimaa."""
from fastapi import APIRouter
from app.models.schemas import DetectLanguageRequest, DetectLanguageResponse
from app.services.language import detect_language

router = APIRouter(prefix="/detect-language", tags=["language"])

@router.post("", response_model=DetectLanguageResponse)
async def detect(req: DetectLanguageRequest):
    result = detect_language(req.text)
    return DetectLanguageResponse(**result)
