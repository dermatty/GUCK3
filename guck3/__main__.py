import os
import sensors
import psutil
import configparser
import json
from setproctitle import setproctitle
import logging
import logging.handlers
from guck3 import setup_dirs, mplogging, peopledetection, clear_all_queues
from guck3.mplogging import whoami
import datetime
import signal
import sys
import multiprocessing as mp
import time
import queue
from telegram.ext import Updater, MessageHandler, Filters
import subprocess
from threading import Thread
from keras_retinanet import models


TERMINATED = False
RESTART = False


def GeneralMsgHandler(msg, bot, state_data, cfg, mp_loggerqueue):
    global TERMINATED
    global RESTART
    # bot = tgram / kbd
    bot0 = bot.lower()
    if bot0 not in ["tgram", "kbd"]:
        return None

    if msg == "start":
        state_data.MAINQUEUE.put(("start", bot0))
        reply = "starting GUCK3 alarm system"
    elif msg == "stop":
        if state_data.mpp_peopledetection:
            if state_data.mpp_peopledetection.pid:
                state_data.MAINQUEUE.put(("stop", None))
                reply = "stopping GUCK3 alarm system"
        else:
            reply = "GUCK3 alarm system is NOT running, cannot stop!"
    elif msg == "exit!!" or msg == "restart!!":
        if msg == "restart!!":
            reply = "restarting GUCK3!"
        else:
            reply = "exiting GUCK3!"
        state_data.MAINQUEUE.put((msg, None))
    elif msg.replace(" ", "") == "recordon" and not state_data.DO_RECORD:
        if not state_data.PD_ACTIVE:
            reply = "PeopleDetector no running, cannot start recording"
        else:
            state_data.PD_OUTQUEUE.put(("record on", None))
            state_data.DO_RECORD = True
            reply = "Recording on all cameras started!"
    elif msg.replace(" ", "") == "recordoff" and state_data.DO_RECORD:
        if not state_data.PD_ACTIVE:
            reply = "PeopleDetector no running, cannot stop recording"
        state_data.PD_OUTQUEUE.put(("record off", None))
        state_data.DO_RECORD = False
        reply = "Recording on all cameras stopped!"
    elif msg == "status":
        reply, _, _, _, _ = get_status(state_data)
    else:
        reply = "Don't know what to do with '" + msg + "'!"
    return reply


class SigHandler_g3:
    def __init__(self, mp_loggerqueue, mp_loglistener, state_data, old_sys_stdout, logger):
        self.logger = logger
        self.state_data = state_data
        self.mp_loggerqueue = mp_loggerqueue
        self.mp_loglistener = mp_loglistener
        self.old_sys_stdout = old_sys_stdout

    def sighandler_g3(self, a, b):
        self.shutdown(exit_status=1)

    def get_trstr(self, exit_status):
        if exit_status == 3:
            trstr = str(datetime.datetime.now()) + ": RESTART - "
        else:
            trstr = str(datetime.datetime.now()) + ": SHUTDOWN - "
        return trstr

    def shutdown(self, exit_status=1):
        trstr = self.get_trstr(exit_status)
        if self.state_data.TG.running:
            self.state_data.TG.stop()
        if self.state_data.KB.active:
            self.state_data.KB.stop()
            self.state_data.KB.join()
        mp_pd = self.state_data.mpp_peopledetection
        if mp_pd:
            if mp_pd.pid:
                print(trstr + "joining peopledetection ...")
                self.state_data.PD_OUTQUEUE.put("stop")
                mp_pd.join()
                print(self.get_trstr(exit_status) + "peopledetection exited!")
        trstr = self.get_trstr(exit_status)
        if self.mp_loglistener:
            if self.mp_loglistener.pid:
                print(trstr + "joining loglistener ...")
                mplogging.stop_logging_listener(self.mp_loggerqueue, self.mp_loglistener)
                self.mp_loglistener.join(timeout=5)
                if self.mp_loglistener.is_alive():
                    print(trstr + "killing loglistener")
                    os.kill(self.mp_loglistener.pid, signal.SIGKILL)
                print(self.get_trstr(exit_status) + "loglistener exited!")
        if sys.stdout != self.old_sys_stdout:
            sys.stdout = self.old_sys_stdout


def input_raise_to(a, b):
    raise TimeoutError


def input_to(fn, timeout, queue):
    signal.signal(signal.SIGALRM, input_raise_to)
    signal.signal(signal.SIGINT, input_raise_to)
    signal.signal(signal.SIGTERM, input_raise_to)
    signal.alarm(timeout)
    sys.stdin = os.fdopen(fn)
    try:
        msg = input()
        signal.alarm(0)
        queue.put(msg)
    except TimeoutError:
        signal.alarm(0)
        queue.put(None)


