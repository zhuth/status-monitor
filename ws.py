from flask_socketio import SocketIO, send, emit
from threading import Thread, Event
import time

thread = Thread()
thread_stop_event = Event()

class StatsThread(Thread):

    class QueryThread(Thread):
        def __init__(self, node_name, n, socketio):
            self.node_name = node_name
            self.n = n
            self.socketio = socketio
            super().__init__()
            
        def run(self):
            try:
                self.socketio.emit('stats', {'node': self.node_name, 'resp': self.n.get_status()}, namespace='/stats', broadcast=True)
            except TimeoutError:
                pass
            time.sleep(0)
    
    def __init__(self, selfnode, delay, socketio):
        self.delay = delay
        self.selfnode = selfnode
        self.socketio = socketio
        super(StatsThread, self).__init__()
        
    def query(self):    
        self.socketio.emit('stats', {'node': 'self', 'resp': self.selfnode.get_status()}, namespace='/stats', broadcast=True)
        for node_name, n in self.selfnode.nodes.items():
            StatsThread.QueryThread(node_name, n, self.socketio).start()
        
    def run(self):
        while not thread_stop_event.isSet():
            self.query()
            time.sleep(self.delay)
    
    
def stats_connect(selfnode, interval, socketio):
    global thread
    emit('notify', {'data': 'Connected'})
    print('Client connected')
    
    if thread.isAlive():
        thread.query()
    else:
        print("Starting Thread")
        thread = StatsThread(selfnode, interval, socketio)
        thread.start()
        
        
def apply(cfg, app, selfnode):
    if cfg.get('async_mode', 'gevent') == 'eventlet':
        import eventlet
        eventlet.monkey_patch()
    socketio = SocketIO(app, async_mode=cfg.get('async_mode', 'gevent'))
    
    @socketio.on('connect', namespace='/stats')
    def s_connect():
        stats_connect(selfnode, cfg.get('interval', 30), socketio)
    
    socketio.run(app, host='0.0.0.0', port=10000, debug=True)