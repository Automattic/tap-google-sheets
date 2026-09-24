import json
import socket
import ssl
import unittest
from unittest import mock

import googleapiclient.discovery
import httplib2
from googleapiclient.errors import HttpError

from tap_google_sheets import client as client_module
from tap_google_sheets.client import (
    GoogleClient, NUM_RETRIES, RATE_LIMIT_MAX_JITTER_SECONDS, RATE_LIMIT_MAX_WAITS,
    RATE_LIMIT_WINDOW_SECONDS)


class FakeHttp:
    """Minimal httplib2.Http stand-in returning a scripted sequence of outcomes.

    Each item is either an exception instance (raised by ``request``) or a tuple
    ``(status, body)`` returned as ``(httplib2.Response, bytes)``.
    """

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def request(self, uri, method='GET', body=None, headers=None, **kwargs):  # pylint: disable=unused-argument
        self.calls.append((method, uri))
        if not self.outcomes:
            raise AssertionError('FakeHttp: more requests made than outcomes scripted')
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        status, payload = outcome
        content = payload if isinstance(payload, bytes) else json.dumps(payload).encode('utf-8')
        return httplib2.Response({'status': status, 'content-type': 'application/json'}), content


OK_BODY = {'values': [['a', 'b']]}
FILE_BODY = {'id': 'file-id', 'name': 'sheet'}


def error_body(status, reason, message='error'):
    return {'error': {'code': status, 'message': message,
                      'errors': [{'reason': reason, 'message': message}]}}