class StateData:
    def __init__(self):
        self.PD_ACTIVE = False
        self.mpp_peopledetection = None
        self.TG = None
        self.KB = None
        self.PD_INQUEUE = None
        self.PD_OUTQUEUE = None
        self.MAINQUEUE = None
        self.DIRS = None
        self.DO_RECORD = False


class KeyboardThread(Thread):
    def __init__(self, state_data, cfg, mp_loggerqueue, logger):
        Thread.__init__(self)
        self.daemon = True
        self.state_data = state_data
        self.mp_loggerqueue = mp_loggerqueue
        self.pd_inqueue = self.state_data.PD_INQUEUE
        self.pd_outqueue = self.state_data.PD_OUTQUEUE
        self.cfg = cfg
        self.logger = logger
        self.running = False
        self.active = self.get_config()
        self.kbqueue = mp.Queue()
        self.fn = sys.stdin.fileno()
        self.is_shutdown = False

    def get_config(self):
        active = True if self.cfg["KEYBOARD"]["ACTIVE"].lower() == "yes" else False
        return active

    def sighandler_kbd(self, a,  b):
        self.running = False

    def stop(self):
        if not self.active:
            return
        self.running = False
        self.logger.debug(whoami() + "stopping keyboard thread")
        print("Stopping GUCK3 keyboard bot, this may take a second ...")

    def run(self):
        if not self.active:
            return
        self.logger.debug(whoami() + "starting keyboard thread")
        self.running = True
        instruction = ">> Enter commands: start stop exit!! restart!! record on/off status"
        print(instruction)
        while self.running:
            mpp_inputto = mp.Process(target=input_to, args=(self.fn, 1, self.kbqueue, ))
            mpp_inputto.start()
            msg = self.kbqueue.get()
            mpp_inputto.join()
            if self.running and msg:
                reply = GeneralMsgHandler(msg, "kbd", self.state_data, self.cfg, self.mp_loggerqueue)
                print(reply)
                print(instruction)
        self.logger.debug(whoami() + "keyboard thread stopped!")


class TelegramThread:
    def __init__(self, state_data, cfg, mp_loggerqueue, logger):
        self.state_data = state_data
        self.mp_loggerqueue = mp_loggerqueue
        self.pd_inqueue = self.state_data.PD_INQUEUE
        self.pd_outqueue = self.state_data.PD_OUTQUEUE
        self.cfg = cfg
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
        self.send_message_all("Stopping GUCK3 telegram bot, this may take a while ...")
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
        reply = GeneralMsgHandler(msg, "tgram", self.state_data, self.cfg, self.mp_loggerqueue)
        update.message.reply_text(reply)


