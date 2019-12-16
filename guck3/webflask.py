from __future__ import unicode_literals
import multiprocessing
import gunicorn.app.base
from flask import Flask, render_template, make_response, request


def number_of_workers():
    return (multiprocessing.cpu_count() * 2) + 1


app = Flask(__name__)


@app.route('/')
def index():
    return render_template('index.html')


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


def main(cfg, dirs, loggerqueue):
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
