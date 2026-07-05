from pydantic import BaseModel, EmailStr, Field

from app.contact.models import ContactReason


class ContactMessageIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    email: EmailStr
    organisation: str | None = Field(default=None, max_length=200)
    reason: ContactReason = ContactReason.other
    subject: str = Field(default="", max_length=300)
    message: str = Field(min_length=10, max_length=5000)


class ContactMessageOut(BaseModel):
    ok: bool
