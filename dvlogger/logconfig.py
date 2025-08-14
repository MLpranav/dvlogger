import asyncio
import datetime
import json
import logging
import os
import queue
import sys
import threading
import time
import traceback
import urllib.parse
import urllib.request

import colorama

from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler

def success(msg, *args, **kwargs):
    if logging.getLogger().isEnabledFor(logging.SUCCESS):
        logging.getLogger()._log(logging.SUCCESS, msg, args, **kwargs)

logging.SUCCESS = 25 # between WARNING and INFO
logging.addLevelName(logging.SUCCESS, 'SUCCESS')
logging.success = success

def thread_except_hook(args):
    log_except_hook(args.exc_type, args.exc_value, args.exc_traceback)

def log_except_hook(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return None
    logging.error(''.join(traceback.format_exception(exc_type, exc_value, exc_traceback)))

def asyncio_exception_handler(loop, context):
    exception = context.get('exception')
    if exception:
        logging.error('Asyncio error:')
        sys.excepthook(type(exception), exception, exception.__traceback__)
    else:
        logging.error(f'Non-exception asyncio error: {context}')
        loop.default_exception_handler(context)

async def asyncio_task_wrapper(coro):
    try:
        return await coro
    except Exception as e:
        logging.error('Task exception caught immediately:')
        sys.excepthook(type(e), e, e.__traceback__)
        raise

_original_create_task = asyncio.create_task
def asyncio_patched_create_task(coro, **kwargs):
    if asyncio.iscoroutine(coro):
        wrapped_coro = asyncio_task_wrapper(coro)
        return _original_create_task(wrapped_coro, **kwargs)
    return _original_create_task(coro, **kwargs)

_original_new_event_loop = asyncio.new_event_loop
def asyncio_patched_new_event_loop(*args, **kwargs):
    loop = _original_new_event_loop(*args, **kwargs)
    loop.set_exception_handler(asyncio_exception_handler)
    return loop

policy = asyncio.get_event_loop_policy()
_original_policy_new_event_loop = policy.new_event_loop
def asyncio_patched_policy_new_event_loop(*args, **kwargs):
    loop = _original_policy_new_event_loop(*args, **kwargs)
    loop.set_exception_handler(asyncio_exception_handler)
    return loop

class CustomFormatter(logging.Formatter):
    def __init__(self, fmt, datefmt):
        super().__init__(fmt=fmt, datefmt=datefmt)
        grey = "\033[90m"
        white = "\033[97m"
        yellow = "\033[33m"
        red = "\033[31m"
        bold_red = "\033[1;31m"
        reset = "\033[0m"
        green = "\033[32m"

        self.FORMATS = {
            logging.DEBUG: logging.Formatter(grey + fmt + reset, datefmt),
            logging.INFO: logging.Formatter(white + fmt + reset, datefmt),
            logging.WARNING: logging.Formatter(yellow + fmt + reset, datefmt),
            logging.ERROR: logging.Formatter(red + fmt + reset, datefmt),
            logging.CRITICAL: logging.Formatter(bold_red + fmt + reset, datefmt),
            logging.SUCCESS: logging.Formatter(green + fmt + reset, datefmt),
        }

    def format(self, record):
        return self.FORMATS[record.levelno].format(record)

class TGHandler(logging.Handler):
    def __init__(self, level, level_bypass_prefix, bot_key, chat_id, thread_id=None):
        super().__init__()
        self.level_filter = level
        self.level_bypass_prefix = level_bypass_prefix
        self.bot_key = bot_key
        self.chat_id = str(chat_id)
        self.thread_id = thread_id

        self.queue = queue.Queue()
        self.doc_len = 3000

    def emit(self, record):
        if record.msg.startswith(self.level_bypass_prefix) or record.levelno >= self.level_filter:
            log_message = self.format(record)
            self.queue.put(log_message)

    def queue_process(self):
        while True:
            log_message = self.queue.get(True, None)
            self.queue.task_done()

            for _ in range(5):
                try:
                    if len(log_message) < self.doc_len:
                        datadict = {'chat_id': self.chat_id, 'text': log_message}
                        if self.thread_id is not None:
                            datadict['message_thread_id'] = self.thread_id
                        url = f'https://api.telegram.org/bot{self.bot_key}/sendMessage?{urllib.parse.urlencode(datadict)}'
                        req = urllib.request.Request(url)
                        with urllib.request.urlopen(req, timeout=30) as resp:
                            resp_data = resp.read()
                            status_code = resp.status
                            resp_json = json.loads(resp_data.decode())
                    else:
                        boundary = '----WebKitFormBoundary' + str(int(time.time() * 1000))
                        filedata = log_message.encode()
                        filename = f'{time.time()}.txt'
                        data = f'--{boundary}\r\nContent-Disposition: form-data; name="chat_id"\r\n\r\n{self.chat_id}\r\n'
                        if self.thread_id is not None:
                            data += f'--{boundary}\r\nContent-Disposition: form-data; name="message_thread_id"\r\n\r\n{self.thread_id}\r\n'
                        data += (
                            f'--{boundary}\r\n'
                            f'Content-Disposition: form-data; name="document"; filename="{filename}"\r\n'
                            f'Content-Type: text/plain\r\n\r\n'
                        )
                        body = data.encode() + filedata + f'\r\n--{boundary}--\r\n'.encode()
                        req = urllib.request.Request(
                            f'https://api.telegram.org/bot{self.bot_key}/sendDocument',
                            data=body,
                            method='POST',
                            headers={
                                'Content-Type': f'multipart/form-data; boundary={boundary}',
                                'Content-Length': str(len(body))
                                }
                        )
                        with urllib.request.urlopen(req, timeout=30) as resp:
                            resp_data = resp.read()
                            status_code = resp.status
                            resp_json = json.loads(resp_data.decode())

                    if status_code == 429:
                        try:
                            time.sleep(int(resp_json["retry_after"]) + 2)
                        except KeyError:
                            try:
                                time.sleep(int(resp_json["parameters"]["retry_after"]) + 2)
                            except KeyError:
                                time.sleep(5)
                    elif (status_code != 200) or ("ok" not in resp_json) or (not resp_json["ok"]):
                        logging.warning(f'TGHandler {status_code} - {resp_json}')
                        time.sleep(5)
                    else:
                        time.sleep(0.05) # 20 messages per second
                        break
                except Exception:
                    logging.warning(traceback.format_exc())
                    time.sleep(5)
            else:
                logging.error(f'TGHandler failed to send message: {log_message}')

def setup(level=logging.DEBUG, capture_warnings=True, exception_hook=True, use_tg_handler=False, use_file_handler=False, file_config=None, tg_config=None):
    """
    file_config
        name [os.path.basename(sys.argv[0]).strip(), dvlogger]
        kind [BASIC] # ROTATING, TIMED, BASIC
        level [logging.DEBUG]
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
        level [logging.ERROR]
        level_bypass_prefix ["TG - "]
        bot_key
        chat_id
        thread_id [None]
    """

    if file_config is None:
        file_config = {}

    colorama.init()
    formatter_string = '%(asctime)s.%(msecs)03d - %(threadName)s - %(taskName)s - %(levelname)s - %(filename)s.%(funcName)s#%(lineno)d - %(message)s'
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

    use_name = file_config.get('name', os.path.basename(sys.argv[0]).strip())
    if use_name == '':
        use_name = 'dvlogger'

    if exception_hook:
        sys.excepthook = log_except_hook
        threading.excepthook = thread_except_hook

        asyncio.create_task = asyncio_patched_create_task
        asyncio.new_event_loop = asyncio_patched_new_event_loop
        policy.new_event_loop = asyncio_patched_policy_new_event_loop

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

        file_handler.setLevel(file_config.get('level', logging.DEBUG))
        file_handler.setFormatter(formatter2)
        logger.addHandler(file_handler)

    if use_tg_handler:
        if tg_config is not None and 'bot_key' in tg_config and 'chat_id' in tg_config:
            if 'thread_id' not in tg_config:
                tg_config['thread_id'] = None
            tg_handler = TGHandler(tg_config.get('level', logging.ERROR), tg_config.get('level_bypass_prefix', 'TG - '), tg_config['bot_key'], tg_config['chat_id'], tg_config['thread_id'])
            tg_handler.setLevel(logging.DEBUG)
            tg_handler.setFormatter(formatter2)
            logger.addHandler(tg_handler)
            threading.Thread(target=tg_handler.queue_process, name='TGHandlerQueueProcessor', daemon=True).start()
        else:
            logging.warning('Failed to setup TGHandler: missing bot_key/chat_id.')

        logging.info('*******')
