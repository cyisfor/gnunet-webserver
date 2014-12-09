import gnunet
import myserver

import note
note.monitor(__name__)

from coro import tracecoroutine

from tornado import gen, ioloop, iostream

iostream.bytes_type = object # duck typing, you morons!

import os
import operator

def add_future(future,what):
    ioloop.IOLoop.instance().add_future(future,(lambda future: what(*future.result())))
    return future

class Handler(myserver.ResponseHandler):
    code = 200
    message = "Otay"
    def get(self):
        if self.path == '/':
            return self.redirect(self.default)
        else:
            type,rest = self.path[1:].split('/',1)
            if type == 'sks':
                return self.cleanSKS()
            elif type == 'chk':
                return self.getCHK()
            else:
                raise RuntimeError('derp '+type)
    @tracecoroutine
    def redirect(self,location):
        yield self.send_status('302','boink')
        yield self.send_header('Location',location)
        yield self.end_headers()
    @gen.coroutine
    def cleanSKS(self):
        results = yield gnunet.search('gnunet://fs'+self.path)
        results.sort(key=lambda result: result[-1]['publication date'])
        indexfiles = {}
        yield gnunet.indexed(lambda tinychk,name: operator.setitem(indexfiles,tinychk.decode(),name))
        good = results[-1]
        results = results[:-1]
        print(indexfiles.keys())
        for chk,*rest in results:
            tinychk = chk[0x10:0x10+8].upper()
            name = indexfiles.get(tinychk)
            if name:
                print('unindex',name)
                yield gnunet.unindex(name)
        chk, name, result = good
        # could yield, but this is cheaper :p
        yield add_future(gnunet.download(chk),self.sendfile)

    def getCHK(self):
        chk = 'gnunet://fs' + self.path
        return add_future(gnunet.download(chk),self.sendfile)
    @tracecoroutine
    def sendfile(self,temp,type,length):
        note('sending')
        temp.seek(0,0)
        yield self.send_header('Content-Type',type)
        yield self.set_length(length)
        yield self.end_headers()
        buf = bytearray(0x1000)
        total = 0
        while True:
            amt = temp.readinto(buf)
            if amt <= 0: break
            total += amt
            yield self.write(memoryview(buf)[:amt])

Handler.default = os.environ['root']

myserver.Server(Handler).listen(8444)
ioloop.IOLoop.instance().start()
