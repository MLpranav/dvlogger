import asyncio
import atexit
import datetime
import json
import logging
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
import math
import mimetypes
import os
import queue
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request

import colorama

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
    def __init__(self, fmt, datefmt, color):
        super().__init__(fmt=fmt, datefmt=datefmt)
        grey = "\033[90m" if color else ''
        white = "\033[97m" if color else ''
        yellow = "\033[33m" if color else ''
        red = "\033[31m" if color else ''
        bold_red = "\033[1;31m" if color else ''
        reset = "\033[0m" if color else ''
        green = "\033[32m" if color else ''

        warn_fmt = fmt.replace("%(levelname)s", "%(levelname)s ⚠️")
        error_fmt = fmt.replace("%(levelname)s", "%(levelname)s ❌")
        self.FORMATS = {
            logging.DEBUG: logging.Formatter(grey + fmt + reset, datefmt),
            logging.INFO: logging.Formatter(white + fmt + reset, datefmt),
            logging.SUCCESS: logging.Formatter(green + fmt + reset, datefmt),
            logging.WARNING: logging.Formatter(yellow + warn_fmt + reset, datefmt),
            logging.ERROR: logging.Formatter(red + error_fmt + reset, datefmt),
            logging.CRITICAL: logging.Formatter(bold_red + error_fmt + reset, datefmt),
        }

    def format(self, record):
        return self.FORMATS[record.levelno].format(record)

