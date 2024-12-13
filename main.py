import sys

import aiogram
from aiogram import Bot, Dispatcher, html
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import Message
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from dotenv import load_dotenv
import os
import google.generativeai as genai
import newspaper
from newspaper import Article
from bs4 import BeautifulSoup
import time
import requests
import asyncio
import logging
import datetime
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import hashlib

load_dotenv()

dp = Dispatcher()

TOKEN = os.getenv("BOT_TOKEN")
genai.configure(api_key=os.environ['GEMINI_API_KEY'])

@dp.message(CommandStart())
async def command_start_handler(message: Message):
    await message.reply("Bot started. Fetching news...")
    await send_to_bot(message)

sent_news = set()


async def send_to_bot(message: Message):
    while True:
        print(f"Checking for new news at {datetime.time()}...")
        try:
            news_sites = [
                #"https://www.coindesk.com/",
                "https://cointelegraph.com/",
                # "https://www.cryptonews.com/",
                # "https://www.bitcoinmagazine.com/",
                # "https://www.theblockcrypto.com/",
                # "https://decrypt.co/",
                # "https://www.newsbtc.com/",
                # "https://u.today/",
                # "https://www.coingape.com/",
                # "https://beincrypto.com/"
            ]

            trending_news = []

            for site in news_sites:
                print(f"Scraping: {site}")
                try:
                    paper = newspaper.build(site, memoize_articles=False)
                    for article in paper.articles[:5]:
                        time.sleep(1)
                        news_data = get_trending_news(article.url)
                        if is_valuable_news(news_data):
                            trending_news.append(news_data)
                            sent_news.add(article.url)
                except newspaper.article.ArticleException as e:
                    print(f"Error building paper for {site}: {e}")
                except requests.exceptions.RequestException as e:
                    print(f"Network error building paper for {site}: {e}")
                except Exception as e:
                    print(f"An unexpected error occurred: {e}")

            print("\nTrending Crypto News:")
            if trending_news:
                for news in trending_news:
                    gemini_summary = summarize_news(news['summary'], news['url'])
                    image_url = get_article_image(news['url'])

                    if gemini_summary:
                        message_text = f"\n{gemini_summary}"
                    else:
                        print("Failed to summarize news. Please try again later.")
                    try:
                        news_id = hashlib.md5(news['url'].encode()).hexdigest()
                        buttons = InlineKeyboardMarkup(
                            inline_keyboard=[
                                [
                                    InlineKeyboardButton(text="✏️ Edit", callback_data=f"edit:{news_id}"),
                                    InlineKeyboardButton(text="🗑️ Delete", callback_data=f"delete:{news_id}")
                                ]
                            ]
                        )
                        if image_url:
                            await message.send_photo(chat_id=1092856248,photo=image_url, caption=message_text, parse_mode=ParseMode.HTML, reply_markup=buttons)
                        else:
                            await message.send_message(chat_id=1092856248, text=message_text,parse_mode=ParseMode.HTML, reply_markup=buttons)
                    except aiogram.exceptions.TelegramBadRequest as e:
                        logging.error(f"Telegram Bad Request: {e}. Message Text: {message_text}")
                    except Exception as e:
                        logging.exception(f"Error sending message to Telegram: {e}")
            else:
                print("No trending crypto news found.")
        except Exception as e:
            logging.exception(f"Error in news fetching loop: {e}")

        await asyncio.sleep(3600)

class EditPostState(StatesGroup):
    waiting_for_new_content = State()

@dp.callback_query(lambda c: c.data.startswith("edit:"))
async def handle_edit(callback: CallbackQuery, state: FSMContext):
    news_url = callback.data.split("edit:")[1]
    current_caption = callback.message.caption
    current_text = callback.message.text

    buttons = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✏️ Edit", callback_data=f"edit:{news_url}"),
                InlineKeyboardButton(text="🗑️ Delete", callback_data=f"delete:{news_url}"),
            ]
        ]
    )
    if current_caption:
        await callback.message.edit_caption(
            caption=f"{current_caption}\n📝 Please provide the new content for this post:",
            reply_markup=buttons,
            parse_mode=ParseMode.HTML
        )
    elif current_text:
        await callback.message.edit_text(
            text=f"{current_text}\n📝 Please provide the new content for this post:",
            reply_markup=buttons,
            parse_mode=ParseMode.HTML
        )
    else:
        await callback.answer("This message cannot be edited.", show_alert=True)
        return

    await state.set_state(EditPostState.waiting_for_new_content)
    await state.update_data(message_id=callback.message.message_id, news_url=news_url)

