from note import note
import coro

from tornado import httputil, gen, concurrent, iostream, util
from tornado.concurrent import is_future
from tornado.ioloop import TimeoutError
from tornado.escape import utf8
from tornado.httputil import HTTPHeaders
from tornado.tcpserver import TCPServer
from tornado.http1connection import HTTP1Connection, HTTP1ConnectionParameters

import json

from datetime import datetime
import calendar
import email
import time,sys,os

# Handler must handle 1 connection, which may manage many requests
# since writes are async, pipelining should work intuitively
# however, one write should finish before the next read is handled
# should receive reads all at once, but cache them and dispatch writes one
# at a time.
# otherwise, write the reply for request #2 then finish the write for request #1 oh no!
# if we tagged every write so the browser could tell which request it was meant for then we're just
# writing a second TCP stack, so multiple connections will work better for that. single connections
# only efficient when writes SHOULD be sequential.

derp = None
def derpid(wut):
    global derp
    if derp is None:
        derp = wut
    return 'id('+str(id(wut) - id(derp))+')'

def denumber(n):
    if isinstance(n,bytes): return n # avoid str(b) aka "b'0'"
    elif isinstance(n,str): return utf8(n)
    return utf8(str(n))

def decodeHeader(name,value):
    if isinstance(value,datetime):
        return utf8(email.utils.formatdate(calendar.timegm(value.utctimetuple())))
    elif isinstance(value,(bytes,memoryview,bytearray)):
        return value
    elif isinstance(value,str):
        return utf8(value)
    else:
        return utf8(str(value))

def send_header(stream, name, normalized_value):
    return stream.write(utf8(name)+ b': ' + utf8(normalized_value) + b'\r\n')

success = concurrent.Future()
success.set_result(None)

here = os.path.dirname(__file__)

class Redirect(coro.Exit):
    def __init__(self,handler,location,code,message):
        if handler.status_sent:
            raise RuntimeError("Can't redirect, you already started the response",code,message,location)
        self.code = str(code)
        self.message = message
        self.location = location
    def __str__(self):
        return '<Redirect '+self.code+' '+self.location+'>'

