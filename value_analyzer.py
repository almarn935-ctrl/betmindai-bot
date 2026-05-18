"""
value_analyzer.py — поиск value bet и сравнение коэффициентов

Value bet = ставка где реальная вероятность выше чем подразумевает кэф букмекера.
"""
import aiohttp
import logging
import os
from database import Database
from history_fetcher import HistoryFetcher

logger = logging.getLogger(__name__)


class ValueAnalyzer:
    def __init__(self, db: Database):
        self.db = db
        self.history = HistoryFetcher(db)
        self.odds_api_key = os.getenv("ODDS_API_KEY", "")
        self.session = None

    async def _get_session(self):
        if not self.session or self.session.closed:
            self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))
        return self.session

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()

    SPORT_KEYS = {
        "футбол": "soccer_uefa_champs_league",
        "баскетбол": "basketball_nba",
        "теннис": "tennis_atp_french_open",
        "хоккей": "icehockey_nhl",
    }

    async def compare_odds(self, sport: str) -> str:
        """Сравниваем кэфы разных букмекеров"""
        if not self.odds_api_key:
            return (
                "🔑 *Для сравнения кэфов нужен ключ The Odds API*\n\n"
                "1. Зарегистрируйся на the-odds-api.com\n"
                "2. Получи бесплатный ключ (500 запросов/месяц)\n"
                "3. Добавь в PowerShell перед запуском бота:\n"
                "`$env:ODDS_API_KEY=\"твой_ключ\"`"
            )

        sport_key = self.SPORT_KEYS.get(sport.lower(), "soccer_uefa_champs_league")
        url = (
            f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds"
            f"?apiKey={self.odds_api_key}&regions=eu&markets=h2h&oddsFormat=decimal"
        )
        try:
            session = await self._get_session()
            async with session.get(url) as resp:
                if resp.status != 200:
                    return "❌ Не удалось получить данные."
                data = await resp.json()
        except Exception as e:
            return f"❌ Ошибка: {e}"

        if not data:
            return "😔 Нет матчей для сравнения."

        lines = [f"📊 *Сравнение кэфов — {sport.title()}*\n"]
        for game in data[:4]:
            home = game.get('home_team', '?')
            away = game.get('away_team', '?')
            lines.append(f"⚽ *{home} vs {away}*")
            all_home, all_away, all_draw = [], [], []
            for bk in game.get('bookmakers', []):
                bk_name = bk.get('title', '?')
                markets = bk.get('markets', [{}])[0]
                outcomes = {o['name']: o['price'] for o in markets.get('outcomes', [])}
                if outcomes.get(home, 0) > 1:
                    all_home.append((bk_name, outcomes[home]))
                if outcomes.get(away, 0) > 1:
                    all_away.append((bk_name, outcomes[away]))
                if outcomes.get('Draw', 0) > 1:
                    all_draw.append((bk_name, outcomes['Draw']))
            if all_home:
                best = max(all_home, key=lambda x: x[1])
                worst = min(all_home, key=lambda x: x[1])
                lines.append(f"  1: лучший *{best[1]}* ({best[0]}) | худший {worst[1]}")
            if all_draw:
                best = max(all_draw, key=lambda x: x[1])
                lines.append(f"  X: лучший *{best[1]}* ({best[0]})")
            if all_away:
                best = max(all_away, key=lambda x: x[1])
                lines.append(f"  2: лучший *{best[1]}* ({best[0]})")
            lines.append("")
        return "\n".join(lines)

    async def find_value_bets(self, league: str) -> str:
        """Ищет value bet на основе исторической статистики"""
        data = await self.history.fetch_league_history(league)
        if 'error' in data:
            return f"❌ {data['error']}"

        matches = data.get('matches', [])
        if not matches:
            return "❌ Нет данных."

        home_stats = {}
        away_stats = {}
        for m in matches:
            h, a = m['home'], m['away']
            for d, team in [(home_stats, h), (away_stats, a)]:
                if team not in d:
                    d[team] = {'w': 0, 'total': 0, 'odds': []}
            home_stats[h]['total'] += 1
            away_stats[a]['total'] += 1
            if m['odds_h'] > 1:
                home_stats[h]['odds'].append(m['odds_h'])
            if m['odds_a'] > 1:
                away_stats[a]['odds'].append(m['odds_a'])
            if m['result'] == 'H':
                home_stats[h]['w'] += 1
            if m['result'] == 'A':
                away_stats[a]['w'] += 1

        value_bets = []
        for stats_dict, bet_type in [(home_stats, 'дома'), (away_stats, 'в гостях')]:
            for team, s in stats_dict.items():
                if s['total'] < 8 or not s['odds']:
                    continue
                real_wr = s['w'] / s['total']
                avg_odds = sum(s['odds']) / len(s['odds'])
                implied = 1 / avg_odds if avg_odds > 1 else 0
                edge = real_wr - implied
                if edge > 0.07:
                    ev = real_wr * (avg_odds - 1) - (1 - real_wr)
                    value_bets.append({
                        'team': team, 'type': bet_type,
                        'real_wr': real_wr, 'implied': implied,
                        'edge': edge, 'avg_odds': avg_odds,
                        'ev': ev, 'games': s['total'],
                    })

        if not value_bets:
            return f"🔍 *Value Bet — {league}*\n\n😔 Value bet не найдено.\nБукмекеры точно оценивают эту лигу."

        value_bets.sort(key=lambda x: x['edge'], reverse=True)
        lines = [
            f"💎 *Value Bet — {league}*\n",
            f"Команд с преимуществом: *{len(value_bets)}*\n",
            "━━━━━━━━━━━━━━━━━━━━\n"
        ]
        for vb in value_bets[:8]:
            lines.append(
                f"✅ *{vb['team']}* ({vb['type']})\n"
                f"  Реальный WR: *{vb['real_wr']*100:.1f}%* | "
                f"Букмекер: *{vb['implied']*100:.1f}%* (кэф ~{vb['avg_odds']:.2f})\n"
                f"  Преимущество: *+{vb['edge']*100:.1f}%* | EV: *{vb['ev']:+.3f}*\n"
            )
        lines.append("_⚠️ Value bet выгодны на дистанции, не гарантируют победу в каждом матче._")
        return "\n".join(lines)

    async def analyze_match(self, home_team: str, away_team: str, league: str,
                            odds_h: float, odds_d: float, odds_a: float) -> str:
        """Анализ конкретного матча"""
        data = await self.history.fetch_league_history(league)
        if 'error' in data:
            return f"❌ {data['error']}"

        matches = data.get('matches', [])
        h2h = [m for m in matches
               if home_team.lower() in m['home'].lower() and away_team.lower() in m['away'].lower()]
        home_form = [m for m in matches[-150:] if home_team.lower() in m['home'].lower()]
        away_form = [m for m in matches[-150:] if away_team.lower() in m['away'].lower()]

        lines = [f"🔍 *Анализ матча*\n🏠 {home_team} vs ✈️ {away_team} | {league}\n"]

        if h2h:
            hw = sum(1 for m in h2h if m['result'] == 'H')
            dr = sum(1 for m in h2h if m['result'] == 'D')
            aw = sum(1 for m in h2h if m['result'] == 'A')
            lines.append(f"📋 *Личные встречи ({len(h2h)}):* {hw}—{dr}—{aw}\n")

        if home_form:
            last = home_form[-10:]
            hw = sum(1 for m in last if m['result'] == 'H')
            lines.append(f"🏠 *{home_team} дома (посл. {len(last)}):* {hw} побед ({hw/len(last)*100:.0f}%)\n")

        if away_form:
            last = away_form[-10:]
            aw = sum(1 for m in last if m['result'] == 'A')
            lines.append(f"✈️ *{away_team} в гостях (посл. {len(last)}):* {aw} побед ({aw/len(last)*100:.0f}%)\n")

        lines.append("💹 *Оценка кэфов:*")
        hist_h = (sum(1 for m in home_form if m['result']=='H')/len(home_form)) if home_form else 0.45
        hist_d = data.get('draw_pct', 25) / 100
        hist_a = (sum(1 for m in away_form if m['result']=='A')/len(away_form)) if away_form else 0.30

        for label, odds, prob in [
            (f"Победа {home_team}", odds_h, hist_h),
            ("Ничья", odds_d, hist_d),
            (f"Победа {away_team}", odds_a, hist_a),
        ]:
            if odds < 1.01:
                continue
            ev = prob * (odds - 1) - (1 - prob)
            is_value = prob > (1/odds) and ev > 0
            icon = "💎 VALUE" if is_value else "⚪"
            lines.append(f"  {icon} {label}: кэф {odds} | ~{prob*100:.0f}% | EV {ev:+.2f}")

        return "\n".join(lines)
