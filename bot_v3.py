import logging, os, asyncio
from io import BytesIO
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from database import Database
from analyzer import BettingAnalyzer
from ai_engine import AIEngine
from data_scraper import DataScraper
from history_fetcher import HistoryFetcher
from chart_generator import ChartGenerator
from value_analyzer import ValueAnalyzer
from beginner_guide import BeginnerGuide
from match_recommender import MatchRecommender
from ai_chat import AIChat

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

(MAIN_MENU, ADD_BET_SPORT, ADD_BET_EVENT, ADD_BET_AMOUNT, ADD_BET_ODDS, ADD_BET_RESULT,
 AI_PREDICT_SPORT, AI_PREDICT_ODDS, SEARCH_SPORT, HISTORY_LEAGUE,
 VALUE_LEAGUE, COMPARE_SPORT, MATCH_LEAGUE, MATCH_HOME, MATCH_AWAY, MATCH_ODDS_H,
 MATCH_ODDS_D, MATCH_ODDS_A, BEGINNER_GUIDE, RECOMMEND_LEAGUE, AI_CHAT) = range(21)

db = Database()
analyzer = BettingAnalyzer(db)
ai = AIEngine(db)
scraper = DataScraper(db)
history = HistoryFetcher(db)
charts = ChartGenerator(db)
value = ValueAnalyzer(db)
guide = BeginnerGuide()
recommender = MatchRecommender(db)
chat_ai = AIChat(db)

MAIN_KEYBOARD = ReplyKeyboardMarkup([
    [KeyboardButton("➕ Добавить ставку"), KeyboardButton("🤖 AI Прогноз")],
    [KeyboardButton("📊 Статистика"),      KeyboardButton("📈 Аналитика")],
    [KeyboardButton("📉 Графики"),         KeyboardButton("💎 Value Bet")],
    [KeyboardButton("🔍 Поиск матчей"),   KeyboardButton("🗂 Архив лиг")],
    [KeyboardButton("🔬 Анализ матча"),   KeyboardButton("🧠 Статус AI")],
    [KeyboardButton("📡 Линия"),          KeyboardButton("📋 История")],
    [KeyboardButton("📅 Ежедневная сводка")],
    [KeyboardButton("🎓 Гид для новичков")],
    [KeyboardButton("🎯 Рекомендации"), KeyboardButton("🌟 Ставка дня")],
    [KeyboardButton("💬 Спросить AI")],
], resize_keyboard=True)

from history_fetcher import LEAGUE_GROUPS, LEAGUES

def make_league_kb():
    from telegram import KeyboardButton
    rows = []
    for group, leagues in LEAGUE_GROUPS.items():
        rows.append([KeyboardButton(group)])
        for i in range(0, len(leagues), 2):
            pair = leagues[i:i+2]
            rows.append([KeyboardButton(l) for l in pair])
    rows.append([KeyboardButton("❌ Отмена")])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

LEAGUE_KB = make_league_kb()
ALL_LEAGUES = set(LEAGUES.keys())
GROUP_NAMES = set(LEAGUE_GROUPS.keys())

SPORT_KB = ReplyKeyboardMarkup([
    [KeyboardButton("Футбол"), KeyboardButton("Баскетбол")],
    [KeyboardButton("Теннис"), KeyboardButton("Хоккей")],
    [KeyboardButton("❌ Отмена")]
], resize_keyboard=True)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.ensure_user(user.id, user.username or user.first_name)
    await update.message.reply_text(
        f"👋 Привет, *{user.first_name}*!\n\n"
        "Я умный бот для анализа ставок с самообучающимся AI.\n\n"
        "🆕 *Новые функции:*\n"
        "• 📉 Графики прибыли по ставкам\n"
        "• 💎 Value Bet детектор\n"
        "• 🔬 Анализ конкретного матча\n"
        "• 🗂 Архив реальных матчей за 4 сезона",
        parse_mode='Markdown', reply_markup=MAIN_KEYBOARD
    )
    return MAIN_MENU


