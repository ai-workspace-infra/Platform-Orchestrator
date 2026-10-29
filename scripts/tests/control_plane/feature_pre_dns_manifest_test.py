import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock

root=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('pre_dns',root/'.github/scripts/feature-lane/pre-dns-manifest.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class PreDnsTest(unittest.TestCase):
 def test_validates_fixed_projection_before_allowing_dns(self):
  receipt={'schema_version':'dev-feature-candidate/v2','result':'verified','stage':'sit','repository':'ai-workspace-infra/gitops','candidate_head':'a'*40,'projection':{'tagged_lane':{}}}
  validator=Mock();validator.validate_tree.return_value={'manifest_sha256':'b'*64}
  self.assertEqual(m.verify(receipt,'/candidate',validator)['manifest_sha256'],'b'*64)
  validator.validate_tree.assert_called_once_with('/candidate','a'*40,'sit',candidate=receipt['projection'])
  for key,value in [('stage','uat'),('candidate_head','not-a-sha'),('result','planned')]:
   invalid=dict(receipt,**{key:value})
   with self.assertRaises(ValueError):m.verify(invalid,'/candidate',validator)

if __name__=='__main__':unittest.main()
