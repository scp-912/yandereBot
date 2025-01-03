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

async def get_total_pages(tag: str) -> int:
    """获取指定tag的总页数"""
    url = f"{config.get('API', 'base_url')}/post?tags={tag}+"
    
    # 添加分级过滤（与 fetch_image_id 函数相同的过滤逻辑）
    rating = config.get('Filter', 'nsfw_rating', 's')
    if rating != 'e+':
        if rating == 'e':
            pass
        elif rating == 'q':
            url += "+(-rating:e)"
        elif rating == 's':
            url += "+rating:s"
    else:
        url += "+rating:e"
    
    headers = {
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'user-agent': config.get('API', 'user_agent')
    }
    
    proxy = config.get('Proxy', 'http') if config.getboolean('Proxy', 'enable') else None
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, proxy=proxy) as response:
            page = await response.text()
            soup = BeautifulSoup(page, 'html.parser')
            
            # 查找分页信息
            pagination = soup.find('div', {'class': 'pagination'})
            if pagination:
                # 找到最后一页的链接
                last_page = pagination.find_all('a')[-2].text
                return int(last_page)
            return 1  # 如果没有分页，说明只有一页

async def fetch_image_id(tag: str):
    """获取图片ID（修改版）"""
    # 首先获取总页数
    total_pages = await get_total_pages(tag)
    
    # 随机选择一页
    random_page = random.randint(1, total_pages)
    
    url = f"{config.get('API', 'base_url')}/post?tags={tag}+&page={random_page}"
    
    # 添加分级过滤
    rating = config.get('Filter', 'nsfw_rating', 's')
    if rating != 'e+':
        if rating == 'e':
            pass
        elif rating == 'q':
            url += "+(-rating:e)"
        elif rating == 's':
            url += "+rating:s"
    else:
        url += "+rating:e"
    
    headers = {
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'user-agent': config.get('API', 'user_agent')
    }
    
    proxy = config.get('Proxy', 'http') if config.getboolean('Proxy', 'enable') else None
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, proxy=proxy) as response:
            page = await response.text()
            soup = BeautifulSoup(page, 'html.parser')
            script_tag = soup.find('script', {'class': 'js-preload-posts', 'type': 'application/json'})
            
            if not script_tag or not script_tag.string:
                raise ValueError("未找到图片数据")
            
            data_list = json.loads(script_tag.string)
            if not data_list:
                raise ValueError(f"未找到关于 {tag} 的图片")
            
            random_image = random.choice(data_list)
            return random_image['id'], random_image.get('rating', 'unknown')


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
    timeout = aiohttp.ClientTimeout(total=config.getint('Limits', 'request_timeout', 30))
    
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(detail_url, headers=headers, proxy=proxy) as response:
            page = await response.text()
            script_tag = next((t for t in page.splitlines() if 'Post.register_resp' in t), None)
            if script_tag:
                data_dict = json.loads(script_tag.replace('<script type="text/javascript"> Post.register_resp(', '')
                                     .replace('); </script>', ''))
                
                # 优先使用较小的预览图
                file_urls = []
                for post in data_dict.get('posts', []):
                    # 优先使用 sample_url（中等大小），如果没有则使用 file_url
                    url = post.get('sample_url') or post.get('file_url')
                    if url:
                        file_urls.append(url)
                
                for file_url in file_urls:
                    try:
                        async with session.get(file_url, headers=headers, proxy=proxy) as image_response:
                            if image_response.status == 200:
                                image_data = await image_response.read()
                                max_size = config.getint('Limits', 'max_file_size')
                                
                                if len(image_data) <= max_size:
                                    base64_encoded = base64.b64encode(image_data).decode('utf-8')
                                    base64_urls.append(f"base64://{base64_encoded}")
                                else:
                                    logger.warning(f"图片大小超过限制: {len(image_data)} > {max_size}")
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
    if config.get('Commands', 'group_response_mode') != 'all':
        if config.get('Commands', 'group_response_mode') == 'white':
            white_list = config.get('Commands', 'white_list_groups').split(',')
            if str(group_id) not in white_list:
                return
        else:  # black mode
            black_list = config.get('Commands', 'black_list_groups').split(',')
            if str(group_id) in black_list:
                return
    
    keyword = config.get('Commands', 'random_image_keyword')
    if keyword in msg:
        parts = msg.split(keyword)
        if len(parts) > 1:
            tag = parts[1].strip()
            if tag:
                # 检查冷却时间
                now = datetime.now()
                if user_id in user_cooldowns:
                    last_time = user_cooldowns[user_id]
                    if (now - last_time).seconds < config.getint('Limits', 'cooldown', 60):
                        await bot.send(event, f"冲太快了，请等待 {config.getint('Limits', 'cooldown', 60) - (now - last_time).seconds} 秒后再试")
                        return
                
                # 发送开始搜索的提示
                await bot.send(event, f"正在寻找「{tag}」的图片...")
                
                try:
                    # 记录请求时间
                    user_cooldowns[user_id] = now
                    
                    image_id, rating = await fetch_image_id(tag)
                    base64_urls = await fetch_images_and_convert_to_base64url(image_id)
                    
                    if base64_urls:
                        # 构建消息
                        message = []
                        
                        # 添加分级提示
                        rating_text = {
                            's': '【全年龄】',
                            'q': '【较安全】',
                            'e': '【限制级】'
                        }.get(rating, '')
                        
                        if rating_text:
                            message.append(MessageSegment.text(f"{rating_text}\n"))
                        
                        # 添加图片
                        for base64_url in base64_urls:
                            message.append(MessageSegment.image(base64_url))
                        
                        # 添加图片信息
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
