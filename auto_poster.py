import argparse
from cpa_brain_bridge import publish_cpa_gadget

# Настоящий оффер с корректной ссылкой на картинку товара
post_data = {
    "product_url": "https://market.yandex.ru/product--besprovodnye-naushniki-xiaomi-redmi-buds-5/102",
    "title": "🎧 Беспроводные наушники Xiaomi Redmi Buds 5",
    "description": "Шумоподавление до 46 дБ, прозрачный режим, чистый бас и до 40 часов работы с кейсом. Отличный вариант за свои деньги!",
    "price": "2 990 ₽",
    "image_url": "https://avatars.mds.yandex.net/get-mpic/5234821/img_id823129381923/orig"
}

def main(argv=None):
    parser = argparse.ArgumentParser(
        description="CPA-пост: по умолчанию только dry-run."
    )
    parser.add_argument(
        "--publish", action="store_true",
        help="Разрешить реальную публикацию в Telegram.",
    )
    args = parser.parse_args(argv)
    result = publish_cpa_gadget(
        product_url=post_data["product_url"],
        title=post_data["title"],
        description=post_data["description"],
        price=post_data["price"],
        image_url=post_data["image_url"],
        dry_run=not args.publish,
        confirm_publish=args.publish,
    )
    if result.get("ok") and result.get("dry_run"):
        print("🧪 Dry-run завершён. Пост не опубликован.")
    elif result.get("ok"):
        print("🚀 Пост опубликован.")
    else:
        print("❌ Ошибка публикации:", result)
    return result


if __name__ == "__main__":
    main()
