#!/usr/bin/env python3
"""Read-only ingress reachability check before creating feature DNS."""
import datetime
import http.client
import ipaddress
import json
import os
from pathlib import Path
import re
import sys

def check(env, now, connect=http.client.HTTPConnection):
    observation=json.loads(Path(env['TARGET_OBSERVATION']).read_text())
    address=ipaddress.ip_address(observation.get('ip',''))
    observed=datetime.datetime.fromisoformat(observation.get('observed_at',''))
    host=env['CONSOLE_HOST']
    if (address.version!=4 or not address.is_global or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,62}\.onwalk\.net',host) or
        observation.get('schema')!='dev-sit-provider-observation/v1' or observation.get('result')!='MATCH' or
        observation.get('node')!='dev-k3s-v5' or observation.get('instance_id')!=env['INSTANCE_ID'] or
        observation.get('candidate_sha256')!=env['CANDIDATE_RECEIPT_SHA256'] or observation.get('cmdb_sha256')!=env['CMDB_SHA256'] or
        observed.tzinfo is None or not datetime.timedelta(0)<=now-observed<=datetime.timedelta(minutes=20)):
        raise ValueError('target observation mismatch')
    path='/.well-known/acme-challenge/owner-preflight'
    connection=connect(str(address),80,timeout=10)
    try:
        connection.request('GET',path,headers={'Host':host})
        response=connection.getresponse()
        if response.status not in (200,404,308) or (response.status==308 and response.getheader('Location')!='https://'+host+path):
            raise ValueError('ingress HTTP preflight failed')
    finally:
        connection.close()

if __name__=='__main__':
    try: check(os.environ,datetime.datetime.now(datetime.timezone.utc))
    except Exception:
        print('::error::Dev ingress preflight failed',file=sys.stderr)
        sys.exit(1)
