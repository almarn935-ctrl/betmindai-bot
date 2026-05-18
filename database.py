import sqlite3
import csv
import io
from datetime import datetime
from typing import Optional, List, Dict

DB_PATH = "bets.db"

class Database:
    def __init__(self, path: str = DB_PATH):
        self.path = path
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id   INTEGER PRIMARY KEY,
                    username  TEXT,
                    created_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS bets (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id    INTEGER NOT NULL,
                    sport      TEXT NOT NULL,
                    event      TEXT NOT NULL,
                    amount     REAL NOT NULL,
                    odds       REAL NOT NULL,
                    result     TEXT NOT NULL CHECK(result IN ('win','loss','refund','pending')),
                    profit     REAL DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY(user_id) REFERENCES users(user_id)
                );

                CREATE TABLE IF NOT EXISTS market_data (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    sport       TEXT NOT NULL,
                    event       TEXT NOT NULL,
                    odds_home   REAL,
                    odds_away   REAL,
                    odds_draw   REAL,
                    fetched_at  TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS model_metrics (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id     INTEGER NOT NULL,
                    cv_accuracy REAL,
                    cv_std      REAL,
                    n_samples   INTEGER,
                    recorded_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS ai_predictions (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id     INTEGER NOT NULL,
                    sport       TEXT,
                    odds        REAL,
                    win_prob    REAL,
                    recommendation TEXT,
                    ev          REAL,
                    kelly       REAL,
                    created_at  TEXT DEFAULT (datetime('now'))
                );

                CREATE INDEX IF NOT EXISTS idx_bets_user ON bets(user_id);
                CREATE INDEX IF NOT EXISTS idx_bets_result ON bets(result);
                CREATE INDEX IF NOT EXISTS idx_bets_sport ON bets(sport);
                CREATE INDEX IF NOT EXISTS idx_metrics_user ON model_metrics(user_id);
            """)

    def ensure_user(self, user_id: int, username: str):
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO users(user_id, username) VALUES (?,?)",
                (user_id, username)
            )

    def add_bet(self, user_id: int, sport: str, event: str,
                amount: float, odds: float, result: str, profit: float):
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO bets(user_id, sport, event, amount, odds, result, profit)
                   VALUES (?,?,?,?,?,?,?)""",
                (user_id, sport, event, amount, odds, result, profit)
            )

    def get_all_bets(self, user_id: int, result_filter: Optional[str] = None) -> List[Dict]:
        with self._connect() as conn:
            if result_filter:
                rows = conn.execute(
                    "SELECT * FROM bets WHERE user_id=? AND result=? ORDER BY created_at",
                    (user_id, result_filter)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM bets WHERE user_id=? ORDER BY created_at",
                    (user_id,)
                ).fetchall()
        return [dict(r) for r in rows]

    def get_recent_bets(self, user_id: int, limit: int = 10) -> List[Dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM bets WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
                (user_id, limit)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_stats_by_sport(self, user_id: int) -> List[Dict]:
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT sport,
                       COUNT(*) as total,
                       SUM(CASE WHEN result='win' THEN 1 ELSE 0 END) as wins,
                       SUM(CASE WHEN result='loss' THEN 1 ELSE 0 END) as losses,
                       SUM(profit) as total_profit,
                       SUM(amount) as total_staked,
                       AVG(odds) as avg_odds
                FROM bets WHERE user_id=? AND result IN ('win','loss','refund')
                GROUP BY sport ORDER BY total DESC
            """, (user_id,)).fetchall()
        return [dict(r) for r in rows]

    def get_stats_by_odds_range(self, user_id: int) -> List[Dict]:
        """Статистика по диапазонам коэффициентов"""
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT
                    CASE
                        WHEN odds < 1.5 THEN '1.01–1.49'
                        WHEN odds < 2.0 THEN '1.50–1.99'
                        WHEN odds < 2.5 THEN '2.00–2.49'
                        WHEN odds < 3.0 THEN '2.50–2.99'
                        WHEN odds < 5.0 THEN '3.00–4.99'
                        ELSE '5.00+'
                    END as odds_range,
                    COUNT(*) as total,
                    SUM(CASE WHEN result='win' THEN 1 ELSE 0 END) as wins,
                    SUM(profit) as profit,
                    AVG(CASE WHEN result='win' THEN 1.0 ELSE 0.0 END)*100 as winrate
                FROM bets WHERE user_id=? AND result IN ('win','loss')
                GROUP BY odds_range ORDER BY MIN(odds)
            """, (user_id,)).fetchall()
        return [dict(r) for r in rows]

    def get_monthly_stats(self, user_id: int) -> List[Dict]:
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT strftime('%Y-%m', created_at) as month,
                       COUNT(*) as total,
                       SUM(CASE WHEN result='win' THEN 1 ELSE 0 END) as wins,
                       SUM(profit) as profit,
                       SUM(amount) as staked
                FROM bets WHERE user_id=? AND result IN ('win','loss','refund')
                GROUP BY month ORDER BY month
            """, (user_id,)).fetchall()
        return [dict(r) for r in rows]

    def get_streak_data(self, user_id: int) -> List[str]:
        """Возвращает последовательность результатов для анализа серий"""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT result FROM bets WHERE user_id=? AND result IN ('win','loss') ORDER BY created_at",
                (user_id,)
            ).fetchall()
        return [r['result'] for r in rows]

    def export_to_csv(self, user_id: int) -> Optional[str]:
        bets = self.get_all_bets(user_id)
        if not bets:
            return None
        output = io.StringIO()
        fields = ['id', 'sport', 'event', 'amount', 'odds', 'result', 'profit', 'created_at']
        writer = csv.DictWriter(output, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(bets)
        return output.getvalue()

    def save_market_data(self, sport: str, event: str,
                         odds_home: float, odds_away: float,
                         odds_draw=None):
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO market_data(sport,event,odds_home,odds_away,odds_draw) VALUES(?,?,?,?,?)",
                (sport, event, odds_home, odds_away, odds_draw)
            )

    def save_model_metrics(self, user_id: int, cv_accuracy: float,
                           cv_std: float, n_samples: int):
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO model_metrics(user_id,cv_accuracy,cv_std,n_samples) VALUES(?,?,?,?)",
                (user_id, cv_accuracy, cv_std, n_samples)
            )

    def get_model_history(self, user_id: int):
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM model_metrics WHERE user_id=? ORDER BY recorded_at DESC LIMIT 10",
                (user_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    def save_ai_prediction(self, user_id: int, sport: str, odds: float,
                           win_prob: float, recommendation: str,
                           ev: float, kelly: float):
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO ai_predictions
                   (user_id,sport,odds,win_prob,recommendation,ev,kelly)
                   VALUES(?,?,?,?,?,?,?)""",
                (user_id, sport, odds, win_prob, recommendation, ev, kelly)
            )
