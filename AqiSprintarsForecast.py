#!/usr/bin/python

from PIL import Image
import os
import requests

colors = [(int(_[:2], 16), int(_[2:4], 16), int(_[4:], 16)) for _ in ('1e3cff', '00a0ff', '00dc00', 'a0e632', 'e6dc32', 'f08228', 'fa3c3c', 'f00082')]

cities = {
    'default': (250, 250, 265, 265)
}

def fetch_pictures(count):
    for i in range(count):
        while True:
            try:
                _fetch_picture(i)
                break
            except:
                continue

    
def _fetch_picture(hr):
    '''
    hr: hours since today 00:00 UTC+9
    '''
    id = 9 + int(hr/3)
    fn = 'pm25_easia_{:02d}.png'.format(id)
    
    while True:
        if not os.path.exists('/tmp/' + fn):
            print(fn)
            with open('/tmp/' + fn, 'wb') as fo:
                fo.write(requests.get('https://sprintars.riam.kyushu-u.ac.jp/images/' + fn, timeout=10,
                ).content)
        
        try:
            buf = open('/tmp/' + fn, 'rb')
            return Image.open(buf)
        except KeyboardInterrupt:
            return 
        except:
            os.unlink('/tmp/' + fn)
        
    
def _value_average(im, rect, by='count'):
    '''
    by: average, max, count
    '''
    from collections import defaultdict
    
    def __average(seq):
        if len(seq) == 0: return -1
        return sum(seq) / len(seq)
        
    def __count(seq):
        bins = defaultdict(int)
        for _ in seq: bins[_] += 1
        return max(bins.items(), key=lambda x: x[1])[0]
        
    def __findmatch(tup, ltup):
        mdiff = 1<<31
        mv = -1
        for _i, _ in enumerate(ltup):
            diff = sum([(_a - _b)**2 for _a, _b in zip(_, tup)])
            if diff < mdiff:
                mdiff = diff
                mv = _i
        return mv
    
    im = im.crop(rect)
    #im.save('tmp.png')
    #print(list(im.getdata()), colors)
    #exit()
    data = [colors.index(tup[:3]) for tup in im.getdata() if tup[:3] in colors]
    return {
        'count': __count,
        'average': __average,
        'max': max
    }[by](data)
    
    
def predict(hrs, city='default', span=24, avg='average'):
    '''
    predict `span` hours after now + `hrs`
    avg: return max or average level in this `span` hours
    '''
    from datetime import datetime
    span = max(span, 3)
    hrs += (datetime.utcnow().hour + 9) % 24
    rect = cities.get(city, (0, 0, 10, 10))
    
    data = []
    for _hr in range(hrs, hrs+span, 3):
        im = _fetch_picture(_hr)
        l = _value_average(im, rect)
        data.append(l)
        
    return {
        'average': lambda d: sum(d)/len(d),
        'max': max
    }[avg](data)
