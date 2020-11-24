from collections import defaultdict
from json import load, dump
from pathlib import Path
from random import shuffle
from shutil import copy, copytree

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
            self.printer.inform(f"The student '{student}' from {tutorial.time} was registered as your student.")
            self.printer.inform(f"Workflow commands will also consider this student now as your own.")


class ExportCommand(Command):
    def __init__(self, printer, storage: InteractiveDataStorage):
        super().__init__(printer, "export", ("->", "exclude"), 1, 1)
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
            self.printer.inform(f"The student '{student}' from {tutorial.time} was deregistered from your group.")
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
        preprocessed_folder = Path(self._storage.get_preprocessed_folder(reference_sheet_name))
        for hand_in in preprocessed_folder.iterdir():
            if hand_in.is_dir():
                with open(hand_in / "submission_meta.json", "r") as file:
                    data = load(file)
                group = []
                for muesli_id in data["muesli_student_ids"]:
                    group.append(self._storage.get_student_by_muesli_id(muesli_id))
                groups.append(group)

        self.printer.inform(f"Found {len(groups)} groups")
        shuffle(groups)
        groups.sort(key=len, reverse=True)

        # Let user specify names of tutorials and the number of groups in this tutorial
        tutor_names = [self._storage.my_name]
        while True:
            tutor_name = self.printer.ask("Please enter another tutor name").strip()
            if len(tutor_name) > 0:
                if tutor_name in tutor_names:
                    self.printer.warning(f"You already have {tutor_name} in your list.")
                else:
                    tutor_names.append(tutor_name)
            else:
                break

        self.printer.inform()
        self.printer.inform(f"Here are your {len(tutor_names)} tutors: " + ", ".join(tutor_names))
        self.printer.inform()

        remaining_groups = len(groups)
        group_counts = [5, 5, 20, 20, 20, 19, 19]
        for i, tutor_name in enumerate(tutor_names[:-1]):
            while True:
                try:
                    self.printer.inform(f"{len(tutor_names) - i} tutors remaining for {remaining_groups} groups.")
                    tutor_group_count = int(self.printer.ask(f"How many groups should {tutor_name} work with?"))
                    group_counts.append(tutor_group_count)

                    remaining_groups -= tutor_group_count
                    if remaining_groups < 0:
                        self.printer.error("You specified more groups than were available")
                        continue
                    break
                except ValueError:
                    self.printer.error("Not an integer, please try again.")

        group_counts.append(remaining_groups)
        self.printer.inform(f"Automatically assigned {remaining_groups} to {tutor_names[-1]}")

        # Assign groups
        tutor_groups = defaultdict(list)
        tutor_group_counts = dict(zip(tutor_names, group_counts))
        for group in groups:
            next_tutor = min((name for name in tutor_names if len(tutor_groups[name]) < tutor_group_counts[name]), key=lambda name: (len(tutor_groups[name])))
            tutor_groups[next_tutor].append(group)

        for tutor_name, tutor_group_count in tutor_group_counts.items():
            assert tutor_group_count == len(tutor_groups[tutor_name]), f"Tutor {tutor_name} was assigned {len(tutor_groups[tutor_name])}, but {tutor_group_count} were requested."

        # Store assignments in ignore lists which can be sent to tutors to be put into their students directory
        meta_dir = Path(self._storage.storage_config.root) / "__meta__"
        tutors_dir = Path(self._storage.storage_config.root) / "Tutors"
        assert not tutors_dir.is_dir(), "Recrating tutors' directories, but they exist"
        tutors_dir.mkdir()
        for tutor_name, own_groups in tutor_groups.items():
            tutor_dir = tutors_dir / tutor_name / "__meta__"
            copytree(meta_dir, tutor_dir)

            with open(tutor_dir / "01_my_name.json", "w") as file:
                dump(tutor_name, file)

            own_students = [student.muesli_student_id for group in own_groups for student in group]
            other_students = [student.muesli_student_id for student in self._storage.all_students if student not in own_students]
            with open(tutor_dir / "students" / "imported_students.json", "w") as file:
                dump(own_students, file)
            with open(tutor_dir / "students" / "exported_students.json", "w") as file:
                dump(other_students, file)
