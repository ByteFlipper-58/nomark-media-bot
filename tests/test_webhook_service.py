"""Async integration tests for WebhookService & AlbumService using pure in-memory fakes."""

from __future__ import annotations

import unittest
from typing import Any

from nomark.application.album_service import AlbumService
from nomark.application.webhook_service import WebhookService
from nomark.config import (
    LANG_EN,
    LANG_RU,
    MODE_C2PA_ONLY,
    MODE_ERASE,
    MODE_FULL_HD,
    MODE_IDENTIFY,
    STRENGTH_STRONG,
)
from nomark.domain.models import UserSettings
from nomark.domain.policies import build_result_cache_key, current_month_key, empty_stats, merge_stat_delta


class InMemoryStateStore:
    def __init__(self) -> None:
        self.seen_updates: set[int] = set()
        self.users: dict[int, dict[str, Any]] = {}
        self.stats: dict[str, dict[str, Any]] = {}
        self.budget_guard: bool = True
        self.jobs: dict[str, dict[str, Any]] = {}
        self.erase_jobs: dict[str, dict[str, Any]] = {}
        self.last_erase: dict[int, str] = {}
        self.result_cache: dict[str, dict[str, Any]] = {}
        self.albums: dict[str, list[dict[str, Any]]] = {}
        self.album_leaders: set[str] = set()

    async def mark_update_seen(self, update_id: int) -> bool:
        if update_id in self.seen_updates:
            return True
        self.seen_updates.add(update_id)
        return False

    async def get_user_settings(self, user_id: int, *, default_lang: str) -> UserSettings:
        return UserSettings.from_raw(self.users.get(user_id), default_lang=default_lang)

    async def save_user_settings(self, user_id: int, settings: UserSettings) -> None:
        self.users[user_id] = settings.to_dict()

    async def get_stats(self, month: str) -> dict[str, Any]:
        return self.stats.get(month, empty_stats(month))

    async def record_cache_hit(self, month: str) -> None:
        cur = self.stats.get(month)
        self.stats[month] = merge_stat_delta(cur, month=month, field="cache_hits", tier="cpu", seconds=0.0)

    async def is_budget_guard_enabled(self) -> bool:
        return self.budget_guard

    async def set_budget_guard_enabled(self, enabled: bool) -> None:
        self.budget_guard = enabled

    async def get_job(self, job_id: str) -> dict[str, Any] | None:
        return self.jobs.get(job_id)

    async def save_job(self, job_id: str, record: dict[str, Any]) -> None:
        self.jobs[job_id] = record

    async def get_erase_job(self, job_id: str) -> dict[str, Any] | None:
        return self.erase_jobs.get(job_id)

    async def save_erase_job(self, job_id: str, chat_id: int, record: dict[str, Any]) -> None:
        self.erase_jobs[job_id] = record
        self.last_erase[chat_id] = job_id

    async def get_last_erase_job(self, chat_id: int) -> dict[str, Any] | None:
        jid = self.last_erase.get(chat_id)
        return self.erase_jobs.get(jid) if jid else None

    async def get_cached_result(self, cache_key: str) -> dict[str, Any] | None:
        return self.result_cache.get(cache_key)

    async def add_album_item(self, media_group_id: str, message_id: int, payload: dict[str, Any]) -> bool:
        self.albums.setdefault(media_group_id, []).append(payload)
        if media_group_id in self.album_leaders:
            return False
        self.album_leaders.add(media_group_id)
        return True

    async def pop_album_items(self, media_group_id: str) -> list[dict[str, Any]]:
        items = self.albums.pop(media_group_id, [])
        self.album_leaders.discard(media_group_id)
        return sorted(items, key=lambda x: int(x.get("message_id", 0)))


