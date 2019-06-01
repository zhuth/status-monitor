#!/opt/bin/python3
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
        nodes.StatusNode.__init__(self, ip='localhost', services='auto', interval=cfg.get('interval', 0))
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
            n = dict(n)
            name = n['name']
            cls = nodes.__dict__.get(n.get('type'), nodes.StatusNode)
            if cls is nodes.DelegateNode:
                if 'parent' not in n: continue
                del n['type']
                n['parent'] = self.nodes[n['parent']]
                n = nodes.DelegateNode(**n)
            else:
                if 'type' in n: del n['type']
                del n['name']
                n = cls(**n)
            self.nodes[name] = n

    def detect_power(self):
        return True

    def ping(self):
        return True

    def run(self, cmd, *args):
        assert cmd in cfg.get('allowed_commands', [])
        out_bytes = subprocess.check_output([cmd] + list(args), stderr=subprocess.STDOUT)
        return out_bytes.decode('utf-8')

    def _get_status(self):
    
        def meminfo():
            return '{:.1f}%'.format(psutil.virtual_memory().percent)
    
        def temperature():
            if 'temperature_method' in self.config:
                vars = {'temp': 'err'}
                try:
                    exec(self.config['temperature_method'], globals(), vars)
                except Exception as ex:
                    vars['temp'] = 'err: ' + str(ex)
                return vars['temp']
            elif os.path.exists('/sys/class/thermal/thermal_zone0/temp'):
                with open('/sys/class/thermal/thermal_zone0/temp', 'r') as tmpo:
                    temp = int(tmpo.read())
                return '{:.1f}d'.format(temp / 1000)
            else:
                return ''
                
        status = {}
        
        status['services'] = {}
        if self.services:
            for _ in self.services:
                if '@' not in _['name']:
                    status['services'][_['name']] = {
                        'status': False,
                        'dispname': _.get('dispname', _['name']),
                        'name': _['name'],
                        'actions': _.get('actions', [])
                    }
        
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

                status['services'][s['name']]['status'] = True
                
        if self.nodes:
            status['nodes'] = {}
            for _, n in self.nodes.items():
                status['nodes'][_] = type(n).__name__

        t = time.time() - psutil.boot_time()
        status['uptime'] = '{}:{:02d}:{:02d}:{:02d} {:.01f}% {} Mem: {}'.format(
            int(t / 86400), int(t / 3600) % 24, int(t % 3600 / 60), int(t % 60),
            psutil.cpu_percent(interval=None), ' '.join([ '%.2f' % _ for _ in os.getloadavg()]),
            meminfo())

        status['temp'] = temperature()
        return status

    def power_off(self):
        if 'shutdown' in self.config:
            vars = {'message': 'err'}
            try:
                exec(self.config['shutdown'], globals(), vars)
            except Exception as ex:
                vars['message'] = 'err: ' + str(ex)
                pass
            message = vars['message']
            if message and message.startswith('err'):
                return {'error': message[4:]}
        
        if self.power_ip:
            os.system('shutdown now')
            return True
        
        return {'error': 'No power-up method, shutting down is forbidden.'}
    
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

    @property
    def services(self):
        if self._services == 'auto':
            services = self.config.get('services', [])
            services = [_ for _ in services if not _.get('uname', '').startswith('//')]

            self.serv_procs = dict([(_['proc'] + ':' + _.get('uname', ''), _)
                                    for _ in services if '@' not in _['name']])
            self._services = services
            self.serv_dict = dict([(_['name'], _) for _ in services])
        
        return self._services
    
app = Flask(__name__)
app.config['SECRET_KEY'] = cfg.get('secret_key', 'secret!')

import hashlib
md5 = lambda x: hashlib.md5(x.encode('utf-8')).hexdigest()
cfg['encrypted_password'] = '' if 'password' not in cfg else md5(cfg['password'] + md5(app.config['SECRET_KEY']))


def client_ip():
    return request.environ.get('HTTP_X_FORWARDED_FOR', request.environ['REMOTE_ADDR']).split(', ')[0]


