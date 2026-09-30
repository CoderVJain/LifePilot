# Friction log

Problems hit while building LifePilot, in the order they happened, with the evidence and the fix.

## 1. Antivirus TLS interception breaks boto3 and awscli (Sep 29, 2026)

**Symptom.** Every AWS call fails with `CERTIFICATE_VERIFY_FAILED`, while Python's own `ssl` module
reaches the same hosts successfully.

**Cause.** Avast intercepts HTTPS and re-signs it with its own root CA. That CA is in the Windows
certificate store, which `ssl` consults, but `botocore` ships and trusts `certifi` only. So the failure
looks like a broken AWS setup rather than a local proxy.

**Fix.** Point botocore at the interceptor's root certificate:

```
AWS_CA_BUNDLE=C:\ProgramData\Avast Software\Avast\wscert.pem
```

`lifepilot_shared/llm.py` applies it so both processes inherit it.

**Feedback for AWS.** The error names the certificate but not the trust store it was checked against, and
does not mention `AWS_CA_BUNDLE`. Naming the bundle in use would turn an hour of guessing into one line.

## 2. Same interception breaks `uv sync` (Sep 30, 2026)

**Symptom.** `uv sync` fails on the first index request:
`invalid peer certificate: UnknownIssuer` for `https://pypi.org/simple/...`.

**Cause.** Identical to #1 — uv carries its own trust store and does not consult the Windows store.

**Fix.** uv's error message does suggest the flag, which is why this cost minutes rather than an hour. Made
it durable in `pyproject.toml` rather than a flag to remember:

```toml
[tool.uv]
native-tls = true
```

## 3. `uv_build` assumes a src layout and one module (Sep 30, 2026)

**Symptom.** `uv sync` fails with `Expected a Python module at: src\lifepilot\__init__.py` for a flat
layout with three top-level modules.

**Fix.** LifePilot is an application, not a distributable, so it does not need building at all. Dropped
`[build-system]` and set `package = false`. Dependencies still install.
