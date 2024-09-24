import logging, sys, traceback
import colorama

def handle_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    logging.error(''.join(traceback.format_exception(exc_type, exc_value, exc_traceback)))

class CustomFormatter(logging.Formatter):
    def __init__(self, fmt, datefmt):
        super().__init__(fmt=fmt, datefmt=datefmt)
        grey = "\033[90m"
        white = "\033[97m"
        yellow = "\033[33m"
        red = "\033[31m"
        bold_red = "\033[1;31m"
        reset = "\033[0m"

        self.FORMATS = {
            logging.DEBUG: grey + self._fmt + reset,
            logging.INFO: white + self._fmt + reset,
            logging.WARNING: yellow + self._fmt + reset,
            logging.ERROR: red + self._fmt + reset,
            logging.CRITICAL: bold_red + self._fmt + reset
        }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt)
        return formatter.format(record)

def setup():
    colorama.init()
    sys.excepthook = handle_exception
    formatter_string = '%(asctime)s - %(threadName)s - %(levelname)s - %(module)s - %(funcName)s - %(message)s'
    formatter_string_date = '%Y-%m-%d %H:%M:%S.%f'
    logging.captureWarnings(True)
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    formatter = CustomFormatter(fmt=formatter_string, datefmt=formatter_string_date)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(formatter)
    logger.handlers = [console_handler]
    logging.info('*******')
    return console_handler
