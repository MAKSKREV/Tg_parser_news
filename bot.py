#!/usr/bin/env python3
"""
Telegram News Parser Agent
Парсит новости из канала, обрабатывает текст через OpenRouter AI,
стилизует изображения и отправляет результат в целевой чат.
"""

import asyncio
import logging
import io
import base64
from typing import Optional, Tuple
from datetime import datetime

import aiohttp
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import FSInputFile, URLInputFile

# ==================== КОНФИГУРАЦИЯ ====================

# Telegram Bot Token (нужно получить от @BotFather)
TELEGRAM_BOT_TOKEN = "8360819683:AAETJcukNkQU18PbsvRtIGe0Gti5KWcM-_E"

# ID каналов
SOURCE_CHANNEL_ID = -1003808796392  # Откуда парсим новости
DESTINATION_CHAT_ID = -1003721535372  # Куда отправляем результат

# OpenRouter API
OPENROUTER_API_KEY = "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"
OPENROUTER_TEXT_MODEL = "deepseek/deepseek-v4-flash:free"
OPENROUTER_IMAGE_MODEL = "google/gemini-2.5-flash-image-preview:free"

# Интервал опроса в секундах
POLL_INTERVAL = 30

# ==================== ЛОГИРОВАНИЕ ====================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# ==================== OPENROUTER CLIENT ====================

class OpenRouterClient:
    """Клиент для работы с OpenRouter API"""
    
    def __init__(self, api_key: str, session: aiohttp.ClientSession):
        self.api_key = api_key
        self.session = session
        self.base_url = "https://openrouter.ai/api/v1"
    
    async def rewrite_text(self, text: str) -> str:
        """
        Переписывает текст в ярком, кликбейтном стиле с хештегами
        """
        prompt = f"""Перепиши эту новость в ярком, кликбейтном, кратком стиле. 
Добавь эмодзи и хештеги в конце. Сделай текст захватывающим и вирусным!

Исходный текст:
{text}

Ответ должен быть на русском языке, не более 150 слов."""

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/tg-parser-news",
            "X-Title": "TG News Parser"
        }
        
        payload = {
            "model": OPENROUTER_TEXT_MODEL,
            "messages": [
                {"role": "system", "content": "Ты вирусный контент-мейкер. Твоя задача - делать тексты яркими, кликбейтными и цепляющими."},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 500
        }
        
        try:
            async with self.session.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=60)
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    rewritten = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    logger.info(f"Текст успешно переписан моделью {OPENROUTER_TEXT_MODEL}")
                    return rewritten if rewritten else text
                else:
                    error_text = await response.text()
                    logger.error(f"Ошибка OpenRouter (текст): {response.status} - {error_text}")
                    return text
        except Exception as e:
            logger.error(f"Исключение при переписывании текста: {e}")
            return text
    
    async def stylize_image(self, image_bytes: bytes, description: str = "") -> Optional[bytes]:
        """
        Стилизует изображение в киберпанк/неон стиле
        Возвращает стилизованное изображение или None если ошибка
        """
        # Кодируем изображение в base64
        image_base64 = base64.b64encode(image_bytes).decode('utf-8')
        
        prompt = f"""Transform this image into a cyberpunk/neon art style. 
Add vibrant neon colors, futuristic elements, glowing effects, and a dark atmospheric background.
Make it look like a digital art masterpiece.

Additional context: {description if description else 'News image'}"""

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/tg-parser-news",
            "X-Title": "TG News Parser"
        }
        
        # Используем модель для генерации/редактирования изображений
        payload = {
            "model": OPENROUTER_IMAGE_MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_base64}"
                            }
                        }
                    ]
                }
            ],
            "max_tokens": 4096
        }
        
        try:
            async with self.session.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=120)
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    
                    # Проверяем, есть ли в ответе изображение
                    # Некоторые модели возвращают URL или base64 изображения
                    if "data:image" in content or "http" in content:
                        logger.info(f"Изображение успешно стилизовано моделью {OPENROUTER_IMAGE_MODEL}")
                        # Извлекаем URL изображения из ответа
                        import re
                        img_match = re.search(r'(data:image[^"\s]+|https?://[^\s"]+\.(?:png|jpg|jpeg|gif|webp))', content)
                        if img_match:
                            img_url = img_match.group(1)
                            # Скачиваем стилизованное изображение
                            async with self.session.get(img_url, timeout=aiohttp.ClientTimeout(total=60)) as img_resp:
                                if img_resp.status == 200:
                                    return await img_resp.read()
                    
                    logger.warning("Модель не вернула изображение, используем оригинал")
                    return None
                else:
                    error_text = await response.text()
                    logger.error(f"Ошибка OpenRouter (изображение): {response.status} - {error_text}")
                    return None
        except Exception as e:
            logger.error(f"Исключение при стилизации изображения: {e}")
            return None


# ==================== TELEGRAM PARSER ====================

