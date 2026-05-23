"""
history_fetcher.py — автоматический сбор исторических данных по ставкам
Источник: football-data.co.uk (бесплатно, без ключа)
"""

import aiohttp
import asyncio
import csv
import io
import logging
from database import Database

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://www.football-data.co.uk/",
}

# Все доступные лиги на football-data.co.uk
LEAGUES = {
    # Англия
    "АПЛ":              ("E0",  "England"),
    "Чемпионшип":       ("E1",  "England"),
    "Лига 1 Англия":    ("E2",  "England"),
    "Лига 2 Англия":    ("E3",  "England"),
    # Испания
    "Ла Лига":          ("SP1", "Spain"),
    "Сегунда":          ("SP2", "Spain"),
    # Германия
    "Бундеслига":       ("D1",  "Germany"),
    "Бундеслига 2":     ("D2",  "Germany"),
    # Италия
    "Серия А":          ("I1",  "Italy"),
    "Серия Б":          ("I2",  "Italy"),
    # Франция
    "Лига 1":           ("F1",  "France"),
    "Лига 2":           ("F2",  "France"),
    # Нидерланды
    "Эредивизи":        ("N1",  "Netherlands"),
    # Бельгия
    "Про Лига":         ("B1",  "Belgium"),
    # Португалия
    "Примейра":         ("P1",  "Portugal"),
    # Турция
    "Суперлига":        ("T1",  "Turkey"),
    # Греция
    "Суперлига Греция": ("G1",  "Greece"),
    # Шотландия
    "Премьершип":       ("SC0", "Scotland"),
    # Россия
    "РПЛ":              ("R1",  "Russia"),
    # Польша
    "Экстракласа":      ("PL1", "Poland"),
    # Украина
    "УПЛ":              ("UKR", "Ukraine"),
    # Аргентина
    "Примера":          ("ARG", "Argentina"),
    # Бразилия
    "Серия А Бразилия": ("BRA", "Brazil"),
    # Мексика
    "Лига МХ":          ("MEX", "Mexico"),
    # США
    "MLS":              ("USA", "USA"),
    # Япония
    "Джей-лига":        ("JPN", "Japan"),
    # Китай
    "Суперлига Китай":  ("CHN", "China"),
}

SEASONS = ["2122", "2223", "2324", "2425"]

# Группировка для удобного отображения в боте
LEAGUE_GROUPS = {
    "🏴󠁧󠁢󠁥󠁮󠁧󠁿 Англия":     ["АПЛ", "Чемпионшип", "Лига 1 Англия", "Лига 2 Англия"],
    "🇪🇸 Испания":    ["Ла Лига", "Сегунда"],
    "🇩🇪 Германия":   ["Бундеслига", "Бундеслига 2"],
    "🇮🇹 Италия":     ["Серия А", "Серия Б"],
    "🇫🇷 Франция":    ["Лига 1", "Лига 2"],
    "🇷🇺 Россия/СНГ": ["РПЛ", "УПЛ"],
    "🌍 Европа":      ["Эредивизи", "Про Лига", "Примейра", "Суперлига", "Суперлига Греция", "Премьершип", "Экстракласа"],
    "🌎 Америка":     ["Примера", "Серия А Бразилия", "Лига МХ", "MLS"],
    "🌏 Азия":        ["Джей-лига", "Суперлига Китай"],
}


