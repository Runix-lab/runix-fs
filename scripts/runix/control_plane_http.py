"""WSGI registration/account API; no production SSO or cluster provisioner.

All authenticated routes require a signed access token. Deployment/readiness
and browser account setup are deliberately incomplete; see control-plane-http.md.
"""

import argparse
import json
import logging
from datetime import datetime, timezone
from http import HTTPStatus
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from wsgiref.simple_server import WSGIRequestHandler, make_server

import boto3

from control_plane_auth import AccessTokenVerifier
from control_plane_errors import HttpError
from marketplace_adapter import MarketplaceDenied, MarketplaceUnavailable, RegistrationGateway
from marketplace_metering import MeteringConflict, MeteringOutbox
from marketplace_registration import RegistrationRegistry


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


def reject_constant(_value):
    raise ValueError('Invalid JSON constant')


class ControlPlaneApp:
    ROUTES = {
        '/marketplace/register': 'POST', '/api/marketplace/bind': 'POST',
        '/api/fs/organizations': 'GET', '/api/fs/purchases': 'GET',
        '/health/live': 'GET', '/health/ready': 'GET',
    }

    def __init__(self, database, seller_account, product_code, verifier, public_origin, gateway=None):
        if not isinstance(verifier, AccessTokenVerifier):
            raise ValueError('Configured signature verifier required')
        origin = urlsplit(public_origin)
        if (not origin.hostname or origin.username or origin.password or origin.query or origin.fragment
                or origin.path not in ('', '/') or origin.scheme not in {'http', 'https'}):
            raise ValueError('Fixed public origin required')
        if origin.scheme == 'http' and origin.hostname not in {'127.0.0.1', '::1', 'localhost'}:
            raise ValueError('Cleartext is allowed only for explicit local loopback tests')
        _ = origin.port  # Validate the configured port before serving any requests.
        if not Path(database).is_absolute():
            raise ValueError('Fixed absolute database path required')
        if gateway is not None and (gateway.seller_account != seller_account or gateway.product_code != product_code):
            raise ValueError('Registration seller/product mismatch')
        self.database, self.seller_account, self.product_code = database, seller_account, product_code
        self.verifier, self.gateway = verifier, gateway
        self.origin, self.host, self.scheme = public_origin.rstrip('/'), origin.netloc.lower(), origin.scheme

    def _transport(self, environ):
        if environ.get('HTTP_HOST', '').lower() != self.host:
            raise HttpError(421, 'wrong_host')
        if environ.get('wsgi.url_scheme') != self.scheme:
            raise HttpError(426, 'tls_required')
        if self.scheme == 'http' and environ.get('REMOTE_ADDR') not in {'127.0.0.1', '::1'}:
            raise HttpError(426, 'loopback_required')
        if environ.get('PATH_INFO', '').startswith('/api/'):
            origin = environ.get('HTTP_ORIGIN')
            if origin is not None and origin != self.origin:
                raise HttpError(403, 'foreign_origin')

    def _principal(self, environ, now):
        header = environ.get('HTTP_AUTHORIZATION', '')
        parts = header.split(' ')
        if len(parts) != 2 or parts[0].lower() != 'bearer' or not parts[1]:
            raise HttpError(401, 'authentication_required')
        try:
            return self.verifier.verify(parts[1], now)
        except MarketplaceDenied:
            raise HttpError(401, 'authentication_required') from None

    @staticmethod
    def _body(environ, expected_type, maximum):
        if environ.get('HTTP_TRANSFER_ENCODING'):
            raise HttpError(400, 'unsupported_transfer_encoding')
        content_type = environ.get('CONTENT_TYPE', '').lower().split(';')
        if content_type[0].strip() != expected_type:
            raise HttpError(415, 'unsupported_content_type')
        if len(content_type) > 2 or (len(content_type) == 2 and content_type[1].strip() not in {'charset=utf-8', 'charset="utf-8"'}):
            raise HttpError(415, 'unsupported_charset')
        length = environ.get('CONTENT_LENGTH', '')
        if not length:
            raise HttpError(411, 'content_length_required')
        if not isinstance(length, str) or not length.isascii() or not length.isdigit():
            raise HttpError(400, 'invalid_content_length')
        if len(length) > 10 or int(length) > maximum:
            raise HttpError(413, 'request_too_large')
        data = environ['wsgi.input'].read(int(length))
        if len(data) != int(length):
            raise HttpError(400, 'incomplete_body')
        try:
            return data.decode('utf-8')
        except UnicodeError:
            raise HttpError(400, 'invalid_utf8') from None

    def _handle(self, environ, now):
        self._transport(environ)
        path, method = environ.get('PATH_INFO', ''), environ.get('REQUEST_METHOD', '')
        if path not in self.ROUTES:
            raise HttpError(404, 'not_found')
        if method != self.ROUTES[path]:
            raise HttpError(405, 'method_not_allowed')
        if path == '/health/live':
            return 200, {'status': 'running'}
        if path == '/health/ready':
            return 503, {'status': 'not_ready', 'reason': 'delivery_not_configured'}
        principal = self._principal(environ, now) if path.startswith('/api/') else None
        if path == '/marketplace/register':
            body = self._body(environ, 'application/x-www-form-urlencoded', 32768)
            fields = parse_qs(body, keep_blank_values=True, strict_parsing=True, encoding='utf-8', errors='strict', max_num_fields=8)
            if (set(fields) != {'x-amzn-marketplace-token'} or len(fields['x-amzn-marketplace-token']) != 1
                    or not fields['x-amzn-marketplace-token'][0].strip()):
                raise HttpError(400, 'invalid_registration_form')
            if environ.get('QUERY_STRING'):
                raise HttpError(400, 'unexpected_query')
        elif path == '/api/marketplace/bind':
            if environ.get('QUERY_STRING'):
                raise HttpError(400, 'unexpected_query')
            fields = json.loads(self._body(environ, 'application/json', 8192), object_pairs_hook=unique_object,
                                parse_constant=reject_constant)
            if not isinstance(fields, dict) or set(fields) != {'organization_id', 'claim'}:
                raise HttpError(400, 'invalid_binding_body')
        else:
            fields = parse_qs(environ.get('QUERY_STRING', ''), keep_blank_values=True, strict_parsing=True, max_num_fields=2)
            if path == '/api/fs/purchases':
                if set(fields) != {'organization_id'} or len(fields['organization_id']) != 1:
                    raise HttpError(400, 'organization_required')
            elif fields:
                raise HttpError(400, 'unexpected_query')
        box = MeteringOutbox(self.database, self.seller_account, self.product_code)
        try:
            registry = RegistrationRegistry(box, self.gateway, self.verifier.issuer)
            if path == '/marketplace/register':
                claim = registry.register(fields['x-amzn-marketplace-token'][0], now)
                return 202, {'status': 'pending_account_binding', 'claim': claim}
            if path == '/api/marketplace/bind':
                result = registry.bind(principal, fields['organization_id'], fields['claim'], now)
                return 200, {'status': result['state'], 'organization_id': result['org'], 'intent_id': result['id']}
            if path == '/api/fs/organizations':
                return 200, {'organizations': registry.list_organizations(principal, now)}
            return 200, {'purchases': registry.list_purchases(principal, fields['organization_id'][0], now)}
        finally:
            box.close()

    def __call__(self, environ, start_response):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        try:
            status, result = self._handle(environ, now)
        except HttpError as error:
            status, result = error.status, {'error': error.code}
        except MarketplaceDenied:
            status, result = 403, {'error': 'purchase_or_organization_denied'}
        except MarketplaceUnavailable:
            status, result = 503, {'error': 'marketplace_unavailable'}
        except MeteringConflict:
            status, result = 409, {'error': 'identity_or_state_conflict'}
        except (ValueError, TypeError, KeyError, UnicodeError):
            status, result = 400, {'error': 'invalid_request'}
        except Exception:
            # No exception string/trace: SDK errors can embed sensitive request data.
            status, result = 503, {'error': 'control_plane_unavailable'}
        body = json.dumps(result, separators=(',', ':')).encode('utf-8')
        headers = [('Content-Type', 'application/json; charset=utf-8'), ('Content-Length', str(len(body))),
                   ('Cache-Control', 'no-store'), ('Referrer-Policy', 'no-referrer'),
                   ('X-Content-Type-Options', 'nosniff'), ('Content-Security-Policy', "default-src 'none'; frame-ancestors 'none'")]
        if status == 401:
            headers.append(('WWW-Authenticate', 'Bearer realm="Runix FS"'))
        start_response(f'{status} {HTTPStatus(status).phrase}', headers)
        return [body]


