from os.path import expanduser
import os
import shutil


# setup folders
def setup_dirs():
    install_dir = os.path.dirname(os.path.realpath(__file__))
    userhome = expanduser("~")
    maindir = userhome + "/.guck3/"
    logsdir = maindir + "logs/"
    dirs = {
        "install": install_dir,
        "home": userhome,
        "main": maindir,
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
