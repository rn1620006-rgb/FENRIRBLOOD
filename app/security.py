import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError

password_hasher = PasswordHasher(time_cost=2, memory_cost=32768, parallelism=2)


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def future(days=0, minutes=0):
    return (datetime.now(timezone.utc) + timedelta(days=days, minutes=minutes)).isoformat(timespec="seconds")


def uid():
    return str(uuid.uuid4())


def token():
    return secrets.token_urlsafe(32)


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def hash_password(password):
    return password_hasher.hash(password)


def check_password(stored, password):
    try:
        return password_hasher.verify(stored, password)
    except (VerifyMismatchError, VerificationError):
        return False


def week_start():
    lisbon = datetime.now(ZoneInfo("Europe/Lisbon"))
    return (lisbon.date() - timedelta(days=lisbon.weekday())).isoformat()


def secure_equal(a,b):
    return hmac.compare_digest(a, b)