class QuietRequestHandler(WSGIRequestHandler):
    def log_message(self, _format, *args):
        # Development runner never logs URL query strings, bodies or credentials.
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--port', type=int, default=8091)
    args = parser.parse_args()
    try:
        raw = Path(args.config).read_bytes()
        if len(raw) > 131072:
            raise ValueError('Config too large')
        config = json.loads(raw, object_pairs_hook=unique_object)
        expected = {'database', 'seller_account', 'product_code', 'issuer', 'audience', 'client_ids', 'jwks', 'public_origin'}
        if set(config) not in (expected, expected | {'browser'}) or not 1 <= args.port <= 65535:
            raise ValueError('Invalid fixed configuration')
        verifier = AccessTokenVerifier(config['issuer'], config['audience'], config['client_ids'], config['jwks'])
        for name in ('botocore', 'boto3', 'urllib3'):
            logging.getLogger(name).setLevel(logging.WARNING)
        gateway = RegistrationGateway.from_session(boto3.Session(), config['seller_account'], config['product_code'])
        app = ControlPlaneApp(config['database'], config['seller_account'], config['product_code'], verifier,
                              config['public_origin'], gateway)
        if 'browser' in config:
            from control_plane_browser import from_config
            app = from_config(app, config['browser'])
        with make_server('127.0.0.1', args.port, app, handler_class=QuietRequestHandler) as server:
            print('Local control-plane API listening on loopback; commercial delivery is not ready.', flush=True)
            server.serve_forever()
    except (ValueError, OSError, MarketplaceDenied, MarketplaceUnavailable):
        raise SystemExit('Control plane not started: verified configuration/AWS identity unavailable.') from None


if __name__ == '__main__':
    main()
