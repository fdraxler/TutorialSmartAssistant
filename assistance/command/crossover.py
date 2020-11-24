from assistance.command import Command
from assistance.command.info import select_student_by_name
from data.storage import InteractiveDataStorage


class ImportCommand(Command):
    def __init__(self, printer, storage: InteractiveDataStorage):
        super().__init__(printer, "import", ("<-",), 1, 1)
        self._storage = storage

    def __call__(self, *args, **kwargs):
        value = args[0]
        student = select_student_by_name(
            value,
            self._storage,
            self.printer,
            self._storage.import_student,
            mode='other'
        )

        if student is not None:
            tutorial = self._storage.get_tutorial_by_id(student.tutorial_id)
            self.printer.inform(f"The student '{student}' from {tutorial.time} was imported.")
            self.printer.inform(f"Workflow commands will also consider this student now as your own.")


class ExportCommand(Command):
    def __init__(self, printer, storage: InteractiveDataStorage):
        super().__init__(printer, "export", ("->",), 1, 1)
        self._storage = storage

    def __call__(self, *args, **kwargs):
        value = args[0]
        student = select_student_by_name(
            value,
            self._storage,
            self.printer,
            self._storage.export_student,
            mode='my'
        )

        if student is not None:
            tutorial = self._storage.get_tutorial_by_id(student.tutorial_id)
            self.printer.inform(f"The student '{student}' from {tutorial.time} was exported.")
            self.printer.inform(f"Workflow commands will ignore this student.")
