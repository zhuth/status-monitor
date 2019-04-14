#!/usr/bin/env python
import serial, sys, os, socket
import threading, json
import time, sqlite3
from PIL import Image, ImageFont, ImageDraw
from io import BytesIO
import os


aqi_colors = ['009966', 'ffde33', 'ff9933', 'cc0033', '660099', '730023']

if not os.path.exists('FreeSansBold.ttf'):
    os.system('curl -L https://github.com/opensourcedesign/fonts/raw/master/gnu-freefont_freesans/FreeSansBold.ttf > FreeSansBold.ttf')
fnt = ImageFont.truetype('FreeSansBold.ttf', 35)
os.chdir(os.path.dirname(__file__))

    
def aqi(pm25at, pm10at):
    def a25(pm25):
        # // break points: 12, 35.5, 55.5, 150.5, 250.5, 350.5, 500.5
        # //               50   100   150    200    300    400    500
        if pm25 <= 12:
            return pm25 * 50 / 12
        elif pm25 <= 35:
            return 50 + (pm25 - 12) * 50 / 23
        elif pm25 <= 55:
            return 100 + (pm25 - 35) * 5 / 2
        elif pm25 <= 150:
            return 150 + (pm25 - 55) * 50 / 95
        elif pm25 <= 350: 
            return 50 + pm25
        else:
            return 400 + (pm25 - 350) * 2 / 3
    
    def a10(pm10):
        # // break points: 55, 155, 255, 355, 425, 505, 605
        if pm10 <= 55:
            return pm10 * 50 / 55
        elif pm10 <= 355:
            return 50 + (pm10 - 55) / 2
        elif pm10 <= 425:
            return 200 + (pm10 - 355) * 10 / 7
        elif pm10 <= 505:
            return 300 + (pm10 - 425) * 10 / 8
        else:
            return pm10 - 105
   
    return max(a25(pm25at), a10(pm10at))

    
def tcplistener(aport):

    def mergeBytes(a, b):
        return (a<<8)|b

    skt = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    while True:
        try:
            os.remove('/tmp/aqimonitor.socket')
        except OSError:
            pass
        try:
            skt.bind('/tmp/aqimonitor.socket')
            os.chmod('/tmp/aqimonitor.socket', 0o777)
            break
        except:
            time.sleep(2)
            pass
    port = aport
    while True:
        if aport == 'auto':
            ports = [_ for _ in os.listdir('/dev/') if _.startswith('ttyACM')]
            if len(ports) == 0:
                time.sleep(1)
                continue
            port = '/dev/' + ports[0]
        try:
            print(port)
            with serial.Serial(port, 9600, timeout=10) as ser:
                time.sleep(1)
                ser.write(b' -')
                b = ''
                while True:
                    skt.listen(1)
                    conn, addr = skt.accept()
                    data = conn.recv(32)
                    details = {}
                    if not data: continue
                    if data == b'?':
                        ser.flushInput()
                        details = {}
                        b = ser.read(32)
                        while len(b) < 32:
                            b += ser.read(32 - len(b))
                        idx = b.find(b'\x42\x4d')
                        if idx > 0:
                            b = b[idx:]
                            b += ser.read(idx)
                        
                        try:
                            b = b[2:]
                            details['pm1_at']  = mergeBytes(b[10], b[11])
                            details['pm25_at'] = mergeBytes(b[12], b[13])
                            details['pm10_at'] = mergeBytes(b[14], b[15])
                            details['p03_c']   = mergeBytes(b[16], b[17])
                            details['p05_c']   = mergeBytes(b[18], b[19])
                            details['p1_c']    = mergeBytes(b[20], b[21])
                            details['p25_c']   = mergeBytes(b[22], b[23])
                            details['temp']    = mergeBytes(b[24], b[25]) / 10
                            details['hum']     = mergeBytes(b[26], b[27]) / 10
                            details['aqi']     = aqi(details['pm25_at'], details['pm10_at'])
                            details['last_update'] = int(time.time() * 1000)
                        except IndexError:
                            pass
                            
                        conn.send(json.dumps(details).encode('utf-8'))
                    elif data == b'/':
                        ser.write(b' \n')
                        ser.flushOutput()
                    elif data.startswith(b'icon'):
                        conn.send(icon(data[4:data.rfind(b'.')].decode('utf-8')))
                    else:
                        ser.write(data + b'\n')
                        ser.flushOutput()
                        conn.send(b'OK')
                    conn.close()
        except KeyboardInterrupt:
            skt.close()
            break
        except Exception as ex:
            print(ex)
            time.sleep(1)


def icon(aqi):
        
    def __icon_color(a):
        a = int(float(a))
        aqi_stage = 1
        if a >  50: aqi_stage += 1
        if a > 100: aqi_stage += 1
        if a > 150: aqi_stage += 1
        if a > 200: aqi_stage += 1
        if a > 300: aqi_stage += 1
        color = aqi_colors[aqi_stage-1]
        return (int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16))
    
    if aqi == '-' or aqi is None:
        color = (255, 255, 255)
        im = Image.new('RGB', (64, 64), color)
        d = ImageDraw.Draw(im)
        w, h = fnt.getsize('-')
        d.text(((64-w)/2, 10), '-', font=fnt, fill=(255, 255, 255))
    elif ':' in aqi:
        im = Image.new('RGB', (64, 64), (0, 0, 0))
        d = ImageDraw.Draw(im)
        aqi1, aqi2 = [int(_) for _ in aqi.split(':')]
        color1, color2 = __icon_color(aqi1), __icon_color(aqi2)
        d.polygon([(0, 0), (64, 0), (0, 64)], fill=color1)
        d.polygon([(64, 64), (64, 0), (0, 64)], fill=color2)
    else:    
        color = __icon_color(aqi)
        im = Image.new('RGB', (64, 64), color)
        d = ImageDraw.Draw(im)
        aqi = int(float(aqi))
        w, h = fnt.getsize(str(aqi))
        d.text(((64-w)/2, 10), str(aqi), font=fnt, fill=(0, 0, 0) if aqi > 50 and aqi <= 150 else (255, 255, 255))
    
    buf = BytesIO()
    im.save(buf, format="PNG")
    content = buf.getvalue()
    return content
            
if __name__ == '__main__':
    tcplistener(sys.argv[1] if len(sys.argv) > 1 else 'auto')

