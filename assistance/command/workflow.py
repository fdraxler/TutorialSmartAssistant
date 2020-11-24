import os
import shutil
from collections import defaultdict
from json import dump as json_save
from json import load as j_load
from os.path import join as p_join
from types import SimpleNamespace
from zipfile import BadZipFile

import numpy as np

from assistance.command import Command
from data.storage import InteractiveDataStorage
from mail.mail_out import EMailSender
from moodle.api import MoodleSession
from muesli.api import MuesliSession
from util.feedback import FeedbackPolisher
from util.parse_names import FileNameParser


class WorkflowDownloadCommand(Command):
    def __init__(self, printer, function: callable, moodle: MoodleSession):
        super().__init__(printer, "workflow.download", ("w.down",), 1, 1)
        self._function = function
        self._moodle = moodle

    def __call__(self, *args):
        exercise_number = args[0]
        self._function(self._moodle, exercise_number, self.printer)


class WorkflowUnzipCommand(Command):
    def __init__(self, printer, storage):
        super().__init__(printer, "workflow.unzip", ("w.uz",), 1, 1)
        self._storage = storage

        from py7zr import unpack_7zarchive
        shutil.register_unpack_format('7zip', ['.7z'], unpack_7zarchive)

    def __call__(self, *args):
        exercise_number = args[0]
        raw_folder = self._storage.get_raw_folder(exercise_number)
        preprocessed_folder = self._storage.get_preprocessed_folder(exercise_number)

        for file in os.listdir(raw_folder):
            if file.endswith((".zip", ".tar.gz", ".tar", ".7z")):
                if file.endswith(".tar.gz"):
                    extension = ".tar.gz"
                    file_name = file[:len(extension)]
                else:
                    file_name, extension = os.path.splitext(file)

                try:
                    source_path = os.path.join(raw_folder, file)
                    name_parser = FileNameParser(self.printer, self._storage, file_name, exercise_number)
                    target_path = os.path.join(preprocessed_folder, name_parser.normalized_name)

                    if os.path.isdir(target_path):
                        self.printer.warning(f"Target path {name_parser.normalized_name} exists!")
                        if self.printer.ask("Continue? ([y]/n)") == "n":
                            break

                    if not extension.endswith("zip"):
                        name_parser.problems.append(f"Minor: Wrong archive format, please use '.zip' instead of '{extension}'.")

                    self.printer.inform("Found: " + ", ".join([student.muesli_name for student in name_parser.students]))
                    if len(name_parser.problems) > 0:
                        self.printer.inform()
                        self.printer.warning("While normalizing name there were some problems:")
                        self.printer.indent()
                        for problem in name_parser.problems:
                            self.printer.warning("- " + problem)
                        self.printer.outdent()
                        if self.printer.ask("Continue? ([y]/n)") == "n":
                            break

                    self.printer.inform(f"Unpacking {file} ... ", end="")
                    try:
                        shutil.unpack_archive(source_path, target_path)
                    except (BadZipFile, NotImplementedError) as e:
                        self.printer.warning("")
                        self.printer.warning(f"Detected bad zip file: {e}")
                        self.printer.warning(f"Trying different archive types ...")
                        with self.printer:
                            problem = None
                            for type in ("7z", "tar", "gztar", "bztar", "xztar"):
                                try:
                                    shutil.unpack_archive(source_path, target_path, format=type)
                                    problem = f"Wrong file extension provided - this file was actually a {type}!"
                                    break
                                except:
                                    self.printer.warning(f"... {type} failed!")

                        if problem is None:
                            self.printer.error(f"Fatal error: {file} could not be unpacked!")
                            self.printer.error("[ERR]")
                            shutil.copy(source_path, target_path)
                            self.printer.inform("Copied zip file to target.")
                            if self.printer.ask("Continue? ([y]/n)") == "n":
                                break
                            continue
                        else:
                            name_parser.problems.append(problem)

                    self.printer.confirm("[OK]")

                    with open(os.path.join(target_path, "submission_meta.json"), 'w', encoding='utf-8') as fp:
                        data = {
                            "original_name": file,
                            "problems": name_parser.problems,
                            "muesli_student_ids": [student.muesli_student_id for student in name_parser.students]
                        }
                        json_save(data, fp)

                except shutil.ReadError:
                    self.printer.error(f"Not supported archive-format: '{extension}'")

                self.printer.inform("─" * 100)
            else:
                self.printer.error(f"File name is {file} -- no known compressed file!")
                if self.printer.ask("Continue? ([y]/n)") == "n":
                    break


