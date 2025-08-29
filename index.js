const TelegramBot = require('node-telegram-bot-api');
const Database = require('better-sqlite3');

const TOKEN = 'YOUR TELEGRAM BOT TOKEN';
const LEVEL_DB = new Database('levels.db');
const STATE_DB = new Database('bot_state.db');

STATE_DB.prepare(`
CREATE TABLE IF NOT EXISTS message_state (
  chat_id INTEGER PRIMARY KEY,
  user_msg_id INTEGER,
  bot_msg_id INTEGER
)
`).run();

const bot = new TelegramBot(TOKEN, { polling: true });

bot.onText(/^\/start$/, (msg) => {
    const chatId = msg.chat.id;
    const text = `👋 Привет! Это бот для игры *Words of Wonders*.

📚 Я могу показать тебе слова из любого уровня игры.

🔎 Используй команду:

/l100 — чтобы посмотреть слова из уровня 100  
(Буква *L*, не цифра 1 или I!)

💬 Просто замени 100 на нужный тебе уровень.

Удачи! 🎯`;

    bot.sendMessage(chatId, text, { parse_mode: 'Markdown' });
});

bot.onText(/^\/l(\d+)$/, (msg, match) => {
    const chatId = msg.chat.id;
    const level = parseInt(match[1]);
    handleLevel(chatId, level, msg.message_id);
});

bot.on('callback_query', query => {
    const chatId = query.message.chat.id;
    const messageId = query.message.message_id;

    const data = query.data;
    if (data.startsWith('next:')) {
        const nextLevel = parseInt(data.split(':')[1]);
        handleLevel(chatId, nextLevel, null, messageId);
        bot.answerCallbackQuery(query.id);
    }
});

function handleLevel(chatId, level, userMsgId = null, previousBotMsgId = null) {
    const state = STATE_DB.prepare(`
        SELECT user_msg_id, bot_msg_id FROM message_state WHERE chat_id = ?
    `).get(chatId);

    if (state) {
        if (state.user_msg_id) bot.deleteMessage(chatId, state.user_msg_id).catch(() => {});
        if (state.bot_msg_id) bot.deleteMessage(chatId, state.bot_msg_id).catch(() => {});
    }

    if (previousBotMsgId) {
        bot.deleteMessage(chatId, previousBotMsgId).catch(() => {});
    }

    const row = LEVEL_DB.prepare(`
        SELECT main_words, bonus_words FROM levels WHERE level = ?
    `).get(level);

    if (!row) {
        bot.sendMessage(chatId, `❌ Уровень ${level} не найден.`).then(botMsg => {
            if (userMsgId) saveState(chatId, userMsgId, botMsg.message_id);
        });
        return;
    }

    const mainWords = row.main_words.split(',').map(w => `🔹 ${w}`).join('\n');
    const bonusWords = row.bonus_words
        ? row.bonus_words.split(',').map(w => `▫️ <i>${w}</i>`).join('\n')
        : null;

    let text = `📘 <b>Уровень ${level}</b>\n\n🧩 <b>Основные слова:</b>\n${mainWords}`;
    if (bonusWords) {
        text += `\n\n🎁 <b>Бонусные слова:</b>\n${bonusWords}`;
    }

    bot.sendMessage(chatId, text, {
        parse_mode: 'HTML',
        reply_markup: {
            inline_keyboard: [[
                { text: '➡️ Следующий', callback_data: `next:${level + 1}` }
            ]]
        }
    }).then(botMsg => {
        if (userMsgId)
            saveState(chatId, userMsgId, botMsg.message_id);
        else
            saveState(chatId, null, botMsg.message_id);
    });
}

function saveState(chatId, userMsgId, botMsgId) {
    STATE_DB.prepare(`
        INSERT INTO message_state (chat_id, user_msg_id, bot_msg_id)
        VALUES (?, ?, ?)
        ON CONFLICT(chat_id) DO UPDATE SET
            user_msg_id=excluded.user_msg_id,
            bot_msg_id=excluded.bot_msg_id
    `).run(chatId, userMsgId, botMsgId);
}
