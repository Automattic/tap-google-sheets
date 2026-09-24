import json
import os
import pickle
import random
import time

import googleapiclient.discovery
import singer
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.errors import HttpError
from singer import metrics
from singer import utils

LOGGER = singer.get_logger()

# Number of retries handed to googleapiclient's HttpRequest.execute(). The client
# retries with a randomized exponential backoff (sleep = random() * 2 ** attempt)
# on 5xx and 429 responses, 403 rate-limit responses, socket timeouts, SSL errors,
# connection errors and DNS failures.
NUM_RETRIES = 7

# Google enforces the Sheets read quota ("Read requests per minute per user") over
# a 60 seconds window, and every retry counts against it. googleapiclient's
# randomized backoff regularly spends all NUM_RETRIES inside that same window
# (observed totals: ~50s and ~80s), so once it gives up on a 429 we wait a full
# window out explicitly, with a little jitter, before trying again.
RATE_LIMIT_WINDOW_SECONDS = 60
RATE_LIMIT_MAX_JITTER_SECONDS = 5
RATE_LIMIT_MAX_WAITS = 3
HTTP_TOO_MANY_REQUESTS = 429

# Read requests per minute allowed to this client. Google's limit is 60 per user
# per minute; keep headroom for retries and anything else using the same account.
REQUESTS_PER_MINUTE = 50


class GoogleError(Exception):
    pass


class GoogleBadRequestError(GoogleError):
    pass


class GoogleUnauthorizedError(GoogleError):
    pass


class GooglePaymentRequiredError(GoogleError):
    pass


class GoogleNotFoundError(GoogleError):
    pass


class GoogleMethodNotAllowedError(GoogleError):
    pass


class GoogleConflictError(GoogleError):
    pass


class GoogleGoneError(GoogleError):
    pass


class GooglePreconditionFailedError(GoogleError):
    pass


class GoogleRequestEntityTooLargeError(GoogleError):
    pass


class GoogleRequestedRangeNotSatisfiableError(GoogleError):
    pass


class GoogleExpectationFailedError(GoogleError):
    pass


class GoogleForbiddenError(GoogleError):
    pass


class GoogleUnprocessableEntityError(GoogleError):
    pass


class GooglePreconditionRequiredError(GoogleError):
    pass


class GoogleInternalServiceError(GoogleError):
    pass


# Error Codes: https://developers.google.com/webmaster-tools/search-console-api-original/v3/errors
ERROR_CODE_EXCEPTION_MAPPING = {
    400: GoogleBadRequestError,
    401: GoogleUnauthorizedError,
    402: GooglePaymentRequiredError,
    403: GoogleForbiddenError,
    404: GoogleNotFoundError,
    405: GoogleMethodNotAllowedError,
    409: GoogleConflictError,
    410: GoogleGoneError,
    412: GooglePreconditionFailedError,
    413: GoogleRequestEntityTooLargeError,
    416: GoogleRequestedRangeNotSatisfiableError,
    417: GoogleExpectationFailedError,
    422: GoogleUnprocessableEntityError,
    428: GooglePreconditionRequiredError,
    500: GoogleInternalServiceError}

