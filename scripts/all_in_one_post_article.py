import os
import requests
from dotenv import load_dotenv
from requests.auth import HTTPBasicAuth
from amazon_paapi import AmazonApi
import google.generativeai as genai
import markdown
from mimetypes import guess_type

load_dotenv()

# ===== ジャンル設定（キーワード・Browse Node・カテゴリID・タグ）=====
GENRES = [
    {
        "name": "ワイヤレスイヤホン",
        "keyword": "ワイヤレスイヤホン",
        "browse_node": "3477981",
        "category_id": int(os.getenv("CATEGORY_ID_EARPHONES")),
        "tags": ["イヤホン", "Bluetooth", "高音質"]
    },
    {
        "name": "電子書籍リーダー",
        "keyword": "電子書籍リーダー",
        "browse_node": "2275256051",
        "category_id": int(os.getenv("CATEGORY_ID_EBOOKS")),
        "tags": ["電子書籍", "読書", "Kindle"]
    },
    {
        "name": "モバイルバッテリー",
        "keyword": "モバイルバッテリー",
        "browse_node": "2016926051",
        "category_id": int(os.getenv("CATEGORY_ID_BATTERIES")),
        "tags": ["充電", "モバイル", "持ち運び"]
    }
]

# ===== APIキー =====
ACCESS_KEY = os.getenv("AMAZON_ACCESS_KEY")
SECRET_KEY = os.getenv("AMAZON_SECRET_KEY")
ASSOCIATE_TAG = os.getenv("AMAZON_ASSOCIATE_TAG")
COUNTRY = "JP"

WP_URL = os.getenv("WP_URL")
USERNAME = os.getenv("WP_USERNAME")
APP_PASSWORD = os.getenv("WP_APP_PASSWORD")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

# ===== Amazon API初期化 =====
amazon = AmazonApi(
    ACCESS_KEY, SECRET_KEY, ASSOCIATE_TAG, COUNTRY,
    resources=[
        "ItemInfo.Title", "ItemInfo.Features", "ItemInfo.ByLineInfo",
        "Images.Primary.Large", "Offers.Listings.Price",
        "Offers.Listings.Availability", "CustomerReviews.Count", "CustomerReviews.StarRating"
    ]
)

# ===== Gemini初期化 =====
genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel("models/gemini-2.0-flash")

# ===== 各ジャンルで商品1件ずつ投稿 =====
for genre in GENRES:
    print(f"\n📦 {genre['name']} の商品を取得中...")

    products = amazon.search_items(
        browse_node_id=genre["browse_node"],
        keywords=genre["keyword"],
        sort_by="Featured",
        item_count=1
    )

    if not products.items:
        print(f"❌ {genre['name']}の商品が見つかりませんでした。")
        continue

    product = products.items[0]
    title = product.item_info.title.display_value
    features = product.item_info.features.display_values if product.item_info.features else []
    manufacturer = product.item_info.by_line_info.manufacturer.display_value if product.item_info.by_line_info and product.item_info.by_line_info.manufacturer else "メーカー情報なし"
    price = product.offers.listings[0].price.display_amount if product.offers and product.offers.listings else "価格情報なし"
    rating = product.customer_reviews.star_rating if product.customer_reviews else "評価なし"
    review_count = product.customer_reviews.count if product.customer_reviews else "レビューなし"
    image_url = product.images.primary.large.url

    # Geminiプロンプト
    prompt = (
        f"以下のAmazonの商品情報をもとに、日本語で商品紹介記事を書いてください。\n\n"
        f"商品名: {title}\n"
        f"メーカー: {manufacturer}\n"
        f"価格: {price}\n"
        f"評価: {rating}（{review_count}件のレビュー）\n"
        f"特徴:\n" + "\n".join([f"- {f}" for f in features]) + "\n"
    )

    print("🧠 Geminiで記事生成中...")
    result = model.generate_content(prompt)
    article_text = result.text.strip()
    article_html = markdown.markdown(article_text)

    # 画像をダウンロード＆アップロード
    print("🖼️ アイキャッチ画像アップロード中...")
    image_data = requests.get(image_url)
    mime_type = guess_type(image_url)[0] or "image/jpeg"

    media_upload = requests.post(
        f"{WP_URL.rsplit('/', 2)[0]}/media",
        auth=HTTPBasicAuth(USERNAME, APP_PASSWORD),
        headers={
            "Content-Disposition": f"attachment; filename={title[:10]}.jpg",
            "Content-Type": mime_type
        },
        data=image_data.content
    )

    featured_media_id = media_upload.json()["id"] if media_upload.status_code == 201 else None
    if featured_media_id:
        print(f"✅ アイキャッチ画像設定成功（Media ID: {featured_media_id}）")
    else:
        print("⚠️ アイキャッチ画像のアップロードに失敗しました")

    # WordPressに投稿
    # タイトル生成用プロンプト
    title_prompt = (
        f"以下のAmazonの商品情報をもとに、自然なブログ記事のタイトル（日本語）を1つ提案してください。\n\n"
        f"商品名: {title}\n"
        f"メーカー: {manufacturer}\n"
        f"価格: {price}\n"
        f"評価: {rating}（{review_count}件のレビュー）\n"
    )

    title_result = model.generate_content(title_prompt)
    post_title = title_result.text.strip().replace('"', '').replace('タイトル：', '')

    payload = {
        "title": post_title,
        "content": article_html,
        "status": "draft",
        "categories": [genre["category_id"]],
        "tags": genre["tags"]
    }
    if featured_media_id:
        payload["featured_media"] = featured_media_id

    print("✍ WordPressに投稿中...")
    post_response = requests.post(
        WP_URL,
        auth=HTTPBasicAuth(USERNAME, APP_PASSWORD),
        json=payload
    )

    if post_response.status_code == 201:
        print(f"✅ 投稿完了！URL: {post_response.json()['link']}")
    else:
        print(f"❌ 投稿失敗: {post_response.status_code}")
        print(post_response.text)
