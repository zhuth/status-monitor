#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
import subprocess
import json
import os
import sys
import base64
import time
from flask import Response
import re


def _curl(url, timeout=None):
    if timeout is None:
        timeout = StatusNode.timeout
    try:
        return requests.get(url, timeout=timeout)
    except requests.exceptions.ReadTimeout:
        raise TimeoutError
    except requests.exceptions.ConnectionError:
        raise TimeoutError


class StatusNode:
    """
    Defines a status node
    """
    timeout = 1

    def __init__(self, ip=None, power_ip=None, services=None, interval=0, url=None, port=10000):
        self.url = url
        if url:
            self.base_url = url + 'node/self'
            self.ip = url.split('://', 1)[1].split('/')[0]
            if ':' in self.ip:
                self.ip, self.port = url.rsplit(':', 1)
                self.port = int(self.port)
            else:
                self.port = 80
        else:
            self.ip = ip
            self.port = port
            self.base_url = 'http://{}:{}/node/self'.format(self.ip, self.port)
        self.power_ip = power_ip
        self.interval = interval
        self._services = services
        self._status_buf = {}
        self.last_update = 0

    def detect_power(self):
        if self.url:
            return None
        return os.system('/bin/ping -w 1 -c 1 {} > /dev/null'.format(self.ip)) == 0

    def jcurl(self, *args):
        j = json.loads(_curl('{}{}'.format(self.base_url, ('/' + '/'.join(args)) if len(args) else ''),).content.decode('utf-8'))
        if 'resp' in j: return j['resp']
        else: return j

    @property
    def services(self):
        if self._services == 'auto' and self.ip:
            try:
                self.services = self.jcurl('services')
            except TimeoutError:
                pass
            except KeyError:
                pass
            except json.decoder.JSONDecodeError:
                print('Error while loading from {}'.format(self.ip))
                pass
        return self._services if isinstance(self._services, list) else []

    def _get_status(self):
        try:
            return self.jcurl()
        except TimeoutError:
            pass

    def get_status(self):
        if time.time() - self.last_update >= self.interval:
            power = self.detect_power()
            if power or power is None:
                self.set_buffer({'status': self._get_status()})
            else:
                self.set_buffer({'status': {'power': power}})
        return self._status_buf

    def set_buffer(self, request_json, **kwargs):
        self._status_buf = request_json['status'] or {}
        if not isinstance(self._services, list):
            self._services = request_json.get('services', [])
        if 'power' not in self._status_buf: self._status_buf['power'] = True
        self.last_update = time.time()
        self._status_buf['last_update'] = self.last_update

    def _power(self, cmd):
        if self.power_ip:
            assert cmd in ['on', 'off', 'uflash', 'flash']
            assert _curl('http://{}/{}'.format(self.power_ip, cmd)
                         ).status_code == 200
            return True

    def force_off(self):
        if self.power_ip:
            self._power('on')
            time.sleep(10)
            self._power('off')
            return True

    def power_on(self):
        if self.power_ip and self.power_ip.startswith("wol:"):
            wolmac = self.power_ip[4:].replace(':', '-').strip()
            from wakeonlan import send_magic_packet
            send_magic_packet(wolmac, ip_address='.'.join(
                self.ip.split('.')[:3]+['255']))
            return True
        elif self.ip and self.power_ip:  # computer with wifi power button
            return self._power('uflash')

    def power_off(self):
        if not self.power_ip:
            return {'error': 'No power-up method, power-off forbidden.'}
        if self.ip:
            return self.jcurl('power_off')
        else:
            return self._power('off')

    def reboot(self):
        return self.jcurl('reboot')

    def set_service(self, service_name, cmd):
        assert cmd in ['restart', 'reload', 'stop', 'start', 'status']
        return self.jcurl('set_service', service_name, cmd)

    def run(self, cmd, *args):
        return self.jcurl('run', cmd, *args)

    def node(self, node_name, *other_params):
        op = '/'.join(other_params)
        if op:
            op = '/' + op
        resp = _curl(self.base_url[:-4] + '{}{}'.format(node_name, op), timeout=2)
        if resp.headers['content-type'] == 'application/json':
            return json.loads(resp.content.decode('utf-8'))
        else:
            return Response(resp.content, content_type=resp.headers['content-type'])

    def refresh_status(self):
        self.last_update = 0


