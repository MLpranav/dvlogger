import logging, sys, traceback, threading, colorama, datetime, os

from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler

def thread_except_hook(args):
    log_except_hook(args.exc_type, args.exc_value, args.exc_traceback)

def log_except_hook(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return None
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
            logging.DEBUG: logging.Formatter(grey + fmt + reset, datefmt),
            logging.INFO: logging.Formatter(white + fmt + reset, datefmt),
            logging.WARNING: logging.Formatter(yellow + fmt + reset, datefmt),
            logging.ERROR: logging.Formatter(red + fmt + reset, datefmt),
            logging.CRITICAL: logging.Formatter(bold_red + fmt + reset, datefmt),
        }

    def format(self, record):
        return self.FORMATS[record.levelno].format(record)

def setup(level=logging.INFO, capture_warnings=True, exception_hook=True, use_tg_handler=False, use_file_handler=False, file_config=None, tg_config=None):
    """
    file_config
        name [os.path.basename(sys.argv[0]).strip(), dvlogger]
        kind [BASIC] # ROTATING, TIMED, BASIC
        level [logging.INFO]
        file_mode [text]

        rotating_size [1e6]
        rotating_count [3]

        timed_when ['midnight']
        timed_interval [1]
        timed_count [7]

        basic_date_format ['%Y_%m_%d_%H_%M%_S_%f']
        basic_put_date [False]
        basic_append [True]

    tg_config
        level [ERROR]
        bot_key
        chat_id
        thread_id [None]
    """

    if file_config is None:
        file_config = {}

    colorama.init()
    formatter_string = '%(asctime)s.%(msecs)03d - %(threadName)s - %(levelname)s - %(module)s - %(funcName)s - %(message)s'
    formatter_string_date = '%Y-%m-%d %H:%M:%S'
    logging.captureWarnings(capture_warnings)

    logger = logging.getLogger()
    logger.handlers.clear()
    logger.setLevel(logging.DEBUG)
    formatter = CustomFormatter(fmt=formatter_string, datefmt=formatter_string_date)
    formatter2 = logging.Formatter(fmt=formatter_string, datefmt=formatter_string_date)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    use_name = os.path.basename(sys.argv[0]).strip()
    if use_name == '':
        use_name = 'dvlogger'

    if exception_hook:
        sys.excepthook = log_except_hook
        threading.excepthook = thread_except_hook

    if use_tg_handler:
        pass

    if use_file_handler:
        if file_config.get('kind', 'BASIC') == 'BASIC':
            if file_config.get("basic_put_date", False):
                use_name = use_name + '_' + datetime.datetime.now().strftime(file_config.get("basic_date_format", "%Y_%m_%d_%H_%M%_S_%f"))
            use_name = use_name + ".dvl.log"
            file_handler = logging.FileHandler(use_name, mode='a' if file_config.get("basic_append", True) else 'w')
        elif file_config['kind'] == 'ROTATING':
            use_name = use_name + ".dvl.log"
            file_handler = RotatingFileHandler(use_name, mode='a', maxBytes=file_config.get('rotating_size', 1e6), backupCount=file_config.get('rotating_count', 3))
        elif file_config['kind'] == 'TIMED':
            use_name = use_name + ".dvl.log"
            file_handler = TimedRotatingFileHandler(use_name, when=file_config.get('timed_when', 'midnight'), interval=file_config.get('timed_interval', 1), backupCount=file_config.get('timed_count', 7))
        else:
            raise Exception(f"kind={file_config['kind']} is not defined")

        file_handler.setLevel(file_config.get('level', logging.INFO))
        file_handler.setFormatter(formatter2)
        logger.addHandler(file_handler)

    logging.info('*******')
