import json
import os
import sensors
import psutil
import configparser
from setproctitle import setproctitle
import logging
import logging.handlers
from guck3 import setup_dirs, mplogging, peopledetection, clear_all_queues, ConfigReader, get_sens_temp, get_external_ip
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
import cv2
from guck3 import webflask
import urllib.request
import base64
import numpy as np


TERMINATED = False
RESTART = False


def get_free_photos(dir, camera_config, logger):
    freedir = dir + "free/"
    if not os.path.exists(freedir):
        try:
            os.mkdir(freedir)
        except Exception as e:
            logger.warning(whoami() + str(e))
            return []
    filelist = [f for f in os.listdir(freedir)]
    for f in filelist:
        try:
            os.remove(freedir + f)
        except Exception as e:
            logger.warning(whoami() + str(e))
    urllist = []
    for c in camera_config:
        urllist.append((c["name"], c["photo_url"], c["user"], c["password"]))
    freephotolist = []
    for cname, url, user, pw in urllist:
        try:
            request = urllib.request.Request(url)
            base64string = base64.b64encode(bytes('%s:%s' % (user, pw),'ascii'))
            request.add_header("Authorization", "Basic %s" % base64string.decode('utf-8'))
            result = urllib.request.urlopen(request, timeout=3)
            image = np.asarray(bytearray(result.read()), dtype="uint8")
            image = cv2.imdecode(image, cv2.IMREAD_COLOR)
            datestr = datetime.datetime.now().strftime("%d%m%Y-%H:%M:%S")
            photoname = freedir + cname + "_" + datestr + ".jpg"
            cv2.imwrite(photoname, image)
            freephotolist.append(photoname)
        except Exception as e:
            logger.warning(whoami() + str(e))
    return freephotolist


def GeneralMsgHandler(msg, bot, state_data, mp_loggerqueue):
    global TERMINATED
    global RESTART
    # bot = tgram / kbd
    bot0 = bot.lower()
    if bot0 not in ["tgram", "kbd", "wf"]:
        return None

    if msg == "start":
        state_data.MAINQUEUE.put(("start", bot0))
        reply = "starting GUCK3 people detection ..."
    elif msg == "stop":
        if state_data.mpp_peopledetection:
            if state_data.mpp_peopledetection.pid:
                state_data.MAINQUEUE.put(("stop", None))
                reply = "stopping GUCK3 people detection ..."
        else:
            reply = "GUCK3 people detection is NOT running, cannot stop!"
    elif msg == "exit!!" or msg == "restart!!":
        if msg == "restart!!":
            reply = "restarting GUCK3!"
        else:
            reply = "exiting GUCK3!"
        state_data.MAINQUEUE.put((msg, None))
    elif msg.replace(" ", "") == "recordon" and not state_data.DO_RECORD:
        if not state_data.PD_ACTIVE:
            reply = "People Detection no running, cannot start recording"
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
        global TERMINATED
        TERMINATED = True
        # self.shutdown(exit_status=1)

    def get_trstr(self, exit_status):
        if exit_status == 3:
            trstr = str(datetime.datetime.now()) + ": RESTART - "
        else:
            trstr = str(datetime.datetime.now()) + ": SHUTDOWN - "
        return trstr

    def shutdown(self, exit_status=1):
        trstr = self.get_trstr(exit_status)
        if self.state_data.TG and self.state_data.TG.running:
            self.state_data.TG.stop()
        if self.state_data.KB and self.state_data.KB.active:
            self.state_data.KB.stop()
            self.state_data.KB.join()
        mp_pd = self.state_data.mpp_peopledetection
        if mp_pd:
            if mp_pd.pid:
                print(trstr + "joining peopledetection ...")
                self.state_data.PD_OUTQUEUE.put("stop")
                mp_pd.join()
                print(self.get_trstr(exit_status) + "peopledetection exited!")
        mp_wf = self.state_data.mpp_webflask
        trstr = self.get_trstr(exit_status)
        if mp_wf:
            if mp_wf.pid:
                os.kill(mp_wf.pid, signal.SIGFPE)
                time.sleep(0.2)
                print(trstr + "joining flask webserver, this may take a while ...")
                os.kill(mp_wf.pid, signal.SIGTERM)
                mp_wf.join(timeout=10)
                if mp_wf.is_alive():
                    os.kill(mp_wf.pid, signal.SIGQUIT)
                    mp_wf.join()
                print(self.get_trstr(exit_status) + "flask webserver exited!")
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
    except Exception:
        pass


