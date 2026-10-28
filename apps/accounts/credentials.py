"""Create logins for school people and hand the password over once."""

import re
import secrets

from django.conf import settings
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.fees.services import whatsapp_link, whatsapp_number

SESSION_KEY = "new_login_credentials"
# No 0/o, 1/l/i so the password is easy to read out over the phone.
PASSWORD_CHARS = "abcdefghjkmnpqrstuvwxyz23456789"


def new_password():
    return "".join(secrets.choice(PASSWORD_CHARS) for _ in range(8))


def phone_username(phone):
    """0300-1234567 / +92 300 1234567 -> 03001234567, or "" when not a phone number."""
    digits = whatsapp_number(phone)
    return f"0{digits[2:]}" if digits.startswith("92") else digits


def unique_username(*candidates):
    """The first candidate nobody uses yet, else the first one with a number added."""
    User = get_user_model()
    cleaned = [re.sub(r"[^\w.@+-]", "", c.strip().lower()) for c in candidates if c and c.strip()]
    cleaned = [c for c in cleaned if c] or ["user"]
    for candidate in cleaned:
        if not User.objects.filter(username=candidate).exists():
            return candidate
    number = 2
    while User.objects.filter(username=f"{cleaned[0]}{number}").exists():
        number += 1
    return f"{cleaned[0]}{number}"


def remember_credentials(request, *, user, password, label, send_to=""):
    """Keep the new password in the session so the next page can show it once."""
    login_url = request.build_absolute_uri(reverse("login"))
    message = (
        f"Assalam-o-Alaikum, your {settings.SCHOOL_NAME} login for {label}:\n"
        f"Username: {user.username}\nPassword: {password}\n{login_url}"
    )
    phone = whatsapp_number(send_to)
    request.session[SESSION_KEY] = {
        "label": label,
        "username": user.username,
        "password": password,
        "whatsapp": whatsapp_link(phone, message) if phone else "",
    }


def pop_credentials(request):
    return request.session.pop(SESSION_KEY, None)
