#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# master version

from flask import Flask, Response, jsonify, request
import os, psutil, json, time, base64, sys, re
import requests

app = Flask(__name__)

path = os.path.dirname(__file__) or './'
os.chdir(path)

class StatusNode:
    """
    Defines a status node
    """
    def __init__(self, ip=None, power_ip=None, services=None):
        self.ip = ip
        self.power_ip = power_ip
        self.services = services

    @staticmethod
    def __curl(url, timeout=0.5):
        try:
            return requests.get(url, timeout=timeout)
        except requests.exceptions.ReadTimeout:
            raise TimeoutError
        except requests.exceptions.ConnectionError:
            raise TimeoutError

    def detect_power(self):
        if self.ip:
            return self.ping()
        else:  # with self.power_ip
            try:
                return StatusNode.__curl('http://{}/'.format(self.power_ip)).content == b'ON'
            except TimeoutError:
                pass

    def ping(self):
        if self.ip:
            return os.system('/usr/bin/timeout 1s /bin/ping -c 1 {} > /dev/null'.format(self.ip)) == 0

    def load_services(self):
        if self.services == 'auto' and self.ip:
            try:
                self.services = json.loads(StatusNode.__curl('http://{}:10000/node/self/load_services'
                                                             .format(self.ip))
                                           .content.decode('utf-8'))['resp']
            except TimeoutError:
                pass
            except KeyError:
                pass
        return self.services if isinstance(self.services, list) else []

    def get_status(self):
        if self.services and self.ip:
            try:
                return json.loads(StatusNode.__curl('http://{}:10000/node/self/get_status'.format(self.ip))
                                  .content.decode('utf-8'))['resp']
            except TimeoutError:
                return

    def power(self, cmd):
        if self.power_ip:
            assert cmd in ['on', 'off', 'uflash', 'flash']
            assert StatusNode.__curl('http://{}/{}'.format(self.power_ip, cmd)).status_code == 200
        return True

    def force_off(self):
        if self.power_ip:
            self.power('on')
            time.sleep(10)
            self.power('off')
            return True

    def power_on(self):
        if self.ip and self.power_ip: # computer
            return self.power('uflash')
        else:
            return self.power('on')

    def power_off(self):
        if self.ip and self.services:
            assert StatusNode.__curl('http://{}:10000/node/self/{}'.format(self.ip, 'power_off')).status_code == 200
        elif self.ip and self.power_ip: # computer
            return self.power('uflash')
        else:
            return self.power('off')
            
    def reboot(self):
        assert StatusNode.__curl('http://{}:10000/node/self/{}'.format(self.ip, 'reboot')).status_code == 200
        return True

    def set_service(self, service_name, cmd):
        if self.ip and self.services:
            assert cmd in ['restart', 'reload', 'stop', 'start', 'status']
            assert StatusNode.__curl('http://{}:10000/node/self/set_service/{},{}'.
                                     format(self.ip, service_name, cmd)).status_code == 200
            return True


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

        if r['aqi'] != '-':
            aqi_icon = self.icon(str(int(r['aqi'])))
            r['aqi_icon'] = 'data:image/png;base64,' + base64.b64encode(aqi_icon).decode('ascii')
            r['temp'] = str(int(r['temp'])) + 'd'
            r['hum'] = str(int(r['hum'])) + '%'

        return r

    def load_services(self):
        return []

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


