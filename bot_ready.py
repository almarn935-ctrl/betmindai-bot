import logging
import os
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler
)
from database import Database
from analyzer import BettingAnalyzer
from ai_engine import AIEngine
from data_scraper import DataScraper
from history_fetcher import HistoryFetcher
from datetime import datetime
from io import BytesIO

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

(MAIN_MENU, ADD_BET_SPORT, ADD_BET_EVENT, ADD_BET_AMOUNT,
 ADD_BET_ODDS, ADD_BET_RESULT,
 AI_PREDICT_SPORT, AI_PREDICT_ODDS,
 SEARCH_SPORT, HISTORY_LEAGUE) = range(10)

db = Database()
analyzer = BettingAnalyzer(db)
ai = AIEngine(db)
scraper = DataScraper(db)
history = HistoryFetcher(db)

MAIN_KEYBOARD = ReplyKeyboardMarkup([
    [KeyboardButton("➕ Добавить ставку"), KeyboardButton("🤖 AI Прогноз")],
    [KeyboardButton("📊 Статистика"),      KeyboardButton("📈 Аналитика")],
    [KeyboardButton("🔍 Поиск матчей"),   KeyboardButton("📡 Линия")],
    [KeyboardButton("🧠 Статус AI"),      KeyboardButton("📋 История")],
    [KeyboardButton("🗂 Архив лиг")],
], resize_keyboard=True)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.ensure_user(user.id, user.username or user.first_name)
    await update.message.reply_text(
        f"👋 Привет, *{user.first_name}*!\n\n"
        "Я умный бот для анализа ставок с *самообучающимся AI*.\n\n"
        "🤖 *Возможности:*\n"
        "• Запись и хранение всех ставок\n"
        "• Поиск реальных матчей (ESPN API)\n"
        "• Актуальная линия букмекеров\n"
        "• ML-модель обучается на твоих данных\n"
        "• AI-прогноз с вероятностью и EV\n"
        "• Критерий Келли для размера ставки\n"
        "• 🗂 Архив реальных матчей за 4 сезона\n\n"
        "Выбери действие:",
        parse_mode='Markdown',
        reply_markup=MAIN_KEYBOARD
    )
    return MAIN_MENU


async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id

    if text == "➕ Добавить ставку":
        await update.message.reply_text(
            "🏅 На какой вид спорта?\n\nНапример: Футбол, Теннис, Баскетбол, Хоккей",
            reply_markup=ReplyKeyboardMarkup([[KeyboardButton("❌ Отмена")]], resize_keyboard=True)
        )
        return ADD_BET_SPORT

    elif text == "🤖 AI Прогноз":
        await update.message.reply_text(
            "🤖 *AI Прогноз*\n\nНа какой вид спорта хочешь поставить?",
            parse_mode='Markdown',
            reply_markup=ReplyKeyboardMarkup([
                [KeyboardButton("Футбол"), KeyboardButton("Теннис")],
                [KeyboardButton("Баскетбол"), KeyboardButton("Хоккей")],
                [KeyboardButton("❌ Отмена")]
            ], resize_keyboard=True)
        )
        return AI_PREDICT_SPORT

    elif text == "📊 Статистика":
        await send_statistics(update, user_id)

    elif text == "📈 Аналитика":
        await send_analytics(update, user_id)

    elif text == "🔍 Поиск матчей":
        context.user_data['mode'] = 'matches'
        await update.message.reply_text(
            "🔍 Матчи по какому виду спорта?",
            reply_markup=ReplyKeyboardMarkup([
                [KeyboardButton("Футбол"), KeyboardButton("Баскетбол")],
                [KeyboardButton("Теннис"), KeyboardButton("Хоккей")],
                [KeyboardButton("❌ Отмена")]
            ], resize_keyboard=True)
        )
        return SEARCH_SPORT

    elif text == "📡 Линия":
        context.user_data['mode'] = 'odds'
        await update.message.reply_text(
            "📡 Линия для какого спорта?",
            reply_markup=ReplyKeyboardMarkup([
                [KeyboardButton("Футбол"), KeyboardButton("Баскетбол")],
                [KeyboardButton("Хоккей"), KeyboardButton("Теннис")],
                [KeyboardButton("❌ Отмена")]
            ], resize_keyboard=True)
        )
        return SEARCH_SPORT

    elif text == "🧠 Статус AI":
        await update.message.reply_text(
            ai.get_model_info(user_id),
            parse_mode='Markdown',
            reply_markup=MAIN_KEYBOARD
        )

    elif text == "📋 История":
        await send_history(update, user_id)

    elif text == "🗂 Архив лиг":
        await update.message.reply_text(
            "🗂 *Анализ исторических данных*\n\n"
            "Выбери лигу — загружу результаты матчей\n"
            "за последние 4 сезона с коэффициентами букмекеров:",
            parse_mode='Markdown',
            reply_markup=ReplyKeyboardMarkup([
                [KeyboardButton("АПЛ"), KeyboardButton("Ла Лига")],
                [KeyboardButton("Бундеслига"), KeyboardButton("Серия А")],
                [KeyboardButton("Лига 1"), KeyboardButton("РПЛ")],
                [KeyboardButton("Эредивизи"), KeyboardButton("Примейра")],
                [KeyboardButton("❌ Отмена")]
            ], resize_keyboard=True)
        )
        return HISTORY_LEAGUE

    return MAIN_MENU


