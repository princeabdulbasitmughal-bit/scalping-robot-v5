"""
email_alert.py - Email Alert System for Gold Scalping Robot
Uses smtplib (built-in) - no external dependencies required.
"""
import smtplib
import json
import os
import logging
import threading
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone
from typing import Optional, Callable, Dict, Any

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
    def __init__(self, config_file: Optional[str] = None, smtp_factory: Optional[Callable] = None):
        self._config_file = str(config_file) if config_file else EMAIL_CONFIG_FILE
        self._smtp_factory = smtp_factory
        self._lock = threading.RLock()
        self.config = self._load_config()

    def _load_config(self):
        """Load email config, create template if missing."""
        try:
            if os.path.exists(self._config_file):
                with open(self._config_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            else:
                # Create template
                dir_path = os.path.dirname(self._config_file)
                if dir_path and not os.path.exists(dir_path):
                    os.makedirs(dir_path, exist_ok=True)
                with open(self._config_file, 'w', encoding='utf-8') as f:
                    json.dump(DEFAULT_CONFIG, f, indent=2)
                email_log.info(f"Created {self._config_file} template - configure to enable alerts")
                return DEFAULT_CONFIG.copy()
        except Exception as e:
            logger.error("EmailAlerter: config load error: %s", e)
            return DEFAULT_CONFIG.copy()

    def _reload_config(self):
        """Reload config in case it was updated."""
        with self._lock:
            self.config = self._load_config()

    def update_config(self, new_cfg: dict, persist: bool = False):
        """Update active configuration in a thread-safe manner."""
        with self._lock:
            if isinstance(new_cfg, dict):
                self.config.update(new_cfg)
                if persist:
                    try:
                        tmp = self._config_file + ".tmp"
                        with open(tmp, "w", encoding="utf-8") as f:
                            json.dump(self.config, f, indent=2)
                        os.replace(tmp, self._config_file)
                    except Exception as e:
                        logger.error(f"Email config persist error: {e}")

    def _make_smtp(self, smtp_host, smtp_port, timeout=15):
        """Create SMTP connection — uses SMTP_SSL for port 465, STARTTLS for others."""
        if self._smtp_factory is not None:
            return self._smtp_factory(smtp_host, smtp_port, timeout=timeout)
        if int(smtp_port) == 465:
            server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=timeout)
            server.ehlo()
        else:
            server = smtplib.SMTP(smtp_host, smtp_port, timeout=timeout)
            server.ehlo()
            server.starttls()
        return server

    def send_alert(self, subject, body):
        """Send email alert. Returns True on success, False on failure."""
        self._reload_config()
        with self._lock:
            cfg = dict(self.config)

        if not cfg.get('enabled', False):
            return False
        from_email = cfg.get('from_email', '')
        password = cfg.get('password', '')
        to_email = cfg.get('to_email', '')
        if not all([from_email, password, to_email]):
            email_log.warning("Email not configured - skipping alert: %s", subject)
            return False
        try:
            msg = MIMEMultipart()
            msg['From'] = from_email
            msg['To'] = to_email
            msg['Subject'] = '[GoldBot] ' + subject
            timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
            full_body = body + '\n\n---\nGold Scalping Robot | ' + timestamp
            msg.attach(MIMEText(full_body, 'plain'))
            smtp_host = cfg.get('smtp_host', 'smtp.gmail.com')
            smtp_port = cfg.get('smtp_port', 587)
            with self._make_smtp(smtp_host, smtp_port, timeout=15) as server:
                server.login(from_email, password)
                server.send_message(msg)
            email_log.info("Alert sent: %s -> %s", subject, to_email)
            return True
        except Exception as e:
            email_log.error("send_alert failed: %s - Error: %s", subject, e)
            return False

    def test_connection(self):
        """Test SMTP connection including authentication. Returns True if successful."""
        self._reload_config()
        with self._lock:
            cfg = dict(self.config)
        try:
            smtp_host = cfg.get('smtp_host', 'smtp.gmail.com')
            smtp_port = cfg.get('smtp_port', 587)
            from_email = cfg.get('from_email', '')
            password = cfg.get('password', '')
            with self._make_smtp(smtp_host, smtp_port, timeout=10) as server:
                if from_email and password:
                    server.login(from_email, password)
            email_log.info("SMTP connection test PASSED: %s:%s", smtp_host, smtp_port)
            return True
        except Exception as e:
            email_log.warning("SMTP connection test FAILED: %s", e)
            return False


# Singleton
_alerter = EmailAlerter()


def get_alerter():
    return _alerter
