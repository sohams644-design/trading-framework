import logging
import os
from datetime import datetime


def setup_logger():

    os.makedirs("data/logs", exist_ok=True)

    filename = datetime.now().strftime("%Y-%m-%d") + ".log"

    logging.basicConfig(
        filename=f"data/logs/{filename}",
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )

    return logging.getLogger("ORB")


logger = setup_logger()