async def history_league(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Отмена":
        await update.message.reply_text("Отменено.", reply_markup=MAIN_KEYBOARD)
        return MAIN_MENU

    league = update.message.text
    await update.message.reply_text(
        f"⏳ Загружаю архив *{league}* за 4 сезона...\nЭто займёт 10–20 секунд.",
        parse_mode='Markdown'
    )

    data = await history.fetch_league_history(league)
    report = history.format_report(data)

    # Разбиваем если сообщение длинное
    if len(report) > 4000:
        report = report[:4000] + "\n..."

    await update.message.reply_text(report, parse_mode='Markdown', reply_markup=MAIN_KEYBOARD)
    return MAIN_MENU


async def add_bet_sport(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Отмена":
        await update.message.reply_text("Отменено.", reply_markup=MAIN_KEYBOARD)
        return MAIN_MENU
    context.user_data['sport'] = update.message.text
    await update.message.reply_text("⚽ Введите название события:\n(например: «Реал Мадрид — Барселона»)")
    return ADD_BET_EVENT

async def add_bet_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['event'] = update.message.text
    await update.message.reply_text("💰 Введите сумму ставки (в рублях):")
    return ADD_BET_AMOUNT

async def add_bet_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text.replace(',', '.').replace(' ', ''))
        if amount <= 0:
            raise ValueError
        context.user_data['amount'] = amount
        await update.message.reply_text("📉 Введите коэффициент (например: 1.85):")
        return ADD_BET_ODDS
    except ValueError:
        await update.message.reply_text("❌ Введите корректную сумму:")
        return ADD_BET_AMOUNT

async def add_bet_odds(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        odds = float(update.message.text.replace(',', '.'))
        if odds < 1.0:
            raise ValueError
        context.user_data['odds'] = odds
    except ValueError:
        await update.message.reply_text("❌ Коэффициент должен быть ≥ 1.0:")
        return ADD_BET_ODDS

    sport = context.user_data.get('sport', '')
    prediction = ai.predict(update.effective_user.id, sport, odds)
    preview = ""
    if prediction:
        ev = prediction.get('expected_value', 0)
        preview = (
            f"\n\n🤖 *AI говорит:* {prediction['rec_icon']} {prediction['recommendation']}\n"
            f"Вероятность победы: *{prediction['win_probability']}%*\n"
            f"Ожидаемая ценность (EV): *{ev:+.3f}*\n"
            f"Рекомендуемая ставка: *{prediction['kelly_fraction']}% банкрола*"
        )

    await update.message.reply_text(
        f"🎯 Каков результат ставки?{preview}",
        parse_mode='Markdown',
        reply_markup=ReplyKeyboardMarkup([
            [KeyboardButton("✅ Выигрыш"), KeyboardButton("❌ Проигрыш")],
            [KeyboardButton("🔄 Возврат"), KeyboardButton("⏳ Ещё не сыграло")]
        ], resize_keyboard=True)
    )
    return ADD_BET_RESULT

async def add_bet_result(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result_map = {
        "✅ Выигрыш": "win", "❌ Проигрыш": "loss",
        "🔄 Возврат": "refund", "⏳ Ещё не сыграло": "pending"
    }
    result = result_map.get(update.message.text)
    if not result:
        await update.message.reply_text("Выберите один из вариантов.")
        return ADD_BET_RESULT

    user_id = update.effective_user.id
    d = context.user_data
    profit = 0.0
    if result == "win":
        profit = round(d['amount'] * d['odds'] - d['amount'], 2)
    elif result == "loss":
        profit = -d['amount']

    db.add_bet(user_id=user_id, sport=d['sport'], event=d['event'],
               amount=d['amount'], odds=d['odds'], result=result, profit=profit)

    try:
        ai.retrain_if_needed(user_id)
    except Exception as e:
        logger.warning(f"Retrain skipped: {e}")

    icons = {"win": "✅", "loss": "❌", "refund": "🔄", "pending": "⏳"}
    profit_str = f"+{profit:.2f} ₽" if profit > 0 else f"{profit:.2f} ₽" if profit < 0 else "0 ₽"

    await update.message.reply_text(
        f"✅ *Ставка записана!*\n\n"
        f"🏅 {d['sport']} | {d['event']}\n"
        f"💰 {d['amount']:.2f} ₽ × {d['odds']} = {profit_str}\n"
        f"🎯 Результат: {icons[result]}\n\n"
        f"_AI обновляется автоматически_",
        parse_mode='Markdown',
        reply_markup=MAIN_KEYBOARD
    )
    context.user_data.clear()
    return MAIN_MENU


async def ai_predict_sport(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Отмена":
        await update.message.reply_text("Отменено.", reply_markup=MAIN_KEYBOARD)
        return MAIN_MENU
    context.user_data['ai_sport'] = update.message.text
    await update.message.reply_text(
        f"🎯 Введи коэффициент букмекера на событие по *{update.message.text}*:",
        parse_mode='Markdown'
    )
    return AI_PREDICT_ODDS

async def ai_predict_odds(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        odds = float(update.message.text.replace(',', '.'))
        if odds < 1.0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Введите корректный коэффициент (например: 2.15):")
        return AI_PREDICT_ODDS

    user_id = update.effective_user.id
    sport = context.user_data.get('ai_sport', 'Неизвестно')
    await update.message.reply_text("🤖 Анализирую данные...")

    prediction = ai.predict(user_id, sport, odds)
    if not prediction:
        await update.message.reply_text(
            "❌ Недостаточно данных.\nДобавь хотя бы 10 завершённых ставок.",
            reply_markup=MAIN_KEYBOARD
        )
        return MAIN_MENU

    db.save_ai_prediction(user_id, sport, odds,
                          prediction['win_probability'],
                          prediction['recommendation'],
                          prediction.get('expected_value', 0),
                          prediction.get('kelly_fraction', 0))

    ev = prediction.get('expected_value', 0)
    fi = prediction.get('feature_importance', {})
    feature_labels = {
        "odds": "кэф", "implied_prob": "имп. вер-ть",
        "sport_roi": "ROI по спорту", "sport_winrate": "WR по спорту",
        "streak": "серия", "weekday": "день нед.",
        "hour": "время", "user_avg_odds": "средний кэф",
        "odds_zscore": "откл. кэфа", "sport_experience": "опыт"
    }
    fi_text = ""
    if fi:
        top = sorted(fi.items(), key=lambda x: x[1], reverse=True)[:3]
        fi_text = "\n\n🔍 *Ключевые факторы:*\n" + "\n".join(
            f"  • {feature_labels.get(k, k)}: {v*100:.0f}%" for k, v in top
        )

    msg = (
        f"🤖 *AI Прогноз — {sport}*\n"
        f"💹 Коэффициент: *{odds}*\n\n"
        f"{prediction['rec_icon']} *{prediction['recommendation']}*\n\n"
        f"📊 Вероятность победы: *{prediction['win_probability']}%*\n"
    )
    if 'rf_probability' in prediction:
        msg += (
            f"  └ Random Forest: {prediction['rf_probability']}%\n"
            f"  └ Gradient Boost: {prediction['gb_probability']}%\n"
        )
    msg += (
        f"\n{'✅' if ev >= 0 else '❌'} Ожид. ценность (EV): *{ev:+.3f}*\n"
        f"💡 Ставка по Келли: *{prediction['kelly_fraction']}% банкрола*\n"
        f"🧠 Уверенность AI: *{prediction.get('confidence', '?')}%*"
    )
    if prediction.get('model_accuracy'):
        msg += f"\n🎯 Точность модели: *{prediction['model_accuracy']}%*"
    msg += fi_text
    if prediction.get('note') == 'heuristic':
        msg += "\n\n_⚠️ Статистический режим — добавь 15+ ставок для ML_"

    await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=MAIN_KEYBOARD)
    context.user_data.clear()
    return MAIN_MENU


async def search_sport(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Отмена":
        context.user_data.pop('mode', None)
        await update.message.reply_text("Отменено.", reply_markup=MAIN_KEYBOARD)
        return MAIN_MENU

    sport = update.message.text
    mode = context.user_data.pop('mode', 'matches')
    await update.message.reply_text(f"🔄 Загружаю данные по *{sport}*...", parse_mode='Markdown')

    if mode == 'odds':
        msg = await scraper.format_odds_message(sport)
    else:
        msg = await scraper.format_matches_message(sport)

    await update.message.reply_text(
        msg, parse_mode='Markdown',
        disable_web_page_preview=True,
        reply_markup=MAIN_KEYBOARD
    )
    return MAIN_MENU


async def send_statistics(update: Update, user_id: int):
    stats = analyzer.get_statistics(user_id)
    if stats['total_bets'] == 0:
        await update.message.reply_text("📊 Пока нет ставок. Добавьте первую!", reply_markup=MAIN_KEYBOARD)
        return
    roi_icon = "📈" if stats['roi'] >= 0 else "📉"
    profit_icon = "💚" if stats['total_profit'] >= 0 else "🔴"
    await update.message.reply_text(
        f"📊 *Статистика*\n\n"
        f"🎰 Всего: *{stats['total_bets']}*  |  ✅ {stats['wins']}  ❌ {stats['losses']}\n"
        f"📈 Winrate: *{stats['winrate']:.1f}%*\n"
        f"💰 Поставлено: *{stats['total_staked']:.0f} ₽*\n"
        f"{profit_icon} Прибыль: *{stats['total_profit']:+.2f} ₽*\n"
        f"{roi_icon} ROI: *{stats['roi']:+.2f}%*\n\n"
        f"📐 Средний кэф: *{stats['avg_odds']:.2f}*\n"
        f"💵 Средняя ставка: *{stats['avg_stake']:.0f} ₽*\n\n"
        f"🏆 Лучшая серия: *{stats['best_streak']} побед*\n"
        f"💀 Худшая серия: *{stats['worst_streak']} поражений*",
        parse_mode='Markdown', reply_markup=MAIN_KEYBOARD
    )

async def send_analytics(update: Update, user_id: int):
    text = analyzer.get_analytics(user_id)
    if not text:
        await update.message.reply_text("📈 Добавьте минимум 5 ставок для аналитики.", reply_markup=MAIN_KEYBOARD)
        return
    await update.message.reply_text(text, parse_mode='Markdown', reply_markup=MAIN_KEYBOARD)

async def send_history(update: Update, user_id: int):
    bets = db.get_recent_bets(user_id, limit=10)
    if not bets:
        await update.message.reply_text("📋 История пуста.", reply_markup=MAIN_KEYBOARD)
        return
    msg = "📋 *Последние 10 ставок:*\n\n"
    icons = {"win": "✅", "loss": "❌", "refund": "🔄", "pending": "⏳"}
    for b in bets:
        icon = icons.get(b['result'], "❓")
        p = f" {b['profit']:+.0f}₽" if b['result'] in ('win', 'loss') else ""
        msg += f"{icon} *{b['sport']}* — {b['event'][:22]}\n   {b['amount']:.0f}₽ × {b['odds']}{p}  📅{b['created_at'][:10]}\n\n"
    await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=MAIN_KEYBOARD)


async def export_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    csv_data = db.export_to_csv(update.effective_user.id)
    if not csv_data:
        await update.message.reply_text("Нет данных.")
        return
    buf = BytesIO(csv_data.encode('utf-8-sig'))
    buf.name = f"bets_{datetime.now().strftime('%Y%m%d')}.csv"
    await update.message.reply_document(document=buf, filename=buf.name, caption="📊 Ваши ставки")

async def retrain_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔄 Переобучаю AI модель...")
    result = ai.train(update.effective_user.id)
    if "error" in result:
        msgs = {
            "not_enough_data": f"❌ Мало данных: {result.get('count',0)}/15",
            "sklearn_not_installed": "❌ Установи: `pip install scikit-learn`",
            "feature_error": "❌ Ошибка признаков. Добавь больше ставок.",
        }
        await update.message.reply_text(msgs.get(result["error"], "❌ Ошибка."), parse_mode='Markdown')
        return
    top = sorted(result['feature_importance'].items(), key=lambda x: x[1], reverse=True)[:4]
    await update.message.reply_text(
        f"✅ *Модель обучена!*\n\n"
        f"🎯 Точность CV: *{result['cv_accuracy']*100:.1f}% ± {result['cv_std']*100:.1f}%*\n"
        f"📚 Обучено на: *{result['n_samples']}* ставках\n\n"
        f"Топ факторы:\n" + "\n".join(f"  • {k}: {v*100:.1f}%" for k, v in top),
        parse_mode='Markdown'
    )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Отменено.", reply_markup=MAIN_KEYBOARD)
    return MAIN_MENU


def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN", "8626920056:AAGrsygHfLE4ICxmcP3xWdcg4uSqpkOqB1o")
    if not token:
        raise ValueError("Установите TELEGRAM_BOT_TOKEN")

    app = Application.builder().token(token).build()

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(filters.TEXT & ~filters.COMMAND, main_menu)
        ],
        states={
            MAIN_MENU:        [MessageHandler(filters.TEXT & ~filters.COMMAND, main_menu)],
            ADD_BET_SPORT:    [MessageHandler(filters.TEXT & ~filters.COMMAND, add_bet_sport)],
            ADD_BET_EVENT:    [MessageHandler(filters.TEXT & ~filters.COMMAND, add_bet_event)],
            ADD_BET_AMOUNT:   [MessageHandler(filters.TEXT & ~filters.COMMAND, add_bet_amount)],
            ADD_BET_ODDS:     [MessageHandler(filters.TEXT & ~filters.COMMAND, add_bet_odds)],
            ADD_BET_RESULT:   [MessageHandler(filters.TEXT & ~filters.COMMAND, add_bet_result)],
            AI_PREDICT_SPORT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ai_predict_sport)],
            AI_PREDICT_ODDS:  [MessageHandler(filters.TEXT & ~filters.COMMAND, ai_predict_odds)],
            SEARCH_SPORT:     [MessageHandler(filters.TEXT & ~filters.COMMAND, search_sport)],
            HISTORY_LEAGUE:   [MessageHandler(filters.TEXT & ~filters.COMMAND, history_league)],
        },
        fallbacks=[CommandHandler("cancel", cancel), CommandHandler("start", start)],
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("export", export_command))
    app.add_handler(CommandHandler("retrain", retrain_command))

    logger.info("Бот запущен!")
    import asyncio
    asyncio.run(app.run_polling())


if __name__ == '__main__':
    main()
