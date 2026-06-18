"""Payment screenshot verification router."""
from fastapi import APIRouter
from app.models.schemas import VerifyPaymentRequest, VerifyPaymentResponse
from app.services.payment import verify_payment

router = APIRouter(prefix="/verify-payment", tags=["payment"])

@router.post("", response_model=VerifyPaymentResponse)
async def verify(req: VerifyPaymentRequest):
    return await verify_payment(req)
