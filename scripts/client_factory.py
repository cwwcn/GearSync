from conf.config import SYNC_CONFIG
from coros.coros_client import CorosClient
from garmin.garmin_cn_client import GarminCNClient
from garmin.garmin_global_client import GarminGlobalClient


def _has_required_config(required_configs, logger):
    for config_key, error_message in required_configs.items():
        if not SYNC_CONFIG.get(config_key):
            logger.info(error_message)
            return False
    return True


def create_coros_client(logger):
    required_configs = {
        "COROS_EMAIL": "The COROS email address is not configured. Please set COROS_EMAIL before running the program.",
        "COROS_PASSWORD": "The COROS password is not configured. Please set COROS_PASSWORD before running the program."
    }
    if not _has_required_config(required_configs, logger):
        return None

    coros_client = CorosClient(SYNC_CONFIG["COROS_EMAIL"], SYNC_CONFIG["COROS_PASSWORD"])
    logger.warning("The COROS account is not logged in or its token has expired. Logging in to COROS now.")
    coros_client.login()
    logger.warning(f"Successfully logged in to COROS as {coros_client.email}.")
    return coros_client


def create_garmin_cn_client(logger):
    garmin_cn_secret = SYNC_CONFIG.get("GARMIN_CN_SECRET")
    if garmin_cn_secret:
        logger.info("GARMIN_CN_SECRET is configured. Using an OAuth token to log in.")
        return GarminCNClient(garmin_cn_secret)

    required_configs = {
        "GARMIN_CN_EMAIL": "The Garmin China email address is not configured. Please set GARMIN_CN_EMAIL before running the program.",
        "GARMIN_CN_PASSWORD": "The Garmin China password is not configured. Please set GARMIN_CN_PASSWORD before running the program."
    }
    if not _has_required_config(required_configs, logger):
        return None

    logger.info("GARMIN_CN_SECRET is not configured. Using an email address and password to log in.")
    return GarminCNClient(SYNC_CONFIG["GARMIN_CN_EMAIL"], SYNC_CONFIG["GARMIN_CN_PASSWORD"])


def create_garmin_global_client(logger):
    garmin_global_secret = SYNC_CONFIG.get("GARMIN_GLOBAL_SECRET")
    if garmin_global_secret:
        logger.info("GARMIN_GLOBAL_SECRET is configured. Using an OAuth token to log in.")
        return GarminGlobalClient(garmin_global_secret)

    required_configs = {
        "GARMIN_GLOBAL_EMAIL": "The Garmin Global email address is not configured. Please set GARMIN_GLOBAL_EMAIL before running the program.",
        "GARMIN_GLOBAL_PASSWORD": "The Garmin Global password is not configured. Please set GARMIN_GLOBAL_PASSWORD before running the program."
    }
    if not _has_required_config(required_configs, logger):
        return None

    logger.info("GARMIN_GLOBAL_SECRET is not configured. Using an email address and password to log in.")
    return GarminGlobalClient(SYNC_CONFIG["GARMIN_GLOBAL_EMAIL"], SYNC_CONFIG["GARMIN_GLOBAL_PASSWORD"])
