# dvlogger (v1.1.2)

## TODO

- `file_config.level` - Take list of multiple levels to create multiple files
- `file_config.file_mode` - Implement CSV
- `use_tg_handler` and `tg_config` - Implement Telegram handler with multiple tries and exponential backoff

```
import logging
import dvlogger

dvlogger.setup(level=logging.INFO, capture_warnings=True, exception_hook=True, use_tg_handler=False, use_file_handler=False, file_config=None, tg_config=None)
```

```
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
```