class TestClientRetry(unittest.TestCase):
    """Verifies googleapiclient's built-in retry (``num_retries``) covers every case
    the previous ``@backoff`` decorator handled (5xx, 429, ConnectionError, TimeoutError)
    plus the ones only googleapiclient handles (SSL errors, DNS failures, 403 rate limits).
    """

    def setUp(self):
        # HttpRequest binds time.sleep at construction time, so patch before building requests.
        sleep_patcher = mock.patch('time.sleep')
        self.sleep = sleep_patcher.start()
        self.addCleanup(sleep_patcher.stop)
        # googleapiclient sleeps random() * 2 ** attempt (up to 128s at attempt 7); pin it
        # to 0 so quota-window waits (>= 60s) are distinguishable from backoff sleeps.
        random_patcher = mock.patch('random.random', return_value=0.0)
        random_patcher.start()
        self.addCleanup(random_patcher.stop)

    def make_client(self, sheets_outcomes=(), drive_outcomes=()):
        self.sheets_http = FakeHttp(sheets_outcomes)
        self.drive_http = FakeHttp(drive_outcomes)
        client = GoogleClient.__new__(GoogleClient)
        # Static discovery docs ship with googleapiclient, so build() makes no network call.
        client._GoogleClient__sheets_service = googleapiclient.discovery.build(
            'sheets', 'v4', http=self.sheets_http, static_discovery=True)
        client._GoogleClient__drive_service = googleapiclient.discovery.build(
            'drive', 'v3', http=self.drive_http, static_discovery=True)
        return client

    def request_sheet_values(self, client):
        return client.request(
            endpoint='sheets_loaded',
            params={'spreadsheetId': '{spreadsheet_id}', 'range': "'{sheet_title}'!{range_rows}"},
            spreadsheet_id='sheet-id', sheet_title='Sheet1', range_rows='1:10')

    def request_file_metadata(self, client):
        return client.request(
            endpoint='file_metadata',
            params={'fileId': '{spreadsheet_id}', 'fields': 'id,name'},
            spreadsheet_id='sheet-id')

    # --- Cases previously handled by the @backoff decorator ---------------------------------

    def test_success_without_retry(self):
        client = self.make_client(sheets_outcomes=[(200, OK_BODY)])
        self.assertEqual(self.request_sheet_values(client), OK_BODY)
        self.assertEqual(len(self.sheets_http.calls), 1)
        self.sleep.assert_not_called()

    def test_retries_on_5xx(self):
        client = self.make_client(sheets_outcomes=[
            (500, error_body(500, 'backendError')),
            (503, error_body(503, 'backendError')),
            (200, OK_BODY),
        ])
        self.assertEqual(self.request_sheet_values(client), OK_BODY)
        self.assertEqual(len(self.sheets_http.calls), 3)
        self.assertEqual(self.sleep.call_count, 2)

    def test_retries_on_429(self):
        client = self.make_client(sheets_outcomes=[
            (429, error_body(429, 'rateLimitExceeded')),
            (200, OK_BODY),
        ])
        self.assertEqual(self.request_sheet_values(client), OK_BODY)
        self.assertEqual(len(self.sheets_http.calls), 2)
        self.assertEqual(self.sleep.call_count, 1)

    def test_retries_on_connection_error(self):
        client = self.make_client(sheets_outcomes=[
            ConnectionResetError(104, 'Connection reset by peer'),
            ConnectionRefusedError(111, 'Connection refused'),
            (200, OK_BODY),
        ])
        self.assertEqual(self.request_sheet_values(client), OK_BODY)
        self.assertEqual(len(self.sheets_http.calls), 3)

    def test_retries_on_read_timeout(self):
        # httplib2 surfaces read timeouts as socket.timeout (== TimeoutError on Python 3.10+)
        client = self.make_client(sheets_outcomes=[
            socket.timeout('The read operation timed out'),
            TimeoutError('timed out'),
            (200, OK_BODY),
        ])
        self.assertEqual(self.request_sheet_values(client), OK_BODY)
        self.assertEqual(len(self.sheets_http.calls), 3)

    # --- Cases only handled by googleapiclient ---------------------------------------------

    def test_retries_on_ssl_error(self):
        client = self.make_client(sheets_outcomes=[
            ssl.SSLError('EOF occurred in violation of protocol'),
            (200, OK_BODY),
        ])
        self.assertEqual(self.request_sheet_values(client), OK_BODY)
        self.assertEqual(len(self.sheets_http.calls), 2)

    def test_retries_on_dns_failure(self):
        client = self.make_client(sheets_outcomes=[
            httplib2.ServerNotFoundError('Unable to find the server at sheets.googleapis.com'),
            (200, OK_BODY),
        ])
        self.assertEqual(self.request_sheet_values(client), OK_BODY)
        self.assertEqual(len(self.sheets_http.calls), 2)

    def test_retries_on_403_rate_limit(self):
        # Drive API reports quota exhaustion as 403 userRateLimitExceeded rather than 429
        client = self.make_client(drive_outcomes=[
            (403, error_body(403, 'userRateLimitExceeded')),
            (403, error_body(403, 'rateLimitExceeded')),
            (200, FILE_BODY),
        ])
        self.assertEqual(self.request_file_metadata(client), FILE_BODY)
        self.assertEqual(len(self.drive_http.calls), 3)

    # --- Non-retryable outcomes -----------------------------------------------------------

    def test_403_without_rate_limit_reason_is_not_retried(self):
        client = self.make_client(drive_outcomes=[(403, error_body(403, 'forbidden'))])
        with self.assertRaises(HttpError) as ctx:
            self.request_file_metadata(client)
        self.assertEqual(ctx.exception.resp.status, 403)
        self.assertEqual(len(self.drive_http.calls), 1)
        self.sleep.assert_not_called()

    def test_4xx_is_not_retried(self):
        client = self.make_client(sheets_outcomes=[(404, error_body(404, 'notFound'))])
        with self.assertRaises(HttpError) as ctx:
            self.request_sheet_values(client)
        self.assertEqual(ctx.exception.resp.status, 404)
        self.assertEqual(len(self.sheets_http.calls), 1)

    def test_unknown_transport_error_is_not_retried(self):
        client = self.make_client(sheets_outcomes=[ValueError('boom'), (200, OK_BODY)])
        with self.assertRaises(ValueError):
            self.request_sheet_values(client)
        self.assertEqual(len(self.sheets_http.calls), 1)

    # --- Exhaustion -----------------------------------------------------------------------

    def test_persistent_5xx_raises_after_retries_exhausted(self):
        client = self.make_client(
            sheets_outcomes=[(503, error_body(503, 'backendError'))] * (NUM_RETRIES + 1))
        with self.assertRaises(HttpError) as ctx:
            self.request_sheet_values(client)
        self.assertEqual(ctx.exception.resp.status, 503)
        self.assertEqual(len(self.sheets_http.calls), NUM_RETRIES + 1)
        self.assertEqual(self.sleep.call_count, NUM_RETRIES)

    def test_persistent_timeout_raises_after_retries_exhausted(self):
        client = self.make_client(
            sheets_outcomes=[socket.timeout('timed out')] * (NUM_RETRIES + 1))
        with self.assertRaises(socket.timeout):
            self.request_sheet_values(client)
        self.assertEqual(len(self.sheets_http.calls), NUM_RETRIES + 1)

    def test_backoff_grows_exponentially(self):
        client = self.make_client(sheets_outcomes=[
            (500, error_body(500, 'backendError')),
            (500, error_body(500, 'backendError')),
            (500, error_body(500, 'backendError')),
            (200, OK_BODY),
        ])
        with mock.patch('random.random', return_value=1.0):
            self.request_sheet_values(client)
        self.assertEqual([c.args[0] for c in self.sleep.call_args_list], [2, 4, 8])

    # --- Rate limit (429) quota window ---------------------------------------------------

    RATE_LIMITED = (429, error_body(429, 'rateLimitExceeded'))

    def quota_waits(self):
        """Sleeps long enough to be a quota-window wait rather than googleapiclient backoff."""
        return [c.args[0] for c in self.sleep.call_args_list if c.args[0] >= RATE_LIMIT_WINDOW_SECONDS]

    def test_429_waits_out_quota_window_after_retries_exhausted(self):
        client = self.make_client(
            sheets_outcomes=[self.RATE_LIMITED] * (NUM_RETRIES + 1) + [(200, OK_BODY)])
        self.assertEqual(self.request_sheet_values(client), OK_BODY)
        self.assertEqual(len(self.sheets_http.calls), NUM_RETRIES + 2)
        waits = self.quota_waits()
        self.assertEqual(len(waits), 1)
        self.assertLessEqual(waits[0], RATE_LIMIT_WINDOW_SECONDS + RATE_LIMIT_MAX_JITTER_SECONDS)

    def test_429_quota_wait_repeats_across_windows(self):
        attempts_per_window = NUM_RETRIES + 1
        client = self.make_client(
            sheets_outcomes=[self.RATE_LIMITED] * (attempts_per_window * 2) + [(200, OK_BODY)])
        self.assertEqual(self.request_sheet_values(client), OK_BODY)
        self.assertEqual(len(self.sheets_http.calls), attempts_per_window * 2 + 1)
        self.assertEqual(len(self.quota_waits()), 2)

    def test_persistent_429_raises_after_quota_waits_exhausted(self):
        attempts_per_window = NUM_RETRIES + 1
        total_attempts = attempts_per_window * (RATE_LIMIT_MAX_WAITS + 1)
        client = self.make_client(sheets_outcomes=[self.RATE_LIMITED] * total_attempts)
        with self.assertRaises(HttpError) as ctx:
            self.request_sheet_values(client)
        self.assertEqual(ctx.exception.resp.status, 429)
        self.assertEqual(len(self.sheets_http.calls), total_attempts)
        self.assertEqual(len(self.quota_waits()), RATE_LIMIT_MAX_WAITS)

    def test_non_429_error_does_not_wait_for_quota_window(self):
        client = self.make_client(
            sheets_outcomes=[(503, error_body(503, 'backendError'))] * (NUM_RETRIES + 1))
        with self.assertRaises(HttpError):
            self.request_sheet_values(client)
        self.assertEqual(self.quota_waits(), [])

    # --- Metrics --------------------------------------------------------------------------

    def test_http_status_code_metric_tag(self):
        with mock.patch.object(client_module.metrics, 'http_request_timer') as timer_factory:
            timer = timer_factory.return_value.__enter__.return_value
            timer.tags = {}

            client = self.make_client(sheets_outcomes=[(200, OK_BODY)])
            self.request_sheet_values(client)
            self.assertEqual(timer.tags[client_module.metrics.Tag.http_status_code], 200)

            client = self.make_client(sheets_outcomes=[(404, error_body(404, 'notFound'))])
            with self.assertRaises(HttpError):
                self.request_sheet_values(client)
            self.assertEqual(timer.tags[client_module.metrics.Tag.http_status_code], 404)

            client = self.make_client(
                sheets_outcomes=[self.RATE_LIMITED] * ((NUM_RETRIES + 1) * (RATE_LIMIT_MAX_WAITS + 1)))
            with self.assertRaises(HttpError):
                self.request_sheet_values(client)
            self.assertEqual(timer.tags[client_module.metrics.Tag.http_status_code], 429)
