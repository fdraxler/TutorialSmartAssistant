import os
import shutil
from collections import defaultdict
from json import dump
from json import dump as json_save
from json import load as j_load
from os.path import join as p_join
from pathlib import Path
from types import SimpleNamespace
from zipfile import BadZipFile

import numpy as np

from assistance.command import Command
from data.storage import InteractiveDataStorage, ensure_folder_exists
from mail.mail_out import EMailSender
from moodle.api import MoodleSession
from muesli.api import MuesliSession
from util.feedback import FeedbackPolisher
from util.files import copy_files, filter_and, filter_name_end, filter_name_not_end, filter_not, filter_or
from util.parse_names import FileNameParser


class WorkflowDownloadCommand(Command):
    def __init__(self, printer, storage: InteractiveDataStorage, moodle: MoodleSession):
        super().__init__(printer, "workflow.download", ("w.down",), 1, 1)
        self._storage = storage
        self._moodle = moodle

    def __call__(self, *args):
        exercise_number = args[0]

        moodle_data = self._storage.moodle_data

        self.printer.inform('Connecting to Moodle and collecting data.')
        self.printer.inform('This may take a few seconds.')
        with self._moodle:
            submissions = self._moodle.find_submissions(
                moodle_data.course_id,
                moodle_data.exercise_prefix,
                exercise_number,
                self.printer
            )
            self.printer.inform(f"Found a total of {len(submissions)} for '{moodle_data.exercise_prefix}{exercise_number}'")

            all_students = {student.moodle_student_id: student for student in self._storage.all_students}

            submissions = [submission for submission in submissions if submission.moodle_student_id in all_students]
            self.printer.inform(f"Found {len(submissions)} submissions")

            folder = os.path.join(
                self._storage.storage_config.root,
                self._storage.storage_config.submission_root,
                f'{self._storage.storage_config.exercise_template}{exercise_number}',
                self._storage.storage_config.raw_folder
            )
            ensure_folder_exists(folder)
            for submission in submissions:
                target_filename = os.path.join(folder, submission.file_name)
                if os.path.isfile(target_filename):
                    self.printer.warning(f"Target path {submission.file_name} exists!")
                    if self.printer.ask("Continue? ([y]/n)") == "n":
                        break
                with open(target_filename, 'wb') as fp:
                    try:
                        self.printer.inform(f"Downloading submission of {all_students[submission.moodle_student_id]} ... ", end='')
                        self._moodle.download(submission.url, fp)
                        self.printer.confirm('[Ok]')
                    except Exception as e:
                        self.printer.error('[Err]')
                        self.printer.error(str(e))

        with open(os.path.join(folder, "meta.json"), 'w') as fp:
            try:
                self.printer.inform(f'Write meta data ... ', end='')
                dump([s.__dict__ for s in submissions], fp, indent=4)
                self.printer.confirm('[Ok]')
            except Exception as e:
                self.printer.error('[Err]')
                self.printer.error(str(e))


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

        multi_hand_in_tracker = defaultdict(list)
        for file in os.listdir(raw_folder):
            if file.endswith((".zip", ".tar.gz", ".tar", ".7z")):
                if file.endswith(".tar.gz"):
                    extension = ".tar.gz"
                    file_name = file[:len(extension)]
                else:
                    file_name, extension = os.path.splitext(file)

                source_path = os.path.join(raw_folder, file)
                name_parser = FileNameParser(self.printer, self._storage, file_name, exercise_number)
                problems = list(name_parser.problems)

                if name_parser.normalized_name in multi_hand_in_tracker:
                    problems.append(f"There appear to be more than one submission by your group. We overwrote the contents of {', '.join(map(repr, multi_hand_in_tracker[name_parser.normalized_name]))} with {file}.")

                    self.printer.warning(f"A submission by {name_parser.normalized_name} was already extracted!")
                    self.printer.warning("Previously extracted file names are:")
                    self.printer.indent()
                    for prev_name in multi_hand_in_tracker[name_parser.normalized_name]:
                        self.printer.warning(f" - {prev_name}")
                    self.printer.outdent()
                    self.printer.inform("You can manually delete the .zip file from the raw folder or ignore this message.")
                    if not self.printer.yes_no("Continue?"):
                        break
                multi_hand_in_tracker[name_parser.normalized_name].append(file)

                target_path = os.path.join(preprocessed_folder, name_parser.normalized_name)
                if os.path.isdir(target_path):
                    self.printer.warning(f"Target path {name_parser.normalized_name} exists!")
                    if not self.printer.yes_no("Continue?"):
                        break

                if not extension.endswith("zip"):
                    problems.append(f"Minor: Wrong archive format, please use '.zip' instead of '{extension}'.")

                self.printer.inform("Found: " + ", ".join([student.muesli_name for student in name_parser.students]))
                if len(problems) > 0:
                    self.printer.inform()
                    self.printer.warning("While normalizing name there were some problems:")
                    self.printer.indent()
                    for problem in problems:
                        self.printer.warning("- " + problem)
                    self.printer.outdent()
                    if self.printer.ask("Continue? ([y]/n)") == "n":
                        break

                try:
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
                        else:
                            problems.append(problem)
                    self.printer.confirm("[OK]")
                except shutil.ReadError:
                    self.printer.error(f"Not supported archive-format: '{extension}'")

                with open(os.path.join(target_path, "submission_meta.json"), 'w', encoding='utf-8') as fp:
                    data = {
                        "original_name": file,
                        "problems": problems,
                        "muesli_student_ids": [student.muesli_student_id for student in name_parser.students]
                    }
                    json_save(data, fp)

                self.printer.inform("─" * 100)
            elif file != "meta.json":
                self.printer.error(f"File name is {file} -- no known compressed file!")
                if self.printer.ask("Continue? ([y]/n)") == "n":
                    break


