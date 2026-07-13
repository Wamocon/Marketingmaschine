import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from validate_growth_env import load_env, validate  # noqa: E402


class GrowthEnvPreflightTests(unittest.TestCase):
    def test_example_is_intentionally_rejected_until_real_secrets_exist(self):
        values = load_env(ROOT / "deploy" / "growth-tools.env.example")
        errors = validate(values, ["postiz", "twenty", "mautic"])
        self.assertTrue(any("placeholder" in error for error in errors))
        self.assertFalse(any("must be pinned" in error for error in errors))

    def test_strong_values_and_digest_pins_pass(self):
        values = load_env(ROOT / "deploy" / "growth-tools.env.example")
        for name in (
            "POSTIZ_JWT_SECRET",
            "POSTIZ_POSTGRES_PASSWORD",
            "POSTIZ_TEMPORAL_POSTGRES_PASSWORD",
            "TWENTY_POSTGRES_PASSWORD",
            "TWENTY_ENCRYPTION_KEY",
            "TWENTY_FALLBACK_ENCRYPTION_KEY",
            "TWENTY_APP_SECRET",
            "MAUTIC_MYSQL_ROOT_PASSWORD",
            "MAUTIC_MYSQL_PASSWORD",
        ):
            values[name] = (name.casefold() + "-A7z9") * 4
        self.assertEqual(validate(values, ["postiz", "twenty", "mautic"]), [])

    def test_registration_test_data_and_mutable_images_fail_closed(self):
        values = load_env(ROOT / "deploy" / "growth-tools.env.example")
        values.update(
            {
                "POSTIZ_JWT_SECRET": "A1b2C3d4" * 8,
                "POSTIZ_POSTGRES_PASSWORD": "A1b2C3d4" * 4,
                "POSTIZ_TEMPORAL_POSTGRES_PASSWORD": "A1b2C3d4" * 4,
                "POSTIZ_DISABLE_REGISTRATION": "false",
                "POSTIZ_REDIS_IMAGE": "redis:latest",
            }
        )
        errors = validate(values, ["postiz"])
        self.assertIn("POSTIZ_DISABLE_REGISTRATION: must be true", errors)
        self.assertTrue(any(error.startswith("POSTIZ_REDIS_IMAGE:") for error in errors))

    def test_http_localhost_and_mismatched_canonical_authorities_fail(self):
        values = load_env(ROOT / "deploy" / "growth-tools.env.example")
        values.update(
            {
                "POSTIZ_JWT_SECRET": "A1b2C3d4" * 8,
                "POSTIZ_POSTGRES_PASSWORD": "A1b2C3d4" * 4,
                "POSTIZ_TEMPORAL_POSTGRES_PASSWORD": "A1b2C3d4" * 4,
                "POSTIZ_MAIN_URL": "http://localhost:4007",
                "POSTIZ_FRONTEND_URL": "https://marketing.example.com:14007",
                "POSTIZ_BACKEND_URL": "https://different.example.com:14007/api",
            }
        )

        errors = validate(values, ["postiz"])

        self.assertTrue(any(error.startswith("POSTIZ_MAIN_URL:") for error in errors))
        self.assertIn(
            "POSTIZ canonical URLs must use the same protected HTTPS authority",
            errors,
        )

    def test_database_url_components_reject_unescaped_reserved_characters(self):
        values = load_env(ROOT / "deploy" / "growth-tools.env.example")
        values.update(
            {
                "TWENTY_POSTGRES_PASSWORD": "strong-but:" + "breaks@the/database?url",
                "TWENTY_ENCRYPTION_KEY": "A1b2C3d4" * 4,
                "TWENTY_FALLBACK_ENCRYPTION_KEY": "B2c3D4e5" * 4,
                "TWENTY_APP_SECRET": "C3d4E5f6" * 4,
            }
        )

        errors = validate(values, ["twenty"])

        self.assertTrue(
            any(error.startswith("TWENTY_POSTGRES_PASSWORD: must use URI-safe") for error in errors)
        )
