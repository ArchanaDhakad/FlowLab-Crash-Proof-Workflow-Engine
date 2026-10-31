"""Send workflow email steps through an SMTP server configured by environment."""

import os
import smtplib
import ssl
from email.headerregistry import Address
from email.message import EmailMessage


def send_email(recipient: str, subject: str, body: str) -> None:
    """Deliver one plain-text message; credentials are never stored in workflows."""
    host = os.environ.get("SMTP_HOST", "").strip()
    sender = os.environ.get("SMTP_FROM_EMAIL", "").strip()
    if not host or not sender:
        raise ValueError(
            "Email step needs SMTP_HOST and SMTP_FROM_EMAIL environment variables."
        )

    try:
        port = int(os.environ.get("SMTP_PORT", "587"))
    except ValueError as error:
        raise ValueError("SMTP_PORT must be a number between 1 and 65535.") from error
    if not 1 <= port <= 65535:
        raise ValueError("SMTP_PORT must be a number between 1 and 65535.")

    username = os.environ.get("SMTP_USERNAME", "")
    password = os.environ.get("SMTP_PASSWORD", "")
    if bool(username) != bool(password):
        raise ValueError("Set both SMTP_USERNAME and SMTP_PASSWORD, or neither.")

    use_ssl_value = os.environ.get("SMTP_USE_SSL", "false").strip().lower()
    if use_ssl_value not in {"true", "false", "1", "0", "yes", "no"}:
        raise ValueError("SMTP_USE_SSL must be true or false.")
    use_ssl = use_ssl_value in {"true", "1", "yes"}

    for label, address in (("recipient", recipient), ("sender", sender)):
        if "\r" in address or "\n" in address:
            raise ValueError(f"Email {label} must be a single email address.")
        try:
            Address(addr_spec=address)
        except ValueError as error:
            raise ValueError(f"Email {label} must be a valid email address.") from error
    if "\r" in subject or "\n" in subject:
        raise ValueError("Email subject cannot contain line breaks.")

    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)

    try:
        if use_ssl:
            with smtplib.SMTP_SSL(
                host, port, timeout=20, context=ssl.create_default_context()
            ) as server:
                if username:
                    server.login(username, password)
                server.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=20) as server:
                server.ehlo()
                server.starttls(context=ssl.create_default_context())
                server.ehlo()
                if username:
                    server.login(username, password)
                server.send_message(message)
    except (OSError, smtplib.SMTPException) as error:
        raise ValueError(
            f"Email delivery failed ({type(error).__name__}): {error}"
        ) from error