class ResponseHandler(object):
    timeout = 10
    chunked = False
    length = None
    finished_headers = False
    length_sent = False
    code = message = path = None
    def __init__(self, conn, stream, start_line):
        self.conn = conn
        self.stream = stream
        self.start_time = time.time()
        self.method, self.path, self.version = start_line
        self.version = self.version.rstrip()
        if not self.conn.old_client and self.version == 'HTTP/1.0':
            self.conn.old_client = True
            self.conn.old_client = True
        else:
            assert self.version == 'HTTP/1.1'
        self.headers = HTTPHeaders()
        self.headers.add("Server", "MYOB/1.0")
        self.pending = [] # delay body writes until headers sent
    def date_time_string(self,timestamp=None):
        """Return the current date and time formatted for a message header."""
        if timestamp is None:
            timestamp = time.time()
        if isinstance(timestamp,(int,float)):
            year, month, day, hh, mm, ss, wd, y, z = time.gmtime(timestamp)
        else:
            year, month, day, hh, mm, ss, wd, y, z = timestamp
        s = "%s, %02d %3s %4d %02d:%02d:%02d GMT" % (
                self.weekdayname[wd],
                day, self.monthname[month], year,
                hh, mm, ss)
        return s
    weekdayname = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

    monthname = [None,
                 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    
    def set_chunked(self):
        assert False, "uuu"
        assert self.length is None, "You can't both be chunked and have a length!"
        self.headers["Transport-Encoding"] = "chunked"
        self.chunked = True
        return self.actually_send_header("Transport-Encoding")
    def set_length(self,length):
        if self.conn.old_client: return # connection terminates at end of data anyway
        assert self.chunked is not True, "You can't specify a length when chunking"
        assert self.code not in {301,302,303,304,204},"No length for these codes"
        self.headers['Content-Length'] = denumber(length)
        self.length = length
        note('set the length te',length)
        return self.actually_send_header('Content-Length')
    def check_header(self,name,value):
        if not self.chunked and name == 'Transport-Encoding' and 'chunked' in self.headers[name]:
            assert False, 'wonk'
            self.chunked = True
        elif name == 'Content-Length':
            if self.conn.old_client: return True # connection terminates at end of data anyway
            if not self.length:
                assert self.code not in {204},"No length for these codes"
                self.length = value
    status_sent = False
    def send_status(self,code,message):
        print('status',code,message)
        self.code = code
        self.message = message
        self.status_sent = True
        return self.stream.write(b'HTTP/1.1 '+
                utf8(denumber(code))+
                b' '+utf8(message)+b'\r\n')
    def send_header(self,name,value=None):
        if value is not None:
            self.headers.add(name,decodeHeader(name,value))
        if self.check_header(name,value): 
            del self.headers[name]
        else:
            return self.actually_send_header(name)
    needDate = True
    @gen.coroutine
    def actually_send_header(self,name):
        if self.status_sent is not True:
            if self.code:
                yield self.send_status(self.code,self.message)
            else:
                print("need to send status first!")
                raise RuntimeError('please send status')
        yield send_header(self.stream, name, self.headers[name])
        if name == 'Date':
            self.needDate = False
        del self.headers[name]
    @gen.coroutine
    def end_headers(self):
        if self.finished_headers:
            raise RuntimeError('finished headers already!')
        if not self.conn.old_client:
            self.headers.add("Connection","keep-alive")
        if self.needDate:
            yield self.send_header('Date',datetime.now())
        for name,normalized_value in self.headers.get_all():
            self.check_header(name,normalized_value)
            yield send_header(self.stream, name, normalized_value)
        if not self.chunked and self.length is None:
            if self.code in {304,204}: #...?
                assert not self.pending,"No data for these codes allowed (or length header)"
            else:
                if not self.conn.old_client:
                    length = 0
                    for chunk in self.pending:
                        # no reason to chunk, since we got all the body already
                        length += len(chunk)
                    self.headers.add("Content-Length",denumber(length))
                    yield self.actually_send_header("Content-Length")
                    self.length = length
        yield self.stream.write(b'\r\n')
        self.finished_headers = True
        yield self.flush_pending()
    @gen.coroutine
    def flush_pending(self):
        pending = self.pending
        self.pending = None
        for chunk in pending:
            yield self.write(chunk)
    written = 0
    def write(self,chunk):
        if self.pending is not None:
            self.pending.append(chunk)
            return success
        
        if self.chunked:
            chunk = self.conn._format_chunk(chunk)
        elif self.length:
            if isinstance(chunk,str):
                chunk = utf8(chunk)
            self.length -= len(chunk)
        elif self.conn.old_client:
            if isinstance(chunk,str):
                chunk = utf8(chunk)
        elif self.length == 0:
            raise RuntimeError("Either tried to send 2 chunks while setting a length, or body was supposed to be empty.")
        else:
            raise RuntimeError("Can't add to the body and automatically calculate content length. Either set chunked, or set the length, or write the whole body before ending headers.")
        self.written += len(chunk)
        return self.stream.write(chunk)
    @gen.coroutine
    def respond(self):
        try:
            response = yield self.do()
            note('got response',derpid(self))
            if not self.finished_headers:
                yield self.end_headers()
        except Redirect as e:
            yield self.send_status(e.code,e.message)
            yield self.send_header('Location',e.location)
            yield self.end_headers()
        finally:
            self.recordAccess()
    def redirect(self,location,code=302,message='boink'):
        raise Redirect(self,location,code,message)
    ip = None
    def recordAccess(self):
        print(json.dumps((self.ip or self.conn.address[0],self.method,self.code,self.path,self.written,time.time())))
    def received_headers(self): pass
    def received_header(self,name,value):
        "received a header just now, can setup, or raise an error if this is not a good header"
        if name == 'Content-Length':
            note('setting length')
            self.length = int(value)
        elif name == 'Transport-Encoding':
            if 'chunked' in value:
                assert False, 'uhhh'
                self.chunked = True
    def OK(self):
        "Check headers/IP if this request's body is OK to push."
        return True
    def do(self):
        "return a Future for when writing the response is finished."
        "override this to wrap all requests in context"
        return getattr(self, self.method.lower())()
    def abort(self,stage):
        "called when a request was in the process of being received, or waiting to start writing back and the connection dies."

class AsyncCancellable(concurrent.Future):
    pending = None
    def __init__(self,ioloop,generator):
        self.gen = generator
        self.ioloop = ioloop
        self.pending = ioloop.add_callback(self.nextOne)
    def cancel(self):
        try:
            self.gen.throw(TimeoutError)
        except StopIterationError: pass
    def nextOne(self,ignored=None):
        if self.cancelled: return
        try:
            future = next(self.gen)
        except StopIterationError:
            self.set_result(None)
        except Return as e:
            self.set_result(e.value)
        else:
            if is_future(future):
                self.pending = self.ioloop.add_future(future,self.nextOne)
            else:
                note('yielded strange thing',future)
                self.pending = self.ioloop.call_later(0.1,self.nextOne)

def asynchronous(ioloop=None):
    if ioloop is None:
        ioloop = IOLoop.current()
    def decorator(f):
        @wraps(f)
        def wrapper(*a,**kw):
            gen = f(*a,**kw)
            AsyncCancellable(ioloop,gen)
    if callable(ioloop):
        # allow @asynchronous w/out parentheses
        decorator = decorator(ioloop)
        ioloop= IOLoop.current()
    return decorator
''' example:

@asynchronous
def f(self):
    yield self.write("foo")
    yield self.write("bar")
    raise Return(42)
'''

class BodyRequest(ResponseHandler):
    def __init__(self,stream,start_line,headers):
        super().__init__(stream,start_line,headers)
        self.chunks = []
    def data_received(self,chunk):
        self.chunks.append(chunk)
    def respond(self):
        self.body = ''.join(self.chunks)
        del self.chunks
        return super().respond()

def maybeTimeout(stream,timeout,future):
    if timeout:
        return gen.with_timeout(
            stream.io_loop.time() + timeout,
            future,
            io_loop=stream.io_loop)
    return future

class ConnectionHandler(HTTP1Connection):
    protocol = "http"
    writing = False
    request = None
    header_timeout = 10
    body_timeout = None
    def __init__(self, requestFactory, connection, address):
        super().__init__(connection,False)
        self.requestFactory = requestFactory
        self.address = address
        self.pendingResponses = []
    max_header_length = 0x1000
    max_start_header_length = max_header_length * 10
    max_headers = 0x20
    readed = 0
    @gen.coroutine
    def read_headers(self):
        parser = HTTPHeaders()
        lastkey = None
        count = 0
        while True:
            line = yield self.stream.read_until(b'\r\n',max_bytes=self.max_header_length)
            if len(line) == 2:
                break
            self.readed += len(line)
            count += 1
            line = line.decode('utf-8')
            if self.max_headers and count > self.max_headers:
                raise iostream.UnsatisfiableReadError("Too many headers "+line+' '+json.dumps(parser))
            parser.parse_line(line)
            if lastkey is None:
                lastkey = parser._last_key
            elif lastkey != parser._last_key:
                self.request.received_header(lastkey,parser[lastkey])
                lastkey = parser._last_key
        self.request.request_headers = parser
        self.request.received_headers()
        note('received all headers')
        raise gen.Return(parser)
    @gen.coroutine
    def read_body(self,headers):
        if headers.get("Expect") == '100-continue':
            if self.request.OK():
                # can't pipeline 100 continues they must be written BEFORE the next request arrives
                # since the client can't send a new request until it learns whether this request's
                # body is OK to send.
                yield self.stream.write(b"HTTP/1.1 100 (Continue)\r\n\r\n")
            else:
                # have to abort the WHOLE connection if the request wasn't OK
                raise HTTPError(500,"Bad request")
        if self.request.length is None:
            note('read chunked body')
            if self.request.chunked:
                # now it's whether the response is chunked, not the request body
                del self.request.chunked
                yield self._read_chunked_body(self.request)
        else:
            length = self.request.length
            note('read body',length)
            # now it's the length of the response, not the length of the request
            del self.request.length
            yield self._read_fixed_body(length,self.request)
    old_client = False # this will get set with the first message's headers
    @gen.coroutine
    def read_message(self):
        if self.request is not None:
            note('err',derpid(self),self.request)
            raise RuntimeError

        try:
            start_line = yield self.stream.read_until(b'\r\n',max_bytes=self.max_start_header_length)
        except iostream.StreamClosedError:
            note('done with',self.address,derpid(self))
            raise
        except iostream.UnsatisfiableReadError:
            print("garbage from address",self.address)
            self.stream.close()
            raise iostream.StreamClosedError
        start_line = httputil.parse_request_start_line(start_line.decode('utf-8'))
        note('setting request',derpid(self),start_line)
        self.request = self.requestFactory(self, self.stream, start_line)
        headers = yield maybeTimeout(self.stream, self.header_timeout, self.read_headers())
        
        yield maybeTimeout(self.stream, self.body_timeout, self.read_body(headers))
        
        # Now we've read the request, so start writing it, asynchronously
        yield self.startWriting()
        note('del self.request (started writing)',derpid(self))
        del self.request
        assert self.request is None, "boop"
        if self.old_client:
            self.stream.close()
        else:
            self.read_next_message('next')
    def read_next_message(self,kind):
        assert self.request is None,kind
        note('reading next message',kind,derpid(self))
        # since this is a generator, lazy generation means this won't recurse infinitely
        # but will trampoline.
        self.reader = self.read_message()
        self.stream.io_loop.add_future(self.reader, self.done_reading)
    def done_reading(self,future):
        try:
            future.result()
        except iostream.StreamClosedError:
            self.on_connection_close('reading')
    max_pending = 100
    @gen.coroutine
    def startWriting(self):
        if self.writing:
            # we'll start after the current response is done writing.
            # ONLY yield if too many requests are pending
            while len(self.pendingResponses) > self.max_pending:
                # would just yield self.writing... but maybe this would be resumed
                # before doneWriting is called... that would make the connection hang
                yield self.done_writing
            if self.writing:
                self.pendingResponses.append(self.request)
                return
        if self.request is None:
            yield success
            return
        self.done_writing = gen.Future()
        self.writing = self.request.respond()
        assert is_future(self.writing)
        self.stream.io_loop.add_future(self.writing,self.doneWriting)
        if self.request.timeout:
            self.writing.timeout = self.stream.io_loop.call_later(self.request.timeout, self.maybeTimeout, self.writing)
            note('setting timeout',derpid(self),derpid(self.writing.timeout))
        else:
            self.writing.timeout = None
    def maybeTimeout(self, oldWriting):
        del self.writing
        if oldWriting.running():
            note('warning, response writer timed out',derpid(oldWriting.timeout))
            oldWriting.set_exception(TimeoutError)
    def doneWriting(self,future):
        note('done writing',derpid(self))
        if self.writing:
            if self.writing.timeout:
                note('cancelling timeout because done',derpid(self.writing.timeout))
                self.stream.io_loop.remove_timeout(self.writing.timeout)
            del self.writing # fallback to class default
        try:
            future.result() # raise exception if one has been set
        except iostream.StreamClosedError:
            self.on_connection_close('writing')
            return
        if len(self.pendingResponses) > 0:
            note('popping request',len(self.pendingResponses))
            self.request = self.pendingResponses.pop(0)
            # resume collecting requests
            self.done_writing.set_result(True)
        else:
            # resume even if nothing pending, but could this ever happen?
            # max_pending = 0?
            self.done_writing.set_result(42)
        return self.startWriting()
    def on_connection_close(self,how):
        sys.stderr.write(json.dumps(('connection lost',self.address,how))+'\n')
        sys.stderr.flush()
        if how == 'reading':
            if self.reader and self.reader.running():
                future = self.reader
                del self.reader
                future.set_exception(iostream.StreamClosedError)
            if self.request:
                self.request.abort('reading')
                note('del self.request (connection lost)',derpid(self))
                del self.request
        elif how == 'writing':
            if self.writing:
                if self.writing.timeout:
                    note('cancelling timeout because connection lost',derpid(self.writing.timeout))
                    self.stream.io_loop.remove_timeout(self.writing.timeout)
                if self.writing.running():
                    self.writing.set_exception(iostream.StreamClosedError)
                del self.writing
            for writer in self.pendingResponses:
                writer.abort('writing')
            self.pendingResponses = []

class Server(TCPServer, httputil.HTTPServerConnectionDelegate):
    protocol = "http" # https is for frontends!
    def __init__(self,requestFactory):
        TCPServer.__init__(self) # meh!
        self.requestFactory = requestFactory
        self.connections = set()
    derp = None
    def add_sockets(self,sockets):
        super().add_sockets(sockets)
        if self.derp is None:
            def notify():
                print('Ready to serve.',[s.getsockname() for s in sockets])
            self.derp = self.io_loop.call_later(0.1,notify)
    @gen.coroutine
    def close_all_connections(self):
        while self.connections:
            conn = next(iter(self.connections))
            yield conn.close()
    def handle_stream(self, stream, address):
        conn = ConnectionHandler(self.requestFactory, stream, address)
        self.connections.add(conn)
        assert conn.request is None,"derp"
        return conn.read_next_message('start')
    def on_close(self, server):
        self.connections.remove(server)

