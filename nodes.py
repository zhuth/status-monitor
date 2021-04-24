#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
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

    def __init__(self, ip=None, power_ip=None, services=None, interval=0, url=None, port=10000, dispname=''):
        self.url = url
        if url:
            self.base_url = url + 'node/self'
        else:
            self.ip = ip
            self.port = port
            self.base_url = 'http://{}:{}/node/self'.format(self.ip, self.port)
        self.power_ip = power_ip
        self.interval = interval
        self._services = services
        self._status_buf = {}
        self.last_update = 0
        self.dispname = dispname

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
        if self._services == 'auto' and self.base_url:
            try:
                self.services = self.jcurl('services')
            except TimeoutError:
                pass
            except KeyError:
                pass
            except json.decoder.JSONDecodeError:
                print('Error while loading from {}'.format(self.base_url))
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


class SwitchNode(StatusNode):
    """
    Power Node
    """

    def __init__(self, power_ip, **kwargs):
        super().__init__(self, power_ip=power_ip, services=[], **kwargs)

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


class DelegateNode(StatusNode):

    def __init__(self, name, parent, services=None, interval=0, **kwargs):
        super().__init__(services=services, interval=interval, **kwargs)
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

    def __init__(self, ip, password, interval=0, **kwargs):
        super().__init__(ip=ip, interval=interval, **kwargs)
        self._tpLinkRouterClass = __import__('tplink_api.tplink').TpLinkRouter
        self.router = self._tpLinkRouterClass(ip)
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
