"""A certificate bundle that works whether or not the antivirus is intercepting.

`AWS_CA_BUNDLE` **replaces** the trust store; it does not add to it. Pointing it at Avast's root
therefore says "trust Avast and nothing else", which is correct exactly while Avast is intercepting
and wrong the moment it is not -- then a genuine Amazon chain arrives and there is no public root left
to validate it against.

Avast does not intercept every process. Two terminals on the same machine, same code, same file: one
saw `CN=Avast Web/Mail Shield Root` and the other saw `CN=Amazon RSA 2048 M04`. The first worked and
the second failed, and the failure looked identical to the problem the setting was meant to solve.

So the bundle is the public roots **plus** the interceptor's, written once to a cache file. Both
chains then validate and it stops mattering which one turns up.
"""

import os
from pathlib import Path

import certifi

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE = PROJECT_ROOT / ".cache" / "ca-bundle.pem"

#: Extra roots to trust alongside the public ones. The name is kept because it is what botocore,
#: awscli and every piece of documentation about this problem already uses.
EXTRA_ROOTS_ENV = "AWS_CA_BUNDLE"


def extra_roots() -> Path | None:
    """The interceptor's root certificate, if one is configured and actually there."""
    configured = (os.environ.get(EXTRA_ROOTS_ENV) or "").strip()
    if not configured:
        return None
    path = Path(configured)
    return path if path.is_file() else None


def trust_bundle() -> str:
    """A PEM trusting the public roots and the interceptor's, built on demand and cached."""
    extra = extra_roots()
    if extra is None:
        return certifi.where()

    public = Path(certifi.where())
    if _is_stale(public, extra):
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_bytes(public.read_bytes() + b"\n" + extra.read_bytes())
    return str(CACHE)


def _is_stale(public: Path, extra: Path) -> bool:
    if not CACHE.is_file():
        return True
    built = CACHE.stat().st_mtime
    return public.stat().st_mtime > built or extra.stat().st_mtime > built
