import json
import urllib.parse
import urllib.request


def publish_cpa_gadget(
    product_url, title, description, price, image_url=None,
    dry_run=True, confirm_publish=False
):
    """Build a CPA post; publishing is opt-in and requires explicit confirmation."""
    title = str(title or "").strip()
    description = str(description or "").strip()
    price = str(price or "").strip()
    product_url = str(product_url or "").strip()

    if not title:
        return {"ok": False, "error": "TITLE_REQUIRED"}
    if not description:
        return {"ok": False, "error": "DESCRIPTION_REQUIRED"}
    if not price:
        return {"ok": False, "error": "PRICE_REQUIRED"}

    parsed_url = urllib.parse.urlparse(product_url)
    if parsed_url.scheme != "https" or not parsed_url.netloc:
        return {"ok": False, "error": "INVALID_PRODUCT_URL"}

    text = (
        f"{title}\n\n{description}\n\n"
        f"💰 **Цена:** {price}\n👉 [Купить на Маркете]({product_url})"
    )

    if not dry_run and confirm_publish is not True:
        return {"ok": False, "error": "PUBLISH_CONFIRMATION_REQUIRED"}

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "result": f"[DRY_RUN SUCCESS]\n{text}",
            "post_text": text,
            "error": None,
        }

    try:
        import config
    except Exception as config_error:
        return {
            "ok": False,
            "error": f"CPA_CONFIG_UNAVAILABLE: {config_error}",
        }

    if image_url:
        url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendPhoto"
        payload = {
            "chat_id": config.TELEGRAM_CHANNEL_ID,
            "photo": image_url,
            "caption": text,
            "parse_mode": "Markdown",
        }
    else:
        url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": config.TELEGRAM_CHANNEL_ID,
            "text": text,
            "parse_mode": "Markdown",
        }

    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )

    try:
        with urllib.request.urlopen(request) as response:
            result = json.loads(response.read().decode("utf-8"))
            if isinstance(result, dict):
                result.setdefault("post_text", text)
            return result
    except Exception as error:
        return {"ok": False, "error": str(error)}
