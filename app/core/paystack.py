"""
Paystack client — wraps the Transfers and Verification APIs.

Configuration (.env):
    PAYSTACK_SECRET_KEY=sk_test_...    ← change to sk_live_... when company account is ready
    PAYSTACK_WEBHOOK_SECRET=...        ← from Paystack dashboard → Settings → Webhooks
    PAYSTACK_ENABLED=true

Amounts: Paystack expects kobo (₦1 = 100 kobo). Conversion is handled internally.

To switch from the Reymage personal account to the company account:
  1. Set PAYSTACK_SECRET_KEY to the company secret key.
  2. Set PAYSTACK_WEBHOOK_SECRET to the new webhook secret.
  3. Restart the API. No code changes needed.
"""
import hashlib
import hmac
import logging
from decimal import Decimal

import httpx

logger = logging.getLogger(__name__)

PAYSTACK_BASE = "https://api.paystack.co"

# Fallback static bank list when Paystack is not enabled.
STATIC_BANKS = [
    {"code": "044", "name": "Access Bank"},
    {"code": "023", "name": "Citibank Nigeria"},
    {"code": "050", "name": "EcoBank Nigeria"},
    {"code": "070", "name": "Fidelity Bank"},
    {"code": "011", "name": "First Bank of Nigeria"},
    {"code": "214", "name": "First City Monument Bank"},
    {"code": "058", "name": "Guaranty Trust Bank"},
    {"code": "030", "name": "Heritage Bank"},
    {"code": "301", "name": "Jaiz Bank"},
    {"code": "082", "name": "Keystone Bank"},
    {"code": "526", "name": "Moniepoint MFB"},
    {"code": "090", "name": "Optimus Bank"},
    {"code": "076", "name": "Polaris Bank"},
    {"code": "101", "name": "Providus Bank"},
    {"code": "221", "name": "Stanbic IBTC Bank"},
    {"code": "068", "name": "Standard Chartered Bank"},
    {"code": "232", "name": "Sterling Bank"},
    {"code": "033", "name": "United Bank for Africa"},
    {"code": "032", "name": "Union Bank of Nigeria"},
    {"code": "035", "name": "Wema Bank"},
    {"code": "057", "name": "Zenith Bank"},
    {"code": "999992", "name": "OPay"},
    {"code": "999991", "name": "PalmPay"},
    {"code": "999993", "name": "Kuda MFB"},
]


def _headers() -> dict:
    from app.config import settings
    return {
        "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json",
    }


async def get_banks() -> list[dict]:
    """
    Returns list of {code, name} dicts.
    Falls back to STATIC_BANKS if Paystack is not enabled or call fails.
    """
    from app.config import settings
    if not settings.paystack_live:
        return STATIC_BANKS
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{PAYSTACK_BASE}/bank",
                params={"currency": "NGN", "per_page": 200},
                headers=_headers(),
            )
            resp.raise_for_status()
        return [{"code": b["code"], "name": b["name"]} for b in resp.json().get("data", [])]
    except Exception as exc:
        logger.warning("paystack get_banks failed, using static list: %s", exc)
        return STATIC_BANKS


async def resolve_account(account_number: str, bank_code: str) -> str:
    """
    Resolves an account via Paystack's account number verification API.
    Returns the verified account name or raises ValueError if not found.
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{PAYSTACK_BASE}/bank/resolve",
            params={"account_number": account_number, "bank_code": bank_code},
            headers=_headers(),
        )
    body = resp.json()
    if resp.status_code == 422 or not body.get("status"):
        msg = body.get("message", "Could not verify account")
        raise ValueError(f"Account verification failed: {msg}")
    resp.raise_for_status()
    return body["data"]["account_name"]


async def create_transfer_recipient(
    account_name: str, account_number: str, bank_code: str, bank_name: str
) -> str:
    """Creates a Paystack transfer recipient. Returns the recipient_code."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{PAYSTACK_BASE}/transferrecipient",
            json={
                "type": "nuban",
                "name": account_name,
                "account_number": account_number,
                "bank_code": bank_code,
                "currency": "NGN",
                "description": f"PTD contributor — {bank_name}",
            },
            headers=_headers(),
        )
        resp.raise_for_status()
    return resp.json()["data"]["recipient_code"]


async def initiate_transfer(
    amount_naira: Decimal,
    recipient_code: str,
    reason: str,
    reference: str,
) -> str:
    """
    Initiates a Paystack transfer. Returns the transfer_code (e.g. TRF_xxx).
    Amount is in naira — converted to kobo internally.
    """
    amount_kobo = int(amount_naira * 100)
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{PAYSTACK_BASE}/transfer",
            json={
                "source": "balance",
                "amount": amount_kobo,
                "recipient": recipient_code,
                "reason": reason,
                "reference": reference,
            },
            headers=_headers(),
        )
        resp.raise_for_status()
    return resp.json()["data"]["transfer_code"]


def verify_webhook_signature(raw_body: bytes, signature: str) -> bool:
    """Verifies a Paystack webhook request using HMAC-SHA512."""
    from app.config import settings
    if not settings.PAYSTACK_WEBHOOK_SECRET:
        return False
    expected = hmac.new(
        settings.PAYSTACK_WEBHOOK_SECRET.encode(),
        raw_body,
        hashlib.sha512,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
