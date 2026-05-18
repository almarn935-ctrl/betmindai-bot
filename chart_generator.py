"""
chart_generator.py — генерация графиков прибыли и статистики
"""
import io
import logging
from database import Database

logger = logging.getLogger(__name__)


def _try_import():
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import numpy as np
        return True, plt, np
    except ImportError:
        return False, None, None


class ChartGenerator:
    def __init__(self, db: Database):
        self.db = db
        self._ok, self._plt, self._np = _try_import()

    def _style(self, plt):
        plt.rcParams.update({
            'figure.facecolor': '#1a1a2e',
            'axes.facecolor': '#16213e',
            'axes.edgecolor': '#0f3460',
            'axes.labelcolor': '#e0e0e0',
            'xtick.color': '#a0a0a0',
            'ytick.color': '#a0a0a0',
            'text.color': '#e0e0e0',
            'grid.color': '#0f3460',
            'grid.alpha': 0.5,
        })

    def profit_chart(self, user_id: int):
        if not self._ok:
            return None
        plt, np = self._plt, self._np
        bets = self.db.get_all_bets(user_id)
        decided = [b for b in bets if b['result'] in ('win', 'loss')]
        if len(decided) < 3:
            return None

        self._style(plt)
        profits = [b['profit'] for b in decided]
        cumulative = list(np.cumsum(profits))
        x = list(range(1, len(cumulative) + 1))

        fig, axes = plt.subplots(2, 1, figsize=(10, 7), gridspec_kw={'height_ratios': [3, 1]})
        fig.suptitle('Анализ прибыли', fontsize=14, fontweight='bold', color='#e0e0e0')

        ax1 = axes[0]
        color = '#00d4aa' if cumulative[-1] >= 0 else '#ff4757'
        ax1.plot(x, cumulative, color=color, linewidth=2)
        ax1.fill_between(x, cumulative, 0,
                         where=[c >= 0 for c in cumulative], alpha=0.3, color='#00d4aa', label='Прибыль')
        ax1.fill_between(x, cumulative, 0,
                         where=[c < 0 for c in cumulative], alpha=0.3, color='#ff4757', label='Убыток')
        ax1.axhline(y=0, color='#ffffff', linewidth=0.8, alpha=0.5, linestyle='--')
        ax1.set_ylabel('Прибыль (руб)', fontsize=10)
        ax1.set_title('Кумулятивная прибыль', fontsize=11, color='#a0a0a0')
        ax1.grid(True, alpha=0.3)
        ax1.legend(fontsize=9)
        final = cumulative[-1]
        ax1.annotate(f'{final:+.0f} руб', xy=(x[-1], final), fontsize=11,
                     fontweight='bold', color='#00d4aa' if final >= 0 else '#ff4757',
                     ha='right', bbox=dict(boxstyle='round,pad=0.3', facecolor='#1a1a2e', alpha=0.8))

        ax2 = axes[1]
        colors = ['#00d4aa' if p >= 0 else '#ff4757' for p in profits]
        ax2.bar(x, profits, color=colors, alpha=0.8, width=0.8)
        ax2.axhline(y=0, color='#ffffff', linewidth=0.5, alpha=0.5)
        ax2.set_xlabel('Ставка №', fontsize=10)
        ax2.set_ylabel('руб', fontsize=9)
        ax2.set_title('Результат каждой ставки', fontsize=10, color='#a0a0a0')
        ax2.grid(True, alpha=0.2, axis='y')

        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=120, bbox_inches='tight', facecolor='#1a1a2e')
        plt.close()
        buf.seek(0)
        return buf

    def monthly_chart(self, user_id: int):
        if not self._ok:
            return None
        plt, np = self._plt, self._np
        monthly = self.db.get_monthly_stats(user_id)
        if len(monthly) < 2:
            return None

        self._style(plt)
        months = [m['month'] for m in monthly]
        profits = [m['profit'] for m in monthly]
        winrates = [(m['wins'] / m['total'] * 100) if m['total'] > 0 else 0 for m in monthly]

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 7))
        fig.suptitle('Статистика по месяцам', fontsize=14, fontweight='bold', color='#e0e0e0')

        colors = ['#00d4aa' if p >= 0 else '#ff4757' for p in profits]
        bars = ax1.bar(months, profits, color=colors, alpha=0.85, width=0.6)
        ax1.axhline(y=0, color='#ffffff', linewidth=0.8, alpha=0.5, linestyle='--')
        ax1.set_ylabel('Прибыль (руб)', fontsize=10)
        ax1.set_title('Прибыль/убыток по месяцам', fontsize=11, color='#a0a0a0')
        ax1.grid(True, alpha=0.3, axis='y')
        for bar, val in zip(bars, profits):
            ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                     f'{val:+.0f}', ha='center',
                     va='bottom' if val >= 0 else 'top', fontsize=8, color='#e0e0e0')
        plt.setp(ax1.xaxis.get_majorticklabels(), rotation=45, ha='right')

        ax2.plot(months, winrates, color='#ffd700', linewidth=2, marker='o', markersize=6)
        ax2.fill_between(range(len(months)), winrates, alpha=0.2, color='#ffd700')
        ax2.axhline(y=50, color='#ffffff', linewidth=0.8, alpha=0.4, linestyle='--', label='50%')
        ax2.set_ylim(0, 100)
        ax2.set_ylabel('Winrate (%)', fontsize=10)
        ax2.set_title('Процент побед по месяцам', fontsize=11, color='#a0a0a0')
        ax2.set_xticks(range(len(months)))
        ax2.set_xticklabels(months, rotation=45, ha='right')
        ax2.grid(True, alpha=0.3)
        ax2.legend(fontsize=9)

        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=120, bbox_inches='tight', facecolor='#1a1a2e')
        plt.close()
        buf.seek(0)
        return buf

    def sport_chart(self, user_id: int):
        if not self._ok:
            return None
        plt, np = self._plt, self._np
        sport_stats = [s for s in self.db.get_stats_by_sport(user_id) if s['total'] >= 2]
        if not sport_stats:
            return None

        self._style(plt)
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 6))
        fig.suptitle('Анализ по видам спорта', fontsize=14, fontweight='bold', color='#e0e0e0')

        palette = ['#00d4aa', '#ffd700', '#ff6b6b', '#a29bfe', '#fd79a8', '#74b9ff']
        sports = [s['sport'] for s in sport_stats]
        totals = [s['total'] for s in sport_stats]
        ax1.pie(totals, labels=sports, colors=palette[:len(sports)],
                autopct='%1.0f%%', startangle=90,
                textprops={'color': '#e0e0e0', 'fontsize': 9})
        ax1.set_title('Доля ставок', fontsize=11, color='#a0a0a0')

        rois = [(s['total_profit'] / s['total_staked'] * 100) if s['total_staked'] else 0
                for s in sport_stats]
        colors_roi = ['#00d4aa' if r >= 0 else '#ff4757' for r in rois]
        bars = ax2.barh(list(range(len(sports))), rois, color=colors_roi, alpha=0.85, height=0.6)
        ax2.axvline(x=0, color='#ffffff', linewidth=0.8, alpha=0.5)
        ax2.set_yticks(list(range(len(sports))))
        ax2.set_yticklabels(sports, fontsize=10)
        ax2.set_xlabel('ROI (%)', fontsize=10)
        ax2.set_title('ROI по видам спорта', fontsize=11, color='#a0a0a0')
        ax2.grid(True, alpha=0.3, axis='x')
        for bar, val in zip(bars, rois):
            ax2.text(val + (0.3 if val >= 0 else -0.3),
                     bar.get_y() + bar.get_height() / 2,
                     f'{val:+.1f}%', va='center',
                     ha='left' if val >= 0 else 'right', fontsize=9, color='#e0e0e0')

        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=120, bbox_inches='tight', facecolor='#1a1a2e')
        plt.close()
        buf.seek(0)
        return buf

    @property
    def available(self):
        return self._ok