class StateData:
    def __init__(self):
        self.PD_ACTIVE = False
        self.mpp_peopledetection = None
        self.mpp_webflask = None
        self.TG = None
        self.KB = None
        self.PD_INQUEUE = None
        self.PD_OUTQUEUE = None
        self.NS_INQUEUE = None
        self.NS_OUTQUEUE = None
        self.MAINQUEUE = None
        self.DIRS = None
        self.DO_RECORD = False
        self.CAMERADATA = []
        self.CAMERA_CONFIG = []


class KeyboardThread(Thread):
    def __init__(self, state_data, cfgr, mp_loggerqueue, logger):
        Thread.__init__(self)
        self.daemon = True
        self.state_data = state_data
        self.mp_loggerqueue = mp_loggerqueue
        self.pd_inqueue = self.state_data.PD_INQUEUE
        self.pd_outqueue = self.state_data.PD_OUTQUEUE
        self.cfgr = cfgr
        self.logger = logger
        self.running = False
        self.active = self.get_config()
        self.kbqueue = mp.Queue()
        self.fn = sys.stdin.fileno()
        self.is_shutdown = False

    def get_config(self):
        active = self.cfgr.get_options()["keyboard_active"]
        return active

    def sighandler_kbd(self, a,  b):
        self.running = False

    def send_message_all(self, txt):
        if not self.active:
            return
        print(txt)

    def send_photo(self, photopath):
        pass

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
                reply = GeneralMsgHandler(msg, "kbd", self.state_data, self.mp_loggerqueue)
                print(reply)
                print(instruction)
        self.logger.debug(whoami() + "keyboard thread stopped!")


class TelegramThread:
    def __init__(self, state_data, cfgr, mp_loggerqueue, logger):
        self.state_data = state_data
        self.mp_loggerqueue = mp_loggerqueue
        self.pd_inqueue = self.state_data.PD_INQUEUE
        self.pd_outqueue = self.state_data.PD_OUTQUEUE
        self.cfgr = cfgr
        self.logger = logger
        self.active, self.token, self.chatids = self.get_config()
        self.running = False

    def start(self):
        if not self.active:
            return -1
        self.logger.debug(whoami() + "starting telegram handler")
        self.logger.debug(whoami() + "telegram  token & chat ids: " + str(self.token) + " / " + str(self.chatids))
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
        if not self.active:
            return
        for c in self.chatids:
            try:
                self.bot.send_message(chat_id=c, text=text)
            except Exception as e:
                self.logger.warning(whoami() + str(e) + ": chat_id " + str(c))

    def send_photo(self, photopath):
        if not self.active:
            return
        for c in self.chatids:
            try:
                self.bot.send_photo(chat_id=c, photo=open(photopath, "rb"))
            except Exception as e:
                self.logger.warning(whoami() + str(e) + ": chat_id " + str(c))

    def get_config(self):
        t = self.cfgr.get_telegram()
        if t["active"].lower() == "no":
            return False, None, None
        try:
            token = t["token"]
            chatids = json.loads(t["chatids"])
            self.logger.debug(whoami() + "got config for active telegram bot")
        except Exception as e:
            self.logger.debug(whoami() + str(e) + "telegram config error, setting telegram to inactive!")
            return False, None, None
        return True, token, chatids

    def handler(self, update, context):
        msg = update.message.text.lower()
        reply = GeneralMsgHandler(msg, "tgram", self.state_data, self.mp_loggerqueue)
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
    if state_data.PD_ACTIVE:
        ret += "\n------- Cameras -------"
        for c in state_data.CAMERADATA:
            cname, cframe, cfps, cisok, cactive, ctx = c
            if not cactive:
                ctstatus0 = "DISABLED"
                ret += "\n" + cname + " " + ctstatus0
            else:
                try:
                    dt = time.time() - ctx
                except Exception:
                    dt = 31
                if dt > 30 or not cisok:
                    ctstatus0 = "DOWN"
                elif dt > 3:
                    ctstatus0 = "DELAYED"
                else:
                    ctstatus0 = "running"
                    if ctstatus0 in ["DOWN", "DELAYED"]:
                        cam_crit = True
                    else:
                        cam_crit = False
                ret += "\n" + cname + " " + ctstatus0 + " @ %3.1f fps" % cfps + ", (%.2f" % dt + " sec. ago)"

    temp, hum = get_sens_temp()
    ret += "\n------- Sensors -------"
    ret += "\nTemperature:  " + "%.1f" % temp + "C"
    ret += "\nHumidity: " + "%.1f" % hum + "%"
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


