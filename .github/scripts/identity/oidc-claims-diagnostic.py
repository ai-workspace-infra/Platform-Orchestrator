#!/usr/bin/env python3
"""Print selected GitHub OIDC claims without persisting or emitting the token."""
import base64
import json
import os
import urllib.request

FIELDS = ("repository", "sub", "ref", "environment", "job_workflow_ref")
try:
    request = urllib.request.Request(
        os.environ["ACTIONS_ID_TOKEN_REQUEST_URL"],
        headers={"Authorization": "Bearer " + os.environ["ACTIONS_ID_TOKEN_REQUEST_TOKEN"]},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        token = json.load(response)["value"]
    payload = token.split(".")[1]
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    result = {name: claims.get(name) for name in FIELDS}
    if not all(value is None or isinstance(value, str) for value in result.values()):
        raise ValueError("invalid claim type")
    print("Selected GitHub OIDC claims: " + json.dumps(result, ensure_ascii=True))
except Exception:
    print("::warning::OIDC claim diagnostic could not retrieve or parse selected claims")
