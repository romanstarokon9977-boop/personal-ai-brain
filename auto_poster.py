import config
from cpa_brain_bridge import publish_cpa_gadget

# Настоящий оффер с корректной ссылкой на картинку товара
post_data = {
    "product_url": "https://market.yandex.ru/product--besprovodnye-naushniki-xiaomi-redmi-buds-5/102",
    "title": "🎧 Беспроводные наушники Xiaomi Redmi Buds 5",
    "description": "Шумоподавление до 46 дБ, прозрачный режим, чистый бас и до 40 часов работы с кейсом. Отличный вариант за свои деньги!",
    "price": "2 990 ₽",
    "image_url": "https://avatars.mds.yandex.net/get-mpic/5234821/img_id823129381923/orig"
}

if __name__ == "__main__":
    res = publish_cpa_gadget(
        product_url=post_data["product_url"],
        title=post_data["title"],
        description=post_data["description"],
        price=post_data["price"],
        image_url=post_data["image_url"]
    )
    if res.get("ok"):
        print("🚀 Пост успешно опубликован с настоящим изображением товара!")
    else:
        print("❌ Ошибка при публикации:", res)
