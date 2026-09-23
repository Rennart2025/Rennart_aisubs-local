import io
import json
import re
import os
import sys
import unittest
import urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

import updates


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def answering(payload, calls=None):
    """An urlopen stand-in that returns `payload` as the body."""
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()

    def opener(url, timeout=None):
        if calls is not None:
            calls.append((url, timeout))
        return FakeResponse(body)
    return opener


def failing(error):
    def opener(url, timeout=None):
        raise error
    return opener


class VersionCompareTests(unittest.TestCase):
    def test_reads_the_numbers_out_of_a_version(self):
        self.assertEqual((1, 2, 1), updates.parse_version("1.2.1"))
        self.assertEqual((1, 3), updates.parse_version("v1.3"))
        self.assertEqual((), updates.parse_version("не версия"))

    def test_a_higher_number_anywhere_wins(self):
        self.assertTrue(updates.is_newer("1.3.0", "1.2.1"))
        self.assertTrue(updates.is_newer("1.2.2", "1.2.1"))
        self.assertTrue(updates.is_newer("2.0", "1.9.9"))

    def test_same_or_older_is_not_an_update(self):
        self.assertFalse(updates.is_newer("1.2.1", "1.2.1"))
        self.assertFalse(updates.is_newer("1.2", "1.2.0"))
        self.assertFalse(updates.is_newer("1.2.0", "1.2.1"))

    def test_a_version_we_cannot_read_never_claims_an_update(self):
        self.assertFalse(updates.is_newer("", "1.2.1"))
        self.assertFalse(updates.is_newer("latest", "1.2.1"))


class CheckTests(unittest.TestCase):
    def test_reports_a_newer_published_version(self):
        calls = []
        result = updates.check(
            "1.2.1",
            opener=answering({"version": "1.3.0", "notes": "Заголовки"}, calls),
        )

        self.assertTrue(result["ok"])
        self.assertTrue(result["update_available"])
        self.assertEqual("1.3.0", result["latest"])
        self.assertEqual("Заголовки", result["notes"])
        self.assertEqual(updates.VERSION_URL, calls[0][0])

    def test_the_current_version_is_not_an_update(self):
        result = updates.check("1.2.1", opener=answering({"version": "1.2.1"}))

        self.assertTrue(result["ok"])
        self.assertFalse(result["update_available"])

    def test_no_internet_is_an_answer_not_a_crash(self):
        result = updates.check("1.2.1", opener=failing(urllib.error.URLError("offline")))

        self.assertFalse(result["ok"])
        self.assertFalse(result["update_available"])
        self.assertIn("GitHub", result["error"])

    def test_a_broken_answer_is_reported_without_raising(self):
        for payload in (b"<html>404</html>", b"[1,2,3]", {"notes": "без версии"}):
            result = updates.check("1.2.1", opener=answering(payload))

            self.assertFalse(result["ok"], payload)
            self.assertFalse(result["update_available"], payload)
            self.assertTrue(result["error"], payload)

    def test_only_an_https_address_from_the_file_is_kept(self):
        result = updates.check(
            "1.2.1",
            opener=answering({"version": "1.3.0", "url": "javascript:alert(1)"}),
        )

        self.assertEqual(updates.RELEASE_URL, result["url"])


class PublishedVersionTests(unittest.TestCase):
    """version.json is what every installed copy compares itself against."""

    def test_the_published_file_matches_the_build(self):
        # app.py is read, not imported: importing it needs pywebview and a
        # window. The version is a plain constant, so the text is enough.
        root = os.path.join(os.path.dirname(__file__), "..")
        with open(os.path.join(root, "app.py"), encoding="utf-8") as handle:
            source = handle.read()
        with open(os.path.join(root, "version.json"), encoding="utf-8") as handle:
            published = json.load(handle)

        match = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', source, re.M)
        self.assertIsNotNone(match, "APP_VERSION не найден в app.py")
        self.assertEqual(match.group(1), published["version"],
                         "version.json на GitHub должен совпадать с версией сборки")
        self.assertTrue(published.get("notes"))


if __name__ == "__main__":
    unittest.main()
