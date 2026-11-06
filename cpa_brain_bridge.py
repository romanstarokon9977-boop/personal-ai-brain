import urllib.request
import urllib.parse
import json

def publish_cpa_gadget(
    product_url, title, description, price, image_url=None,
    dry_run=True, confirm_publish=False
):
    text = f"{title}\n\n{description}\n\n💰 **Цена:** {price}\n👉 [Купить на Маркете]({product_url})"
    
    if not dry_run and confirm_publish is not True:
        return {"ok": False, "error": "PUBLISH_CONFIRMATION_REQUIRED"}

    if dry_run:
        print("[DRY RUN] Сообщение сформировано:")
        print(text)
        return {"ok": True, "dry_run": True}
    
    try:
        import config
    except Exception as config_error:
        return {"ok": False, "error": f"CPA_CONFIG_UNAVAILABLE: {config_error}"}

    # Если есть ссылка на изображение — отправляем фото с подписью
    if image_url:
        url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendPhoto"
        payload = {
            "chat_id": config.TELEGRAM_CHANNEL_ID,
            "photo": image_url,
            "caption": text,
            "parse_mode": "Markdown"
        }
    else:
        url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": config.TELEGRAM_CHANNEL_ID,
            "text": text,
            "parse_mode": "Markdown"
        }
    
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    
    try:
        with urllib.request.urlopen(req) as response:
            res = json.loads(response.read().decode())
            return res
    except Exception as e:
        return {"ok": False, "error": str(e)}
