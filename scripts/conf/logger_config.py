import logging
import sys
def get_logger(name):
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = False  # 防止日志重复传播

    # 如果 logger 已经有处理器，则避免重复添加
    if not logger.handlers:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)

        formatter = logging.Formatter('%(message)s')
        console_handler.setFormatter(formatter)

        logger.addHandler(console_handler)

    return logger