from __future__ import unicode_literals
import multiprocessing
import gunicorn.app.base
import os
from flask import Flask, render_template, make_response, request, g, redirect, url_for, flash
from flask_sse import sse
from flask_session import Session
import flask_login
from setproctitle import setproctitle
from guck3.mplogging import whoami
from guck3 import mplogging
from guck3.g3db import G3DB
import time
from guck3 import models


DB = None
INQUEUE = None
OUTQUEUE = None
LOGGER = None
USERS = None
USERDATA = None


def number_of_workers():
    return (multiprocessing.cpu_count() * 2) + 1


# init flask
app = Flask(__name__)
app.secret_key = "dfdsmdsv11nmDFSDfds"
app.config['SESSION_TYPE'] = 'filesystem'
app.config["REDIS_URL"] = "redis://etec.iv.at"
app.register_blueprint(sse, url_prefix='/stream')
Session(app)

# Login Manager
login_manager = flask_login.LoginManager()
login_manager.login_view = 'userlogin'
login_manager.init_app(app)


@app.before_request
def beforerequest():
    try:
        user0 = flask_login.current_user.get_id()
        g.user = user0
        if user0 is not None:
            USERDATA = DB.get_userdata()
            if user0 not in USERDATA:
                DB.insert_new_userdata(user0, time.time(), True, 0, [])
            else:
                DB.update_userdata(user0, time.time(), True, USERDATA[user0]["no_newdetections"],
                                   USERDATA[user0]["photolist"])
    except Exception as e:
        print(str(e))
        pass


# Login Manager
class User(flask_login.UserMixin):
    pass


@login_manager.user_loader
def user_loader(email):
    if email not in USERS:
        return
    user = User()
    user.id = email
    return user


@app.route("/", methods=['GET', 'POST'])
@app.route("/home", methods=['GET', 'POST'])
def index():
    return render_template('index.html', userauth=flask_login.current_user.is_authenticated)


@app.route("/detections", methods=['GET', 'POST'])
@flask_login.login_required
def detections():
    return render_template('index.html', userauth=flask_login.current_user.is_authenticated)


@app.route("/userlogin", methods=['GET', 'POST'])
def userlogin():
    if request.method == "GET":
        userloginform = models.UserLoginForm(request.form)
        return render_template("login.html", userloginform=userloginform, userauth=flask_login.current_user.is_authenticated)
    else:
        userloginform = models.UserLoginForm(request.form)
        email = userloginform.email.data
        pw = userloginform.password.data
        try:
            correct_pw = USERS[email]
        except Exception:
            return redirect(url_for("index"))
        if pw == correct_pw:
            user = User()
            user.id = email
            flask_login.login_user(user)
            return render_template("index.html")
        return redirect(url_for('index'))
    return render_template('index.html', userauth=flask_login.current_user.is_authenticated)


@app.route("/userlogout", methods=['GET', 'POST'])
@flask_login.login_required
def userlogout():
    global USER
    flask_login.logout_user()
    USER = None
    return render_template("index.html", userauth=flask_login.current_user.is_authenticated)


class StandaloneApplication(gunicorn.app.base.BaseApplication):

    def __init__(self, app, options=None):
        self.options = options or {}
        self.application = app
        super().__init__()
        # super(StandaloneApplication, self).__init__()

    def load_config(self):
        config = {key: value for key, value in self.options.items()
                  if key in self.cfg.settings and value is not None}
        for key, value in config.items():
            self.cfg.set(key.lower(), value)

    def load(self):
        return self.application


def main(cfg, mplock, dirs, inqueue, outqueue, loggerqueue):
    global DB
    global INQUEUE
    global OUTQUEUE
    global LOGGER
    global USERS

    setproctitle("g3." + os.path.basename(__file__))

    LOGGER = mplogging.setup_logger(loggerqueue, __file__)
    LOGGER.info(whoami() + "starting ...")

    db = G3DB(mplock, cfg, dirs, LOGGER)
    DB = db
    INQUEUE = inqueue
    OUTQUEUE = outqueue

    # Password
    USERS = DB.get_users()
    for key, item in USERS.items():
        print(key, item)
    USERDATA = DB.get_userdata()

    options = {
        'bind': '%s:%s' % ('127.0.0.1', '8080'),
        'error-logfile':  dirs["logs"] + "webflask_error.log",
        'log-file': dirs["logs"] + "webflask.log",
        'capture-output': True,
        'workers': number_of_workers(),
    }
    StandaloneApplication(app, options).run()


if __name__ == '__main__':
    main()
