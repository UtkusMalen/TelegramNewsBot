import sys

import aiogram
from aiogram import Bot, Dispatcher, html
from aiogram import types
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
from newspaper import Article, Config
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

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

sent_news = set()

news_cache = {}

callback_data_cache = {}


async def send_to_bot(message: Message):
    while True:
        print(f"Checking for new news at {datetime.datetime.now()}...")
        try:
            config = Config()
            config.browser_user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            config.request_timeout = 10
            news_sites = [
                "https://www.coindesk.com/",
                "https://cointelegraph.com/",
                "https://decrypt.co/",
                "https://beincrypto.com/",
                "https://www.theblock.co/"
            ]

            trending_news = []

            for site in news_sites:
                print(f"Scraping: {site}")
                try:
                    paper = newspaper.build(site, config=config, memoize_articles=False)
                    for article in paper.articles[:5]:
                        time.sleep(1)
                        url = article.url
                        if url not in sent_news and url not in news_cache:
                            news_data = get_trending_news(url)
                            if is_valuable_news(news_data):
                                trending_news.append(news_data)
                                sent_news.add(url)
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
                    asyncio.sleep(5)

                    if gemini_summary:
                        message_text = gemini_summary
                    else:
                        print("Failed to summarize news. Please try again later.")
                    try:
                        news_id = hashlib.md5(news['url'].encode()).hexdigest()
                        buttons = InlineKeyboardMarkup(
                            inline_keyboard=[
                                [
                                    InlineKeyboardButton(text="🗑️ Delete", callback_data=f"delete:{news_id}"),
                                    InlineKeyboardButton(text="♻️ Regenerate", callback_data=f"regenerate:{news_id}"),
                                    InlineKeyboardButton(text="📰 Publish", callback_data=f"publish:{news_id}")
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
                print(f"No trending crypto news found at {datetime.datetime.now()}")
        except Exception as e:
            logging.exception(f"Error in news fetching loop: {e}")

        await asyncio.sleep(3600)

class EditPostState(StatesGroup):
    waiting_for_new_content = State()

@dp.callback_query(lambda c: c.data.startswith("delete:"))
async def handle_delete(callback: CallbackQuery):
    await callback.message.delete()
    await callback.answer("🗑️ Post deleted.")

@dp.callback_query(lambda c: c.data.startswith("regenerate:"))
async def handle_regenerate(callback: CallbackQuery):
    try:
        _, news_id = callback.data.split(":")

        url = None

        for cached_url, news_data in news_cache.items():
            if hashlib.md5(cached_url.encode()).hexdigest() == news_id:
                url = cached_url
                break

        if not url:
            await callback.answer("Failed to find news in cache.")
            return

        news_data = news_cache.get(url) or get_trending_news(url)
        if not news_data or 'summary' not in news_data:
            await callback.answer("Failed to find news in cache.")
            return



        gemini_summary = summarize_news(news_data['summary'], url)
        if gemini_summary:
            if callback.message.text:
                await callback.message.edit_text(text=gemini_summary, parse_mode=ParseMode.HTML, reply_markup=callback.message.reply_markup)
            elif callback.message.caption:
                await callback.message.edit_caption(caption=gemini_summary, parse_mode=ParseMode.HTML,reply_markup=callback.message.reply_markup)
            await callback.answer("♻️ Post regenerated.")
        else:
            await callback.answer("Failed to summarize news. Please try again later.")
            return

    except Exception as e:
        logging.exception(f"Error handling regenerate callback: {e}")
        await callback.answer("Error regenerating post")

@dp.callback_query(lambda c: c.data.startswith("publish:"))
async def handle_publish(callback: CallbackQuery):
    message = callback.message
    if not message:
        await callback.answer("Failed to find message.")
        return

    if message.photo:
        photo = message.photo[-1].file_id
        caption = message.html_text
        sent_message = await bot.send_photo(chat_id=-1002346321511, photo=photo, caption=f"{caption}\n\nhttps://t.me/wiretapnews", parse_mode=ParseMode.HTML)
    elif message.html_text:
        text = message.html_text
        sent_message = await bot.send_message(chat_id=-1002346321511, text=f"{text}\n\nhttps://t.me/wiretapnews", parse_mode=ParseMode.HTML)
    if sent_message:
        await callback.message.delete()
        await callback.answer("Published to channel")
    else:
        await callback.answer("Failed to publish to channel")


def get_trending_news(url):
    if url in news_cache:
        print("Getting news from cache")
        return news_cache[url]

    try:
        article = Article(url)
        article.download()
        article.parse()
        article.nlp()
        news_data = {
            'title': article.title,
            'text': article.text,
            'keywords': article.keywords,
            'summary': article.summary,
            'url': url
        }
        news_cache[url] = news_data
        return news_data
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

    value_keywords = ["price", "market", "analysis", "regulation", "adoption", "investment", "blockchain", "DeFi", "Bitcoin", "Ethereum", "USA", "Argentina", "Ton", "Telegram", "Gram"]
    if any(keyword.lower() in text.lower() or keyword.lower() in title.lower() for keyword in value_keywords):
        return True
    return False

def summarize_news(text_to_summarize, url):
    try:
        model = genai.GenerativeModel('gemini-2.0-flash-exp')
        response = model.generate_content(f"""Please summarize the following news article and format it using these HTML-like tags for Telegram: <b>bold</b>, <i>italic</i>, <u>underline</u>, <a href="URL">link</a>.Format the link using the provided URL: {url}.Do not generate invalid or placeholder links.Add some emojis that fit the context and tone of the news.Apply formatting meaningfully to highlight key points, not randomly.Avoid addressing the audience directly.Conclude with a brief comment summarizing the significance of the news. Don't say things like: Here's a summary of the news article using the requested HTML-like tags and emojis and things like this. Paste links to sources where you get the news from. Keep the text short and focused, ensuring it delivers the core message effectively.It should have title and main article.Make it concise and engaging:\n\n{text_to_summarize}""")

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
    asyncio.create_task(send_to_bot(bot))
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    asyncio.run(main())