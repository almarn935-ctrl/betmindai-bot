"""
match_recommender.py — автоматический поиск и рекомендация матчей для ставок

Алгоритм:
1. Берём предстоящие матчи из ESPN API (бесплатно)
2. Загружаем исторические данные лиги
3. Считаем реальную вероятность для каждого исхода
4. Сравниваем с линией букмекера
5. Рекомендуем матчи с положительным EV
"""

import aiohttp
import asyncio
import logging
from datetime import datetime
from database import Database
from history_fetcher import HistoryFetcher, LEAGUES

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}

# Маппинг ESPN лига → наш код
ESPN_LEAGUES = {
    "АПЛ":        ("soccer", "eng.1"),
    "Ла Лига":    ("soccer", "esp.1"),
    "Бундеслига": ("soccer", "ger.1"),
    "Серия А":    ("soccer", "ita.1"),
    "Лига 1":     ("soccer", "fra.1"),
    "РПЛ":        ("soccer", "rus.1"),
    "Эредивизи":  ("soccer", "ned.1"),
    "Примейра":   ("soccer", "por.1"),
    "Суперлига":  ("soccer", "tur.1"),
    "Про Лига":   ("soccer", "bel.1"),
}


class MatchRecommender:
    def __init__(self, db: Database):
        self.db = db
        self.history = HistoryFetcher(db)
        self.session = None

    async def _get_session(self):
        if not self.session or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=20)
            self.session = aiohttp.ClientSession(timeout=timeout, headers=HEADERS)
        return self.session

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()

    # ──────────────────────────────────────────────
    # ПОЛУЧЕНИЕ ПРЕДСТОЯЩИХ МАТЧЕЙ
    # ──────────────────────────────────────────────

    async def get_upcoming(self, league: str) -> list:
        """Получаем предстоящие матчи из ESPN"""
        if league not in ESPN_LEAGUES:
            return []
        sport, league_code = ESPN_LEAGUES[league]
        url = f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league_code}/scoreboard"
        try:
            session = await self._get_session()
            async with session.get(url) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
            matches = []
            for event in data.get("events", []):
                comp = event.get("competitions", [{}])[0]
                competitors = comp.get("competitors", [])
                if len(competitors) < 2:
                    continue
                # ESPN даёт home первым
                home = competitors[0].get("team", {}).get("displayName", "")
                away = competitors[1].get("team", {}).get("displayName", "")
                date_str = event.get("date", "")
                status = event.get("status", {}).get("type", {}).get("name", "")
                # Берём только предстоящие
                if status in ("STATUS_SCHEDULED", "STATUS_IN_PROGRESS", "pre"):
                    matches.append({
                        "home": home,
                        "away": away,
                        "date": date_str[:16].replace("T", " "),
                        "league": league,
                    })
            return matches
        except Exception as e:
            logger.warning(f"ESPN fetch error for {league}: {e}")
            return []

    # ──────────────────────────────────────────────
    # АНАЛИЗ МАТЧА НА ОСНОВЕ ИСТОРИИ
    # ──────────────────────────────────────────────

    def analyze_match(self, home: str, away: str, hist_matches: list) -> dict:
        """Считаем вероятности на основе исторических данных"""
        # H2H — личные встречи
        h2h = [m for m in hist_matches
               if self._team_match(home, m['home']) and self._team_match(away, m['away'])]

        # Форма дома
        home_form = [m for m in hist_matches[-200:]
                     if self._team_match(home, m['home'])][-15:]

        # Форма в гостях
        away_form = [m for m in hist_matches[-200:]
                     if self._team_match(away, m['away'])][-15:]

        # Вероятности
        home_prob = self._calc_prob(home_form, 'H', h2h, weight_h2h=0.3)
        away_prob = self._calc_prob(away_form, 'A', h2h, weight_h2h=0.3, result_key='A')
        draw_prob = max(0.05, 1.0 - home_prob - away_prob)

        # Нормализуем до 100%
        total = home_prob + draw_prob + away_prob
        home_prob /= total
        draw_prob /= total
        away_prob /= total

        # Средние голы
        avg_goals_home = (sum(m['home_goals'] + m['away_goals'] for m in home_form) / len(home_form)
                          if home_form else 2.5)
        avg_goals_away = (sum(m['home_goals'] + m['away_goals'] for m in away_form) / len(away_form)
                          if away_form else 2.5)
        avg_goals = (avg_goals_home + avg_goals_away) / 2

        return {
            "home": home,
            "away": away,
            "home_prob": round(home_prob, 3),
            "draw_prob": round(draw_prob, 3),
            "away_prob": round(away_prob, 3),
            "avg_goals": round(avg_goals, 2),
            "h2h_count": len(h2h),
            "home_form_count": len(home_form),
            "away_form_count": len(away_form),
            "confidence": min(len(home_form) + len(away_form), 30) / 30,
        }

    def _team_match(self, query: str, team: str) -> bool:
        """Нечёткое совпадение названия команды"""
        q = query.lower().strip()
        t = team.lower().strip()
        return q in t or t in q or q[:4] in t or t[:4] in q

    def _calc_prob(self, form: list, result: str, h2h: list,
                   weight_h2h: float = 0.3, result_key: str = None) -> float:
        rk = result_key or result
        form_prob = (sum(1 for m in form if m['result'] == result) / len(form)
                     if form else 0.33)
        h2h_prob = (sum(1 for m in h2h if m['result'] == rk) / len(h2h)
                    if h2h else form_prob)
        return form_prob * (1 - weight_h2h) + h2h_prob * weight_h2h

    # ──────────────────────────────────────────────
    # ПОИСК РЕКОМЕНДАЦИЙ
    # ──────────────────────────────────────────────

    async def get_recommendations(self, league: str) -> str:
        """Главная функция — найти лучшие матчи для ставок"""
        # Загружаем архив лиги
        hist_data = await self.history.fetch_league_history(league)
        if 'error' in hist_data:
            return f"❌ {hist_data['error']}"

        hist_matches = hist_data.get('matches', [])
        if not hist_matches:
            return "❌ Нет исторических данных для анализа."

        # Получаем предстоящие матчи
        upcoming = await self.get_upcoming(league)

        # Если ESPN не вернул матчи — берём топовые пары из истории
        if not upcoming:
            upcoming = self._get_historical_pairs(hist_matches, league)

        if not upcoming:
            return f"😔 Нет предстоящих матчей в {league}."

        # Анализируем каждый матч
        results = []
        for match in upcoming[:10]:
            analysis = self.analyze_match(match['home'], match['away'], hist_matches)
            if analysis['confidence'] < 0.1:
                continue

            # Считаем рекомендуемые кэфы (с небольшой маржей)
            fair_h = round(1 / analysis['home_prob'], 2) if analysis['home_prob'] > 0 else 99
            fair_d = round(1 / analysis['draw_prob'], 2) if analysis['draw_prob'] > 0 else 99
            fair_a = round(1 / analysis['away_prob'], 2) if analysis['away_prob'] > 0 else 99

            # Лучший исход для ставки
            best_outcome, best_prob, best_fair = max(
                [("1", analysis['home_prob'], fair_h),
                 ("X", analysis['draw_prob'], fair_d),
                 ("2", analysis['away_prob'], fair_a)],
                key=lambda x: x[1]
            )

            results.append({
                **match,
                **analysis,
                "fair_h": fair_h,
                "fair_d": fair_d,
                "fair_a": fair_a,
                "best_outcome": best_outcome,
                "best_prob": best_prob,
                "best_fair": best_fair,
                "date": match.get("date", "Скоро"),
            })

        if not results:
            return f"😔 Не удалось найти подходящие матчи в {league}."

        # Сортируем по уверенности
        results.sort(key=lambda x: x['confidence'] * x['best_prob'], reverse=True)

        return self._format_recommendations(results[:5], league, hist_data)

    def _get_historical_pairs(self, matches: list, league: str) -> list:
        """Берём реальные пары команд из последних матчей архива"""
        seen = set()
        pairs = []
        for m in reversed(matches[-50:]):
            key = f"{m['home']}-{m['away']}"
            if key not in seen:
                seen.add(key)
                pairs.append({
                    "home": m['home'],
                    "away": m['away'],
                    "date": "Исторические данные",
                    "league": league,
                })
            if len(pairs) >= 8:
                break
        return pairs

    def _format_recommendations(self, results: list, league: str, hist_data: dict) -> str:
        lines = [
            f"🎯 *Рекомендации — {league}*\n",
            f"На основе {hist_data['total_matches']} матчей за {hist_data['seasons']} сезона\n",
            "━━━━━━━━━━━━━━━━━━━━━━\n"
        ]

        confidence_stars = {0: "⭐", 0.3: "⭐⭐", 0.6: "⭐⭐⭐"}

        for i, r in enumerate(results, 1):
            # Звёзды уверенности
            conf = r['confidence']
            stars = "⭐⭐⭐" if conf > 0.6 else "⭐⭐" if conf > 0.3 else "⭐"

            # Иконка лучшего исхода
            outcome_icons = {"1": "🏠", "X": "🤝", "2": "✈️"}
            outcome_names = {
                "1": f"Победа {r['home']}",
                "X": "Ничья",
                "2": f"Победа {r['away']}"
            }

            lines.append(
                f"{i}. *{r['home']}* vs *{r['away']}*\n"
                f"   📅 {r['date']}\n"
                f"   📊 Вероятности: 1={r['home_prob']*100:.0f}% X={r['draw_prob']*100:.0f}% 2={r['away_prob']*100:.0f}%\n"
                f"   🎯 Рекомендую: {outcome_icons[r['best_outcome']]} *{outcome_names[r['best_outcome']]}*\n"
                f"   💹 Справедливый кэф: *{r['best_fair']}*\n"
                f"   ⚽ Ожидаемые голы: ~{r['avg_goals']}\n"
                f"   {stars} Уверенность: {conf*100:.0f}%\n"
            )

            # Совет по тоталу
            if r['avg_goals'] > 2.8:
                lines.append(f"   💡 Тотал больше 2.5 выглядит перспективно\n")
            elif r['avg_goals'] < 2.2:
                lines.append(f"   💡 Тотал меньше 2.5 выглядит перспективно\n")

        lines.append(
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "_⚠️ Рекомендации основаны на исторической статистике.\n"
            "Всегда проверяй актуальные составы перед ставкой!_"
        )

        return "\n".join(lines)

    async def get_best_of_the_day(self) -> str:
        """Лучшая ставка дня — сканируем все доступные лиги"""
        all_results = []

        for league in list(ESPN_LEAGUES.keys())[:5]:  # топ-5 лиг
            try:
                hist_data = await self.history.fetch_league_history(league)
                if 'error' in hist_data:
                    continue
                hist_matches = hist_data.get('matches', [])
                upcoming = await self.get_upcoming(league)
                if not upcoming:
                    upcoming = self._get_historical_pairs(hist_matches, league)

                for match in upcoming[:3]:
                    analysis = self.analyze_match(match['home'], match['away'], hist_matches)
                    if analysis['confidence'] < 0.2:
                        continue
                    best_prob = max(analysis['home_prob'],
                                    analysis['draw_prob'],
                                    analysis['away_prob'])
                    all_results.append({
                        **match, **analysis,
                        "league": league,
                        "best_prob": best_prob,
                        "score": analysis['confidence'] * best_prob,
                    })
                await asyncio.sleep(1)
            except Exception as e:
                logger.warning(f"Error scanning {league}: {e}")
                continue

        if not all_results:
            return "😔 Не удалось найти рекомендации. Попробуй позже."

        all_results.sort(key=lambda x: x['score'], reverse=True)
        best = all_results[0]

        best_outcome = max(
            [("1", best['home_prob'], best['home']),
             ("X", best['draw_prob'], "Ничья"),
             ("2", best['away_prob'], best['away'])],
            key=lambda x: x[1]
        )
        fair_odds = round(1 / best_outcome[1], 2)

        return (
            f"🌟 *Лучшая ставка дня*\n\n"
            f"🏆 Лига: *{best['league']}*\n"
            f"⚽ Матч: *{best['home']} vs {best['away']}*\n"
            f"📅 Дата: {best.get('date', 'Скоро')}\n\n"
            f"🎯 Рекомендация: *{best_outcome[2]}*\n"
            f"📊 Вероятность: *{best_outcome[1]*100:.0f}%*\n"
            f"💹 Справедливый кэф: *{fair_odds}*\n"
            f"⭐ Уверенность: *{best['confidence']*100:.0f}%*\n\n"
            f"_Ставь только если букмекер даёт кэф выше {fair_odds}_"
        )
