"""Why can this shell not reach Bedrock? Run it in the terminal that starts the simulator.

Prints only names, booleans and certificate subjects. No credential value is ever shown.

    uv run python -m scripts.check_bedrock
"""

import os
import socket
import ssl
import sys

from cryptography import x509

from lifepilot_shared.llm import PROJECT_ROOT, Turn, ca_bundle_problem, converse

ENDPOINT = "bedrock-runtime.us-east-1.amazonaws.com"

# A proxy variable changes which server answers, and so which certificate is presented. Set in one
# terminal and not another, it is invisible and decisive.
PROXY_VARS = ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "NO_PROXY", "no_proxy")
CERT_VARS = ("AWS_CA_BUNDLE", "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE")


def main() -> None:
    print(f"python      : {sys.executable}")
    print(f"working dir : {os.getcwd()}")
    print(f"project root: {PROJECT_ROOT}")
    print(f".env present: {(PROJECT_ROOT / '.env').is_file()}")

    print("\ncertificate settings in this shell")
    for name in CERT_VARS:
        value = os.environ.get(name)
        if not value:
            print(f"  {name:<20} unset")
        else:
            print(f"  {name:<20} {value}  (exists: {os.path.isfile(value)})")

    print("\nproxy settings in this shell")
    found_proxy = False
    for name in PROXY_VARS:
        value = os.environ.get(name)
        if value:
            found_proxy = True
            print(f"  {name:<20} {value}")
    if not found_proxy:
        print("  none set")

    print(f"\nca_bundle_problem(): {ca_bundle_problem() or 'none'}")

    print(f"\nwho answers for {ENDPOINT}")
    try:
        leaf = _presented_certificate()
        print(f"  issued by: {leaf.issuer.rfc4514_string()[:80]}")
        print("  intercepted:", "Avast" in leaf.issuer.rfc4514_string())
    except OSError as unreachable:
        print(f"  could not connect: {unreachable}")

    print("\nactual Bedrock call")
    try:
        converse(
            messages=[{"role": "user", "content": [{"text": "say ok"}]}],
            turn=Turn(max_calls=1),
            max_tokens=8,
        )
        print("  succeeded")
    except Exception as failure:  # noqa: BLE001 - this script exists to report whatever happens
        print(f"  failed: {type(failure).__name__}")
        print(f"  {str(failure)[:300]}")


def _presented_certificate() -> x509.Certificate:
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    with socket.create_connection((ENDPOINT, 443), timeout=15) as raw:
        with context.wrap_socket(raw, server_hostname=ENDPOINT) as tls:
            return x509.load_der_x509_certificate(tls.getpeercert(binary_form=True))


if __name__ == "__main__":
    main()
