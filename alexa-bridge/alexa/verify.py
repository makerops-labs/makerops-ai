"""Amazon Alexa request verification: signature, timestamp, and Application
ID. Hand-rolled rather than using ask-sdk-webservice-support's
RequestVerifier: that library's certificate-chain validation depends on
`certvalidator` -> `oscrypto`, and oscrypto has a long-standing unfixed bug
parsing OpenSSL 3.x version strings with a two-digit patch number (e.g.
"3.0.13", ubiquitous on any current Debian/Ubuntu base including this
service's own python:3.12-slim image) — confirmed locally: it raises
LibraryNotFoundError at import time, before a single request is ever
verified. This reimplements Amazon's documented algorithm
(https://developer.amazon.com/en-US/docs/alexa/custom-skills/host-a-custom-skill-as-a-web-service.html#check-request-signature)
directly with the `cryptography` library's own modern X.509 verification
API (cryptography.x509.verification, stable since 42.0), which needs no
oscrypto/certvalidator at all. The chain-of-trust + signature + timestamp
logic below was validated against a synthetic self-signed CA/leaf pair
(valid chain, tampered body, wrong hostname, untrusted root, expired cert,
and missing-SAN cases) before being written here — see docs/alexa-voice-
setup.md for how to re-verify it against a genuine Amazon-signed request
once the skill exists (the Developer Console Simulator).

Still uses ask-sdk-core/ask-sdk-model for RequestEnvelope deserialization
only (DefaultSerializer) — that import path never touches
ask_sdk_webservice_support and is unaffected by the oscrypto issue above.

Signature verification needs the RAW, byte-exact request body — main.py
reads it before any JSON parsing touches it; even a byte-identical
reserialization with different key order would break the signature for
reasons unrelated to real tampering."""

import base64
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from urllib.request import urlopen

import certifi
from ask_sdk_core.exceptions import SerializationException
from ask_sdk_core.serialize import DefaultSerializer
from ask_sdk_model import RequestEnvelope
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.padding import PKCS1v15
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.x509.verification import (Criticality, ExtensionPolicy,
                                             PolicyBuilder, Store,
                                             VerificationError)

from . import config

_serializer = DefaultSerializer()

# Header names and cert-URL requirements per Amazon's documented algorithm
# (see module docstring link) — the modern signature header is
# "Signature-256" (SHA-256), not the older SHA-1 "Signature" header.
_SIGNATURE_CERT_CHAIN_URL_HEADER = "signaturecertchainurl"
_SIGNATURE_HEADER = "signature-256"
_CERT_CHAIN_URL_SCHEME = "https"
_CERT_CHAIN_URL_HOSTNAME = "s3.amazonaws.com"
_CERT_CHAIN_URL_PATH_PREFIX = "/echo.api/"
_CERT_CHAIN_URL_PORT = 443
_CERT_CHAIN_DOMAIN = "echo-api.amazon.com"
_TIMESTAMP_TOLERANCE = timedelta(milliseconds=150000)

# Trust anchors for chain validation: the standard public CA bundle
# (certifi), same default certvalidator/most TLS stacks use. Loaded once —
# ~120 certs, sub-millisecond to parse, no need to reload per request.
_trust_store = Store(x509.load_pem_x509_certificates(
    open(certifi.where(), "rb").read()))

# Requires SAN to be present (Amazon's documented check) but does NOT
# require the TLS-specific serverAuth EKU webpki_defaults_ee() would
# enforce — Amazon's signing cert is a message-signing cert, not a TLS
# server cert, so demanding that EKU would incorrectly reject it.
_EE_EXTENSION_POLICY = ExtensionPolicy.permit_all().require_present(
    x509.SubjectAlternativeName, Criticality.AGNOSTIC, None)

# cert chain URL -> (leaf cert, [intermediate certs]); Amazon rotates this
# rarely and a rotation simply appears as a new URL, naturally busting the
# cache without needing an explicit TTL (mirrors ask-sdk-webservice-
# support's own unbounded per-process cache).
_cert_chain_cache: dict[str, tuple] = {}


class VerifyError(Exception):
    """Raised for any verification failure — malformed body, bad cert-chain
    URL, untrusted/expired/wrong-hostname certificate, bad signature, stale
    timestamp, or an Application ID that doesn't match this skill."""


def verify_request(headers: dict, raw_body: str) -> RequestEnvelope:
    """Verifies an incoming Alexa request and returns its deserialized
    RequestEnvelope. Raises VerifyError on any failure. In DEV_MODE,
    signature/timestamp checks are skipped for local curl testing — the
    Application ID check still runs if configured (see config.py). This
    does synchronous network I/O (cert chain fetch, cache misses only) and
    RSA verification — call it via run_in_threadpool from the async route
    handler rather than awaiting it directly."""
    try:
        request_envelope = _serializer.deserialize(
            payload=raw_body, obj_type=RequestEnvelope)
    except SerializationException as exc:
        raise VerifyError(f"malformed request body: {exc}") from exc

    if not config.DEV_MODE:
        _verify_signature(headers, raw_body)
        _verify_timestamp(request_envelope)

    _verify_application_id(request_envelope)
    return request_envelope