class WorkflowPrepareCommand(Command):
    FILTER_CROSS_COMMENT = filter_or(filter_name_end("cross-commented"), filter_name_end("cross_commented"))
    FILTER_SELF_COMMENT = filter_and(filter_name_end("commented"), filter_not(FILTER_CROSS_COMMENT))

    def __init__(self, printer, storage: InteractiveDataStorage, muesli: MuesliSession):
        super().__init__(printer, "workflow.prepare", ("w.prep",), 1, 2)
        self._storage = storage
        self._muesli = muesli

    def __call__(self, exercise_number, next_exercise_number=None):
        if next_exercise_number is None:
            self.printer.warning("You are omitting loading the feedback from the next submission")
            if not self.printer.yes_no("Continue?"):
                return

        preprocessed_folder = Path(self._storage.get_preprocessed_folder(exercise_number))
        working_folder = Path(self._storage.get_working_folder(exercise_number))

        if not preprocessed_folder.is_dir():
            self.printer.error(f"The data for exercise {exercise_number} was not preprocessed. Run workflow.unzip first.")
            return

        can_generate_feedback = self.load_muesli_data(exercise_number)

        if next_exercise_number is not None:
            all_next_submissions = self.load_next_submissions(next_exercise_number)
            cross_assignments = self.load_cross_assignments(exercise_number)
        else:
            all_next_submissions = {}
            cross_assignments = []

        my_student_muesli_ids = [student.muesli_student_id for student in self._storage.my_students]
        for src_directory in preprocessed_folder.iterdir():
            if src_directory.name.startswith("."):
                continue
            with open(src_directory / "submission_meta.json", "rb") as file:
                submission_info = j_load(file)

            submission_muesli_ids = submission_info["muesli_student_ids"]
            any_own_student_detected = any(muesli_id in my_student_muesli_ids for muesli_id in submission_muesli_ids)

            if any_own_student_detected:
                not_my_students = [self._storage.get_student_by_muesli_id(muesli_id) for muesli_id in submission_muesli_ids if muesli_id not in my_student_muesli_ids]
                if len(not_my_students) > 0:
                    self.printer.warning(f"There are students among {src_directory.name} who do not belong to your group: {', '.join([student.muesli_name for student in not_my_students])}.")
                    if not self.printer.yes_no("Please talk to the head tutor. Continue anyway?", default="n"):
                        return

                target_directory = working_folder / src_directory.name
                if not target_directory.is_dir():
                    shutil.copytree(src_directory, target_directory)
                if can_generate_feedback and target_directory.is_dir():
                    self._storage.generate_feedback_template(exercise_number, target_directory, self.printer)

                self.copy_own_feedback(submission_muesli_ids, all_next_submissions, target_directory)
                self.copy_cross_feedback(cross_assignments, submission_muesli_ids, all_next_submissions, target_directory)

    def copy_own_feedback(self, submission_muesli_ids, all_next_submissions, target_directory):
        next_own_submissions = set()
        for submission_muesli_id in submission_muesli_ids:
            if submission_muesli_id in all_next_submissions:
                next_own_submissions.add(all_next_submissions[submission_muesli_id])
        for next_own_submission in next_own_submissions:
            # Find files ending with commented.X and copy them over
            self_target = target_directory / f"Own feedback by {next_own_submission.name}"
            if not self_target.is_dir():
                self_target.mkdir()
            copy_files(next_own_submission, self_target, WorkflowPrepareCommand.FILTER_SELF_COMMENT)

    def copy_cross_feedback(self, cross_assignments, submission_muesli_ids, all_next_submissions, target_directory):
        next_cross_submissions = set()
        for solution_by_muesli_id, was_assigned_to_muesli_id in cross_assignments:
            if solution_by_muesli_id in submission_muesli_ids and was_assigned_to_muesli_id in all_next_submissions:
                next_cross_submissions.add(all_next_submissions[was_assigned_to_muesli_id])
        for next_cross_submission in next_cross_submissions:
            # Find files ending with cross[-_]commented.X and copy them over
            cross_target = target_directory / f"Cross by {next_cross_submission.name}"
            if not cross_target.is_dir():
                cross_target.mkdir()
            copy_files(next_cross_submission, cross_target, WorkflowPrepareCommand.FILTER_CROSS_COMMENT)

    def load_muesli_data(self, exercise_number):
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
        return can_generate_feedback

    def load_cross_assignments(self, exercise_number):
        assignment_file = Path(self._storage.get_exercise_folder(exercise_number)) / "cross-assignments.json"
        assignments = []
        with open(assignment_file, "r") as file:
            data = j_load(file)
            for assignment in data:
                assignments.append((
                    assignment["submission_by_muesli_student_id"],
                    assignment["assigned_to_muesli_student_id"]
                ))
        return assignments

    def load_next_submissions(self, next_exercise_number):
        next_exercise_unpacked_folder = Path(self._storage.get_preprocessed_folder(next_exercise_number))
        all_next_submissions = {}
        for next_submission in next_exercise_unpacked_folder.iterdir():
            next_meta = Path(next_submission / "submission_meta.json")
            if next_meta.is_file():
                with open(next_meta, "r") as file:
                    for muesli_id in j_load(file)["muesli_student_ids"]:
                        all_next_submissions[muesli_id] = next_submission
        return all_next_submissions