async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    uid = update.effective_user.id

    if text == "➕ Добавить ставку":
        await update.message.reply_text("🏅 На какой вид спорта?",
            reply_markup=ReplyKeyboardMarkup([[KeyboardButton("❌ Отмена")]], resize_keyboard=True))
        return ADD_BET_SPORT

    elif text == "🤖 AI Прогноз":
        await update.message.reply_text("🤖 На какой вид спорта?", parse_mode='Markdown', reply_markup=SPORT_KB)
        return AI_PREDICT_SPORT

    elif text == "📊 Статистика":
        await send_statistics(update, uid)

    elif text == "📈 Аналитика":
        text2 = analyzer.get_analytics(uid)
        if text2:
            await update.message.reply_text(text2, parse_mode='Markdown', reply_markup=MAIN_KEYBOARD)
        else:
            await update.message.reply_text("Добавьте минимум 5 ставок.", reply_markup=MAIN_KEYBOARD)

    elif text == "📉 Графики":
        await send_charts(update, uid)

    elif text == "💎 Value Bet":
        await update.message.reply_text(
            "💎 *Value Bet детектор*\n\nВыбери лигу для поиска недооценённых ставок:",
            parse_mode='Markdown', reply_markup=LEAGUE_KB)
        return VALUE_LEAGUE

    elif text == "🔍 Поиск матчей":
        context.user_data['mode'] = 'matches'
        await update.message.reply_text("🔍 Какой вид спорта?", reply_markup=SPORT_KB)
        return SEARCH_SPORT

    elif text == "📡 Линия":
        context.user_data['mode'] = 'odds'
        await update.message.reply_text("📡 Линия для какого спорта?", reply_markup=SPORT_KB)
        return SEARCH_SPORT

    elif text == "🗂 Архив лиг":
        await update.message.reply_text("🗂 Выбери лигу:", reply_markup=LEAGUE_KB)
        return HISTORY_LEAGUE

    elif text == "🔬 Анализ матча":
        await update.message.reply_text(
            "🔬 *Анализ матча*\n\nВыбери лигу:",
            parse_mode='Markdown', reply_markup=LEAGUE_KB)
        return MATCH_LEAGUE

    elif text == "🎯 Рекомендации":
        await update.message.reply_text(
            "🎯 *Рекомендации матчей*\n\nВыбери лигу — найду лучшие ставки:",
            parse_mode='Markdown', reply_markup=LEAGUE_KB
        )
        return RECOMMEND_LEAGUE

    elif text == "💬 Спросить AI":
        chat_ai.clear_history(uid)
        await update.message.reply_text(
            "💬 *AI-советник по ставкам*

"
            "Привет! Я BetMind — твой личный эксперт по беттингу.

"
            "Спрашивай всё что хочешь:
"
            "• Стоит ли ставить на конкретный матч?
"
            "• Как правильно управлять банкролом?
"
            "• Что такое value bet?
"
            "• Анализ твоей стратегии

"
            "Для выхода напиши /menu или «Выход»",
            parse_mode='Markdown',
            reply_markup=ReplyKeyboardMarkup(
                [[KeyboardButton("Выход из чата")]],
                resize_keyboard=True
            )
        )
        return AI_CHAT

    elif text == "📅 Ежедневная сводка":
        from scheduler import Scheduler
        sched = Scheduler(db, ai)
        summary = sched._build_daily_summary(uid)
        if summary:
            await update.message.reply_text(summary, parse_mode='Markdown', reply_markup=MAIN_KEYBOARD)
        else:
            stats = analyzer.get_statistics(uid)
            if stats['total_bets'] == 0:
                await update.message.reply_text(
                    "📅 *Ежедневная сводка*

Пока нет ставок за последние 7 дней.
Добавь первую ставку!",
                    parse_mode='Markdown', reply_markup=MAIN_KEYBOARD)
            else:
                p_icon = "💚" if stats['total_profit'] >= 0 else "🔴"
                await update.message.reply_text(
                    f"📅 *Сводка*

"
                    f"🎰 Всего ставок: *{stats['total_bets']}*
"
                    f"✅ Побед: *{stats['wins']}* ({stats['winrate']:.0f}%)
"
                    f"{p_icon} Прибыль: *{stats['total_profit']:+.0f} ₽*
"
                    f"📈 ROI: *{stats['roi']:+.1f}%*

"
                    f"_Добавляй ставки каждый день для детальной сводки_",
                    parse_mode='Markdown', reply_markup=MAIN_KEYBOARD)

    elif text == "🌟 Ставка дня":
        await update.message.reply_text("🌟 Ищу лучшую ставку дня по всем лигам... (30–60 сек)")
        result = await recommender.get_best_of_the_day()
        await update.message.reply_text(result, parse_mode='Markdown', reply_markup=MAIN_KEYBOARD)

    elif text == "🎓 Гид для новичков":
        stats = analyzer.get_statistics(uid)
        advice = BeginnerGuide.get_personal_advice(stats)
        await update.message.reply_text(
            advice + "

📖 Выбери тему для изучения:",
            parse_mode='Markdown',
            reply_markup=BeginnerGuide.get_topics_keyboard()
        )
        return BEGINNER_GUIDE

    elif text == "🧠 Статус AI":
        await update.message.reply_text(ai.get_model_info(uid), parse_mode='Markdown', reply_markup=MAIN_KEYBOARD)

    elif text == "📋 История":
        await send_history(update, uid)

    return MAIN_MENU