class HistoryFetcher:
    def __init__(self, db: Database):
        self.db = db
        self.session = None

    async def _get_session(self):
        if not self.session or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=30)
            self.session = aiohttp.ClientSession(timeout=timeout, headers=HEADERS)
        return self.session

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()

    async def fetch_league_history(self, league_name: str) -> dict:
        if league_name not in LEAGUES:
            available = ", ".join(LEAGUES.keys())
            return {"error": f"Лига не найдена. Доступны: {available}"}

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
            return {"error": "Не удалось загрузить данные. Возможно лига временно недоступна, попробуй позже."}

        return self._analyze_matches(all_matches, league_name)

    def _parse_row(self, row: dict, season: str):
        home = row.get('HomeTeam', '').strip()
        away = row.get('AwayTeam', '').strip()
        if not home or not away:
            return None
        fthg = int(row.get('FTHG', 0) or 0)
        ftag = int(row.get('FTAG', 0) or 0)
        ftr  = row.get('FTR', '').strip()
        if ftr not in ('H', 'D', 'A'):
            return None
        odds_h = self._avg_odds([row.get('B365H'), row.get('BWH'), row.get('PSH'), row.get('WHH')])
        odds_d = self._avg_odds([row.get('B365D'), row.get('BWD'), row.get('PSD'), row.get('WHD')])
        odds_a = self._avg_odds([row.get('B365A'), row.get('BWA'), row.get('PSA'), row.get('WHA')])
        return {
            'home': home, 'away': away,
            'home_goals': fthg, 'away_goals': ftag,
            'result': ftr,
            'odds_h': odds_h, 'odds_d': odds_d, 'odds_a': odds_a,
            'season': season,
            'total_goals': fthg + ftag,
        }

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
        total = len(matches)
        home_wins = sum(1 for m in matches if m['result'] == 'H')
        draws     = sum(1 for m in matches if m['result'] == 'D')
        away_wins = sum(1 for m in matches if m['result'] == 'A')
        avg_goals = sum(m['total_goals'] for m in matches) / total if total else 0

        roi_h = self._calc_roi(matches, 'H', 'odds_h')
        roi_d = self._calc_roi(matches, 'D', 'odds_d')
        roi_a = self._calc_roi(matches, 'A', 'odds_a')
        best_odds_range = self._best_odds_range(matches)
        team_stats = self._team_analysis(matches)

        return {
            'league': league,
            'total_matches': total,
            'seasons': len(set(m['season'] for m in matches)),
            'home_win_pct': round(home_wins / total * 100, 1),
            'draw_pct':     round(draws     / total * 100, 1),
            'away_win_pct': round(away_wins / total * 100, 1),
            'avg_goals':    round(avg_goals, 2),
            'roi_home':     roi_h,
            'roi_draw':     roi_d,
            'roi_away':     roi_a,
            'best_odds_range': best_odds_range,
            'top_home_teams':  team_stats['top_home'],
            'top_away_teams':  team_stats['top_away'],
            'matches': matches[-50:],
        }

    def _calc_roi(self, matches, result, odds_key):
        profit = staked = 0
        for m in matches:
            odds = m.get(odds_key, 0)
            if odds < 1.01:
                continue
            staked += 1
            profit += (odds - 1) if m['result'] == result else -1
        return round(profit / staked * 100, 1) if staked else 0.0

    def _best_odds_range(self, matches):
        ranges = {
            '1.01–1.49': (1.01, 1.49), '1.50–1.99': (1.50, 1.99),
            '2.00–2.49': (2.00, 2.49), '2.50–2.99': (2.50, 2.99),
            '3.00–4.99': (3.00, 4.99), '5.00+':     (5.00, 99.0),
        }
        best_roi, best_range = -999, '2.00–2.49'
        for label, (lo, hi) in ranges.items():
            relevant = [
                (m['result'], ok, m[ok])
                for m in matches
                for ok in ('odds_h', 'odds_d', 'odds_a')
                if lo <= m.get(ok, 0) <= hi
            ]
            if len(relevant) < 10:
                continue
            profit = sum(
                (o - 1) if (r=='H' and ok=='odds_h') or (r=='D' and ok=='odds_d') or (r=='A' and ok=='odds_a') else -1
                for r, ok, o in relevant
            )
            roi = profit / len(relevant) * 100
            if roi > best_roi:
                best_roi, best_range = roi, label
        return best_range

    def _team_analysis(self, matches):
        home_stats, away_stats = {}, {}
        for m in matches:
            h, a = m['home'], m['away']
            for d, t in [(home_stats, h), (away_stats, a)]:
                if t not in d:
                    d[t] = {'w': 0, 'total': 0, 'profit': 0}
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

        def top(stats, min_games=8):
            f = [(t, s) for t, s in stats.items() if s['total'] >= min_games]
            f.sort(key=lambda x: x[1]['profit'], reverse=True)
            return [(t, round(s['profit']/s['total']*100,1), s['w'], s['total']) for t, s in f[:5]]

        return {'top_home': top(home_stats), 'top_away': top(away_stats)}

    def format_report(self, data: dict) -> str:
        if 'error' in data:
            return f"❌ {data['error']}"
        lines = [
            f"📊 *{data['league']}* — исторический анализ\n",
            f"📁 Матчей: *{data['total_matches']}* за *{data['seasons']}* сезона\n",
            f"🏠 Победы хозяев: *{data['home_win_pct']}%*",
            f"🤝 Ничьи: *{data['draw_pct']}%*",
            f"✈️ Победы гостей: *{data['away_win_pct']}%*",
            f"⚽ Среднее голов: *{data['avg_goals']}*\n",
            f"💰 *ROI при ставках на:*",
            f"  🏠 Хозяев: *{data['roi_home']:+.1f}%*",
            f"  🤝 Ничью: *{data['roi_draw']:+.1f}%*",
            f"  ✈️ Гостей: *{data['roi_away']:+.1f}%*\n",
            f"🎯 Лучший диапазон кэфов: *{data['best_odds_range']}*\n",
        ]
        if data['top_home_teams']:
            lines.append("🏆 *Топ дома (по ROI):*")
            for t, roi, w, total in data['top_home_teams']:
                lines.append(f"  • {t}: {roi:+.0f}% ({w}/{total})")
            lines.append("")
        if data['top_away_teams']:
            lines.append("✈️ *Топ в гостях (по ROI):*")
            for t, roi, w, total in data['top_away_teams']:
                lines.append(f"  • {t}: {roi:+.0f}% ({w}/{total})")
        return "\n".join(lines)

    @staticmethod
    def get_keyboard_layout() -> list:
        """Возвращает клавиатуру по группам для Telegram"""
        from telegram import KeyboardButton
        rows = []
        for group, leagues in LEAGUE_GROUPS.items():
            # Заголовок группы
            rows.append([KeyboardButton(group)])
            # Лиги по 2 в ряд
            for i in range(0, len(leagues), 2):
                pair = leagues[i:i+2]
                rows.append([KeyboardButton(l) for l in pair])
        rows.append([KeyboardButton("❌ Отмена")])
        return rows

    @staticmethod
    def all_league_names() -> list:
        return list(LEAGUES.keys())
