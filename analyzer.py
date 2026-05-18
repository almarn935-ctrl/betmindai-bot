from typing import Optional
from database import Database


class BettingAnalyzer:
    def __init__(self, db: Database):
        self.db = db

    def get_statistics(self, user_id: int) -> dict:
        bets = self.db.get_all_bets(user_id)
        finished = [b for b in bets if b['result'] in ('win', 'loss', 'refund')]
        wins = [b for b in bets if b['result'] == 'win']
        losses = [b for b in bets if b['result'] == 'loss']
        refunds = [b for b in bets if b['result'] == 'refund']
        pending = [b for b in bets if b['result'] == 'pending']

        total_staked = sum(b['amount'] for b in finished if b['result'] != 'refund')
        total_profit = sum(b['profit'] for b in finished)
        decided = [b for b in bets if b['result'] in ('win', 'loss')]

        roi = (total_profit / total_staked * 100) if total_staked > 0 else 0
        winrate = (len(wins) / len(decided) * 100) if decided else 0
        avg_odds = (sum(b['odds'] for b in decided) / len(decided)) if decided else 0
        avg_stake = (total_staked / len(finished)) if finished else 0

        best_streak, worst_streak = self._calc_streaks(user_id)

        return {
            'total_bets': len(bets),
            'wins': len(wins),
            'losses': len(losses),
            'refunds': len(refunds),
            'pending': len(pending),
            'total_staked': total_staked,
            'total_profit': total_profit,
            'roi': roi,
            'winrate': winrate,
            'avg_odds': avg_odds,
            'avg_stake': avg_stake,
            'best_streak': best_streak,
            'worst_streak': worst_streak,
        }

    def _calc_streaks(self, user_id: int):
        results = self.db.get_streak_data(user_id)
        best = worst = cur_win = cur_loss = 0
        for r in results:
            if r == 'win':
                cur_win += 1
                cur_loss = 0
                best = max(best, cur_win)
            else:
                cur_loss += 1
                cur_win = 0
                worst = max(worst, cur_loss)
        return best, worst

    def get_forecast(self, user_id: int) -> Optional[str]:
        bets = self.db.get_all_bets(user_id)
        decided = [b for b in bets if b['result'] in ('win', 'loss')]
        if len(decided) < 10:
            return None

        wins = [b for b in decided if b['result'] == 'win']
        winrate = len(wins) / len(decided)
        avg_odds = sum(b['odds'] for b in decided) / len(decided)
        total_profit = sum(b['profit'] for b in decided)
        total_staked = sum(b['amount'] for b in decided if b['result'] != 'refund')
        roi = (total_profit / total_staked * 100) if total_staked > 0 else 0

        # Паттерны по коэффициентам
        odds_stats = self.db.get_stats_by_odds_range(user_id)
        best_odds_range = None
        best_range_winrate = 0
        for o in odds_stats:
            if o['total'] >= 3 and o['winrate'] > best_range_winrate:
                best_range_winrate = o['winrate']
                best_odds_range = o['odds_range']

        # Лучший вид спорта
        sport_stats = self.db.get_stats_by_sport(user_id)
        best_sport = None
        best_sport_roi = -999
        for s in sport_stats:
            if s['total'] >= 3 and s['total_staked'] > 0:
                sport_roi = (s['total_profit'] / s['total_staked']) * 100
                if sport_roi > best_sport_roi:
                    best_sport_roi = sport_roi
                    best_sport = s['sport']

        # Последние 10 ставок — тренд
        recent = decided[-10:]
        recent_wins = sum(1 for b in recent if b['result'] == 'win')
        recent_winrate = recent_wins / len(recent) * 100

        # Серии
        results = self.db.get_streak_data(user_id)
        current_streak_type = None
        current_streak_len = 0
        if results:
            current_streak_type = results[-1]
            for r in reversed(results):
                if r == current_streak_type:
                    current_streak_len += 1
                else:
                    break

        # Строим прогноз
        lines = ["🔮 *Прогноз и рекомендации*\n"]

        # Общая оценка
        if roi > 10:
            lines.append("📈 *Общая оценка: Отличная*")
            lines.append("Твоя стратегия работает прибыльно. Так держать!\n")
        elif roi > 0:
            lines.append("📊 *Общая оценка: Удовлетворительная*")
            lines.append("Ты в плюсе, но есть куда расти.\n")
        elif roi > -10:
            lines.append("⚠️ *Общая оценка: Слабая*")
            lines.append("Ты в небольшом минусе. Нужна корректировка стратегии.\n")
        else:
            lines.append("🔴 *Общая оценка: Критическая*")
            lines.append("Серьёзные убытки. Рекомендую пересмотреть подход.\n")

        # Тренд
        lines.append("📉 *Последние 10 ставок:*")
        if recent_winrate > winrate * 100 + 10:
            lines.append(f"Ты на подъёме! Последние ставки — {recent_winrate:.0f}% побед (лучше среднего).\n")
        elif recent_winrate < winrate * 100 - 10:
            lines.append(f"Наблюдается спад: {recent_winrate:.0f}% побед в последних ставках.\n")
        else:
            lines.append(f"Стабильный уровень: {recent_winrate:.0f}% побед в последних ставках.\n")

        # Серия
        if current_streak_len >= 3:
            if current_streak_type == 'loss':
                lines.append(f"⚠️ *Внимание:* У тебя серия из {current_streak_len} проигрышей подряд.")
                lines.append("Рекомендую снизить суммы ставок или взять паузу.\n")
            elif current_streak_type == 'win':
                lines.append(f"🔥 *Горячая серия:* {current_streak_len} побед подряд!")
                lines.append("Будь осторожен — не поддавайся эйфории и не увеличивай ставки резко.\n")

        # Лучший диапазон коэффициентов
        if best_odds_range:
            lines.append(f"🎯 *Лучший диапазон коэффициентов:* {best_odds_range}")
            lines.append(f"Там твой винрейт составляет {best_range_winrate:.0f}%. Сосредоточься на этом диапазоне.\n")

        # Лучший спорт
        if best_sport:
            lines.append(f"🏅 *Лучший вид спорта:* {best_sport}")
            lines.append(f"ROI = {best_sport_roi:+.1f}%. Рекомендую делать больше ставок именно здесь.\n")

        # Оптимальный кэф
        breakeven_winrate = 1 / avg_odds
        actual_winrate = winrate
        lines.append(f"📐 *Точка безубыточности:*")
        lines.append(f"При среднем кэфе {avg_odds:.2f} нужен винрейт ≥ {breakeven_winrate*100:.1f}%")
        lines.append(f"Твой фактический: {actual_winrate*100:.1f}%")
        if actual_winrate > breakeven_winrate:
            lines.append("✅ Ты выше порога безубыточности — стратегия математически жизнеспособна.\n")
        else:
            lines.append("❌ Ты ниже порога безубыточности — стратегия математически убыточна.\n")

        # Рекомендация по банкролу
        lines.append("💡 *Рекомендация:*")
        bets_all = self.db.get_all_bets(user_id)
        if bets_all:
            avg_amount = sum(b['amount'] for b in decided) / len(decided) if decided else 0
            recent_staked = sum(b['amount'] for b in recent)
            lines.append(f"Средняя ставка: {avg_amount:.0f} ₽")
            if total_staked > 0:
                avg_pct = avg_amount / (total_staked / len(decided)) * 100 if decided else 0
            lines.append("Ставь не более 3–5% от банкрола на одно событие.")

        return "\n".join(lines)

    def get_analytics(self, user_id: int) -> Optional[str]:
        decided = [b for b in self.db.get_all_bets(user_id) if b['result'] in ('win', 'loss')]
        if len(decided) < 5:
            return None

        lines = ["📈 *Детальная аналитика*\n"]

        # По видам спорта
        sport_stats = self.db.get_stats_by_sport(user_id)
        if sport_stats:
            lines.append("🏅 *По видам спорта:*")
            for s in sport_stats[:5]:
                wr = (s['wins'] / s['total'] * 100) if s['total'] > 0 else 0
                roi = (s['total_profit'] / s['total_staked'] * 100) if s['total_staked'] else 0
                profit_icon = "📈" if s['total_profit'] >= 0 else "📉"
                lines.append(
                    f"{profit_icon} *{s['sport']}*: {s['total']} ставок, "
                    f"{wr:.0f}% побед, ROI {roi:+.1f}%"
                )
            lines.append("")

        # По диапазонам коэффициентов
        odds_stats = self.db.get_stats_by_odds_range(user_id)
        if odds_stats:
            lines.append("📊 *По диапазонам коэффициентов:*")
            for o in odds_stats:
                if o['total'] > 0:
                    profit_icon = "✅" if o['profit'] >= 0 else "❌"
                    lines.append(
                        f"{profit_icon} *{o['odds_range']}*: "
                        f"{o['total']} ставок, {o['winrate']:.0f}% побед, "
                        f"прибыль: {o['profit']:+.0f}₽"
                    )
            lines.append("")

        # По месяцам (последние 6)
        monthly = self.db.get_monthly_stats(user_id)
        if monthly:
            lines.append("📅 *По месяцам (последние 6):*")
            for m in monthly[-6:]:
                profit_icon = "📈" if m['profit'] >= 0 else "📉"
                wr = (m['wins'] / m['total'] * 100) if m['total'] > 0 else 0
                lines.append(
                    f"{profit_icon} *{m['month']}*: {m['total']} ставок, "
                    f"{wr:.0f}% побед, {m['profit']:+.0f}₽"
                )

        return "\n".join(lines)