@dp.message(EditPostState.waiting_for_new_content)
async def handle_new_content(message: Message, state: FSMContext):
    data = await state.get_data()
    message_id = data.get("message_id")
    news_url = data.get("news_url")
    new_content = message.text

    buttons = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✏️ Edit", callback_data=f"edit:{news_url}"),
                InlineKeyboardButton(text="🗑️ Delete", callback_data=f"delete:{news_url}"),
            ]
        ]
    )

    try:
        await message.bot.edit_message_caption(
            chat_id=message.chat.id,
            message_id=message_id,
            caption=new_content,
            parse_mode=ParseMode.HTML,
            reply_markup=buttons
        )
    except aiogram.exceptions.TelegramBadRequest:
        await message.bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=message_id,
            text=new_content,
            parse_mode=ParseMode.HTML,
            reply_markup=buttons
        )


    await message.delete()

    await state.clear()

@dp.callback_query(lambda c: c.data.startswith("delete:"))
async def handle_delete(callback: CallbackQuery):
    await callback.message.delete()
    await callback.answer("🗑️ Post deleted.")

def get_trending_news(url):
    try:
        article = Article(url)
        article.download()
        article.parse()
        article.nlp()
        return {
            'title': article.title,
            'text': article.text,
            'keywords': article.keywords,
            'summary': article.summary,
            'url': url
        }
    except newspaper.article.ArticleException as e:
        print(f"Error parsing {url}: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Network error fetching {url}: {e}")
        return None
    except Exception as e:
        print(f"Unexpected error occured parsing{url}: {e}")
        return None

def is_valuable_news(article_data):
    if not article_data:
        return False
    text = article_data.get('text', '')
    title = article_data.get('title', '')

    value_keywords = ["price", "market", "analysis", "regulation", "adoption", "investment", "blockchain", "DeFi", "NFT", "metaverse", "Bitcoin", "Ethereum", "USA", "Argentina", "Ton", "Telegram", "Gram"]
    if any(keyword.lower() in text.lower() or keyword.lower() in title.lower() for keyword in value_keywords):
        return True
    return False

def summarize_news(text_to_summarize, url):
    try:
        model = genai.GenerativeModel('gemini-2.0-flash-exp')
        response = model.generate_content(f"""Please summarize the following news article and format it using these HTML-like tags for Telegram: <b>bold</b>, <i>italic</i>, <u>underline</u>, <a href="URL">link</a>.Format the link using the provided URL: {url}.Do not generate invalid or placeholder links.Add emojis that fit the context and tone of the news.Apply formatting meaningfully to highlight key points, not randomly.Avoid addressing the audience directly.Conclude with a brief comment summarizing the significance of the news. Don't say things like: Here's a summary of the news article using the requested HTML-like tags and emojis and things like this. Paste links to sources where you get the news from. Keep the text short and focused, ensuring it delivers the core message effectively. Make it concise and engaging:\n\n{text_to_summarize}""")

        return response.text
    except Exception as e:
        print(f"Gemini API error: {e}")
        return None

def get_article_image(url):
    try:
        response = requests.get(url, timeout=10)
        soup = BeautifulSoup(response.content, 'html.parser')
        og_image = soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            return og_image.get('content')

        img_tag = soup.find('img')
        if img_tag and img_tag.get('src'):
            src = img_tag.get('src')
            if not src.startswith('http'):
                src = requests.compat.urljoin(url, src)
            return src
        return None
    except:
        return None

async def main():
    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    asyncio.create_task(send_to_bot(bot))
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    asyncio.run(main())