# ── Графики ──────────────────────────────────────────────

async def send_charts(update: Update, user_id: int):
    if not charts.available:
        await update.message.reply_text(
            "📉 *Для графиков нужен matplotlib*\n\n"
            "Установи командой:\n"
            "`pip install matplotlib`\n\n"
            "Потом перезапусти бота.",
            parse_mode='Markdown', reply_markup=MAIN_KEYBOARD)
        return

    await update.message.reply_text("📉 Генерирую графики...")

    sent = 0
    for name, func in [
        ("прибыли", lambda: charts.profit_chart(user_id)),
        ("по месяцам", lambda: charts.monthly_chart(user_id)),
        ("по спортам", lambda: charts.sport_chart(user_id)),
    ]:
        try:
            buf = func()
            if buf:
                await update.message.reply_photo(photo=buf, caption=f"📊 График {name}")
                sent += 1
        except Exception as e:
            logger.warning(f"Chart error {name}: {e}")

    if sent == 0:
        await update.message.reply_text(
            "😔 Недостаточно данных для графиков.\nДобавьте минимум 3 завершённые ставки.",
            reply_markup=MAIN_KEYBOARD)
    else:
        await update.message.reply_text("✅ Готово!", reply_markup=MAIN_KEYBOARD)


# ── Value Bet ─────────────────────────────────────────────

