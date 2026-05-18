"""
data_scraper.py — сбор внешних данных для анализа
Источники (все бесплатные, без ключей или с бесплатным ключом):
  - The Odds API      (бесплатный ключ: 500 запросов/месяц)
  - API-Football      (бесплатный ключ: 100 запросов/день)
  - ESPN hidden API   (публичный, без ключа)
  - football-data.org (бесплатный ключ)
"""

import asyncio
import aiohttp
import logging
import os
import json
import re
from datetime import datetime, timedelta
from typing import Optional
from database import Database

logger = logging.getLogger(__name__)


class DataScraper:
    def __init__(self, db: Database):
        self.db = db
        self.odds_api_key = os.getenv("ODDS_API_KEY", "")
        self.football_api_key = os.getenv("FOOTBALL_API_KEY", "")
        self.session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if not self.session or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=15)
            self.session = aiohttp.ClientSession(timeout=timeout)
        return self.session

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()

    # ──────────────────────────────────────────────
    # 1. ТЕКУЩИЕ МАТЧИ — ESPN (без ключа!)
    # ──────────────────────────────────────────────

    SPORT_ESPN_MAP = {
        "футбол":      ("soccer", "uefa.champions"),
        "баскетбол":   ("basketball", "nba"),
        "теннис":      ("tennis", "atp"),
        "хоккей":      ("hockey", "nhl"),
        "американский футбол": ("football", "nfl"),
        "бейсбол":     ("baseball", "mlb"),
    }

    async def get_upcoming_matches(self, sport: str) -> list[dict]:
        """Получить ближайшие матчи через ESPN API (без ключа)"""
        sport_key = sport.lower().strip()
        espn_sport, espn_league = self.SPORT_ESPN_MAP.get(
            sport_key, ("soccer", "uefa.champions")
        )
        url = (
            f"https://site.api.espn.com/apis/site/v2/sports/"
            f"{espn_sport}/{espn_league}/scoreboard"
        )
        try:
            session = await self._get_session()
            async with session.get(url) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
            events = data.get("events", [])
            matches = []
            for e in events[:8]:
                comp = e.get("competitions", [{}])[0]
                competitors = comp.get("competitors", [])
                if len(competitors) < 2:
                    continue
                home = competitors[0].get("team", {}).get("displayName", "?")
                away = competitors[1].get("team", {}).get("displayName", "?")
                date_str = e.get("date", "")
                status = e.get("status", {}).get("type", {}).get("description", "")
                matches.append({
                    "home": home, "away": away,
                    "date": date_str[:16].replace("T", " "),
                    "status": status,
                    "league": espn_league.upper(),
                })
            return matches
        except Exception as ex:
            logger.warning(f"ESPN fetch error: {ex}")
            return []

    # ──────────────────────────────────────────────
    # 2. ЛИНИЯ — The Odds API (нужен бесплатный ключ)
    # ──────────────────────────────────────────────

    SPORT_ODDS_MAP = {
        "футбол":    "soccer_uefa_champs_league",
        "баскетбол": "basketball_nba",
        "теннис":    "tennis_atp_french_open",
        "хоккей":    "icehockey_nhl",
    }

    async def get_odds(self, sport: str) -> list[dict]:
        """Получить актуальные коэффициенты через The Odds API"""
        if not self.odds_api_key:
            return []
        sport_key = self.SPORT_ODDS_MAP.get(sport.lower(), "soccer_uefa_champs_league")
        url = (
            f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds"
            f"?apiKey={self.odds_api_key}&regions=eu&markets=h2h&oddsFormat=decimal"
        )
        try:
            session = await self._get_session()
            async with session.get(url) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
            result = []
            for game in data[:5]:
                home = game.get("home_team", "?")
                away = game.get("away_team", "?")
                bookmakers = game.get("bookmakers", [])
                if not bookmakers:
                    continue
                markets = bookmakers[0].get("markets", [{}])[0]
                outcomes = {o["name"]: o["price"] for o in markets.get("outcomes", [])}
                result.append({
                    "home": home, "away": away,
                    "odds_home": outcomes.get(home, "?"),
                    "odds_away": outcomes.get(away, "?"),
                    "odds_draw": outcomes.get("Draw", "?"),
                    "start_time": game.get("commence_time", "")[:16].replace("T", " "),
                })
            return result
        except Exception as ex:
            logger.warning(f"Odds API error: {ex}")
            return []

    # ──────────────────────────────────────────────
    # 3. СТАТИСТИКА КОМАНДЫ — API-Football (бесплатный ключ)
    # ──────────────────────────────────────────────

    async def get_team_stats(self, team_name: str) -> Optional[dict]:
        """Поиск статистики команды через API-Football"""
        if not self.football_api_key:
            return None
        headers = {"x-apisports-key": self.football_api_key}
        search_url = f"https://v3.football.api-sports.io/teams?search={team_name}"
        try:
            session = await self._get_session()
            async with session.get(search_url, headers=headers) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
            teams = data.get("response", [])
            if not teams:
                return None
            team_id = teams[0]["team"]["id"]
            season = datetime.now().year
            stats_url = (
                f"https://v3.football.api-sports.io/teams/statistics"
                f"?team={team_id}&season={season}&league=2"
            )
            async with session.get(stats_url, headers=headers) as resp2:
                if resp2.status != 200:
                    return None
                stats_data = await resp2.json()
            r = stats_data.get("response", {})
            fixtures = r.get("fixtures", {})
            goals = r.get("goals", {})
            return {
                "team": teams[0]["team"]["name"],
                "played": fixtures.get("played", {}).get("total", "?"),
                "wins": fixtures.get("wins", {}).get("total", "?"),
                "draws": fixtures.get("draws", {}).get("total", "?"),
                "losses": fixtures.get("loses", {}).get("total", "?"),
                "goals_for": goals.get("for", {}).get("total", {}).get("total", "?"),
                "goals_against": goals.get("against", {}).get("total", {}).get("total", "?"),
            }
        except Exception as ex:
            logger.warning(f"API-Football error: {ex}")
            return None

    # ──────────────────────────────────────────────
    # 4. СОХРАНЕНИЕ В БД
    # ──────────────────────────────────────────────

    def save_market_data(self, sport: str, event: str, odds_home: float,
                         odds_away: float, odds_draw: Optional[float] = None):
        """Сохранить данные о линии букмекера для обучения AI"""
        self.db.save_market_data(sport, event, odds_home, odds_away, odds_draw)

    # ──────────────────────────────────────────────
    # 5. ФОРМАТИРОВАНИЕ ДЛЯ TELEGRAM
    # ──────────────────────────────────────────────

    async def format_matches_message(self, sport: str) -> str:
        matches = await self.get_upcoming_matches(sport)
        if not matches:
            return f"😔 Не удалось получить матчи по {sport}. Попробуй позже."

        lines = [f"⚽ *Ближайшие матчи — {sport.title()}*\n"]
        for m in matches:
            lines.append(f"🆚 *{m['home']}* vs *{m['away']}*")
            lines.append(f"   📅 {m['date']}  |  {m['status']}\n")
        return "\n".join(lines)

    async def format_odds_message(self, sport: str) -> str:
        if not self.odds_api_key:
            return (
                "🔑 *Коэффициенты недоступны*\n\n"
                "Для получения линии добавь бесплатный ключ:\n"
                "1. Зарегистрируйся на [the-odds-api.com](https://the-odds-api.com)\n"
                "2. Скопируй API ключ\n"
                "3. Установи переменную: `ODDS_API_KEY=твой_ключ`"
            )
        odds = await self.get_odds(sport)
        if not odds:
            return "😔 Нет данных о коэффициентах для этого вида спорта."

        lines = [f"📊 *Актуальная линия — {sport.title()}*\n"]
        for o in odds:
            lines.append(f"🆚 *{o['home']}* vs *{o['away']}*")
            lines.append(f"   1️⃣ {o['odds_home']}  Х {o['odds_draw']}  2️⃣ {o['odds_away']}")
            lines.append(f"   ⏰ {o['start_time']}\n")
        return "\n".join(lines)