class TelegramNewsParser:
    """Парсер новостей из Telegram канала"""
    
    def __init__(self, bot: Bot, session: aiohttp.ClientSession):
        self.bot = bot
        self.session = session
        self.last_message_id = 0
    
    async def get_latest_post(self) -> Optional[dict]:
        """
        Получает последний пост из канала
        Возвращает dict с полями: text, photo_bytes, message_id
        """
        try:
            bot_me = await self.bot.get_me()
            
            # Проверяем статус бота в канале
            chat_member = await self.bot.get_chat_member(SOURCE_CHANNEL_ID, bot_me.id)
            logger.info(f"Статус бота в канале: {chat_member.status}")
            
            if chat_member.status not in ["administrator", "member"]:
                logger.error("Бот не имеет доступа к каналу")
                return None
            
            # Для получения сообщений из канала используем трюк:
            # Отправляем тестовое сообщение и смотрим его ID, затем получаем предыдущее
            # Или используем прямой HTTP запрос для получения последнего сообщения
            
            # Создаём временное сообщение чтобы узнать текущий max_message_id
            test_msg = await self.bot.send_message(
                chat_id=SOURCE_CHANNEL_ID,
                text="🔄 Parser check...",
                disable_notification=True
            )
            current_max_id = test_msg.message_id
            logger.info(f"Текущий max_message_id в канале: {current_max_id}")
            
            # Удаляем тестовое сообщение
            try:
                await self.bot.delete_message(chat_id=SOURCE_CHANNEL_ID, message_id=current_max_id)
            except:
                pass
            
            # Теперь проверяем последнее настоящее сообщение (current_max_id - 1)
            last_msg_id = current_max_id - 1
            
            # Если это первый запуск, просто запоминаем ID
            if self.last_message_id == 0:
                logger.info(f"Первый запуск. Последнее сообщение ID: {last_msg_id}")
                self.last_message_id = last_msg_id
                return None
            
            # Если есть новое сообщение (last_msg_id > self.last_message_id)
            if last_msg_id > self.last_message_id:
                logger.info(f"Найдено новое сообщение! ID: {last_msg_id}, было: {self.last_message_id}")
                
                # Пробуем получить сообщение через forward в сохранённые сообщения бота
                try:
                    fwd = await self.bot.forward_message(
                        chat_id=bot_me.id,
                        from_chat_id=SOURCE_CHANNEL_ID,
                        message_id=last_msg_id
                    )
                    
                    # Парсим пересланное сообщение
                    result = await self._parse_message(fwd)
                    self.last_message_id = last_msg_id
                    
                    # Удаляем пересланное сообщение из чата с ботом
                    try:
                        await self.bot.delete_message(chat_id=bot_me.id, message_id=fwd.message_id)
                    except:
                        pass
                    
                    return result
                    
                except Exception as e:
                    logger.error(f"Ошибка при пересылке сообщения: {e}")
                    # Фоллбэк: просто обновляем last_message_id без обработки
                    self.last_message_id = last_msg_id
                    return None
            else:
                logger.debug(f"Новых сообщений нет. Последний ID: {last_msg_id}")
                self.last_message_id = last_msg_id
                return None
            
        except Exception as e:
            logger.error(f"Ошибка при получении поста: {e}", exc_info=True)
            return None
    
    async def _parse_message(self, message: types.Message) -> dict:
        """Парсит сообщение и извлекает текст и изображение"""
        result = {
            "text": message.text or message.caption or "",
            "photo_bytes": None,
            "message_id": message.message_id,
            "date": message.date
        }
        
        # Пробуем получить фото
        if message.photo:
            # Берем фото наилучшего качества
            photo = message.photo[-1]
            file = await self.bot.get_file(photo.file_id)
            file_bytes = await self.bot.download_file(file.file_path)
            result["photo_bytes"] = file_bytes.read() if hasattr(file_bytes, 'read') else file_bytes
        
        return result


# ==================== MAIN BOT LOGIC ====================

