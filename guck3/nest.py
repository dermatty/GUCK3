import os
import sys
import signal
import queue
import sseclient   # Achtung: sseclient-py !!!
import urllib3
import http
from urllib.parse import urlparse
import certifi
from threading import Thread, Lock
import json
import time
from setproctitle import setproctitle
from guck3.mplogging import whoami
from guck3 import mplogging, clear_all_queues

TERMINATED = False


class SigHandler_ns:
    def __init__(self, logger):
        self.logger = logger

    def sighandler_ns(self, a, b):
        self.shutdown()

    def shutdown(self):
        global TERMINATED
        TERMINATED = True
        self.logger.debug(whoami() + "got signal, exiting ...")


class Nest_sse(Thread):
    def __init__(self, token, api_endpoint, msg, logger):
        Thread.__init__(self)
        self.daemon = True
        self.lock = Lock()
        self.LAST_KEEPALIVE = time.time()
        self.TOKEN = token
        self.API_ENDPOINT = api_endpoint
        self.STATUS = 1
        self.client = None
        self.NESTLIST = []
        self.OLDNESTLIST = []
        self.STRUCTURE_STATUS_CHANGED = []
        self.DEVICE_STATUS_CHANGED = []
        self.LASTKEEPALIVE = time.time()
        self.SHOWINITIALSTATUS = False
        self.logger = logger
        self.do_send = False
        self.SEND = None
        if msg.upper() == "STATUS":
            self.SHOWINITIALSTATUS = True

    # compares NESTLIST to OLDNESTLIST and returns differences:
    #     "away" status per structure
    #     "co_alarm_state", "smoke_alarm_state", "battery_health" per device
    def check_status(self):
        ssch = []
        dsch = []
        statuschanged = False
        for n0 in self.NESTLIST:
            locationfound = False
            for n1 in self.OLDNESTLIST:
                if n1["name"] == n0["name"]:
                    locationfound = True
                    if n1["away"] != n0["away"]:
                        ssch.append((n1["name"], "away", n0["away"]))
                        statuschanged = True
                    for ln0 in n0["locations"]:
                        devicefound = False
                        for ln1 in n1["locations"]:
                            if ln0["name"] == ln1["name"]:
                                devicefound = True
                                if ln0["co_alarm_state"] != ln1["co_alarm_state"]:
                                    statuschanged = True
                                    dsch.append((n1["name"], ln1["name"], "co_alarm_state", ln0["co_alarm_state"]))
                                if ln0["smoke_alarm_state"] != ln1["smoke_alarm_state"]:
                                    statuschanged = True
                                    dsch.append((n1["name"], ln1["name"], "smoke_alarm_state", ln0["smoke_alarm_state"]))
                                if ln0["battery_health"] != ln1["battery_health"]:
                                    statuschanged = True
                                    dsch.append((n1["name"], ln1["name"], "battery_health", ln0["battery_health"]))
                        if not devicefound:
                            statuschanged = True
                            dsch.append((n1["name"], ln0["name"], "new_device", ""))
                            dsch.append((n1["name"], ln0["name"], "co_alarm_state", ln0["co_alarm_state"]))
                            dsch.append((n1["name"], ln0["name"], "smoke_alarm_state", ln0["smoke_alarm_state"]))
                            dsch.append((n1["name"], ln0["name"], "battery_health", ln0["battery_health"]))
            if not locationfound:
                statuschanged = True
                ssch.append((n0["name"], "new_structure", ""))
                ssch.append((n0["name"], "away", n0["away"]))
                for ln0 in n0["locations"]:
                    dsch.append((n0["name"], ln0["name"], "co_alarm_state", ln0["co_alarm_state"]))
                    dsch.append((n0["name"], ln0["name"], "smoke_alarm_state", ln0["smoke_alarm_state"]))
                    dsch.append((n0["name"], ln0["name"], "battery_health", ln0["battery_health"]))
        self.STRUCTURE_STATUS_CHANGED = ssch
        self.DEVICE_STATUS_CHANGED = dsch
        return statuschanged

    def update_status(self, eventdata):
        try:
            nestlist = []
            structures = eventdata["data"]["structures"]
            for key, s in structures.items():
                structure = {}
                structure["name"] = s["name"]
                structure["away"] = s["away"]
                structure["co_alarm_state"] = s["co_alarm_state"]
                structure["smoke_alarm_state"] = s["smoke_alarm_state"]
                structure["locations"] = []
                for location in s["smoke_co_alarms"]:
                    loc = {}
                    s0 = eventdata["data"]["devices"]["smoke_co_alarms"][location]
                    loc["name"] = s0["name"]
                    loc["co_alarm_state"] = s0["co_alarm_state"]
                    loc["smoke_alarm_state"] = s0["smoke_alarm_state"]
                    loc["battery_health"] = s0["battery_health"]
                    structure["locations"].append(loc)
                nestlist.append(structure)
            self.OLDNESTLIST = self.NESTLIST
            self.NESTLIST = nestlist
            return True
        except Exception as e:
            self.logger.error("Nest update: " + str(e))
            return False

    def connect(self):
        headers0 = {
            'Authorization': "Bearer " + self.TOKEN,
            'Accept': 'text/event-stream'
        }
        url = self.API_ENDPOINT

        # Test for redirect
        conn = http.client.HTTPSConnection("developer-api.nest.com")
        headers = {'authorization': "Bearer {0}".format(self.TOKEN)}
        conn.request("GET", "/", headers=headers)
        response = conn.getresponse()
        if response.status == 307:
            redirectLocation = urlparse(response.getheader("location"))
            conn = http.client.HTTPSConnection(redirectLocation.netloc)
            conn.request("GET", "/", headers=headers)
            response = conn.getresponse()
            if response.status != 200:
                self.logger.error("Cannot connect to NEST, redirect with non 200 response, aborting ...")
                return False
            url = "https://" + redirectLocation.netloc

        http0 = urllib3.PoolManager(cert_reqs='CERT_REQUIRED', ca_certs=certifi.where())
        response = http0.request('GET', url, headers=headers0, preload_content=False)

        if response.status != 200:
            self.logger.error("Cannot connect to redirected NEST, aborting ...")
            return False
        try:
            client = sseclient.SSEClient(response)
        except Exception as e:
            self.logger.error(str(e))
            return False
        self.logger.info("NEST: Connected to " + url)
        return client

    def retry_connect(self, maxtry=10):
        client = False
        i = 1
        while not client and i <= maxtry:
            client = self.connect()
            if client:
                break
            time.sleep(3)
            i += 1
        if client:
            self.STATUS = 1
        else:
            self.STATUS = -2
        return client

    def send(self):
        with self.lock:
            self.do_send = True
            self.SEND = self.STRUCTURE_STATUS_CHANGED, self.DEVICE_STATUS_CHANGED, self.NESTLIST

    def fetch(self):
        if self.do_send:
            with self.lock:
                self.do_send = False
                return self.SEND
        else:
            return None

    def run(self):
        self.logger.info("Starting nest retry_connect")
        self.client = self.retry_connect()
        if self.STATUS == -2:
            time.sleep(3)
            return

        self.logger.info("Waiting for NEST events ...")

        msgcounter = 0
        for event in self.client.events():  # returns a generator
            try:
                event_type = event.event
                # print("event: ", event_type)
                if event_type == 'open':  # not always received here
                    self.logger.info("The event stream has been opened")
                elif event_type == 'put':
                    # if status notfier for first msg is not requested -> continue
                    if msgcounter == 0 and not self.SHOWINITIALSTATUS:
                        msgcounter += 1
                        continue
                    eventdata = json.loads(event.data)
                    self.update_status(eventdata)
                    if self.check_status():
                        self.logger.info("Nest status has changed, communicating ...")
                        self.send()
                        # CONNECTOR_AUX.send_to_connector("nest", "send", (self.STRUCTURE_STATUS_CHANGED, self.DEVICE_STATUS_CHANGED, self.NESTLIST))
                elif event_type == 'keep-alive':
                    self.logger.info("keep alive")
                    pass
                elif event_type == 'auth_revoked':
                    # print("revoked token: ", event.data)
                    raise Exception("AUTH ERROR")
                elif event_type == 'error':
                    raise Exception(str(event.data))
                else:
                    raise Exception("unknown event, no handler for it")
            except Exception as e:
                if str(e) == "AUTH_ERROR":
                    self.STATUS = -2
                    self.logger.error("Nest loop error: " + str(e))
                else:
                    self.STATUS = -1
                    self.logger.warning("Nest loop warning: " + str(e))
            msgcounter += 1
            self.LASTKEEPALIVE = time.time()