def _header(headers: dict, name: str) -> str | None:
    for key, value in headers.items():
        if key.lower() == name:
            return value
    return None


def _verify_signature(headers: dict, raw_body: str) -> None:
    cert_url = _header(headers, _SIGNATURE_CERT_CHAIN_URL_HEADER)
    signature_b64 = _header(headers, _SIGNATURE_HEADER)
    if not cert_url or not signature_b64:
        raise VerifyError("missing SignatureCertChainUrl/Signature-256 header")

    leaf_cert, intermediates = _load_cert_chain(cert_url)

    try:
        decoded_signature = base64.b64decode(signature_b64)
    except (ValueError, TypeError) as exc:
        raise VerifyError(f"malformed signature encoding: {exc}") from exc

    try:
        leaf_cert.public_key().verify(
            decoded_signature, raw_body.encode("utf-8"),
            PKCS1v15(), SHA256())
    except InvalidSignature as exc:
        raise VerifyError("request body signature is invalid") from exc


def _load_cert_chain(cert_url: str) -> tuple:
    """Validates the cert chain URL per Amazon's documented requirements,
    downloads and parses the PEM chain (cached by URL), validates the
    chain trusts back to a public root AND that its SAN covers
    echo-api.amazon.com, and returns (leaf_cert, [intermediate_certs])."""
    cached = _cert_chain_cache.get(cert_url)
    if cached is not None:
        return cached

    parsed = urlparse(cert_url)
    if (parsed.scheme or "").lower() != _CERT_CHAIN_URL_SCHEME:
        raise VerifyError(f"cert chain URL has invalid scheme: {parsed.scheme!r}")
    if (parsed.hostname or "").lower() != _CERT_CHAIN_URL_HOSTNAME:
        raise VerifyError(f"cert chain URL has invalid host: {parsed.hostname!r}")
    if not parsed.path.startswith(_CERT_CHAIN_URL_PATH_PREFIX):
        raise VerifyError(f"cert chain URL has invalid path: {parsed.path!r}")
    if parsed.port is not None and parsed.port != _CERT_CHAIN_URL_PORT:
        raise VerifyError(f"cert chain URL has invalid port: {parsed.port!r}")

    try:
        with urlopen(cert_url, timeout=10) as resp:
            pem_bytes = resp.read()
    except OSError as exc:
        raise VerifyError(f"could not fetch cert chain: {exc}") from exc

    try:
        certs = x509.load_pem_x509_certificates(pem_bytes)
    except ValueError as exc:
        raise VerifyError(f"cert chain did not parse: {exc}") from exc
    if not certs:
        raise VerifyError("cert chain URL returned no certificates")
    leaf_cert, intermediates = certs[0], certs[1:]

    verifier = (PolicyBuilder().store(_trust_store)
               .extension_policies(ca_policy=ExtensionPolicy.webpki_defaults_ca(),
                                   ee_policy=_EE_EXTENSION_POLICY)
               .build_server_verifier(x509.DNSName(_CERT_CHAIN_DOMAIN)))
    try:
        verifier.verify(leaf_cert, intermediates)
    except VerificationError as exc:
        raise VerifyError(f"cert chain did not validate: {exc}") from exc

    _cert_chain_cache[cert_url] = (leaf_cert, intermediates)
    return leaf_cert, intermediates


def _verify_timestamp(request_envelope: RequestEnvelope) -> None:
    request = request_envelope.request
    if request is None or request.timestamp is None:
        raise VerifyError("request has no timestamp")
    timestamp = request.timestamp
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    if abs(datetime.now(timezone.utc) - timestamp) > _TIMESTAMP_TOLERANCE:
        raise VerifyError("request timestamp is outside the allowed tolerance "
                          "(replay or clock skew)")


def _verify_application_id(request_envelope: RequestEnvelope) -> None:
    """Amazon's signature only proves a request came from SOME Alexa skill,
    not specifically this one — this is the check that actually scopes the
    endpoint to this skill, and the main defense if the URL ever leaks."""
    if not config.ALEXA_SKILL_APPLICATION_ID:
        return  # not configured yet (e.g. before the skill exists) — allowed

    application_id = None
    context = request_envelope.context
    if (context is not None and context.system is not None
            and context.system.application is not None):
        application_id = context.system.application.application_id
    if application_id is None and request_envelope.session is not None:
        session_app = request_envelope.session.application
        if session_app is not None:
            application_id = session_app.application_id

    if application_id != config.ALEXA_SKILL_APPLICATION_ID:
        raise VerifyError(f"Application ID mismatch (got {application_id!r})")
