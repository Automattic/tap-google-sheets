import importlib
import unittest
from unittest import mock

from tap_google_sheets.schema import column_string
from tap_google_sheets.sync import DEFAULT_BATCH_ROWS, get_batch_rows, sync

# `tap_google_sheets.sync` the attribute is the sync() function (re-exported by the
# package __init__), so fetch the module itself for patching.
sync_module = importlib.import_module('tap_google_sheets.sync')


class TestGetBatchRows(unittest.TestCase):

    def test_default(self):
        self.assertEqual(get_batch_rows({}), DEFAULT_BATCH_ROWS)
        self.assertEqual(get_batch_rows({'batch_rows': None}), DEFAULT_BATCH_ROWS)

    def test_override(self):
        self.assertEqual(get_batch_rows({'batch_rows': 1000}), 1000)
        # Meltano passes settings through the environment as strings
        self.assertEqual(get_batch_rows({'batch_rows': '1000'}), 1000)

    def test_invalid(self):
        with self.assertRaises(ValueError):
            get_batch_rows({'batch_rows': 0})
        with self.assertRaises(ValueError):
            get_batch_rows({'batch_rows': 'lots'})


class TestSyncPaging(unittest.TestCase):
    """Runs sync() against a fake client and checks the ranges requested per page."""

    SHEET_TITLE = 'Decided'
    NUM_COLS = 24  # A..X

    def setUp(self):
        self.columns = [
            {'columnIndex': i, 'columnLetter': column_string(i), 'columnName': 'col_{}'.format(i),
             'columnType': 'stringValue', 'columnSkipped': False}
            for i in range(1, self.NUM_COLS + 1)
        ]
        for name in ('write_schema', 'process_records', 'write_bookmark', 'update_currently_syncing'):
            patcher = mock.patch.object(sync_module, name)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(sync_module, 'get_sheet_metadata',
                                    return_value=({'type': 'object'}, self.columns))
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(sync_module.singer, 'write_message')
        patcher.start()
        self.addCleanup(patcher.stop)

    def make_client(self, data_rows):
        """Fake GoogleClient whose sheet holds `data_rows` rows of data below the header."""
        last_data_row = data_rows + 1

        def request(endpoint=None, params=None, **kwargs):
            if endpoint == 'file_metadata':
                return {'modifiedTime': '2026-01-01T00:00:00Z'}
            if endpoint == 'spreadsheet_metadata':
                return {'sheets': [{'properties': {
                    'title': self.SHEET_TITLE, 'sheetId': 1,
                    'gridProperties': {'rowCount': self.row_count}}}]}
            if endpoint == 'sheets_loaded':
                from_row, to_row = self.parse_range(kwargs['range_rows'])
                to_row = min(to_row, last_data_row)
                return {'values': [['x'] * self.NUM_COLS for _ in range(from_row, to_row + 1)]}
            raise AssertionError('unexpected endpoint {}'.format(endpoint))

        client = mock.Mock()
        client.request.side_effect = request
        return client

    @staticmethod
    def parse_range(range_rows):
        start, end = range_rows.split(':')
        return int(start.lstrip('A')), int(end.lstrip('X'))

    def run_sync(self, config, row_count, data_rows):
        self.row_count = row_count
        client = self.make_client(data_rows)
        catalog = mock.Mock()
        catalog.get_selected_streams.return_value = [mock.Mock(stream=self.SHEET_TITLE)]
        catalog.get_stream.return_value.metadata = []
        config = {'start_date': '2000-01-01T00:00:00Z', 'spreadsheet_id': 'sheet-id'} | config
        sync(client, config, catalog, state={})
        return [c.kwargs['range_rows'] for c in client.request.call_args_list
                if c.kwargs.get('endpoint') == 'sheets_loaded']

    def test_default_batch_rows_pages_in_5000s(self):
        ranges = self.run_sync({}, row_count=10500, data_rows=10100)
        self.assertEqual(ranges, ['A2:X5000', 'A5001:X10000', 'A10001:X10500'])

    def test_batch_rows_from_config(self):
        ranges = self.run_sync({'batch_rows': 200}, row_count=450, data_rows=449)
        self.assertEqual(ranges, ['A2:X200', 'A201:X400', 'A401:X450'])

    def test_small_sheet_is_a_single_request(self):
        ranges = self.run_sync({}, row_count=1000, data_rows=999)
        self.assertEqual(ranges, ['A2:X1000'])

    def test_stops_after_first_short_page(self):
        ranges = self.run_sync({}, row_count=100000, data_rows=6000)
        self.assertEqual(ranges, ['A2:X5000', 'A5001:X10000'])
