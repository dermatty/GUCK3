import threading
from threading import get_ident
import time
import cv2

# all this is copy-paste from :
#    https://github.com/miguelgrinberg/flask-video-streaming


class CameraEvent(object):
    def __init__(self):
        self.events = {}

    def wait(self):
        ident = get_ident()
        if ident not in self.events:
            self.events[ident] = [threading.Event(), time.time()]
        return self.events[ident][0].wait()

    def set(self):
        now = time.time()
        remove = None
        for ident, event in self.events.items():
            if not event[0].isSet():
                event[0].set()
                event[1] = now
            else:
                if now - event[1] > 5:
                    remove = ident
        if remove:
            del self.events[remove]

    def clear(self):
        self.events[get_ident()][0].clear()


class BaseCamera(object):
    thread = None  # background thread that reads frames from camera
    frame = None  # current frame is stored here by background thread
    last_access = 0  # time of last client access to the camera
    event = CameraEvent()

    def __init__(self):
        """Start the background camera thread if it isn't running yet."""
        if BaseCamera.thread is None:
            BaseCamera.last_access = time.time()
            BaseCamera.thread = threading.Thread(target=self._thread)
            BaseCamera.thread.start()
            while self.get_frame() is None:
                time.sleep(0.01)

    def get_frame(self):
        BaseCamera.last_access = time.time()
        BaseCamera.event.wait()
        BaseCamera.event.clear()
        return BaseCamera.frame

    @staticmethod
    def frames():
        raise RuntimeError('Must be implemented by subclasses.')

    @classmethod
    def _thread(cls):
        frames_iterator = cls.frames()
        for frame in frames_iterator:
            BaseCamera.frame = frame
            BaseCamera.event.set()  # send signal to clients
            time.sleep(0)
            if time.time() - BaseCamera.last_access > 10:
                frames_iterator.close()
                break
        BaseCamera.thread = None


class Camera(BaseCamera):
    def __init__(self, camnr, db):
        cameralist = [(cd["name"], cd["stream_url"]) for cd in db.get_cameras()]
        Camera.name, Camera.surl = cameralist[camnr]
        super(Camera, self).__init__()

    @staticmethod
    def frames():
        try:
            camera = cv2.VideoCapture(Camera.surl)
            while True:
                _, img = camera.read()
                yield cv2.imencode('.jpg', img)[1].tobytes()
        except Exception:
            pass


def gen(camera):
    while True:
        try:
            frame = camera.get_frame()
            if frame:
                yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
        except Exception:
            pass
