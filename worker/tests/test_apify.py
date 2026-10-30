import unittest
from datetime import date, timezone

from app.domain.apify import (build_run_input, is_terminal, map_item, succeeded)
from app.domain.talkwalker import RejectedRow


class BuildRunInputTests(unittest.TestCase):
    def test_tweet_scraper_uses_search_terms_and_cap(self) -> None:
        run_input = build_run_input("apidojo/tweet-scraper", ["agua", " nuevo leon "], 200)
        self.assertEqual(run_input["searchTerms"], ["agua", "nuevo leon"])
        self.assertEqual(run_input["maxItems"], 200)

    def test_unknown_actor_falls_back_to_generic_schema(self) -> None:
        run_input = build_run_input("vendor/otro-actor", ["ramen"], 10)
        self.assertEqual(run_input, {"searchStringsArray": ["ramen"], "maxItems": 10})

    def test_requires_keywords(self) -> None:
        with self.assertRaises(ValueError):
            build_run_input("apidojo/tweet-scraper", ["  ", ""], 10)

    def test_rejects_non_positive_cap(self) -> None:
        with self.assertRaises(ValueError):
            build_run_input("apidojo/tweet-scraper", ["agua"], 0)

    def test_rejects_actor_without_keyword_search(self) -> None:
        # Facebook posts-scraper no busca por palabras: debe fallar ANTES de llamar a Apify.
        with self.assertRaises(ValueError):
            build_run_input("apify/facebook-posts-scraper", ["agua"], 50)

    def test_clamps_records_to_quota_ceiling(self) -> None:
        run_input = build_run_input("apidojo/tweet-scraper", ["agua"], 99_999)
        self.assertEqual(run_input["maxItems"], 10_000)


class MapItemTests(unittest.TestCase):
    def test_maps_common_fields_and_reuses_url_identity(self) -> None:
        item = {"url": "https://x.com/u/status/1", "fullText": "hola",
                "createdAt": "2026-10-20T12:00:00Z", "username": "u", "likes": "5"}
        row = map_item("x", 1, item, minimum=date(2015, 1, 1))
        self.assertEqual(row["red_id"], 1)
        self.assertEqual(row["url"], "https://x.com/u/status/1")
        self.assertEqual(row["texto"], "hola")
        self.assertEqual(row["autor_usuario"], "u")
        self.assertEqual(row["likes"], 5)
        self.assertEqual(row["fecha_publicacion"].tzinfo, timezone.utc)
        self.assertIsInstance(row["url_hash"], (bytes, bytearray))

    def test_epoch_milliseconds_are_accepted(self) -> None:
        item = {"url": "https://x.com/u/status/2", "timestamp": 1_760_000_000_000, "text": "x"}
        row = map_item("x", 1, item)
        self.assertEqual(row["fecha_publicacion"].year, 2025)

    def test_item_without_url_is_rejected(self) -> None:
        with self.assertRaises(RejectedRow):
            map_item("x", 1, {"text": "sin url", "createdAt": "2026-01-01T00:00:00Z"})

    def test_item_without_date_is_rejected(self) -> None:
        with self.assertRaises(RejectedRow):
            map_item("x", 1, {"url": "https://x.com/u/status/3"})

    def test_reply_marks_comment(self) -> None:
        item = {"url": "https://x.com/u/status/4", "createdAt": "2026-01-01T00:00:00Z",
                "inReplyToUrl": "https://x.com/u/status/1"}
        row = map_item("x", 1, item)
        self.assertTrue(row["es_comentario"])
        self.assertEqual(row["url_padre"], "https://x.com/u/status/1")


class RunStatusTests(unittest.TestCase):
    def test_terminal_and_success(self) -> None:
        self.assertTrue(is_terminal("SUCCEEDED"))
        self.assertTrue(is_terminal("failed"))
        self.assertFalse(is_terminal("RUNNING"))
        self.assertTrue(succeeded("SUCCEEDED"))
        self.assertFalse(succeeded("FAILED"))


if __name__ == "__main__":
    unittest.main()
