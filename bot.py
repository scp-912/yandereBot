import aiohttp
import base64
from bs4 import BeautifulSoup
from aiocqhttp import CQHttp, Event, MessageSegment
from loguru import logger
import json
import random
from config_manager import ConfigManager
from datetime import datetime

# 初始化配置和日志
config = ConfigManager()
logger.add(
    config.get('Bot', 'log_file'),
    rotation=config.get('Bot', 'log_rotation'),
    level=config.get('Bot', 'log_level')
)

bot = CQHttp()

# 用户冷却时间记录
user_cooldowns = {}

def check_group_permission(group_id: int) -> bool:
    """检查群组权限"""
    mode = config.get('Commands', 'group_response_mode')
    if mode == 'all':
        return True
    
    if mode == 'white':
        white_list = config.get('Commands', 'white_list_groups').split(',')
        return str(group_id) in white_list
    
    if mode == 'black':
        black_list = config.get('Commands', 'black_list_groups').split(',')
        return str(group_id) not in black_list
    
    return True

def check_rate_limit(user_id: int) -> bool:
    """检查用户请求频率"""
    now = datetime.now()
    rate_limit = config.getint('Limits', 'rate_limit')
    
    if user_id in user_cooldowns:
        # 清理超过1分钟的记录
        user_cooldowns[user_id] = [t for t in user_cooldowns[user_id] 
                                 if (now - t).seconds < 60]
        
        if len(user_cooldowns[user_id]) >= rate_limit:
            return False
    else:
        user_cooldowns[user_id] = []
        
    user_cooldowns[user_id].append(now)
    return True

async def fetch_image_id(tag: str):
    """获取图片ID"""
    url = f"{config.get('API', 'base_url')}/post?tags={tag}+"
    
    # 如果开启了NSFW过滤，添加分级过滤
    if config.getboolean('Filter', 'filter_nsfw'):
        url += f"+rating:{config.get('Filter', 'nsfw_rating')}"
    
    headers = {
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'accept-language': 'zh-CN,zh;q=0.9,en;q=0.8,zh-TW;q=0.7',
        'user-agent': config.get('API', 'user_agent')
    }
    
    proxy = None
    if config.getboolean('Proxy', 'enable'):
        proxy = config.get('Proxy', 'http')
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, proxy=proxy) as response:
            page = await response.text()
            soup = BeautifulSoup(page, 'html.parser')
            script_tag = soup.find('script', {'class': 'js-preload-posts', 'type': 'application/json'})
            if not script_tag:
                raise ValueError(config.get('Message', 'error_message').format(tag=tag))
            
            data_list = json.loads(script_tag.string)
            if not data_list:
                raise ValueError(config.get('Message', 'error_message').format(tag=tag))
            
            random_image = random.choice(data_list)
            return random_image['id']

async def fetch_images_and_convert_to_base64url(image_id: int):
    """获取图片并转换为base64"""
    detail_url = f"{config.get('API', 'base_url')}/post/show/{image_id}"
    headers = {
        'user-agent': config.get('API', 'user_agent')
    }
    
    proxy = None
    if config.getboolean('Proxy', 'enable'):
        proxy = config.get('Proxy', 'http')
    
    base64_urls = []
    async with aiohttp.ClientSession() as session:
        async with session.get(detail_url, headers=headers, proxy=proxy) as response:
            page = await response.text()
            script_tag = next((t for t in page.splitlines() if 'Post.register_resp' in t), None)
            if script_tag:
                data_dict = json.loads(script_tag.replace('<script type="text/javascript"> Post.register_resp(', '')
                                     .replace('); </script>', ''))
                
                file_urls = [post['file_url'] for post in data_dict.get('posts', [])]
                for file_url in file_urls:
                    try:
                        async with session.get(file_url, headers=headers, proxy=proxy) as image_response:
                            if image_response.status == 200:
                                image_data = await image_response.read()
                                # 检查文件大小限制
                                if len(image_data) <= config.getint('Limits', 'max_file_size'):
                                    base64_encoded = base64.b64encode(image_data).decode('utf-8')
                                    base64_urls.append(f"base64://{base64_encoded}")
                    except Exception as e:
                        logger.error(f"获取图片失败: {e}")
                        continue
    
    return base64_urls

@bot.on_message('group')
async def handle_group_message(event: Event):
    """处理群消息"""
    msg = event.raw_message
    user_id = event.user_id
    group_id = event.group_id
    
    logger.info(f"收到消息: {msg}, 来自用户: {user_id}, 群组: {group_id}")
    
    # 检查群组权限
    if not check_group_permission(group_id):
        return
    
    keyword = config.get('Commands', 'random_image_keyword')
    if keyword in msg:
        # 检查请求频率
        if not check_rate_limit(user_id):
            await bot.send(event, "请求过于频繁，请稍后再试")
            return
        
        parts = msg.split(keyword)
        if len(parts) > 1:
            tag = parts[1].strip()
            if tag:
                try:
                    image_id = await fetch_image_id(tag)
                    base64_urls = await fetch_images_and_convert_to_base64url(image_id)
                    
                    if base64_urls:
                        # 构建消息
                        message = []
                        if config.getboolean('Message', 'show_safe_mode_mark') and \
                           config.getboolean('Filter', 'filter_nsfw'):
                            message.append(MessageSegment.text("【安全模式】\n"))
                        
                        for base64_url in base64_urls:
                            message.append(MessageSegment.image(base64_url))
                        
                        if config.getboolean('Message', 'show_image_info'):
                            message.append(MessageSegment.text(f"\n标签: {tag}\nID: {image_id}"))
                        
                        await bot.send(event, message)
                    else:
                        await bot.send(event, config.get('Message', 'error_message').format(tag=tag))
                except Exception as e:
                    logger.error(f"处理图片时出错: {e}")
                    await bot.send(event, config.get('Message', 'error_message').format(tag=tag))

if __name__ == "__main__":
    bot.run(
        host=config.get('Bot', 'host'),
        port=config.getint('Bot', 'port')
    )
