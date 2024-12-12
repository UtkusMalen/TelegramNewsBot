import aiogram
import dotenv
from aiogram import Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import Message
from dotenv import load_dotenv
import os
import google.generativeai as genai
import newspaper
from newspaper import Article
from bs4 import BeautifulSoup
import time
import requests
import nltk

nltk.download('punkt_tab')

load_dotenv()

dp = Dispatcher()

TOKEN = os.getenv("BOT_TOKEN")
genai.configure(api_key=os.environ['GEMINI_API_KEY'])

@dp.message(CommandStart())
async def command_start_handler(message: Message):
    await message.answer("Restarting...")

@dp.message()

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
    keywords = article_data.get('keywords', [])
    text = article_data.get('text', '')
    title = article_data.get('title', '')

    value_keywords = ["price", "market", "analysis", "regulation", "adoption", "investment", "blockchain", "DeFi", "NFT", "metaverse", "Bitcoin", "Ethereum", "USA", "Argentina", "Ton", "Telegram", "Gram"]
    if any(keyword.lower() in text.lower() or keyword.lower() in title.lower() for keyword in value_keywords):
        return True
    return False

def summarize_news(text_to_summarize):
    try:
        model = genai.GenerativeModel('gemini-2.0-flash-exp')
        response = model.generate_content(f"""Please summarize the following news article and format it using these HTML-like tags for Telegram: <b>bold</b>, <i>italic</i>, <u>underline</u>, <a href="URL">link</a>, <code>code</code>, <pre>preformatted text</pre>, and <tg-spoiler>spoiler</tg-spoiler>. Make it concise and engaging:\n\n{text_to_summarize}""")

        return response.text
    except Exception as e:
        print(f"Gemini API error: {e}")
        return None

def get_article_image(url):
    try:
        response = requests.get(url)
        soup = BeautifulSoup(response.content, 'html.parser')
        og_image = soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            return og_image.get['content']

        img_tag = soup.find('img')
        if img_tag and img_tag.get('src'):
            src = img_tag.get('src')
            if not src.startswith('http'):
                src = requests.compat.urljoin(url, src)
            return src
        return None
    except:
        return None

news_sites = [
    "https://www.coindesk.com/",
    #"https://cointelegraph.com/",
    #"https://www.cryptonews.com/",
    #"https://www.bitcoinmagazine.com/",
    #"https://www.theblockcrypto.com/",
    #"https://decrypt.co/",
    #"https://www.newsbtc.com/",
    #"https://u.today/",
    #"https://www.coingape.com/",
    #"https://beincrypto.com/"
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
    except newspaper.article.ArticleException as e:
        print(f"Error building paper for {site}: {e}")
    except requests.exceptions.RequestException as e:
        print(f"Network error building paper for {site}: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

print("\nTrending Crypto News:")
if trending_news:
    for news in trending_news:
        gemini_summary = summarize_news(news['summary'])
        image_url = get_article_image(news['url'])

        if gemini_summary:
            print(f"\nTitle: {news['title']}")
            print(f"URL: {news['url']}")
            if image_url:
                print(f"Image:{image_url}")
            print(f"Summary: {gemini_summary}")
        else:
            print(f"\nTitle: {news['title']}")
            print(f"URL: {news['url']}")
            print("Failed to summarize news. Please try again later.")
else:
    print("No trending crypto news found.")