from assistance.command import Command
from assistance.command.info import select_student_by_name
from data.storage import InteractiveDataStorage
from muesli.api import MuesliSession


class PresentCommand(Command):
    def __init__(self, printer, storage: InteractiveDataStorage, muesli: MuesliSession):
        super().__init__(printer, "presented", ("pres", "[x]"), 1, 1)
        self._storage = storage
        self._muesli = muesli

    def __call__(self, *args):
        if not self._storage.muesli_data.presentation.supports_presentations:
            self.printer.error("Presenting is not supported. Please change config.json if you want to enable it.")
        else:
            name = args[0]
            select_student_by_name(
                name,
                self._storage,
                self.printer,
                self._update_presented_in_muesli,
                mode='my'
            )

    def _update_presented_in_muesli(self, student):
        if self._muesli.update_presented(student, self._storage.muesli_data.presentation.name):
            self.printer.confirm(f"MÜSLI: {student} has presented")
            self._storage.set_presented_for(student)
        else:
            self.printer.error("MÜSLI: Some error occurred. Please check connection state.")
