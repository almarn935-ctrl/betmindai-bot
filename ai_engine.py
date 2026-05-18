"""
ai_engine.py — самообучающийся AI для прогнозирования ставок

Архитектура:
  - RandomForestClassifier — основная модель (учится на твоих ставках)
  - LogisticRegression — калибровочная модель (вероятности)
  - GradientBoosting — ансамблевая модель для повышения точности
  - Модели сохраняются на диск и обновляются после каждой новой ставки
  - Confidence score — уверенность AI в прогнозе
  - Feature importance — что реально влияет на исход
"""

import os
import pickle
import logging
import math
from typing import Optional
from datetime import datetime
from database import Database

logger = logging.getLogger(__name__)

MODEL_DIR = "models"
os.makedirs(MODEL_DIR, exist_ok=True)


def _try_import():
    """Ленивый импорт sklearn — не всегда установлен"""
    try:
        from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import LabelEncoder, StandardScaler
        from sklearn.model_selection import cross_val_score
        from sklearn.calibration import CalibratedClassifierCV
        import numpy as np
        return True, {
            'RF': RandomForestClassifier,
            'GB': GradientBoostingClassifier,
            'LR': LogisticRegression,
            'LE': LabelEncoder,
            'SS': StandardScaler,
            'cv': cross_val_score,
            'Cal': CalibratedClassifierCV,
            'np': np,
        }
    except ImportError:
        return False, {}