def get_status(state_data):

    osversion = os.popen("cat /etc/os-release").read().split("\n")[2].split("=")[1].replace('"', '')

    # os & version
    ret = "------- General -------"
    ret += "\nOS: " + osversion
    ret += "\nVersion: " + os.environ["GUCK3_VERSION"]
    ret += "\nAlarm System Active: "
    ret += "YES" if state_data.PD_ACTIVE else "NO"
    '''ret += "\nRecording: "
    ret += "YES" if recording else "NO"
    ret += "\nPaused: "
    ret += "YES" if not alarmrunning else "NO"
    ret += "\nTelegram Mode: " + TG_MODE
    ret += "\nAI Mode: " + AIMODE.upper()
    ret += "\nAI Sens.: " + str(AISENS)
    ret += "\nHCLIMIT: " + str(HCLIMIT)
    ret += "\nNIGHTMODE: "
    ret += "YES" if NIGHTMODE else "NO"'''
    ret += "\n------- System -------"

    # memory
    overall_mem = round(psutil.virtual_memory()[0] / float(2 ** 20) / 1024, 2)
    free_mem = round(psutil.virtual_memory()[1] / float(2 ** 20) / 1024, 2)
    used_mem = round(overall_mem - free_mem, 2)
    perc_used = round((used_mem / overall_mem) * 100, 2)
    mem_crit = False
    if perc_used > 85:
        mem_crit = True

    # cpu
    cpu_perc0 = psutil.cpu_percent(interval=0.25, percpu=True)
    cpu_avg = sum(cpu_perc0)/float(len(cpu_perc0))
    cpu_perc = (max(cpu_perc0) * 0.6 + cpu_avg * 0.4)/2
    cpu_crit = False
    if cpu_perc > 0.8:
        cpu_crit = True
    ret += "\nRAM: " + str(perc_used) + "% ( =" + str(used_mem) + " GB) of overall " + str(overall_mem) + \
           " GB used"
    ret += "\nCPU: " + str(round(cpu_avg, 1)) + "% ("
    for cpu0 in cpu_perc0:
        ret += str(cpu0) + " "
    ret += ")"

    # sensors / cpu temp
    sensors.init()
    cpu_temp = []
    for chip in sensors.iter_detected_chips():
        for feature in chip:
            if feature.label[0:4] == "Core":
                temp0 = feature.get_value()
                cpu_temp.append(temp0)
                ret += "\nCPU " + feature.label + " temp.: " + str(round(temp0, 2)) + "°"
    sensors.cleanup()
    if len(cpu_temp) > 0:
        avg_cpu_temp = sum(c for c in cpu_temp)/len(cpu_temp)
    else:
        avg_cpu_temp = 0
    if avg_cpu_temp > 52.0:
        cpu_crit = True
    else:
        cpu_crit = False

    # gpu
    if osversion == "Gentoo/Linux":
        smifn = "/opt/bin/nvidia-smi"
    else:
        smifn = "/usr/bin/nvidia-smi"
    try:
        gputemp = subprocess.Popen([smifn, "--query-gpu=temperature.gpu", "--format=csv"],
                                   stdout=subprocess.PIPE).stdout.readlines()[1]
        gpuutil = subprocess.Popen([smifn, "--query-gpu=utilization.gpu", "--format=csv"],
                               stdout=subprocess.PIPE).stdout.readlines()[1]
        gputemp_str = gputemp.decode("utf-8").rstrip()
        gpuutil_str = gpuutil.decode("utf-8").rstrip()
    except Exception:
        gputemp_str = "0.0"
        gpuutil_str = "0.0%"
    ret += "\nGPU: " + gputemp_str + "°C" + " / " + gpuutil_str + " util."
    if float(gputemp_str) > 70.0:
        gpu_crit = True
    else:
        gpu_crit = False

    cam_crit = False
    '''ret += "\n------- Cameras -------"
    camstate = []
    for key, value in FPS.items():
        ctstatus0 = "n/a"
        dt = 0.0
        mog = -1
        j = 0
        for i in shmlist:
            try:
                sname, frame, ctstatus, _, tx0 = i
                if key == sname:
                    mog = MOGSENS[j]
                    dt = time.time() - tx0
                    if dt > 30:
                        ctstatus0 = "DOWN"
                    elif dt > 3:
                        ctstatus0 = "DELAYED"
                    else:
                        ctstatus0 = "running"
                    camstate.append(ctstatus0)
            except:
                pass
            j += 1
        ret += "\n" + key + " " + ctstatus0 + " @ %3.1f fps\r" % value + ", sens.=" + str(mog) + " (%.2f" % dt + " sec. ago)"
    if len([c for c in camstate if c != "running"]) > 0:
        cam_crit = True'''
    ret += "\n------- System Summary -------"
    ret += "\nRAM: "
    ret += "CRITICAL!" if mem_crit else "OK!"
    ret += "\nCPU: "
    ret += "CRITICAL!" if cpu_crit else "OK!"
    ret += "\nGPU: "
    ret += "CRITICAL!" if gpu_crit else "OK!"
    ret += "\nCAMs: "
    if state_data.PD_ACTIVE:
        ret += "CRITICAL!" if cam_crit else "OK!"
    else:
        ret += "NOT RUNNING!"
    return ret, mem_crit, cpu_crit, gpu_crit, cam_crit


