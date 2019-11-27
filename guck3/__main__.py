import os
import configparser
import ephem
from setproctitle import setproctitle
import logging
import logging.handlers
from guck3 import setup_dirs, mplogging, peopledetection
from guck3.mplogging import whoami
import datetime
import signal
import sys
import multiprocessing as mp


__version__ = "0.1"


class SigHandler_g3:
    def __init__(self, mp_loggerqueue, mp_loglistener, mp_pd, old_sys_stdout, logger):
        self.logger = logger
        self.mp_pd = mp_pd
        self.mp_loggerqueue = mp_loggerqueue
        self.mp_loglistener = mp_loglistener
        self.old_sys_stdout = old_sys_stdout

    def sighandler_g3(self, a, b):
        self.shutdown(1)

    def get_trstr(self, exit_status):
        if exit_status == 3:
            trstr = str(datetime.datetime.now()) + ": RESTART - "
        else:
            trstr = str(datetime.datetime.now()) + ": SHUTDOWN - "
        return trstr

    def shutdown(self, exit_status=3):
        trstr = self.get_trstr(exit_status)
        if self.mp_pd:
            if self.mp_pd.pid:
                print(trstr + "joining peopledetection ...")
                self.mp_pd.join()
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
        sys.exit()


class GControl:

    def __init__(self, _db, logger):
        # configfile path
        self.DB = _db
        self.HCLIMIT = 1

        # nightmode
        # Pressbaum Koordinaten
        self.NIGHTMODE = False
        self.OEPHEM = ephem.Observer()
        self.OEPHEM.lat = self.DB.db_query("ephem", "lat")
        self.OEPHEM.long = self.DB.db_query("ephem", "long")
        self.SUN = ephem.Sun()
        # just for logging
        logger.info("Latitude: " + self.DB.db_query("ephem", "lat"))
        logger.info("Long: " + self.DB.db_query("ephem", "long"))
        sunset0 = ephem.localtime(self.OEPHEM.next_setting(self.SUN))
        logger.info("Sunset: " + str(sunset0.hour + sunset0.minute/60))
        sunrise0 = ephem.localtime(self.OEPHEM.next_rising(self.SUN))
        logger.info("Sunrise: " + str(sunrise0.hour + sunrise0.minute/60))

        # telegram
        self.DO_TELEGRAM = self.DB.db_query("telegram", "do_telegram")
        self.TELEGRAM_MODE = self.DB.db_query("telegram", "mode")
        self.TELEGRAM_TOKEN = self.DB.db_query("telegram", "token")
        self.TELEGRAM_CHATID = [int(x) for x in self.DB.db_query("telegram", "chatidlist")]
        self.MAXT_TELEGRAM = self.DB.db_query("telegram", "maxt")
        self.NO_CHATIDS = len(self.TELEGRAM_CHATID)
        self.LASTTELEGRAM = None

        # basic + heartbeat
        self.DO_LOGFPS = self.DB.db_query("basic", "do_logfps")
        self.DO_CRIT = self.DB.db_query("basic", "warn_on_status")
        self.DO_HEARTBEAT = self.DB.db_query("basic", "do_heartbeat")
        self.SHOW_FRAMES = self.DB.db_query("basic", "show_frames")
        self.MAXT_HEARTBEAT = self.DB.db_query("basic", "maxt_heartbeat")
        self.LASTHEARTBEAT = None
        self.HEARTBEAT_DEST = self.DB.db_query("basic", "heartbeat_dest")
        self.LASTCRIT = None
        self.LASTPROC = None

        # ftp
        '''self.DO_FTP = self.DB.db_query("ftp", "enable")
        self.FTP_SERVER_URL = self.DB.db_query("ftp", "server_url")
        self.FTP_USER = self.DB.db_query("ftp", "user")
        self.FTP_PASSWORD = self.DB.db_query("ftp", "password")
        self.FTP_DIR = self.DB.db_query("ftp", "dir")
        self.FTP_SET_PASSIVE = self.DB.db_query("ftp", "set_passive")
        self.FTP_MAXT = self.DB.db_query("ftp", "maxt")

        # mail
        self.DO_MAIL = self.DB.db_query("mail", "enable")
        self.MAIL_FROM = self.DB.db_query("mail", "from")
        self.MAIL_TO = self.DB.db_query("mail", "to")
        self.MAIL_USER = self.DB.db_query("mail", "user")
        self.MAIL_PASSWORD = self.DB.db_query("mail", "password")
        self.SMTPSERVER = self.DB.db_query("mail", "server")
        self.SMTPPORT = self.DB.db_query("mail", "smtport")
        self.MAXT_MAIL = self.DB.db_query("mail", "maxt")
        self.MAIL_ONLYTEXT = self.DB.db_query("mail", "only_text")
        self.LASTMAIL = None
        self.MAIL = None
        if self.DO_MAIL:
            logger.info("Starting STMTP server ...")
            self.MAIL = guckmsg.SMTPServer(self.MAIL_FROM, self.MAIL_TO, self.SMTPSERVER, self.SMTPPORT, self.MAIL_USER,
                                           self.MAIL_PASSWORD)
            if not self.MAIL.MAILOK:
                logger.warning("Mail credentials wrong or smtp server down or some other bs with mail ...")
                self.MAIL = None
                self.DO_MAIL = False
        else:
            self.MAIL = None

        # sms
        self.DO_SMS = self.DB.db_query("sms", "enable")
        self.SMS_USER = self.DB.db_query("sms", "user")
        self.SMS_HASHCODE = self.DB.db_query("sms", "hashcode")
        self.SMS_SENDER = self.DB.db_query("sms", "sender")
        self.SMS_DESTNUMBER = self.DB.db_query("sms", "destnumber")
        self.SMS_MAXTSMS = self.DB.db_query("sms", "maxt")
        self.LASTSMS = None

        # photo
        self.DO_PHOTO = self.DB.db_query("photo", "enable")
        self.DO_AI_PHOTO = self.DB.db_query("photo", "enable_aiphoto")
        self.APHOTO_DIR = os.environ["GUCK_HOME"] + self.DB.db_query("photo", "aphoto_dir")
        self.AIPHOTO_DIR = os.environ["GUCK_HOME"] + self.DB.db_query("photo", "aiphoto_dir")
        self.AIPHOTO_DIR_NEG = os.environ["GUCK_HOME"] + self.DB.db_query("photo", "aiphoto_dir_neg")
        self.MAXT_DETECTPHOTO = self.DB.db_query("photo", "maxt")
        self.LASTPHOTO = None
        self.PHOTO_CUTOFF = self.DB.db_query("photo", "cutoff")
        self.PHOTO_CUTOFF_LEN = self.DB.db_query("photo", "cutoff_len")

        # AI
        self.AI_MODE = "cnn"
        self.CNN_PATH = os.environ["GUCK_HOME"] + self.DB.db_query("ai", "cnn_path")
        self.CNN_PATH2 = os.environ["GUCK_HOME"] + self.DB.db_query("ai", "cnn_path2")
        self.CNN_PATH3 = os.environ["GUCK_HOME"] + self.DB.db_query("ai", "cnn_path3")
        self.CNNMODEL = None
        self.CNNMODEL2 = None
        self.CNNMODEL3 = None
        self.AI_SENS = self.DB.db_query("ai", "ai_sens")
        thaarpath = self.HAAR_PATH = os.environ["GUCK_HOME"] + self.DB.db_query("ai", "haar_path")
        thaarpath2 = self.HAAR_PATH2 = os.environ["GUCK_HOME"] + self.DB.db_query("ai", "haar_path2")
        self.LASTAIPHOTO = None
        self.AIC = None
        self.AIDATA = []
        self.AI = None
        self.CPUHOG = cv2.HOGDescriptor()
        self.CPUHOG.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
        try:
            self.CNNMODEL = keras.models.load_model(self.CNN_PATH)
            self.CNNMODEL2 = keras.models.load_model(self.CNN_PATH2)
            self.CNNMODEL3 = keras.models.load_model(self.CNN_PATH3)
            logger.info("Created Keras CNN model for people detection")
        except Exception as e:
            logger.warning(str(e) + ": cannot load CNN model, applying fallback to CV2 GPU, exiting ...")
            sys.exit()
        self.RETINA_PATH = os.environ["GUCK_HOME"] + "data/cnn/resnet50_coco_best_v2.1.0.h5"
        try:
            self.RETINAMODEL = models.load_model(self.RETINA_PATH, backbone_name='resnet50')
            # self.RETINAMODEL = keras.models.load_model(self.RETINA_PATH, custom_objects=custom_objects)
            logger.info("Created Keras Retina model for people detection")
        except Exception as e:
            logger.warning(str(e) + ": cannot load retina model, setting it to None!")
            self.RETINAMODEL = None
            sys.exit()

        # cameras
        self.PTZ = {}
        self.REBOOT = {}
        self.MOGSENS = {}
        self.DETECTIONDICT = {}
        self.CAMERADATA = []
        self.VIDEO_INPUT = {}
        cursor = self.DB.db_getall("cameras")
        i = 0
        for cn in cursor:
            tenable = cn["enable"]
            if tenable:
                tchannel = "N/A"
                tgateway = "N/A"
                tstatus = "N/A"
                tinputmode = "camera"   # hardcoded: change to "video" for testing
                tvideofile = os.environ["GUCK_HOME"] + cn["videofile"]
                trecordfile = os.environ["GUCK_HOME"] + cn["recordfile"]
                tcamurl = cn["url"]
                tcamname = cn["name"]
                thostip = cn["host_ip"]
                thostvenv = cn["host_venv"]
                tminarearect = int(cn["min_area_rect"])
                thaarscale = float(cn["haarscale"])
                thogscale = float(cn["hog_scale"])
                thogthresh = float(cn["hog_thresh"])
                tscanrate = int(cn["scanrate"])
                treboot = cn["reboot"]
                tmog2sens = int(cn["mog2_sensitivity"])
                self.MOGSENS[i] = tmog2sens
                self.REBOOT[i] = treboot
                tptzm = cn["ptz_mode"]
                tptzr = cn["ptz_mode"]
                tptzl = cn["ptz_mode"]
                tptzu = cn["ptz_mode"]
                tptzd = cn["ptz_mode"]
                self.PTZ[i] = (tptzm, tptzr, tptzl, tptzu, tptzd)
                try:
                    self.CAMERADATA.append(CameraDataClass(tenable, tchannel, tgateway, tstatus, tinputmode,
                                                           tvideofile, trecordfile, tcamurl, tcamname,
                                                           thostip, thostvenv, tminarearect, thaarpath, thaarpath2,
                                                           thaarscale, thogscale, thogthresh, tscanrate, tptzm,
                                                           tptzr, tptzl, tptzu, tptzd, treboot, tmog2sens))
                except:
                    logger.error("Wrong keys/data for camera" + str(i + 1) + ", exiting ...")
                    sys.exit()
                i += 1
        self.NR_CAMERAS = i - 1

        # init pyzmq server for ssh remote query ("gq")

        shm_initdata = self.PTZ, self.REBOOT, self.MOGSENS
        self.SSHSERVER = guckmsg.SSHServer(False, shm_initdata, threading.Lock())

        # init WastAlarmServer
        self.WAS = guckmsg.WastlAlarmServer(threading.Lock())

        # init telegram
        if self.DO_TELEGRAM:
            logger.info("Initializing Telegram ...")
            try:
                self.TELEGRAMBOT = telepot.Bot(self.TELEGRAM_TOKEN)
            except Exception as e:
                logger.error(e)
                self.DO_TELEGRAM = False
                self.TELEGRAMBOT = None
                logger.info("Please initiate telegram chat with your alarmbot!")

        # send thread
        logger.info("Initializing sendthread ...")
        sd_1 = None
        sd_2 = None
        sd_3 = None
        sd_4 = None
        sd_5 = None
        sd_6 = None     # FTP - Tuple
        if self.DO_MAIL:
            sd_1 = self.MAIL.SMTPSERVER
            sd_2 = self.MAIL.MAIL_FROM
            sd_3 = self.MAIL.MAIL_TO
        if self.DO_TELEGRAM:
            sd_4 = self.TELEGRAMBOT
            sd_5 = self.TELEGRAM_CHATID
        if self.DO_FTP:
            sd_6 = self.FTP_SERVER_URL, self.FTP_USER, self.FTP_PASSWORD, self.FTP_DIR, self.FTP_SET_PASSIVE

        if self.DO_TELEGRAM or self.DO_MAIL or self.DO_FTP:
            self.SENDMSG = guckmsg.MsgSendThread(sd_1, sd_2, sd_3, sd_4, sd_5, sd_6)
            self.SENDMSG.start()
        if self.DO_FTP:
            if not self.SENDMSG.FTP.FTPOK:
                self.DO_FTP = None
                logger.warning("Cannot login to FTP server, disabling FTP!")
            else:
                logger.info("Login to FTP successfull")'''


def run():
    print(str(datetime.datetime.now()) + ": START UP - starting guck3 " + __version__)

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

    # init logger
    mp_loggerqueue, mp_loglistener = mplogging.start_logging_listener(dirs["logs"] + "g3.log", maxlevel=loglevel)
    logger = mplogging.setup_logger(mp_loggerqueue, __file__)
    logger.debug(whoami() + "starting with loglevel '" + loglevel_str + "'")
    logger.info(whoami() + "Welcome to GUCK3 " + __version__)

    # start peopledetection & sighandler
    mpp_peopledetection = mp.Process(target=peopledetection.g3_main, args=(cfg, mp_loggerqueue, ))
    sh = SigHandler_g3(mp_loggerqueue, mp_loglistener, mpp_peopledetection, old_sys_stdout, logger)
    signal.signal(signal.SIGINT, sh.sighandler_g3)
    signal.signal(signal.SIGTERM, sh.sighandler_g3)
    mpp_peopledetection.start()
    mpp_peopledetection.join()

    # shutdown
    sh.shutdown(1)
    if sys.stdout != old_sys_stdout:
        sys.stdout = old_sys_stdout
    return 1
