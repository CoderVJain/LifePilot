"""The trust bundle. Offline and free: no network, no AWS.

`AWS_CA_BUNDLE` replaces the trust store rather than adding to it, so pointing it at an interceptor's
root says "trust the interceptor and nothing else". That is right exactly while the interceptor is
intercepting. Avast does not intercept every process, and the moment a genuine Amazon chain arrives
there is no public root left to validate it. These tests pin the fix: both sets of roots, always.
"""

from pathlib import Path

import certifi
import pytest
from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding

from lifepilot_shared import certs


@pytest.fixture
def fake_root(tmp_path, monkeypatch):
    """A PEM standing in for the antivirus root, so the test needs nothing installed."""
    source = Path(certifi.where()).read_bytes()
    first = x509.load_pem_x509_certificates(source)[0]
    root = tmp_path / "interceptor.pem"
    root.write_bytes(first.public_bytes(encoding=Encoding.PEM))
    monkeypatch.setenv(certs.EXTRA_ROOTS_ENV, str(root))
    monkeypatch.setattr(certs, "CACHE", tmp_path / ".cache" / "ca-bundle.pem")
    return root


def test_with_no_interceptor_configured_the_public_roots_are_used(monkeypatch):
    monkeypatch.delenv(certs.EXTRA_ROOTS_ENV, raising=False)
    assert certs.trust_bundle() == certifi.where()


def test_a_configured_file_that_is_missing_is_ignored_rather_than_breaking_everything(monkeypatch):
    """Trusting nothing is worse than trusting the usual roots."""
    monkeypatch.setenv(certs.EXTRA_ROOTS_ENV, "C:/does/not/exist.pem")
    assert certs.trust_bundle() == certifi.where()


def test_the_bundle_contains_the_public_roots_and_the_interceptor(fake_root):
    bundle = Path(certs.trust_bundle())
    assert bundle != Path(certifi.where())

    public_count = len(x509.load_pem_x509_certificates(Path(certifi.where()).read_bytes()))
    combined = x509.load_pem_x509_certificates(bundle.read_bytes())

    assert len(combined) == public_count + 1, "every public root, plus the one extra"
    assert combined[-1].subject == x509.load_pem_x509_certificates(fake_root.read_bytes())[0].subject


def test_the_bundle_is_rebuilt_when_the_interceptor_changes(fake_root):
    bundle = Path(certs.trust_bundle())
    before = bundle.read_bytes()

    source = Path(certifi.where()).read_bytes()
    different = x509.load_pem_x509_certificates(source)[1]
    fake_root.write_bytes(different.public_bytes(encoding=Encoding.PEM))
    # Make the change unambiguously newer than the cache on filesystems with coarse timestamps.
    import os
    import time

    os.utime(fake_root, (time.time() + 10, time.time() + 10))

    assert Path(certs.trust_bundle()).read_bytes() != before


def test_building_it_twice_does_not_rewrite_it(fake_root):
    first = Path(certs.trust_bundle())
    stamp = first.stat().st_mtime_ns
    assert Path(certs.trust_bundle()).stat().st_mtime_ns == stamp
