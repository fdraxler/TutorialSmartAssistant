from traceback import format_exc

from assistance.command.connection import ConnectionCommand
from assistance.command.crossover import ImportCommand, ExportCommand, AssignTutorsCommand
from assistance.command.help import HelpCommand
from assistance.command.info import InfoCommand
from assistance.command.present import PresentCommand
from assistance.command.stop import StopCommand
from assistance.command.workflow import WorkflowDownloadCommand, WorkflowParseNamesCommand, WorkflowUnzipCommand, WorkflowPrepareCommand, \
    WorkflowConsolidate, WorkflowUpload, WorkflowSendMail, WorkflowSendCrossTask, WorkflowSendConfirmation, WorkflowSetupEmptyCommand, \
    WorkflowZipCommand
from assistance.commands import CommandRegister, parse_command, normalize_string
from data.storage import InteractiveDataStorage
from moodle.api import MoodleSession
from muesli.api import MuesliSession
from util.console import ConsoleFormatter, string_table


class SmartAssistant:
    def __init__(self):
        self._storage = InteractiveDataStorage()
        self._printer = ConsoleFormatter()
        self._muesli = MuesliSession(account=self._storage.muesli_account)
        if self._storage.moodle_data:
            self._moodle = MoodleSession(account=self._storage.moodle_account)
        else:
            self._moodle = None
        self._command_register = CommandRegister()
        self.ready = True

        # self._initialize_connections()
        self._initialize_storage()
        self._command_register.register_command(StopCommand(self._printer, self._stop))
        self._command_register.register_command(HelpCommand(self._printer, self._command_register))
        self._command_register.register_command(InfoCommand(self._printer, self._storage))
        self._command_register.register_command(ConnectionCommand(self._printer, self._moodle, self._muesli))

        self._command_register.register_command(WorkflowSetupEmptyCommand(self._printer, self._storage))
        self._command_register.register_command(WorkflowDownloadCommand(self._printer, self._storage, self._moodle))
        self._command_register.register_command(WorkflowParseNamesCommand(self._printer, self._storage))
        self._command_register.register_command(WorkflowUnzipCommand(self._printer, self._storage))
        self._command_register.register_command(WorkflowSendConfirmation(self._printer, self._storage))
        self._command_register.register_command(WorkflowPrepareCommand(self._printer, self._storage, self._muesli))
        self._command_register.register_command(WorkflowConsolidate(self._printer, self._storage))
        self._command_register.register_command(WorkflowUpload(self._printer, self._storage, self._muesli))
        self._command_register.register_command(WorkflowSendMail(self._printer, self._storage))
        self._command_register.register_command(WorkflowSendCrossTask(self._printer, self._storage))
        self._command_register.register_command(WorkflowZipCommand(self._printer, self._storage))

        self._command_register.register_command(ImportCommand(self._printer, self._storage))
        self._command_register.register_command(ExportCommand(self._printer, self._storage))
        self._command_register.register_command(AssignTutorsCommand(self._printer, self._storage))
        self._command_register.register_command(PresentCommand(self._printer, self._storage, self._muesli))

    def _initialize_connections(self):
        self._print_header("Initializing Connections")
        self._open_connection_to(self._muesli)
        self._open_connection_to(self._moodle)
        print()

    def _print_header(self, title):
        self._printer.inform('┌' + '─' * 120 + '┐')
        self._printer.inform(f'│{title:^120}│')
        self._printer.inform('└' + '─' * 120 + '┘')

    def _open_connection_to(self, session):
        self._printer.inform(f'Current state: {session.name}')
        if not session.online:
            with self._printer as printer:
                printer.inform("Logging in...", end='')
                try:
                    session.login()
                    printer.confirm("[Success]")
                except ConnectionRefusedError as e:
                    printer.error(f"[Error] - {e}")

    def _initialize_storage(self):
        self._print_header("Initializing Storage")
        self._storage.init_data(self._muesli, self._moodle)
        self._printer.inform()

    def hello(self):
        def my_tutorial_to_str(my_tutorial):
            students = self._storage.get_all_students_of_tutorial(my_tutorial.tutorial_id)
            return f'({my_tutorial.tutorial_id}) ' \
                   f'{my_tutorial.time} {my_tutorial.location:<15}' \
                   f'[{len(students)}]'

        def other_tutorial_to_str(other_tutorial):
            students = self._storage.get_all_students_of_tutorial(other_tutorial.tutorial_id)
            tutor = other_tutorial.tutor.split()
            tutor = f'{tutor[0]} {tutor[-1]}'
            return f'({other_tutorial.tutorial_id}) ' \
                   f'{other_tutorial.time} {other_tutorial.location:<15} ' \
                   f'{tutor:25}' \
                   f'[{len(students)}]'

        self._print_header(f'{"Hello, " + self._storage.my_name_alias:^88}')
        headers = ["My Tutorials", "Other Tutorials"]
        my_tutorials = self._storage.my_tutorials
        my_tutorials = [my_tutorial_to_str(my_tutorial) for my_tutorial in my_tutorials]
        other_tutorials = self._storage.other_tutorials
        other_tutorials = [other_tutorial_to_str(other_tutorial) for other_tutorial in other_tutorials]
        table = string_table(headers, [my_tutorials, other_tutorials])

        with self._printer as printer:
            for line in table:
                printer.inform(line)
        self._printer.inform()

        self._printer.inform("Enter a command or use 'help' / '?' to list all available commands.")
        self._printer.inform()

    def execute_cycle(self):
        str_command = input(">: ")
        with self._printer as printer:
            try:
                name, args = parse_command(str_command)
                command = self._command_register.get_command(name)
            except KeyError as k:
                self._printer.error(normalize_string(str(k)))
                self._printer.error("Please refer to 'help' / '?' to list all available commands.")
                return

            if command.min_arg_count <= len(args) <= command.max_arg_count:
                try:
                    command(*args)
                except Exception as e:
                    self._printer.error(f'{e.__class__.__name__}: {e}\n{format_exc()}')
            else:
                if command.min_arg_count == command.max_arg_count:
                    limitation = f"exactly {command.min_arg_count}"
                else:
                    limitation = f"between {command.min_arg_count} and {command.max_arg_count}"

                printer.error(f"The command '{command.name}' needs {limitation} arguments, but got {len(args)}.")

        self._printer.inform()

    def _stop(self):
        self.ready = False
        self._printer.inform("Close connections ...", end='')
        self._moodle.logout()
        self._muesli.logout()
        self._printer.inform("[OK]")
        self._printer.outdent()
        self._print_header("Have a nice day \\(^_^)/")
