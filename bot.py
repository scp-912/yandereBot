import aiohttp
import base64
from bs4 import BeautifulSoup
from aiocqhttp import CQHttp, Event, MessageSegment
from event_filter import EventFilter
from loguru import logger
import json
import random
from datetime import datetime
from config_manager import ConfigManager
import os

# 初始化配置管理器
config = ConfigManager()

# 设置日志
logger.add(
    config.get('Bot', 'log_file'),
    rotation=config.get('Bot', 'log_rotation'),
    level=config.get('Bot', 'log_level')
)

bot = CQHttp()
event_filter = EventFilter(config.get('Filter', 'filter_file'))

# 请求频率限制
request_records = {}

async def check_rate_limit(user_id: int) -> bool:
    """检查用户请求频率"""
    now = datetime.now()
    rate_limit = config.getint('Limits', 'rate_limit')
    
    if user_id not in request_records:
        request_records[user_id] = []
    
    # 清理旧记录
    request_records[user_id] = [t for t in request_records[user_id] 
                               if (now - t).seconds < 60]
    
    if len(request_records[user_id]) >= rate_limit:
        return False
    
    request_records[user_id].append(now)
    return True

async def get_session():
    """创建带有配置的aiohttp会话"""
    session_kwargs = {
        'timeout': aiohttp.ClientTimeout(total=config.getint('Limits', 'request_timeout'))
    }
    
    if config.getboolean('Proxy', 'enable'):
        session_kwargs['proxy'] = config.get('Proxy', 'http')
    
    return aiohttp.ClientSession(**session_kwargs)

async def fetch_image_id(tag: str) -> int:
    """获取符合条件的随机图片ID"""
    url = f"{config.get('API', 'base_url')}/post?tags={tag}+"
    
    # 根据配置添加NSFW过滤
    if config.getboolean('Filter', 'filter_nsfw'):
        url += f"+rating:{config.get('Filter', 'nsfw_rating')}"
    
    headers = {
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'accept-language': 'zh-CN,zh;q=0.9,en;q=0.8,zh-TW;q=0.7',
        'user-agent': config.get('API', 'user_agent'),
    }
    
    async with await get_session() as session:
        async with session.get(url, headers=headers) as response:
            page = await response.text()
            soup = BeautifulSoup(page, 'html.parser')
            script_tag = soup.find('script', {'class': 'js-preload-posts', 'type': 'application/json'})
            
            if not script_tag:
                raise ValueError("无法找到图片数据")
            
            data_list = json.loads(script_tag.string)
            if not data_list:
                raise ValueError("未找到符合条件的图片")
            
            random_image = random.choice(data_list)
            return random_image['id']

async def fetch_images_and_convert_to_base64url(image_id: int) -> list:
    """获取图片并转换为base64格式"""
    detail_url = f"{config.get('API', 'base_url')}/post/show/{image_id}"
    headers = {
        'user-agent': config.get('API', 'user_agent'),
    }
    
    base64_urls = []
    max_size = config.getint('Limits', 'max_file_size')
    
    async with await get_session() as session:
        async with session.get(detail_url, headers=headers) as response:
            page = await response.text()
            script_tag = next((t for t in page.splitlines() if 'Post.register_resp' in t), None)
            if not script_tag:
                return base64_urls

            data_dict = json.loads(script_tag.replace('<script type="text/javascript"> Post.register_resp(', '')
                                   .replace('); </script>', ''))

            file_urls = [post['file_url'] for post in data_dict.get('posts', [])]

            for file_url in file_urls:
                try:
                    async with session.get(file_url, headers=headers) as image_response:
                        image_data = await image_response.read()
                        if len(image_data) > max_size:
                            logger.warning(f"图片大小超过限制: {len(image_data)} bytes")
                            continue
                        
                        base64_encoded_data = base64.b64encode(image_data).decode('utf-8')
                        base64_url_data = f"base64://{base64_encoded_data}"
                        base64_urls.append(base64_url_data)
                except Exception as e:
                    logger.error(f"下载图片失败: {e}")
                    continue

    return base64_urls

@bot.on_message('group')
async def handle_group_message(event: Event):
    """处理群消息"""
    msg = event.raw_message
    user_id = event.user_id
    group_id = event.group_id
    
    logger.info(f"收到消息: {msg}, 来自用户: {user_id}, 群组: {group_id}")

    # 检查事件过滤
    if not event_filter.should_pass(event):
        logger.info(f"消息被过滤: {msg}")
        await bot.send(event, '事件被过滤')
        return

    # 检查群组权限
    response_mode = config.get('Commands', 'group_response_mode')
    if response_mode == 'white':
        white_list = config.get('Commands', 'white_list_groups').split(',')
        if str(group_id) not in white_list:
            return
    elif response_mode == 'black':
        black_list = config.get('Commands', 'black_list_groups').split(',')
        if str(group_id) in black_list:
            return

    keyword = config.get('Commands', 'random_image_keyword')
    if keyword in msg:
        # 检查请求频率
        if not await check_rate_limit(user_id):
            await bot.send(event, f"请求过于频繁，请{config.get('Limits', 'rate_limit')}秒后再试")
            return

        parts = msg.split(keyword)
        if len(parts) > 1:
            tag = parts[1].strip()
            if tag:
                try:
                    image_id = await fetch_image_id(tag)
                except Exception as e:
                    error_msg = str(e)
                    logger.error(f"获取图片ID失败: {error_msg}")
                    await bot.send(event, config.get('Message', 'error_message').format(tag=tag))
                    return

                try:
                    base64_urls = await fetch_images_and_convert_to_base64url(image_id)
                    if not base64_urls:
                        await bot.send(event, config.get('Message', 'error_message').format(tag=tag))
                        return

                    # 构建消息
                    message = []
                    if config.getboolean('Message', 'show_safe_mode_mark') and config.getboolean('Filter', 'filter_nsfw'):
                        message.append(MessageSegment.text("【安全模式】\n"))
                    
                    for base64_url in base64_urls:
                        message.append(MessageSegment.image(base64_url))

                    if config.getboolean('Message', 'show_image_info'):
                        message.append(MessageSegment.text(f"\n标签: {tag}\nID: {image_id}"))

                    await bot.send(event, message)
                    
                except Exception as e:
                    logger.error(f"处理图片失败: {e}")
                    await bot.send(event, config.get('Message', 'error_message').format(tag=tag))

if __name__ == "__main__":
    # 运行机器人
    bot.run(
        host=config.get('Bot', 'host'),
        port=config.getint('Bot', 'port')
    )