class WorkflowConsolidate(Command):
    def __init__(self, printer, storage):
        super().__init__(printer, "workflow.consolidate", ("w.cons",), 1, 1)
        self._storage = storage

    def __call__(self, *args):
        exercise_number = args[0]
        working_folder = Path(self._storage.get_working_folder(exercise_number))
        finished_folder = Path(self._storage.get_finished_folder(exercise_number))

        for directory in working_folder.iterdir():
            if directory.name.startswith("."):
                continue

            self.printer.inform()
            self.printer.inform(f"Working in {directory.name}")
            self.printer.inform("Polishing feedback ... ", end='')
            polisher = FeedbackPolisher(
                self._storage,
                directory,
                self.printer
            )
            self.printer.confirm("[Ok]")
            self.printer.inform("Saving meta data   ... ", end='')
            target_directory = finished_folder / directory.name
            polisher.save_meta_to_folder(target_directory)

            feedback_directory = target_directory / "Original and Comments"
            if not feedback_directory.is_dir():
                feedback_directory.mkdir()
            copy_files(directory, feedback_directory, filter_and(filter_name_not_end("Feedback"), filter_name_not_end("submission_meta")))
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
            meta_path = p_join(finished_folder, directory, meta_file_name)
            if not os.path.isfile(meta_path):
                self.printer.inform(f"Skipping {directory}")
                continue

            with open(meta_path, 'r', encoding="utf-8") as fp:
                meta = SimpleNamespace(**j_load(fp))
                for muesli_id in meta.muesli_ids:
                    student = self._storage.get_student_by_muesli_id(muesli_id)
                    data[student.tutorial_id][muesli_id] = meta.credits_per_task

        with self._muesli:
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
        exercise_number, debug = self._parse_arguments(args)
        if debug:
            self.printer.confirm("Running in debug mode.")

        finished_folder = Path(self._storage.get_finished_folder(exercise_number))
        feedback_file_name = f"{self._storage.muesli_data.feedback.file_name}.txt"
        meta_file_name = "meta.json"

        with EMailSender(self._storage.email_account, self._storage.my_name) as sender:
            for directory in finished_folder.iterdir():
                if not (directory / meta_file_name).is_file():
                    self.printer.inform(f"Skipping {directory.name}.")
                    continue

                students = list()
                with open(directory / meta_file_name, 'r') as fp:
                    meta = SimpleNamespace(**j_load(fp))

                    for muesli_id in meta.muesli_ids:
                        try:
                            student = self._storage.get_student_by_muesli_id(muesli_id)
                            students.append(student)
                        except ValueError:
                            self.printer.error(f"Did not find student with id {muesli_id}, maybe he left the tutorial?")

                    feedback_path = directory / feedback_file_name

                    message = list()
                    message.append("This feedback is for:")
                    for student in students:
                        message.append(f"• {student.muesli_name} ({student.muesli_mail})")
                    message.append("")
                    message.append("Tutor notes are in Feedback.txt, with explanations about where you did really well and where you did not.")
                    message.append("")
                    if len(list(directory.glob("Original and Comments/Cross by *"))) > 0:
                        message.append("You also got feedback from another student group. Be sure to check it out.")
                        message.append("")
                    message.append(f"LG {self._storage.my_name_alias}")
                    message = "\n".join(message)

                    shutil.make_archive(directory / "Comments", "zip", directory, "Original and Comments")
                    archive_zip = directory / "Comments.zip"

                    student_names = ', '.join([student.muesli_name for student in students])
                    self.printer.inform(f"Sending feedback to {student_names} ... ", end='')
                    try:
                        sender.send_mail(students, message, f'[IFML-20] Feedback to {self._storage.muesli_data.exercise_prefix} {exercise_number}', [feedback_path, archive_zip], debug=debug)
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