class GoogleClient: # pylint: disable=too-many-instance-attributes
    SCOPES = [
        "https://www.googleapis.com/auth/drive.metadata.readonly",
        "https://www.googleapis.com/auth/spreadsheets.readonly"
    ]

    def __init__(self, credentials_file):
        self.__credentials = self.fetchCredentials(credentials_file)
        self.__sheets_service = googleapiclient.discovery.build(
            'sheets',
            'v4',
            credentials=self.__credentials,
            cache_discovery=False
        )
        self.__drive_service = googleapiclient.discovery.build(
            'drive',
            'v3',
            credentials=self.__credentials,
            cache_discovery=False
        )

    def fetchCredentials(self, credentials_file):
        LOGGER.debug('authenticate with google')
        data = None

        # Check a credentials file exist
        if not os.path.exists(credentials_file):
            raise Exception("The configured Google credentials file {} doesn't exist".format(credentials_file))

        # Load credentials json file
        with open(credentials_file) as json_file:
            data = json.load(json_file)

        if data.get('type', '') == 'service_account':
            return self.fetchServiceAccountCredentials(credentials_file)
        elif data.get('installed'):
            return self.fetchInstalledOAuthCredentials(credentials_file)
        else:
            raise Exception("""This Google credentials file is not yet recognize.

            Please use either:
            - a Service Account (https://github.com/googleapis/google-api-python-client/blob/d0110cf4f7aaa93d6f56fc028cd6a1e3d8dd300a/docs/oauth-server.md)
            - an installed OAuth client (https://github.com/googleapis/google-api-python-client/blob/d0110cf4f7aaa93d6f56fc028cd6a1e3d8dd300a/docs/oauth-installed.md)"""
            )

    def fetchServiceAccountCredentials(self, credentials_file):
        # The service account credentials file can be used for server-to-server applications
        return service_account.Credentials.from_service_account_file(
            credentials_file, scopes=GoogleClient.SCOPES)

    def fetchInstalledOAuthCredentials(self, credentials_file):
        creds = None

        # The file token.pickle stores the user's access and refresh tokens, and is
        # created automatically when the authorization flow completes for the first
        # time.
        if os.path.exists('token.pickle'):
            with open('token.pickle', 'rb') as token:
                creds = pickle.load(token)

        # If there are no (valid) credentials available, let the user log in.
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    credentials_file, GoogleClient.SCOPES)
                creds = flow.run_local_server(port=0)
            # Save the credentials for the next run
            with open('token.pickle', 'wb') as token:
                pickle.dump(creds, token)

        return creds

    def __enter__(self):
        return self

    def __exit__(self, exception_type, exception_value, traceback):
        LOGGER.debug('exiting google client')

    # Rate Limit: https://developers.google.com/sheets/api/limits
    #   60 request per 60 seconds per User
    @utils.ratelimit(REQUESTS_PER_MINUTE, 60)
    def request(self, endpoint=None, params={}, **kwargs):
        formatted_params = {}
        for (key, value) in params.items():
            # API parameters interpolation
            # will raise a KeyError in case a necessary argument is missing
            formatted_params[key] = value.format(**kwargs)

        # Call the correct Google API depending on the stream name
        if endpoint == 'spreadsheet_metadata' or endpoint == 'sheet_metadata':
            # https://developers.google.com/sheets/api/reference/rest/v4/spreadsheets/get
            request = self.__sheets_service.spreadsheets().get(**formatted_params)
        elif endpoint == 'sheets_loaded':
            # https://developers.google.com/sheets/api/reference/rest/v4/spreadsheets.values/get
            request = self.__sheets_service.spreadsheets().values().get(**formatted_params)
        elif endpoint == 'file_metadata':
            # https://developers.google.com/drive/api/v3/reference/files/get
            request = self.__drive_service.files().get(**formatted_params)
        else:
            raise Exception('{} not implemented yet!'.format(endpoint))

        with metrics.http_request_timer(endpoint) as timer:
            for rate_limit_waits in range(RATE_LIMIT_MAX_WAITS + 1):
                try:
                    # Retries (with backoff) are handled by googleapiclient, see NUM_RETRIES.
                    # Once retries are exhausted the last error is raised: HttpError for
                    # non-2xx responses, the original exception for transport errors.
                    response = request.execute(num_retries=NUM_RETRIES)
                    break
                except HttpError as e:
                    if e.resp.status != HTTP_TOO_MANY_REQUESTS \
                            or rate_limit_waits == RATE_LIMIT_MAX_WAITS:
                        timer.tags[metrics.Tag.http_status_code] = e.resp.status
                        raise
                    wait = RATE_LIMIT_WINDOW_SECONDS + random.uniform(0, RATE_LIMIT_MAX_JITTER_SECONDS)
                    LOGGER.warning(
                        'Rate limit (HTTP 429) still exceeded after %d retries for %s; '
                        'waiting %.1f seconds for the quota window to reset (%d of %d)',
                        NUM_RETRIES, endpoint, wait, rate_limit_waits + 1, RATE_LIMIT_MAX_WAITS)
                    time.sleep(wait)
            timer.tags[metrics.Tag.http_status_code] = 200

        return response
