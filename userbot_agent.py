import os
import asyncio
import logging
import aiohttp
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from openrouter import AsyncOpenRouter

# --- Конфигурация из переменных окружения ---
API_ID = int(os.getenv("TELEGRAM_API_ID"))
API_HASH = os.getenv("TELEGRAM_API_HASH")
SESSION_STRING = os.getenv("SESSION_STRING")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

SOURCE_CHANNEL_ID = int(os.getenv("SOURCE_CHANNEL_ID", "-1003808796392"))
DESTINATION_CHAT_ID = int(os.getenv("DESTINATION_CHAT_ID", "-1003721535372"))

# Модели
TEXT_MODEL = "deepseek/deepseek-v4-flash:free"
IMAGE_MODEL = "google/gemini-2.5-flash-image-preview:free" # Или другая доступная бесплатная

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Инициализация клиентов
client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
openrouter_client = AsyncOpenRouter(api_key=OPENROUTER_API_KEY)

# Хранилище ID последнего обработанного сообщения (чтобы не дублировать)
last_processed_id = 0

async def rewrite_text(text: str) -> str:
    """Переписывает текст в кликбейтном стиле"""
    prompt = f"""
    Перепиши эту новость в ярком, кликбейтном, кратком стиле для Telegram.
    Добавь много эмодзи 🔥🚀💣.
    В конце добавь 3-5 релевантных хештегов.
    Текст новости:
    {text}
    """
    
    try:
        response = await openrouter_client.chat.completions.create(
            model=TEXT_MODEL,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Ошибка при рерайте текста: {e}")
        return f"⚠️ Ошибка обработки текста: {e}\n\nОригинал:\n{text}"

async def process_image(image_path: str, prompt_text: str) -> str:
    """Отправляет картинку в AI для стилизации (киберпанк/неон)"""
    # Примечание: Прямая генерация/редактирование изображений через OpenRouter API 
    # может требовать специфических параметров или поддержки модели.
    # Здесь мы используем подход: отправляем картинку + промпт модели, которая умеет видеть и описывать/менять.
    # Если модель поддерживает image-to-image, она вернет новую картинку. 
    # Если нет - вернет описание. Для полноценного image-to-image лучше использовать специфические эндпоинты,
    # но попробуем универсальный чат с вложением изображения, если модель поддерживает vision.
    
    # ВАЖНО: Большинство бесплатных моделей на OpenRouter сейчас - это текстовые или vision (понимают фото),
    # но не все умеют ВОЗВРАЩАТЬ фото (image-to-image). 
    # Модель google/gemini-2.5-flash-image-preview:free может генерировать, но через API это сложно.
    # Для стабильности в этом коде мы попробуем отправить запрос. Если модель не вернет фото, 
    # мы отправим оригинал с новым описанием.
    
    try:
        with open(image_path, "rb") as f:
            # Читаем как base64 или binary, зависит от библиотеки openrouter python.
            # Библиотека openrouter обычно ожидает URL или base64 в message content.
            import base64
            base64_image = base64.b64encode(f.read()).decode('utf-8')
            
            prompt = f"Сделай стилизацию этого изображения в стиле Киберпанк / Неоновый Арт. Верни результат как изображение."
            
            # Формируем сообщение с картинкой (стандарт OpenAI compatible)
            messages = [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                ]
            }]

            response = await openrouter_client.chat.completions.create(
                model=IMAGE_MODEL,
                messages=messages
            )
            
            # Проверяем, вернула ли модель изображение (обычно в content или special field)
            # Многие модели возвращают просто текст-описание новой картинки.
            # Если модель реально генерирует image-to-image, ответ может содержать url или base64.
            # Пока предположим, что если это текстовая модель с vision, она опишет результат.
            # Для реальной замены картинки нужен сервис типа Replicate или специфический API.
            # В рамках задачи "используй OpenRouter", если модель не вернет картинку, мы вернем None, 
            # и бот отправит оригинал.
            
            # ПРОВЕРКА: Если модель возвращает изображение в формате DALL-E style (url)
            if hasattr(response.choices[0].message, 'images') and response.choices[0].message.images:
                 # Скачиваем новое изображение
                 img_url = response.choices[0].message.images[0].url # Примерный путь
                 async with aiohttp.ClientSession() as session:
                     async with session.get(img_url) as resp:
                         new_img_data = await resp.read()
                         new_path = image_path.replace(".jpg", "_styled.jpg")
                         with open(new_path, "wb") as f_new:
                             f_new.write(new_img_data)
                         return new_path
            
            logger.info("Модель не вернула новое изображение (возможно, только текст). Используем оригинал.")
            return None

    except Exception as e:
        logger.error(f"Ошибка обработки изображения: {e}")
        return None

@client.on(events.NewMessage(chats=[SOURCE_CHANNEL_ID]))
async def handler(event):
    global last_processed_id
    
    # Защита от старых сообщений при старте
    if event.id <= last_processed_id:
        return
    
    last_processed_id = event.id
    logger.info(f"Новое сообщение найдено в канале! ID: {event.id}")

    text_content = event.raw_text
    media = event.media
    photo_path = None
    styled_photo_path = None

    # 1. Обработка текста
    final_text = text_content
    if text_content:
        logger.info("Обработка текста...")
        final_text = await rewrite_text(text_content)
    
    # 2. Обработка изображения
    if media and hasattr(media, 'photo'):
        logger.info("Найдено изображение, скачивание...")
        photo_path = await event.download_media()
        
        if photo_path:
            logger.info("Стилизация изображения...")
            styled_photo_path = await process_image(photo_path, final_text)
            
            # Если стилизация не удалась или модель не вернула фото, используем оригинал
            if not styled_photo_path:
                styled_photo_path = photo_path

    # 3. Отправка результата
    try:
        if styled_photo_path:
            logger.info(f"Отправка фото с подписью в {DESTINATION_CHAT_ID}...")
            await client.send_file(
                DESTINATION_CHAT_ID,
                styled_photo_path,
                caption=final_text,
                parse_mode='md'
            )
            # Чистим файлы
            if os.path.exists(photo_path): os.remove(photo_path)
            if styled_photo_path != photo_path and os.path.exists(styled_photo_path): os.remove(styled_photo_path)
        elif text_content:
            logger.info(f"Отправка текста в {DESTINATION_CHAT_ID}...")
            await client.send_message(DESTINATION_CHAT_ID, final_text, parse_mode='md')
        else:
            logger.warning("Сообщение пустое и без медиа, пропускаем.")
            
    except Exception as e:
        logger.error(f"Ошибка при отправке ответа: {e}")

async def main():
    logger.info("Запуск Userbot агента...")
    logger.info(f"Канал источник: {SOURCE_CHANNEL_ID}")
    logger.info(f"Чат назначения: {DESTINATION_CHAT_ID}")
    
    try:
        await client.start()
        logger.info("Клиент успешно запущен!")
        
        # Проверка доступа
        try:
            entity = await client.get_entity(SOURCE_CHANNEL_ID)
            logger.info(f"Доступ к каналу получен: {entity.title}")
        except Exception as e:
            logger.error(f"Нет доступа к каналу! Убедитесь, что аккаунт подписан. Ошибка: {e}")
            return

        await client.run_until_disconnected()
    except Exception as e:
        logger.error(f"Критическая ошибка запуска: {e}")

if __name__ == "__main__":
    asyncio.run(main())
