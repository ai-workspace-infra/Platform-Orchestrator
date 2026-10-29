import datetime,importlib.util,json,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock
ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('edge',ROOT/'.github/scripts/feature-lane/edge-preflight.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class EdgeTest(unittest.TestCase):
 def test_requires_bound_target_and_exact_redirect(self):
  now=datetime.datetime.now(datetime.timezone.utc)
  row={'schema':'dev-sit-provider-observation/v1','result':'MATCH','node':'dev-k3s-v5','instance_id':'123','ip':'8.8.8.8','candidate_sha256':'a'*64,'cmdb_sha256':'b'*64,'observed_at':now.isoformat()}
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'target.json';path.write_text(json.dumps(row))
   env={'TARGET_OBSERVATION':str(path),'INSTANCE_ID':'123','CANDIDATE_RECEIPT_SHA256':'a'*64,'CMDB_SHA256':'b'*64,'CONSOLE_HOST':'smoke-sit-test-1483-sit.onwalk.net'}
   conn=Mock();conn.getresponse.return_value.status=404
   m.check(env,now,lambda *args,**kwargs:conn)
   conn.getresponse.return_value.status=308;conn.getresponse.return_value.getheader.return_value='https://wrong.example/'
   with self.assertRaises(ValueError):m.check(env,now,lambda *args,**kwargs:conn)
   path.write_text(json.dumps({**row,'candidate_sha256':'c'*64}))
   with self.assertRaises(ValueError):m.check(env,now,lambda *args,**kwargs:conn)
   for change in ({'ip':'10.0.0.1'},{'observed_at':(now-datetime.timedelta(minutes=21)).isoformat()},{'instance_id':'456'}):
    path.write_text(json.dumps({**row,**change}))
    with self.subTest(change=change),self.assertRaises(ValueError):m.check(env,now,lambda *args,**kwargs:conn)
if __name__=='__main__':unittest.main()
