"""
ai_chat.py — умный чат-советник по ставкам на базе Claude API
Общается как эксперт-аналитик, знает контекст пользователя
"""

import aiohttp
import json
import logging
import os
from database import Database
from analyzer import BettingAnalyzer

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Ты — BetMind, умный AI-помощник и эксперт по спортивным ставкам. 
Ты работаешь внутри Telegram-бота для анализа ставок.

Твоя личность:
- Дружелюбный и прямой, общаешься на "ты"
- Говоришь по-русски, кратко и по делу
- Эксперт в беттинге: знаешь математику ставок, value bet, управление банкролом
- Честный — не обещаешь гарантированных выигрышей
- Используешь эмодзи умеренно

Что ты умеешь:
- Анализировать конкретные ставки (дай кэф и событие — скажу своё мнение)
- Объяснять стратегии беттинга
- Помогать с управлением банкролом
- Обсуждать конкретные матчи и лиги
- Считать EV, Kelly criterion, ROI
- Давать персональные советы на основе статистики пользователя

Ограничения:
- Не даёшь гарантий выигрыша
- Напоминаешь о рисках при опасных паттернах (высокие ставки, погоня за убытками)
- Отвечаешь кратко — максимум 3-4 абзаца

Если пользователь спрашивает не о ставках — вежливо перенаправь к теме беттинга."""


class AIChat:
    def __init__(self, db: Database):
        self.db = db
        self.analyzer = BettingAnalyzer(db)
        self.api_key = os.getenv("ANTHROPIC_API_KEY", "")
        self.conversations: dict = {}  # user_id -> история сообщений
        self.session = None

    async def _get_session(self):
        if not self.session or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()

    def _get_user_context(self, user_id: int) -> str:
        """Собираем контекст о пользователе для AI"""
        try:
            stats = self.analyzer.get_statistics(user_id)
            if stats['total_bets'] == 0:
                return "Пользователь новичок, ещё не делал ставок."

            bets = self.db.get_recent_bets(user_id, limit=5)
            recent = ", ".join([f"{b['sport']} {b['odds']} ({b['result']})" for b in bets])

            return (
                f"Статистика пользователя: "
                f"{stats['total_bets']} ставок, "
                f"винрейт {stats['winrate']:.0f}%, "
                f"ROI {stats['roi']:+.1f}%, "
                f"прибыль {stats['total_profit']:+.0f}₽, "
                f"средний кэф {stats['avg_odds']:.2f}. "
                f"Последние ставки: {recent}. "
                f"Серия поражений: {stats['worst_streak']}."
            )
        except Exception:
            return ""

    async def chat(self, user_id: int, message: str) -> str:
        """Отправляем сообщение в Claude и получаем ответ"""
        if not self.api_key:
            return (
                "🤖 *AI чат не настроен*\n\n"
                "Для активации нужен ключ Anthropic API:\n"
                "1. Зарегистрируйся на console.anthropic.com\n"
                "2. Создай API ключ\n"
                "3. Добавь в Railway Variables:\n"
                "`ANTHROPIC_API_KEY=твой_ключ`\n\n"
                "_Бесплатный лимит: $5 на старте_"
            )

        # История диалога (последние 10 сообщений)
        if user_id not in self.conversations:
            self.conversations[user_id] = []

        history = self.conversations[user_id]

        # Добавляем контекст пользователя к первому сообщению
        user_context = self._get_user_context(user_id)
        full_message = message
        if user_context and len(history) == 0:
            full_message = f"[Контекст: {user_context}]\n\n{message}"

        history.append({"role": "user", "content": full_message})

        # Обрезаем историю до 10 сообщений
        if len(history) > 10:
            history = history[-10:]
            self.conversations[user_id] = history

        try:
            session = await self._get_session()
            async with session.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 600,
                    "system": SYSTEM_PROMPT,
                    "messages": history,
                },
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status != 200:
                    error = await resp.text()
                    logger.error(f"Claude API error {resp.status}: {error}")
                    return "😔 Не удалось получить ответ. Попробуй позже."

                data = await resp.json()

            reply = data["content"][0]["text"]
            history.append({"role": "assistant", "content": reply})
            return reply

        except aiohttp.ClientTimeout:
            return "⏱ Время ожидания истекло. Попробуй снова."
        except Exception as e:
            logger.error(f"AI chat error: {e}")
            return "😔 Произошла ошибка. Попробуй позже."

    def clear_history(self, user_id: int):
        """Очищаем историю диалога"""
        self.conversations.pop(user_id, None)
