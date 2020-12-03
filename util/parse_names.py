import re

from assistance.command.info import select_student_by_name
from data.storage import InteractiveDataStorage
from util.console import single_choice, ConsoleFormatter


def is_number(s):
    try:
        int(s)
        return True
    except ValueError:
        return False


class NameParsingFailed(Exception):
    pass


class FileNameParser:
    def __init__(self, printer: ConsoleFormatter, storage: InteractiveDataStorage, file_name, exercise_number):
        self._printer = printer
        self._storage = storage

        self._file_name = file_name
        self._exercise_number = exercise_number
        self.problems = []
        self.students = []
        self.needed_manual_help = False

        self._parse()

    def _parse(self):
        try:
            name_part = self._strip_suffix()
            self._identify_students(name_part)
        except NameParsingFailed:
            while True:
                try:
                    self._manual_all_students()
                    break
                except NameParsingFailed as e:
                    if len(str(e)) > 0:
                        self.problems.append(f"Oh no: {e}")
                    if self._printer.yes_no("Do you want to skip this hand in?", default="n"):
                        break

        if len(self.students) < 2:
            self.problems.append("Submission groups should consist at least of 2 members!")
        if 3 < len(self.students):
            self.problems.append("Submission groups should consist at most of 3 members!")

    def ask_retry(self, question):
        self._printer.inform("Type 'manual' to enter manual mode.")
        answer = self._printer.ask(question)
        if answer == "manual":
            raise NameParsingFailed()
        return answer

    def yes_no_retry(self, question):
        while True:
            answer = self.ask_retry(f"{question} (y/n/manual)")
            if answer == "manual":
                raise NameParsingFailed()
            elif answer in ["y", "n"]:
                return answer == "y"
            else:
                self._printer.warning(f"Could not understand your answer: {answer}")

    @property
    def normalized_name(self):
        return ", ".join(sorted(student.muesli_name for student in self.students))

    def _strip_suffix(self):
        exercise_number = self._exercise_number
        file_name = self._file_name
        try:
            correct_file_name_end = f'_ex{exercise_number:02d}'
        except ValueError:
            correct_file_name_end = f'_ex{exercise_number}'

        self._printer.inform("Checking file name suffix.")
        if file_name.endswith(f"-ex{exercise_number:}") or (is_number(exercise_number) and file_name.endswith(f"-ex{exercise_number:02d}")):
            self.problems.append(f"Used '-' instead of '_' to mark end of filename. Please use '{correct_file_name_end}'")
            file_name = file_name.replace(f'-ex{exercise_number:02d}', correct_file_name_end) \
                .replace(f'-ex{exercise_number:}', correct_file_name_end)

        if correct_file_name_end != f"_ex{exercise_number:}" and file_name.endswith(f"_ex{exercise_number:}"):
            self.problems.append(f"The exercise number should be formatted with two digits.")
            file_name = file_name.replace(f'_ex{exercise_number:}', correct_file_name_end)

        if not (file_name.endswith(f"_ex{exercise_number}")):
            self.problems.append(f"Filename does not end with required '{correct_file_name_end}'.")
            file_name += correct_file_name_end

        return file_name[:-len(correct_file_name_end)]

    def _identify_students(self, name_part):
        self._printer.inform(f"Finding students in '{self._file_name}'.")

        student_names = []
        for student_name in name_part.split("_"):
            parts = re.findall(r'[A-Z](?:[a-zöäüß]+|[A-Z]*(?=[A-Z]|$))', student_name)
            if len(parts) > 0:
                student_name = ("-".join(parts))

            student_name = student_name.split("-")
            student_name = " ".join(student_name)
            if len(student_name) > 0:
                student_names.append(student_name)

        for student_name in student_names:
            if any(char.isdigit() for char in student_name):
                if self.ask_retry(f"Is '{student_name}' really a student name? (y/n)?") != 'y':
                    self._printer.inform("Skip")
                    continue

            # Try to find student
            student = select_student_by_name(student_name, self._storage, self._printer, mode='all')
            if student is None:
                student = self._manual_single_student(student_name)
                if student is None:
                    self._printer.error("Manual correction failed! Ignoring student.")
            if student is not None:
                self.students.append(student)

    def _manual_single_student(self, student_name):
        problem = f"Could not identify student '{student_name}', manual correction needed."
        self.problems.append(problem)
        self._printer.warning(problem)
        student = None
        while student is None:
            self._printer.inform(f"Please try a manual name for '{student_name}', e.g. parts of the name:")
            student = self._find_student_by_input()
            if student is None and not self.yes_no_retry("Did not find the student. Do you want to try again?"):
                raise NameParsingFailed(f"Manual correction of name '{student_name}' did not succeed.")

        return student

    def _manual_all_students(self):
        self.students = []
        problem = "Fatal: Wrong naming detected - manual correction needed."
        self.problems.append(problem)
        self._printer.error(problem)
        self._printer.error(self._file_name)
        self._printer.inform()
        self._printer.inform("Please enter the names you can read in the file name separated with ','.")

        names = self._printer.input(">: ")
        for name in names.split(','):
            student = self._find_student_by_input(name=name)
            if student is not None:
                self.students.append(student)
            else:
                while student is None:
                    self._printer.warning(f"Did not find a student with name '{name}'.")
                    self._printer.inform("Please try again or type 'cancel' to skip this name.")
                    student = self._find_student_by_input()
                    if student == 'cancel':
                        break

                if student != 'cancel':
                    self.students.append(student)

    def _find_student_by_input(self, mode='all', name=None):
        if name is None:
            name = self._printer.input(">: ")

        if name is 'cancel':
            return None
        elif len(name) == 0:
            return None
        else:
            possible_students = self._storage.get_students_by_name(name, mode=mode)
            if len(possible_students) == 1:
                return possible_students[0]
            elif len(possible_students) == 0:
                self._printer.warning(f"No match found for '{name}'")
                return None
            else:
                index = single_choice("Please select correct student", possible_students, self._printer)
                if index is None:
                    return None
                else:
                    return possible_students[index]
