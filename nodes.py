#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests, subprocess, json, os, sys, base64, time
from flask import Response

def _curl(url, timeout=None):
    if timeout is None: timeout = StatusNode.timeout
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

    def __init__(self, ip=None, power_ip=None, services=None, interval=0):
        self.ip = ip
        self.power_ip = power_ip
        self.services = services
        self.interval = interval
        self._status_buf = {}
        self._last_update = 0

    def detect_power(self):
        return self.ping()

    def ping(self):
        if self.ip:
            return os.system('/bin/ping -c 1 {} > /dev/null'.format(self.ip)) == 0

    def load_services(self):
        if self.services == 'auto' and self.ip:
            try:
                self.services = json.loads(_curl('http://{}:10000/node/self/load_services'
                                                             .format(self.ip))
                                           .content.decode('utf-8'))['resp']
            except TimeoutError:
                pass
            except KeyError:
                pass
            except json.decoder.JSONDecodeError:
                print('Error while loading from {}'.format(self.ip))
                pass
        return self.services if isinstance(self.services, list) else []
        
    def _get_status(self):
        if self.services is not None and self.ip:
            try:
                return json.loads(_curl('http://{}:10000/node/self'.format(self.ip))
                                  .content.decode('utf-8'))['resp']
            except TimeoutError:
                pass

    def get_status(self):
        if time.time() - self._last_update >= self.interval:
            if not self.detect_power():
                self._status_buf = {'power': False, '_last_update': time.time()}
                self._last_update = 0
            else:
                self.set_buffer({'status': self._get_status()})
        return self._status_buf

    def set_buffer(self, request_json, **kwargs):
        self._status_buf = request_json['status'] or {}
        if not self.services: self.services = request_json.get('services', [])
        
        self._status_buf['power'] = True
        
        self._last_update = time.time()
        self._status_buf['_last_update'] = self._last_update
    
    def power(self, cmd):
        if self.power_ip:
            assert cmd in ['on', 'off', 'uflash', 'flash']
            assert _curl('http://{}/{}'.format(self.power_ip, cmd)).status_code == 200
            return True

    def force_off(self):
        if self.power_ip:
            self.power('on')
            time.sleep(10)
            self.power('off')
            return True

    def power_on(self):
        if self.power_ip and self.power_ip.startswith("wol:"):
            wolmac = self.power_ip[4:].replace(':', '-').strip()
            from wakeonlan import send_magic_packet
            send_magic_packet(wolmac, ip_address='.'.join(self.ip.split('.')[:3]+['255']))
            return True
        elif self.ip and self.power_ip : # computer with wifi power button
            return self.power('uflash')
        else: # power node
            return self.power('on')

    def power_off(self):
        if self.ip:
            assert _curl('http://{}:10000/node/self/{}'.format(self.ip, 'power_off')).status_code == 200
        else:
            return self.power('off')

    def reboot(self):
        assert _curl('http://{}:10000/node/self/{}'.format(self.ip, 'reboot')).status_code == 200
        return True

    def set_service(self, service_name, cmd):
        if self.ip and self.services:
            assert cmd in ['restart', 'reload', 'stop', 'start', 'status']
            assert _curl('http://{}:10000/node/self/set_service/{}/{}'.
                                     format(self.ip, service_name, cmd)).status_code == 200
            return True

    def node(self, node_name, *other_params):
        op = '/'.join(other_params)
        if op: op = '/' + op
        resp = _curl('http://{}:10000/node/{}{}'.format(self.ip, node_name, op), timeout=2)
        if resp.headers['content-type'] == 'application/json':
            return json.loads(resp.content.decode('utf-8'))
        else:
            return Response(resp.content, content_type=resp.headers['content-type'])
            
    def refresh_status(self):
        self._last_update = 0


