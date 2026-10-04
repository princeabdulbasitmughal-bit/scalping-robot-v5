"""
email_alert.py - Email Alert System for Gold Scalping Robot
Uses smtplib (built-in) - no external dependencies required.
"""
import smtplib
import json
import os
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

logger = logging.getLogger(__name__)

EMAIL_CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'email_config.json')
EMAIL_LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'email.log')

# Setup email log
email_log = logging.getLogger('email_alert')
if not email_log.handlers:
    fh = logging.FileHandler(EMAIL_LOG_FILE, encoding='utf-8')
    fh.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    email_log.addHandler(fh)
    email_log.setLevel(logging.INFO)

DEFAULT_CONFIG = {
    'from_email': '',
    'password': '',
    'to_email': '',
    'enabled': False,
    'smtp_host': 'smtp.gmail.com',
    'smtp_port': 587
}


class EmailAlerter:
    def __init__(self):
        self.config = self._load_config()

    def _load_config(self):
        """Load email config, create template if missing."""
        try:
            if os.path.exists(EMAIL_CONFIG_FILE):
                with open(EMAIL_CONFIG_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            else:
                # Create template
                with open(EMAIL_CONFIG_FILE, 'w', encoding='utf-8') as f:
                    json.dump(DEFAULT_CONFIG, f, indent=2)
                email_log.info("Created email_config.json template - configure to enable alerts")
                return DEFAULT_CONFIG.copy()
        except Exception as e:
            logger.error("EmailAlerter: config load error: %s", e)
            return DEFAULT_CONFIG.copy()

    def _reload_config(self):
        """Reload config in case it was updated."""
        self.config = self._load_config()

    def send_alert(self, subject, body):
        """Send email alert. Returns True on success, False on failure."""
        self._reload_config()
        if not self.config.get('enabled', False):
            return False
        from_email = self.config.get('from_email', '')
        password = self.config.get('password', '')
        to_email = self.config.get('to_email', '')
        if not all([from_email, password, to_email]):
            email_log.warning("Email not configured - skipping alert: %s", subject)
            return False
        try:
            msg = MIMEMultipart()
            msg['From'] = from_email
            msg['To'] = to_email
            msg['Subject'] = '[GoldBot] ' + subject
            timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')
            full_body = body + '\n\n---\nGold Scalping Robot | ' + timestamp
            msg.attach(MIMEText(full_body, 'plain'))
            smtp_host = self.config.get('smtp_host', 'smtp.gmail.com')
            smtp_port = self.config.get('smtp_port', 587)
            with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
                server.ehlo()
                server.starttls()
                server.login(from_email, password)
                server.send_message(msg)
            email_log.info("Alert sent: %s -> %s", subject, to_email)
            return True
        except Exception as e:
            email_log.error("send_alert failed: %s - Error: %s", subject, e)
            return False

    def test_connection(self):
        """Test SMTP connection. Returns True if successful."""
        self._reload_config()
        try:
            smtp_host = self.config.get('smtp_host', 'smtp.gmail.com')
            smtp_port = self.config.get('smtp_port', 587)
            with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
                server.ehlo()
                server.starttls()
            email_log.info("SMTP connection test PASSED: %s:%s", smtp_host, smtp_port)
            return True
        except Exception as e:
            email_log.warning("SMTP connection test FAILED: %s", e)
            return False


# Singleton
_alerter = EmailAlerter()


def get_alerter():
    return _alerter
