import baseserver
import myserver
import gnunet

import sanehtml,sanestyle

import note

from coro import tracecoroutine

from tornado import ioloop
from tornado.gen import Return
from bs4 import BeautifulSoup

from urllib.parse import quote

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
        dd.append(gnunet.encode(n,v))
        dl.append(dt)
        dl.append(dd)

goofs = len('gnunet://fs')

def buildLink(chk,name,info):
    if name:
        href += '/' + name
    if info:
        href += '?' + '&'.join(quote(n)+'='+quote(gnunet.encode(n,v)) for n,v in info.items())
    return href

@tracecoroutine
def processDirectory(parentchk,info,temp):
    doc = BeautifulSoup(directoryTemplate)
    presentInfo(doc,doc.find(id='info'),info)
    entries = doc.find(id='entries')
    def addEntry(chk,name,info):
        note.yellow('entry',name)
        entry = doc.new_tag('tr')
        td = doc.new_tag('td')
        a = doc.new_tag('a')
        if 'mimetype' in info:
            info['subtype'] = info['mimetype']
            info['mimetype'] = 'application/gnunet-directory'
        a['href'] = buildLink('/dir/'+parentchk[goofs+4:],name,info)
        a['title'] = chk # don't go to this, since we want to remember our parent directory
        a.append(chk[goofs+5:goofs+5+8].upper())
        td.append(a)
        entry.append(td)
        td = doc.new_tag('td')
        td.append(name)
        entry.append(td)
        td = doc.new_tag('td')
        dl = doc.new_tag('dl')
        presentInfo(doc,dl,info)
        td.append(dl)
        entry.append(td)
        entries.append(entry)
    note.yellow('adding entries')
    yield gnunet.directory(temp.name,addEntry)
    raise Return(doc)

class Handler(baseserver.Handler):
    @tracecoroutine
    def sendblob(self,blob,type):
        yield self.send_header('Content-Type',type)
        yield self.set_length(len(blob))
        yield self.end_headers()
        yield self.write(blob)
        note('wrote blob',type)
    @tracecoroutine
    def sendfile(self,chk,sub,info,temp,type,length):
        note.yellow('type',type,bold=True)
        if type == 'application/gnunet-directory':
            # XXX: if the sub-entry, is a subdirectory, switch to that for a chk?
            if sub:
                note.yellow('sub-entry here',sub,bold=True)
                # getting a directory entry here...
                gotit = False
                def oneResult(chk,name,info):
                    note.blue('name',name,bold=True)
                    nonlocal gotit
                    if name == sub:
                        self.send_status(302,'over here')
                        self.send_header('Location',buildLink(chk[goofs:],name,info))
                        gotit = True
                        return True
                yield gnunet.directory(temp.name,oneResult)
                if not gotit:
                    self.write("Oh a wise guy, eh?")
                return
            doc = yield processDirectory(chk,info,temp)
            del temp
            yield self.sendblob(str(doc).encode('utf-8'),'text/html')
        elif type == 'text/html':
            doc = BeautifulSoup(temp)
            sanehtml.sanitize(doc)
            yield self.sendblob(str(doc).encode('utf-8'),'text/html')
        elif type == 'text/css':
            assert length < 0x10000
            contents = sanestyle.sanitize(temp.read(length))
            del temp
            yield self.sendblob(contents.encode('utf-8'),'text/css')
        elif type == 'application/x-shockwave-flash' and self.noflash:
            yield self.set_length(0)
        else:
            yield super().sendfile(chk,sub,info,temp,type,length)

Handler.default = os.environ['root']
if Handler.default.startswith('gnunet://fs'):
    Handler.default = Handler.default[len('gnunet://fs'):]

myserver.Server(Handler).listen(8444)
ioloop.IOLoop.instance().start()
