import aiohttp
import base64
from bs4 import BeautifulSoup
from aiocqhttp import CQHttp, Event, MessageSegment
from event_filter import EventFilter
from loguru import logger
import json
import random

logger.add("bot.log", rotation="500 MB", level="DEBUG")
bot = CQHttp()
event_filter = EventFilter('filter.json')


async def fetch_image_id(tag):
    url = f'https://yande.re/post?tags={tag}+'
    headers = {
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'accept-language': 'zh-CN,zh;q=0.9,en;q=0.8,zh-TW;q=0.7',
        'cache-control': 'no-cache',
        'cookie': 'vote=1; forum_post_last_read_at=%222025-01-01T02%3A49%3A49.032%2B09%3A00%22; session_yande-re=...',
        'pragma': 'no-cache',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, proxy='http://127.0.0.1:10809') as response:
            page = await response.text()
            soup = BeautifulSoup(page, 'html.parser')
            script_tag = soup.find('script', {'class': 'js-preload-posts', 'type': 'application/json'})
            data_list = json.loads(script_tag.string)
            random_image = random.choice(data_list)
            image_id = random_image['id']
            return image_id


async def fetch_images_and_convert_to_base64url(image_id):
    detail_url = f'https://yande.re/post/show/{image_id}'
    headers = {
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    }
    base64_urls = []
    async with aiohttp.ClientSession() as session:
        async with session.get(detail_url, headers=headers, proxy='http://127.0.0.1:10809') as response:
            page = await response.text()
            script_tag = next((t for t in page.splitlines() if 'Post.register_resp' in t), None)
            if not script_tag:
                return base64_urls

            data_dict = json.loads(script_tag.replace('<script type="text/javascript"> Post.register_resp(', '')
                                   .replace('); </script>', ''))

            file_urls = [post['file_url'] for post in data_dict.get('posts', [])]

            for file_url in file_urls:
                async with session.get(file_url, headers=headers, proxy='http://127.0.0.1:10809') as image_response:
                    image_data = await image_response.read()
                    base64_encoded_data = base64.b64encode(image_data).decode('utf-8')
                    base64_url_data = f"base64://{base64_encoded_data}"
                    base64_urls.append(base64_url_data)

    return base64_urls


@bot.on_message('group')
async def handle_group_message(event: Event):
    msg = event.raw_message
    logger.info(f"收到消息: {msg}, 来自: {event.user_id}")

    if not event_filter.should_pass(event):
        await bot.send(event, '事件被过滤')
        return

    if "随机图片" in msg:
        parts = msg.split("随机图片")
        if len(parts) > 1:
            tag = parts[1].strip()
            if tag:
                try:
                    image_id = await fetch_image_id(tag)
                    # image_id = 1209289
                except IndexError:
                    return {'reply': "未能找到任何图片"}

                base64_urls = await fetch_images_and_convert_to_base64url(image_id)
                imgs = None

                for base64_url in base64_urls:
                    imgs += MessageSegment.image(base64_url)

                if imgs is None:
                    return {'reply': "未能找到任何图片"}

                await bot.send(event, imgs)


bot.run(host='0.0.0.0', port=5545)
