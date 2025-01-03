# config_manager.py
import configparser
import os
from typing import Any, Dict
from loguru import logger

class ConfigManager:
    # 默认配置
    DEFAULT_CONFIG = {
        'Bot': {
            'host': '0.0.0.0',
            'port': '5545',
            'log_file': 'bot.log',
            'log_level': 'INFO',
            'log_rotation': '500 MB'
        },
        'Proxy': {
            'enable': 'false',
            'http': 'http://127.0.0.1:10809',
            'https': 'http://127.0.0.1:10809'
        },
        'API': {
            'base_url': 'https://yande.re',
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
        },
        'Filter': {
            'filter_file': 'filter.json',
            'filter_nsfw': 'true',
            'nsfw_rating': 's'
        },
        'Limits': {
            'max_file_size': '10485760',
            'request_timeout': '30',
            'rate_limit': '5'
        },
        'Commands': {
            'random_image_keyword': '随机图片',
            'group_response_mode': 'all',
            'white_list_groups': '',
            'black_list_groups': ''
        },
        'Cache': {
            'enable_cache': 'false',
            'cache_dir': 'cache',
            'cache_expire_hours': '24',
            'max_cache_size': '1024'
        },
        'Message': {
            'show_image_info': 'true',
            'show_safe_mode_mark': 'true',
            'success_message': '为您找到关于{tag}的图片',
            'error_message': '抱歉，未找到相关图片',
            'nsfw_blocked_message': '由于安全模式已开启，无法显示该图片'
        }
    }

    def __init__(self, config_file: str = 'config.cfg'):
        self.config_file = config_file
        self.config = configparser.ConfigParser()
        self.load_config()

    def create_default_config(self) -> None:
        """创建默认配置文件"""
        config = configparser.ConfigParser()
        
        for section, options in self.DEFAULT_CONFIG.items():
            config[section] = {}
            for key, value in options.items():
                config[section][key] = value
                # 添加配置项说明
                if section == 'Bot':
                    config[section].comments[key] = {
                        'host': '# 机器人监听的IP地址，0.0.0.0表示监听所有地址',
                        'port': '# 机器人使用的端口号',
                        'log_file': '# 日志文件保存路径',
                        'log_level': '# 日志等级: DEBUG, INFO, WARNING, ERROR, CRITICAL',
                        'log_rotation': '# 日志文件切割大小，超过此大小会自动创建新文件'
                    }.get(key, '')
                # ... 其他部分的注释同理

        with open(self.config_file, 'w', encoding='utf-8') as f:
            config.write(f)

    def load_config(self) -> None:
        """加载配置，如果配置不存在或无效则使用默认配置"""
        try:
            if not os.path.exists(self.config_file):
                self.create_default_config()
                logger.info(f"已创建默认配置文件: {self.config_file}")

            self.config.read(self.config_file, encoding='utf-8')
            if not self.validate_config():
                logger.warning("配置文件验证失败，将使用默认配置")
                self.use_default_config()
        except Exception as e:
            logger.error(f"加载配置文件失败: {e}")
            self.use_default_config()

    def use_default_config(self) -> None:
        """使用默认配置"""
        self.config = configparser.ConfigParser()
        for section, options in self.DEFAULT_CONFIG.items():
            self.config[section] = options

    def validate_config(self) -> bool:
        """验证配置文件的正确性"""
        try:
            # 验证必要的部分是否存在
            required_sections = self.DEFAULT_CONFIG.keys()
            for section in required_sections:
                if section not in self.config:
                    logger.warning(f"缺少配置节: {section}")
                    return False

            # 验证具体的值
            if not 0 <= self.getint('Bot', 'port', 5545) <= 65535:
                logger.warning("端口号必须在0-65535之间")
                return False

            log_level = self.get('Bot', 'log_level', 'INFO')
            if log_level not in ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']:
                logger.warning("无效的日志等级")
                return False

            nsfw_rating = self.get('Filter', 'nsfw_rating', 's')
            if nsfw_rating not in ['s', 'q', 'e', 'e+']:
                logger.warning(f"无效的NSFW分级设置: {nsfw_rating}，将使用默认值's'")
                self.config.set('Filter', 'nsfw_rating', 's')
                return False

            return True


            response_mode = self.get('Commands', 'group_response_mode', 'all')
            if response_mode not in ['all', 'white', 'black']:
                logger.warning("无效的群组响应模式")
                return False

            return True

        except Exception as e:
            logger.error(f"配置验证时发生错误: {e}")
            return False

    def get(self, section: str, option: str, fallback: Any = None) -> str:
        """获取配置项的值，如果不存在则返回默认值"""
        try:
            return self.config.get(section, option)
        except:
            return self.DEFAULT_CONFIG.get(section, {}).get(option, fallback)

    def getboolean(self, section: str, option: str, fallback: bool = None) -> bool:
        """获取布尔类型的配置项值"""
        try:
            return self.config.getboolean(section, option)
        except:
            default_value = self.DEFAULT_CONFIG.get(section, {}).get(option, str(fallback))
            return default_value.lower() == 'true'

    def getint(self, section: str, option: str, fallback: int = None) -> int:
        """获取整数类型的配置项值"""
        try:
            return self.config.getint(section, option)
        except:
            return int(self.DEFAULT_CONFIG.get(section, {}).get(option, fallback))
