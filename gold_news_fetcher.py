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
    # Removed bare 'fed', 'rate' — too many false positives (matched 'forward', 'moderate', etc.)
]

# Compile keyword patterns as whole-word matches to avoid false positives
# e.g. 'rate' won't match 'moderate', 'war' won't match 'forward'
_KW_PATTERNS = [
    re.compile(rf"\b{re.escape(kw)}\b", re.IGNORECASE) for kw in HIGH_IMPACT_KEYWORDS
]

RSS_FEEDS = [
    'https://feeds.finance.yahoo.com/rss/2.0/headline?s=GC%3DF&region=US&lang=en-US',
    # Kitco RSS was returning 404; replaced with MarketWatch metals feed
    'https://feeds.content.dowjones.io/public/rss/mw_realtimeheadline',
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
    for title, _ in headlines:
        for pattern in _KW_PATTERNS:
            if pattern.search(title):
                logger.info("HIGH IMPACT KEYWORD FOUND: '%s' in '%s'", pattern.pattern, title[:80])
                return True, title
    return False, ''


def write_status(high_impact, headlines, avoid_trading):
    """Write news_status.json."""
    status = {
        'high_impact_alert': high_impact,
        'last_headlines': [h[0][:100] for h in headlines[:5]],
        'last_checked': datetime.now(timezone.utc).isoformat(),
        'avoid_trading': avoid_trading,
    }
    try:
        tmp = NEWS_STATUS_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(status, f, indent=2)
        os.replace(tmp, NEWS_STATUS_FILE)
    except Exception as e:
        logger.error("write_status error: %s", e)


def _load_last_avoid_trading() -> bool:
    """Load previous avoid_trading state from disk (fail-closed fallback)."""
    try:
        with open(NEWS_STATUS_FILE, 'r', encoding='utf-8') as f:
            return bool(json.load(f).get('avoid_trading', False))
    except Exception:
        return False  # First run: default to allowing (no prior state)


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
                # FIX: FAIL-SAFE — all feeds failed, preserve last known avoid_trading state
                last_state = _load_last_avoid_trading()
                logger.error(
                    "ALL RSS FEEDS FAILED — preserving last avoid_trading=%s (fail-safe)", last_state
                )
                # Update last_checked timestamp but keep avoid_trading as-is
                write_status(last_state, [], last_state)
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
