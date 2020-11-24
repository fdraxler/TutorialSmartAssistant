from assistance.command import Command
from assistance.command.info import select_student_by_name
from data.storage import InteractiveDataStorage


class IncludeCommand(Command):
    def __init__(self, printer, storage: InteractiveDataStorage):
        super().__init__(printer, "include", ("<-",), 1, 1)
        self._storage = storage

    def __call__(self, *args, **kwargs):
        value = args[0]
        student = select_student_by_name(
            value,
            self._storage,
            self.printer,
            self._storage.include_student,
            mode='other'
        )

        if student is not None:
            tutorial = self._storage.get_tutorial_by_id(student.tutorial_id)
            self.printer.inform(f"The student '{student}' from {tutorial.time} was remove from the ignore list.")
            self.printer.inform(f"Workflow commands will also consider this student now as your own.")


class IgnoreCommand(Command):
    def __init__(self, printer, storage: InteractiveDataStorage):
        super().__init__(printer, "ignore", ("->", "exclude"), 1, 1)
        self._storage = storage

    def __call__(self, *args, **kwargs):
        value = args[0]
        student = select_student_by_name(
            value,
            self._storage,
            self.printer,
            self._storage.ignore_student,
            mode='my'
        )

        if student is not None:
            tutorial = self._storage.get_tutorial_by_id(student.tutorial_id)
            self.printer.inform(f"The student '{student}' from {tutorial.time} was set on the ignore list.")
            self.printer.inform(f"Workflow commands will ignore this student.")


class AssignTutorsCommand(Command):
    def __init__(self, printer, storage: InteractiveDataStorage):
        super().__init__(printer, "assign-tutors", ("<-^->",), 1, 1)
        self._storage = storage

    def __call__(self, reference_sheet_name):
        # Check that only one tutorial exists
        assert len(self._storage.tutorials) == 1, "Only one tutorial supported, assignment was probably done in Müsli."

        # Group people by their last hand in group
        groups = []
        self._storage.get

        # Let user specify names of tutorials and the number of groups in this tutorial
        # Assign groups fairly
        # Store assignments in ignore lists which can be sent to tutors to be put into their students directory
        pass