async def value_league(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "❌ Отмена":
        await update.message.reply_text("Отменено.", reply_markup=MAIN_KEYBOARD)
        return MAIN_MENU
    if text in GROUP_NAMES:
        return VALUE_LEAGUE
    if text not in ALL_LEAGUES:
        await update.message.reply_text("Выбери лигу из списка.", reply_markup=LEAGUE_KB)
        return VALUE_LEAGUE
    await update.message.reply_text(f"💎 Ищу value bet в {text}... (15–20 сек)")
    result = await value.find_value_bets(text)
    await update.message.reply_text(result, parse_mode='Markdown', reply_markup=MAIN_KEYBOARD)
    return MAIN_MENU


# ── Анализ матча ──────────────────────────────────────────

async def match_league(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "❌ Отмена":
        await update.message.reply_text("Отменено.", reply_markup=MAIN_KEYBOARD)
        return MAIN_MENU
    if text in GROUP_NAMES:
        return MATCH_LEAGUE
    if text not in ALL_LEAGUES:
        await update.message.reply_text("Выбери лигу из списка.", reply_markup=LEAGUE_KB)
        return MATCH_LEAGUE
    context.user_data['match_league'] = text
    await update.message.reply_text("🏠 Введи название команды хозяев (на английском):\n(например: Arsenal)")
    return MATCH_HOME

async def match_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['match_home'] = update.message.text
    await update.message.reply_text("✈️ Введи название команды гостей:")
    return MATCH_AWAY

async def match_away(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['match_away'] = update.message.text
    await update.message.reply_text("1️⃣ Введи кэф на победу хозяев:")
    return MATCH_ODDS_H

async def match_odds_h(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data['odds_h'] = float(update.message.text.replace(',', '.'))
    except ValueError:
        await update.message.reply_text("❌ Введи число, например: 1.85")
        return MATCH_ODDS_H
    await update.message.reply_text("🤝 Введи кэф на ничью:")
    return MATCH_ODDS_D

async def match_odds_d(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data['odds_d'] = float(update.message.text.replace(',', '.'))
    except ValueError:
        await update.message.reply_text("❌ Введи число, например: 3.40")
        return MATCH_ODDS_D
    await update.message.reply_text("2️⃣ Введи кэф на победу гостей:")
    return MATCH_ODDS_A

async def match_odds_a(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data['odds_a'] = float(update.message.text.replace(',', '.'))
    except ValueError:
        await update.message.reply_text("❌ Введи число, например: 4.50")
        return MATCH_ODDS_A

    d = context.user_data
    await update.message.reply_text("🔄 Загружаю данные и анализирую матч... (15–20 сек)")
    result = await value.analyze_match(
        d['match_home'], d['match_away'], d['match_league'],
        d['odds_h'], d['odds_d'], d['odds_a']
    )
    await update.message.reply_text(result, parse_mode='Markdown', reply_markup=MAIN_KEYBOARD)
    context.user_data.clear()
    return MAIN_MENU


# ── Добавление ставки ──────────────────────────────────────

async def add_bet_sport(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Отмена":
        await update.message.reply_text("Отменено.", reply_markup=MAIN_KEYBOARD)
        return MAIN_MENU
    context.user_data['sport'] = update.message.text
    await update.message.reply_text("⚽ Введите название события:")
    return ADD_BET_EVENT

async def add_bet_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['event'] = update.message.text
    await update.message.reply_text("💰 Введите сумму ставки (руб):")
    return ADD_BET_AMOUNT

async def add_bet_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text.replace(',', '.').replace(' ', ''))
        if amount <= 0: raise ValueError
        context.user_data['amount'] = amount
        await update.message.reply_text("📉 Введите коэффициент:")
        return ADD_BET_ODDS
    except ValueError:
        await update.message.reply_text("❌ Введите корректную сумму:")
        return ADD_BET_AMOUNT

async def add_bet_odds(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        odds = float(update.message.text.replace(',', '.'))
        if odds < 1.0: raise ValueError
        context.user_data['odds'] = odds
    except ValueError:
        await update.message.reply_text("❌ Коэффициент должен быть ≥ 1.0:")
        return ADD_BET_ODDS
    sport = context.user_data.get('sport', '')
    pred = ai.predict(update.effective_user.id, sport, odds)
    preview = ""
    if pred:
        ev = pred.get('expected_value', 0)
        preview = (f"\n\n🤖 {pred['rec_icon']} *{pred['recommendation']}*\n"
                   f"Вероятность: *{pred['win_probability']}%* | EV: *{ev:+.3f}*\n"
                   f"Ставка по Келли: *{pred['kelly_fraction']}%*")
    await update.message.reply_text(
        f"🎯 Каков результат?{preview}", parse_mode='Markdown',
        reply_markup=ReplyKeyboardMarkup([
            [KeyboardButton("✅ Выигрыш"), KeyboardButton("❌ Проигрыш")],
            [KeyboardButton("🔄 Возврат"), KeyboardButton("⏳ Ещё не сыграло")]
        ], resize_keyboard=True))
    return ADD_BET_RESULT

async def add_bet_result(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result_map = {"✅ Выигрыш": "win", "❌ Проигрыш": "loss",
                  "🔄 Возврат": "refund", "⏳ Ещё не сыграло": "pending"}
    result = result_map.get(update.message.text)
    if not result:
        await update.message.reply_text("Выберите один из вариантов.")
        return ADD_BET_RESULT
    uid = update.effective_user.id
    d = context.user_data
    profit = round(d['amount'] * d['odds'] - d['amount'], 2) if result == "win" else (-d['amount'] if result == "loss" else 0.0)
    db.add_bet(user_id=uid, sport=d['sport'], event=d['event'],
               amount=d['amount'], odds=d['odds'], result=result, profit=profit)
    try: ai.retrain_if_needed(uid)
    except Exception as e: logger.warning(f"Retrain: {e}")
    icons = {"win": "✅", "loss": "❌", "refund": "🔄", "pending": "⏳"}
    profit_str = f"+{profit:.2f} ₽" if profit > 0 else f"{profit:.2f} ₽" if profit < 0 else "0 ₽"
    await update.message.reply_text(
        f"✅ *Ставка записана!*\n{d['sport']} | {d['event']}\n"
        f"💰 {d['amount']:.0f}₽ × {d['odds']} = {profit_str} {icons[result]}",
        parse_mode='Markdown', reply_markup=MAIN_KEYBOARD)
    context.user_data.clear()
    return MAIN_MENU


# ── AI прогноз ─────────────────────────────────────────────

async def ai_predict_sport(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Отмена":
        await update.message.reply_text("Отменено.", reply_markup=MAIN_KEYBOARD)
        return MAIN_MENU
    context.user_data['ai_sport'] = update.message.text
    await update.message.reply_text(f"🎯 Введи коэффициент на *{update.message.text}*:", parse_mode='Markdown')
    return AI_PREDICT_ODDS

async def ai_predict_odds(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        odds = float(update.message.text.replace(',', '.'))
        if odds < 1.0: raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Введите корректный коэффициент:")
        return AI_PREDICT_ODDS
    uid = update.effective_user.id
    sport = context.user_data.get('ai_sport', '?')
    await update.message.reply_text("🤖 Анализирую...")
    pred = ai.predict(uid, sport, odds)
    if not pred:
        await update.message.reply_text("❌ Добавь 10+ завершённых ставок.", reply_markup=MAIN_KEYBOARD)
        return MAIN_MENU
    db.save_ai_prediction(uid, sport, odds, pred['win_probability'],
                          pred['recommendation'], pred.get('expected_value', 0), pred.get('kelly_fraction', 0))
    ev = pred.get('expected_value', 0)
    msg = (f"🤖 *AI Прогноз — {sport}* | кэф {odds}\n\n"
           f"{pred['rec_icon']} *{pred['recommendation']}*\n\n"
           f"📊 Вероятность: *{pred['win_probability']}%*\n"
           f"{'✅' if ev>=0 else '❌'} EV: *{ev:+.3f}*\n"
           f"💡 Ставка по Келли: *{pred['kelly_fraction']}%*\n"
           f"🧠 Уверенность: *{pred.get('confidence','?')}%*")
    if pred.get('model_accuracy'):
        msg += f"\n🎯 Точность модели: *{pred['model_accuracy']}%*"
    if pred.get('note') == 'heuristic':
        msg += "\n\n_⚠️ Статистический режим — добавь 15+ ставок для ML_"
    await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=MAIN_KEYBOARD)
    context.user_data.clear()
    return MAIN_MENU


# ── Поиск / архив ─────────────────────────────────────────

async def search_sport(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Отмена":
        context.user_data.pop('mode', None)
        await update.message.reply_text("Отменено.", reply_markup=MAIN_KEYBOARD)
        return MAIN_MENU
    sport = update.message.text
    mode = context.user_data.pop('mode', 'matches')
    await update.message.reply_text(f"🔄 Загружаю данные по {sport}...")
    msg = await (scraper.format_odds_message(sport) if mode == 'odds' else scraper.format_matches_message(sport))
    await update.message.reply_text(msg, parse_mode='Markdown', disable_web_page_preview=True, reply_markup=MAIN_KEYBOARD)
    return MAIN_MENU

async def history_league(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "❌ Отмена":
        await update.message.reply_text("Отменено.", reply_markup=MAIN_KEYBOARD)
        return MAIN_MENU
    # Если нажали заголовок группы — просто ждём выбора лиги
    if text in GROUP_NAMES:
        return HISTORY_LEAGUE
    if text not in ALL_LEAGUES:
        await update.message.reply_text("Выбери лигу из списка ниже.", reply_markup=LEAGUE_KB)
        return HISTORY_LEAGUE
    league = text
    await update.message.reply_text(f"⏳ Загружаю архив {league}... (15–20 сек)")
    data = await history.fetch_league_history(league)
    report = history.format_report(data)
    if len(report) > 4000: report = report[:4000] + "\n..."
    await update.message.reply_text(report, parse_mode='Markdown', reply_markup=MAIN_KEYBOARD)
    return MAIN_MENU


# ── Статистика / история ───────────────────────────────────

async def ai_chat_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    uid = update.effective_user.id

    if text in ("Выход из чата", "/menu", "❌ Закрыть"):
        chat_ai.clear_history(uid)
        await update.message.reply_text(
            "👋 Выходим из AI чата.", reply_markup=MAIN_KEYBOARD
        )
        return MAIN_MENU

    await update.message.reply_text("🤔 Думаю...")
    reply = await chat_ai.chat(uid, text)
    await update.message.reply_text(
        reply,
        parse_mode='Markdown',
        reply_markup=ReplyKeyboardMarkup(
            [[KeyboardButton("Выход из чата")]],
            resize_keyboard=True
        )
    )
    return AI_CHAT


async def recommend_league(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "❌ Отмена":
        await update.message.reply_text("Отменено.", reply_markup=MAIN_KEYBOARD)
        return MAIN_MENU
    if text in GROUP_NAMES:
        return RECOMMEND_LEAGUE
    if text not in ALL_LEAGUES:
        await update.message.reply_text("Выбери лигу из списка.", reply_markup=LEAGUE_KB)
        return RECOMMEND_LEAGUE
    await update.message.reply_text(f"🎯 Анализирую матчи {text}... (20–30 сек)")
    result = await recommender.get_recommendations(text)
    await update.message.reply_text(result, parse_mode='Markdown', reply_markup=MAIN_KEYBOARD)
    return MAIN_MENU


async def beginner_guide_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "❌ Закрыть гид":
        await update.message.reply_text("Удачных ставок! 🍀", reply_markup=MAIN_KEYBOARD)
        return MAIN_MENU
    if text == "🎲 Случайный совет":
        tip = BeginnerGuide.get_random_tip()
        await update.message.reply_text(tip, reply_markup=BeginnerGuide.get_topics_keyboard())
        return BEGINNER_GUIDE
    if text in BeginnerGuide.all_topic_names():
        lesson = BeginnerGuide.get_lesson(text)
        await update.message.reply_text(lesson, parse_mode='Markdown',
                                         reply_markup=BeginnerGuide.get_topics_keyboard())
        return BEGINNER_GUIDE
    await update.message.reply_text("Выбери тему из списка:", reply_markup=BeginnerGuide.get_topics_keyboard())
    return BEGINNER_GUIDE


async def send_statistics(update, user_id):
    stats = analyzer.get_statistics(user_id)
    if stats['total_bets'] == 0:
        await update.message.reply_text("Пока нет ставок.", reply_markup=MAIN_KEYBOARD)
        return
    p_icon = "💚" if stats['total_profit'] >= 0 else "🔴"
    r_icon = "📈" if stats['roi'] >= 0 else "📉"
    await update.message.reply_text(
        f"📊 *Статистика*\n\n"
        f"🎰 Всего: *{stats['total_bets']}* | ✅{stats['wins']} ❌{stats['losses']}\n"
        f"📈 Winrate: *{stats['winrate']:.1f}%*\n"
        f"💰 Поставлено: *{stats['total_staked']:.0f}₽*\n"
        f"{p_icon} Прибыль: *{stats['total_profit']:+.2f}₽*\n"
        f"{r_icon} ROI: *{stats['roi']:+.2f}%*\n\n"
        f"📐 Средний кэф: *{stats['avg_odds']:.2f}*\n"
        f"🏆 Лучшая серия: *{stats['best_streak']} побед*\n"
        f"💀 Худшая серия: *{stats['worst_streak']} поражений*",
        parse_mode='Markdown', reply_markup=MAIN_KEYBOARD)

async def send_history(update, user_id):
    bets = db.get_recent_bets(user_id, limit=10)
    if not bets:
        await update.message.reply_text("История пуста.", reply_markup=MAIN_KEYBOARD)
        return
    msg = "📋 *Последние 10 ставок:*\n\n"
    icons = {"win": "✅", "loss": "❌", "refund": "🔄", "pending": "⏳"}
    for b in bets:
        p = f" {b['profit']:+.0f}₽" if b['result'] in ('win','loss') else ""
        msg += f"{icons.get(b['result'],'❓')} *{b['sport']}* — {b['event'][:20]}\n   {b['amount']:.0f}₽×{b['odds']}{p} 📅{b['created_at'][:10]}\n\n"
    await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=MAIN_KEYBOARD)


async def export_command(update, context):
    csv_data = db.export_to_csv(update.effective_user.id)
    if not csv_data:
        await update.message.reply_text("Нет данных.")
        return
    buf = BytesIO(csv_data.encode('utf-8-sig'))
    buf.name = f"bets_{datetime.now().strftime('%Y%m%d')}.csv"
    await update.message.reply_document(document=buf, filename=buf.name)

async def cancel(update, context):
    context.user_data.clear()
    await update.message.reply_text("Отменено.", reply_markup=MAIN_KEYBOARD)
    return MAIN_MENU


def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    app = Application.builder().token(token).build()
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start), MessageHandler(filters.TEXT & ~filters.COMMAND, main_menu)],
        states={
            MAIN_MENU:       [MessageHandler(filters.TEXT & ~filters.COMMAND, main_menu)],
            ADD_BET_SPORT:   [MessageHandler(filters.TEXT & ~filters.COMMAND, add_bet_sport)],
            ADD_BET_EVENT:   [MessageHandler(filters.TEXT & ~filters.COMMAND, add_bet_event)],
            ADD_BET_AMOUNT:  [MessageHandler(filters.TEXT & ~filters.COMMAND, add_bet_amount)],
            ADD_BET_ODDS:    [MessageHandler(filters.TEXT & ~filters.COMMAND, add_bet_odds)],
            ADD_BET_RESULT:  [MessageHandler(filters.TEXT & ~filters.COMMAND, add_bet_result)],
            AI_PREDICT_SPORT:[MessageHandler(filters.TEXT & ~filters.COMMAND, ai_predict_sport)],
            AI_PREDICT_ODDS: [MessageHandler(filters.TEXT & ~filters.COMMAND, ai_predict_odds)],
            SEARCH_SPORT:    [MessageHandler(filters.TEXT & ~filters.COMMAND, search_sport)],
            HISTORY_LEAGUE:  [MessageHandler(filters.TEXT & ~filters.COMMAND, history_league)],
            VALUE_LEAGUE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, value_league)],
            MATCH_LEAGUE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, match_league)],
            MATCH_HOME:      [MessageHandler(filters.TEXT & ~filters.COMMAND, match_home)],
            MATCH_AWAY:      [MessageHandler(filters.TEXT & ~filters.COMMAND, match_away)],
            MATCH_ODDS_H:    [MessageHandler(filters.TEXT & ~filters.COMMAND, match_odds_h)],
            MATCH_ODDS_D:    [MessageHandler(filters.TEXT & ~filters.COMMAND, match_odds_d)],
            MATCH_ODDS_A:    [MessageHandler(filters.TEXT & ~filters.COMMAND, match_odds_a)],
            BEGINNER_GUIDE:  [MessageHandler(filters.TEXT & ~filters.COMMAND, beginner_guide_handler)],
            RECOMMEND_LEAGUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, recommend_league)],
            AI_CHAT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ai_chat_handler)],
        },
        fallbacks=[CommandHandler("cancel", cancel), CommandHandler("start", start)],
    )
    app.add_handler(conv)
    app.add_handler(CommandHandler("export", export_command))
    from scheduler import Scheduler
    scheduler = Scheduler(db, ai, app)

    async def post_init(application):
        asyncio.create_task(scheduler.run())

    app.post_init = post_init
    logger.info("Бот v3 запущен!")
    app.run_polling()

if __name__ == '__main__':
    main()
