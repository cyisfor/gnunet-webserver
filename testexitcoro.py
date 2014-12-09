from tornado import ioloop, gen
from tornado.concurrent import Future

class Context:
    def __enter__(self,*a):
        print('context enter',a)
    def __exit__(self,*a):
        print('context exit',a)

context = Context()

def later(t):
    done = Future()
    ioloop.IOLoop.instance().call_later(t/10.0,lambda: done.set_result(True))
    return done

@gen.coroutine
def dostuff():
    with context:
        print('in with')
        yield later(1)
        print('yielded in with')
        yield later(1)
        print('done in with')
    print('out of with')

@gen.coroutine
def dostufftail():
    with context:
        print('in with 2')
        yield later(1)
        print('yielded in with 2')
        yield later(1)

@gen.coroutine
def run():
    yield dostuff()
    print('didstuff')
    yield dostufftail()
    print('didtail')
    ioloop.IOLoop.instance().stop()

if __name__ == '__main__':
    run()
    ioloop.IOLoop.instance().start()
