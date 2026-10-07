import unittest
from unittest.mock import patch

from fabric.rest import _TOKEN_CACHE, token


class TokenCacheTests(unittest.TestCase):
    def test_reuses_valid_token_only_for_the_same_tenant_and_audience(self):
        with patch.dict(_TOKEN_CACHE, {}, clear=True), patch("fabric.rest.time.time", return_value=1000), \
                patch("fabric.rest.az_json", return_value={"accessToken": "fixture", "expires_on": 2000}) as cli:
            self.assertEqual(token("tenant-a", "audience-a"), "fixture")
            self.assertEqual(token("tenant-a", "audience-a"), "fixture")
            self.assertEqual(cli.call_count, 1)
            token("tenant-a", "audience-b")
            token("tenant-b", "audience-a")
            self.assertEqual(cli.call_count, 3)

    def test_refreshes_before_expiry_without_an_interactive_login(self):
        with patch.dict(_TOKEN_CACHE, {("tenant", "audience"): ("old", 1080)}, clear=True), \
                patch("fabric.rest.time.time", return_value=1000), \
                patch("fabric.rest.az_json", return_value={"accessToken": "new", "expires_on": 2000}) as cli:
            self.assertEqual(token("tenant", "audience"), "new")
            self.assertEqual(cli.call_args.args[0:2], ("account", "get-access-token"))


if __name__ == "__main__":
    unittest.main()
