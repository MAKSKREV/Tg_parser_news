import asyncio
import logging
import os
import aiohttp
from telethon import TelegramClient, events
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument

# --- КОНФИГУРАЦИЯ ---
API_ID = 25316255
API_HASH = 'caacc56333e6d2445732ea75eddd56e5'
PHONE = '+79686041007'  # Ваш номер

SOURCE_CHANNEL = -1003969868108  # Канал откуда брать новости
TARGET_CHAT = -1003780268513     # Куда отправлять результат

# Вставьте ваш актуальный ключ сюда, если он изменился
OPENROUTER_API_KEY = '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'

# Используем стабильные бесплатные модели
# Список актуальных бесплатных моделей: https://openrouter.ai/models?q=free
TEXT_MODEL = 'google/gemma-2-9b-it:free' 
IMAGE_MODEL = 'google/gemma-2-9b-it:free'  # Для анализа изображений тоже используем надежную модель

SESSION_NAME = 'my_userbot_session'

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("userbot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Инициализация клиентов
client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

# OpenRouter клиент через aiohttp (так как библиотека не установлена или несовместима)
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
HEADERS = {
    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
    "Content-Type": "application/json",
    "HTTP-Referer": "https://github.com/your-app",  # Опционально
}

# Хранилище ID последнего обработанного сообщения
last_message_id = 0

async def rewrite_text(text: str) -> str:
    """Переписывает текст в кликбейтном стиле"""
    prompt = f"""
    Перепиши эту новость в ярком, кликбейтном, кратком стиле для Telegram.
    Добавь много эмодзи 🔥😱🚀.
    Добавь 3-5 релевантных хештегов в конце.
    Текст новости:
    {text}
    """
    
    payload = {
        "model": TEXT_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 300
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(OPENROUTER_URL, json=payload, headers=HEADERS) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data['choices'][0]['message']['content']
                else:
                    error_text = await resp.text()
                    raise Exception(f"HTTP {resp.status}: {error_text}")
    except Exception as e:
        logger.error(f"Ошибка при переписывании текста: {e}")
        return f"⚠️ Ошибка обработки текста: {e}\n\nОригинал:\n{text}"

async def process_image(image_path: str, prompt_text: str) -> str:
    """Стилизует изображение (киберпанк/неон)"""
    # Примечание: OpenRouter API для изображений может отличаться в зависимости от модели.
    # Здесь используется примерный вызов для генерации/редактирования.
    # Если модель требует specific payload, его нужно адаптировать.
    # Для gemini-2.5-flash-image-preview часто нужен мультимодальный запрос.
    
    try:
        # Читаем изображение в base64 (если требуется моделью) или передаем путь
        # В данном случае попробуем отправить запрос на "стилизацию" через текстовый промпт с картинкой
        # Так как прямое редактирование "image-to-image" через стандартный chat completion 
        # зависит от конкретной реализации модели на OpenRouter.
        
        # Попытка использовать мультимодальность (если модель поддерживает)
        with open(image_path, "rb") as f:
            import base64
            image_data = base64.b64encode(f.read()).decode('utf-8')
            
        prompt = f"Сделай стилизацию этого изображения в стиле киберпанк/неон/арт. Сделай его ярким и футуристичным. {prompt_text}"
        
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_data}"}}
                ]
            }
        ]

        payload = {
            "model": IMAGE_MODEL,
            "messages": messages,
            "max_tokens": 500
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(OPENROUTER_URL, json=payload, headers=HEADERS) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    result_text = data['choices'][0]['message']['content']
                else:
                    error_text = await resp.text()
                    logger.error(f"HTTP ошибка от API изображений: {resp.status} - {error_text}")
                    return None
        
        logger.info(f"Ответ от модели изображения: {result_text}")
        
        # Если модель вернула URL новой картинки (некоторые модели так делают)
        if "http" in result_text and ("png" in result_text or "jpg" in result_text):
            # Парсим URL (упрощенно)
            import re
            urls = re.findall(r'http[s]?://\S+', result_text)
            if urls:
                return urls[0] # Возвращаем ссылку на новую картинку
        
        return None # Значит, новой картинки нет, используем оригинал

    except Exception as e:
        logger.error(f"Ошибка при обработке изображения: {e}")
        return None

@client.on(events.NewMessage(chats=[SOURCE_CHANNEL]))
async def handler(event):
    global last_message_id
    
    msg = event.message
    if msg.id <= last_message_id:
        return
    
    logger.info(f"Получено новое сообщение ID: {msg.id}")
    last_message_id = msg.id
    
    original_text = msg.text or ""
    media = msg.media
    new_image_path = None
    final_media_to_send = None
    
    # 1. Обработка текста
    if not original_text and not media:
        logger.warning("Пустое сообщение без текста и медиа, пропускаем.")
        return

    rewritten_text = ""
    if original_text:
        logger.info("Обработка текста...")
        rewritten_text = await rewrite_text(original_text)
    
    # 2. Обработка изображения
    if media:
        if isinstance(media, MessageMediaPhoto):
            photo_path = await client.download_media(media, file='downloads/')
            logger.info(f"Фото скачано: {photo_path}")
            
            # Пробуем стилизовать
            new_img_url = await process_image(photo_path, rewritten_text)
            
            if new_img_url and new_img_url.startswith("http"):
                # Если модель сгенерировала новое фото (ссылка)
                # Нужно скачать его, чтобы отправить в ТГ
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    async with session.get(new_img_url) as resp:
                        if resp.status == 200:
                            new_image_path = 'downloads/styled_' + os.path.basename(photo_path)
                            with open(new_image_path, 'wb') as f:
                                f.write(await resp.read())
                            final_media_to_send = new_image_path
                            logger.info("Новое стилизованное фото сохранено.")
                        else:
                            final_media_to_send = photo_path # Фоллбэк на оригинал
            else:
                final_media_to_send = photo_path # Фоллбэк на оригинал
                
        elif isinstance(media, MessageMediaDocument):
            # Если это документ (возможно фото или стикер)
            if media.document.mime_type.startswith('image/'):
                final_media_to_send = await client.download_media(media, file='downloads/')
                logger.info("Документ-изображение скачан.")
            else:
                logger.warning("Неподдерживаемый тип документа.")

    # 3. Отправка результата
    try:
        if final_media_to_send:
            await client.send_file(
                TARGET_CHAT,
                final_media_to_send,
                caption=rewritten_text,
                force_document=False
            )
            logger.info("Результат (фото + текст) отправлен.")
        elif rewritten_text:
            await client.send_message(TARGET_CHAT, rewritten_text)
            logger.info("Результат (только текст) отправлен.")
        else:
            logger.warning("Нечего отправлять (нет текста и медиа).")
            
    except Exception as e:
        logger.error(f"Ошибка при отправке сообщения: {e}")

async def main():
    await client.start(phone=PHONE)
    logger.info("Клиент запущен и авторизован!")
    
    # Получаем последнее сообщение, чтобы не обрабатывать старые
    try:
        history = await client.get_messages(SOURCE_CHANNEL, limit=1)
        if history:
            last_message_id = history[0].id
            logger.info(f"Начальный ID последнего сообщения: {last_message_id}")
    except Exception as e:
        logger.error(f"Не удалось получить историю сообщений: {e}")

    await client.run_until_disconnected()

if __name__ == '__main__':
    if not os.path.exists('downloads'):
        os.makedirs('downloads')
    
    try:
        client.loop.run_until_complete(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем.")
