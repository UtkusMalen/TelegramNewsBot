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
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import hashlib
import nltk
from datetime import datetime, timezone, timedelta
import re
from playwright.async_api import async_playwright

load_dotenv()

nltk.download('punkt_tab')

dp = Dispatcher()

TOKEN = os.getenv("BOT_TOKEN")
genai.configure(api_key=os.environ['GEMINI_API_KEY'])

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

sent_news = set()

news_cache = {}

callback_data_cache = {}


async def send_to_bot(message: Message):
    while True:
        try:
            user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36'
            config = Config()
            config.browser_user_agent = user_agent
            static_sites = [
                "https://www.coindesk.com",
                "https://cryptoslate.com/top-news/"
            ]
            dynamic_sites = [
                "https://cointelegraph.com",
                "https://www.newsbtc.com",
                "https://www.ft.com/markets",
                "https://www.financemagnates.com/"
            ]

            trending_news = []

            for site in static_sites:
                print(f"Scraping: {site}")
                try:
                    paper = newspaper.build(site, config=config, language='en')
                    for article in paper.articles[:5]:
                        print(article.url)
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

            for site in dynamic_sites:
                print(f"Scraping dynamic site: {site}")
                try:
                    links = await fetch_valid_links(site)
                    for link in links[:5]:
                        print(link)
                        if link not in news_cache:
                            news_data = get_trending_news(link)
                            if news_data:
                                trending_news.append(news_data)
                except Exception as e:
                    print(f"Error scraping {site} with Playwright: {e}")

            print("\nTrending Crypto News:")
            if trending_news:
                for news in trending_news:
                    gemini_summary = summarize_news(news['text'], news['url'], news['links'])
                    image_url = get_article_image(news['url'])
                    publish_date = (news['publish_date'])
                    time.sleep(5)

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
                            await message.send_message(chat_id=1092856248,
                                                       text=f"<a href='{image_url}'>‎</a> {message_text}\n\n{publish_date}",
                                                       parse_mode=ParseMode.HTML, reply_markup=buttons)
                        else:
                            await message.send_message(chat_id=1092856248, text=f"{message_text}\n\n{publish_date}",
                                                       parse_mode=ParseMode.HTML, reply_markup=buttons)
                    except aiogram.exceptions.TelegramBadRequest as e:
                        logging.error(f"Telegram Bad Request: {e}. Message Text: {message_text}")
                    except Exception as e:
                        logging.exception(f"Error sending message to Telegram: {e}")
            else:
                print(f"No trending crypto news found at {datetime.now()}")
        except Exception as e:
            logging.exception(f"Error in news fetching loop: {e}")

        await asyncio.sleep(1800)

async def fetch_valid_links(url):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36")
        page = await context.new_page()

        try:
            await page.goto(url, timeout=30000)
            links = await page.eval_on_selector_all(
                "a", "elements => elements.map(el => el.href)"
            )

            valid_links = list({
                link for link in links
                if "news" in link and not ("/category/" in link or "/latest-news" in link) or "economics" in link or "technology" in link or "markets" in link
            })
            return valid_links

        finally:
            await browser.close()


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
        if not news_data or 'text' not in news_data:
            await callback.answer("Failed to find news in cache.")
            return

        image_url = get_article_image(news_data['url'])
        publish_date = (news_data['publish_date'])

        gemini_summary = summarize_news(news_data['text'], url, news_data['links'])
        if gemini_summary:
            if callback.message.text:
                await callback.message.edit_text(text=f"{gemini_summary}\n\n{publish_date}", parse_mode=ParseMode.HTML,
                                                 reply_markup=callback.message.reply_markup)
            elif callback.message.caption:
                await callback.message.edit_text(text=f"<a href='{image_url}'>‎</a> {gemini_summary}\n\n{publish_date}",
                                                 parse_mode=ParseMode.HTML, reply_markup=callback.message.reply_markup)
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
    text = message.html_text
    date_pattern = r"\b(?:\d{4}-\d{2}-\d{2}|\w+ \d{1,2}, \d{4}|\d{2} \w+ \d{4}) \d{2}:\d{2}:\d{2}\b"
    cleaned_text = re.sub(date_pattern, '', text)
    if not message:
        await callback.answer("Failed to find message.")
        return

    elif message.html_text:
        sent_message = await bot.send_message(chat_id=-1002346321511, text=f"{cleaned_text}https://t.me/wiretapnews",
                                              parse_mode=ParseMode.HTML)
    if sent_message:
        await callback.message.delete()
        await callback.answer("Published to channel")
    else:
        await callback.answer("Failed to publish to channel")


