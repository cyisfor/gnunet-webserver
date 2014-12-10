urlre = re.compile(r'url\s*\(([^)]*)\)')

def sanitize(contents):
    return urlre.sub('',contents)
