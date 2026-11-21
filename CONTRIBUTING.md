# Contributing to NoMark

Contributions are welcome!

## Clean Architecture Overview

NoMark follows a strict layered Clean Architecture with end-to-end async I/O on the webhook & album-coalescing paths:

```text
modal_app.py                         # Thin Modal Composition Root (images, snapshots, worker bindings)
nomark/
  config.py                          # Centralized constants & NOMARK_* env overrides
  domain/
    models.py                        # Immutable entities (UserSettings, MediaItem)
    policies.py                      # Pure deterministic rules (cache keys, budget guard, box geometry, vendor)
    ports.py                         # Async Protocol interfaces (StateStore, TelegramGateway, JobDispatcher)
  presentation/
    i18n.py                          # Bilingual RU/EN translation catalog & helpers
    keyboards.py                     # Telegram inline keyboard builders
    views.py                         # HTML message & provenance inspection renderers
  application/
    webhook_service.py               # Pure async webhook use-case controller (zero Modal/HTTP imports)
    album_service.py                 # Pure async Telegram album coalescer
  infrastructure/
    telegram_client.py               # Pooled AsyncTelegramClient (keep-alive AsyncClient) + SyncTelegramClient
    media_io.py                      # SSRF-safe URL download, ZIP extract/pack, Camera EXIF, FFmpeg helpers
    ml_loaders.py                    # Offline-first HF Volume loaders, CUDA TF32, Wan 2.1 prompt_embeds cache
    modal_adapters.py                # Modal Dict/Volume adapters implementing StateStore + sync helpers
    pipelines.py                     # CPU & GPU media processing execution pipelines
tests/
  test_domain.py                     # Domain models, policies, ZIP & EXIF tests
  test_presentation.py               # RU/EN i18n key/placeholder parity, 64-byte callback limits, HTML escaping
  test_webhook_service.py            # Async IsolatedAsyncioTestCase tests with pure in-memory fakes
```

## Local Development & Tests

`nomark.domain`, `nomark.presentation`, and `nomark.application` have **zero third-party runtime imports**, so the entire unit and async integration test suite runs anywhere with Python 3.12+:

```bash
python -m unittest discover -s tests -v
```

To also run the camera EXIF tests (`inject_camera_exif`), install `pillow` and `piexif`:

```bash
pip install pillow piexif
python -m unittest discover -s tests -v
```

## Adding a New Language

All bot UI strings live in [`nomark/presentation/i18n.py`](nomark/presentation/i18n.py):

1. Add your language code to `SUPPORTED_LANGS` / `LANG_ORDER` in [`nomark/config.py`](nomark/config.py) and `LANG_LABELS` + `TRANSLATIONS` in [`nomark/presentation/i18n.py`](nomark/presentation/i18n.py).
2. Translate all keys from `TRANSLATIONS["en"]`.
3. Optionally add a button for your language in `build_language_picker_keyboard()` inside [`nomark/presentation/keyboards.py`](nomark/presentation/keyboards.py).
4. Run `python -m unittest discover -s tests -v` — the test suite automatically verifies 100% key & placeholder parity across every language and checks that all Telegram `callback_data` payloads stay within the 64-byte limit.

## Guidelines

- Respect layer boundaries: `domain` must never import `application`, `presentation`, or `infrastructure`; `application` depends only on `domain` ports and `presentation`.
- Keep third-party dependencies (`httpx`, `PIL`, `piexif`, `diffusers`, `remove_ai_watermarks`) lazily imported inside infrastructure functions so local tests and `modal deploy` stay lightweight and HF Volume env vars bind cleanly.
- Never commit tokens, `.env`, or `.modal.toml`.
- Keep GPU workers scale-to-zero friendly (`$0/mo` idle) and preserve output visual quality.
