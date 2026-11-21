"""Bilingual (RU / EN) localization strings for NoMark Telegram bot.

Zero external dependencies (stdlib only) so Modal deployment works from any environment.
To add another language, add its code to SUPPORTED_LANGS, LANG_LABELS, and TRANSLATIONS.
"""

from __future__ import annotations

from typing import Any

from nomark.config import BOT_NAME, DEFAULT_LANG, LANG_EN, LANG_ORDER, LANG_RU, SUPPORTED_LANGS
from nomark.domain.policies import normalize_lang

LANG_LABELS: dict[str, str] = {
    LANG_RU: "🇷🇺 Русский",
    LANG_EN: "🇬🇧 English",
}


TRANSLATIONS: dict[str, dict[str, str]] = {
    LANG_RU: {
        # Modes
        "mode.full_hd": "✨ Полная очистка HD",
        "mode.full_fast": "⚡ Полная очистка (быстрая)",
        "mode.visible": "🧹 Убрать видимый знак",
        "mode.erase": "✂️ Стереть угол / область",
        "mode.c2pa_only": "🏷 Только метаданные (C2PA)",
        "mode.identify": "🔍 Проверить файл",
        "desc.full_hd": (
            "Удаляет C2PA и SynthID с фото, альбомов, видео и аудио в максимальном качестве.\n"
            "• Фото / Альбом / ZIP: SDXL-ZImage · GPU L4 / A10G\n"
            "• Видео: Wan 2.1 3D (родной размер и FPS) · GPU H100 / A100\n"
            "• Аудио: DAC · GPU L4 / A10G  |  Текст: Unicode / C2PA · CPU"
        ),
        "desc.full_fast": (
            "Удаляет C2PA и SynthID с фото, альбомов, видео и аудио в ускоренном режиме.\n"
            "• Фото / Альбом / ZIP: SDXL-ZImage · GPU L4 / A10G\n"
            "• Видео: SD-VAE HD (родной FPS) · GPU L4 / A10G\n"
            "• Аудио: DAC · GPU L4 / A10G  |  Текст: Unicode / C2PA · CPU"
        ),
        "desc.visible": (
            "Автоматически удаляет известные логотипы (Sora, Kling, Hailuo, Veo, Seedance, Doubao, Gemini) + C2PA.\n"
            "• Фото / Видео / Альбом / ZIP: MI-GAN ONNX · CPU"
        ),
        "desc.erase": (
            "Ручное стирание любого угла или области (для нестандартных логотипов и подписей) + C2PA.\n"
            "• Фото / Видео: выбор угла кнопками или x,y,w,h · MI-GAN ONNX · CPU"
        ),
        "desc.c2pa_only": (
            "Мгновенно удаляет C2PA, EXIF, XMP и скрытые символы без потери качества (SynthID остаётся).\n"
            "• Фото / Видео / Аудио / Текст / Альбом / ZIP · CPU"
        ),
        "desc.identify": (
            "Проверяет C2PA, AI-метаданные и определяет вероятную нейросеть по пикселям.\n"
            "• Фото: C2PA + Source Classifier (10 нейросетей) · CPU\n"
            "• Видео / Аудио / Текст: C2PA / метаданные / стеганография · CPU"
        ),
        # Labels
        "strength.soft": "Мягче",
        "strength.balanced": "Баланс",
        "strength.strong": "Максимум",
        "vendor.auto": "Авто",
        "vendor.google": "Gemini / Google",
        "vendor.openai": "ChatGPT / OpenAI",
        "vendor.meta": "Meta AI",
        "exif.off": "Выкл",
        "exif.iphone": "iPhone 16 Pro",
        "exif.sony": "Sony A7 IV",
        "corner.tl": "↖️ Верх-лево",
        "corner.tr": "↗️ Верх-право",
        "corner.bl": "↙️ Низ-лево",
        "corner.br": "↘️ Низ-право",
        "corner.bc": "⬇️ Низ-центр",
        "corner.center": "🎯 Центр",
        "state.on": "ВКЛ",
        "state.off": "ВЫКЛ",
        "state.on_lower": "вкл",
        "state.off_lower": "выкл",
        # Menu & navigation buttons
        "btn.settings": "⚙️ Настройки",
        "btn.stats": "📊 Статистика",
        "btn.warmup": "🔥 Прогреть GPU",
        "btn.back_modes": "◀️ Назад к режимам",
        "btn.back": "◀️ Назад",
        "btn.refresh": "🔄 Обновить",
        "btn.menu": "⚙️ Меню",
        "btn.verify_result": "🔍 Проверить результат",
        "btn.upgrade_synthid": "✨ Полная очистка (SynthID)",
        "btn.recompute": "🔄 Пересчитать заново (без кэша)",
        "btn.warm_photo": "🖼 Прогреть Фото / Аудио (L4 · 3.5 мин)",
        "btn.warm_vfast": "⚡ Прогреть Быстрое видео (L4 · 3.5 мин)",
        "btn.warm_vwan": "🎬 Прогреть Видео HD (H100 · 1.2 мин)",
        "btn.set_strength": "🎚 Сила обработки видео: {val}",
        "btn.set_vendor": "🤖 Источник фото: {val}",
        "btn.set_exif": "📸 EXIF камеры на фото: {val}",
        "btn.set_polish": "🎞 Естественная текстура (зерно): {val}",
        "btn.set_photo_out": "📷 Отдача фото: {val}",
        "btn.set_audio": "{icon} Очистка звука в видео: {val}",
        "btn.set_lang": "🌐 Язык / Language: {val}",
        "btn.budget_guard": "🛡 Защита бюджета (${limit}): {state}",
        "photo_out.document_btn": "Как файл (без сжатия)",
        "photo_out.photo_btn": "Как фото (удобнее)",
        "photo_out.document_desc": "как файл без сжатия",
        "photo_out.photo_desc": "как обычное фото Telegram",
        # Welcome, Settings, Stats, Warmup texts
        "welcome.text": (
            "<b>{bot}</b> — очистка фото, видео, аудио и текста от AI-меток\n\n"
            "<b>Режим:</b> {mode_label}\n"
            "{mode_desc}\n\n"
            "<b>Параметры:</b> видео <code>{strength}</code> · фото <code>{vendor}</code> · "
            "EXIF <code>{exif}</code> · зерно <code>{polish}</code> · звук <code>{audio}</code>\n\n"
            "Отправь <b>фото, альбом из галереи, видео, аудио, ZIP с фото, текстовый файл</b> "
            "или <b>ссылку</b> (для файлов &gt;20 МБ).\n"
            "Очистить текст в чате: <code>/text ваш текст</code>"
        ),
        "settings.text": (
            "<b>⚙️ Настройки · {bot}</b>\n\n"
            "• <b>Сила видео:</b> {strength} "
            "(<code>Wan 2.1={wan_s:.2f}</code>, <code>SD-VAE={vae_s:.2f}</code>)\n"
            "• <b>Источник фото:</b> {vendor} "
            "(для ChatGPT сила <code>0.15</code>, для Gemini <code>0.50</code>)\n"
            "• <b>EXIF камеры:</b> {exif} (без GPS, без AI-тегов)\n"
            "• <b>Естественная текстура:</b> {polish_desc}\n"
            "• <b>Отдача фото:</b> {photo_desc}\n"
            "• <b>Звук в видео:</b> {audio_desc}\n"
            "• <b>Язык интерфейса:</b> {lang_label}\n\n"
            "Нажимай на кнопки ниже, чтобы переключить нужный параметр."
        ),
        "settings.polish_on": "включена (лёгкая резкость + микрозерно для фото и Wan 2.1)",
        "settings.polish_off": "выключена",
        "settings.audio_on": "включена (DAC · GPU)",
        "settings.audio_off": "выключена (копия дорожки)",
        "warmup.text": (
            "<b>🔥 Прогрев GPU · {bot}</b>\n\n"
            "Запускает нужный GPU-воркер заранее, пока ты выбираешь файлы в галерее — "
            "после прогрева обработка стартует мгновенно.\n\n"
            "• <b>L4 (Фото / Быстрое видео):</b> держится горячим <b>3.5 мин</b> (~$0.013/мин)\n"
            "• <b>H100 (Видео HD Wan 2.1):</b> держится горячим <b>75 сек</b> (~$0.07/мин)\n"
            "<i>В простое после остывания контейнеры спят за $0/мес.</i>"
        ),
        "stats.guard_on": "ВКЛ (авто-стоп GPU на ${limit})",
        "stats.guard_off": "ВЫКЛ",
        "stats.text": (
            "<b>📊 Статистика {bot} ({month})</b>\n\n"
            "<b>Обработано файлов:</b>\n"
            "• Фото: <b>{photos}</b> (альбомов: <b>{albums}</b>, ZIP: <b>{zips}</b>)\n"
            "• Видео HD (Wan 2.1): <b>{videos_hd}</b>\n"
            "• Видео быстрых (SD-VAE): <b>{videos_fast}</b>\n"
            "• Видимых знаков: <b>{visible_jobs}</b>  |  Стираний области: <b>{erase_jobs}</b>\n"
            "• Аудио: <b>{audios}</b>  |  Текстов: <b>{texts}</b>\n"
            "• Только C2PA: <b>{c2pa_jobs}</b>  |  Проверок: <b>{identify_jobs}</b>\n"
            "• ⚡ Из кэша (0с GPU): <b>{cache_hits}</b>\n\n"
            "<b>Время вычислений:</b>\n"
            "• GPU H100 / A100: <code>{h100_min:.1f} мин</code>\n"
            "• GPU L4 / A10G: <code>{l4_min:.1f} мин</code>\n"
            "• CPU: <code>{cpu_min:.1f} мин</code>\n\n"
            "<b>Оценка расхода Modal:</b> ~<code>${spend:.2f}</code> из <code>${free}/мес</code>\n"
            "<b>Примерный остаток:</b> ~<code>${remaining:.2f}</code>\n"
            "<b>🛡 Защита бюджета:</b> {guard_line}\n"
            "<i>Точный баланс всегда смотри в Modal → Settings → Billing.</i>"
        ),
        # Budget messages
        "budget.blocked": (
            "🛡 <b>Защита бюджета активна:</b> ориентировочный расход за месяц достиг "
            "<b>~${spend:.2f}</b> (порог ${limit} из ${free}).\n\n"
            "GPU-задачи приостановлены, чтобы не уйти в списание с карты.\n"
            "• Бесплатные CPU-режимы (C2PA, проверка, текст, видимые знаки, стирание) работают без ограничений.\n"
            "• Снять лимит можно в /stats."
        ),
        "budget.warn_line": "\n<i>⚠️ Расход за месяц: ~${spend:.2f} из ${free} (/stats)</i>",
        # Identify reports
        "report.img.title": "<b>🔍 Проверка фото · {bot}</b>",
        "report.img.verdict_ai": "обнаружены AI-метки",
        "report.img.verdict_clean": "AI-метаданных не найдено",
        "report.unknown": "не определена",
        "report.img.meta_line": "• <b>Метаданные / C2PA:</b> {verdict}",
        "report.img.platform_line": "• <b>Платформа (по метаданным):</b> {platform}",
        "report.img.marks_line": "• <b>Метки:</b> {wms}",
        "report.img.cls_header": "\n<b>Нейросетевой классификатор (по пикселям):</b>",
        "report.img.cls_source": "• <b>Вероятный источник:</b> <code>{label}{sub}</code> ({conf:.0f}%)",
        "report.img.cls_ai": "• <b>Признаки AI-генерации:</b> {yn} ({prob:.0f}%)",
        "report.yes": "да",
        "report.no_unconfirmed": "не подтверждено",
        "report.no": "нет",
        "report.signals_header": "\n<b>Найденные сигналы:</b>",
        "report.img.tg_compressed": (
            "\n<i>⚠️ Фото пришло со сжатием Telegram — метаданные срезаны мессенджером. "
            "Для полной проверки отправляй «Как файл».</i>"
        ),
        "report.img.synthid_note": "\n<i>Отсутствие C2PA не гарантирует отсутствие скрытого SynthID в пикселях.</i>",
        "report.vid.title": "<b>🔍 Проверка видео · {bot}</b>",
        "report.vid.status": "• <b>Статус:</b> {verdict}",
        "report.vid.platform": "• <b>Платформа:</b> {platform}",
        "report.vid.meta": "• <b>C2PA / AI-метаданные:</b> {found}",
        "report.found": "найдены",
        "report.not_found": "не найдены",
        "report.vid.visible": "• <b>Видимый знак:</b> <code>{mark}</code>",
        "report.fields": "• <b>Поля:</b> <code>{keys}</code>",
        "report.vid.hints": "• <b>Скрытые метки:</b> {hints}",
        "report.vid.note": (
            "\n<i>Скрытый SynthID в кадре и звуке локально не считывается — "
            "для окончательной проверки используй верификатор Google.</i>"
        ),
        "report.aud.title": "<b>🔍 Проверка аудио · {bot}</b>",
        "report.aud.meta": "• <b>AI-метаданные:</b> {val}",
        "report.aud.found_n": "найдены ({n})",
        "report.aud.status": "• <b>Статус аудио-меток:</b> <code>{status}</code>",
        "report.aud.rec": "• <b>Рекомендация:</b> {rec}",
        "report.txt.title": "<b>🔍 Проверка текста · {bot}</b>",
        "report.txt.verdict_ai": "обнаружены скрытые метки / обёртки",
        "report.txt.verdict_clean": "скрытых символов и C2PA не найдено",
        "report.txt.status": "• <b>Статус:</b> {verdict}",
        "report.txt.unicode": "• <b>Скрытых Unicode-символов:</b> <b>{count}</b>",
        "report.txt.c2pa": "• <b>C2PA / AI-обёртки:</b> {yn}",
        "report.txt.signals": "• <b>Сигналы:</b> <code>{sigs}</code>",
        # Runtime & worker messages
        "err.header": "❌ <b>Не удалось обработать файл:</b>\n<code>{msg}</code>",
        "err.access_denied": "⛔ Нет доступа",
        "err.private_bot": "⛔ Бот приватный.",
        "err.too_large": (
            "⚠️ Файл весит <b>{mb:.1f} МБ</b> — Telegram позволяет ботам принимать файлы до <b>20 МБ</b>.\n"
            "💡 Загрузи файл на Google Drive / Dropbox и просто скинь сюда <b>ссылку</b> (бот поддерживает до 250 МБ)."
        ),
        "err.no_media_help": (
            "Отправь <b>фото, альбом, видео, аудио, ZIP с фото, текстовый файл</b> или <b>ссылку</b> (для файлов &gt;20 МБ).\n"
            "Для очистки текста прямо в чате: <code>/text текст</code>. Меню: /start"
        ),
        "err.text_usage": "Напиши <code>/text твой текст</code> или ответь командой <code>/text</code> на нужное сообщение.",
        "err.erase_only_media": "✂️ Режим стирания области работает только для <b>фото и видео</b>. Сменить режим — /start",
        "err.zip_identify_unsupported": "⚠️ Проверка ZIP-архивов не поддерживается — отправь отдельный файл.",
        "err.zip_no_images": "В ZIP-архиве не найдено поддерживаемых изображений.",
        "err.zip_all_failed": "Не удалось обработать ни одно изображение из архива.",
        "err.img_read": "Не удалось прочитать изображение.",
        "err.img_write": "Не удалось сохранить итоговое изображение.",
        "err.coords_oob": "Координаты ({x},{y},{bw},{bh}) выходят за пределы файла ({w}×{h}).",
        "err.staged_missing": "Временный файл по ссылке не найден (попробуй отправить ссылку ещё раз).",
        "err.missing_file_ref": "Отсутствует file_id и staged_path.",
        "cb.mode_updated": "Режим обновлён",
        "cb.lang_updated": "Язык: Русский",
        "cb.expired_file": "Файл устарел, отправь его заново",
        "cb.expired_job": "Задача устарела, отправь файл заново",
        "cb.no_file_check": "Нет файла для проверки",
        "cb.checking": "Проверяю результат...",
        "cb.retry_unavailable": "Повтор недоступен",
        "cb.budget_active": "Защита бюджета активна",
        "cb.retrying": "Повторяю: {val}",
        "cb.unavailable": "Недоступно",
        "cb.starting_full": "Запускаю полную очистку...",
        "cb.recompute_unavailable": "Пересчёт недоступен",
        "cb.recomputing": "Пересчитываю заново...",
        "cb.recomputing_gpu": "Пересчитываю на GPU...",
        "cb.erasing": "Стираю: {zone}",
        "cb.warming_photo": "Прогреваю GPU L4 (Фото)...",
        "cb.warming_vfast": "Прогреваю GPU L4 (Быстрое видео)...",
        "cb.warming_vwan": "Прогреваю GPU H100 (Видео HD)...",
        "cb.budget_guard": "Защита бюджета: {state}",
        "cb.strength": "Сила: {val}",
        "cb.vendor": "Источник: {val}",
        "cb.exif": "EXIF: {val}",
        "cb.polish": "Текстура: {state}",
        "cb.photo_out": "Формат фото обновлён",
        "cb.audio": "Звук: {state}",
        # Status messages
        "status.text_clean": "⏳ <b>{bot}:</b> обрабатываю текст...",
        "status.text_file": "⏳ <b>{bot}:</b> очищаю текстовый файл...",
        "status.identify": "🔍 <b>{bot}:</b> проверяю файл...",
        "status.identify_result": "🔍 <b>{bot}:</b> проверяю очищенный файл...",
        "status.identify_pixels": "🔍 <b>{bot}:</b> определяю источник по пикселям...",
        "status.visible_start": "🧹 <b>{bot}:</b> запускаю удаление видимых знаков...",
        "status.visible_img": "🧹 <b>{bot}:</b> ищу и удаляю видимые знаки (MI-GAN)...",
        "status.visible_vid": "🧹 <b>{bot}:</b> ищу и удаляю видимые знаки на видео (Sora / Kling / Hailuo / Veo / Seedance)...",
        "status.c2pa_start": "🏷 <b>{bot}:</b> удаляю метаданные...",
        "status.erase_start": "✂️ <b>{bot}:</b> запускаю стирание ({zone})...",
        "status.erase_box": "✂️ <b>{bot}:</b> стираю область <code>{box}</code>...",
        "status.erase_img": "✂️ <b>{bot}:</b> стираю область {zone} (MI-GAN)...",
        "status.erase_vid": "✂️ <b>{bot}:</b> стираю область {zone} на видео (MI-GAN)...",
        "status.erase_choose": (
            "✂️ <b>Выбери угол / область для стирания</b>\n"
            "<i>Или просто отправь координаты <code>x,y,w,h</code> (например, <code>1500,1850,400,120</code>).</i>"
        ),
        "status.erase_choose_url": (
            "✂️ <b>Файл скачан ({mb:.1f} МБ). Выбери угол / область для стирания</b>\n"
            "<i>Или отправь координаты <code>x,y,w,h</code> (например, <code>1500,1850,400,120</code>).</i>"
        ),
        "status.url_downloading": "🌐 <b>{bot}:</b> скачиваю файл по ссылке (до 250 МБ)...",
        "status.url_downloaded": "📥 <b>{bot}:</b> файл скачан ({mb:.1f} МБ), запускаю обработку...",
        "status.album_cpu": "📚 <b>{bot}:</b> принял альбом из <b>{n}</b> фото, запускаю обработку...",
        "status.album_gpu": "📚 <b>{bot}:</b> принял альбом из <b>{n}</b> фото, запускаю очистку на одном GPU...",
        "status.album_warming": "📚 <b>{bot}:</b> прогреваю GPU для альбома ({n} фото)...",
        "status.album_progress": "✨ <b>{bot}:</b> очищаю альбом ({idx}/{n})...",
        "status.album_cpu_progress": "📚 <b>{bot}:</b> обрабатываю альбом ({idx}/{n})...",
        "status.zip_cpu_progress": "📦 <b>{bot}:</b> обрабатываю ZIP ({idx}/{n})...",
        "status.zip_gpu_start": "📦 <b>{bot}:</b> принял ZIP-архив, запускаю пакетную очистку фото...",
        "status.zip_gpu_warming": "📦 <b>{bot}:</b> найдено {n} фото, прогреваю GPU...",
        "status.zip_gpu_progress": "✨ <b>{bot}:</b> очищаю фото из ZIP ({idx}/{n})...",
        "status.photo_start": "⏳ <b>{bot}:</b> принял фото, запускаю очистку...",
        "status.photo_cleaning": "✨ <b>{bot}:</b> очищаю фото от C2PA и SynthID...",
        "status.photo_upgrade": "✨ <b>{bot}:</b> запускаю полную очистку фото (C2PA + SynthID)...",
        "status.audio_start": "🔊 <b>{bot}:</b> принял аудио, запускаю очистку...",
        "status.audio_cleaning": "🔊 <b>{bot}:</b> очищаю аудио от метаданных и AI-меток (DAC)...",
        "status.video_hd_start": "⏳ <b>{bot}:</b> принял видео, запускаю HD-очистку...",
        "status.video_fast_start": "⏳ <b>{bot}:</b> принял видео, запускаю быструю очистку...",
        "status.video_retry": "🔁 <b>{bot}:</b> повторяю видео (сила: {strength})...",
        "status.video_prep_hd": "⚙️ <b>{bot}:</b> подготавливаю нейросеть для HD-обработки...",
        "status.video_prep_fast": "⚙️ <b>{bot}:</b> подготавливаю обработчик видео...",
        "status.video_running": "{icon} <b>{bot}:</b> обрабатываю видео ({mode_caption}, сила: {strength})...",
        "status.video_polish": "🎞 <b>{bot}:</b> финальная доработка резкости и текстуры...",
        "status.video_audio": "🔊 <b>{bot}:</b> очищаю аудиодорожку...",
        "status.video_uploading": "📤 <b>{bot}:</b> отправляю готовое видео...",
        "status.recompute": "🔄 <b>{bot}:</b> пересчитываю файл заново...",
        "status.recompute_gpu": "🔄 <b>{bot}:</b> пересчитываю файл заново без кэша...",
        "status.warm_photo_start": "🔥 <b>{bot}:</b> прогреваю GPU Фото / Аудио (L4)...",
        "status.warm_vfast_start": "🔥 <b>{bot}:</b> прогреваю GPU Быстрое видео (SD-VAE, L4)...",
        "status.warm_vwan_start": "🔥 <b>{bot}:</b> прогреваю GPU Видео HD (Wan 2.1, H100)...",
        "status.warm_photo_done": (
            "🔥 <b>GPU Фото / Аудио (L4) прогрет!</b> ({sec:.1f}с)\n"
            "Готов к работе ~3.5 мин — можешь сразу кидать фото, альбомы или ZIP."
        ),
        "status.warm_vfast_done": (
            "🔥 <b>GPU Быстрое видео (SD-VAE, L4) прогрет!</b> ({sec:.1f}с)\n"
            "Готов к работе ~3.5 мин — можешь отправлять видео."
        ),
        "status.warm_vwan_done": (
            "🔥 <b>GPU Видео HD (Wan 2.1, H100) прогрет!</b> ({sec:.1f}с)\n"
            "Готов к работе ~75 сек — отправляй видео прямо сейчас."
        ),
        # Captions & delivery
        "cap.large_file": (
            "{caption}\n\n"
            "📦 Итоговый файл весит <b>{mb:.1f} МБ</b> (больше лимита Telegram 50 МБ).\n"
            "⬇️ <a href=\"{url}\">Скачать готовый файл</a> <i>(ссылка действует 1 час)</i>"
        ),
        "cap.cached_prefix": "⚡ <b>Из кэша (мгновенно · $0 GPU)</b>\n{base}",
        "cap.done_default": "<b>✅ Готово · {bot}</b>",
        "cap.text_done": (
            "<b>✅ Текст очищен · {bot}</b> ({sec:.2f}с)\n"
            "• Удалено скрытых Unicode-символов: <b>{codepoints}</b>\n"
            "• Снятых C2PA/AI-меток: <b>{markers}</b>"
        ),
        "cap.zip_cpu_done": (
            "<b>✅ ZIP обработан · {bot}</b> ({sec:.1f}с)\n"
            "• Изображений: <b>{count}</b>\n"
            "• Режим: {mode_note}{exif_note}"
        ),
        "cap.zip_mode_visible": "Видимые знаки + C2PA (удалено знаков: {n})",
        "cap.zip_mode_c2pa": "Только C2PA / метаданные",
        "cap.zip_gpu_done": (
            "<b>✅ ZIP очищен · {bot}</b> ({sec:.1f}с)\n"
            "• Обработано фото: <b>{count}</b>{fail_note}\n"
            "• Очищено: C2PA + SynthID{exif_note}{warn_note}"
        ),
        "cap.exif_line": "• EXIF камеры: {exif}",
        "cap.fail_line": "\n• Пропущено с ошибкой: <b>{n}</b>",
        "cap.visible_img_done": (
            "<b>✅ Готово · {bot}</b> ({sec:.1f}с)\n"
            "• Видимые знаки: <b>{labels}</b>\n"
            "• AI-метаданные / C2PA очищены{exif_line}"
        ),
        "cap.visible_none_img": "не найдены (очищены метаданные)",
        "cap.visible_vid_done": (
            "<b>✅ Готово · {bot}</b> ({sec:.1f}с)\n"
            "• Удалён видимый знак: <code>{mark}</code> ({removed}/{total} кадров)\n"
            "• AI-метаданные / C2PA очищены"
        ),
        "cap.visible_vid_none": (
            "<b>✅ Готово · {bot}</b> ({sec:.1f}с)\n"
            "• Известных видимых знаков на видео не найдено\n"
            "• C2PA / AI-метаданные очищены (найдено: <b>{n}</b>)"
        ),
        "cap.audio_meta_done": (
            "<b>✅ Метаданные аудио очищены · {bot}</b> ({sec:.1f}с)\n"
            "• C2PA / AI-поля: найдено <b>{before}</b> → осталось <b>{after}</b>\n"
            "• Без перекодирования звука."
        ),
        "cap.c2pa_img_title": "<b>✅ Метаданные очищены · {bot}</b> ({sec:.1f}с)",
        "cap.c2pa_fields": "• C2PA / AI-поля: найдено <b>{before}</b> → осталось <b>{after}</b>",
        "cap.c2pa_synthid_note": "• Скрытый SynthID в этом режиме не изменялся.",
        "cap.tg_doc_tip": "<i>💡 Отправляй фото «Как файл», чтобы Telegram не сжимал его.</i>",
        "cap.tg_doc_tip_quality": "<i>💡 Чтобы сохранить максимум качества, отправляй фото «Как файл».</i>",
        "cap.c2pa_vid_done": (
            "<b>✅ Метаданные видео очищены · {bot}</b> ({sec:.1f}с)\n"
            "• C2PA / AI-поля: найдено <b>{before}</b> → осталось <b>{after}</b>\n"
            "• Без перекодирования (скрытый SynthID не изменялся)."
        ),
        "cap.erase_img_done": (
            "<b>✅ Область стёрта · {bot}</b> ({sec:.1f}с)\n"
            "• Зона: {zone} (<code>{box}</code>)\n"
            "• C2PA / AI-метаданные очищены{exif_line}"
        ),
        "cap.erase_vid_done": (
            "<b>✅ Область стёрта на видео · {bot}</b> ({sec:.1f}с)\n"
            "• Зона: {zone} ({erased}/{total} кадров)\n"
            "• C2PA / AI-метаданные очищены"
        ),
        "cap.album_identify_title": "<b>🔍 Проверка альбома ({n} фото) · {bot}</b>\n",
        "cap.album_identify_ai": "AI",
        "cap.album_identify_clean": "нет C2PA",
        "cap.album_identify_cls": " · нейросеть: <code>{label}</code> ({conf:.0f}%)",
        "cap.album_item_cpu": "✅ Фото {idx}/{n} · {bot}",
        "cap.album_item_gpu": "✅ Фото {idx}/{n} · {bot} ({vendor}{exif})",
        "cap.album_cpu_done": "<b>✅ Альбом готов · {bot}</b> ({sec:.1f}с, фото: <b>{done}/{n}</b>)",
        "cap.album_gpu_done": "<b>✅ Альбом очищен · {bot}</b> ({sec:.1f}с, фото: <b>{done}/{n}</b>{fail}){warn}",
        "cap.album_fail_suffix": ", ошибок: {n}",
        "cap.photo_gpu_title": "<b>✅ Готово · {bot}</b> ({sec:.1f}с)",
        "cap.photo_gpu_cleaned": "• Очищено: C2PA + SynthID (профиль: {vendor})",
        "cap.photo_gpu_meta": "• AI-метаданные: найдено <b>{before}</b> → осталось <b>{after}</b>",
        "cap.photo_gpu_source": "• Источник: {platform}",
        "cap.photo_gpu_visible": "• Видимый знак: удалён ({label})",
        "cap.audio_gpu_done": (
            "<b>✅ Аудио очищено · {bot}</b> ({sec:.1f}с)\n"
            "• Метаданные: найдено <b>{before}</b> → осталось <b>{after}</b>\n"
            "• Обработка звука: {dac_state}{warn}"
        ),
        "cap.audio_dac_on": "выполнена (DAC)",
        "cap.audio_dac_off": "только метаданные",
        "cap.video_mode_hd": "HD",
        "cap.video_mode_fast": "быстрый",
        "cap.video_audio_none": "без звука",
        "cap.video_audio_clean": "очищено",
        "cap.video_audio_copy": "без изменений",
        "cap.video_done_mode": "• Режим: {mode} · сила: {strength} ({w}×{h}, {fps:.0f} fps)",
        "cap.video_done_cleaned": "• Очищено: C2PA + SynthID",
        "cap.video_done_audio": "• Звук: {audio}",
    },
    LANG_EN: {
        # Modes
        "mode.full_hd": "✨ Full Clean HD",
        "mode.full_fast": "⚡ Full Clean (Fast)",
        "mode.visible": "🧹 Remove Visible Mark",
        "mode.erase": "✂️ Erase Corner / Region",
        "mode.c2pa_only": "🏷 Metadata Only (C2PA)",
        "mode.identify": "🔍 Inspect File",
        "desc.full_hd": (
            "Strips C2PA and SynthID from photos, albums, videos, and audio at maximum quality.\n"
            "• Photo / Album / ZIP: SDXL-ZImage · GPU L4 / A10G\n"
            "• Video: Wan 2.1 3D (native resolution & FPS) · GPU H100 / A100\n"
            "• Audio: DAC · GPU L4 / A10G  |  Text: Unicode / C2PA · CPU"
        ),
        "desc.full_fast": (
            "Strips C2PA and SynthID from photos, albums, videos, and audio in faster mode.\n"
            "• Photo / Album / ZIP: SDXL-ZImage · GPU L4 / A10G\n"
            "• Video: SD-VAE HD (native FPS) · GPU L4 / A10G\n"
            "• Audio: DAC · GPU L4 / A10G  |  Text: Unicode / C2PA · CPU"
        ),
        "desc.visible": (
            "Automatically removes known logos (Sora, Kling, Hailuo, Veo, Seedance, Doubao, Gemini) + C2PA.\n"
            "• Photo / Video / Album / ZIP: MI-GAN ONNX · CPU"
        ),
        "desc.erase": (
            "Manually erase any corner or custom box (for non-standard watermarks & captions) + C2PA.\n"
            "• Photo / Video: pick a corner button or send x,y,w,h · MI-GAN ONNX · CPU"
        ),
        "desc.c2pa_only": (
            "Instantly strips C2PA, EXIF, XMP, and hidden Unicode without re-encoding (SynthID stays).\n"
            "• Photo / Video / Audio / Text / Album / ZIP · CPU"
        ),
        "desc.identify": (
            "Checks C2PA, AI metadata, and identifies the likely AI generator from pixels.\n"
            "• Photo: C2PA + Source Classifier (10 AI providers) · CPU\n"
            "• Video / Audio / Text: C2PA / metadata / steganography · CPU"
        ),
        # Labels
        "strength.soft": "Softer",
        "strength.balanced": "Balanced",
        "strength.strong": "Strong",
        "vendor.auto": "Auto",
        "vendor.google": "Gemini / Google",
        "vendor.openai": "ChatGPT / OpenAI",
        "vendor.meta": "Meta AI",
        "exif.off": "Off",
        "exif.iphone": "iPhone 16 Pro",
        "exif.sony": "Sony A7 IV",
        "corner.tl": "↖️ Top-Left",
        "corner.tr": "↗️ Top-Right",
        "corner.bl": "↙️ Bottom-Left",
        "corner.br": "↘️ Bottom-Right",
        "corner.bc": "⬇️ Bottom-Center",
        "corner.center": "🎯 Center",
        "state.on": "ON",
        "state.off": "OFF",
        "state.on_lower": "on",
        "state.off_lower": "off",
        # Menu & navigation buttons
        "btn.settings": "⚙️ Settings",
        "btn.stats": "📊 Stats",
        "btn.warmup": "🔥 Warm up GPU",
        "btn.back_modes": "◀️ Back to Modes",
        "btn.back": "◀️ Back",
        "btn.refresh": "🔄 Refresh",
        "btn.menu": "⚙️ Menu",
        "btn.verify_result": "🔍 Verify Result",
        "btn.upgrade_synthid": "✨ Full Clean (SynthID)",
        "btn.recompute": "🔄 Recompute Fresh (No Cache)",
        "btn.warm_photo": "🖼 Warm up Photo / Audio (L4 · 3.5 min)",
        "btn.warm_vfast": "⚡ Warm up Fast Video (L4 · 3.5 min)",
        "btn.warm_vwan": "🎬 Warm up HD Video (H100 · 1.2 min)",
        "btn.set_strength": "🎚 Video Strength: {val}",
        "btn.set_vendor": "🤖 Photo Source: {val}",
        "btn.set_exif": "📸 Camera EXIF on Photos: {val}",
        "btn.set_polish": "🎞 Natural Texture (Grain): {val}",
        "btn.set_photo_out": "📷 Photo Output: {val}",
        "btn.set_audio": "{icon} Clean Video Audio: {val}",
        "btn.set_lang": "🌐 Language / Язык: {val}",
        "btn.budget_guard": "🛡 Budget Guard (${limit}): {state}",
        "photo_out.document_btn": "As File (Uncompressed)",
        "photo_out.photo_btn": "As Photo (Preview)",
        "photo_out.document_desc": "as uncompressed file",
        "photo_out.photo_desc": "as standard Telegram photo",
        # Welcome, Settings, Stats, Warmup texts
        "welcome.text": (
            "<b>{bot}</b> — remove AI provenance marks from photos, videos, audio &amp; text\n\n"
            "<b>Mode:</b> {mode_label}\n"
            "{mode_desc}\n\n"
            "<b>Options:</b> video <code>{strength}</code> · photo <code>{vendor}</code> · "
            "EXIF <code>{exif}</code> · grain <code>{polish}</code> · audio <code>{audio}</code>\n\n"
            "Send a <b>photo, gallery album, video, audio, ZIP of photos, text file</b>, "
            "or a <b>direct / Drive / Dropbox link</b> (for files &gt;20 MB).\n"
            "Clean inline text: <code>/text your text</code>"
        ),
        "settings.text": (
            "<b>⚙️ Settings · {bot}</b>\n\n"
            "• <b>Video strength:</b> {strength} "
            "(<code>Wan 2.1={wan_s:.2f}</code>, <code>SD-VAE={vae_s:.2f}</code>)\n"
            "• <b>Photo source:</b> {vendor} "
            "(ChatGPT uses <code>0.15</code>, Gemini uses <code>0.50</code>)\n"
            "• <b>Camera EXIF:</b> {exif} (no GPS, zero AI tags)\n"
            "• <b>Natural texture:</b> {polish_desc}\n"
            "• <b>Photo delivery:</b> {photo_desc}\n"
            "• <b>Video audio:</b> {audio_desc}\n"
            "• <b>Interface language:</b> {lang_label}\n\n"
            "Tap the buttons below to toggle any option."
        ),
        "settings.polish_on": "enabled (subtle sharpness + film micro-grain for photos & Wan 2.1)",
        "settings.polish_off": "disabled",
        "settings.audio_on": "enabled (DAC · GPU)",
        "settings.audio_off": "disabled (stream copy)",
        "warmup.text": (
            "<b>🔥 GPU Warmup · {bot}</b>\n\n"
            "Pre-warms the selected GPU worker while you pick files from your gallery, "
            "so processing begins immediately.\n\n"
            "• <b>L4 (Photo / Fast Video):</b> stays warm for <b>3.5 min</b> (~$0.013/min)\n"
            "• <b>H100 (HD Video Wan 2.1):</b> stays warm for <b>75 sec</b> (~$0.07/min)\n"
            "<i>Containers automatically scale to zero ($0/mo) when idle.</i>"
        ),
        "stats.guard_on": "ON (auto-pause GPU at ${limit})",
        "stats.guard_off": "OFF",
        "stats.text": (
            "<b>📊 {bot} Usage ({month})</b>\n\n"
            "<b>Processed items:</b>\n"
            "• Photos: <b>{photos}</b> (albums: <b>{albums}</b>, ZIP: <b>{zips}</b>)\n"
            "• HD Videos (Wan 2.1): <b>{videos_hd}</b>\n"
            "• Fast Videos (SD-VAE): <b>{videos_fast}</b>\n"
            "• Visible Marks: <b>{visible_jobs}</b>  |  Region Erase: <b>{erase_jobs}</b>\n"
            "• Audio: <b>{audios}</b>  |  Text: <b>{texts}</b>\n"
            "• C2PA Only: <b>{c2pa_jobs}</b>  |  Inspections: <b>{identify_jobs}</b>\n"
            "• ⚡ Cache Hits (0s GPU): <b>{cache_hits}</b>\n\n"
            "<b>Compute time:</b>\n"
            "• GPU H100 / A100: <code>{h100_min:.1f} min</code>\n"
            "• GPU L4 / A10G: <code>{l4_min:.1f} min</code>\n"
            "• CPU: <code>{cpu_min:.1f} min</code>\n\n"
            "<b>Estimated Modal spend:</b> ~<code>${spend:.2f}</code> of <code>${free}/mo</code>\n"
            "<b>Estimated remaining:</b> ~<code>${remaining:.2f}</code>\n"
            "<b>🛡 Budget Guard:</b> {guard_line}\n"
            "<i>Check exact balance in Modal → Settings → Billing.</i>"
        ),
        # Budget messages
        "budget.blocked": (
            "🛡 <b>Budget Guard active:</b> estimated monthly spend reached "
            "<b>~${spend:.2f}</b> (threshold ${limit} of ${free}).\n\n"
            "GPU jobs are paused to prevent overage charges.\n"
            "• Free CPU modes (C2PA, Inspect, Text, Visible Marks, Erase) still work normally.\n"
            "• You can toggle the guard in /stats."
        ),
        "budget.warn_line": "\n<i>⚠️ Monthly spend: ~${spend:.2f} of ${free} (/stats)</i>",
        # Identify reports
        "report.img.title": "<b>🔍 Photo Inspection · {bot}</b>",
        "report.img.verdict_ai": "AI provenance marks detected",
        "report.img.verdict_clean": "no AI metadata found",
        "report.unknown": "unknown",
        "report.img.meta_line": "• <b>Metadata / C2PA:</b> {verdict}",
        "report.img.platform_line": "• <b>Platform (metadata):</b> {platform}",
        "report.img.marks_line": "• <b>Watermarks:</b> {wms}",
        "report.img.cls_header": "\n<b>Neural Source Classifier (pixel-level):</b>",
        "report.img.cls_source": "• <b>Likely source:</b> <code>{label}{sub}</code> ({conf:.0f}%)",
        "report.img.cls_ai": "• <b>Synthetic signs:</b> {yn} ({prob:.0f}%)",
        "report.yes": "yes",
        "report.no_unconfirmed": "not confirmed",
        "report.no": "no",
        "report.signals_header": "\n<b>Detected signals:</b>",
        "report.img.tg_compressed": (
            "\n<i>⚠️ Photo was compressed by Telegram — metadata was stripped by the messenger. "
            "Send \"As File\" for a complete check.</i>"
        ),
        "report.img.synthid_note": "\n<i>Absence of C2PA does not guarantee absence of invisible pixel SynthID.</i>",
        "report.vid.title": "<b>🔍 Video Inspection · {bot}</b>",
        "report.vid.status": "• <b>Status:</b> {verdict}",
        "report.vid.platform": "• <b>Platform:</b> {platform}",
        "report.vid.meta": "• <b>C2PA / AI metadata:</b> {found}",
        "report.found": "found",
        "report.not_found": "not found",
        "report.vid.visible": "• <b>Visible mark:</b> <code>{mark}</code>",
        "report.fields": "• <b>Fields:</b> <code>{keys}</code>",
        "report.vid.hints": "• <b>Invisible hints:</b> {hints}",
        "report.vid.note": (
            "\n<i>Invisible video/audio SynthID cannot be read locally — "
            "use Google's official verifier for final confirmation.</i>"
        ),
        "report.aud.title": "<b>🔍 Audio Inspection · {bot}</b>",
        "report.aud.meta": "• <b>AI metadata:</b> {val}",
        "report.aud.found_n": "found ({n})",
        "report.aud.status": "• <b>Audio watermark status:</b> <code>{status}</code>",
        "report.aud.rec": "• <b>Recommendation:</b> {rec}",
        "report.txt.title": "<b>🔍 Text Inspection · {bot}</b>",
        "report.txt.verdict_ai": "hidden markers / wrappers detected",
        "report.txt.verdict_clean": "no hidden characters or C2PA found",
        "report.txt.status": "• <b>Status:</b> {verdict}",
        "report.txt.unicode": "• <b>Hidden Unicode chars:</b> <b>{count}</b>",
        "report.txt.c2pa": "• <b>C2PA / AI wrappers:</b> {yn}",
        "report.txt.signals": "• <b>Signals:</b> <code>{sigs}</code>",
        # Runtime & worker messages
        "err.header": "❌ <b>Failed to process file:</b>\n<code>{msg}</code>",
        "err.access_denied": "⛔ Access denied",
        "err.private_bot": "⛔ This bot is private.",
        "err.too_large": (
            "⚠️ File is <b>{mb:.1f} MB</b> — Telegram limits bot downloads to <b>20 MB</b>.\n"
            "💡 Upload it to Google Drive / Dropbox and send the <b>link</b> here (supports up to 250 MB)."
        ),
        "err.no_media_help": (
            "Send a <b>photo, album, video, audio, ZIP of photos, text file</b>, or a <b>URL</b> (for files &gt;20 MB).\n"
            "Clean inline text: <code>/text your text</code>. Menu: /start"
        ),
        "err.text_usage": "Send <code>/text your text</code> or reply with <code>/text</code> to any message.",
        "err.erase_only_media": "✂️ Region erase mode works for <b>photos and videos</b> only. Switch mode via /start",
        "err.zip_identify_unsupported": "⚠️ Inspecting ZIP archives is not supported — send an individual file.",
        "err.zip_no_images": "No supported images were found in the ZIP archive.",
        "err.zip_all_failed": "Failed to process any image from the ZIP archive.",
        "err.img_read": "Could not read the image file.",
        "err.img_write": "Could not save the output image.",
        "err.coords_oob": "Coordinates ({x},{y},{bw},{bh}) are outside file dimensions ({w}×{h}).",
        "err.staged_missing": "Temporary URL file expired or missing (please send the link again).",
        "err.missing_file_ref": "Missing both file_id and staged_path.",
        "cb.mode_updated": "Mode updated",
        "cb.lang_updated": "Language: English",
        "cb.expired_file": "File expired, please send it again",
        "cb.expired_job": "Job expired, please send the file again",
        "cb.no_file_check": "No file available to verify",
        "cb.checking": "Checking result...",
        "cb.retry_unavailable": "Retry unavailable",
        "cb.budget_active": "Budget Guard active",
        "cb.retrying": "Retrying: {val}",
        "cb.unavailable": "Unavailable",
        "cb.starting_full": "Starting full clean...",
        "cb.recompute_unavailable": "Recompute unavailable",
        "cb.recomputing": "Recomputing fresh...",
        "cb.recomputing_gpu": "Recomputing on GPU...",
        "cb.erasing": "Erasing: {zone}",
        "cb.warming_photo": "Warming GPU L4 (Photo)...",
        "cb.warming_vfast": "Warming GPU L4 (Fast Video)...",
        "cb.warming_vwan": "Warming GPU H100 (HD Video)...",
        "cb.budget_guard": "Budget Guard: {state}",
        "cb.strength": "Strength: {val}",
        "cb.vendor": "Source: {val}",
        "cb.exif": "EXIF: {val}",
        "cb.polish": "Texture: {state}",
        "cb.photo_out": "Photo delivery updated",
        "cb.audio": "Audio: {state}",
        # Status messages
        "status.text_clean": "⏳ <b>{bot}:</b> cleaning text...",
        "status.text_file": "⏳ <b>{bot}:</b> cleaning text file...",
        "status.identify": "🔍 <b>{bot}:</b> inspecting file...",
        "status.identify_result": "🔍 <b>{bot}:</b> verifying cleaned file...",
        "status.identify_pixels": "🔍 <b>{bot}:</b> classifying AI source from pixels...",
        "status.visible_start": "🧹 <b>{bot}:</b> starting visible mark removal...",
        "status.visible_img": "🧹 <b>{bot}:</b> detecting &amp; erasing visible marks (MI-GAN)...",
        "status.visible_vid": "🧹 <b>{bot}:</b> detecting &amp; erasing video watermarks (Sora / Kling / Hailuo / Veo / Seedance)...",
        "status.c2pa_start": "🏷 <b>{bot}:</b> stripping metadata...",
        "status.erase_start": "✂️ <b>{bot}:</b> erasing region ({zone})...",
        "status.erase_box": "✂️ <b>{bot}:</b> erasing box <code>{box}</code>...",
        "status.erase_img": "✂️ <b>{bot}:</b> erasing {zone} (MI-GAN)...",
        "status.erase_vid": "✂️ <b>{bot}:</b> erasing {zone} on video (MI-GAN)...",
        "status.erase_choose": (
            "✂️ <b>Pick a corner / region to erase</b>\n"
            "<i>Or send custom coordinates <code>x,y,w,h</code> (e.g. <code>1500,1850,400,120</code>).</i>"
        ),
        "status.erase_choose_url": (
            "✂️ <b>Downloaded ({mb:.1f} MB). Pick a corner / region to erase</b>\n"
            "<i>Or send custom coordinates <code>x,y,w,h</code> (e.g. <code>1500,1850,400,120</code>).</i>"
        ),
        "status.url_downloading": "🌐 <b>{bot}:</b> downloading from URL (up to 250 MB)...",
        "status.url_downloaded": "📥 <b>{bot}:</b> downloaded ({mb:.1f} MB), starting processing...",
        "status.album_cpu": "📚 <b>{bot}:</b> received album of <b>{n}</b> photos, processing...",
        "status.album_gpu": "📚 <b>{bot}:</b> received album of <b>{n}</b> photos, cleaning on one GPU...",
        "status.album_warming": "📚 <b>{bot}:</b> warming up GPU for album ({n} photos)...",
        "status.album_progress": "✨ <b>{bot}:</b> cleaning album ({idx}/{n})...",
        "status.album_cpu_progress": "📚 <b>{bot}:</b> processing album ({idx}/{n})...",
        "status.zip_cpu_progress": "📦 <b>{bot}:</b> processing ZIP ({idx}/{n})...",
        "status.zip_gpu_start": "📦 <b>{bot}:</b> received ZIP archive, starting batch photo clean...",
        "status.zip_gpu_warming": "📦 <b>{bot}:</b> found {n} photos, warming up GPU...",
        "status.zip_gpu_progress": "✨ <b>{bot}:</b> cleaning ZIP photos ({idx}/{n})...",
        "status.photo_start": "⏳ <b>{bot}:</b> photo received, starting clean...",
        "status.photo_cleaning": "✨ <b>{bot}:</b> stripping C2PA &amp; SynthID from photo...",
        "status.photo_upgrade": "✨ <b>{bot}:</b> running full photo clean (C2PA + SynthID)...",
        "status.audio_start": "🔊 <b>{bot}:</b> audio received, starting clean...",
        "status.audio_cleaning": "🔊 <b>{bot}:</b> stripping audio metadata &amp; watermarks (DAC)...",
        "status.video_hd_start": "⏳ <b>{bot}:</b> video received, starting HD clean...",
        "status.video_fast_start": "⏳ <b>{bot}:</b> video received, starting fast clean...",
        "status.video_retry": "🔁 <b>{bot}:</b> retrying video (strength: {strength})...",
        "status.video_prep_hd": "⚙️ <b>{bot}:</b> preparing HD neural pipeline...",
        "status.video_prep_fast": "⚙️ <b>{bot}:</b> preparing video pipeline...",
        "status.video_running": "{icon} <b>{bot}:</b> processing video ({mode_caption}, strength: {strength})...",
        "status.video_polish": "🎞 <b>{bot}:</b> applying final sharpness &amp; natural grain...",
        "status.video_audio": "🔊 <b>{bot}:</b> cleaning audio track...",
        "status.video_uploading": "📤 <b>{bot}:</b> uploading cleaned video...",
        "status.recompute": "🔄 <b>{bot}:</b> recomputing file fresh...",
        "status.recompute_gpu": "🔄 <b>{bot}:</b> recomputing file fresh (no cache)...",
        "status.warm_photo_start": "🔥 <b>{bot}:</b> warming up Photo / Audio GPU (L4)...",
        "status.warm_vfast_start": "🔥 <b>{bot}:</b> warming up Fast Video GPU (SD-VAE, L4)...",
        "status.warm_vwan_start": "🔥 <b>{bot}:</b> warming up HD Video GPU (Wan 2.1, H100)...",
        "status.warm_photo_done": (
            "🔥 <b>Photo / Audio GPU (L4) is warm!</b> ({sec:.1f}s)\n"
            "Ready for ~3.5 min — send photos, albums, or ZIPs now."
        ),
        "status.warm_vfast_done": (
            "🔥 <b>Fast Video GPU (SD-VAE, L4) is warm!</b> ({sec:.1f}s)\n"
            "Ready for ~3.5 min — send videos now."
        ),
        "status.warm_vwan_done": (
            "🔥 <b>HD Video GPU (Wan 2.1, H100) is warm!</b> ({sec:.1f}s)\n"
            "Ready for ~75 sec — send HD videos right away."
        ),
        # Captions & delivery
        "cap.large_file": (
            "{caption}\n\n"
            "📦 Output file is <b>{mb:.1f} MB</b> (exceeds Telegram's 50 MB upload limit).\n"
            "⬇️ <a href=\"{url}\">Download cleaned file</a> <i>(link valid for 1 hour)</i>"
        ),
        "cap.cached_prefix": "⚡ <b>From cache (instant · $0 GPU)</b>\n{base}",
        "cap.done_default": "<b>✅ Done · {bot}</b>",
        "cap.text_done": (
            "<b>✅ Text cleaned · {bot}</b> ({sec:.2f}s)\n"
            "• Hidden Unicode removed: <b>{codepoints}</b>\n"
            "• C2PA / AI markers removed: <b>{markers}</b>"
        ),
        "cap.zip_cpu_done": (
            "<b>✅ ZIP processed · {bot}</b> ({sec:.1f}s)\n"
            "• Images: <b>{count}</b>\n"
            "• Mode: {mode_note}{exif_note}"
        ),
        "cap.zip_mode_visible": "Visible marks + C2PA (marks removed: {n})",
        "cap.zip_mode_c2pa": "C2PA / metadata only",
        "cap.zip_gpu_done": (
            "<b>✅ ZIP cleaned · {bot}</b> ({sec:.1f}s)\n"
            "• Photos cleaned: <b>{count}</b>{fail_note}\n"
            "• Removed: C2PA + SynthID{exif_note}{warn_note}"
        ),
        "cap.exif_line": "• Camera EXIF: {exif}",
        "cap.fail_line": "\n• Skipped with error: <b>{n}</b>",
        "cap.visible_img_done": (
            "<b>✅ Done · {bot}</b> ({sec:.1f}s)\n"
            "• Visible marks: <b>{labels}</b>\n"
            "• AI metadata / C2PA stripped{exif_line}"
        ),
        "cap.visible_none_img": "none found (metadata stripped)",
        "cap.visible_vid_done": (
            "<b>✅ Done · {bot}</b> ({sec:.1f}s)\n"
            "• Erased visible mark: <code>{mark}</code> ({removed}/{total} frames)\n"
            "• AI metadata / C2PA stripped"
        ),
        "cap.visible_vid_none": (
            "<b>✅ Done · {bot}</b> ({sec:.1f}s)\n"
            "• No known visible watermarks found on video\n"
            "• C2PA / AI metadata stripped (found: <b>{n}</b>)"
        ),
        "cap.audio_meta_done": (
            "<b>✅ Audio metadata stripped · {bot}</b> ({sec:.1f}s)\n"
            "• C2PA / AI fields: found <b>{before}</b> → left <b>{after}</b>\n"
            "• Lossless (no audio re-encoding)."
        ),
        "cap.c2pa_img_title": "<b>✅ Metadata stripped · {bot}</b> ({sec:.1f}s)",
        "cap.c2pa_fields": "• C2PA / AI fields: found <b>{before}</b> → left <b>{after}</b>",
        "cap.c2pa_synthid_note": "• Invisible SynthID was not modified in this mode.",
        "cap.tg_doc_tip": "<i>💡 Send photos \"As File\" so Telegram does not compress them.</i>",
        "cap.tg_doc_tip_quality": "<i>💡 Send photos \"As File\" to preserve maximum quality.</i>",
        "cap.c2pa_vid_done": (
            "<b>✅ Video metadata stripped · {bot}</b> ({sec:.1f}s)\n"
            "• C2PA / AI fields: found <b>{before}</b> → left <b>{after}</b>\n"
            "• Lossless remux (invisible SynthID unchanged)."
        ),
        "cap.erase_img_done": (
            "<b>✅ Region erased · {bot}</b> ({sec:.1f}s)\n"
            "• Zone: {zone} (<code>{box}</code>)\n"
            "• C2PA / AI metadata stripped{exif_line}"
        ),
        "cap.erase_vid_done": (
            "<b>✅ Region erased on video · {bot}</b> ({sec:.1f}s)\n"
            "• Zone: {zone} ({erased}/{total} frames)\n"
            "• C2PA / AI metadata stripped"
        ),
        "cap.album_identify_title": "<b>🔍 Album Inspection ({n} photos) · {bot}</b>\n",
        "cap.album_identify_ai": "AI",
        "cap.album_identify_clean": "no C2PA",
        "cap.album_identify_cls": " · model: <code>{label}</code> ({conf:.0f}%)",
        "cap.album_item_cpu": "✅ Photo {idx}/{n} · {bot}",
        "cap.album_item_gpu": "✅ Photo {idx}/{n} · {bot} ({vendor}{exif})",
        "cap.album_cpu_done": "<b>✅ Album ready · {bot}</b> ({sec:.1f}s, photos: <b>{done}/{n}</b>)",
        "cap.album_gpu_done": "<b>✅ Album cleaned · {bot}</b> ({sec:.1f}s, photos: <b>{done}/{n}</b>{fail}){warn}",
        "cap.album_fail_suffix": ", errors: {n}",
        "cap.photo_gpu_title": "<b>✅ Done · {bot}</b> ({sec:.1f}s)",
        "cap.photo_gpu_cleaned": "• Removed: C2PA + SynthID (profile: {vendor})",
        "cap.photo_gpu_meta": "• AI metadata: found <b>{before}</b> → left <b>{after}</b>",
        "cap.photo_gpu_source": "• Source: {platform}",
        "cap.photo_gpu_visible": "• Visible mark: removed ({label})",
        "cap.audio_gpu_done": (
            "<b>✅ Audio cleaned · {bot}</b> ({sec:.1f}s)\n"
            "• Metadata: found <b>{before}</b> → left <b>{after}</b>\n"
            "• Audio resynthesis: {dac_state}{warn}"
        ),
        "cap.audio_dac_on": "applied (DAC)",
        "cap.audio_dac_off": "metadata only",
        "cap.video_mode_hd": "HD",
        "cap.video_mode_fast": "fast",
        "cap.video_audio_none": "no audio",
        "cap.video_audio_clean": "cleaned",
        "cap.video_audio_copy": "unchanged",
        "cap.video_done_mode": "• Mode: {mode} · strength: {strength} ({w}×{h}, {fps:.0f} fps)",
        "cap.video_done_cleaned": "• Removed: C2PA + SynthID",
        "cap.video_done_audio": "• Audio: {audio}",
    },
}


