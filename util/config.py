from getpass import getpass
from json import load as json_load
from types import SimpleNamespace


def load_config(path):
    with open(path, 'r', encoding='utf-8') as fp:
        json_dict = json_load(fp)

    return dict_to_simple_namespace(json_dict)


class LazyPassword:
    def __init__(self, account_name):
        self.account_name = account_name
        self.value = None

    def __str__(self):
        if self.value is None:
            self.value = getpass(f"Input password for {self.account_name}: ")
        return self.value


def mixin_passwords(config, name="root"):
    for key, value in config.__dict__.items():
        if isinstance(value, str):
            if key == "password" and (value == "###INTERACTIVE" or (value.startswith("<your ") and "password" in value and value.endswith(">"))):
                config.__dict__[key] = LazyPassword(name)
        else:
            mixin_passwords(value, key)
    return config


def dict_to_simple_namespace(d) -> SimpleNamespace:
    if type(d) is not dict:
        return d
    return SimpleNamespace(**{key: dict_to_simple_namespace(value) for key, value in d.items()})
