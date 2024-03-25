import unittest
from tap_google_sheets import schema


class TestUnsupportedFields(unittest.TestCase):
    def test_two_skipped_columns(self):
        """
        Test whether the columns has the `prior_column_skipped` key which is True as there ar 2 consecutive empty headers
        and the `sheet_json_schema` has only 3 keys
        """
        sheet = {
            "properties":{
                "sheetId":1825500887,
                "title":"Sheet11",
                "index":2,
                "sheetType":"GRID",
                "gridProperties":{
                    "rowCount":1000,
                    "columnCount":26
                }
            },
            "data":[
                {
                    "rowData":[
                        {
                        "values":[
                            {},
                            {},
                            {
                                "formattedValue":"abd",
                            }
                        ]
                        },
                        {
                        "values":[
                            {
                                "formattedValue":"1",
                            },
                            {
                                "formattedValue":"3",
                            },
                            {
                                "formattedValue":"45",
                            }
                        ]
                        }
                    ],
                    "rowMetadata":[
                        {
                        "pixelSize":21
                        }
                    ],
                    "columnMetadata":[
                        {
                        "pixelSize":100
                        },
                    ]
                }
            ]
        }
        expected_columns = [
            {
                'columnIndex': 1,
                'columnLetter': 'A',
                'columnName': '__sdc_skip_col_01',
                'columnType': 'stringValue',
                'columnSkipped': True,
                'prior_column_skipped': True
            }
        ]
        expected_schema = {
            'type': 'object',
            'additionalProperties': False,
            'properties': {
                '__sdc_spreadsheet_id': {
                    'type': ['null', 'string']
                    },
                '__sdc_sheet_id': {
                    'type': ['null', 'integer']
                    },
                '__sdc_row': {
                    'type': ['null', 'integer']
                }
            }
        }
        sheet_json_schema, columns = schema.get_sheet_schema_columns(sheet, config={})
        self.assertEqual(sheet_json_schema, expected_schema) # test the schema is as expected
        self.assertEqual(columns, expected_columns) # test if the columns is as expected