def t(key: str, lang: str = LANG_RU, **kwargs: Any) -> str:
    """Translate a key into the requested language with safe fallback to English."""
    norm = normalize_lang(lang, fallback=LANG_RU)
    table = TRANSLATIONS.get(norm) or TRANSLATIONS[LANG_EN]
    template = table.get(key)
    if template is None:
        template = TRANSLATIONS[LANG_EN].get(key, key)
    if "bot" not in kwargs and "{bot}" in template:
        kwargs = {**kwargs, "bot": BOT_NAME}
    return template.format(**kwargs) if kwargs else template


def mode_label(mode: str, lang: str = LANG_RU) -> str:
    return t(f"mode.{mode}", lang)


def mode_description(mode: str, lang: str = LANG_RU) -> str:
    return t(f"desc.{mode}", lang)


def strength_label(strength: str, lang: str = LANG_RU) -> str:
    return t(f"strength.{strength}", lang)


def vendor_label(vendor: str, lang: str = LANG_RU) -> str:
    return t(f"vendor.{vendor}", lang)


def exif_label(exif: str, lang: str = LANG_RU) -> str:
    return t(f"exif.{exif}", lang)


def corner_label(corner: str, lang: str = LANG_RU) -> str:
    return t(f"corner.{corner}", lang)