class AirPurifier(StatusNode):

    def __init__(self, socket='/tmp/aqimonitor.socket'):
        super().__init__()
        import aqimonitor
        self.socket = socket
        self.aqi_colors = aqimonitor.aqi_colors
        self.icon = aqimonitor.icon

    def call_command(self, cmd):
        import socket
        r = {}
        try:
            skt = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            skt.connect(self.socket)
            skt.sendall(cmd.encode('utf-8'))
            if cmd == '?':
                tr = skt.recv(1024)
                r = json.loads(tr[tr.find(b'{'):tr.rfind(b'}')+1].decode('utf-8'))
                if r['aqi'] > 1000: raise Exception("Data range error.")
            else:
                r = b''
                while True:
                    tr = skt.recv(1024)
                    if not tr: break
                    r += tr
            skt.close()
        except TypeError as e:
            r['aqi'] = '-'
            r['error'] = str(e)

        if cmd == '?':
            if r['aqi'] != '-':
                aqi_icon = self.icon(str(int(r['aqi'])))
                r['aqi_icon'] = 'data:image/png;base64,' + base64.b64encode(aqi_icon).decode('ascii')
                r['temp'] = str(int(r['temp'])) + 'd'
                r['hum'] = str(int(r['hum'])) + '%'
        else:
            r = r.decode('utf-8')
        return r

    def load_services(self):
        return []
        
    def detect_power(self):
        return True
        
    def aqi_icon(self, aqi):
        from aqimonitor import icon as __icon
        return Response(__icon(aqi), content_type='image/png')

    def aqi_pred(self):
        from AqiSprintarsForecast import predict
        return {
            'first_half': predict(0, span=12),
            'second_half': predict(12, span=12)
        }
        
    def _get_status(self):
        return self.call_command('?')

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
        
    def power(self, onoff):
        self.call_command('0' if onoff == 'off' else 'x')
        
    def power_on(self):
        self.power('on')
    
    def power_off(self):
        self.power('off')
        
    def bgon(self):
        return self.call_command(':')

    def bgoff(self):
        return self.call_command('/')


class SwitchNode(StatusNode):
    """
    Power Node
    """
    def __init__(self, power_ip):
        super().__init__(self, power_ip=power_ip, services=None)
    
    def detect_power(self):        
        try:
            return _curl('http://{}/'.format(self.power_ip)).content == b'ON'
        except TimeoutError:
            pass
            
    def _get_status(self):
        return {}

    def load_services(self):
        pass
    
    def reboot(self):
        pass

    def set_service(self, service_name, cmd):
        pass
        
    def power_off(self):
        self.power('off')
        return True
    
    def power_on(self):
        self.power('on')
        return True


class KonkeNode(SwitchNode):
    """
    Konke Switch
    """
    def __init__(self, power_ip):
        super(SwitchNode, self).__init__(self, power_ip)
        from pykonkeio import Switch
        self._konke = Switch(self.power_ip)

    def detect_power(self):
        return self._konke.status == 'open'

    def ping(self):
        return self._konke.status != 'offline'

    def power_off(self):
        self._konke.turn_off()
        return True
    
    def power_on(self):
        self._konke.turn_on()
        return True


class DelegateNode(StatusNode):
    
    def __init__(self, name, parent, services=None, interval=0):
        super().__init__(services=services, interval=interval)
        self.parent = parent
        self.name = name
        
    @staticmethod
    def resp(r):
        if isinstance(r, dict): return r.get('resp')
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
        
    def get_status(self):
        return super().get_status()
        
    def __getattr__(self, name):
        def deal(*args):
            try:
                return DelegateNode.resp(self.parent.node(self.name, name, *args))
            except TimeoutError:
                pass
        return deal
    
    def load_services(self):
        if self.services == "auto":
            self.services = DelegateNode.resp(self.parent.node(self.name, 'load_services'))
        return self.services


class TpLinkRouterNode(StatusNode):
    
    def __init__(self, ip, password, interval=0):
        super().__init__(ip=ip, interval=interval)
        from tplink_api.tplink import TpLinkRouter
        self.router = TpLinkRouter(ip)
        self.password = password
        self.services = [
            {'name': 'wlan2g', 'dispname': '2.4GHz'},
            {'name': 'wlan5g', 'dispname': '5GHz'},
        ]
        
    def _get_status(self):
        self.router.login(self.password)
        wl = self.router.get_wireless()
        return { # "wl":wl,
            'services': {
                'wlan2g': wl['wireless']['wlan_host_2g']['enable'] == "1",
                'wlan5g': wl['wireless']['wlan_host_5g']['enable'] == "1"
            }
        }

    def reboot(self):
        return self.router.reboot()
    
    def set_service(self, service_name, cmd):
        self.router.login(self.password)
        if service_name in ('wlan2g', 'wlan5g'):
            if cmd == 'restart': self.router.reboot()
            else: self.router.set_wireless(cmd == 'start', service_name[-2:])
