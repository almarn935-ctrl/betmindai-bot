# Этот файл содержит новые handlers для bot_v3.py
# Добавь их содержимое в bot_v3.py перед функцией main()

async def value_bet_start(update, context):
    await update.message.reply_text(
        "🔍 *Value Bet Калькулятор*\n\n"
        "Введи коэффициент букмекера:",
        parse_mode='Markdown',
        reply_markup=ReplyKeyboardMarkup([[KeyboardButton("❌ Отмена")]], resize_keyboard=True)
    )
    return 10  # VALUE_BET_ODDS

async def value_bet_odds(update, context):
    if update.message.text == "❌ Отмена":
        await update.message.reply_text("Отменено.", reply_markup=MAIN_KEYBOARD)
        return 0
    try:
        odds = float(update.message.text.replace(',', '.'))
        if odds < 1.0: raise ValueError
        context.user_data['vb_odds'] = odds
        await update.message.reply_text(
            f"✅ Кэф: *{odds}*\n\n"
            f"Теперь введи свою оценку вероятности победы в % (например: 55):",
            parse_mode='Markdown'
        )
        return 11  # VALUE_BET_PROB
    except ValueError:
        await update.message.reply_text("❌ Введи корректный кэф:")
        return 10

async def value_bet_prob(update, context):
    if update.message.text == "❌ Отмена":
        await update.message.reply_text("Отменено.", reply_markup=MAIN_KEYBOARD)
        return 0
    try:
        prob = float(update.message.text.replace(',', '.').replace('%', ''))
        if not 1 <= prob <= 99: raise ValueError
        odds = context.user_data.get('vb_odds', 2.0)
        report = value_analyzer.format_value_report(odds, prob)
        await update.message.reply_text(report, parse_mode='Markdown', reply_markup=MAIN_KEYBOARD)
        context.user_data.clear()
        return 0
    except ValueError:
        await update.message.reply_text("❌ Введи число от 1 до 99:")
        return 11

async def chart_handler(update, context):
    user_id = update.effective_user.id
    await update.message.reply_text("📊 Генерирую графики...")
    chart = generate_profit_chart(db, user_id)
    if chart:
        from io import BytesIO
        await update.message.reply_photo(photo=BytesIO(chart), caption="📈 Динамика прибыли")
        sport_chart = generate_sport_chart(db, user_id)
        if sport_chart:
            await update.message.reply_photo(photo=BytesIO(sport_chart), caption="🏅 По видам спорта")
    else:
        await update.message.reply_text(
            "❌ Для графиков нужен matplotlib:\n`pip install matplotlib`\n\nИли добавь больше ставок.",
            parse_mode='Markdown', reply_markup=MAIN_KEYBOARD
        )

async def team_form_league(update, context):
    if update.message.text == "❌ Отмена":
        await update.message.reply_text("Отменено.", reply_markup=MAIN_KEYBOARD)
        return 0
    league = update.message.text
    context.user_data['form_league'] = league
    if league not in league_cache:
        await update.message.reply_text(f"⏳ Загружаю архив *{league}*...", parse_mode='Markdown')
        data = await history.fetch_league_history(league)
        if 'error' not in data:
            league_cache[league] = data.get('matches', [])
    await update.message.reply_text(
        "⚽ Введи название команды (на английском):\nНапример: Arsenal, Barcelona, Bayern",
        reply_markup=ReplyKeyboardMarkup([[KeyboardButton("❌ Отмена")]], resize_keyboard=True)
    )
    return 13  # TEAM_FORM_NAME

async def team_form_name(update, context):
    if update.message.text == "❌ Отмена":
        await update.message.reply_text("Отменено.", reply_markup=MAIN_KEYBOARD)
        return 0
    team = update.message.text
    league = context.user_data.get('form_league', '')
    matches = league_cache.get(league, [])
    report = await value_analyzer.get_team_form(team, matches)
    await update.message.reply_text(report, parse_mode='Markdown', reply_markup=MAIN_KEYBOARD)
    context.user_data.clear()
    return 0