class AirPurifier(StatusNode):

    def __init__(self, httpserv='', socket='/tmp/aqimonitor.socket', city='Beijing', interval=60):
        super().__init__(interval=interval)
        self._services = []
        self.socket = socket
        self.httpserv = httpserv
        self.city = city

    def detect_power(self):
        return None

    def icon_base64(self, aqio):
        if not isinstance(aqio, str):
            aqio = str(int(aqio))
        aqi_icon = self.icon(aqio) or b''
        return 'data:image/png;base64,' + base64.b64encode(aqi_icon).decode('ascii')

    def try_connect(self):
        import socket
        try:
            skt = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            skt.connect(self.socket)
            return skt
        except:
            pass

    def call_command(self, cmd='?'):
        r = b''
        skt = self.try_connect()
        if self.httpserv and len(cmd) == 1:
            path = self.httpserv
            if cmd != '?': path += cmd
            try:
                lines = requests.get(path).content.decode('ascii').split('\r\n')
                if cmd == '?':
                    r = {}
                    paqi, pm, th = lines[:3]
                    r['aqi'] = paqi
                    r['pm25'], r['pm10'] = pm.split(' ')
                    r['temp'], r['hum'] = th.split(' ')
            except:
                return
        else:
            try:
                if not skt: return
                skt.sendall(cmd.encode('utf-8'))
                if cmd == '?':
                    tr = skt.recv(1024)
                    r = json.loads(
                        tr[tr.find(b'{'):tr.rfind(b'}')+1].decode('utf-8'))
                    if r['aqi'] > 1000:
                        raise Exception("Data range error.")
                else:
                    while True:
                        tr = skt.recv(1024)
                        if not tr:
                            break
                        r += tr
                skt.close()
            except TypeError as e:
                r['aqi'] = '-'
                r['error'] = str(e)

        if cmd == '?':
            return r
        elif cmd.startswith('icon'):
            return r
        else:
            return r.decode('utf-8')

    def icon(self, aqistr):
        return self.call_command('icon{}.'.format(aqistr))
        
    def aqi_icon(self, aqi):
        return Response(self.icon(aqi), content_type='image/png')

    def aqi_pred(self):
        return {
            'first_half': float(self.call_command('pred0,12') or -1),
            'second_half': float(self.call_command('pred12,12') or -1)
        }

    def city_aqi(self):
        js = requests.get(
            'http://feed.aqicn.org/feed/{}/en/feed.v1.js'.format(self.city)).content.decode('utf-8')
        m = re.search(r'>(\d+)<', js)
        if m:
            return m.group(1)
        else:
            return '-'

    def _get_status(self):
        d = self.call_command('?') or {'aqi': '-'}
        if d['aqi'] != '-':
            d['aqi_icon'] = self.icon_base64(d['aqi'])
            d['temp'] = str(int(d['temp'])) + 'd'
            d['hum'] = str(int(d['hum'])) + '%'
            
        pred = self.aqi_pred()
        d['aqi_pred'] = self.icon_base64('{}:{}'.format(
            int(pred['first_half']*30), int(pred['second_half']*30)))
        d['city_aqi'] = self.icon_base64(self.city_aqi())
        d['power'] = None
        return d

    def show(self, text):
        return self.call_command('c' + text)

    def reset(self):
        return self.call_command('y')

    def time(self):
        import datetime
        now = datetime.datetime.now()
        return self.call_command('t{}{:02d}{:02d}'.format(now.year, now.month, now.day))

    def toggle(self):
        return self.call_command('-')

    def speed1(self):
        return self.call_command('1')

    def speed2(self):
        return self.call_command('2')

    def power_on(self):
        return self.call_command('x')

    def power_off(self):
        return self.call_command('0')

    def bgon(self):
        return self.call_command(':')

    def bgoff(self):
        return self.call_command('/')


class SwitchNode(StatusNode):
    """
    Power Node
    """

    def __init__(self, power_ip):
        super().__init__(self, power_ip=power_ip, services=[])

    def detect_power(self):
        try:
            return _curl('http://{}/'.format(self.power_ip)).content == b'ON'
        except TimeoutError:
            pass

    def _get_status(self):
        return {'power': self.detect_power()}

    def set_service(self, service_name, cmd):
        pass

    def power_off(self):
        self._power('off')
        return True

    def power_on(self):
        self._power('on')
        return True


class KonkeNode(SwitchNode):
    """
    Konke Switch
    """

    def __init__(self, power_ip):
        super().__init__(power_ip=power_ip)
        from pykonkeio import Switch
        self._konke = Switch(power_ip)

    def detect_power(self):
        print(self._konke.status)
        return self._konke.status == 'open'

    def power_off(self):
        return self._konke.turn_off()
    
    def power_on(self):
        print('power on')
        return self._konke.turn_on()


class DelegateNode(StatusNode):

    def __init__(self, name, parent, services=None, interval=0):
        super().__init__(services=services, interval=interval)
        self.parent = parent
        self.name = name

    @staticmethod
    def resp(r):
        if isinstance(r, dict):
            return r.get('resp')
        return r

    def _get_status(self):
        return DelegateNode.resp(self.parent.node(self.name, 'get_status'))

    def detect_power(self):
        return DelegateNode.resp(self.parent.node(self.name, 'detect_power'))

    def power_on(self):
        return DelegateNode.resp(self.parent.node(self.name, 'power_on'))

    def power_off(self):
        return DelegateNode.resp(self.parent.node(self.name, 'power_off'))

    def set_service(self, service_name, cmd):
        r = DelegateNode.resp(self.parent.node(self.name, 'set_service'))
        return r

    def __getattr__(self, name):
        def deal(*args):
            try:
                return DelegateNode.resp(self.parent.node(self.name, name, *args))
            except TimeoutError:
                pass
        return deal

    @property
    def services(self):
        if self._services == "auto":
            self._services = DelegateNode.resp(
                self.parent.node(self.name, 'services'))
        return self._services


class TpLinkRouterNode(StatusNode):

    def __init__(self, ip, password, interval=0):
        super().__init__(ip=ip, interval=interval)
        from tplink_api.tplink import TpLinkRouter
        self.router = TpLinkRouter(ip)
        self.password = password
        self._services = [
            {'name': 'wlan2g', 'dispname': '2.4GHz'},
            {'name': 'wlan5g', 'dispname': '5GHz'},
        ]

    def _get_status(self):
        self.router.login(self.password)
        wl = self.router.get_wireless()
        return {  # "wl":wl,
            'services': {
                'wlan2g':
                    {'name': 'wlan2g', 'dispname': '2.4GHz',
                        'status': wl['wireless']['wlan_host_2g']['enable'] == "1"},
                'wlan5g':
                    {'name': 'wlan5g', 'dispname': '5GHz',
                        'status': wl['wireless']['wlan_host_5g']['enable'] == "1"}
            }
        }

    def reboot(self):
        return self.router.reboot()

    def set_service(self, service_name, cmd):
        self.router.login(self.password)
        if service_name in ('wlan2g', 'wlan5g'):
            if cmd == 'restart':
                self.router.reboot()
            else:
                self.router.set_wireless(cmd == 'start', service_name[-2:])
