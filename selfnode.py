# load config and set up async mode

import yaml
import os

cfg = {}
if os.path.exists('config.yaml'):
    cfg = yaml.safe_load(open('config.yaml', encoding='utf-8'))

if cfg.get('websocket'):
    if 'async_mode' not in cfg: cfg['async_mode'] = 'gevent'
    a = __import__(cfg['async_mode'])
    if cfg['async_mode'] == 'gevent':
        from gevent import monkey
        monkey.patch_all()
    elif cfg['async_mode'] == 'eventlet': a.monkey_patch()


import psutil, json, time, base64, sys, re
import requests
import subprocess
import nodes
from threading import Thread

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
            cls = nodes.__dict__.get(n.get('type', 'StatusNode'))
            if cls is None:
                print('No such type', n['type'])
                continue
            elif cls is nodes.DelegateNode:
                if 'parent' not in n: continue
                del n['type']
                n['parent'] = self.nodes[n['parent']]
                n = nodes.DelegateNode(**n)
            else:
                if 'type' in n: del n['type']
                del n['name']
                try:
                    n = cls(**n)
                except TypeError as te:
                    raise te
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

        status['shortcuts'] = cfg.get('shortcuts', [])

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

        status['disks'] = [
            '{} {:.01f}%'.format(d.mountpoint, usage.percent)
            for d, usage in [(disk, psutil.disk_usage(disk.mountpoint)) for disk in psutil.disk_partitions()]
        ]

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
            else:
                return {'message': message}
        else:
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
                    return action[5:]
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


selfnode = SelfNode()
    
    
class ActiveNodeThread(Thread):   
    def __init__(self, parent):
        super().__init__(daemon=False)
        self.parent = parent

    def run(self):
        while True:
            try:
                r = requests.put(self.parent + 'node/' + cfg.get('name'), data=json.dumps({
                    'node': cfg.get('name'),
                    'status': selfnode.get_status()
                }), headers={"Content-Type": "application/json"})
                if r.status_code != 201:
                    rc = r.content
                    raise Exception(rc)
            except Exception as ex:
                print(ex)
                continue
            time.sleep(cfg.get('interval', 30))

if cfg.get('parent'):
    parent = cfg['parent']
    if '://' not in parent: parent = 'http://' + parent
    ActiveNodeThread(parent).start()
