"""
scheduler.py — фоновые задачи: автоанализ архива, ежедневная статистика
Запускается вместе с ботом через asyncio
"""
import asyncio
import logging
from datetime import datetime, time
from database import Database
from history_fetcher import HistoryFetcher
from ai_engine import AIEngine

logger = logging.getLogger(__name__)

LEAGUES_TO_FETCH = ["АПЛ", "Ла Лига", "Бундеслига", "Серия А", "РПЛ"]


class Scheduler:
    def __init__(self, db: Database, ai: AIEngine, app=None):
        self.db = db
        self.ai = ai
        self.app = app  # telegram app для отправки уведомлений
        self.history = HistoryFetcher(db)
        self._cache = {}  # кэш архива лиг

    async def run(self):
        """Запускает все фоновые задачи"""
        logger.info("Scheduler started")
        await asyncio.gather(
            self._task_refresh_archive(),
            self._task_daily_retrain(),
            self._task_daily_summary(),
        )

    async def _task_refresh_archive(self):
        """Обновляет архив лиг каждые 24 часа"""
        while True:
            try:
                logger.info("Refreshing league archive...")
                for league in LEAGUES_TO_FETCH:
                    data = await self.history.fetch_league_history(league)
                    if 'error' not in data:
                        self._cache[league] = data
                        logger.info(f"Cached {league}: {data['total_matches']} matches")
                    await asyncio.sleep(5)  # пауза между запросами
                logger.info("Archive refresh complete")
            except Exception as e:
                logger.error(f"Archive refresh error: {e}")
            # Обновляем раз в 24 часа
            await asyncio.sleep(24 * 3600)

    async def _task_daily_retrain(self):
        """Переобучает AI модели всех пользователей каждую ночь в 3:00"""
        while True:
            now = datetime.now()
            # Ждём до 3:00 ночи
            target = now.replace(hour=3, minute=0, second=0, microsecond=0)
            if now >= target:
                target = target.replace(day=target.day + 1)
            wait_seconds = (target - now).total_seconds()
            await asyncio.sleep(wait_seconds)

            try:
                logger.info("Nightly AI retrain started...")
                users = self.db.get_all_users()
                for user_id in users:
                    try:
                        result = self.ai.train(user_id)
                        if 'error' not in result:
                            logger.info(f"Retrained user {user_id}: {result['cv_accuracy']*100:.1f}%")
                    except Exception as e:
                        logger.warning(f"Retrain failed for {user_id}: {e}")
                logger.info("Nightly retrain complete")
            except Exception as e:
                logger.error(f"Nightly retrain error: {e}")

    async def _task_daily_summary(self):
        """Отправляет ежедневную сводку пользователям в 9:00"""
        while True:
            now = datetime.now()
            target = now.replace(hour=9, minute=0, second=0, microsecond=0)
            if now >= target:
                target = target.replace(day=target.day + 1)
            wait_seconds = (target - now).total_seconds()
            await asyncio.sleep(wait_seconds)

            if not self.app:
                continue

            try:
                users = self.db.get_all_users()
                for user_id in users:
                    try:
                        summary = self._build_daily_summary(user_id)
                        if summary:
                            await self.app.bot.send_message(
                                chat_id=user_id,
                                text=summary,
                                parse_mode='Markdown'
                            )
                    except Exception as e:
                        logger.warning(f"Summary send failed for {user_id}: {e}")
            except Exception as e:
                logger.error(f"Daily summary error: {e}")

    def _build_daily_summary(self, user_id: int) -> str:
        """Строим ежедневную сводку"""
        bets = self.db.get_all_bets(user_id)
        if not bets:
            return ""

        # Ставки за последние 7 дней
        from datetime import timedelta
        week_ago = (datetime.now() - timedelta(days=7)).isoformat()
        week_bets = [b for b in bets if b['created_at'] >= week_ago and b['result'] in ('win', 'loss')]

        if not week_bets:
            return ""

        wins = sum(1 for b in week_bets if b['result'] == 'win')
        profit = sum(b['profit'] for b in week_bets)
        wr = wins / len(week_bets) * 100

        profit_icon = "📈" if profit >= 0 else "📉"

        # Ставки в ожидании
        pending = [b for b in bets if b['result'] == 'pending']

        msg = (
            f"☀️ *Доброе утро! Сводка за 7 дней:*\n\n"
            f"🎰 Ставок: *{len(week_bets)}*\n"
            f"✅ Побед: *{wins}* ({wr:.0f}%)\n"
            f"{profit_icon} Прибыль: *{profit:+.0f} ₽*\n"
        )
        if pending:
            msg += f"\n⏳ Ожидают результата: *{len(pending)} ставок*\n"

        # Предупреждение о серии поражений
        results = [b['result'] for b in bets if b['result'] in ('win', 'loss')]
        if results:
            streak = 0
            for r in reversed(results):
                if r == 'loss':
                    streak += 1
                else:
                    break
            if streak >= 4:
                msg += f"\n⚠️ *Внимание:* {streak} поражений подряд!\nРекомендую снизить ставки или взять паузу."

        return msg

    def get_cached_archive(self, league: str) -> dict | None:
        return self._cache.get(league)
