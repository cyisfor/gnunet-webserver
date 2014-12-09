import note
note.monitor(__name__)

from tornado import gen
from functools import wraps
import traceback
import sys
def tracecoroutine(f):
    @wraps(f)
    def wrapper(*a,**kw):
        g = f(*a,**kw)
        thing = None
        try:
            while True:
                thing = g.send(thing)
                try: thing = yield thing
                except Exception as e:
                    note('passing down',type(e))
                    thing = g.throw(e)
                    note('passed down')
        except StopIteration: pass
        except gen.Return as e: 
            note('yay returning',e)
            raise
        except:
            note.alarm('error in ',f)
            traceback.print_exc()
            return
    return gen.coroutine(wrapper)