class FakeTelegramGateway:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.edited: list[dict[str, Any]] = []
        self.callbacks: list[dict[str, Any]] = []
        self.cached_files: list[dict[str, Any]] = []
        self._msg_seq = 100

    async def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        reply_markup: dict[str, Any] | None = None,
        reply_to_message_id: int | None = None,
    ) -> int:
        self._msg_seq += 1
        self.sent.append(
            {
                "message_id": self._msg_seq,
                "chat_id": chat_id,
                "text": text,
                "reply_markup": reply_markup,
                "reply_to_message_id": reply_to_message_id,
            }
        )
        return self._msg_seq

    async def edit_message_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        *,
        reply_markup: dict[str, Any] | None = None,
    ) -> None:
        self.edited.append(
            {"chat_id": chat_id, "message_id": message_id, "text": text, "reply_markup": reply_markup}
        )

    async def answer_callback_query(self, callback_query_id: str, text: str | None = None) -> None:
        self.callbacks.append({"id": callback_query_id, "text": text})

    async def send_cached_file(
        self,
        chat_id: int,
        *,
        delivery_method: str,
        file_id: str,
        caption: str | None = None,
        reply_to_message_id: int | None = None,
        reply_markup: dict[str, Any] | None = None,
    ) -> str | None:
        self.cached_files.append(
            {
                "chat_id": chat_id,
                "delivery_method": delivery_method,
                "file_id": file_id,
                "caption": caption,
                "reply_to_message_id": reply_to_message_id,
                "reply_markup": reply_markup,
            }
        )
        return file_id


class FakeJobDispatcher:
    def __init__(self) -> None:
        self.spawned: list[tuple[str, dict[str, Any]]] = []

    async def _record(self, name: str, kwargs: dict[str, Any]) -> None:
        self.spawned.append((name, kwargs))

    async def spawn_cpu_file(self, **kwargs: Any) -> None:
        await self._record("cpu_file", kwargs)

    async def spawn_cpu_text(self, **kwargs: Any) -> None:
        await self._record("cpu_text", kwargs)

    async def spawn_cpu_erase(self, **kwargs: Any) -> None:
        await self._record("cpu_erase", kwargs)

    async def spawn_cpu_album(self, **kwargs: Any) -> None:
        await self._record("cpu_album", kwargs)

    async def spawn_url_job(self, **kwargs: Any) -> None:
        await self._record("url_job", kwargs)

    async def spawn_album_collector(self, **kwargs: Any) -> None:
        await self._record("album_collector", kwargs)

    async def spawn_gpu_photo(self, **kwargs: Any) -> None:
        await self._record("gpu_photo", kwargs)

    async def spawn_gpu_photo_album(self, **kwargs: Any) -> None:
        await self._record("gpu_photo_album", kwargs)

    async def spawn_gpu_zip(self, **kwargs: Any) -> None:
        await self._record("gpu_zip", kwargs)

    async def spawn_gpu_audio(self, **kwargs: Any) -> None:
        await self._record("gpu_audio", kwargs)

    async def spawn_gpu_video_hd(self, **kwargs: Any) -> None:
        await self._record("gpu_video_hd", kwargs)

    async def spawn_gpu_video_fast(self, **kwargs: Any) -> None:
        await self._record("gpu_video_fast", kwargs)

    async def spawn_gpu_warmup(self, target: str, *, chat_id: int, status_message_id: int, lang: str) -> None:
        await self._record("gpu_warmup", {"target": target, "chat_id": chat_id, "status_message_id": status_message_id, "lang": lang})


class WebhookAndAlbumServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.state = InMemoryStateStore()
        self.tg = FakeTelegramGateway()
        self.dispatcher = FakeJobDispatcher()
        self.service = WebhookService(state=self.state, tg=self.tg, dispatcher=self.dispatcher)

    async def test_first_start_shows_language_picker_then_selects_english(self) -> None:
        res1 = await self.service.handle_update(
            {
                "update_id": 1,
                "message": {
                    "message_id": 10,
                    "chat": {"id": 42},
                    "from": {"id": 42, "language_code": "ru"},
                    "text": "/start",
                },
            }
        )
        self.assertEqual(res1, {"ok": True, "onboarding": "language_picker"})
        self.assertIn("Choose your language", self.tg.sent[-1]["text"])

        # Duplicate update_id must be ignored atomically
        dup = await self.service.handle_update({"update_id": 1, "message": {"chat": {"id": 42}, "text": "/start"}})
        self.assertEqual(dup, {"ok": True, "duplicate": True})

        # Select English via inline button
        res2 = await self.service.handle_update(
            {
                "update_id": 2,
                "callback_query": {
                    "id": "cb_lang",
                    "from": {"id": 42, "language_code": "ru"},
                    "message": {"chat": {"id": 42}, "message_id": 101},
                    "data": "lang:en",
                },
            }
        )
        self.assertEqual(res2, {"ok": True, "lang": LANG_EN})
        saved = await self.state.get_user_settings(42, default_lang=LANG_RU)
        self.assertEqual(saved.lang, LANG_EN)
        self.assertTrue(saved.lang_chosen)
        self.assertIn("Full Clean HD", self.tg.edited[-1]["text"])

        # Subsequent /start skips picker and opens English main menu directly
        res3 = await self.service.handle_update(
            {
                "update_id": 3,
                "message": {"message_id": 11, "chat": {"id": 42}, "from": {"id": 42}, "text": "/start"},
            }
        )
        self.assertEqual(res3, {"ok": True, "command": "start"})
        self.assertIn("Full Clean HD", self.tg.sent[-1]["text"])

    async def test_settings_language_toggle_and_access_control(self) -> None:
        restricted = WebhookService(state=self.state, tg=self.tg, dispatcher=self.dispatcher, allowed_users_raw="999")
        denied = await restricted.handle_update(
            {
                "update_id": 10,
                "message": {"message_id": 1, "chat": {"id": 7}, "from": {"id": 7, "language_code": "en"}, "text": "/start"},
            }
        )
        self.assertTrue(denied.get("denied"))
        self.assertIn("this bot is private", self.tg.sent[-1]["text"].lower())

        await self.state.save_user_settings(42, UserSettings(lang=LANG_EN, lang_chosen=True))
        await self.service.handle_update(
            {
                "update_id": 11,
                "callback_query": {
                    "id": "cb_set_lang",
                    "from": {"id": 42},
                    "message": {"chat": {"id": 42}, "message_id": 50},
                    "data": "set:lang",
                },
            }
        )
        saved = await self.state.get_user_settings(42, default_lang=LANG_EN)
        self.assertEqual(saved.lang, LANG_RU)

    async def test_instant_result_cache_hit_and_recompute(self) -> None:
        settings = UserSettings(mode=MODE_FULL_HD, lang=LANG_EN, lang_chosen=True)
        await self.state.save_user_settings(42, settings)
        cache_key = build_result_cache_key(
            file_unique_id="uniq_photo_1",
            kind="image",
            mode=settings.mode,
            natural_polish=settings.natural_polish,
            photo_vendor=settings.photo_vendor,
            camera_exif=settings.camera_exif,
            photo_output=settings.photo_output,
        )
        assert cache_key is not None
        self.state.result_cache[cache_key] = {
            "out_file_id": "tg_cached_fid",
            "delivery_method": "document",
            "out_file_name": "img_clean.png",
            "out_size": 1024,
            "caption": "Done in 10s",
            "lang": LANG_RU,  # cross-language hit should fallback cleanly to EN default caption!
        }

        res = await self.service.handle_update(
            {
                "update_id": 20,
                "message": {
                    "message_id": 200,
                    "chat": {"id": 42},
                    "from": {"id": 42},
                    "document": {
                        "file_id": "src_fid_1",
                        "file_unique_id": "uniq_photo_1",
                        "file_name": "img.png",
                        "mime_type": "image/png",
                        "file_size": 5000,
                    },
                },
            }
        )
        self.assertEqual(res, {"ok": True, "cache_hit": True})
        self.assertEqual(len(self.dispatcher.spawned), 0)
        self.assertEqual(len(self.tg.cached_files), 1)
        self.assertIn("From cache", self.tg.cached_files[0]["caption"])
        stats = await self.state.get_stats(current_month_key())
        self.assertEqual(stats["cache_hits"], 1)

        # Trigger Recompute button from the saved job record
        job_id = next(iter(self.state.jobs.keys()))
        res_re = await self.service.handle_update(
            {
                "update_id": 21,
                "callback_query": {
                    "id": "cb_recomp",
                    "from": {"id": 42},
                    "message": {"chat": {"id": 42}, "message_id": 201},
                    "data": f"act:recompute:{job_id}",
                },
            }
        )
        self.assertEqual(res_re, {"ok": True, "dispatched": "act_recompute_gpu"})
        self.assertEqual(self.dispatcher.spawned[-1][0], "gpu_photo")

    async def test_budget_guard_blocks_gpu_but_allows_cpu(self) -> None:
        month = current_month_key()
        self.state.stats[month] = merge_stat_delta(None, month=month, field="videos_hd", tier="h100", seconds=30000.0)
        await self.state.save_user_settings(42, UserSettings(mode=MODE_FULL_HD, lang=LANG_EN, lang_chosen=True))

        blocked = await self.service.handle_update(
            {
                "update_id": 30,
                "message": {
                    "message_id": 300,
                    "chat": {"id": 42},
                    "from": {"id": 42},
                    "photo": [{"file_id": "p1", "file_unique_id": "up1", "file_size": 1000, "width": 500}],
                },
            }
        )
        self.assertEqual(blocked, {"ok": True, "blocked_by_budget": True})
        self.assertEqual(len(self.dispatcher.spawned), 0)

        # Switch to C2PA-only (CPU) -> must still work!
        await self.state.save_user_settings(42, UserSettings(mode=MODE_C2PA_ONLY, lang=LANG_EN, lang_chosen=True))
        allowed = await self.service.handle_update(
            {
                "update_id": 31,
                "message": {
                    "message_id": 301,
                    "chat": {"id": 42},
                    "from": {"id": 42},
                    "photo": [{"file_id": "p2", "file_unique_id": "up2", "file_size": 1000, "width": 500}],
                },
            }
        )
        self.assertEqual(allowed, {"ok": True, "dispatched": "cpu"})
        self.assertEqual(self.dispatcher.spawned[-1][0], "cpu_file")

    async def test_album_coalescing_and_async_album_service(self) -> None:
        await self.state.save_user_settings(42, UserSettings(mode=MODE_FULL_HD, lang=LANG_EN, lang_chosen=True))

        r1 = await self.service.handle_update(
            {
                "update_id": 40,
                "message": {
                    "message_id": 401,
                    "media_group_id": "grp_99",
                    "chat": {"id": 42},
                    "from": {"id": 42},
                    "photo": [{"file_id": "a1", "file_unique_id": "ua1", "file_size": 500, "width": 400}],
                },
            }
        )
        r2 = await self.service.handle_update(
            {
                "update_id": 41,
                "message": {
                    "message_id": 402,
                    "media_group_id": "grp_99",
                    "chat": {"id": 42},
                    "from": {"id": 42},
                    "photo": [{"file_id": "a2", "file_unique_id": "ua2", "file_size": 600, "width": 400}],
                },
            }
        )
        self.assertTrue(r1["album_leader"])
        self.assertFalse(r2["album_leader"])
        self.assertEqual(len(self.dispatcher.spawned), 1)
        self.assertEqual(self.dispatcher.spawned[0][0], "album_collector")

        album_service = AlbumService(
            state=self.state,
            tg=self.tg,
            dispatcher=self.dispatcher,
            delay_sec=0.0,
        )
        collector_args = self.dispatcher.spawned[0][1]
        dispatched = await album_service.collect_and_dispatch(**collector_args)
        self.assertEqual(dispatched, {"ok": True, "dispatched": "gpu_album", "count": 2})
        self.assertEqual(self.dispatcher.spawned[-1][0], "gpu_photo_album")
        self.assertEqual(len(self.dispatcher.spawned[-1][1]["items"]), 2)

    async def test_erase_corner_and_custom_box_and_warmup_and_post_actions(self) -> None:
        await self.state.save_user_settings(42, UserSettings(mode=MODE_ERASE, lang=LANG_EN, lang_chosen=True))
        r_media = await self.service.handle_update(
            {
                "update_id": 50,
                "message": {
                    "message_id": 500,
                    "chat": {"id": 42},
                    "from": {"id": 42},
                    "photo": [{"file_id": "e1", "file_unique_id": "ue1", "file_size": 500, "width": 400}],
                },
            }
        )
        erase_job_id = r_media["awaiting_corner"]

        # Click corner button
        r_corner = await self.service.handle_update(
            {
                "update_id": 51,
                "callback_query": {
                    "id": "cb_erase",
                    "from": {"id": 42},
                    "message": {"chat": {"id": 42}, "message_id": 501},
                    "data": f"erase:{erase_job_id}:br",
                },
            }
        )
        self.assertEqual(r_corner, {"ok": True, "dispatched": "cpu_erase"})

        # Send manual coordinates x,y,w,h
        r_box = await self.service.handle_update(
            {
                "update_id": 52,
                "message": {"message_id": 502, "chat": {"id": 42}, "from": {"id": 42}, "text": "10,20,100,50"},
            }
        )
        self.assertEqual(r_box, {"ok": True, "dispatched": "erase_custom_box"})
        self.assertEqual(self.dispatcher.spawned[-1][1]["custom_box"], (10, 20, 100, 50))

        # Trigger GPU warmup
        r_warm = await self.service.handle_update(
            {
                "update_id": 53,
                "callback_query": {
                    "id": "cb_warm",
                    "from": {"id": 42},
                    "message": {"chat": {"id": 42}, "message_id": 503},
                    "data": "warm:vwan",
                },
            }
        )
        self.assertEqual(r_warm, {"ok": True, "dispatched": "warm_vwan"})

        # Post-result retry + check + upgrade
        await self.state.save_job(
            "job123",
            {
                "kind": "video",
                "mode": MODE_FULL_HD,
                "src_file_id": "vid_src",
                "src_file_name": "clip.mp4",
                "out_file_id": "vid_out",
                "out_file_name": "clip_clean.mp4",
            },
        )
        r_retry = await self.service.handle_update(
            {
                "update_id": 54,
                "callback_query": {
                    "id": "cb_retry",
                    "from": {"id": 42},
                    "message": {"chat": {"id": 42}, "message_id": 504},
                    "data": f"act:retry:job123:{STRENGTH_STRONG}",
                },
            }
        )
        self.assertEqual(r_retry, {"ok": True, "dispatched": "act_retry"})
        self.assertEqual(self.dispatcher.spawned[-1][0], "gpu_video_hd")
        self.assertEqual(self.dispatcher.spawned[-1][1]["video_strength"], STRENGTH_STRONG)

        r_check = await self.service.handle_update(
            {
                "update_id": 55,
                "callback_query": {
                    "id": "cb_check",
                    "from": {"id": 42},
                    "message": {"chat": {"id": 42}, "message_id": 504},
                    "data": "act:check:job123",
                },
            }
        )
        self.assertEqual(r_check, {"ok": True, "dispatched": "act_check"})
        self.assertEqual(self.dispatcher.spawned[-1][1]["mode"], MODE_IDENTIFY)

    async def test_anonymous_sender_and_botname_commands_do_not_crash(self) -> None:
        # Message without from.id (e.g. channel/anonymous admin) must not raise TypeError
        res_anon = await self.service.handle_update(
            {
                "update_id": 60,
                "message": {"message_id": 600, "chat": {"id": -100123}, "text": "/help@NoMarkBot"},
            }
        )
        self.assertEqual(res_anon, {"ok": True, "command": "help"})

        # /text@NoMarkBot must strip the @botname from payload_text
        res_txt = await self.service.handle_update(
            {
                "update_id": 61,
                "message": {
                    "message_id": 601,
                    "chat": {"id": 42},
                    "from": {"id": 42},
                    "text": "/text@NoMarkBot clean this text",
                },
            }
        )
        self.assertEqual(res_txt, {"ok": True, "dispatched": "cpu_text"})
        self.assertEqual(self.dispatcher.spawned[-1][1]["raw_text"], "clean this text")

        # Message without message_id is safely ignored
        res_no_mid = await self.service.handle_update(
            {"update_id": 62, "message": {"chat": {"id": 42}, "text": "/start"}}
        )
        self.assertEqual(res_no_mid, {"ok": True})


if __name__ == "__main__":
    unittest.main()
