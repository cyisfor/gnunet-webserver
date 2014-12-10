import baseserver
import myserver
import gnunet

from coro import tracecoroutine

from tornado import ioloop
from bs4 import BeautifulSoup

import os

directoryTemplate = '''<!DOCTYPE html><html>
<head>
</head>
<body>
<p>Listing for <span class="chk"/></p>
<dl id="info"/>
<table id="entries">
<th>CHK</th><th>Filename</th><th>Info</th>
</table>
</body>
</html>
'''

def presentInfo(doc,dl,info):
    for n,v in info.items():
        dt = doc.new_tag('dt')
        dt.append(n)
        dd = doc.new_tag('dd')
        dd.append(v)
        dl.append(dt)
        dl.append(dd)

@tracecoroutine
def processDirectory(chk,info,temp):
    doc = BeautifulSoup(directoryTemplate)
    presentInfo(doc,doc.find(id='info'),info)
    entries = doc.find(id='entries')
    def addEntry(chk,name,info):
        entry = doc.new_tag('tr')
        td = doc.new_tag('td')
        td.append(chk)
        entry.append(td)
        td = doc.new_Tag('td')
        td.append(name)
        entry.append(td)
        td = doc.new_tag('td')
        dl = doc.new_tag('dl')
        presentInfo(doc,dl,info)
        td.append(dl)
        entry.append(td)
        entries.append(entry)
    yield gnunet.directory(temp,addEntry)
    raise Return(doc)

class Handler(baseserver.Handler):
    @tracecoroutine
    def sendblob(self,blob,type):
        yield self.send_header('Content-Type',type)
        yield self.set_length(len(doc))
        yield self.end_headers()
        yield self.write(doc)
        note('wrote blob',type)
    @tracecoroutine
    def sendfile(self,info,temp,type,length):
        if type == 'application/gnunet-directory':
            doc = yield processDirectory(temp.name)
            del temp
            yield self.sendblob(str(doc).encode('utf-8'),'text/html')
        elif type == 'text/html':
            doc = BeautifulSoup(temp)
            sanehtml.sanitize(doc)
            yield self.sendblob(str(doc).encode('utf-8'),'text/html')
        elif type == 'text/css':
            assert length < 0x10000
            contents = sanecss.sanitize(temp.read(length))
            del temp
            yield self.sendblob(contents.encode('utf-8'),'text/css')
        elif type == 'application/x-shockwave-flash' and self.noflash:
            yield self.set_length(0)
        else:
            yield super().sendfile(info,temp,type,length)

Handler.default = os.environ['root']
if Handler.default.startswith('gnunet://fs'):
    Handler.default = Handler.default[len('gnunet://fs'):]

myserver.Server(Handler).listen(8444)
ioloop.IOLoop.instance().start()
