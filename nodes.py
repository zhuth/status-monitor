#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests, subprocess, json, os, sys, base64
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

    def __init__(self, ip=None, power_ip=None, services=None):
        self.ip = ip
        self.power_ip = power_ip
        self.services = services

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

    def get_status(self):
        if self.services is not None and self.ip:
            try:
                return json.loads(_curl('http://{}:10000/node/self/get_status'.format(self.ip))
                                  .content.decode('utf-8'))['resp']
            except TimeoutError:
                return

    def power(self, cmd):
        if self.power_ip.startswith("wol:"):
            if cmd == 'on':
                wolmac = self.power_ip[4:].replace(':', '-').strip()
                from wakeonlan import send_magic_packet
                send_magic_packet(wolmac, ip_address='.'.join(self.ip.split('.')[:3]+['255']))
                return True
        elif self.power_ip:
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
        if self.ip and self.power_ip and not self.power_ip.startswith('wol:'): # computer with wifi power button
            return self.power('uflash')
        else: # power node
            return self.power('on')

    def power_off(self):
        if self.ip and self.services:
            assert _curl('http://{}:10000/node/self/{}'.format(self.ip, 'power_off')).status_code == 200
        elif self.ip and self.power_ip: # computer
            return self.power('uflash')
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
        resp = _curl('http://{}:10000/node/{}{}'.
                                 format(self.ip, node_name, op), timeout=2)
        if resp.headers['content-type'] == 'application/json':
            return json.loads(resp.content.decode('utf-8'))
        else:
            return Response(resp.content, content_type=resp.headers['content-type'])


class ActiveNode(StatusNode):
    
    def __init__(self, ip=None, power_ip=None):
        StatusNode.__init__(self, ip=ip, power_ip=power_ip, services=[])
        self.status_buf = {}
        
    def get_status(self):
        return self.status_buf
        
    def load_services(self):
        return self.services
    
    def set_buffer(self, request_json):
        self.status_buf = request_json['status']
        self.services = request_json.get('services', [])


class AirPurifier(StatusNode):

    def __init__(self, socket='/tmp/aqimonitor.socket'):
        StatusNode.__init__(self)
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
        
    def aqi_icon(self, aqi):
        from aqimonitor import icon as __icon
        return Response(__icon(aqi), content_type='image/png')

    def aqi_pred(self):
        from AqiSprintarsForecast import predict
        return {
            'first_half': predict(0, span=12),
            'second_half': predict(12, span=12)
        }
        
    def get_status(self):
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

    def speed0(self):
        return self.call_command('0')

    def speed1(self):
        return self.call_command('1')

    def speed2(self):
        return self.call_command('2')

    def speed3(self):
        return self.call_command('x')

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

    def load_services(self):
        pass
    
    def reboot(self):
        pass

    def set_service(self, service_name, cmd):
        pass


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

    def get_status(self):
        pass

    def power_off(self):
        self._konke.turn_off()
        return True
    
    def power_on(self):
        self._konke.turn_on()
        return True


class DelegateNode:
    
    def __init__(self, name, parent):
        self.parent = parent
        self.name = name
        self.services = []
        
    @staticmethod
    def resp(r):
        if isinstance(r, dict): return r.get('resp')
        return r
        
    def __getattr__(self, name):
        def deal(*args):
            try:
                return DelegateNode.resp(self.parent.node(self.name, name, *args))
            except TimeoutError:
                pass
        return deal
    
    def load_services(self):
        if not self.services:
            self.services = DelegateNode.resp(self.parent.node(self.name, 'load_services'))
        return self.services
