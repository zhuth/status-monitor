#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from flask import Flask, Response, jsonify, request, redirect
from flask_socketio import SocketIO, send, emit

import os, psutil, json, time, base64, sys, re, yaml
import requests
import subprocess
from threading import Thread, Event

import eventlet
eventlet.monkey_patch()

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
cfg = {}
if os.path.exists('config.yaml'):
    cfg = yaml.load(open('config.yaml', encoding='utf-8'))

socketio = SocketIO(app, async_mode='eventlet')
path = os.path.dirname(__file__) or '.'
os.chdir(path)

import nodes
nodes.StatusNode.timeout = cfg.get('timeout', 1)

thread = Thread()
thread_stop_event = Event()


class StatsThread(Thread):

    class QueryThread(Thread):
        def __init__(self, node_name, n):
            self.node_name = node_name
            self.n = n
            super().__init__()
            
        def run(self):
            try:
                socketio.emit('stats', {'node': self.node_name, 'resp': self.n.get_status()}, namespace='/stats', broadcast=True)
            except TimeoutError:
                pass
            time.sleep(0)
    
    def __init__(self, nodes, delay):
        self.delay = delay
        self.nodes = nodes
        super(StatsThread, self).__init__()
        
    def query(self):    
        socketio.emit('stats', {'node': 'self', 'resp': selfnode.get_status()}, namespace='/stats', broadcast=True)
        for node_name, n in self.nodes.items():
            StatsThread.QueryThread(node_name, n).start()
        
    def run(self):
        while not thread_stop_event.isSet():
            self.query()
            time.sleep(self.delay)
            
        
class SelfNode(nodes.StatusNode):
    """
    Detect system mode
    """
    def __init__(self):
        nodes.StatusNode.__init__(self, ip='localhost', services='auto')
        self.serv_procs = {}
        self.nodes = {}
        if subprocess.call('which systemctl'.split()) == 0:
            self._service_cmd = 'systemctl {cmd} {name}'
        elif os.path.exists('/etc/init.d'):
            self._service_cmd = '/etc/init.d/{name} {cmd}'
        elif os.path.exists('/opt/etc/init.d'):
            self._service_cmd = '/opt/etc/init.d/{name} {cmd}'

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
            self.nodes[name] = n

    def detect_power(self):
        return True

    def ping(self):
        return True

    def get_status(self):
    
        def meminfo():
            if os.path.exists('/proc/meminfo'):
                with open('/proc/meminfo', 'r') as f:
                    total = f.readline().split()[-2]
                    free  = f.readline().split()[-2]
                return '{:.1f}%'.format(100-100.0*float(free)/float(total))
            return ''
    
        def temperature():
            if 'temperature_method' in self.config:
                vars = {}
                exec(self.config['temperature_method'], globals(), vars)
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


@app.route('/node/<node_name>/<path:cmd>')
@app.route('/node/<node_name>')
def node(node_name='self', cmd='get_status', arg=''):
    n = selfnode.nodes.get(node_name, selfnode)
    arg = cmd.split('/')[1:] or []
    cmd = cmd.split('/')[0]
    if hasattr(n, cmd):
        r = getattr(n, cmd)(*arg)
        if isinstance(r, (Response, tuple)):
            return r
        else:
            if cmd == 'node':
                return jsonify(r)
            else:
                return jsonify({'node': node_name, 'resp': r})
    else:
        return 'No command {} for node {}. Choices are: {}'.format(cmd, node_name, ', '.join(dir(n))), 404


@app.route('/reload')
def reload():
    from pathlib import Path
    Path(__file__).touch()
    return redirect('./')
        

@app.route('/')
@app.route('/<path:p>')
def index(p='index.html'):
    if p and os.path.exists(p):
        with open(p, 'rb') as f:
            return Response(f.read(), mimetype={
                'html': 'text/html',
                'json': 'application/json',
                'css': 'text/css'
            }.get(p.split('.')[-1], 'text/plain'))
    return 'Not Found', 404
    
    
@socketio.on('connect', namespace='/stats')
def stats_connect():
    global thread
    emit('notify', {'data': 'Connected'})
    print('Client connected')
    
    if thread.isAlive():
        thread.query()
    else:
        print("Starting Thread")
        thread = StatsThread(selfnode.nodes, cfg.get('interval', 30))
        thread.start()


if __name__ == '__main__':
    if not os.path.exists('bootstrap.min.css'):
        os.system('wget -c https://cdn.bootcss.com/jquery/3.2.1/jquery.min.js')
        os.system('wget -c https://stackpath.bootstrapcdn.com/bootstrap/3.3.7/js/bootstrap.min.js')
        os.system('wget -c https://stackpath.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css')
        os.system('wget -c https://cdnjs.cloudflare.com/ajax/libs/socket.io/1.3.6/socket.io.min.js')

    selfnode = SelfNode()
    socketio.run(app, host='0.0.0.0', port=10000, debug=True)