def run_nest(ns_outqueue, ns_inqueue, dirs, cfg, mp_loggerqueue):
    global TERMINATED

    setproctitle("g3." + os.path.basename(__file__))

    logger = mplogging.setup_logger(mp_loggerqueue, __file__)
    logger.info(whoami() + "starting ...")

    sh = SigHandler_ns(logger)
    signal.signal(signal.SIGINT, sh.sighandler_ns)
    signal.signal(signal.SIGTERM, sh.sighandler_ns)

    try:
        nest_token = cfg["NEST"]["TOKEN"]
        nest_api_url = "https://developer-api.nest.com"
        nest = Nest_sse(nest_token, nest_api_url, "STATUS", logger)
        nest.start()
    except Exception:
        logger.error(whoami() + "cannot start nest, exiting ...")
        ns_outqueue.put("NOOK")
        sys.exit()

    ns_outqueue.put("OK")

    while not TERMINATED:
        time.sleep(0.02)
        try:
            cmd = ns_inqueue.get_nowait()
            if cmd == "stop":
                break
            elif cmd == "get_status":
                nest_status = nest.fetch()
                ns_outqueue.put(nest_status)
        except (queue.Empty, EOFError):
            continue
        except Exception:
            continue

    clear_all_queues([ns_inqueue, ns_outqueue])
    logger.info(whoami() + "... exited!")
