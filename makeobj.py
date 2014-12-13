import six

# meh, slots are slower, not worth size cut
class ProvideInit(type):
    def __new__(cls, name, bases, namespace):
        assert(not '__init__' in namespace)
        def setattrs(self):
            for n,default in self.entries.items():
                if not hasattr(self,n):
                    setattr(self,n,default)
        namespace['__init__'] = setattrs
        # don't mess with __init__ of bases, of course
        super().__init__(name, bases, namespace)

@six.add_metaclass(ProvideInit)
class Object(): pass
