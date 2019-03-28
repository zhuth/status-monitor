from flask_socketio import SocketIO, send, emit
from threading import Thread, Event
import time

thread_stop_event = Event()

socketio = None
thread = Thread()

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
        except Exception as ex:
            socketio.emit('stats', {'node': self.node_name, 'resp': {'error': str(ex)}}, namespace='/stats', broadcast=True)
        time.sleep(0)
        
        
class StatsThread(Thread):
    
    def __init__(self, selfnode, delay):
        self.delay = delay
        self.selfnode = selfnode
        super(StatsThread, self).__init__()
        
    def query(self):
        for node_name, n in [('self', self.selfnode)] + list(self.selfnode.nodes.items()):
            QueryThread(node_name, n).start()
        
    def run(self):
        thread_stop_event.clear()
        while not thread_stop_event.isSet():
            self.query()
            time.sleep(self.delay)
    
        
def apply(cfg, app, selfnode):
    global socketio, thread
    if cfg.get('async_mode', 'gevent') == 'eventlet':
        import eventlet
        eventlet.monkey_patch()
    
    socketio = SocketIO(app, async_mode=cfg.get('async_mode', 'gevent'))
    
    @socketio.on('pull', namespace='/stats')
    @socketio.on('connect', namespace='/stats')
    def s_connect():
        global thread
        if thread.isAlive():
            thread.query()
        else:
            print("Starting Thread")
            thread = StatsThread(selfnode, cfg.get('interval', 30))
            thread.start()
    
    @socketio.on('disconnect', namespace='/stats')
    def s_disconnect():
        thread_stop_event.set()
    
    @socketio.on('push', namespace='/nodes')
    def s_push(data):
        n = selfnode.nodes.get(data['node'])
        if n and hasattr(n, 'set_buffer'):
            n.set_buffer(data)
    
    socketio.run(app, host='0.0.0.0', port=10000, debug=True)

