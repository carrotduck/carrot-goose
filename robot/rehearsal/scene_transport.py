"""Authenticated HTTPS event/receipt transport, with no serial access."""
import json
import http.client
import socket
import queue
import threading
import time
import urllib.parse
import urllib.request
from thermal_sample import StopSampling

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*a,**k):raise StopSampling('bridge_redirect_rejected')

class PersistentHTTPS:
    """One worker owns this connection; retain TLS between event/ack requests."""
    def __init__(self):self.connection=None
    def close(self):
        if self.connection:self.connection.close();self.connection=None
    def open(self,request,timeout):
        url=urllib.parse.urlsplit(request.full_url)
        if url.scheme!='https' or url.netloc!='carrotduck.online':raise StopSampling('bridge_origin_rejected')
        # GET reads and correlated ack writes are idempotent. A dropped socket
        # may be retried once with the exact same request, never a new action.
        for attempt in range(2):
            try:
                if self.connection is None:self.connection=http.client.HTTPSConnection(url.netloc,timeout=timeout)
                self.connection.request(request.get_method(),url.path+('?' + url.query if url.query else ''),
                                        body=request.data,headers=dict(request.header_items()))
                response=self.connection.getresponse()
                if response.status!=200:
                    status=response.status;response.close();self.close()
                    raise StopSampling('bridge_http_'+str(status))
                return response
            except (socket.timeout,ConnectionError,http.client.RemoteDisconnected,http.client.CannotSendRequest):
                self.close()
                if attempt:raise

class WebLink:
    def __init__(self,user,take,token,origin='https://carrotduck.online'):
        if origin!='https://carrotduck.online':raise ValueError('unexpected_bridge_origin')
        if not token:raise ValueError('missing_session_token')
        self.user,self.take=user,take
        self.url=origin+'/api/chat/'+urllib.parse.quote(user,safe='')+'/rehearsal/body-events'
        self.token=token;self.events=queue.Queue(maxsize=4);self.jobs=queue.Queue(maxsize=4)
        self.stop=threading.Event();self.ready=threading.Event();self.error=None;self.last_ok=None
        self.opener=PersistentHTTPS()
    def request(self,body=None,after=0):
        url=self.url if body is not None else self.url+'?'+urllib.parse.urlencode({'take_id':self.take,'after':after})
        data=None if body is None else json.dumps({'take_id':self.take,**body}).encode()
        req=urllib.request.Request(url,data=data,headers={'Authorization':'Bearer '+self.token,'Content-Type':'application/json'})
        with self.opener.open(req,timeout=1.5) as response:
            raw=response.read(65537)
            if len(raw)>65536:raise StopSampling('oversize_bridge_response')
        return json.loads(raw)
    def start(self):
        self.thread=threading.Thread(target=self.worker,daemon=True);self.thread.start()
        if not self.ready.wait(3):raise StopSampling('bridge_not_ready')
        self.check()
    def worker(self):
        cursor=0
        try:
            while not self.stop.is_set():
                data=self.request(after=cursor)
                if data.get('take_id')!=self.take or data.get('mode')!='receipts_only':raise StopSampling('invalid_bridge_session')
                for e in data['events']:
                    if type(e.get('sequence')) is not int or e['sequence']!=cursor+1:raise StopSampling('bridge_event_sequence')
                    self.events.put_nowait(e);cursor=e['sequence']
                self.last_ok=time.monotonic();self.ready.set()
                try:
                    body,ticket=self.jobs.get(timeout=.5)
                except queue.Empty:continue
                camera_commit=body.get('command')=='commit'
                ack=self.request(body if camera_commit else {'command':'ack',**body})
                keys=('event','source') if camera_commit else ('action_id','step','status')
                if any(ack.get(k)!=body.get(k) for k in keys) or ack.get('take_id')!=self.take:
                    raise StopSampling('invalid_device_ack')
                self.last_ok=time.monotonic()
                ticket.set()
        except Exception as error:
            # Do not log request headers, tokens, response bodies or URLs with credentials.
            self.error=str(error) if isinstance(error,StopSampling) else type(error).__name__
            self.ready.set()
        finally:
            if hasattr(self.opener,'close'):self.opener.close()
    def check(self):
        if self.error:raise StopSampling('web_link_lost:'+self.error)
        if self.last_ok is None or time.monotonic()-self.last_ok>3.5:raise StopSampling('web_link_lost:stale_success')
    def drain(self,scene):
        self.check()
        while True:
            try:e=self.events.get_nowait()
            except queue.Empty:break
            scene.accept(e,time.time()*1000)
    def report(self,body,pump):
        self.check();ticket=threading.Event();self.jobs.put_nowait((body,ticket))
        began=time.monotonic()
        while not ticket.is_set():
            self.check()
            if time.monotonic()-began>3:raise StopSampling('device_receipt_ack_timeout')
            pump()
    def withdrawn(self,evidence):
        self.check()
        self.jobs.put_nowait(({'command':'commit','event':'hand_withdrawn',**evidence},threading.Event()))
    def close(self):
        self.stop.set()
        if hasattr(self,'thread'):self.thread.join(timeout=2)

class LocalLink:
    """Supervised arms test only; cannot substitute web events into full mode."""
    def check(self):pass
    def drain(self,scene):pass
    def report(self,body,pump):pass
    def close(self):pass