class SelfNode(StatusNode):
    def __init__(self):
        StatusNode.__init__(self, ip='localhost', services='auto')
        self.serv_procs = {}
        self.nodes = {}

        if os.path.exists('nodes.json'):
            j = json.loads(open('nodes.json').read())
            for n in j:
                name = n['name']
                if 'type' not in n:
                    n['type'] = 'StatusNode'

                cls = StatusNode
                if n['type'] == 'AirPurifier':
                    cls = AirPurifier

                del n['type']
                del n['name']
                n = cls(**n)
                self.nodes[name] = n

        self.load_services()

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
            if os.path.exists('/sys/class/thermal/thermal_zone0/temp'):
                with open('/sys/class/thermal/thermal_zone0/temp', 'r') as tmpo:
                    temp = int(tmpo.read())
                return '{:.1f}d'.format(temp / 1000)
            else:
                try:
                    wls = ['WL' + i + ': ' + subprocess.check_output('wl -i eth{} phy_tempsense'.format(i).split()).decode('utf-8').split()[0] + 'd' for i in '12']
                    return ', '.join(wls)
                except:
                    pass
            return ''
    
        import subprocess
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
                os.system('systemctl {} {}'.format(cmd, service_name))
    
        assert service_name in self.serv_dict
        actions = self.serv_dict[service_name].get('actions', {})
        assert cmd in ['reload', 'restart', 'start', 'stop', 'status'] or cmd in actions
        __act(actions, cmd)
        return True

    def load_services(self):
        if self.services == 'auto':
            services = json.loads(open('services.json', encoding='utf-8').read())
            services = [_ for _ in services if not _.get('uname', '').startswith('//')]

            for node_name, n in self.nodes.items():
                if n.services:
                    services += [
                        {
                            'name': '{}@{}'.format(_['name'], node_name),
                            'uname': '',
                            'actions': _.get('actions', [])
                        }
                        for _ in n.load_services()
                        if not _.get('uname', '').startswith('//')
                    ]

            self.serv_procs = dict([(_['proc'] + ':' + _.get('uname', ''), _)
                                    for _ in services if '@' not in _['name']])

            self.services = services
            self.serv_dict = dict([(_['name'], _) for _ in services])
            
        return self.services


selfnode = SelfNode()


@app.route('/echo/<path:text>')
def echo(text):
    return text


@app.route('/node/<node_name>/<cmd>/<arg>')
@app.route('/node/<node_name>/<cmd>')
@app.route('/node/<node_name>')
def node(node_name='self', cmd='get_status', arg=''):
    n = selfnode.nodes.get(node_name, selfnode)
    if hasattr(n, cmd):
        if arg:
            return jsonify({'node': node_name, 'resp': getattr(n, cmd)(*arg.split(','))})
        return jsonify({'node': node_name, 'resp': getattr(n, cmd)()})
    else:
        return 'No command {} for node {}. Choices are: {}'.format(cmd, node_name, ', '.join(dir(n))), 404


buses = None


@app.route('/bus/<bus_no>/<int:stop>')
def bus(bus_no, stop):
    global buses
    if buses is None:
        if os.path.exists('bus.json'):
            buses = json.loads(open('bus.json').read())
        else:
            return jsonify({'error': 404})

    stop_type = 0 if stop > 0 else 1
    stop = abs(stop)
    bus_no = buses.get(bus_no + ('路' if bus_no.isnumeric() else ''), '')
    if bus_no and stop:
        bus_no = bus_no['sid']
        cont = requests.post('http://shanghaicity.openservice.kankanews.com/public/bus/Getstop',
                             {'stoptype': stop_type, 'stopid': '{}.'.format(stop), 'sid': bus_no}).content
        return jsonify(json.loads(cont))
    else:
        return jsonify({'error': 999})


@app.route('/aqi_icon/<aqi>')
def aqi_icon(aqi):
    from aqimonitor import icon as __icon
    return Response(__icon(aqi), content_type='image/png')


@app.route('/aqi_pred')
def aqi_pred():
    from AqiSprintarsForecast import predict
    return jsonify({
        'tomorrow': predict(0),
        'the_day_after_tomorrow': predict(24)
    })


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


if __name__ == '__main__':

    if not os.path.exists('bootstrap.min.css'):
        os.system('wget -n https://cdn.bootcss.com/jquery/3.2.1/jquery.min.js')
        os.system('wget -n https://stackpath.bootstrapcdn.com/bootstrap/3.3.7/js/bootstrap.min.js')
        os.system('wget -n https://stackpath.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css')

    if len(sys.argv) > 1 and sys.argv[1] == 'loop':
        while True:
            os.system('nohup python3 status.py > /dev/null')
            time.sleep(1)
    else:
        app.run(host='0.0.0.0', port=10000, debug=True)
