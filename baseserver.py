import gnunet
import myserver

import note
note.monitor(__name__)

from coro import tracecoroutine

from tornado import gen, ioloop, iostream
from tornado.gen import Return
iostream.bytes_type = object # duck typing, you morons!

from urllib.parse import unquote

from functools import partial
import calendar
import os
import operator
import time

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
            self.kind,self.rest = self.path[1:].split('/',1)
            return getattr(self,'handle'+kind.upper())()
    @tracecoroutine
    def redirect(self,location):
        yield self.send_status('302','boink')
        yield self.send_header('Location',location)
        yield self.end_headers()
    @gen.coroutine
    def handleSKS(self):
        self.ident,tail = self.rest.split('/',1)
        if not '/' in tail:
            # /sks/ident/keyword/filename
            # with just keyword, these are always directories
            # URLs for directories must end in / on the CLIENT side
            # ...for relative links to work right.
            yield self.redirect(self.path+'/')
            return
        self.keyword,self.filename = tail.split('/',1)
        if '/' in self.filename:
            # if a directory entry is itself a directory, this saves the sub-directory sub-part for it
            # otherwise self.subsequent is ignored
            self.filename,self.subsequent = self.filename.split('/',1)
        # get the CHK for this SKS (the most recent one ofc)
        results = yield gnunet.search('gnunet://fs/sks/'+self.ident+'/'+self.keyword)
        results.sort(key=lambda result: result[-1]['publication date'])
        self.cleanSKS(results[:-1])
        chk, name, info = results[-1]
        result = yield self.startDownload(chk,name,info)
        raise Return(result)
    def cleanSKS(self,oldinfos):
        indexfiles = {}
        yield gnunet.indexed(lambda tinychk,name: operator.setitem(indexfiles,tinychk.decode(),name))
        good = results[-1]
        results = results[:-1]
        note(indexfiles.keys())
        for chk,*rest in results:
            tinychk = chk[0x10:0x10+8].upper()
            name = indexfiles.get(tinychk)
            if name:
                note('unindex',name)
                yield gnunet.unindex(name)
    queryShortcuts = (
            ('p', 'publication date'),
            ('m', 'mimetype')
            )
    def handleCHK(self):
        try: path, query = self.rest.split('?',1)
        except ValueError:
            path = self.rest
            info = {}
        else:
            info = dict((n,gnunet.decode(n,v)) for n,v in ((unquote(n),unquote(v)) for n,v in (e.split('=',1) for e in query.split('&'))))
            for n,long in self.queryShortcuts:
                if n in info:
                    info[long] = info[n]
                    del info[n]
        try: 
            self.ident, name = path.split('/',1)
        except ValueError:
            name = None
        chk = 'gnunet://fs/chk/' + self.ident
        info.setdefault('publication date',time.gmtime())
        return self.startDownload(chk,name,info)
    progress = None
    def startDownload(self,chk,name,info):
        "override this to do stuff if you don't care what the file type or publication date is"
        type = info.get('mimetype')
        modification = calendar.timegm(info['publication date'])
        return self.download(chk,name,info,type,modification)
    @tracecoroutine
    def download(self,chk,name,info,type,modification,progress=None):
        "augment this to setup stuff according to the file type, HTML filters etc"
        # and by augment I mean override it, then call it w/ progress.

        # in here you handle the type and modification 
        # instead of re-parsing them out of the info
        # is this too much granularity?

        temp,type,length = yield gnunet.download(chk,progress,type,modification)
        result = yield self.sendfile(chk,name,info,temp,type,length)
        raise Return(result)
    @tracecoroutine
    def sendfile(self,chk,name,info,temp,type,length):
        "override this to do things with the contents of the file, transform HTML, check for spam, list directories, etc"
        # note: the type argument is more reliable than info['mimetype'] 
        # as it's guessed from the file contents even if info has no mimetype record
        note('sending')
        temp.seek(0,0)
        yield self.send_header('Content-Type',type)
        modified = info.get('publication date')
        if modified:
            yield self.send_header('Last-Modified',self.date_time_string(modified))
        yield self.set_length(length)
        yield self.end_headers()
        buf = bytearray(0x1000)
        total = 0
        # Can't use X-SendFile because it offers no notification of when the file has
        # been started sending (and can be deleted) or has been sent.
        while True:
            amt = temp.readinto(buf)
            if amt <= 0: break
            total += amt
            yield self.write(memoryview(buf)[:amt])
        del temp
        # don't return temp, so that it can be garbage collected
        raise Return((info,type,length))
