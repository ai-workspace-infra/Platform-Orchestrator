import importlib.util,json,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('dns_evidence',ROOT/'.github/scripts/feature-lane/dns-evidence.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class EvidenceTest(unittest.TestCase):
 def test_all_three_matching_receipts_are_required(self):
  hosts={s:s+'.onwalk.net' for s in ('console','accounts','billing')}
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp)
   for service in hosts:
    directory=root/service;directory.mkdir()
    receipt={'result':'verified','service':service,'feature_id':'f','feature_tag':'x-f','hostname':hosts[service],'candidate_sha256':'a'*64,
             'provider_observation':{'cmdb_sha256':'b'*64,'node':'dev-k3s-v5','instance_id':'123','ip':'8.8.8.8'},
             'address':'8.8.8.8','action':'create','record_id':service}
    (directory/'receipt.json').write_text(json.dumps(receipt))
   result=m.verify(root,'f','x-f','a'*64,'b'*64,'123',hosts)
   self.assertEqual(result['tls_acceptance'],'NOT_RUN');self.assertEqual(set(result['services']),set(hosts))
   for service,field,value in [('accounts','hostname','other.onwalk.net'),('console','feature_id','other'),('billing','action','delete')]:
    path=root/service/'receipt.json'; original=path.read_text(); changed=json.loads(original);changed[field]=value;path.write_text(json.dumps(changed))
    with self.subTest(service=service,field=field),self.assertRaises(ValueError):m.verify(root,'f','x-f','a'*64,'b'*64,'123',hosts)
    path.write_text(original)
   path=root/'billing'/'receipt.json';data=json.loads(path.read_text());data['candidate_sha256']='c'*64;path.write_text(json.dumps(data))
   with self.assertRaises(ValueError):m.verify(root,'f','x-f','a'*64,'b'*64,'123',hosts)
   path.unlink()
   with self.assertRaises(ValueError):m.verify(root,'f','x-f','a'*64,'b'*64,'123',hosts)
if __name__=='__main__':unittest.main()
