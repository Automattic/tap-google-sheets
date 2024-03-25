import pytest

from tap_google_sheets import schema

cols = [
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

cols_schema = {'a': {'type': ['null', 'integer']},
               'b': {'type': ['null', 'integer']},
               'c': {'type': ['null', 'number']}}

@pytest.mark.parametrize(
    "max_col_letter,expected_cols,expected_schema_cols",
    [
        pytest.param("A", cols[:1], {k: v for k, v in cols_schema.items() if k in ('a',)}, id='test_limit_max_col_A'),
        pytest.param("B", cols[:2], {k: v for k, v in cols_schema.items() if k in ('a', 'b',)}, id='test_limit_max_col_B'),
        pytest.param("C", cols, cols_schema, id='test_limit_max_col_C'),
        pytest.param("D", cols, cols_schema, id='test_limit_max_col_D'),
        pytest.param(None, cols, cols_schema, id='test_limit_max_col_None')
    ]
)
def test_limit_max_col(max_col_letter, expected_cols, expected_schema_cols):
    """
    Test when the config max col letter is set, the schema return the columns with the max col letter
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
            **expected_schema_cols
        }
    }
    sheet_json_schema, columns = schema.get_sheet_schema_columns(sheet, config={'max_col_letter': max_col_letter})
    assert expected_schema == sheet_json_schema
    assert expected_cols == columns