class WorkflowPrepareCommand(Command):
    def __init__(self, printer, storage, muesli):
        super().__init__(printer, "workflow.prepare", ("w.prep",), 1, 1)
        self._storage = storage
        self._muesli = muesli

    def __call__(self, *args):
        try:
            exercise_number = args[0]

            preprocessed_folder = self._storage.get_preprocessed_folder(exercise_number)
            working_folder = self._storage.get_working_folder(exercise_number)

            if not os.path.exists(preprocessed_folder):
                self.printer.error(f"The data for exercise {exercise_number} was not preprocessed. "
                                   f"Run workflow.unzip first.")

            can_generate_feedback = False
            if not self._storage.has_exercise_meta(exercise_number):
                self.printer.inform("Meta data for exercise not found. Syncing from MÜSLI ... ", end='')
                try:
                    self._storage.update_exercise_meta(self._muesli, exercise_number)
                    can_generate_feedback = True
                    self.printer.confirm("[OK]")
                except TypeError:
                    self.printer.error("[Err]")
                    self.printer.error("No credit stats found for this exercise.")
            else:
                can_generate_feedback = True

            for directory in os.listdir(preprocessed_folder):
                src_directory = os.path.join(preprocessed_folder, directory)
                target_directory = os.path.join(working_folder, directory)
                if not os.path.exists(target_directory):
                    shutil.copytree(src_directory, target_directory)
                if can_generate_feedback and os.path.isdir(target_directory):
                    self._storage.generate_feedback_template(exercise_number, target_directory, self.printer)
        except ValueError:
            self.printer.error(f"Exercise number must be an integer, not '{args[0]}'")


class WorkflowConsolidate(Command):
    def __init__(self, printer, storage):
        super().__init__(printer, "workflow.consolidate", ("w.cons",), 1, 1)
        self._storage = storage

    def __call__(self, *args):
        exercise_number = args[0]
        working_folder = self._storage.get_working_folder(exercise_number)
        finished_folder = self._storage.get_finished_folder(exercise_number)

        for directory in os.listdir(working_folder):
            self.printer.inform()
            self.printer.inform(f"Working in {directory}")
            self.printer.inform("Polishing feedback ... ", end='')
            polisher = FeedbackPolisher(
                self._storage,
                p_join(working_folder, directory),
                self.printer
            )
            self.printer.confirm("[Ok]")
            self.printer.inform("Saving meta data   ... ", end='')
            polisher.save_meta_to_folder(p_join(finished_folder, directory))
            self.printer.confirm("[Ok]")


class WorkflowUpload(Command):
    def __init__(self, printer, storage: InteractiveDataStorage, muesli: MuesliSession):
        super().__init__(printer, "workflow.upload", ("w.up",), 1, 1)
        self._storage = storage
        self._muesli = muesli

    def __call__(self, *args):
        exercise_number = args[0]
        finished_folder = self._storage.get_finished_folder(exercise_number)
        meta_file_name = "meta.json"

        data = defaultdict(dict)

        for directory in os.listdir(finished_folder):
            with open(p_join(finished_folder, directory, meta_file_name), 'r', encoding="utf-8") as fp:
                meta = SimpleNamespace(**j_load(fp))
                for muesli_id in meta.muesli_ids:
                    student = self._storage.get_student_by_muesli_id(muesli_id)
                    data[student.tutorial_id][muesli_id] = meta.credits_per_task

        for tutorial_id, student_data in data.items():
            tutorial = self._storage.get_tutorial_by_id(tutorial_id)
            self.printer.inform(
                f"Uploading credits to {tutorial.time} for {len(student_data.keys()):>3d} students ... ",
                end=''
            )
            exercise_id = self._muesli.get_exercise_id(
                tutorial_id,
                self._storage.muesli_data.exercise_prefix,
                exercise_number
            )
            status, number_of_changes = self._muesli.upload_credits(tutorial_id, exercise_id, student_data)

            if status:
                self.printer.confirm("[Ok]", end="")
                self.printer.inform(f" Changed {number_of_changes:>3d} entries.")
            else:
                self.printer.error("[Err]")
                self.printer.error("Please check your connection state.")


