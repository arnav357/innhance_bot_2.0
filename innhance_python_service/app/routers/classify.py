"""Intent classification router."""
from fastapi import APIRouter
from app.models.schemas import ClassifyRequest, ClassifyResponse
from app.services.classifier import classify_intent

router = APIRouter(prefix="/classify", tags=["classify"])

@router.post("", response_model=ClassifyResponse)
async def classify(req: ClassifyRequest):
    return await classify_intent(req)
