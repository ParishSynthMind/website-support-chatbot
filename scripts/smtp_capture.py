"""A throwaway local SMTP server that prints every email it receives.
Handy for watching handover notifications without a real mail account.

    python scripts/smtp_capture.py            # listens on 127.0.0.1:8025
    NOTIFIER=smtp SMTP_HOST=127.0.0.1 SMTP_PORT=8025 SMTP_USE_TLS=false \\
      SMTP_FROM=bot@example.com SMTP_TO=support@example.com python -m app.main
"""
import sys
import time

from aiosmtpd.controller import Controller


class PrintHandler:
    async def handle_DATA(self, server, session, envelope):
        print(f"---------- email from {envelope.mail_from} to {', '.join(envelope.rcpt_tos)} ----------")
        print(envelope.content.decode("utf-8", "replace"))
        print("---------- end ----------", flush=True)
        return "250 OK"


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8025
    controller = Controller(PrintHandler(), hostname="127.0.0.1", port=port)
    controller.start()
    print(f"Capturing SMTP on 127.0.0.1:{port}", flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        controller.stop()
