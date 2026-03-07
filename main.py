import logging

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)-8s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)

from ai_dungeon_master.ui import run_app

if __name__ == "__main__":
    run_app()
