import logging

from fastapi import APIRouter

from app.contact.models import ContactMessage, ContactReason
from app.contact.schemas import ContactMessageIn, ContactMessageOut
from app.core.email import email_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/contact", tags=["contact"])

# Where stakeholder messages land. Interim inbox — move to a dedicated
# Wire24 address once mailboxes are provisioned.
CONTACT_INBOX = "primetimesdaily@gmail.com"

REASON_LABELS: dict[ContactReason, str] = {
    ContactReason.advertising: "Advertise with us",
    ContactReason.business: "Do business with us",
    ContactReason.news_tip: "News tip / story idea",
    ContactReason.press: "Press & media inquiry",
    ContactReason.careers: "Careers",
    ContactReason.feedback: "Feedback / complaint",
    ContactReason.other: "Other",
}


@router.post("", response_model=ContactMessageOut, status_code=201)
async def submit_contact_message(body: ContactMessageIn):
    await ContactMessage.create(**body.model_dump())

    # Forward to the team inbox. Failures are logged, never surfaced — the
    # message is already persisted and readable from the database.
    try:
        await email_client.send_contact_message(
            to_email=CONTACT_INBOX,
            reason_label=REASON_LABELS.get(body.reason, "Other"),
            name=body.name,
            email=body.email,
            organisation=body.organisation,
            subject=body.subject,
            message=body.message,
        )
    except Exception:
        logger.exception("Failed to forward contact message to %s", CONTACT_INBOX)

    return {"ok": True}
