# meh, slots are slower, not worth size cut
def makeobj(entries):
    class Object:
        def __init__(self):
            for n,v in entries.items():
                setattr(self,n,v)
    return Object
