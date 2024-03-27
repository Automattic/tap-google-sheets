from typing import TypedDict


class Config(TypedDict):
    credentials_file: str
    spreadsheet_id: str
    start_date: str
    max_col_letter: str
