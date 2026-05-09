import os

from dotenv import dotenv_values, load_dotenv

load_dotenv()

ENV_FILE_VALUES = dotenv_values(
    os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))
)


def _get_int_env(names, default):
    for name in names:
        value = ENV_FILE_VALUES.get(name)
        case_insensitive_match = next(
            (env_value for env_name, env_value in ENV_FILE_VALUES.items() if env_name.lower() == name.lower()),
            None,
        )
        if value is None and case_insensitive_match is None:
            value = next((env_value for env_name, env_value in os.environ.items() if env_name == name), None)
        if value is None:
            continue
        value = value.strip().strip("'").strip('"')
        if value:
            return int(value)
    return default


def get_point_id():
    return _get_int_env(['PRESTO_POINT_ID', 'POINT_ID'], 3)


def get_price_list_id():
    return _get_int_env(['PRESTO_PRICE_LIST_ID', 'PRICE_LIST_ID'], 74)


def get_price_list_id_delivery():
    return _get_int_env(['PRESTO_PRICE_LIST_ID_DELIVERY', 'PRICE_LIST_ID_DELIVERY'], None)