def get_trending_news(url):
    if url in news_cache:
        print("Getting news from cache")
        return news_cache[url]
    user_agent = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_11_5) AppleWebKit/537.36 (HTML, like Gecko) Chrome/50.0.2661.102 Safari/537.36'
    config = Config()
    config.browser_user_agent = user_agent

    try:
        article = Article(url, config=config)
        article.download()
        article.parse()
        article.nlp()
        publish_date = article.publish_date
        utc_plus_2 = timezone(timedelta(hours=2))

        if publish_date:
            if publish_date.tzinfo is None:
                publish_date = publish_date.replace(tzinfo=timezone.utc)
            publish_date = publish_date.astimezone(utc_plus_2)
        else:
            utc_now = datetime.now(timezone.utc)
            publish_date = utc_now.astimezone(utc_plus_2)

        publish_date = publish_date.strftime("%Y-%m-%d %H:%M:%S")

        soup = BeautifulSoup(article.html, 'html.parser')
        all_links = [a['href'] for a in soup.find_all('a', href=True)]
        relevant_links = [
            link for link in all_links
            if "x.com/" in link and "/status/" in link or "reports" in link
        ]
        unique_links = list(set(relevant_links))
        news_data = {
            'title': article.title,
            'text': article.text,
            'keywords': article.keywords,
            'summary': article.summary,
            'url': url,
            'links': unique_links,
            'publish_date': publish_date
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

    value_keywords = ["price", "market", "analysis", "regulation", "adoption", "investment", "blockchain", "DeFi",
                      "Bitcoin", "Ethereum", "USA", "Argentina", "Ton", "Telegram", "Gram"]
    if any(keyword.lower() in text.lower() or keyword.lower() in title.lower() for keyword in value_keywords):
        return True
    return False


def summarize_news(text_to_summarize, url, links):
    try:
        model = genai.GenerativeModel('gemini-2.0-flash-exp')
        response = model.generate_content(f"""
        Format the following news article for Telegram using *only* these HTML-like tags: <b>bold</b>, <i>italic</i>, <u>underline</u>, <a href="URL">link</a>.

        **Formatting Goals (Screenshot Style):**

        * **Visually Scannable:**  Prioritize clear sections and easy readability. Think of it as catching the reader's eye instantly.
        * **Clear Hierarchy:** Make the title stand out, followed by the main points.
        * **Concise & Impactful:** Every word should contribute. Maximux is 400 characters, always write short text (excluding link URLs).
        * **Engaging Tone:**  Use emojis and formatting to create a lively, informative feel.

        **Rules:**
        1. **Title First, Prominently Displayed:**  Use `<b>` for the main title. Keep it short and attention-grabbing.
        2. **Structured Main Article:** Break down the information into key points. Consider using short paragraphs or bullet-like formatting (even without actual bullet tags).
        3. **Strategic Tag Usage:**
            * `<b>`:  For key terms, numbers, or very important phrases within the main article.
            * `<i>`:  For subtle emphasis, context, or to introduce a quote.
            * `<u>`: Use sparingly for *very* specific emphasis or to visually separate elements if necessary (avoid overuse).
            * `<a href="URL">link</a>`:  Integrate links smoothly within the text, ideally right after the related information. Always input link to primary sources if possible(official posts/statements from {links}). If unavailable, use {url}. Use concise and relevant link text.
        4. **Emoji Power:** Use relevant emojis to enhance the tone and context of specific points. Place them strategically (e.g., before a key point, after a statement), but not much.
        5. **Quotes: Short & Sweet:**  Use quotes *very* sparingly for impactful statements. Introduce them briefly (e.g., "Key takeaway:"). Format like: "This is crucial" - Source Name.
        6. **No Audience Address:**  Avoid phrases like "Here's a summary," "Check this out," etc.
        7. **Focus on Content:** Don't include any extra text like "html" or empty lines (`<br>`).
        8. **Mimic Visual Flow:**  Imagine how the information would flow visually on a Telegram screen. Use formatting to guide the reader's eye.
        here is the text:\n{text_to_summarize}""")

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