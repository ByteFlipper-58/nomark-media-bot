# NoMark — Serverless Telegram-бот для очистки AI-меток и метаданных

[![CI](https://github.com/ByteFlipper-58/nomark-media-bot/actions/workflows/ci.yml/badge.svg)](https://github.com/ByteFlipper-58/nomark-media-bot/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB.svg)](https://www.python.org/)
[![Modal Serverless](https://img.shields.io/badge/Hosted%20on-Modal%20Serverless-00D26A.svg)](https://modal.com/)
[![Languages: EN / RU](https://img.shields.io/badge/Bot%20UI-EN%20%7C%20RU-purple.svg)](nomark/presentation/i18n.py)

🇬🇧 **[English](README.md)** | 🇷🇺 **Русский**

**NoMark** — полностью serverless Telegram-бот на базе [remove-ai-watermarks](https://github.com/wiltodelta/remove-ai-watermarks) и [Modal](https://modal.com/). Удаляет **C2PA / EXIF / XMP метаданные**, **невидимые водяные знаки (SynthID, OpenAI, Meta)**, **видимые логотипы** и **скрытые Unicode-символы** из фото, альбомов, видео, аудио, ZIP-архивов и текста — при **$0/мес в простое** и **$30/мес бесплатных кредитов** на тарифе Modal Starter.

---

## Возможности

### 6 режимов работы (`/start`)
| Режим | Что делает | Движок и железо |
| :--- | :--- | :--- |
| **✨ Полная очистка HD** | Удаляет C2PA и SynthID в родном разрешении и FPS | Фото/Альбом/ZIP: `SDXL-ZImage` (`L4`/`A10G`) · Видео: `Wan 2.1 3D` (`H100`/`A100`) · Аудио: `DAC` (`L4`) · Текст: `CPU` |
| **⚡ Полная очистка (быстрая)** | Ускоренная очистка видео от C2PA + SynthID | Видео: `SD-VAE HD` (родной FPS, до 1280px, `L4`/`A10G`) · Фото/Аудио: как в HD |
| **🧹 Убрать видимый знак** | Автоматически удаляет логотипы Sora, Kling, Hailuo, Veo, Seedance, Doubao, Gemini + C2PA | `MI-GAN ONNX` (`CPU`) |
| **✂️ Стереть угол / область** | Ручное стирание любого из 6 углов кнопками или произвольной зоны `x,y,w,h` на фото и видео + C2PA | `MI-GAN ONNX` (`CPU`) |
| **🏷 Только метаданные (C2PA)** | Мгновенное снятие C2PA, EXIF, XMP и скрытого Unicode без потери качества | `CPU` (без перекодирования) |
| **🔍 Проверить файл** | Проверка C2PA/метаданных + нейросетевой классификатор источника (10 нейросетей) | `classify-source` (`CPU`) |

### Удобство и управление
- **Два языка (🇷🇺 Русский / 🇬🇧 English)** — экран выбора языка при первом `/start` + переключение в `/settings`.
- **Быстрые кнопки под результатом**: повтор видео с другой силой (`Мягче` / `Баланс` / `Максимум`) без повторной загрузки, апгрейд фото до `Полной очистки (SynthID)`, `Проверить результат`, `Пересчитать заново` и `Меню`.
- **Умный выбор источника фото (`/settings`)**: `Авто` (по C2PA) / `Gemini` (`0.50`) / `ChatGPT` (`0.15` — минимальные правки) / `Meta AI` (`0.20`).
- **Реалистичный EXIF камеры (`/settings`)**: опционально `Выкл` / `iPhone 16 Pro` / `Sony A7 IV` (без GPS, ноль AI-тегов).
- **Альбомы Telegram (`media_group_id`) и ZIP-архивы**: серии фото из галереи и ZIP до 40 фото обрабатываются пакетом на одном тёплом GPU-контейнере.
- **Большие файлы (>20 МБ)**: ссылки Google Drive, Dropbox и прямые URL до 250 МБ; результаты >50 МБ отдаются временной ссылкой на 1 час.
- **Статистика и защита бюджета (`/stats`)**: предупреждение с `~$24` и авто-стоп GPU на `~$27` из `$30/мес` бесплатных кредитов (CPU-режимы продолжают работать).

### Оптимизации скорости и кэширования (без потери качества)
- **Modal CPU & GPU Memory Snapshots**: библиотеки и веса (`SDXL + ControlNet`, `SD-VAE`, `Wan 2.1`) сохраняются прямо в RAM/VRAM-снапшоты для быстрого холодного старта при `$0/мес` в простое.
- **Кэш `prompt_embeds` для Wan 2.1**: статический эмбеддинг кэшируется в `modal.Volume`, полностью пропуская загрузку **9.4 ГБ UMT5-XXL** и CPU-кодирование (результат бит-в-бит идентичен, старт быстрее в ~7×).
- **Оффлайн-загрузка из Volume**: загрузка строго локально из `/mnt/models/hf/hub` (`HF_HUB_OFFLINE=1` / `local_files_only=True`) с авто-фоллбэком в сеть при первом запуске.
- **Мгновенный кэш результатов**: повторная отправка того же файла (`file_unique_id` + настройки) отдаётся за `<1с` и `$0 GPU` (с кнопкой `🔄 Пересчитать заново`).
- **CUDA TF32 + `ffmpeg veryfast crf 16` + `@modal.concurrent` + кнопка `🔥 Прогреть GPU`**.

### Чистая архитектура и асинхронность
- **`nomark/domain/`**: неизменяемые модели (`UserSettings`, `MediaItem`), чистые бизнес-правила и async-порты (`StateStore`, `TelegramGateway`, `JobDispatcher`).
- **`nomark/presentation/`**: RU/EN локализация (`i18n`), inline-клавиатуры и HTML-шаблоны отчётов.
- **`nomark/application/`**: полностью асинхронные use-case сервисы (`WebhookService`, `AlbumService`) с `asyncio.gather` и 100% покрытием unit/async-тестами без сети.
- **`nomark/infrastructure/`**: пулированный `AsyncTelegramClient` (keep-alive `httpx.AsyncClient`), `SyncTelegramClient`, SSRF-защищённый медиа I/O, оффлайн ML-загрузчики, адаптеры Modal Dict/Volume и CPU/GPU пайплайны.
- **`modal_app.py`**: тонкий Composition Root с описанием контейнеров, CPU/GPU снапшотов и воркеров Modal.

---

## Быстрый старт (3 минуты)

### Что понадобится
1. Токен Telegram-бота от [@BotFather](https://t.me/BotFather).
2. Бесплатный аккаунт [Modal](https://modal.com/) (тариф Starter даёт **$30/мес бесплатных кредитов**, простой бесплатный).
3. Python 3.12+ (или [uv](https://docs.astral.sh/uv/)).

### Деплой на Windows (PowerShell)
```powershell
git clone https://github.com/ByteFlipper-58/nomark-media-bot.git
cd nomark-media-bot
powershell -ExecutionPolicy Bypass -File .\deploy.ps1
```

### Деплой на Linux / macOS
```bash
git clone https://github.com/ByteFlipper-58/nomark-media-bot.git
cd nomark-media-bot
chmod +x deploy.sh
./deploy.sh
```

> **Важно по безопасности:** обязательно укажи `ALLOWED_USER_IDS` (свой числовой Telegram ID из `@userinfobot`, через запятую для нескольких пользователей) во время деплоя. Если оставить поле пустым, любой, кто найдёт бота, сможет тратить твои кредиты Modal GPU.

### Обновление и просмотр логов
```bash
# Повторный деплой после правок (~5 секунд)
modal deploy modal_app.py

# Логи
modal app logs raiw-telegram-bot --timestamps --tail 80
```

---

## Запуск тестов

```bash
python -m unittest discover -s tests -v
```

---

## Благодарности, лицензия и ответственное использование

- Работает на базе [**remove-ai-watermarks**](https://github.com/wiltodelta/remove-ai-watermarks) (Apache-2.0).
- Веса моделей (`SDXL`, `ControlNet`, `Z-Image`, `SAM`, `Wan 2.1`, `SD-VAE`, `MI-GAN`, `DAC`), загружаемые при работе, подчиняются лицензиям их правообладателей.
- Код этого репозитория распространяется под лицензией [MIT](LICENSE).
- **Ответственное использование:** инструмент предназначен для защиты приватности, очистки метаданных, личной творческой обработки и исследования устойчивости водяных знаков. Не используйте его для мошенничества, дезинформации или нарушения правил платформ и законов.