def is_authenticated():
    import fnmatch

    if 'granted_ips' in cfg:
        client = client_ip()
        for ips in cfg['granted_ips']:
            if client == ips or (('*' in ips or '?' in ips) and fnmatch.fnmatch(client, ips)):
                return True
    
    if 'password' in cfg:
        return request.cookies.get('auth') == cfg['encrypted_password']
    
    return True


def node_call(node_name='self', cmd='get_status', arg=''):
    
    def filter_password(d):
        if isinstance(d, dict):
            if 'password' in d: del d['password']
            for k in d:
                d[k] = filter_password(d[k])
        elif isinstance(d, list):
            d = [filter_password(_) for _ in d]
        return d
        
    n = selfnode.nodes.get(node_name, selfnode)
    arg = [_ for _ in arg.split('/') if _ != ''] or cmd.split('/')[1:] or []
    cmd = cmd.split('/')[0]
    if hasattr(n, cmd):
        try:
            r = getattr(n, cmd)
            if hasattr(r, '__call__'):
                r = r(*arg)
                if cmd != 'get_status':
                    n.refresh_status()
            if isinstance(r, (Response, tuple)):
                return r
            else:
                if cmd == 'config':
                    r = filter_password(dict(r))
                if cmd == 'node':
                    return r
                else:
                    return {'node': node_name, 'resp': r}
        except Exception as ex:
            return {'error': repr(ex), 'callstack': traceback.format_exc()}
    else:
        return {'error': 'No command {} for node {}. Choices are: {}'.format(cmd, node_name, ', '.join(dir(n)))}
        
        
@app.route('/node/<node_name>/<path:cmd>')
@app.route('/node/<node_name>')
def node(node_name='self', cmd='get_status', arg=''):
    if not is_authenticated(): return {'error': 'forbidden', 'source': client_ip()}

    r = node_call(node_name, cmd, arg)    
    if isinstance(r, (Response, tuple)):
        return r
    else:
        return jsonify(r)
        
        
@app.route('/node/<node_name>', methods=["PUT"])
def node_put_status(node_name):
    n = selfnode.nodes.get(node_name, None)
    if n is None:
        return 'No such node.', 404
    elif not isinstance(n, nodes.StatusNode):
        return 'Node {} is not an active node.', 400
    n.set_buffer(request.get_json())
    return 'Updated', 201


@app.route('/reload')
def reload():
    from pathlib import Path
    Path(__file__).touch()
    return redirect('./')
        

@app.route('/', methods=["GET", "POST"])
def index(p='index.html'):
    if not is_authenticated():
        if 'password' in cfg:
            if request.form.get('pass') == cfg['password']:
                resp = Response('''<html><script>location.href='./'</script>
                ''')
                resp.set_cookie('auth', cfg['encrypted_password'], expires=datetime.now()+timedelta(days=90))
                return resp
            elif request.cookies.get('auth', '') != cfg['encrypted_password']:
                return Response('''<html><form method="post" action=""><input type="password" name="pass"></form>
                ''' + client_ip())
    
    if p and os.path.exists(p) and p != 'config.yaml':
        with open(p, 'rb') as f:
            return Response(f.read(), mimetype={
                'html': 'text/html',
                'json': 'application/json',
                'css': 'text/css'
            }.get(p.split('.')[-1], 'text/plain'))
    return 'Not Found for {}'.format(p), 404


if __name__ == '__main__':
    selfnode = SelfNode()
    
    if cfg.get('parent'):
        from threading import Thread
        from socketIO_client import SocketIO as SIOClient, LoggingNamespace
        parent = cfg['parent']
        
        class ActiveNodeThread(Thread):            
            def run(self):
                while True:
                    s = SIOClient(parent, 10000)
                    st = s.define(LoggingNamespace, '/nodes')
                    with s:
                        while True:
                            try:
                                print('push')
                                st.emit('push', {
                                    'node': cfg['name'],
                                    'status': selfnode.get_status(),
                                    'services': selfnode.services
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
        vars = globals()
        ws.apply(vars)
    else:
        print('Web Socket disabled')
        app.run(host='0.0.0.0', port=10000, debug=True)
