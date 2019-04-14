from flask_socketio import SocketIO, send, emit
from threading import Thread, Event
import time

thread_stop_event = Event()
thread_stop_event.set()

socketio = None
thread = Thread()

class QueryThread(Thread):
    def __init__(self, node_name, n, min_interval):
        super().__init__()
        self.node_name = node_name
        self.n = n
        self.interval = max(min_interval, self.n.interval)
        print('QueryThread for', node_name, 'started with interval', self.interval)
        
    def run(self):
        while not thread_stop_event.isSet():
            time.sleep(self.interval)
            try:
                socketio.emit('stats', {'node': self.node_name, 'resp': self.n.get_status()}, namespace='/stats', broadcast=True)
            except TimeoutError:
                pass
            except Exception as ex:
                socketio.emit('stats', {'node': self.node_name, 'resp': {'error': str(ex)}}, namespace='/stats', broadcast=True)
          
        
def apply(vars):
    cfg, app, selfnode = vars['cfg'], vars['app'], vars['selfnode']
    global socketio, thread
    if cfg.get('async_mode', 'gevent') == 'eventlet':
        import eventlet
        eventlet.monkey_patch()
    
    socketio = SocketIO(app, async_mode=cfg.get('async_mode', 'gevent'))
    
    @socketio.on('pull', namespace='/stats')
    @socketio.on('connect', namespace='/stats')
    def s_connect():
        nodes = [('self', selfnode)] + list(selfnode.nodes.items())
        if thread_stop_event.isSet():
            print("Starting Thread")
            thread_stop_event.clear()
            interval = cfg.get('interval', 30)
            for node_name, n in nodes:
                QueryThread(node_name, n, interval).start()
        for node_name, n in nodes:
            socketio.emit('stats', {'node': node_name, 'resp': n.get_status()}, namespace='/stats')
            
    @socketio.on('request', namespace='/stats')
    def s_node(data):
        socketio.emit('notify', vars['node_call'](data['node_name'], data['cmd'], data['arg']), namespace='/stats')
        time.sleep(2)
        socketio.emit('stats',
                        {'node': data['node_name'], 'resp': selfnode.nodes.get(data['node_name']).get_status()},
                        namespace='/stats')
    
    @socketio.on('disconnect', namespace='/stats')
    def s_disconnect():
        thread_stop_event.set()
    
    @socketio.on('push', namespace='/nodes')
    def s_push(data):
        n = selfnode.nodes.get(data['node'])
        if n and hasattr(n, 'set_buffer'):
            n.set_buffer(data)
    
    socketio.run(app, host='0.0.0.0', port=10000, debug=True)