def run(startmode="systemd"):
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

    cfgr = ConfigReader(cfg)

    # get log level
    try:
        loglevel_str = cfg["OPTIONS"]["LOGLEVEL"].lower()
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
    
    # get camera data
    cfgr = ConfigReader(cfg)
    state_data.CAMERA_CONFIG= cfgr.get_cameras()

    # init logger
    print(dirs["logs"] + "g3.log")
    mp_loggerqueue, mp_loglistener = mplogging.start_logging_listener(dirs["logs"] + "g3.log", maxlevel=loglevel)
    logger = mplogging.setup_logger(mp_loggerqueue, __file__)
    logger.debug(whoami() + "starting with loglevel '" + loglevel_str + "'")
    logger.info(whoami() + "Welcome to GUCK3 " + os.environ["GUCK3_VERSION"])
    logger.info(whoami() + "started with startmode " + startmode)

    # sighandler
    sh = SigHandler_g3(mp_loggerqueue, mp_loglistener, state_data, old_sys_stdout, logger)
    old_sigint = signal.getsignal(signal.SIGINT)
    old_sigterm = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGINT, sh.sighandler_g3)
    signal.signal(signal.SIGTERM, sh.sighandler_g3)

    # save photos setup
    try:
        options = cfgr.get_options()
        addtl_photo_path = options["addtl_photo_path"]
        if addtl_photo_path.lower() == "none":
            addtl_photo_path = None
    except Exception:
        addtl_photo_path = None

    # init queues
    state_data.PD_INQUEUE = mp.Queue()
    state_data.PD_OUTQUEUE = mp.Queue()
    state_data.MAINQUEUE = queue.Queue()
    state_data.WF_INQUEUE = mp.Queue()
    state_data.WF_OUTQUEUE = mp.Queue()
    state_data.NS_INQUEUE = mp.Queue()
    state_data.NS_OUTQUEUE = mp.Queue()

    # WebServer
    try:
        webflask.REDISCLIENT.ping()
    except Exception:
        logger.error(whoami() + "cannot start webserver due to redis server not available, exiting")
        sh.shutdown()
        return -1
    state_data.mpp_webflask = mp.Process(target=webflask.main, args=(cfg, dirs, state_data.WF_OUTQUEUE,
                                                                     state_data.WF_INQUEUE, mp_loggerqueue, ))
    state_data.mpp_webflask.start()
    if state_data.WF_INQUEUE.get() == "False":
        logger.error(whoami() + ": cannot init DB, exiting")
        sh.shutdown()
        return -1

    commlist = []
    # Telegram
    state_data.TG = TelegramThread(state_data, cfgr, mp_loggerqueue, logger)
    state_data.TG.start()
    commlist.append(state_data.TG)

    # KeyboardThread
    if startmode != "systemd":
        state_data.KB = KeyboardThread(state_data, cfgr, mp_loggerqueue, logger)
        state_data.KB.start()
        commlist.append(state_data.KB)
    else:
        state_data.KB = None

    wf_msglist = []
    pd_cmd = None

    while not TERMINATED:

        time.sleep(0.02)

        # get from webflask queue
        try:
            wf_cmd, wf_data = state_data.WF_INQUEUE.get_nowait()
            if wf_cmd == "get_pd_status":
                state_data.WF_OUTQUEUE.put((state_data.PD_ACTIVE, wf_msglist))
                wf_msglist = []
            elif wf_cmd == "set_pdstart":
                state_data.WF_OUTQUEUE.put((state_data.PD_ACTIVE, None))
                pd_cmd = "start"
            elif wf_cmd == "set_pdstop":
                state_data.WF_OUTQUEUE.put((state_data.PD_ACTIVE, None))
                pd_cmd = "stop"
            elif wf_cmd == "set_pdrestart":
                state_data.WF_OUTQUEUE.put((state_data.PD_ACTIVE, None))
                pd_cmd = "restart!!"
            elif wf_cmd == "get_host_status":
                ret, mem_crit, cpu_crit, gpu_crit, cam_crit = get_status(state_data)
                state_data.WF_OUTQUEUE.put(("status", (ret, mem_crit, cpu_crit, gpu_crit, cam_crit)))
            elif wf_cmd == "get_free_photodata":
                imglist = get_free_photos(dirs["photo"], state_data.CAMERA_CONFIG, logger)
                state_data.WF_OUTQUEUE.put(("free_photodata", imglist))
        except (queue.Empty, EOFError):
            pass
        except Exception:
            pass

        # get el from peopledetection queue (clear it always!!)
        pdmsglist = []
        while True:
            try:
                pdmsglist = state_data.PD_INQUEUE.get_nowait()
            except (queue.Empty, EOFError):
                break
            except Exception:
                break

        if pdmsglist:
            state_data.CAMERADATA = []
            for pdmsg, pdpar in pdmsglist:
                c_cname, c_frame, _, _, _, _ = pdpar
                state_data.CAMERADATA.append(pdpar)
                if pdmsg == "detection":
                    try:
                        logger.info(whoami() + "received detection for " + c_cname)
                        for c in commlist:
                            c.send_message_all(time.strftime("%d-%m-%Y %H:%M:%S") + ": Human detected @ " + c_cname + "!")
                        # save photo
                        datestr = datetime.datetime.now().strftime("%d%m%Y-%H:%M:%S")
                        short_photo_name = c_cname + "_" + datestr + ".jpg"
                        photo_name = dirs["photo"] + short_photo_name
                        wf_msglist.insert(0, photo_name)
                    except Exception as e:
                        logger.warning(whoami() + str(e))
                    try:
                        cv2.imwrite(photo_name, c_frame)
                        for c in commlist:
                            c.send_photo(photo_name)
                        if addtl_photo_path:
                            photo_name2 = addtl_photo_path + c_cname + "_" + datestr + ".jpg"
                            cv2.imwrite(photo_name2, c_frame)
                        logger.debug(whoami() + "saved detection photo " + photo_name)
                    except Exception as e:
                        logger.warning(whoami() + str(e))

        # get el from main queue (GeneralMsgHandler)
        # because we cannot start pdedector from thread! (keras/tf bug/feature!?)
        try:
            mq_cmd = None
            mq_param = None
            if not pd_cmd:
                mq_cmd, mq_param = state_data.MAINQUEUE.get_nowait()
                print(mq_cmd)
            else:
                if pd_cmd == "start":
                    mq_cmd = "start"
                    mq_param = "wf"
                elif pd_cmd == "stop":
                    mq_cmd = "stop"
                    mq_param = "wf"
                elif pd_cmd == "restart!!":
                    mq_cmd = "restart!!"
                    mq_param = "wf"
                pd_cmd = None
            if mq_cmd == "start" and not state_data.PD_ACTIVE:
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
                        logger.error(whoami() + ": cameras/PD startup failed!")
                        state_data.mpp_peopledetection.join()
                        for c in commlist:
                            c.send_message_all("Error - cannot start GUCK3 people detection!")
                    else:
                        logger.info(whoami() + "cameras/PD started!")
                        state_data.PD_ACTIVE = True
                        for c in commlist:
                            c.send_message_all("... GUCK3 people detection started!")
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
                        state_data.mpp_peopledetection = None
                        for c in commlist:
                            c.send_message_all("... GUCK3 people detection stopped!")
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
    # close all the other mps & stuff
    logger.info(whoami() + "calling shutdown sequence ...")
    sh.shutdown(exitcode)
    print("... shutdown sequence finished!")

    if sys.stdout != old_sys_stdout:
        sys.stdout = old_sys_stdout
    signal.signal(signal.SIGINT, old_sigint)
    signal.signal(signal.SIGTERM, old_sigterm)
    clear_all_queues([state_data.PD_INQUEUE, state_data.PD_OUTQUEUE, state_data.MAINQUEUE])
    return exitcode
