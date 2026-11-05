"""Phone number normalisation, keyed hashing and masking.

Numbers are stored encrypted. Look-ups and duplicate checks use an HMAC of the E.164 form, so the
database never needs the plain number to find a match.
"""

import hashlib
import hmac
import re
from dataclasses import dataclass

import phonenumbers

from app.core.config import get_settings
from app.core.security import encrypt


class InvalidPhoneNumber(ValueError):
    pass


@dataclass(frozen=True)
class NormalisedPhone:
    e164: str
    hash: str
    masked: str
    encrypted: str


def to_e164(raw: str, region: str | None = None) -> str:
    region = region or get_settings().default_phone_region
    text = raw.strip()
    try:
        parsed = phonenumbers.parse(text, region)
    except phonenumbers.NumberParseException:
        raise InvalidPhoneNumber(f"Not a phone number: {raw!r}")
    if not phonenumbers.is_valid_number(parsed):
        raise InvalidPhoneNumber(f"Not a valid phone number: {raw!r}")
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def phone_hash(e164: str) -> str:
    key = get_settings().phone_hash_key.get_secret_value().encode()
    return hmac.new(key, e164.encode(), hashlib.sha256).hexdigest()


def mask(e164: str) -> str:
    """+919876543210 -> +91******3210"""
    country_code = phonenumbers.parse(e164).country_code
    prefix = f"+{country_code}"
    return prefix + "*" * (len(e164) - len(prefix) - 4) + e164[-4:]


def normalise(raw: str, region: str | None = None) -> NormalisedPhone:
    e164 = to_e164(raw, region)
    return NormalisedPhone(e164=e164, hash=phone_hash(e164), masked=mask(e164), encrypted=encrypt(e164))


_NUMBER_IN_TEXT = re.compile(r"\+?\d[\d \-]{7,}\d")


def mask_numbers_in_text(text: str) -> str:
    """Masks anything that looks like a phone number (9+ digits), keeping the last four: for provider payloads
    and logs, which may carry the dialled number."""

    def _mask(match: re.Match) -> str:
        digits = re.sub(r"\D", "", match.group())
        if len(digits) < 9:
            return match.group()
        return "*" * (len(digits) - 4) + digits[-4:]

    return _NUMBER_IN_TEXT.sub(_mask, text)
