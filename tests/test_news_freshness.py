import datetime
import unittest
from email.utils import format_datetime
from unittest import mock

import fetch_data


class NewsFreshnessTests(unittest.TestCase):
    def test_stale_future_and_undated_articles_are_rejected(self):
        now = datetime.datetime(2026, 7, 27, 12, tzinfo=datetime.timezone.utc)
        fresh = {"published": (now - datetime.timedelta(days=2)).isoformat()}
        stale = {"published": (now - datetime.timedelta(days=8)).isoformat()}
        future = {"published": (now + datetime.timedelta(hours=25)).isoformat()}

        self.assertTrue(fetch_data._news_is_fresh(fresh, now))
        self.assertFalse(fetch_data._news_is_fresh(stale, now))
        self.assertFalse(fetch_data._news_is_fresh(future, now))
        self.assertFalse(fetch_data._news_is_fresh({"published": ""}, now))

    def test_balancing_cannot_resurface_stale_cached_article(self):
        now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
        items = [
            {"headline": "Fresh", "source": "A", "published": now.isoformat()},
            {"headline": "Ancient", "source": "B",
             "published": (now - datetime.timedelta(days=30)).isoformat()},
        ]
        self.assertEqual([item["headline"] for item in fetch_data._balanced_news(items)], ["Fresh"])

    def test_feed_is_sorted_before_six_article_cap(self):
        now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
        dates = [now - datetime.timedelta(hours=i) for i in range(7)]
        # Deliberately put the oldest entry first, which previously consumed a
        # slot before publication dates were considered.
        order = list(reversed(dates))
        items = "".join(
            f"<item><title>Story {published.hour}-{published.minute}</title>"
            f"<pubDate>{format_datetime(published)}</pubDate>"
            f"<link>https://example.com/{index}</link></item>"
            for index, published in enumerate(order)
        )
        xml = f"<rss><channel>{items}</channel></rss>"

        with mock.patch.object(fetch_data, "RSS_FEEDS", [("Test", "https://example.com/rss")]), \
             mock.patch.object(fetch_data, "_get_text", return_value=xml), \
             mock.patch.object(fetch_data, "_load_previous_news", return_value=[]), \
             mock.patch.object(fetch_data, "_news_relevant", return_value=True), \
             mock.patch.object(fetch_data, "_NEWS_CACHE", {"t": 0.0, "data": []}):
            result = fetch_data.fetch_news()

        result_dates = [fetch_data._news_datetime(item["published"]) for item in result]
        self.assertEqual(len(result_dates), 6)
        self.assertEqual(result_dates, sorted(dates, reverse=True)[:6])


if __name__ == "__main__":
    unittest.main()
