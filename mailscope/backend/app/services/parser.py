"""Email parsing for .eml and .msg files."""

from __future__ import annotations

import email
import email.policy
import json
import logging
from dataclasses import dataclass, field
from email.message import EmailMessage
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class Attachment:
    filename: str
    content_type: str
    size: int


@dataclass
class ParsedEmail:
    subject: str = ""
    sender: str = ""
    reply_to: str = ""
    return_path: str = ""
    to: str = ""
    date: str = ""
    message_id: str = ""
    authentication_results: str = ""
    received_chain: list[str] = field(default_factory=list)
    raw_headers: str = ""
    structured_headers: dict[str, list[str]] = field(default_factory=dict)
    body_text: str = ""
    body_html: str = ""
    attachments: list[Attachment] = field(default_factory=list)


def parse_eml(file_path: str) -> ParsedEmail:
    """Parse a .eml file using Python's email package."""
    raw_bytes = Path(file_path).read_bytes()
    msg: EmailMessage = email.message_from_bytes(raw_bytes, policy=email.policy.default)

    result = ParsedEmail()
    result.subject = str(msg.get("Subject", ""))
    result.sender = str(msg.get("From", ""))
    result.reply_to = str(msg.get("Reply-To", ""))
    result.return_path = str(msg.get("Return-Path", ""))
    result.to = str(msg.get("To", ""))
    result.date = str(msg.get("Date", ""))
    result.message_id = str(msg.get("Message-ID", ""))
    result.authentication_results = str(msg.get("Authentication-Results", ""))

    # Received chain
    result.received_chain = [str(v) for v in msg.get_all("Received", [])]

    # Raw + structured headers
    header_lines = []
    structured: dict[str, list[str]] = {}
    for key, value in msg.items():
        header_lines.append(f"{key}: {value}")
        structured.setdefault(key.lower(), []).append(str(value))
    result.raw_headers = "\n".join(header_lines)
    result.structured_headers = structured

    # Body extraction
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            cd = str(part.get("Content-Disposition", ""))
            if "attachment" in cd:
                payload = part.get_payload(decode=True)
                result.attachments.append(
                    Attachment(
                        filename=part.get_filename() or "unknown",
                        content_type=ct,
                        size=len(payload) if payload else 0,
                    )
                )
            elif ct == "text/plain" and not result.body_text:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    result.body_text = payload.decode(charset, errors="replace")
            elif ct == "text/html" and not result.body_html:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    result.body_html = payload.decode(charset, errors="replace")
    else:
        ct = msg.get_content_type()
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="replace")
            if ct == "text/html":
                result.body_html = text
            else:
                result.body_text = text

    return result


def parse_msg(file_path: str) -> ParsedEmail:
    """Parse a .msg file using python-oxmsg."""
    from oxmsg import Message

    msg = Message.load(file_path)
    result = ParsedEmail()
    result.subject = msg.subject or ""
    result.sender = msg.sender or ""
    result.to = msg.to or ""
    result.date = str(msg.sent_date) if msg.sent_date else ""
    result.message_id = getattr(msg, "message_id", "") or ""

    # Extract body
    if msg.body:
        result.body_text = msg.body
    if hasattr(msg, "html_body") and msg.html_body:
        result.body_html = msg.html_body

    # Transport headers if available
    headers_str = getattr(msg, "transport_message_headers", "") or ""
    if headers_str:
        result.raw_headers = headers_str
        # Parse transport headers
        parsed = email.message_from_string(headers_str, policy=email.policy.default)
        structured: dict[str, list[str]] = {}
        for key, value in parsed.items():
            structured.setdefault(key.lower(), []).append(str(value))
        result.structured_headers = structured
        result.reply_to = str(parsed.get("Reply-To", ""))
        result.return_path = str(parsed.get("Return-Path", ""))
        result.authentication_results = str(parsed.get("Authentication-Results", ""))
        result.received_chain = [str(v) for v in parsed.get_all("Received", [])]
        if not result.message_id:
            result.message_id = str(parsed.get("Message-ID", ""))

    # Attachments
    if hasattr(msg, "attachments"):
        for att in msg.attachments:
            name = getattr(att, "filename", None) or getattr(att, "display_name", "unknown")
            ct = getattr(att, "content_type", "application/octet-stream") or "application/octet-stream"
            data = getattr(att, "data", b"") or b""
            result.attachments.append(Attachment(filename=name, content_type=ct, size=len(data)))

    return result


def parse_email_file(file_path: str, extension: str) -> ParsedEmail:
    """Dispatch to correct parser based on extension."""
    if extension == ".eml":
        return parse_eml(file_path)
    elif extension == ".msg":
        return parse_msg(file_path)
    else:
        raise ValueError(f"Unsupported extension: {extension}")
