import json
import time
import unittest
from scene_transport import WebLink, NoRedirect, PersistentHTTPS
from unittest.mock import patch
import urllib.request
import socket
from thermal_sample import StopSampling

class TransportTests(unittest.TestCase):
    def test_persistent_connection_reused_and_redirect_rejected(self):
        class Reply:
            status=200
            def close(self):pass
        class Connection:
            def __init__(self,*a,**k):self.calls=[];self.reply=Reply()
            def request(self,*a,**k):self.calls.append((a,k))
            def getresponse(self):return self.reply
            def close(self):pass
        with patch('scene_transport.http.client.HTTPSConnection',side_effect=Connection) as factory:
            opener=PersistentHTTPS();req=urllib.request.Request('https://carrotduck.online/api/test')
            opener.open(req,1.5);opener.open(req,1.5)
            self.assertEqual(factory.call_count,1)
            self.assertEqual(len(opener.connection.calls),2)
            opener.connection.reply.status=302
            with self.assertRaisesRegex(StopSampling,'bridge_http_302'):opener.open(req,1.5)
            self.assertIsNone(opener.connection)

    def test_dropped_socket_retries_identical_ack_once(self):
        calls=[]
        class Connection:
            def __init__(self,*a,**k):pass
            def request(self,*a,**k):
                calls.append((a,k))
                if len(calls)==1:raise socket.timeout()
            def getresponse(self):
                class Reply:status=200
                return Reply()
            def close(self):pass
        req=urllib.request.Request('https://carrotduck.online/api/test',data=b'{"step":2}')
        with patch('scene_transport.http.client.HTTPSConnection',Connection):PersistentHTTPS().open(req,1.5)
        self.assertEqual(len(calls),2);self.assertEqual(calls[0],calls[1])

    def test_ack_updates_last_success_and_http_failure_has_code(self):
        link=WebLink('u','take','secret');ticket=__import__('threading').Event()
        link.jobs.put(({'action_id':'take:0','step':0,'status':'started'},ticket))
        def request(body=None,after=0):
            if body is None:return {'take_id':'take','mode':'receipts_only','events':[]}
            link.stop.set();return {**body,'take_id':'take'}
        link.request=request
        with patch('scene_transport.time.monotonic',side_effect=[1.,2.]):link.worker()
        self.assertEqual(link.last_ok,2.);self.assertTrue(ticket.is_set())
        link.error='bridge_http_409'
        with self.assertRaisesRegex(StopSampling,'web_link_lost:bridge_http_409'):link.check()
    def test_https_identity_request_and_no_redirect(self):
        link=WebLink('user/name','take','test-token');seen=[]
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,n):return b'{}'
        class Opener:
            def open(self,r,timeout):seen.append((r,timeout));return Response()
        link.opener=Opener();link.request({'command':'ack','step':0})
        req,timeout=seen[0]
        self.assertEqual(req.get_header('Authorization'),'Bearer test-token')
        self.assertIn('user%2Fname',req.full_url)
        self.assertEqual(json.loads(req.data)['take_id'],'take');self.assertEqual(timeout,1.5)
        with self.assertRaises(StopSampling):NoRedirect().redirect_request(None)
        with self.assertRaises(ValueError):WebLink('u','t','token',origin='http://other')
    def test_worker_ack_is_correlated_before_completion(self):
        for wrong in (False,True):
            link=WebLink('user','take','test-token');calls=[]
            def request(body=None,after=0):
                if body is None:return {'take_id':'take','mode':'receipts_only','events':[]}
                calls.append(body)
                return {**body,'take_id':'wrong' if wrong else 'take'}
            link.request=request
            try:
                link.start()
                body={'action_id':'take:0','step':0,'status':'started'}
                if wrong:
                    with self.assertRaises(StopSampling):link.report(body,lambda:time.sleep(.005))
                else:link.report(body,lambda:time.sleep(.005))
                self.assertEqual(calls[0]['command'],'ack')
            finally:link.close()
    def test_wrong_session_or_missing_sequence_never_ready(self):
        for data in ({'take_id':'wrong','mode':'receipts_only','events':[]},
                     {'take_id':'take','mode':'receipts_only','events':[{'sequence':2}]}):
            link=WebLink('u','take','token');link.request=lambda **kw:data
            try:
                with self.assertRaises(StopSampling):link.start()
            finally:link.close()
    def test_oversize_response_rejected(self):
        link=WebLink('u','t','token')
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,n):return b'x'*n
        class Opener:
            def open(self,*a,**k):return Response()
        link.opener=Opener()
        with self.assertRaisesRegex(StopSampling,'oversize'):link.request()

if __name__=='__main__':unittest.main()
