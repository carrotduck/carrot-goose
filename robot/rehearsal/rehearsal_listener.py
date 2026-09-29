"""Wait for an authenticated, freshly claimed webpage Start. No idle servo access."""
import fcntl,json,os,signal,subprocess,sys,time,urllib.request
from pathlib import Path

HERE=Path(__file__).resolve().parent
def main():
    lock=open('/home/pi/yushi/web-launcher.lock','a')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    session=json.loads(Path('/home/pi/yushi/.scene-session.json').read_text())
    endpoint='https://carrotduck.online/api/chat/'+session['user_id']+'/rehearsal/body-events'
    def request(body):
        req=urllib.request.Request(endpoint,data=json.dumps(body).encode(),headers={
            'Authorization':'Bearer '+session['token'],'Content-Type':'application/json'})
        # Same fixed origin as the existing authenticated rehearsal link.
        from scene_transport import NoRedirect
        with urllib.request.build_opener(NoRedirect()).open(req,timeout=5) as response:return json.load(response)
    child=None
    def stop(*_):
        if child and child.poll() is None:child.terminate();child.wait(timeout=8)
        raise SystemExit(0)
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    while True:
        try:
            take=request({'command':'executor_poll'}).get('take_id')
            if not take:time.sleep(1);continue
            import re
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',take):raise ValueError('invalid_take')
            request({'command':'executor_result','take_id':take,'status':'running'})
            env=dict(os.environ,CARROTDUCK_SESSION_TOKEN=session['token'],PYTHONPATH='/home/pi/.local/lib/python3.11/site-packages')
            args=[sys.executable,str(HERE/'run_scene_take.py'),'--run','--mode','full','--commission-candidates',
                  '--preset-gaze','--body-sway','--temperature-profile','recording',
                  '--user-id',session['user_id'],'--take-id',take]
            reason='执行器未完成';completed=False;temperature_warning={}
            child=subprocess.Popen(args,env=env,cwd=HERE,stdout=subprocess.PIPE,stderr=None,text=True)
            for line in child.stdout:
                try:row=json.loads(line)
                except ValueError:continue
                if row.get('kind')=='full_take_complete':completed=True;temperature_warning=row.get('temperature_warning',{})
                if row.get('kind') in ('take_failed','take_ended_at_idle'):reason=row.get('reason','执行已结束')
                if row.get('kind') in ('take_failed','full_take_complete','take_ended_at_idle'):print(json.dumps(row),flush=True)
            code=child.wait();child=None
            message='已完成并回位'
            if temperature_warning:message+='；本轮温度曾达'+str(max(temperature_warning.values()))+'°C，请关机散热后再开始下一轮'
            request({'command':'executor_result','take_id':take,'status':'completed' if completed and code==0 else 'ended' if code==0 else 'failed','message':reason if not completed else message})
        except Exception as e:
            # Never log credentials or HTTP request objects; no replay after claim.
            print(json.dumps({'listener_error':type(e).__name__}),flush=True);time.sleep(2)

if __name__=='__main__':main()
