from conf.config import SYNC_CONFIG
import garth
from conf.logger_config import get_logger

logger = get_logger(__name__)

if __name__ == "__main__":
    DOMAIN = SYNC_CONFIG["DOMAIN"].upper()

    if DOMAIN == 'CN':
        GARMIN_EMAIL = SYNC_CONFIG["GARMIN_CN_EMAIL"]
        GARMIN_PASSWORD = SYNC_CONFIG["GARMIN_CN_PASSWORD"]
        garth.configure(domain="garmin.cn", ssl_verify=False)
    else:
        GARMIN_EMAIL = SYNC_CONFIG["GARMIN_GLOBAL_EMAIL"]
        GARMIN_PASSWORD = SYNC_CONFIG["GARMIN_GLOBAL_PASSWORD"]
        garth.configure(domain="garmin.com", ssl_verify=False)

    garth.login(GARMIN_EMAIL, GARMIN_PASSWORD)
    secret_string = garth.client.dumps()
    logger.info(secret_string)
