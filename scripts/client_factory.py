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
        "COROS_EMAIL": "Coros email is not configured. Please set COROS_EMAIL value before running the program.",
        "COROS_PASSWORD": "Coros password is not configured. Please set COROS_PASSWORD value before running the program."
    }
    if not _has_required_config(required_configs, logger):
        return None

    coros_client = CorosClient(SYNC_CONFIG["COROS_EMAIL"], SYNC_CONFIG["COROS_PASSWORD"])
    logger.warning("Coros account is not logging in or the token has expired. So start logging into Coros now!")
    coros_client.login()
    logger.warning(f"Coros account {coros_client.email} logged in successfully!")
    return coros_client


def create_garmin_cn_client(logger):
    garmin_cn_secret = SYNC_CONFIG.get("GARMIN_CN_SECRET")
    if garmin_cn_secret:
        logger.info("GARMIN_CN_SECRET is configured, using OAuth token method for login!")
        return GarminCNClient(garmin_cn_secret)

    required_configs = {
        "GARMIN_CN_EMAIL": "Garmin China email is not configured. Please set GARMIN_CN_EMAIL value before running the program.",
        "GARMIN_CN_PASSWORD": "Garmin China password is not configured. Please set GARMIN_CN_PASSWORD value before running the program."
    }
    if not _has_required_config(required_configs, logger):
        return None

    logger.info("GARMIN_CN_SECRET is not configured, so 'Email-Password' method will be used for login!")
    return GarminCNClient(SYNC_CONFIG["GARMIN_CN_EMAIL"], SYNC_CONFIG["GARMIN_CN_PASSWORD"])


def create_garmin_global_client(logger):
    garmin_global_secret = SYNC_CONFIG.get("GARMIN_GLOBAL_SECRET")
    if garmin_global_secret:
        logger.info("GARMIN_GLOBAL_SECRET is configured, using OAuth token method for login!")
        return GarminGlobalClient(garmin_global_secret)

    required_configs = {
        "GARMIN_GLOBAL_EMAIL": "Garmin Global email is not configured. Please set GARMIN_GLOBAL_EMAIL value before running the program.",
        "GARMIN_GLOBAL_PASSWORD": "Garmin Global password is not configured. Please set GARMIN_GLOBAL_PASSWORD value before running the program."
    }
    if not _has_required_config(required_configs, logger):
        return None

    logger.info("GARMIN_GLOBAL_SECRET is not configured, so 'Email-Password' method will be used for login!")
    return GarminGlobalClient(SYNC_CONFIG["GARMIN_GLOBAL_EMAIL"], SYNC_CONFIG["GARMIN_GLOBAL_PASSWORD"])