class TGHandler(logging.Handler):
    def setup(self, level, level_bypass_prefix, message_skip_prefix, bot_key, chat_id, thread_id, error_chat_id, error_thread_id, flush_interval):
        self.level_filter = level
        self.level_bypass_prefix = level_bypass_prefix
        self.message_skip_prefix = message_skip_prefix
        self.bot_key = bot_key
        self.chat_id = chat_id
        self.thread_id = thread_id
        self.error_chat_id = error_chat_id
        self.error_thread_id = error_thread_id
        self.flush_interval = flush_interval / 1000.0

        for attr in ('chat_id', 'thread_id', 'error_chat_id', 'error_thread_id'):
            val = getattr(self, attr)
            if isinstance(val, (int, float)):
                setattr(self, attr, str(int(val)))

        self.doc_len = 3000
        self.error_count = 0
        self.error_max = 100
        self.queue = queue.Queue()
        self.shutdown_event = threading.Event()

    def _tg_request(self, build_req, label=''):
        for ix in range(5):
            try:
                try:
                    with urllib.request.urlopen(build_req(), timeout=30) as resp:
                        resp_data = resp.read()
                        status_code = resp.status
                        resp_json = json.loads(resp_data.decode())

                    if status_code != 200 or 'ok' not in resp_json or not resp_json['ok']:
                        self.error_count += 1
                        logging.warning(f'{self.message_skip_prefix}TGHandler{label} {status_code} - {resp_json}')
                        time.sleep(5)
                    else:
                        return resp_json
                except urllib.error.HTTPError as e:
                    self.error_count += 1
                    resp_data = e.read()
                    status_code = e.code
                    try:
                        resp_json = json.loads(resp_data.decode())
                    except Exception:
                        resp_json = {}

                    if status_code == 429:
                        if 'retry_after' in resp_json:
                            time.sleep(int(resp_json['retry_after']) + 5)
                        elif 'parameters' in resp_json and 'retry_after' in resp_json['parameters']:
                            time.sleep(int(resp_json['parameters']['retry_after']) + 5)
                        else:
                            time.sleep(5)
                    else:
                        logging.warning(f'{self.message_skip_prefix}TGHandler{label} try #{ix+1} failed - {resp_json}')
                        time.sleep(5)
            except Exception:
                self.error_count += 1
                logging.warning(f'{self.message_skip_prefix}TGHandler{label} try #{ix+1} failed - {traceback.format_exc()}')
                time.sleep(5)
        logging.error(f'{self.message_skip_prefix}TGHandler{label} all tries failed')
        return None

    def _build_document_request(self, chat_id, thread_id, filedata, filename, caption='', content_type='application/octet-stream'):
        boundary = '----WebKitFormBoundary' + str(int(time.time() * 1000))
        data = f'--{boundary}\r\nContent-Disposition: form-data; name="chat_id"\r\n\r\n{chat_id}\r\n'
        if thread_id is not None:
            data += f'--{boundary}\r\nContent-Disposition: form-data; name="message_thread_id"\r\n\r\n{thread_id}\r\n'
        if caption:
            data += f'--{boundary}\r\nContent-Disposition: form-data; name="caption"\r\n\r\n{caption}\r\n'
        data += (
            f'--{boundary}\r\n'
            f'Content-Disposition: form-data; name="document"; filename="{filename}"\r\n'
            f'Content-Type: {content_type}\r\n\r\n'
        )
        body = data.encode() + filedata + f'\r\n--{boundary}--\r\n'.encode()
        return urllib.request.Request(
            f'https://api.telegram.org/bot{self.bot_key}/sendDocument',
            data=body,
            method='POST',
            headers={
                'Content-Type': f'multipart/form-data; boundary={boundary}',
                'Content-Length': str(len(body)),
            },
        )

    def send_file(self, file, name, caption='', is_error=False):
        chat_id = self.chat_id
        thread_id = self.thread_id
        if is_error and self.error_chat_id is not None:
            chat_id = self.error_chat_id
            thread_id = self.error_thread_id

        if isinstance(file, str):
            with open(file, 'rb') as f:
                filedata = f.read()
        elif hasattr(file, 'read'):
            filedata = file.read()
            if isinstance(filedata, str):
                filedata = filedata.encode()
        else:
            logging.error(f'{self.message_skip_prefix}file must be a path (str) or file-like object, got {type(file).__name__}')
            return None

        content_type = mimetypes.guess_type(name)[0] or 'application/octet-stream'
        return self._tg_request(lambda: self._build_document_request(chat_id, thread_id, filedata, name, caption, content_type), ' send_file')

    def stop(self):
        if not self.shutdown_event.is_set():
            logging.info(f'{self.message_skip_prefix}Shutting down dvlogger...')
            self.shutdown_event.set()
        else:
            logging.info(f'{self.message_skip_prefix}dvlogger already shutdown...')

    def emit(self, record):
        if not isinstance(record.msg, str):
            try:
                record.msg = str(record.msg)
            except Exception:
                try:
                    record.msg = '<>' + str(type(record.msg))
                except Exception:
                    record.msg = '<Unknown>'
        if not record.msg.startswith(self.message_skip_prefix) and (record.msg.startswith(self.level_bypass_prefix) or record.levelno >= self.level_filter):
            log_message = self.format(record)
            self.queue.put((record.levelno, log_message))

    def queue_process(self):
        while True:
            if (self.shutdown_event.is_set() and self.queue.empty()) or (self.error_count >= self.error_max):
                break

            cur_time = time.time()
            next_flush = math.ceil(cur_time / self.flush_interval) * self.flush_interval
            sleep_time = next_flush - cur_time
            if sleep_time > 0:
                time.sleep(sleep_time)

            log_entries = []
            while True: # drain queue
                try:
                    entry = self.queue.get(block=False)
                    self.queue.task_done()
                    log_entries.append(entry)
                except queue.Empty:
                    break

            if len(log_entries) == 0:
                continue

            max_level = max(lvl for lvl, _ in log_entries)
            log_message = '\n\n'.join(msg for _, msg in log_entries)

            if max_level >= logging.WARNING and self.error_chat_id is not None:
                log_message2 = '\n\n'.join(msg for lvl, msg in log_entries if lvl >= logging.WARNING)
                if len(log_message2) < self.doc_len:
                    datadict = {'chat_id': self.error_chat_id, 'text': log_message2}
                    if self.error_thread_id is not None:
                        datadict['message_thread_id'] = self.error_thread_id
                    build_req = lambda: urllib.request.Request(
                        f'https://api.telegram.org/bot{self.bot_key}/sendMessage',
                        data=json.dumps(datadict).encode(),
                        method='POST',
                        headers={'Content-Type': 'application/json'},
                    )
                else:
                    caption = ''
                    if max_level >= logging.WARNING:
                        caption = 'WARNING ⚠️'
                    if max_level >= logging.ERROR:
                        caption = 'ERROR ❌'
                    if max_level >= logging.CRITICAL:
                        caption = 'CRITICAL ❌'
                    build_req = lambda: self._build_document_request(self.error_chat_id, self.error_thread_id, log_message2.encode(), f'{time.time()}.txt', caption, 'text/plain')
                self._tg_request(build_req)
                time.sleep(0.05)

            if len(log_message) < self.doc_len:
                datadict = {'chat_id': self.chat_id, 'text': log_message}
                if self.thread_id is not None:
                    datadict['message_thread_id'] = self.thread_id
                build_req = lambda: urllib.request.Request(
                    f'https://api.telegram.org/bot{self.bot_key}/sendMessage',
                    data=json.dumps(datadict).encode(),
                    method='POST',
                    headers={'Content-Type': 'application/json'},
                )
            else:
                caption = ''
                if max_level >= logging.WARNING:
                    caption = 'WARNING ⚠️'
                if max_level >= logging.ERROR:
                    caption = 'ERROR ❌'
                if max_level >= logging.CRITICAL:
                    caption = 'CRITICAL ❌'
                build_req = lambda: self._build_document_request(self.chat_id, self.thread_id, log_message.encode(), f'{time.time()}.txt', caption, 'text/plain')
            self._tg_request(build_req)
            time.sleep(0.05) # 20 messages per second

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
        message_skip_prefix ["NTG - "]
        bot_key
        chat_id
        thread_id [None]
        error_chat_id [None]
        error_thread_id [None]
        flush_interval [5000] # ms
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
    formatter = CustomFormatter(fmt=formatter_string, datefmt=formatter_string_date, color=False)
    color_formatter = CustomFormatter(fmt=formatter_string, datefmt=formatter_string_date, color=True)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(color_formatter)
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
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    if use_tg_handler:
        if tg_config is not None and 'bot_key' in tg_config and 'chat_id' in tg_config:
            TG_HANDLER.setup(
                tg_config.get('level', logging.ERROR),
                tg_config.get('level_bypass_prefix', 'TG - '),
                tg_config.get('message_skip_prefix', 'NTG - '),
                tg_config['bot_key'],
                tg_config['chat_id'],
                tg_config.get('thread_id', None),
                tg_config.get('error_chat_id', None),
                tg_config.get('error_thread_id', None),
                tg_config.get('flush_interval', 5000),
            )
            TG_HANDLER.setLevel(logging.DEBUG)
            TG_HANDLER.setFormatter(formatter)
            logger.addHandler(TG_HANDLER)
            tg_thread = threading.Thread(target=TG_HANDLER.queue_process, name='TGHandlerQueueProcessor', daemon=True)
            tg_thread.start()

            def _shutdown_tg_handler():
                TG_HANDLER.stop()
                tg_thread.join()

            atexit.register(_shutdown_tg_handler)
        else:
            logging.warning('Failed to setup TGHandler: missing bot_key/chat_id.')

    logging.info('*******')

def tg_send_file(file, name, caption='', is_error=False):
    TG_HANDLER.send_file(file, name, caption, is_error)

TG_HANDLER = TGHandler()