def run():
    global TERMINATED
    global RESTART

    TERMINATED = False
    RESTART = False

    print("*" * 80)
    print(str(datetime.datetime.now()) + ": START UP - starting guck3 " + os.environ["GUCK3_VERSION"])

    setproctitle("g3." + os.path.basename(__file__))

    # get dirs
    ret, dirs = setup_dirs()
    if ret == -1:
        print(dirs)
        print(str(datetime.datetime.now()) + ": START UP - " + dirs)
        print(str(datetime.datetime.now()) + ": START UP - exiting ...")
    else:
        print(str(datetime.datetime.now()) + ": START UP - setup for folders ok!")

    # redirect prints to file if not started from tty
    old_sys_stdout = sys.stdout
    if not sys.stdout.isatty():
        try:
            sys.stdout = open(dirs["logs"] + "printlog.txt", "w")
        except Exception:
            pass

    # read config
    try:
        cfg_file = dirs["main"] + "guck3.config"
        cfg = configparser.ConfigParser()
        cfg.read(cfg_file)
    except Exception as e:
        print(str(datetime.datetime.now()) + ": START UP - " + str(e) + ": config file syntax error, exiting")
        return -1

    # get log level
    try:
        loglevel_str = cfg["OPTIONS"]["debuglevel"].lower()
        if loglevel_str == "info":
            loglevel = logging.INFO
        elif loglevel_str == "debug":
            loglevel = logging.DEBUG
        elif loglevel_str == "warning":
            loglevel = logging.WARNING
        elif loglevel_str == "error":
            loglevel = logging.ERROR
        else:
            loglevel = logging.INFO
            loglevel_str = "info"
    except Exception:
        loglevel = logging.INFO
        loglevel_str = "info"
    print(str(datetime.datetime.now()) + ": START UP - setting log level to " + loglevel_str)

    print(str(datetime.datetime.now()) + ": START UP - now switching to logging in log files!")

    # global data object
    state_data = StateData()
    state_data.DIRS = dirs

    # init logger
    mp_loggerqueue, mp_loglistener = mplogging.start_logging_listener(dirs["logs"] + "g3.log", maxlevel=loglevel)
    logger = mplogging.setup_logger(mp_loggerqueue, __file__)
    logger.debug(whoami() + "starting with loglevel '" + loglevel_str + "'")
    logger.info(whoami() + "Welcome to GUCK3 " + os.environ["GUCK3_VERSION"])

    # sighandler
    sh = SigHandler_g3(mp_loggerqueue, mp_loglistener, state_data, old_sys_stdout, logger)
    old_sigint = signal.getsignal(signal.SIGINT)
    old_sigterm = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGINT, sh.sighandler_g3)
    signal.signal(signal.SIGTERM, sh.sighandler_g3)

    # init queues
    state_data.PD_INQUEUE = mp.Queue()
    state_data.PD_OUTQUEUE = mp.Queue()
    state_data.MAINQUEUE = queue.Queue()

    # Telegram
    state_data.TG = TelegramThread(state_data, cfg, mp_loggerqueue, logger)
    state_data.TG.start()

    # KeyboardThread
    state_data.KB = KeyboardThread(state_data, cfg, mp_loggerqueue, logger)
    state_data.KB.start()

    while not TERMINATED:
        time.sleep(0.1)

        # get el from peopledetection queue
        try:
            pd_cmd, pd_params = state_data.PD_INQUEUE.get_nowait()
        except (queue.Empty, EOFError):
            pass
        except Exception:
            pass

        # get el from main queue (GeneralMsgHandler)
        # because we cannot start pdedector from thread! (keras/tf bug)
        try:
            mq_cmd, mq_param = state_data.MAINQUEUE.get_nowait()
            if mq_cmd == "start":
                mpp_peopledetection = mp.Process(target=peopledetection.run_cameras,
                                                 args=(state_data.PD_INQUEUE, state_data.PD_OUTQUEUE, state_data.DIRS,
                                                       cfg, mp_loggerqueue, ))
                mpp_peopledetection.start()
                state_data.mpp_peopledetection = mpp_peopledetection
                state_data.PD_OUTQUEUE.put((mq_param + "_active", True))
                try:
                    pd_answer, pd_prm = state_data.PD_INQUEUE.get()
                    if "error" in pd_answer:
                        state_data.PD_ACTIVE = False
                        state_data.mpp_peopledetection.join()
                    else:
                        state_data.PD_ACTIVE = True
                except Exception as e:
                    logger.error(whoami() + str(e) + ": cannot communicate with peopledetection, trying to exit!")
                    state_data.PD_ACTIVE = False
                    try:
                        os.kill(mpp_peopledetection.pid, signal.SIGKILL)
                        mpp_peopledetection.join(timeout=5)
                    except Exception:
                        pass
                    TERMINATED = True
            elif mq_cmd == "stop":
                if state_data.mpp_peopledetection:
                    if state_data.mpp_peopledetection.pid:
                        state_data.PD_OUTQUEUE.put(("stop", None))
                        state_data.mpp_peopledetection.join()
                    state_data.PD_ACTIVE = False
            elif mq_cmd == "exit!!" or mq_cmd == "restart!!":
                
                if mq_cmd == "restart!!":
                    RESTART = True
                if state_data.mpp_peopledetection:
                    if state_data.mpp_peopledetection.pid:
                        state_data.PD_OUTQUEUE.put(("stop", None))
                        state_data.mpp_peopledetection.join()
                        state_data.PD_ACTIVE = False
                TERMINATED = True
        except (queue.Empty, EOFError):
            pass
        except Exception:
            pass

    # shutdown
    exitcode = 1
    if RESTART:
        exitcode = 3
    sh.shutdown(exitcode)
    if sys.stdout != old_sys_stdout:
        sys.stdout = old_sys_stdout
    signal.signal(signal.SIGINT, old_sigint)
    signal.signal(signal.SIGTERM, old_sigterm)
    clear_all_queues([state_data.PD_INQUEUE, state_data.PD_OUTQUEUE, state_data.MAINQUEUE])
    return exitcode
