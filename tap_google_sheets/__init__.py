#!/usr/bin/env python3

import json
import sys

import singer

from tap_google_sheets.client import GoogleClient
from tap_google_sheets.config import Config
from tap_google_sheets.discover import discover
from tap_google_sheets.sync import sync

LOGGER = singer.get_logger()

REQUIRED_CONFIG_KEYS = [
    'credentials_file',
    'spreadsheet_id',
    'start_date'
]

def do_discover(client: GoogleClient, config: Config):

    LOGGER.info('Starting discover')
    catalog = discover(client, config)
    json.dump(catalog.to_dict(), sys.stdout, indent=2)
    LOGGER.info('Finished discover')


@singer.utils.handle_top_exception(LOGGER)
def main():

    parsed_args = singer.utils.parse_args(REQUIRED_CONFIG_KEYS)

    with GoogleClient(parsed_args.config['credentials_file']) as client:

        state = {}
        if parsed_args.state:
            state = parsed_args.state

        config = parsed_args.config

        if parsed_args.discover:
            do_discover(client, config)
        elif parsed_args.catalog:
            sync(client=client,
                 config=config,
                 catalog=parsed_args.catalog,
                 state=state)

if __name__ == '__main__':
    main()
