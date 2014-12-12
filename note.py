import os,io
from ansi import color,reset

white = color('white',bold=True)

def decode(o):
    if isinstance(o,Exception):
        return repr(o.value)
    return str(o)

if 'debug' in os.environ:
    import sys,time
    out = sys.stderr.buffer
    modules = set()
    here = os.path.dirname(__file__)
    always = 'always' in os.environ
    def setroot(where):
        global here
        here = os.path.dirname(where) 
    if hasattr(sys,'_getframe'):
        def getframe():
            return sys._getframe(3)
    else:
        def getframe():
            tb = sys.exc_info()[2]
            if not tb:
                try: raise Exception
                except Exception as e:
                    tb = e.__traceback__
                while tb.tb_next:
                    tb = tb.tb_next
            # here -> output -> note/alarm/warn/etc -> module
            return tb.tb_frame.f_back.f_back.f_back
    def output(color,s):
        f = getframe()
        # function above us
        module = f.f_globals['__name__'] 
        
        if not always and module not in modules: 
            return

        o = io.TextIOWrapper(io.BytesIO(),encoding='utf-8')
        def writec(c):
            o.flush()
            o.buffer.write(c)


        s = (decode(s) for s in s)
        s = ' '.join(s)
        hasret = '\n' in s
        
        o.write('== '+str(time.time())+' ')
        writec(white)
        o.write(os.path.relpath(f.f_code.co_filename,here))
        writec(reset)
        o.write(':'+str(f.f_lineno))
        if hasret:
            o.write('\n'+'-'*60+'\n')
        else:
            o.write('\n')

        writec(color)
        o.write(s)
        writec(reset)

        if hasret:
            o.write('\n'+'-'*60+'\n')
        else:
            o.write('\n')
        o.flush()
        out.write(o.buffer.getbuffer())
        out.flush()
    class NoteModule:
        def note(self,*s):
            output(color('green',bold=True),s)
        def alarm(self,*s):
            output(color('red',bold=True),s)
        def __call__(self,*s):
            output(color('green'),s)
        def __getattr__(self,n):
            return lambda *s,**kw: output(color(n,**kw),s)
        def monitor(self,module=None):
            if module:
                if hasattr(module,'__name__'):
                    module = module.__name__
            else:
                module = '__main__'
            modules.add(module)
else:
    class NoteModule:
        def __getattr__(self,n):
            return lambda *a, **kw: None
sys.modules[__name__] = NoteModule()
