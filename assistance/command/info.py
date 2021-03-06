from assistance.command import Command
from assistance.commands import normalize_string
from data.data import Student
from data.storage import InteractiveDataStorage
from util.collection import group
from util.console import single_choice, print_header, string_card, align_horizontal, string_framed_line, align_vertical


class InfoCommand(Command):
    def __init__(self, printer, storage: InteractiveDataStorage):
        super().__init__(printer, "information", ("info",), 1, 1, help="""Shows information about students, tutorials, tutors and exercises.
Aliases:
  ■ info
Required Named Arguments (one of):
  ■ --student , -s: (partial) name of student [type: str]
  ■ --tutor   , -t: (partial) name of tutor [type: str]
  ■ --Tutorial, -T: id of tutorial in MÜSLI [type: int]
  ■ --exercise, -e: number of the exercise [type: int]
Example usage:
  info -t="Christopher Schuster"
""")
        self._storage = storage

    def __call__(self, argument):
        parts = argument.split("=")
        if len(parts) < 2 or 2 < len(parts):
            raise ValueError("Expected an argument of the form <name>=<value>. Use help for more information.")
        name, value = parts

        if name in ("--student", "-s"):
            self._print_student_info(value)
        elif name in ("--tutor", "-t"):
            self._print_tutor_info(value)
        elif name in ("--Tutorial", "-T"):
            self._print_tutorial_info(value)
        elif name in ("--exercise", "-e"):
            raise NotImplementedError("This feature is not available (info.py: 50)")

        else:
            raise ValueError(f"Unknown argument '{name}'")

    def _print_student_info(self, value):
        select_student_by_name(value, self._storage, self.printer, self._print_student_info_card)

    def _print_student_info_card(self, student: Student):
        print_header(f'{student.muesli_name} (aka {student.alias})', self.printer)

        muesli_data = student.muesli_data
        tutorial = self._storage.get_tutorial_by_id(student.tutorial_id)
        muesli_data['Tutorial'] = f'{tutorial.time} ({tutorial.tutor})'
        muesli_card = string_card('Data from MÜSLI', muesli_data)
        moodle_card = string_card('Data from Moodle', student.moodle_data)
        if self._storage.muesli_data.presentation.supports_presentations:
            has_presented = self._storage.has_presented(student)
            answer = 'Ja' if has_presented else 'Nein'
            bottom_card = string_framed_line(f"Vorgerechnet: {answer}", length=60, orientation='<')
            moodle_card = align_vertical(moodle_card, bottom_card)

        lines = align_horizontal(muesli_card, moodle_card, space_size=2)

        for line in lines:
            self.printer.inform(line)

    def _print_tutor_info(self, value):
        value = normalize_string(value)
        all_tutors = self._storage.get_all_tutors()
        possible_tutors = [tutor for tutor in all_tutors if value in tutor]

        if len(possible_tutors) == 0:
            self.printer.error(f"No tutor found containing '{value}'")
            tutor = None
        elif len(possible_tutors) == 1:
            tutor = possible_tutors[0]
        else:
            selected_index = single_choice(f"Found {len(possible_tutors)} possible tutors", possible_tutors,
                                           self.printer)
            if selected_index is not None:
                tutor = possible_tutors[selected_index]
            else:
                tutor = None

        if tutor is None:
            self.printer.warning("Canceled")
        else:
            tutorials = self._storage.get_all_tutorials_of_tutor(tutor)
            mail = tutorials[0].tutor_mail

            data = {
                "E-Mail": mail
            }
            for tutorial in tutorials:
                data[f'Tutorial-{tutorial.tutorial_id}'] = f'{tutorial.time} - {tutorial.location}'
            for line in string_card(tutor, data, length=120, title_orientation='^'):
                self.printer.inform(line)

    def _print_tutorial_info(self, value):
        try:
            value = int(value)
        except ValueError:
            raise ValueError(f"Expected an id for an tutorial, not '{value}'")

        tutorial = self._storage.get_tutorial_by_id(value)
        print_header(f'{tutorial.time} {tutorial.location} (Id: {tutorial.tutorial_id})', self.printer)

        tutor_data = {
            "Name": tutorial.tutor,
            "E-Mail": tutorial.tutor_mail
        }
        tutor_card = string_card('Tutor', tutor_data)

        students = self._storage.get_all_students_of_tutorial(tutorial.tutorial_id)
        grouped_data = {k: len(v) for k, v in group(students, key=lambda student: student.subject).items()}

        participant_data = {"Total": f'{len(students):3d} (100.00%)'}
        for k, v in sorted(grouped_data.items(), key=lambda t: -t[1]):
            participant_data[k] = f'{v:3d} ({100 * v / len(students):5.2f}%)'

        participant_card = string_card('Participants', participant_data)

        lines = align_horizontal(tutor_card, participant_card, space_size=2)

        for line in lines:
            self.printer.inform(line)


def select_student_by_name(value, storage, printer, action=None, mode='all', too_much_limit=11):
    value = normalize_string(value)
    possible_students = storage.get_students_by_name(value, mode=mode)
    student = None

    if 1 < len(possible_students) < too_much_limit:
        selected_index = single_choice(
            f"Found {len(possible_students)} possible choices for '{value}'",
            possible_students,
            printer
        )
        if selected_index is not None:
            student = possible_students[selected_index]
    elif too_much_limit <= len(possible_students):
        if printer.yes_no(f"There are a lot of possibilities for '{value}'. Show them all? (y/n)", default=None):
            selected_index = single_choice(
                f"Found {len(possible_students)} possible choices",
                possible_students,
                printer
            )
            if selected_index is not None:
                student = possible_students[selected_index]
    elif len(possible_students) == 1:
        student = possible_students[0]

    if student is None:
        printer.warning("Canceled")
    elif action is not None:
        action(student)

    return student
