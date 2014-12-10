#!/usr/bin/env python2

from bs4 import BeautifulSoup,Comment
import sys,re,os
import urllib.parse

urlre = re.compile(r'url\s*\(([^)]*)\)')

def group1(match):
    return '"derp' + match.group(1).replace('://','') + '"'

def fixlink(link):
    if not '://' in link: return link
    if link.startswith('gnunet://fs'):
        return link[len('gnunet://fs'):]

def sanitize(doc,base=None):

    for script in doc.findAll('script'):
        script.extract();
    for comment in doc.findAll(text=lambda c: isinstance(c,Comment)):
        # these may hide macros IFDEF etc
        comment.extract()

    for link in doc.findAll('link'):
        url = link['href']
        if url:
            link.attrs['href'] = fixlink(url)
    for img in doc.findAll('img'):
        src = img.get('src')
        if src:
            img.attrs['src'] = fixlink(src)
    for style in doc.findAll('style'):
        style.string = sanestyle.sanitize(style.string)

noDisplay = re.compile('display:\s*none')

def cleanattrs(e):
    if e.name == 'a':
        isSafe = True
    else:
        isSafe = False
    d = []

    for attr,value in e.attrs.items():
        if attr.startswith('on'):
            d.append(attr)
            continue
        if isSafe: 
            if base and attr == 'href':
                e.attrs[attr] = urllib.parse.urljoin(base,value)
            continue
        if not isinstance(value,list):
            value = [value]
        for v in value:
            if '://' in v:
                if e.name == 'meta':
                    e.extract()
                    return
                d.append(attr)
            if attr == 'style': 
                if noDisplay.match(v):
                    e.extract()
                else:
                    del e.attrs['style']
                return
    for attr in d:
        del e[attr]


for e in doc.findAll():
       cleanattrs(e)

print(doc.prettify())
