import os
import queue
from setproctitle import setproctitle
from guck3.mplogging import whoami
from guck3 import mplogging
from telegram.ext import Updater, MessageHandler, Filters
import signal
import json
import time
import sensors
import psutil
import subprocess

TERMINATED = False
PD_ACTIVE = False


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
        if msg == "start":
            reply = "starting GUCK3 alarm system"
            self.outqueue.put("start")
        elif msg == "stop":
            reply = "stopping GUCK3 alarm system"
            self.outqueue.put("stop")
        elif msg == "exit!!":
            reply = "exiting GUCK3!"
            self.outqueue.put("exit")
        elif msg == "status":
            reply, _, _, _, _ = get_status()
        update.message.reply_text(reply)


def get_status():
    global PD_ACTIVE

    osversion = os.popen("cat /etc/os-release").read().split("\n")[2].split("=")[1].replace('"', '')

    # os & version
    ret = "------- General -------"
    ret += "\nOS: " + osversion
    ret += "\nVersion: " + os.environ["GUCK3_VERSION"]
    ret += "\nAlarm System Active: "
    ret += "YES" if PD_ACTIVE else "NO"
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
    gputemp = subprocess.Popen([smifn, "--query-gpu=temperature.gpu", "--format=csv"],
                               stdout=subprocess.PIPE).stdout.readlines()[1]
    gpuutil = subprocess.Popen([smifn, "--query-gpu=utilization.gpu", "--format=csv"],
                               stdout=subprocess.PIPE).stdout.readlines()[1]
    gputemp_str = gputemp.decode("utf-8").rstrip()
    gpuutil_str = gpuutil.decode("utf-8").rstrip()
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
    ret += "CRITICAL!" if cam_crit else "OK!"
    return ret, mem_crit, cpu_crit, gpu_crit, cam_crit


def run_mpcommunicator(pd_outqueue, pd_inqueue, cfg, mp_loggerqueue):
    global PD_ACTIVE

    setproctitle("g3." + os.path.basename(__file__))

    logger = mplogging.setup_logger(mp_loggerqueue, __file__)
    logger.info(whoami() + "starting ...")

    sh = SigHandler_mpcomm(logger)
    signal.signal(signal.SIGINT, sh.sighandler_mpcomm)
    signal.signal(signal.SIGTERM, sh.sighandler_mpcomm)

    tg = TelegramComm(pd_outqueue, pd_inqueue, cfg, logger)
    tg.start()
    pd_outqueue.put(tg.active)

    # ------ main looooooooop -------
    while not TERMINATED:
        time.sleep(0.1)
        try:
            pd_cmd, pd_params = pd_inqueue.get_nowait()
            if pd_cmd == "exit":
                logger.debug(whoami() + "got exit cmd from pd")
                break
            if pd_cmd == "capture_active":
                PD_ACTIVE = pd_params
        except (queue.Empty, EOFError):
            continue
        except Exception:
            continue

    tg.stop()

    logger.info(whoami() + "... exited!")
