import configparser
import os
import argparse
import logging

logger = logging.getLogger(__name__)

# 此处无需填值，方便后面的for in根据这里的key从环境变量里面取值即可。除非你是ide或者docker运行，把值写在空白''内
SYNC_CONFIG = {
    'SOURCE': '',
    'TARGET': '',
    'SYNC_ACTIVITY_START_TIME': '',
    'GARMIN_GLOBAL_EMAIL': '',
    'GARMIN_GLOBAL_PASSWORD': '',
    'GARMIN_CN_EMAIL': '',
    'GARMIN_CN_PASSWORD': '',
    "COROS_EMAIL": '',
    "COROS_PASSWORD": '',
    "GARMIN_CN_SECRET": '',
    "GARMIN_GLOBAL_SECRET": '',
    "DOMAIM": '',
}

RQ_CONFIG = {
    'AESKEY': '',
    "RQ_EMAIL": '',
    "RQ_PASSWORD": ''
}

# 在 config.py 中添加
NOTIFY_CONFIG = {
    'DD_BOT_SECRET': '',
    'DD_BOT_TOKEN': ''
}


def load_config_from_file():
    """从配置文件加载配置"""
    # 尝试加载INI配置文件
    ini_config_path = os.path.join(os.path.dirname(__file__), '..', 'config.ini')
    if os.path.exists(ini_config_path):
        config = configparser.ConfigParser()
        config.read(ini_config_path)

        # 从INI文件读取配置
        for section in config.sections():
            for key in config[section]:
                config_key = key.upper()
                if config_key in SYNC_CONFIG:
                    SYNC_CONFIG[config_key] = config[section][key]
                # 添加RQ的处理
                elif config_key in RQ_CONFIG:
                    RQ_CONFIG[config_key] = config[section][key]
                # 添加通知配置的处理
                elif config_key in NOTIFY_CONFIG:
                    NOTIFY_CONFIG[config_key] = config[section][key]
        return True
    return False


def get_argv():
    parser = argparse.ArgumentParser()
    parser.add_argument("--SOURCE", default="")
    parser.add_argument("--TARGET", default="")
    parser.add_argument("--SYNC_ACTIVITY_START_TIME", default="")
    parser.add_argument("--GARMIN_GLOBAL_EMAIL", default="")  # 可选参数以--开头
    parser.add_argument("--GARMIN_GLOBAL_PASSWORD", default="")
    parser.add_argument("--GARMIN_CN_EMAIL", default="")  # 可选参数以--开头
    parser.add_argument("--GARMIN_CN_PASSWORD", default="")
    parser.add_argument("--COROS_EMAIL", default="")
    parser.add_argument("--COROS_PASSWORD", default="")
    # 添加RQ_CONFIG相关的命令行参数
    parser.add_argument("--AESKEY", default="")
    parser.add_argument("--RQ_EMAIL", default="")
    parser.add_argument("--RQ_PASSWORD", default="")
    # 添加通知相关的命令行参数
    parser.add_argument("--DD_BOT_SECRET", default="")
    parser.add_argument("--DD_BOT_TOKEN", default="")
    return parser.parse_args()


# 首先从配置文件加载配置
load_config_from_file()

argv = get_argv()
# 首先读取 命令行参数，再取面板变量 或者 github action 运行变量
for k in SYNC_CONFIG:
    if argv.__dict__.get(k):
        SYNC_CONFIG[k] = argv.__dict__.get(k)
        logger.warning(f"fill config value {k} = {str(SYNC_CONFIG[k])} from argv")
    elif os.getenv(k):
        SYNC_CONFIG[k] = os.getenv(k)
    # 否则使用从配置文件加载的值或默认空值

# 添加从环境变量或命令行参数加载RQ_CONFIG
for k in RQ_CONFIG:
    if argv.__dict__.get(k):
        RQ_CONFIG[k] = argv.__dict__.get(k)
        logger.warning(f"fill config value {k} = {str(RQ_CONFIG[k])} from argv")
    elif os.getenv(k):
        RQ_CONFIG[k] = os.getenv(k)
    # 否则使用从配置文件加载的值或默认空值

# 添加从环境变量或命令行参数加载NOTIFY_CONFIG
for k in NOTIFY_CONFIG:
    if argv.__dict__.get(k):
        NOTIFY_CONFIG[k] = argv.__dict__.get(k)
        logger.warning(f"fill config value {k} = {str(NOTIFY_CONFIG[k])} from argv")
    elif os.getenv(k):
        NOTIFY_CONFIG[k] = os.getenv(k)

# getting content root directory
current = os.path.dirname(os.path.realpath(__file__))
# 由于config.py移动到了conf目录下，需要多一层parent
conf_dir = os.path.dirname(current)  # scripts/conf目录
parent = os.path.dirname(conf_dir)  # 项目根目录

GARMIN_GLOBAL_FIT_DIR = os.path.join(parent, "garmin-global-fit")
GARMIN_CN_FIT_DIR = os.path.join(parent, "garmin-cn-fit")
COROS_FIT_DIR = os.path.join(parent, "coros-fit")
DB_DIR = os.path.join(parent, "db")
