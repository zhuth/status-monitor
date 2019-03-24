#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from flask import Flask, Response, jsonify, request, redirect

import os, psutil, json, time, base64, sys, re, yaml
from datetime import datetime, timedelta
import requests
import subprocess
import traceback

path = os.path.dirname(__file__) or '.'
os.chdir(path)

cfg = {}
if os.path.exists('config.yaml'):
    cfg = yaml.load(open('config.yaml', encoding='utf-8'))

import nodes
nodes.StatusNode.timeout = cfg.get('timeout', 1)
        
        
class SelfNode(nodes.StatusNode):
    """
    Detect system mode
    """
    def __init__(self):
        nodes.StatusNode.__init__(self, ip='localhost', services='auto')
        self.serv_procs = {}
        self.nodes = {}
        try:
            rs = subprocess.call('which systemctl'.split())
        except:
            rs = 2
        if rs == 0:
            self._service_cmd = 'systemctl {cmd} {name}'
        elif os.path.exists('/etc/init.d'):
            self._service_cmd = '/etc/init.d/{name} {cmd}'
        elif os.path.exists('/opt/etc/init.d'):
            self._service_cmd = '/opt/etc/init.d/{name} {cmd}'
            
        if not hasattr(os, 'getloadavg'):
            os.getloadavg = lambda: ''

        self.config = cfg
        for n in self.config.get('nodes', []):
            name = n['name']
            cls = nodes.__dict__.get(n.get('type'), nodes.StatusNode)
            if cls is nodes.DelegateNode:
                n = nodes.DelegateNode(name, self.nodes[n.get('parent')])
            else:
                if 'type' in n: del n['type']
                del n['name']
                n = cls(**n)
                print(n)
            self.nodes[name] = n
        print('Init done.')

    def detect_power(self):
        return True

    def ping(self):
        return True

    def get_status(self):
    
        def meminfo():
            return '{:.1f}%'.format(psutil.virtual_memory().percent)
    
        def temperature():
            if 'temperature_method' in self.config:
                vars = {'temp': 'err'}
                try:
                    exec(self.config['temperature_method'], globals(), vars)
                except: pass
                return vars['temp']
            elif os.path.exists('/sys/class/thermal/thermal_zone0/temp'):
                with open('/sys/class/thermal/thermal_zone0/temp', 'r') as tmpo:
                    temp = int(tmpo.read())
                return '{:.1f}d'.format(temp / 1000)
            else:
                return ''
                
        if self.services == 'auto': self.load_services()

        status = {}
        status['nodes'] = {}
        for name, n in self.nodes.items():
            status['nodes'][name] = {
                'power': n.detect_power(),
                'name': name
            }

        status['services'] = {}
        for _ in self.services:
            if '@' not in _['name']:
                status['services'][_['name']] = False
        
        if self.services:
            for _ in psutil.process_iter():
                short_key = _.name() + ':'
                long_key = short_key + _.username()
                s = None
                if short_key in self.serv_procs:
                    s = self.serv_procs[short_key]
                if long_key in self.serv_procs:
                    s = self.serv_procs[long_key]
                if s is None:
                    continue
                if s.get('uname') and s['uname'] != _.username():
                    continue
                if s.get('args') and s['args'] not in _.cmdline():
                    continue

                status['services'][s['name']] = True

        t = time.time() - psutil.boot_time()
        status['uptime'] = '{}:{:02d}:{:02d}:{:02d} {:.01f}% {} Mem: {}'.format(
            int(t / 86400), int(t / 3600) % 24, int(t % 3600 / 60), int(t % 60),
            psutil.cpu_percent(interval=None), ' '.join([ '%.2f' % _ for _ in os.getloadavg()]),
            meminfo())

        status['temp'] = temperature()
        return status

    def power_off(self):
        os.system('shutdown now')
        return True
    
    def reboot(self):
        os.system('reboot')
        return True

    def set_service(self, service_name, cmd):
        def __act(actions, cmd):
            if cmd in actions:
                action = actions[cmd]
                if action.startswith('link:'):
                    return redirect(action[5:])
                elif action == '@' and cmd == 'restart':
                    __act(actions, 'stop')
                    __act(actions, 'start')
                else:
                    os.system(action)
            else:
                os.system(self._service_cmd.format(cmd=cmd, name=service_name))
    
        assert service_name in self.serv_dict
        actions = self.serv_dict[service_name].get('actions', {})
        assert cmd in ['reload', 'restart', 'start', 'stop', 'status'] or cmd in actions
        __act(actions, cmd)
        return True

    def load_services(self):
        services = self.config.get('services', [])
        services = [_ for _ in services if not _.get('uname', '').startswith('//')]

        for node_name, n in self.nodes.items():
            if n.services:
                services += [
                    {
                        'name': '{}@{}'.format(_['name'], node_name),
                        'uname': '',
                        'actions': _.get('actions', []),
                        'dispname': _.get('dispname', None),
                    }
                    for _ in n.load_services()
                    if not _.get('uname', '').startswith('//')
                ]

        self.serv_procs = dict([(_['proc'] + ':' + _.get('uname', ''), _)
                                for _ in services if '@' not in _['name']])

        self.services = services
        self.serv_dict = dict([(_['name'], _) for _ in services])
            
        return self.services