class AIEngine:
    """
    Самообучающийся движок прогнозирования.

    Признаки (features) для каждой ставки:
      - коэффициент (odds)
      - implied probability = 1/odds
      - ROI пользователя в этом спорте
      - winrate пользователя в этом спорте
      - текущая серия (streak)
      - день недели ставки
      - час ставки
      - средний кэф пользователя
      - z-score кэфа относительно среднего пользователя
      - количество ставок в этом спорте (опыт)
    """

    FEATURE_NAMES = [
        "odds", "implied_prob", "sport_roi", "sport_winrate",
        "streak", "weekday", "hour", "user_avg_odds",
        "odds_zscore", "sport_experience"
    ]

    def __init__(self, db: Database):
        self.db = db
        self._sklearn_ok, self._sk = _try_import()
        self._models: dict = {}   # user_id -> {'rf': ..., 'gb': ..., 'scaler': ...}
        self._encoders: dict = {}  # user_id -> LabelEncoder for sports

    def _model_path(self, user_id: int) -> str:
        return os.path.join(MODEL_DIR, f"model_{user_id}.pkl")

    def _load_model(self, user_id: int) -> bool:
        path = self._model_path(user_id)
        if os.path.exists(path):
            try:
                with open(path, "rb") as f:
                    self._models[user_id] = pickle.load(f)
                return True
            except Exception as e:
                logger.warning(f"Model load error for {user_id}: {e}")
        return False

    def _save_model(self, user_id: int):
        path = self._model_path(user_id)
        try:
            with open(path, "wb") as f:
                pickle.dump(self._models[user_id], f)
        except Exception as e:
            logger.error(f"Model save error: {e}")

    # ──────────────────────────────────────────────
    # FEATURE ENGINEERING
    # ──────────────────────────────────────────────

    def _build_features(self, user_id: int, bets: list) -> tuple:
        """Строим матрицу признаков из истории ставок"""
        np = self._sk['np']

        # Рассчитываем статистику по видам спорта
        sport_stats: dict = {}
        for b in bets:
            s = b['sport'].lower()
            if s not in sport_stats:
                sport_stats[s] = {'wins': 0, 'total': 0, 'profit': 0, 'staked': 0}
            if b['result'] in ('win', 'loss'):
                sport_stats[s]['total'] += 1
                sport_stats[s]['profit'] += b['profit']
                sport_stats[s]['staked'] += b['amount']
                if b['result'] == 'win':
                    sport_stats[s]['wins'] += 1

        # Средний кэф пользователя
        decided = [b for b in bets if b['result'] in ('win', 'loss')]
        avg_odds = (sum(b['odds'] for b in decided) / len(decided)) if decided else 2.0
        std_odds = float(np.std([b['odds'] for b in decided])) if len(decided) > 1 else 1.0

        # Строим серии
        streak_map = {}  # индекс -> текущая серия перед этой ставкой
        cur_streak = 0
        streak_type = None
        for i, b in enumerate(bets):
            streak_map[i] = cur_streak if streak_type == 'win' else -cur_streak
            if b['result'] == 'win':
                cur_streak = cur_streak + 1 if streak_type == 'win' else 1
                streak_type = 'win'
            elif b['result'] == 'loss':
                cur_streak = cur_streak + 1 if streak_type == 'loss' else 1
                streak_type = 'loss'
            else:
                cur_streak = 0
                streak_type = None

        X, y = [], []
        for i, b in enumerate(bets):
            if b['result'] not in ('win', 'loss'):
                continue
            sport = b['sport'].lower()
            ss = sport_stats.get(sport, {})
            st = ss.get('total', 0)
            sw = ss.get('wins', 0)
            sp = ss.get('profit', 0)
            sk = ss.get('staked', 1)

            sport_winrate = sw / st if st > 0 else 0.5
            sport_roi = (sp / sk * 100) if sk > 0 else 0.0
            odds = b['odds']
            implied_prob = 1.0 / odds if odds > 0 else 0.5
            z_score = (odds - avg_odds) / (std_odds or 1.0)

            # Время ставки
            try:
                dt = datetime.fromisoformat(b['created_at'])
                weekday = dt.weekday()
                hour = dt.hour
            except Exception:
                weekday, hour = 3, 12

            streak = streak_map.get(i, 0)

            X.append([
                odds, implied_prob, sport_roi, sport_winrate,
                streak, weekday, hour, avg_odds, z_score, st
            ])
            y.append(1 if b['result'] == 'win' else 0)

        return np.array(X) if X else None, np.array(y) if y else None

    # ──────────────────────────────────────────────
    # ОБУЧЕНИЕ
    # ──────────────────────────────────────────────

    def train(self, user_id: int) -> dict:
        """
        Обучить/дообучить модель на всех ставках пользователя.
        Возвращает метрики.
        """
        if not self._sklearn_ok:
            return {"error": "sklearn_not_installed"}

        bets = self.db.get_all_bets(user_id)
        decided = [b for b in bets if b['result'] in ('win', 'loss')]

        if len(decided) < 15:
            return {"error": "not_enough_data", "count": len(decided)}

        X, y = self._build_features(user_id, bets)
        if X is None or len(X) < 15:
            return {"error": "feature_error"}

        np = self._sk['np']
        RF = self._sk['RF']
        GB = self._sk['GB']
        SS = self._sk['SS']
        cv = self._sk['cv']

        scaler = SS()
        X_scaled = scaler.fit_transform(X)

        # Основная модель — Random Forest
        rf = RF(
            n_estimators=200,
            max_depth=6,
            min_samples_leaf=3,
            class_weight='balanced',
            random_state=42,
            n_jobs=-1
        )
        rf.fit(X_scaled, y)

        # Ансамблевая — Gradient Boosting
        gb = GB(
            n_estimators=100,
            learning_rate=0.05,
            max_depth=4,
            random_state=42
        )
        gb.fit(X_scaled, y)

        # Кросс-валидация (оценка качества)
        n_splits = min(5, max(2, len(y) // 5))
        try:
            cv_scores = cv(rf, X_scaled, y, cv=n_splits, scoring='accuracy')
            cv_mean = float(np.mean(cv_scores))
            cv_std = float(np.std(cv_scores))
        except Exception:
            cv_mean, cv_std = 0.0, 0.0

        # Важность признаков
        importances = rf.feature_importances_
        feature_importance = dict(zip(self.FEATURE_NAMES, importances.tolist()))

        self._models[user_id] = {
            'rf': rf,
            'gb': gb,
            'scaler': scaler,
            'trained_at': datetime.now().isoformat(),
            'n_samples': len(y),
            'cv_accuracy': cv_mean,
            'cv_std': cv_std,
            'feature_importance': feature_importance,
            'class_balance': float(np.mean(y)),
        }
        self._save_model(user_id)
        self.db.save_model_metrics(user_id, cv_mean, cv_std, len(y))

        return {
            "cv_accuracy": cv_mean,
            "cv_std": cv_std,
            "n_samples": len(y),
            "feature_importance": feature_importance,
        }

    # ──────────────────────────────────────────────
    # ПРОГНОЗ
    # ──────────────────────────────────────────────

    def predict(self, user_id: int, sport: str, odds: float,
                amount: Optional[float] = None) -> Optional[dict]:
        """
        Прогноз для новой ставки.
        Возвращает вероятность победы, рекомендацию и уверенность.
        """
        if not self._sklearn_ok:
            return self._heuristic_predict(user_id, sport, odds)

        # Загружаем или обучаем модель
        if user_id not in self._models:
            if not self._load_model(user_id):
                result = self.train(user_id)
                if "error" in result:
                    return self._heuristic_predict(user_id, sport, odds)

        model_data = self._models.get(user_id)
        if not model_data:
            return self._heuristic_predict(user_id, sport, odds)

        np = self._sk['np']
        bets = self.db.get_all_bets(user_id)
        decided = [b for b in bets if b['result'] in ('win', 'loss')]

        # Собираем контекст для одной ставки
        avg_odds = (sum(b['odds'] for b in decided) / len(decided)) if decided else 2.0
        odds_list = [b['odds'] for b in decided]
        std_odds = float(np.std(odds_list)) if len(odds_list) > 1 else 1.0

        # Статистика по спорту
        sport_bets = [b for b in decided if b['sport'].lower() == sport.lower()]
        sport_wins = sum(1 for b in sport_bets if b['result'] == 'win')
        sport_total = len(sport_bets)
        sport_winrate = sport_wins / sport_total if sport_total > 0 else 0.5
        sport_profit = sum(b['profit'] for b in sport_bets)
        sport_staked = sum(b['amount'] for b in sport_bets if b['result'] != 'refund')
        sport_roi = (sport_profit / sport_staked * 100) if sport_staked > 0 else 0.0

        # Текущая серия
        streak_results = [b['result'] for b in decided[-10:]]
        streak = 0
        if streak_results:
            last = streak_results[-1]
            for r in reversed(streak_results):
                if r == last:
                    streak += 1
                else:
                    break
            if last == 'loss':
                streak = -streak

        implied_prob = 1.0 / odds if odds > 0 else 0.5
        z_score = (odds - avg_odds) / (std_odds or 1.0)
        now = datetime.now()

        x = np.array([[
            odds, implied_prob, sport_roi, sport_winrate,
            streak, now.weekday(), now.hour, avg_odds, z_score, sport_total
        ]])
        x_scaled = model_data['scaler'].transform(x)

        # Предсказание от обеих моделей
        rf_prob = model_data['rf'].predict_proba(x_scaled)[0][1]
        gb_prob = model_data['gb'].predict_proba(x_scaled)[0][1]
        ensemble_prob = 0.6 * rf_prob + 0.4 * gb_prob

        # Уверенность модели (насколько она уверена в прогнозе)
        confidence = abs(ensemble_prob - 0.5) * 2  # 0..1

        # Kelly criterion для размера ставки
        kelly = self._kelly(ensemble_prob, odds)

        # Рекомендация
        if ensemble_prob >= 0.65:
            recommendation = "✅ СТАВИТЬ"
            rec_icon = "🟢"
        elif ensemble_prob >= 0.55:
            recommendation = "🤔 ВОЗМОЖНО"
            rec_icon = "🟡"
        elif ensemble_prob >= 0.45:
            recommendation = "⚠️ РИСКОВАННО"
            rec_icon = "🟠"
        else:
            recommendation = "❌ НЕ СТАВИТЬ"
            rec_icon = "🔴"

        # Ожидаемая ценность (EV)
        ev = ensemble_prob * (odds - 1) - (1 - ensemble_prob)

        return {
            "win_probability": round(ensemble_prob * 100, 1),
            "rf_probability": round(rf_prob * 100, 1),
            "gb_probability": round(gb_prob * 100, 1),
            "confidence": round(confidence * 100, 1),
            "recommendation": recommendation,
            "rec_icon": rec_icon,
            "kelly_fraction": round(kelly * 100, 1),
            "expected_value": round(ev, 3),
            "model_accuracy": round(model_data.get('cv_accuracy', 0) * 100, 1),
            "trained_on": model_data.get('n_samples', 0),
            "feature_importance": model_data.get('feature_importance', {}),
        }

    def _kelly(self, prob: float, odds: float) -> float:
        """Критерий Келли для оптимального размера ставки"""
        b = odds - 1  # чистый выигрыш на единицу
        q = 1 - prob
        kelly = (b * prob - q) / b if b > 0 else 0
        return max(0.0, min(kelly * 0.25, 0.15))  # четверть Келли, max 15%

    # ──────────────────────────────────────────────
    # ЭВРИСТИЧЕСКИЙ РЕЗЕРВ (без sklearn)
    # ──────────────────────────────────────────────

    def _heuristic_predict(self, user_id: int, sport: str, odds: float) -> dict:
        """Упрощённый прогноз на основе статистики пользователя"""
        bets = self.db.get_all_bets(user_id)
        decided = [b for b in bets if b['result'] in ('win', 'loss')]
        sport_bets = [b for b in decided if b['sport'].lower() == sport.lower()]

        if not decided:
            implied = 1.0 / odds
            return {
                "win_probability": round(implied * 100, 1),
                "recommendation": "❓ Мало данных",
                "rec_icon": "⚪",
                "kelly_fraction": 0,
                "expected_value": 0,
                "model_accuracy": 0,
                "trained_on": 0,
                "note": "heuristic"
            }

        global_wr = sum(1 for b in decided if b['result'] == 'win') / len(decided)
        sport_wr = (
            sum(1 for b in sport_bets if b['result'] == 'win') / len(sport_bets)
            if sport_bets else global_wr
        )
        avg_odds = sum(b['odds'] for b in decided) / len(decided)

        # Взвешиваем: имплицитная вероятность + исторический WR
        implied = 1.0 / odds
        weight_history = min(len(sport_bets) / 20, 0.6)
        prob = implied * (1 - weight_history) + sport_wr * weight_history

        # Корректировка на основе разницы кэфа от среднего
        if odds < avg_odds * 0.8:
            prob = min(prob * 1.05, 0.95)
        elif odds > avg_odds * 1.3:
            prob = prob * 0.95

        kelly = self._kelly(prob, odds)
        ev = prob * (odds - 1) - (1 - prob)

        if prob >= 0.60:
            rec, icon = "✅ СТАВИТЬ", "🟢"
        elif prob >= 0.50:
            rec, icon = "🤔 ВОЗМОЖНО", "🟡"
        else:
            rec, icon = "❌ НЕ СТАВИТЬ", "🔴"

        return {
            "win_probability": round(prob * 100, 1),
            "recommendation": rec,
            "rec_icon": icon,
            "kelly_fraction": round(kelly * 100, 1),
            "expected_value": round(ev, 3),
            "model_accuracy": 0,
            "trained_on": len(decided),
            "note": "heuristic"
        }

    # ──────────────────────────────────────────────
    # СТАТУС И INFO
    # ──────────────────────────────────────────────

    def get_model_info(self, user_id: int) -> str:
        if not self._sklearn_ok:
            return (
                "⚠️ *Режим: Эвристический*\n"
                "scikit-learn не установлен. Прогнозы работают на статистике.\n"
                "Для ML-режима: `pip install scikit-learn`"
            )
        if user_id not in self._models:
            self._load_model(user_id)
        model = self._models.get(user_id)
        if not model:
            bets = self.db.get_all_bets(user_id)
            decided = [b for b in bets if b['result'] in ('win', 'loss')]
            needed = 15 - len(decided)
            return (
                f"🤖 *AI модель ещё не обучена*\n\n"
                f"Нужно ещё *{needed}* завершённых ставок для обучения.\n"
                f"Сейчас: {len(decided)}/15"
            )

        fi = model.get('feature_importance', {})
        top_features = sorted(fi.items(), key=lambda x: x[1], reverse=True)[:3]
        feature_labels = {
            "odds": "коэффициент", "implied_prob": "имп. вероятность",
            "sport_roi": "ROI по спорту", "sport_winrate": "WR по спорту",
            "streak": "текущая серия", "weekday": "день недели",
            "hour": "время ставки", "user_avg_odds": "средний кэф",
            "odds_zscore": "отклонение кэфа", "sport_experience": "опыт в спорте"
        }

        lines = [
            "🤖 *Статус AI модели*\n",
            f"✅ Режим: *Machine Learning* (sklearn)",
            f"📊 Обучено на: *{model['n_samples']}* ставках",
            f"🎯 Точность CV: *{model['cv_accuracy']*100:.1f}% ± {model['cv_std']*100:.1f}%*",
            f"📅 Обновлена: {model['trained_at'][:16]}\n",
            "🔍 *Топ-3 важных фактора:*",
        ]
        for fname, fval in top_features:
            label = feature_labels.get(fname, fname)
            lines.append(f"  • {label}: {fval*100:.1f}%")

        lines.append("\n_Модель автоматически дообучается после каждой ставки_")
        return "\n".join(lines)

    def retrain_if_needed(self, user_id: int):
        """Вызывается после добавления ставки — дообучает если достаточно данных"""
        bets = self.db.get_all_bets(user_id)
        decided = [b for b in bets if b['result'] in ('win', 'loss')]
        if len(decided) >= 15 and len(decided) % 3 == 0:
            # Переобучаем каждые 3 новые ставки
            logger.info(f"Retraining model for user {user_id} ({len(decided)} samples)")
            self.train(user_id)
