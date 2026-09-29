"""Isolated local MediaPipe perception; child process can never write servos."""
import multiprocessing as mp
import queue
import time

def _capture(output,stop,device):
    cap=None;face=None;hands=None
    def publish(item):
        try:output.put_nowait(item)
        except queue.Full:
            try:output.get_nowait()
            except queue.Empty:pass
            try:output.put_nowait(item)
            except queue.Full:pass
    try:
        import cv2
        import mediapipe
        cv2.setNumThreads(1)
        cap=cv2.VideoCapture(device)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH,640);cap.set(cv2.CAP_PROP_FRAME_HEIGHT,480)
        cap.set(cv2.CAP_PROP_BUFFERSIZE,1)
        if not cap.isOpened():raise RuntimeError('camera_open_failed')
        face=mediapipe.solutions.face_detection.FaceDetection(model_selection=0,min_detection_confidence=.7)
        hands=mediapipe.solutions.hands.Hands(max_num_hands=1,model_complexity=0,min_detection_confidence=.7,min_tracking_confidence=.6)
        sequence=0
        while not stop.is_set():
            ok,frame=cap.read();captured=time.monotonic()
            if not ok:raise RuntimeError('camera_frame_failed')
            rgb=cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)
            faces=face.process(rgb).detections or []
            hand_result=hands.process(rgb).multi_hand_landmarks or []
            face_center=None;hand_center=None
            if faces:
                box=max(faces,key=lambda d:d.location_data.relative_bounding_box.width*d.location_data.relative_bounding_box.height).location_data.relative_bounding_box
                face_center=[box.xmin+box.width/2,box.ymin+box.height/2]
            if hand_result:
                lm=hand_result[0].landmark
                # Pointing gesture: index extended, middle/ring/little folded.
                def distance(a,b):return ((lm[a].x-lm[b].x)**2+(lm[a].y-lm[b].y)**2)**.5
                extended=lambda tip,pip:distance(tip,0)>distance(pip,0)*1.12
                if extended(8,6) and not any(extended(tip,pip) for tip,pip in ((12,10),(16,14),(20,18))):
                    hand_center=[lm[8].x,lm[8].y]
            sequence+=1
            publish({'sequence':sequence,'time':captured,'face':face_center,'hand':hand_center,'hand_present':bool(hand_result),'inference_ms':round((time.monotonic()-captured)*1000)})
    except Exception as error:publish({'error':type(error).__name__})
    finally:
        if face:face.close()
        if hands:hands.close()
        if cap is not None:cap.release()

class CameraObservations:
    def __init__(self,device=0):
        context=mp.get_context('spawn');self.output=context.Queue(maxsize=1);self.stop=context.Event()
        self.process=context.Process(target=_capture,args=(self.output,self.stop,device),daemon=True)
        self.latest=None
    def start(self):self.process.start()
    def read(self):
        while True:
            try:self.latest=self.output.get_nowait()
            except queue.Empty:return self.latest
    def close(self):
        self.stop.set()
        if self.process.pid:
            self.process.join(timeout=.5)
            if self.process.is_alive():self.process.terminate();self.process.join(timeout=.5)
        self.output.close()

if __name__=='__main__':
    import argparse,json
    parser=argparse.ArgumentParser(description='Local camera observations only; never opens serial or moves the robot.')
    parser.add_argument('--observe',action='store_true');parser.add_argument('--device',type=int,default=0)
    args=parser.parse_args()
    if not args.observe:parser.print_help()
    else:
        camera=CameraObservations(args.device);camera.start();end=time.monotonic()+12;seen=-1
        try:
            while time.monotonic()<end:
                observation=camera.read()
                if observation and observation.get('error'):print(json.dumps(observation));break
                if observation and observation['sequence']!=seen:
                    seen=observation['sequence'];print(json.dumps(observation),flush=True)
                time.sleep(.05)
        finally:camera.close()
