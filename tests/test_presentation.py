"""Unit tests for Presentation layer: RU/EN i18n parity, keyboards, and HTML views."""

from __future__ import annotations

import string
import unittest
from types import SimpleNamespace

from nomark.config import (
    LANG_EN,
    LANG_RU,
    MODE_C2PA_ONLY,
    MODE_FULL_HD,
    MODE_VISIBLE,
    STRENGTH_BALANCED,
    SUPPORTED_LANGS,
)
from nomark.domain.models import UserSettings
from nomark.domain.policies import empty_stats
from nomark.presentation.i18n import TRANSLATIONS, t
from nomark.presentation.keyboards import (
    build_erase_corner_keyboard,
    build_language_picker_keyboard,
    build_menu_keyboard,
    build_result_keyboard,
    build_settings_keyboard,
    build_stats_keyboard,
    build_warmup_keyboard,
)
from nomark.presentation.views import (
    build_language_picker_text,
    build_settings_text,
    build_warmup_text,
    build_welcome_text,
    format_audio_identify_report,
    format_error_text,
    format_image_identify_report,
    format_stats_text,
    format_text_identify_report,
    format_video_identify_report,
)


def _format_field_names(template: str) -> set[str]:
    formatter = string.Formatter()
    return {field for _, field, _, _ in formatter.parse(template) if field is not None}


class I18nParityTests(unittest.TestCase):
    def test_ru_and_en_have_identical_keys_and_placeholders(self) -> None:
        ru = TRANSLATIONS[LANG_RU]
        en = TRANSLATIONS[LANG_EN]
        self.assertEqual(set(ru.keys()), set(en.keys()))
        for key in ru:
            self.assertEqual(
                _format_field_names(ru[key]),
                _format_field_names(en[key]),
                f"Placeholder mismatch for key {key!r}",
            )

    def test_t_falls_back_gracefully_on_unknown_lang(self) -> None:
        self.assertEqual(t("state.on", "fr"), t("state.on", LANG_EN))


class KeyboardConstraintTests(unittest.TestCase):
    def _assert_valid_markup(self, markup: dict) -> None:
        rows = markup.get("inline_keyboard")
        self.assertIsInstance(rows, list)
        self.assertGreater(len(rows), 0)
        for row in rows:
            for btn in row:
                self.assertIn("text", btn)
                self.assertIn("callback_data", btn)
                cb = btn["callback_data"]
                self.assertLessEqual(len(cb.encode("utf-8")), 64, f"callback_data > 64 bytes: {cb!r}")

    def test_all_keyboards_valid_in_both_languages(self) -> None:
        self._assert_valid_markup(build_language_picker_keyboard())
        for lang in SUPPORTED_LANGS:
            settings = UserSettings(lang=lang, lang_chosen=True)
            self._assert_valid_markup(build_menu_keyboard(settings))
            self._assert_valid_markup(build_settings_keyboard(settings))
            self._assert_valid_markup(build_stats_keyboard(budget_guard=True, lang=lang))
            self._assert_valid_markup(build_warmup_keyboard(lang=lang))
            self._assert_valid_markup(build_erase_corner_keyboard("abc1234567", lang=lang))
            self._assert_valid_markup(
                build_result_keyboard(
                    "abc1234567",
                    kind="video",
                    mode=MODE_FULL_HD,
                    video_strength=STRENGTH_BALANCED,
                    has_source_file=True,
                    has_output_file=True,
                    is_cached=True,
                    lang=lang,
                )
            )
            self._assert_valid_markup(
                build_result_keyboard(
                    "abc1234567",
                    kind="image",
                    mode=MODE_C2PA_ONLY,
                    has_source_file=True,
                    has_output_file=True,
                    lang=lang,
                )
            )
            self._assert_valid_markup(
                build_result_keyboard(
                    "abc1234567",
                    kind="image",
                    mode=MODE_VISIBLE,
                    has_source_file=True,
                    has_output_file=False,
                    lang=lang,
                )
            )


class ViewRendererTests(unittest.TestCase):
    def test_views_render_cleanly_in_both_languages(self) -> None:
        self.assertIn("Choose your language", build_language_picker_text())
        for lang in SUPPORTED_LANGS:
            s = UserSettings(lang=lang, lang_chosen=True)
            self.assertIn("NoMark", build_welcome_text(s))
            self.assertTrue(build_settings_text(s))
            self.assertTrue(build_warmup_text(lang))
            self.assertIn("2026-11", format_stats_text(empty_stats("2026-11"), budget_guard=True, lang=lang))
            self.assertIn("&lt;script&gt;", format_error_text(RuntimeError("<script>boom</script>"), lang=lang))

    def test_identify_reports_escape_html_in_both_languages(self) -> None:
        img_rep = SimpleNamespace(
            is_ai_generated=True,
            platform="<Gemini>",
            watermarks=["<c2pa>"],
            signals=[SimpleNamespace(name="sig<1>", detail="<detail>")],
        )
        cls = SimpleNamespace(
            label="google<gemini>",
            version_subfamily="v2<beta>",
            confidence=0.92,
            synthetic_probability=0.95,
            synthetic_detected=True,
        )
        vid_rep = SimpleNamespace(
            is_ai_generated=True,
            platform="<Veo>",
            has_ai_metadata=True,
            visible_mark="<veo_logo>",
            metadata_markers={"<c2pa>": "1"},
            invisible_watermark_hints=("hint<1>",),
        )
        aud_rep = SimpleNamespace(
            metadata_markers={"<tag>": "1"},
            watermark_status="<detected>",
            recommended_recipe="<dac>",
        )
        txt_rep = SimpleNamespace(
            is_ai_generated=True,
            stego_codepoint_count=4,
            has_ai_metadata=False,
            platform="<gpt>",
            signals=("zwsp<1>",),
        )

        for lang in SUPPORTED_LANGS:
            for rendered in (
                format_image_identify_report(img_rep, source_cls=cls, lang=lang),
                format_video_identify_report(vid_rep, lang=lang),
                format_audio_identify_report(aud_rep, lang=lang),
                format_text_identify_report(txt_rep, lang=lang),
            ):
                self.assertNotIn("<Gemini>", rendered)
                self.assertNotIn("<Veo>", rendered)
                self.assertNotIn("<tag>", rendered)
                self.assertNotIn("<gpt>", rendered)
                self.assertIn("&lt;", rendered)


if __name__ == "__main__":
    unittest.main()
