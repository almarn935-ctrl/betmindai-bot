"""
history_fetcher.py — автоматический сбор исторических данных по ставкам
Источники:
  - football-data.co.uk  (бесплатно, CSV с результатами и коэффициентами)
  - api-football (исторические матчи)
  - the-odds-api (архив)
"""

import aiohttp
import asyncio
import csv
import io
import logging
from datetime import datetime, timedelta
from database import Database

logger = logging.getLogger(__name__)

# Лиги на football-data.co.uk (бесплатно, без ключа!)
LEAGUES = {
    "АПЛ":          ("E0", "England"),
    "Ла Лига":      ("SP1", "Spain"),
    "Бундеслига":   ("D1", "Germany"),
    "Серия А":      ("I1", "Italy"),
    "Лига 1":       ("F1", "France"),
    "РПЛ":          ("R1", "Russia"),
    "Эредивизи":    ("N1", "Netherlands"),
    "Примейра":     ("P1", "Portugal"),
}

SEASONS = ["2122", "2223", "2324", "2425"]  # последние 4 сезона


class HistoryFetcher:
    def __init__(self, db: Database):
        self.db = db
        self.session = None

    async def _get_session(self):
        if not self.session or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=30)
            self.session = aiohttp.ClientSession(timeout=timeout)
        return self.session

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()

    async def fetch_league_history(self, league_name: str) -> dict:
        """
        Скачивает исторические результаты матчей с коэффициентами.
        Возвращает статистику для анализа.
        """
        if league_name not in LEAGUES:
            return {"error": f"Лига не найдена. Доступны: {', '.join(LEAGUES.keys())}"}

        league_code, _ = LEAGUES[league_name]
        all_matches = []

        session = await self._get_session()
        for season in SEASONS:
            url = f"https://www.football-data.co.uk/mmz4281/{season}/{league_code}.csv"
            try:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        continue
                    text = await resp.text(encoding='latin-1')
                    reader = csv.DictReader(io.StringIO(text))
                    for row in reader:
                        try:
                            match = self._parse_row(row, season)
                            if match:
                                all_matches.append(match)
                        except Exception:
                            continue
            except Exception as e:
                logger.warning(f"Error fetching {league_name} {season}: {e}")
                continue

        if not all_matches:
            return {"error": "Не удалось загрузить данные. Попробуй позже."}

        return self._analyze_matches(all_matches, league_name)

    def _parse_row(self, row: dict, season: str) -> dict | None:
        """Парсим строку CSV с матчем"""
        try:
            home = row.get('HomeTeam', '').strip()
            away = row.get('AwayTeam', '').strip()
            if not home or not away:
                return None

            fthg = int(row.get('FTHG', 0) or 0)  # голы хозяев
            ftag = int(row.get('FTAG', 0) or 0)  # голы гостей
            ftr = row.get('FTR', '').strip()      # H/D/A

            # Коэффициенты (берём средние по нескольким букмекерам)
            odds_h = self._avg_odds([row.get('B365H'), row.get('BWH'), row.get('PSH')])
            odds_d = self._avg_odds([row.get('B365D'), row.get('BWD'), row.get('PSD')])
            odds_a = self._avg_odds([row.get('B365A'), row.get('BWA'), row.get('PSA')])

            if not ftr or ftr not in ('H', 'D', 'A'):
                return None

            return {
                'home': home, 'away': away,
                'home_goals': fthg, 'away_goals': ftag,
                'result': ftr,  # H=хозяева, D=ничья, A=гости
                'odds_h': odds_h, 'odds_d': odds_d, 'odds_a': odds_a,
                'season': season,
                'total_goals': fthg + ftag,
            }
        except Exception:
            return None

    def _avg_odds(self, values: list) -> float:
        nums = []
        for v in values:
            try:
                f = float(v)
                if f > 1.0:
                    nums.append(f)
            except (TypeError, ValueError):
                pass
        return round(sum(nums) / len(nums), 2) if nums else 0.0

    def _analyze_matches(self, matches: list, league: str) -> dict:
        """Анализируем исторические данные"""
        total = len(matches)
        home_wins = sum(1 for m in matches if m['result'] == 'H')
        draws = sum(1 for m in matches if m['result'] == 'D')
        away_wins = sum(1 for m in matches if m['result'] == 'A')

        # Средняя результативность
        avg_goals = sum(m['total_goals'] for m in matches) / total if total else 0

        # ROI по ставкам на хозяев/ничью/гостей
        roi_h = self._calc_roi(matches, 'H', 'odds_h')
        roi_d = self._calc_roi(matches, 'D', 'odds_d')
        roi_a = self._calc_roi(matches, 'A', 'odds_a')

        # Лучший диапазон коэффициентов
        best_odds_range = self._best_odds_range(matches)

        # Команды с лучшим ROI для ставок на победу хозяев
        team_stats = self._team_analysis(matches)

        return {
            'league': league,
            'total_matches': total,
            'seasons': len(set(m['season'] for m in matches)),
            'home_win_pct': round(home_wins / total * 100, 1),
            'draw_pct': round(draws / total * 100, 1),
            'away_win_pct': round(away_wins / total * 100, 1),
            'avg_goals': round(avg_goals, 2),
            'roi_home': roi_h,
            'roi_draw': roi_d,
            'roi_away': roi_a,
            'best_odds_range': best_odds_range,
            'top_home_teams': team_stats['top_home'],
            'top_away_teams': team_stats['top_away'],
            'matches': matches[-50:],  # последние 50 для AI
        }

    def _calc_roi(self, matches: list, result: str, odds_key: str) -> float:
        profit = 0
        staked = 0
        for m in matches:
            odds = m.get(odds_key, 0)
            if odds < 1.01:
                continue
            staked += 1
            if m['result'] == result:
                profit += odds - 1
            else:
                profit -= 1
        return round(profit / staked * 100, 1) if staked > 0 else 0.0

    def _best_odds_range(self, matches: list) -> str:
        ranges = {
            '1.01-1.49': (1.01, 1.49),
            '1.50-1.99': (1.50, 1.99),
            '2.00-2.49': (2.00, 2.49),
            '2.50-2.99': (2.50, 2.99),
            '3.00-4.99': (3.00, 4.99),
            '5.00+':     (5.00, 99.0),
        }
        best_roi = -999
        best_range = '2.00-2.49'
        for label, (lo, hi) in ranges.items():
            relevant = []
            for m in matches:
                for ok in ('odds_h', 'odds_d', 'odds_a'):
                    o = m.get(ok, 0)
                    if lo <= o <= hi:
                        relevant.append((m['result'], ok, o))
            if len(relevant) < 10:
                continue
            profit = sum((o - 1) if (r == 'H' and ok == 'odds_h') or
                                    (r == 'D' and ok == 'odds_d') or
                                    (r == 'A' and ok == 'odds_a') else -1
                         for r, ok, o in relevant)
            roi = profit / len(relevant) * 100
            if roi > best_roi:
                best_roi = roi
                best_range = label
        return best_range

    def _team_analysis(self, matches: list) -> dict:
        home_stats = {}
        away_stats = {}
        for m in matches:
            h, a = m['home'], m['away']
            if h not in home_stats:
                home_stats[h] = {'w': 0, 'total': 0, 'profit': 0}
            if a not in away_stats:
                away_stats[a] = {'w': 0, 'total': 0, 'profit': 0}

            home_stats[h]['total'] += 1
            away_stats[a]['total'] += 1

            if m['result'] == 'H':
                home_stats[h]['w'] += 1
                home_stats[h]['profit'] += (m['odds_h'] - 1) if m['odds_h'] > 1 else 0
            else:
                home_stats[h]['profit'] -= 1

            if m['result'] == 'A':
                away_stats[a]['w'] += 1
                away_stats[a]['profit'] += (m['odds_a'] - 1) if m['odds_a'] > 1 else 0
            else:
                away_stats[a]['profit'] -= 1

        def top_teams(stats, min_games=10):
            filtered = [(t, s) for t, s in stats.items() if s['total'] >= min_games]
            filtered.sort(key=lambda x: x[1]['profit'], reverse=True)
            return [(t, round(s['profit'] / s['total'] * 100, 1), s['w'], s['total'])
                    for t, s in filtered[:5]]

        return {
            'top_home': top_teams(home_stats),
            'top_away': top_teams(away_stats),
        }

    def format_report(self, data: dict) -> str:
        """Форматируем отчёт для Telegram"""
        if 'error' in data:
            return f"❌ {data['error']}"

        lines = [
            f"📊 *Анализ исторических данных — {data['league']}*\n",
            f"📁 Матчей проанализировано: *{data['total_matches']}*",
            f"📅 Сезонов: *{data['seasons']}*\n",
            f"🏠 Победы хозяев: *{data['home_win_pct']}%*",
            f"🤝 Ничьи: *{data['draw_pct']}%*",
            f"✈️ Победы гостей: *{data['away_win_pct']}%*",
            f"⚽ Среднее голов в матче: *{data['avg_goals']}*\n",
            f"💰 *ROI при ставках на:*",
            f"  🏠 Хозяев: *{data['roi_home']:+.1f}%*",
            f"  🤝 Ничью: *{data['roi_draw']:+.1f}%*",
            f"  ✈️ Гостей: *{data['roi_away']:+.1f}%*\n",
            f"🎯 Лучший диапазон кэфов: *{data['best_odds_range']}*\n",
        ]

        if data['top_home_teams']:
            lines.append("🏆 *Топ команд дома (по ROI):*")
            for team, roi, w, total in data['top_home_teams']:
                lines.append(f"  • {team}: {roi:+.0f}% ({w}/{total})")
            lines.append("")

        if data['top_away_teams']:
            lines.append("✈️ *Топ команд в гостях (по ROI):*")
            for team, roi, w, total in data['top_away_teams']:
                lines.append(f"  • {team}: {roi:+.0f}% ({w}/{total})")

        return "\n".join(lines)
