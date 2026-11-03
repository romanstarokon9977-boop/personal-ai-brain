import re

bot_token = input("Введите TELEGRAM_BOT_TOKEN из @BotFather: ").strip()
channel_id = "@gadget_deals_ru"

with open("config.py", "r", encoding="utf-8") as f:
    content = f.read()

content = re.sub(r'TELEGRAM_BOT_TOKEN\s*=\s*".*?"', f'TELEGRAM_BOT_TOKEN = "{bot_token}"', content)
content = re.sub(r'TELEGRAM_CHANNEL_ID\s*=\s*".*?"', f'TELEGRAM_CHANNEL_ID = "{channel_id}"', content)

with open("config.py", "w", encoding="utf-8") as f:
    f.write(content)

print("✅ Файл config.py успешно обновлен!")