class NewsAgent:
    """Основной класс агента"""
    
    def __init__(self, bot_token: str):
        self.bot = Bot(token=bot_token)
        self.dp = Dispatcher()
        self.session: Optional[aiohttp.ClientSession] = None
        self.openrouter: Optional[OpenRouterClient] = None
        self.parser: Optional[TelegramNewsParser] = None
        self.processed_messages = set()
    
    async def init_session(self):
        """Инициализирует HTTP сессию и клиенты"""
        self.session = aiohttp.ClientSession()
        self.openrouter = OpenRouterClient(OPENROUTER_API_KEY, self.session)
        self.parser = TelegramNewsParser(self.bot, self.session)
        logger.info("Сессия и клиенты инициализированы")
    
    async def close_session(self):
        """Закрывает HTTP сессию"""
        if self.session:
            await self.session.close()
            logger.info("HTTP сессия закрыта")
    
    async def process_news(self):
        """Основной цикл обработки новостей"""
        logger.info("Запуск цикла обработки новостей...")
        
        while True:
            try:
                # Получаем последний пост
                post = await self.parser.get_latest_post()
                
                if post and post["message_id"] not in self.processed_messages:
                    logger.info(f"Обработка нового поста #{post['message_id']}")
                    
                    # Обрабатываем текст через AI
                    original_text = post["text"]
                    if original_text:
                        logger.info("Переписывание текста через OpenRouter...")
                        rewritten_text = await self.openrouter.rewrite_text(original_text)
                        logger.info(f"Переписанный текст: {rewritten_text[:100]}...")
                    else:
                        rewritten_text = ""
                    
                    # Обрабатываем изображение если есть
                    styled_photo = None
                    if post["photo_bytes"]:
                        logger.info("Стилизация изображения через OpenRouter...")
                        styled_photo = await self.openrouter.stylize_image(
                            post["photo_bytes"],
                            original_text[:200] if original_text else ""
                        )
                        
                        if styled_photo:
                            logger.info("Изображение успешно стилизовано")
                        else:
                            logger.warning("Не удалось стилизовать изображение, используем оригинал")
                            styled_photo = post["photo_bytes"]
                    
                    # Отправляем результат в целевой чат
                    await self.send_result(rewritten_text, styled_photo)
                    
                    # Добавляем в обработанные
                    self.processed_messages.add(post["message_id"])
                    
                    # Очищаем старые записи (храним последние 1000)
                    if len(self.processed_messages) > 1000:
                        self.processed_messages = set(list(self.processed_messages)[-1000:])
                
                await asyncio.sleep(POLL_INTERVAL)
                
            except Exception as e:
                logger.error(f"Ошибка в цикле обработки: {e}")
                await asyncio.sleep(POLL_INTERVAL)
    
    async def send_result(self, text: str, photo: Optional[bytes]):
        """Отправляет результат в целевой чат"""
        try:
            if photo:
                # Отправляем как фото с подписью
                photo_io = io.BytesIO(photo)
                photo_io.name = "news_image.jpg"
                
                await self.bot.send_photo(
                    chat_id=DESTINATION_CHAT_ID,
                    photo=FSInputFile(photo_io),
                    caption=text if text else "📰 Новая новость!",
                    parse_mode=ParseMode.HTML
                )
                logger.info(f"Отправлено фото с подписью в чат {DESTINATION_CHAT_ID}")
            elif text:
                # Отправляем только текст
                await self.bot.send_message(
                    chat_id=DESTINATION_CHAT_ID,
                    text=text,
                    parse_mode=ParseMode.HTML
                )
                logger.info(f"Отправлен текст в чат {DESTINATION_CHAT_ID}")
            else:
                logger.warning("Нет текста или изображения для отправки")
                
        except Exception as e:
            logger.error(f"Ошибка при отправке результата: {e}")
    
    async def start_command(self, message: types.Message):
        """Обработчик команды /start"""
        await message.answer(
            "🤖 TG News Parser запущен!\n\n"
            f"Парсинг канала: {SOURCE_CHANNEL_ID}\n"
            f"Отправка в чат: {DESTINATION_CHAT_ID}\n"
            f"Интервал опроса: {POLL_INTERVAL} сек\n\n"
            "Бот работает в фоновом режиме."
        )
    
    async def status_command(self, message: types.Message):
        """Обработчик команды /status"""
        await message.answer(
            f"📊 Статус:\n"
            f"✅ Бот активен\n"
            f"📝 Обработано сообщений: {len(self.processed_messages)}\n"
            f"🕐 Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
    
    def setup_handlers(self):
        """Настраивает обработчики команд"""
        self.dp.message(Command("start"))(self.start_command)
        self.dp.message(Command("status"))(self.status_command)
        logger.info("Обработчики команд настроены")
    
    async def run(self):
        """Запускает бота"""
        try:
            await self.init_session()
            self.setup_handlers()
            
            logger.info("=" * 50)
            logger.info("TG News Parser запускается...")
            logger.info(f"Source Channel: {SOURCE_CHANNEL_ID}")
            logger.info(f"Destination Chat: {DESTINATION_CHAT_ID}")
            logger.info(f"Text Model: {OPENROUTER_TEXT_MODEL}")
            logger.info(f"Image Model: {OPENROUTER_IMAGE_MODEL}")
            logger.info("=" * 50)
            
            # Запускаем polling для обработки команд
            polling_task = asyncio.create_task(
                self.dp.start_polling(self.bot)
            )
            
            # Запускаем основной цикл обработки новостей
            news_task = asyncio.create_task(self.process_news())
            
            # Ждем завершения задач
            await asyncio.gather(polling_task, news_task)
            
        except KeyboardInterrupt:
            logger.info("Получен сигнал остановки")
        except Exception as e:
            logger.error(f"Критическая ошибка: {e}")
        finally:
            await self.close_session()
            await self.bot.session.close()
            logger.info("Бот остановлен")


# ==================== ENTRY POINT ====================

async def main():
    """Точка входа"""
    if TELEGRAM_BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        print("❌ ОШИБКА: Укажите ваш Telegram Bot Token в переменной TELEGRAM_BOT_TOKEN")
        print("Получите токен у @BotFather в Telegram")
        return
    
    agent = NewsAgent(TELEGRAM_BOT_TOKEN)
    await agent.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nБот остановлен пользователем")