class WorkflowSendMail(Command):
    def __init__(self, printer, storage: InteractiveDataStorage):
        super().__init__(printer, "workflow.send_feedback", ("w.send",), 1, 2)
        self._storage = storage

    def _parse_arguments(self, args):
        if len(args) == 1:
            exercise_number = args[0]
            debug = False
        else:
            if args[0].lower() == '--debug':
                debug = True
                exercise_number = args[1]
            else:
                exercise_number = args[0]
                debug = args[1].lower() == '--debug'

                if not debug:
                    raise ValueError(f'Unexpected flag {args[1]}')

        return exercise_number, debug

    def __call__(self, *args):
        exercise_number, debug = self. \
            _parse_arguments(args)
        if debug:
            self.printer.confirm("Running in debug mode.")

        finished_folder = self._storage.get_finished_folder(exercise_number)
        feedback_file_name = f"{self._storage.muesli_data.feedback.file_name}.txt"
        meta_file_name = "meta.json"

        with EMailSender(self._storage.email_account, self._storage.my_name) as sender:
            for directory in os.listdir(finished_folder):
                students = list()
                with open(p_join(finished_folder, directory, meta_file_name), 'r', encoding="utf-8") as fp:
                    meta = SimpleNamespace(**j_load(fp))

                    for muesli_id in meta.muesli_ids:
                        try:
                            student = self._storage.get_student_by_muesli_id(muesli_id)
                            students.append(student)
                        except ValueError:
                            self.printer.error(f"Did not find student with id {muesli_id}, maybe he left the tutorial?")

                    feedback_path = p_join(finished_folder, directory, feedback_file_name)

                    message = list()
                    message.append("Dieses Feedback ist für:")
                    for student in students:
                        message.append(f"• {student.muesli_name} ({student.muesli_mail})")
                    message.append("")
                    message.append("Das Feedback befindet sich im Anhang.")
                    message.append("")
                    message.append(f"LG {self._storage.my_name_alias}")
                    message = "\n".join(message)

                    student_names = ', '.join([student.muesli_name for student in students])
                    self.printer.inform(f"Sending feedback to {student_names} ... ", end='')
                    try:
                        sender.send_mail(students, message, f'[IFML-20] Feedback zu {self._storage.muesli_data.exercise_prefix} {exercise_number}', feedback_path, debug=debug)
                        self.printer.confirm("[Ok]")
                    except BaseException as e:
                        self.printer.error(f"[Err] - {e}")


class WorkflowSendCrossTask(Command):
    def __init__(self, printer, storage: InteractiveDataStorage):
        super().__init__(printer, "workflow.send_cross_task", ("w.cross",), 1, 2)
        self._storage = storage

    def _parse_arguments(self, args):
        if len(args) == 1:
            exercise_number = args[0]
            debug = False
        else:
            if args[0].lower() == '--debug':
                debug = True
                exercise_number = args[1]
            else:
                exercise_number = args[0]
                debug = args[1].lower() == '--debug'

                if not debug:
                    raise ValueError(f'Unexpected flag {args[1]}')

        return exercise_number, debug

    def __call__(self, *args):
        exercise_number, debug = self. \
            _parse_arguments(args)
        if debug:
            self.printer.confirm("Running in debug mode.")
        raw_folder = self._storage.get_raw_folder(exercise_number)

        assignment_file = p_join(self._storage.get_exercise_folder(exercise_number), "cross-assignments.json")

        assert not os.path.isfile(assignment_file), "You already sent cross-feedback tasks to people"

        # Collect all submission files and corresponding uploader
        submissions = []
        with open(p_join(raw_folder, "meta.json")) as file:
            submission_list = j_load(file)
            for submission in submission_list:
                sub_info = SimpleNamespace(**submission)
                student = self._storage.get_student_by_moodle_id(sub_info.moodle_student_id)
                submissions.append((student, sub_info.file_name))

        # Find a permutation without self-assignment
        while True:
            new_order = np.random.permutation(len(submissions))
            if np.all(new_order != np.arange(len(submissions))):
                break

        with open(assignment_file, "w") as file:
            data = []
            for submission_idx, (assigned_to_student, _) in zip(new_order, submissions):
                creator_student, assigned_file = submissions[submission_idx]
                data.append({
                    "submission": assigned_file,
                    "submission_by_muesli_student_id": creator_student.muesli_student_id,
                    "assigned_to_muesli_student_id": assigned_to_student.muesli_student_id,
                })
            json_save(data, file)

        with EMailSender(self._storage.email_account, self._storage.my_name) as sender:
            for submission_idx, (student, _) in zip(new_order, submissions):
                creator_student, assigned_file = submissions[submission_idx]
                message = f"""Dear {student.moodle_name},

please provide cross-feedback to the appended submission by another student group.
For instructions, check the current Exercise Sheet.
Remember that you have to give cross-feedback at least four times over the semester.

Have an awesome day!
{self._storage.my_name}
"""

                self.printer.inform(f"Sending cross-feedback task to {student.moodle_name} ... ", end='')

                tmp_path = p_join(self._storage.get_exercise_folder(exercise_number), "cross-feedback-task.zip")
                try:
                    assigned_path = p_join(raw_folder, assigned_file)
                    shutil.copy(assigned_path, tmp_path)
                    sender.send_mail([student], message, f'[Fundamentals of Machine Learning] Your Cross-Feedback Task {self._storage.muesli_data.exercise_prefix} {exercise_number}', tmp_path, debug=debug)
                    self.printer.confirm("[Ok]")
                except BaseException as e:
                    self.printer.error(f"[Err] - {e}")
                finally:
                    os.unlink(tmp_path)
