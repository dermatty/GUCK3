from os.path import expanduser
import os
import shutil
import queue


# setup folders
def setup_dirs():
    install_dir = os.path.dirname(os.path.realpath(__file__))
    userhome = expanduser("~")
    maindir = userhome + "/.guck3/"
    logsdir = maindir + "logs/"
    videodir = maindir + "video/"
    dirs = {
        "install": install_dir,
        "home": userhome,
        "main": maindir,
        "video": videodir,
        "logs": logsdir
    }

    # check for maindir
    if not os.path.exists(maindir):
        try:
            os.mkdir(maindir)
        except Exception as e:
            return -1, str(e)

    # check for logsdir
    if not os.path.exists(logsdir):
        try:
            os.mkdir(logsdir)
        except Exception as e:
            return -1, str(e) + ": cannot create logs directory!", None, None, None, None, None

    # check for logsdir
    if not os.path.exists(videodir):
        try:
            os.mkdir(videodir)
        except Exception as e:
            return -1, str(e) + ": cannot create video directory!", None, None, None, None, None

    # check for configfile
    if not os.path.isfile(maindir + "guck3.config"):
        config_template = "/etc/default/guck3.config"
        if os.path.isfile(config_template):
            try:
                shutil.copy(config_template, maindir + "guck3.config")
            except Exception as e:
                return -1, str(e) + ": cannot initialize guck3.config file!"
        else:
            try:
                shutil.copy(install_dir + "/data/guck3.config", maindir + "guck3.config")
            except Exception as e:
                return -1, str(e) + ": cannot initialize guck3.config file!"

    return 1, dirs


# clear all queues
def clear_all_queues(queuelist):
    for q in queuelist:
        while True:
            try:
                q.get_nowait()
            except (queue.Empty, EOFError):
                break
