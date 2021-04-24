#!/opt/bin/python3
# -*- coding: utf-8 -*-

import os

os.chdir(os.path.dirname(os.path.abspath(__file__)))

# normal imports

import traceback
import json
from datetime import datetime, timedelta
import time
from flask import Flask, Response, jsonify, request, redirect
import hashlib
crypt = lambda x: hashlib.sha1(x.encode('utf-8')).hexdigest()

path = os.path.dirname(__file__) or '.'
os.chdir(path)

from selfnode import selfnode, cfg, nodes

app = Flask(__name__)
app.config['SECRET_KEY'] = cfg.get('secret_key', 'secret!')

tokens = set()

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
        return request.form.get('token') in tokens
    
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
                elif isinstance(r, dict) and 'error' in r:
                    return r
                else:
                    return {'node': node_name, 'resp': r}
        except Exception as ex:
            return {'error': repr(ex), 'callstack': traceback.format_exc()}
    else:
        return {'error': 'No command {} for node {}. Choices are: {}'.format(cmd, node_name, ', '.join(dir(n)))}
        
        
@app.route('/node/<node_name>/<path:cmd>', methods=['POST', 'GET'])
@app.route('/node/<node_name>', methods=['POST', 'GET'])
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


@app.route('/auth', methods=['POST', 'GET'])
def auth_deal():
    if is_authenticated():
        return jsonify({'authenticated': True})

    atoken = request.form.get('token')
    apassword = request.form.get('password')
    if apassword and crypt(apassword) == cfg['password']:
        token = crypt('%.2f %s' % (time.time(), apassword))
        tokens.add(token)
        return jsonify({'token': token})
    else:
        return jsonify({'authenticated': atoken in tokens})


@app.route('/reload')
def reload():
    from pathlib import Path
    Path(__file__).touch()
    return redirect('./')


@app.route('/config.js')
def config():
    return 'var config = ' + json.dumps({
        'default_hash': 'node/self',
        'dispname': cfg.get('dispname', 'Router')
    })

@app.route('/', methods=['POST', 'GET'])
def index(p='index.html'):
    if p and os.path.exists(p) and p != 'config.yaml':
        with open(p, 'rb') as f:
            return Response(f.read(), mimetype={
                'html': 'text/html',
                'json': 'application/json',
                'css': 'text/css'
            }.get(p.split('.')[-1], 'text/plain'))
    return 'Not Found for {}'.format(p), 404


if __name__ == '__main__':
    
    import sys
    if len(sys.argv) == 3 and sys.argv[1] == 'crypt':
        pwd = sys.argv[2]
        print(crypt(pwd))
        exit()
    
    if cfg.get('http_serv', True):
        app.run(host='0.0.0.0', port=cfg.get('port', 10000), debug=True)
