import os
import queue
from setproctitle import setproctitle
from guck3.mplogging import whoami
from guck3 import mplogging
from telegram.ext import Updater, MessageHandler, Filters
import signal
import json
import time

TERMINATED = False


class SigHandler_mpcomm:
    def __init__(self, logger):
        self.logger = logger

    def sighandler_mpcomm(self, a, b):
        self.shutdown()

    def shutdown(self):
        global TERMINATED
        TERMINATED = True
        self.logger.debug(whoami() + "got signal, exiting ...")


class TelegramComm:
    def __init__(self, outqueue, inqueue, cfg, logger):
        self.cfg = cfg
        self.outqueue = outqueue
        self.inqueue = inqueue
        self.logger = logger
        self.active, self.token, self.chatids = self.get_config(self.cfg, self.logger)
        self.running = False

    def start(self):
        if not self.active:
            return -1
        self.logger.debug(whoami() + "starting telegram handler")
        self.logger.debug(whoami() + str(self.token) + " / " + str(self.chatids))
        try:
            self.updater = Updater(self.token, use_context=True)
            self.dp = self.updater.dispatcher
            self.bot = self.updater.bot
            self.dp.add_handler(MessageHandler(Filters.text, self.handler))
            self.updater.start_polling()
            self.running = True
            self.send_message_all("GUCK3 telegram bot started!")
            self.logger.info(whoami() + "telegram handler/bot started!")
            return 1
        except Exception as e:
            self.logger.warning(whoami() + str(e) + "cannot start telegram bot, setting to inactive!")
            self.token = None
            self.chatids = None
            self.active = False
            return -1

    def stop(self):
        if not self.active or not self.running:
            return
        self.logger.debug(whoami() + "stopping telegram bot")
        self.send_message_all("GUCK3 telegram bot stopped!")
        self.updater.stop()
        self.logger.info(whoami() + "telegram bot stopped!")
        self.running = False

    def send_message_all(self, text):
        for c in self.chatids:
            try:
                self.bot.send_message(chat_id=c, text=text)
            except Exception as e:
                self.logger.warning(whoami() + str(e) + ": chat_id " + str(c))

    def get_config(self, cfg, logger):
        active = True if cfg["TELEGRAM"]["ACTIVE"].lower() == "yes" else False
        if not active:
            return False, None, None
        try:
            token = cfg["TELEGRAM"]["TOKEN"]
            chatids = json.loads(cfg.get("TELEGRAM", "CHATIDS"))
            logger.debug(whoami() + "got config for active telegram bot")
        except Exception as e:
            logger.debug(whoami() + str(e) + "telegram config error, setting telegram to inactive!")
            return False, None, None
        return active, token, chatids

    def handler(self, update, context):
        msg = update.message.text.lower()
        if msg == "start":
            reply = "starting GUCK3 alarm system"
            self.outqueue.put("start")
        elif msg == "stop":
            reply = "stopping GUCK3 alarm system"
            self.outqueue.put("stop")
        elif msg == "exit!!":
            reply = "exiting GUCK3!"
            self.outqueue.put("exit")
        update.message.reply_text(reply)


def run_mpcommunicator(pd_outqueue, pd_inqueue, cfg, mp_loggerqueue):
    setproctitle("g3." + os.path.basename(__file__))

    logger = mplogging.setup_logger(mp_loggerqueue, __file__)
    logger.info(whoami() + "starting ...")

    sh = SigHandler_mpcomm(logger)
    signal.signal(signal.SIGINT, sh.sighandler_mpcomm)
    signal.signal(signal.SIGTERM, sh.sighandler_mpcomm)

    tg = TelegramComm(pd_outqueue, pd_inqueue, cfg, logger)
    tg.start()

    # ------ main looooooooop -------
    while not TERMINATED:
        try:
            pd_cmd = pd_inqueue.get_nowait()
            if pd_cmd == "exit":
                logger.debug(whoami() + "got exit cmd from pd")
                break
        except (queue.Empty, EOFError):
            continue
        except Exception:
            continue
        time.sleep(0.1)

    tg.stop()

    logger.info(whoami() + "... exited!")
