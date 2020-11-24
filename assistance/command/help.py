from assistance.command import Command
from util.console import string_table


class HelpCommand(Command):
    def __init__(self, printer, register):
        super().__init__(printer, "help", ("(?",), 0, 1)
        self._register = register

    def __call__(self, *args):
        if len(args) == 0:
            self._print_all_commands()
        elif len(args) == 1:
            self._print_single_command(args[0])
        else:
            self.printer.error(f"Expected no or one argument, not {len(args)}")

    def _print_all_commands(self):
        commands = sorted(self._register.commands, key=lambda cmd: cmd.name)
        header = ["Name", "Aliases", "Description"]
        columns = [list()] * len(header)
        columns[0] = [cmd.name for cmd in commands]
        columns[1] = [" ".join([f"'{alias}'" for alias in cmd.aliases]) for cmd in commands]
        columns[2] = [cmd.help.split("\n")[0] for cmd in commands]

        for line in string_table(header, columns):
            self.printer.inform(line)

    def _print_single_command(self, command):
        for line in self._register.get_command(command).help.split("\n"):
            self.printer.inform(line)