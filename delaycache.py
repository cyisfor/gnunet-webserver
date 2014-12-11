from tornado import ioloop

class DelayCache(dict):
    def __init__(self,delay):
        self.delay = delay
        super().__init__()
    def reset_timeout(self):
        timeout = self.handles.get(key)
        if timeout:
            ioloop.IOLoop.instance().remove_timeout(timeout)
        self.handles[key] = ioloop.IOLoop.instance().call_later(self.delay, operator.delitem, key)
    def __setitem__(self,key,value):
        super().__setitem__(key,value)
        self.reset_timeout()
    def __getitem__(self,key):
        self.reset_timeout(key)
        return super().__getitem__(key)
