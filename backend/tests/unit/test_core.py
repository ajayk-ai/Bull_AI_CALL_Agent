import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core import phone
from app.core.config import get_settings
from app.core.errors import Forbidden, Unauthorized, ValidationFailed
from app.core.security import create_token, decode_token, decrypt, encrypt, hash_password, verify_password
from app.models.enums import Role
from app.models.org import User
from app.rbac.permissions import ROLE_PERMISSIONS, Permission, resolve_department, visible_departments

# ---- phone numbers ----


@pytest.mark.parametrize("raw", ["9876543210", "+91 98765 43210", "098765-43210", "+919876543210", " 91 9876543210 "])
def test_indian_formats_normalise_to_one_e164(raw):
    assert phone.to_e164(raw) == "+919876543210"


@pytest.mark.parametrize("raw", ["12345", "abcdefghij", "+91 00000 00000", "+91 5555", ""])
def test_invalid_numbers_rejected(raw):
    with pytest.raises(phone.InvalidPhoneNumber):
        phone.to_e164(raw)


def test_foreign_number_keeps_its_country_code():
    assert phone.to_e164("+44 20 7946 0958") == "+442079460958"
    assert phone.mask("+442079460958") == "+44******0958"


def test_mask_hides_all_but_last_four():
    assert phone.mask("+919876543210") == "+91******3210"


def test_hash_is_keyed_and_stable():
    first = phone.normalise("9876543210")
    second = phone.normalise("+91 98765 43210")
    assert first.hash == second.hash
    assert first.e164 not in first.hash and len(first.hash) == 64
    assert first.encrypted != second.encrypted  # Fernet uses a random IV
    assert decrypt(first.encrypted) == "+919876543210"


# ---- passwords, tokens, encryption ----


def test_password_hash_round_trip():
    hashed = hash_password("correct horse battery")
    assert verify_password("correct horse battery", hashed)
    assert not verify_password("wrong", hashed)
    assert not verify_password("anything", "not-a-hash")


def test_token_round_trip_and_type_check():
    user_id = uuid.uuid4()
    access = create_token(user_id, 3, "access")
    payload = decode_token(access, "access")
    assert payload["sub"] == str(user_id) and payload["ver"] == 3
    with pytest.raises(Unauthorized):
        decode_token(access, "refresh")


def test_expired_and_tampered_tokens_rejected():
    settings = get_settings()
    past = datetime.now(UTC) - timedelta(minutes=5)
    expired = jwt.encode(
        {"sub": str(uuid.uuid4()), "ver": 0, "typ": "access", "exp": past},
        settings.jwt_secret.get_secret_value(),
        algorithm="HS256",
    )
    with pytest.raises(Unauthorized, match="expired"):
        decode_token(expired, "access")
    forged = jwt.encode(
        {"sub": "x", "ver": 0, "typ": "access", "exp": datetime.now(UTC) + timedelta(hours=1)},
        "some-other-secret-that-is-long-enough!!",
        algorithm="HS256",
    )
    with pytest.raises(Unauthorized):
        decode_token(forged, "access")


def test_encryption_round_trip():
    assert decrypt(encrypt("secret value")) == "secret value"
    with pytest.raises(ValueError):
        decrypt("garbage")


# ---- RBAC ----


def test_roles_are_strictly_nested():
    operator, manager, hod, admin = (
        ROLE_PERMISSIONS[r] for r in (Role.OPERATOR, Role.CAMPAIGN_MANAGER, Role.HOD, Role.ADMIN)
    )
    assert operator < manager < hod < admin
    assert admin == frozenset(Permission)


def test_sensitive_permissions():
    assert Permission.CONTACTS_VIEW_FULL_NUMBER not in ROLE_PERMISSIONS[Role.CAMPAIGN_MANAGER]
    assert Permission.DNC_DELETE not in ROLE_PERMISSIONS[Role.OPERATOR]
    assert Permission.DNC_GLOBAL not in ROLE_PERMISSIONS[Role.HOD]
    assert Permission.DEPARTMENTS_MANAGE not in ROLE_PERMISSIONS[Role.HOD]


def test_resolve_department():
    own, other = uuid.uuid4(), uuid.uuid4()
    operator = User(role=Role.OPERATOR, department_id=own)
    admin = User(role=Role.ADMIN, department_id=None)
    assert resolve_department(operator, None) == own
    assert resolve_department(operator, own) == own
    with pytest.raises(Forbidden):
        resolve_department(operator, other)
    assert resolve_department(admin, other) == other
    with pytest.raises(ValidationFailed):
        resolve_department(admin, None)
    assert visible_departments(admin) is None
    assert visible_departments(operator) == [own]
