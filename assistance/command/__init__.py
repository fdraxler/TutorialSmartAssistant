from typing import Tuple

from util.console import ConsoleFormatter


class Command:
    def __init__(self, printer: ConsoleFormatter, name: str, aliases: Tuple[str, ...], min_arg_count: int, max_arg_count: int, help: str = "No help available."):
        self._printer = printer

        self._name = name
        self._aliases = aliases
        self._min_arg_count = min_arg_count
        self._max_arg_count = max_arg_count

        self._help = help

    @property
    def printer(self):
        return self._printer

    @property
    def name(self):
        return self._name

    @property
    def aliases(self):
        return self._aliases

    @property
    def min_arg_count(self):
        return self._min_arg_count

    @property
    def max_arg_count(self):
        return self._max_arg_count

    @property
    def help(self):
        return self._help
