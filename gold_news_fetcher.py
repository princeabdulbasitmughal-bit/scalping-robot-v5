"""
gold_news_fetcher.py - Gold/XAU News Awareness Module
Fetches news from free RSS feeds and flags high-impact events.
"""
import json
import os
import re
import time
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.request import urlopen, Request
from urllib.error import URLError

logging.basicConfig(
    filename=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'news.log'),
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)
logger = logging.getLogger(__name__)

NEWS_STATUS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'news_status.json')

HIGH_IMPACT_KEYWORDS = [
    'federal reserve', 'inflation', 'interest rate',
    'jobs', 'nfp', 'non-farm', 'fomc', 'cpi', 'gdp', 'war',
    'crisis', 'recession', 'unemployment', 'payroll', 'powell',
    'treasury', 'dollar', 'dxy', 'sanctions', 'conflict',
    # 'fed' is safe to include with whole-word \b boundary matching
    # (\bfed\b won't match 'forward', 'modified', 'unified', etc.)
    'fed',
]

# Compile keyword patterns as whole-word matches to avoid false positives
# e.g. '\bfed\b' won't match 'forward', '\bwar\b' won't match 'award'
_KW_PATTERNS = [
    re.compile(rf"\b{re.escape(kw)}\b", re.IGNORECASE) for kw in HIGH_IMPACT_KEYWORDS
]

# Feed list is ordered by priority; fetcher continues to next on failure.
# All feeds are on the finance.yahoo.com domain which is confirmed reachable.
# The Dow Jones / MarketWatch endpoint was confirmed dead (connection refused).
RSS_FEEDS = [
    # Primary: GC=F (Gold Futures) headlines — confirmed working
    'https://feeds.finance.yahoo.com/rss/2.0/headline?s=GC%3DF&region=US&lang=en-US',
    # Secondary: Yahoo Finance general news (broad macro/geopolitical coverage)
    'https://feeds.finance.yahoo.com/rss/2.0/headline?s=%5EGSPC&region=US&lang=en-US',
    # Tertiary: Yahoo Finance US Dollar Index (DXY) — relevant USD/gold correlation
    'https://feeds.finance.yahoo.com/rss/2.0/headline?s=DX%3DF&region=US&lang=en-US',
]

HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; GoldBot/1.0)'}


def fetch_rss(url, timeout=10):
    """Fetch RSS feed and return list of (title, pubDate) tuples."""
    try:
        req = Request(url, headers=HEADERS)
        with urlopen(req, timeout=timeout) as resp:
            content = resp.read()
        root = ET.fromstring(content)
        items = []
        for item in root.iter('item'):
            title = item.findtext('title', default='')
            pub_date = item.findtext('pubDate', default='')
            items.append((title.lower(), pub_date))
        return items
    except (URLError, ET.ParseError, Exception) as e:
        logger.warning("RSS fetch error for %s: %s", url, e)
        return None  # FIX: return None to signal failure (vs empty list = success with no items)


def check_high_impact(headlines):
    """Return True if any headline contains high-impact keywords (whole-word match)."""
    if not headlines or not isinstance(headlines, (list, tuple)):
        return False, ''
    for item in headlines:
        if not isinstance(item, (list, tuple)) or len(item) == 0:
            continue
        title = str(item[0]) if item[0] is not None else ""
        for pattern in _KW_PATTERNS:
            if pattern.search(title):
                logger.info("HIGH IMPACT KEYWORD FOUND: '%s' in '%s'", pattern.pattern, title[:80])
                return True, title
    return False, ''


def write_status(high_impact, headlines, avoid_trading, target_file=None):
    target = target_file or NEWS_STATUS_FILE
    head_list = []
    if headlines and isinstance(headlines, (list, tuple)):
        for h in headlines[:5]:
            if isinstance(h, (list, tuple)) and len(h) > 0 and h[0] is not None:
                head_list.append(str(h[0])[:100])
            elif isinstance(h, str):
                head_list.append(h[:100])
    status = {
        'high_impact_alert': bool(high_impact),
        'last_headlines': head_list,
        'last_checked': datetime.now(timezone.utc).isoformat(),
        'avoid_trading': bool(avoid_trading),
    }
    tmp = target + f'.{os.getpid()}.tmp'
    try:
        dir_name = os.path.dirname(target)
        if dir_name and not os.path.exists(dir_name):
            os.makedirs(dir_name, exist_ok=True)
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(status, f, indent=2)
        # Windows retry loop for transient file sharing lock
        for attempt in range(5):
            try:
                os.replace(tmp, target)
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.05)
    except Exception as e:
        logger.error("write_status error: %s", e)
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def _load_last_status(status_file=None) -> dict:
    """Load previous status from disk (fail-closed fallback)."""
    target = status_file or NEWS_STATUS_FILE
    try:
        if os.path.exists(target):
            with open(target, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logger.warning("_load_last_status error: %s", e)
    return {}


def _load_last_avoid_trading(status_file=None) -> bool:
    """Load previous avoid_trading state from disk."""
    return bool(_load_last_status(status_file=status_file).get('avoid_trading', False))


def is_entry_blocked(status_file: str = None) -> bool:
    """Return True if avoid_trading or high_impact_alert is active in news_status.json."""
    target = status_file or NEWS_STATUS_FILE
    try:
        if not os.path.exists(target):
            return False
        with open(target, 'r', encoding='utf-8') as f:
            st = json.load(f)
        return bool(st.get('avoid_trading', False) or st.get('high_impact_alert', False))
    except Exception as e:
        logger.warning("gold_news_fetcher is_entry_blocked error: %s", e)
        return True  # fail-closed on corrupt or unreadable file


def is_blocked(status_file: str = None) -> bool:
    return is_entry_blocked(status_file=status_file)





def run():
    logger.info("Gold News Fetcher started.")
    while True:
        try:
            all_headlines = []
            any_feed_succeeded = False

            for feed_url in RSS_FEEDS:
                items = fetch_rss(feed_url)
                if items is None:
                    logger.warning("Feed failed: %s — using last known state", feed_url)
                    continue  # Don't count failures as "no headlines"
                any_feed_succeeded = True
                all_headlines.extend(items)
                logger.info("Fetched %d items from %s", len(items), feed_url)

            if not any_feed_succeeded:
                # FIX: FAIL-SAFE — all feeds failed, preserve last known avoid_trading state and headlines
                last_data = _load_last_status()
                last_state = bool(last_data.get('avoid_trading', False))
                logger.error(
                    "ALL RSS FEEDS FAILED — preserving last avoid_trading=%s (fail-safe)", last_state
                )
                prev_headlines = [(h, "") for h in last_data.get('last_headlines', [])]
                write_status(last_state, prev_headlines, last_state)
            else:
                high_impact, matched = check_high_impact(all_headlines)
                avoid_trading = high_impact

                if high_impact:
                    logger.warning("HIGH IMPACT EVENT DETECTED: %s - Avoid trading!", matched[:80])
                else:
                    logger.info("No high-impact events detected.")

                write_status(high_impact, all_headlines, avoid_trading)

            time.sleep(900)  # 15 minutes

        except Exception:  # pragma: no cover
            logger.exception(
                "Unhandled exception in gold_news_fetcher run loop — sleeping 60s before retry"
            )
            time.sleep(60)


if __name__ == '__main__':
    run()