app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'


@app.route('/node/<node_name>/<path:cmd>')
@app.route('/node/<node_name>')
def node(node_name='self', cmd='get_status', arg=''):
    n = selfnode.nodes.get(node_name, selfnode)
    arg = cmd.split('/')[1:] or []
    cmd = cmd.split('/')[0]
    if hasattr(n, cmd):
        try:
            r = getattr(n, cmd)(*arg)
            if isinstance(r, (Response, tuple)):
                return r
            else:
                if cmd == 'node':
                    return jsonify(r)
                else:
                    return jsonify({'node': node_name, 'resp': r})
        except Exception as ex:
            return jsonify({'error': str(ex), 'callstack': traceback.format_exc()})
    else:
        return 'No command {} for node {}. Choices are: {}'.format(cmd, node_name, ', '.join(dir(n))), 404
        
        
@app.route('/node/<node_name>', methods=["PUT"])
def node_put_status(node_name):
    n = selfnode.nodes.get(node_name, None)
    if n is None:
        return 'No such node.', 404
    elif not isinstance(n, nodes.ActiveNode):
        return 'Node {} is not an active node.', 400
    n.set_buffer(request.get_json())
    return 'Updated', 201


@app.route('/reload')
def reload():
    from pathlib import Path
    Path(__file__).touch()
    return redirect('./')
        

@app.route('/', methods=["GET", "POST"])
@app.route('/<path:p>')
def index(p='index.html'):
    if cfg.get('password'):
        if request.form.get('pass') == cfg.get('password'):
            resp = Response('''<html><script>location.href='./'</script>
            ''')
            resp.set_cookie('auth', 'FF', expires=datetime.now()+timedelta(days=90))
            return resp
        elif request.cookies.get('auth') != 'FF':
            return Response('''<html><form method="post" action=""><input type="password" name="pass"></form>
            ''')
    if p and os.path.exists(p):
        with open(p, 'rb') as f:
            return Response(f.read(), mimetype={
                'html': 'text/html',
                'json': 'application/json',
                'css': 'text/css'
            }.get(p.split('.')[-1], 'text/plain'))
    return 'Not Found', 404


if __name__ == '__main__':
    if not os.path.exists('bootstrap.min.css'):
        os.system('wget -c https://cdn.bootcss.com/jquery/3.2.1/jquery.min.js')
        os.system('wget -c https://stackpath.bootstrapcdn.com/bootstrap/3.3.7/js/bootstrap.min.js')
        os.system('wget -c https://stackpath.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css')
        os.system('wget -c https://cdnjs.cloudflare.com/ajax/libs/socket.io/1.3.6/socket.io.min.js')

    selfnode = SelfNode()
    
    if cfg.get('parent'):
        from threading import Thread
        from socketIO_client import SocketIO as SIOClient, LoggingNamespace
        parent = cfg['parent']
        
        class ActiveNodeThread(Thread):            
            def run(self):
                while True:
                    s = SIOClient(parent, 10000)
                    st = s.define(LoggingNamespace, '/stats')
                    with s:
                        while True:
                            try:
                                print('push')
                                st.emit('push', {
                                    'node': cfg['name'],
                                    'status': selfnode.get_status(),
                                    'services': selfnode.load_services()
                                })
                                s.wait(seconds=1)
                                time.sleep(30)
                            except KeyboardInterrupt:
                                exit()
                            except Exception as ex:
                                print(ex)
                                break
                                
        ActiveNodeThread().start()
    
    if cfg.get('websocket', True):
        import ws
        ws.apply(cfg, app, selfnode)
    else:
        print('Web Socket disabled')
        app.run(host='0.0.0.0', port=10000, debug=True)
