import unittest
from tap_google_sheets import schema

class TestUnsupportedFields(unittest.TestCase):
    def test_singer_decimal_format(self):
        """
        Test whether the columns has the format singer.decimal for numbertype columns.
        """
        sheet = {
            "properties":{
                "sheetId":1825500887,
                "title":"Sheet11"
            },
            "data":[
                {
                    "rowData":[
                        {
                        "values":[
                            {
                                "formattedValue":"a",
                            },
                            {
                                "formattedValue":"b",
                            }
                        ]
                        },
                        {
                        "values":[
                            {
                                "effectiveValue": {
                                    "numberValue": 1
                                },
                            },
                            {
                                "effectiveValue": {
                                    "numberValue": 2
                                },
                            }
                        ]
                        }
                    ]
                }
            ]
        }
        expected_columns = [
        {
            "columnIndex": 1,
            "columnLetter": "A",
            "columnName": "a",
            "columnType": "numberType",
            "columnSkipped": False
        },
        {
            "columnIndex": 2,
            "columnLetter": "B",
            "columnName": "b",
            "columnType": "numberType",
            "columnSkipped": False
        }
        ]
        expected_schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "__sdc_spreadsheet_id": {
                    "type": [
                        "null",
                        "string"
                    ]
                },
                "__sdc_sheet_id": {
                    "type": [
                        "null",
                        "integer"
                    ]
                },
                "__sdc_row": {
                    "type": [
                        "null",
                        "integer"
                    ]
                },
                'a': {'type': ['null', 'number']},
                'b': {'type': ['null', 'number']},
            }
        }
        sheet_json_schema, columns = schema.get_sheet_schema_columns(sheet, config={})
        self.assertEqual(sheet_json_schema, expected_schema) # test the schema is as expected
        self.assertEqual(columns, expected_columns) # test if the columns is as expected

    def test_singer_integer_format(self):
        """
        Test whether the columns has the integer format for numbertype columns.
        """
        sheet = {
            "properties":{
                "sheetId":1825500887,
                "title":"Sheet11"
            },
            "data":[
                {
                    "rowData":[
                        {
                        "values":[
                            {
                                "formattedValue":"a",
                            },
                            {
                                "formattedValue":"b",
                            },
                            {
                                "formattedValue":"c",
                            }
                        ]
                        },
                        {
                        "values":[
                            {
                                "effectiveValue": {
                                    "numberValue": 1
                                },
                                "effectiveFormat": {
                                    "numberFormat": {
                                        "type": "NUMBER",
                                        "pattern": "0"
                                    }
                                }
                            },
                            {
                                "effectiveValue": {
                                    "numberValue": 2.0
                                },
                                "effectiveFormat": {
                                    "numberFormat": {
                                        "type": "NUMBER",
                                        "pattern": "0"
                                    }
                                }
                            },
                            {
                                "effectiveValue": {
                                    "numberValue": 3.1
                                },
                                "effectiveFormat": {
                                    "numberFormat": {
                                        "type": "NUMBER",
                                        "pattern": "0.0"
                                    }
                                }
                            }
                        ]
                        }
                    ]
                }
            ]
        }
        expected_columns = [
        {
            "columnIndex": 1,
            "columnLetter": "A",
            "columnName": "a",
            "columnType": "numberType.INTEGER",
            "columnSkipped": False
        },
        {
            "columnIndex": 2,
            "columnLetter": "B",
            "columnName": "b",
            "columnType": "numberType.INTEGER",
            "columnSkipped": False
        },
        {
            "columnIndex": 3,
            "columnLetter": "C",
            "columnName": "c",
            "columnType": "numberType",
            "columnSkipped": False
        }
        ]
        expected_schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "__sdc_spreadsheet_id": {
                    "type": [
                        "null",
                        "string"
                    ]
                },
                "__sdc_sheet_id": {
                    "type": [
                        "null",
                        "integer"
                    ]
                },
                "__sdc_row": {
                    "type": [
                        "null",
                        "integer"
                    ]
                },
                'a': {'type': ['null', 'integer']},
                'b': {'type': ['null', 'integer']},
                'c': {'type': ['null', 'number']},
            }
        }
        sheet_json_schema, columns = schema.get_sheet_schema_columns(sheet, config={})
        self.assertEqual(sheet_json_schema, expected_schema) # test the schema is as expected
        self.assertEqual(columns, expected_columns) # test if the columns is as expected

