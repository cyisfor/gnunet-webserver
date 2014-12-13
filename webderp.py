import baseserver
import myserver
import gnunet

import sanehtml,sanestyle

import note

from coro import tracecoroutine

from tornado import ioloop
from tornado.gen import Return
from bs4 import BeautifulSoup

import calendar
from urllib.parse import quote

import os
oj = os.path.join

directoryTemplate = '''<!DOCTYPE html><html>
<head>
</head>
<body>
<p>Listing for <span class="chk"/></p>
<div id="nav"/>
<dl id="info"/>
<table id="entries">
<th>CHK</th><th>Filename</th><th>Info</th>
</table>
</body>
</html>
'''

statusTemplate = '''<!DOCTYPE html><html>
<head>
</head>
<body>
<p>Status</p>
<div id="nav"/>
<dl id="info"/>
<table id="searches">
<th>Keywords</th><th>Results</th><th>Status</th><th>Actions</th>
</table>
<table id="downloads">
<th>CHK</th><th>SKS</th><th>Progress</th><th>Actions</th>
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

goofs = gnunet.goofs
goof = gnunet.goof

def buildLink(chk,name,info):
    href = chk
    if name:
        href += '/' + name
    if info:
        href += '?' + '&'.join(quote(n)+'='+quote(gnunet.encode(n,v)) for n,v in info.items())
    return href

def interpretLink(uri, info=None):
    if uri.startswith(goofs):
        uri = uri[goof:]
    if info:
        uri += '?' + '&'.join(quote(n)+'='+quote(gnunet.encode(n,v)) for n,v in info.items())
    return uri

@tracecoroutine
def processDirectory(top, upper, here, info, path):
    doc = BeautifulSoup(directoryTemplate)
    nav = None
    head = doc.find('head')
    def addLink(rel,href,name=None):
        link = doc.new_tag('link')
        link['rel'] = rel
        link['href'] = href
        head.append(link)
        link = doc.new_tag('a')
        link['href'] = href
        link.append(name or rel.title())
        if nav:
            nav.append(' ')
        else:
            nav = doc.find(id='navigation')
        nav.append(link)
    if top:
        addLink(interpretLink(top)+'/','first','Top')
        addLink(interpretLink(here)+'/','next','Root here')
    if upper:
        addLink(interpretLink(upper)+'/','up','Up')
    presentInfo(doc,doc.find(id='info'),info)
    entries = doc.find(id='entries')
    def addEntry(chk,name,info):
        note.yellow('entry',name)
        entry = doc.new_tag('tr')
        td = doc.new_tag('td')
        td.append(chk[goof+5:goof+5+8])
        entry.append(td)
        td = doc.new_tag('td')
        a = doc.new_tag('a')
        a['href'] = name # relative links woo
        if info['mimetype'] == 'application/gnunet-directory':
            a['href'] += '/'
        a['id'] = chk # don't go to this, since we want to remember our parent directory
        a.append(name)
        td.append(a)
        entry.append(td)
        td = doc.new_tag('td')
        dl = doc.new_tag('dl')
        presentInfo(doc,dl,info)
        td.append(dl)
        entry.append(td)
        entries.append(entry)
    note.yellow('adding entries')
    yield gnunet.directory(path,addEntry)
    raise Return(doc)

class Handler(baseserver.Handler):
    def __init__(self,*a,**kw):
        note.magenta("Creating a Handler!",id(self))
        super().__init__(*a,**kw)
    def handle(self):
        return self.redirect(self.default)
    def handleSTATUS(self):
        self.isDir = '/' in self.rest
        if not self.isDir:
            return self.redirect(self.path + '/')
        if self.ident:
            try: self.kind, self.action = self.filepath.split('/',1)
            except ValueError:
                self.kind = self.filepath
                self.action = None
            if not self.action:
                return self.showStatus()
    def showStatus(self):
        doc = BeautifulSoup(statusTemplate)
        table = doc.find(id='searches')
        # <th>Keywords</th><th>Results</th><th>Status</th><th>Actions</th>
        for search in gnunet.searches:
            info = '/status/'+search.kw
            if search.sks:
                check = '/sks/'
                fancyname = search.keyword[goof+5:goof+5+8]
            else:
                check = '/ksk/'
                check += quote(gnunet.encode(search.keyword))
                fancyname = search.keyword
            info = {}
            if search.supplemental:
                info['keywords'] = ','.join(search.supplemental)
                fancyname = fancyname + ' ' + ', '.join(search.supplemental)
            if info:
                query = '?' + '&'.join(quote(n)+'='+quote(gnunet.encode(v)) for n,v in info)
            else:
                query = ''
            
            row = doc.new_tag('tr')
            table.append(row)
            def cell(e):
                td = doc.new_tag('td')
                tr.append(td)
                td.append(e)
            a = doc.new_tag('a')
            a['href'] = check + query
            a.append(fancyname)
            cell(a)
            subtab = doc.new_tag('table')
            def subrow(*a,head=False):
                tr = doc.new_tag('tr')
                for i in a:
                    if i:
                        td = doc.new_tag('th' if head else 'td')
                        td.append(i)
                        tr.append(td)
                subtab.append(tr)
            subrow('CHK','Name','Meta',head=True)
            for result in results:
                if result[2]:
                    dl = doc.new_tag('dl')
                    presentInfo(doc,dl,result[2])
                else:
                    dl = None
                subrow(result[0],result[1],dl)
            cell(subtab)
            if result.request.running():
                num = str(len(result.request._callbacks))
                if result.done.running():
                    cell('Requested ('+num+')')
                else:
                    cell('Requested ('+num+') (done)')
            elif result.done.running():
                cell('Searching')
            else:
                cell('Idle')
            p = None
            def action(ident,name):
                nonlocal p
                a = doc.new_tag('a')
                a['href'] = info + ident
                a.append(name)
                if p:
                    p.append(' ')
                else:
                    p = doc.new_tag('p')
                p.append(a)
            action('','Info')
            action('interrupt','Stop Requests')
            action('cancel','Stop Search')
            action('forget','Forget Search')
            cell(p)
            # XXX: do the rest l8r




    @tracecoroutine
    def sendblob(self,blob,type):
        yield self.send_header('Content-Type',type)
        yield self.set_length(len(blob))
        yield self.end_headers()
        raise Return(self.write(blob))
    top = None
    upper = None
    @tracecoroutine
    def sendfile(self,chk,name,info,temp,type,length):
        temp.seek(0,0)
        note.yellow('type',type,bold=True)
        if self.isDir:
            if len(self.filepath) > 0:
                note.yellow('sub-entry here',self.filepath,bold=True)
                # now find the chk/info of the filename in this directory
                gotit = False
                def oneResult(chk,name,info):
                    note.blue('name',repr(name),chk,info,bold=True)
                    nonlocal gotit
                    if name == self.filepath:
                        note.red('gotit!')
                        gotit = (chk,name,info)
                        return True
                note.cyan('wanted',repr(self.filepath),bold=True)
                yield gnunet.directory(temp.name,oneResult)
                if gotit:
                    chk,name,info = gotit
                    if info['mimetype'] == 'application/gnunet-directory':
                        if self.top is None:
                            self.top = self.uri
                        if self.upper is None:
                            self.upper = self.uri
                        if self.filepath:
                            self.keyword,self.filepath = self.filepath.split('/',1)
                        else:
                            self.keyword = self.filepath
                            self.filepath = None
                    else:
                        assert not '/' in self.filepath, "No subdirs below a normal file!"
                        self.isDir = False
                    # going down....
                    raise Return(self.startDownload(chk,name,info))
                else:
                    # a filename not in this directory.
                    self.write("Oh a wise guy, eh? "+repr(self.filepath))
                return
            # the directory itself, no sub-entry filename
            doc = yield processDirectory(self.top,self.upper,self.uri,info,temp.name)
            del temp
            raise Return(self.sendblob(str(doc).encode('utf-8'),'text/html'))
        elif type == 'text/html':
            doc = BeautifulSoup(temp)
            sanehtml.sanitize(doc)
            note.yellow('Sanitized')
            raise Return(self.sendblob(str(doc).encode('utf-8'),'text/html'))
        # XXX: this is wrong, and unsafe.
        elif type == 'text/css' or type == 'text/plain' and name.endswith('.css'):
            assert length < 0x10000
            contents = sanestyle.sanitize(temp.read(length).decode('utf-8'))
            raise Return(self.sendblob(contents.encode('utf-8'),'text/css'))
        elif type == 'application/x-shockwave-flash' and self.noflash:            
            raise Return(self.write("ha"))
        else:
            raise Return(super().sendfile(chk,name,info,temp,type,length))

Handler.default = os.environ.get('root')
if Handler.default:
    if Handler.default.startswith(goofs):
        Handler.default = Handler.default[goof:]
else:
    Handler.default = '/status/'

myserver.Server(Handler).listen(8444)
ioloop.IOLoop.instance().start()
