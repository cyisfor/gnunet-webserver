colors = ['black','red','green','yellow','blue','magenta','cyan','white']   
colorlookup = dict(zip(colors,range(len(colors))))

CSI = b'\x1b['

def color(what,fg=True,bold=False):
    base = 30
    if not fg:
        base = 40
    base += colorlookup[what]
    result = CSI+str(base).encode()
    if bold:
        result += b';1'
    return result + b'm'

reset = CSI + b'0m'
