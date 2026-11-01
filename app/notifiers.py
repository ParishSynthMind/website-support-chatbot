"""Pluggable handover notifications. Pick one with NOTIFIER=console|smtp|slack.

Every notifier takes a lead dict and raises on failure. The lead is always
saved to SQLite before notify() runs, so a failed notification never loses it.
"""
import json
import smtplib
import sys
from email.message import EmailMessage


def format_lead(lead: dict, company: str) -> str:
    lines = [
        f"New {company} chat handover (lead #{lead['id']})",
        f"Name:     {lead['name']}",
        f"Email:    {lead['email']}",
        f"Reason:   {lead['reason']}",
        f"Question: {lead['question']}",
        "",
        "Conversation so far:",
    ]
    for turn in lead.get("transcript") or []:
        lines.append(f"  {turn.get('role', '?')}: {turn.get('text', '')}")
    if not lead.get("transcript"):
        lines.append("  (none)")
    return "\n".join(lines)


class ConsoleNotifier:
    """Prints the lead to stdout. The default, and handy for local demos."""

    def __init__(self, company: str, stream=None):
        self.company = company
        self.stream = stream or sys.stdout

    def notify(self, lead: dict) -> None:
        print("=" * 60, file=self.stream)
        print(format_lead(lead, self.company), file=self.stream)
        print("=" * 60, file=self.stream, flush=True)


class SMTPNotifier:
    """Emails the support inbox. Works with any SMTP server (Gmail app
    password, SendGrid, Mailgun, Postmark SMTP, a company relay...)."""

    def __init__(self, company: str, host: str, port: int, username: str, password: str,
                 use_tls: bool, sender: str, recipient: str, smtp_factory=smtplib.SMTP):
        if not (host and sender and recipient):
            raise ValueError("SMTP notifier needs SMTP_HOST, SMTP_FROM and SMTP_TO")
        self.company = company
        self.host, self.port = host, port
        self.username, self.password = username, password
        self.use_tls = use_tls
        self.sender, self.recipient = sender, recipient
        self.smtp_factory = smtp_factory

    def build_message(self, lead: dict) -> EmailMessage:
        msg = EmailMessage()
        msg["Subject"] = f"[{self.company} chat] Handover from {lead['name']}"
        msg["From"] = self.sender
        msg["To"] = self.recipient
        # Reply goes straight to the visitor, so support can just hit reply.
        msg["Reply-To"] = lead["email"]
        msg.set_content(format_lead(lead, self.company))
        return msg

    def notify(self, lead: dict) -> None:
        msg = self.build_message(lead)
        with self.smtp_factory(self.host, self.port, timeout=15) as smtp:
            if self.use_tls:
                smtp.starttls()
            if self.username:
                smtp.login(self.username, self.password)
            smtp.send_message(msg)


class SlackWebhookNotifier:
    """Stub. Builds the Slack incoming-webhook payload, but sending is not
    implemented yet, so selecting it fails loudly instead of dropping leads."""

    def __init__(self, company: str, webhook_url: str):
        self.company = company
        self.webhook_url = webhook_url

    def build_payload(self, lead: dict) -> dict:
        return {"text": format_lead(lead, self.company)}

    def notify(self, lead: dict) -> None:
        raise NotImplementedError(
            "Slack notifier is a stub: POST json.dumps(build_payload(lead)) to SLACK_WEBHOOK_URL to finish it. "
            f"Payload would be: {json.dumps(self.build_payload(lead))[:200]}"
        )


def make_notifier(settings):
    kind = settings.notifier
    if kind == "console":
        return ConsoleNotifier(settings.company_name)
    if kind == "smtp":
        return SMTPNotifier(
            settings.company_name, settings.smtp_host, settings.smtp_port, settings.smtp_username,
            settings.smtp_password, settings.smtp_use_tls, settings.smtp_from, settings.smtp_to,
        )
    if kind == "slack":
        return SlackWebhookNotifier(settings.company_name, settings.slack_webhook_url)
    raise ValueError(f"Unknown NOTIFIER '{kind}' (use console, smtp or slack)")
