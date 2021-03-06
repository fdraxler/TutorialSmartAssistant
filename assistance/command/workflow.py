import json
import os
import shutil
from collections import defaultdict
from json import dump
from json import dump as json_save
from json import load as j_load
from os.path import join as p_join
from pathlib import Path
from types import SimpleNamespace
from typing import List, Dict
from zipfile import BadZipFile, ZipFile

import numpy as np

from assistance.command import Command
from data.storage import InteractiveDataStorage, ensure_folder_exists
from mail.mail_out import EMailSender
from moodle.api import MoodleSession
from muesli.api import MuesliSession
from util.feedback import FeedbackPolisher
from util.files import copy_files, filter_and, filter_name_end, filter_name_not_end, filter_not, filter_or
from util.parse_names import FileNameParser, normalized_name


class WorkflowDownloadCommand(Command):
    def __init__(self, printer, storage: InteractiveDataStorage, moodle: MoodleSession):
        super().__init__(printer, "workflow.download", ("w.down",), 1, 1)
        self._storage = storage
        self._moodle = moodle

    def __call__(self, exercise_number):
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

            # Check for duplicates
            existing_submissions = {}
            for submission in submissions:
                if submission.file_name.lower() in existing_submissions:
                    original_student = self._storage.get_student_by_moodle_id(existing_submissions[submission.file_name.lower()].moodle_student_id)
                    replace_student = self._storage.get_student_by_moodle_id(submission.moodle_student_id)
                    self.printer.warning(f"Duplicate file {submission.file_name}. Original was uploaded by {original_student.moodle_name}, this was uploaded by {replace_student.moodle_name}")
                    if self.printer.yes_no("Do you want to replace the original file?", "n"):
                        existing_submissions[submission.file_name.lower()] = submission
                else:
                    existing_submissions[submission.file_name.lower()] = submission
            submissions = list(existing_submissions.values())

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


class WorkflowSetupEmptyCommand(Command):
    def __init__(self, printer, storage: InteractiveDataStorage):
        super().__init__(printer, "workflow.setup", ("w.setup",), 1, 1)
        self._storage = storage

    def __call__(self, exercise_number):
        raw_folder = Path(self._storage.get_raw_folder(exercise_number))
        if raw_folder.is_dir():
            raise ValueError(f"{raw_folder} exists! No need to create it.")
        else:
            raw_folder.mkdir(parents=True)

        self.printer.inform(f"Created {raw_folder}. Please put students' uploaded zip files there.")


class WorkflowParseNamesCommand(Command):
    def __init__(self, printer, storage: InteractiveDataStorage):
        super().__init__(printer, "workflow.parse", ("w.parse",), 1, 1)
        self._storage = storage

    def __call__(self, exercise_number):
        ex_folder = Path(self._storage.get_exercise_folder(exercise_number))
        name_file = ex_folder / "names.json"

        zip_file_names = self.find_zip_files(exercise_number)
        self.printer.inform(f"Found {len(zip_file_names)} input files.")

        if name_file.is_file():
            with open(name_file, "r") as file:
                names = j_load(file)
            problems = [problem for prob_list in self.find_errors(names, zip_file_names) for problem in prob_list]

            self.printer.warning(f"{len(names)} names were already parsed.")
            self.printer.inform("You have the following options:")
            self.printer.indent()
            self.printer.inform("a) Restart from scratch,")
            self.printer.inform(f"b) Resolve conflicts and missing/ignored files ({len(problems)}),")
            self.printer.inform(f"c) Abort.")
            self.printer.outdent()
            while True:
                answer = self.printer.ask("Please choose an option (a/b/c):")
                if answer in "abc":
                    if answer == "a":
                        names = {}
                    elif answer == "b":
                        pass
                    elif answer == "c":
                        return
                    break
        else:
            names = {}

        try:
            if len(names) == 0:
                for file in zip_file_names:
                    names[file] = self.parse_names_from_file(file, exercise_number)

            self.fix_errors(names, exercise_number)
        except:
            if self.printer.yes_no("An error occurred. Do you want to store the current state?"):
                with open(name_file, "w") as file:
                    json_save(names, file, indent=4)
            return

        with open(name_file, "w") as file:
            json_save(names, file, indent=4)

    def find_errors(self, names: Dict[str, dict], zip_file_names: List[str]):
        handled_files = set()
        handled_people: Dict[int, List[str]] = defaultdict(list)

        removed_files = []
        for file, file_info in names.items():
            if file not in zip_file_names:
                removed_files.append(file)

            handled_files.add(file)
            for person in file_info["muesli_student_ids"]:
                handled_people[person].append(file)

        people_double_assigned = []
        for person, files in handled_people.items():
            if len(files) > 1:
                people_double_assigned.append((person, files))

        unparsed_files = []
        for zip_file_name in zip_file_names:
            if zip_file_name not in handled_files:
                unparsed_files.append(zip_file_name)

        return removed_files, people_double_assigned, unparsed_files

    def fix_errors(self, names, exercise_number):
        while True:
            zip_file_names = self.find_zip_files(exercise_number)
            removed_files, people_double_assigned, unparsed_files = self.find_errors(names, zip_file_names)
            if len(removed_files) > 0:
                self.printer.warning(f"{len(removed_files)} are in the list of files that do not exist on the file system:")
                self.printer.indent()
                for removed_file in removed_files:
                    self.printer.warning(f"- {removed_file}")
                self.printer.outdent()
                if self.printer.yes_no("Do you want to remove them from the list of files?"):
                    for removed_file in removed_files:
                        del names[removed_file]
                continue

            if len(unparsed_files) > 0:
                self.printer.warning(f"{len(removed_files)} are on the file system, but not parsed:")
                self.printer.indent()
                for unparsed_file in unparsed_files:
                    self.printer.warning(f"- {unparsed_file}")
                self.printer.outdent()
                if self.printer.yes_no("Do you want to parse them now?"):
                    for file in unparsed_files:
                        names[file] = self.parse_names_from_file(file, exercise_number)
                else:
                    self.printer.ask("Please remove the files from the raw folder and hit enter.")
                continue

            if len(people_double_assigned) > 0:
                self.printer.warning(f"{len(people_double_assigned)} names were parsed for more than one submission.")
                for muesli_student_id, files in people_double_assigned:
                    self.printer.inform(f"Student: {self._storage.get_student_by_muesli_id(muesli_student_id)}")
                    self.printer.inform("Please select the correct assignment:")
                    self.printer.indent()
                    for idx, file in enumerate(files):
                        self.printer.inform(f"{idx}) {file}")
                    self.printer.outdent()
                    while True:
                        try:
                            selected_file = files[int(self.printer.ask("Correct assignment: "))]
                            break
                        except (ValueError, KeyError):
                            pass

                    for file_name in files:
                        if file_name == selected_file:
                            pass
                        else:
                            names[file_name]["muesli_student_ids"].remove(muesli_student_id)

            break

    def find_zip_files(self, exercise_number):
        raw_folder = self._storage.get_raw_folder(exercise_number)
        zip_file_names = []
        for file_name in os.listdir(raw_folder):
            if is_zip_file(file_name):
                zip_file_names.append(file_name)
            elif file_name != "meta.json":
                self.printer.error(f"File name is {file_name} -- no known compressed file!")
                while True:
                    answer = self.printer.ask("Choose [s]kip, [l]eave uncompressed or [a]bort.").strip().lower()
                    if answer[0] in "sla":
                        break
                    else:
                        self.printer.warning("Did not understand your answer.")
                if answer[0] == "s":
                    continue
                elif answer[0] == "a":
                    raise ValueError("Found invalid file name, aborting due to user request.")
                elif answer[0] == "l":
                    zip_file_names.append(file_name)
        return zip_file_names

    def parse_names_from_file(self, file, exercise_number):
        if file.endswith(".tar.gz"):
            extension = ".tar.gz"
            file_name = file[:len(extension)]
        else:
            file_name, extension = os.path.splitext(file)

        name_parser = FileNameParser(self.printer, self._storage, file_name, exercise_number)
        problems = list(name_parser.problems)

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
            self.printer.ask("Hit enter to continue")

        self.printer.confirm("[OK]")
        self.printer.inform("─" * 100)
        return {
            "original_name": file,
            "problems": problems,
            "muesli_student_ids": [student.muesli_student_id for student in name_parser.students]
        }


class WorkflowUnzipCommand(Command):
    def __init__(self, printer, storage):
        super().__init__(printer, "workflow.unzip", ("w.uz",), 1, 3)
        self._storage = storage

        from py7zr import unpack_7zarchive
        shutil.register_unpack_format('7zip', ['.7z'], unpack_7zarchive)

    def __call__(self, exercise_number, skip_existing=False):
        if skip_existing is not False:
            if skip_existing == "--skip":
                skip_existing = True
            else:
                raise ValueError(f"Did not understand second parameter {skip_existing}, should be '--skip' or nothing.")

        ex_folder = Path(self._storage.get_exercise_folder(exercise_number))
        name_file = ex_folder / "names.json"

        with open(name_file, "r") as file:
            names = j_load(file)

        raw_folder = Path(self._storage.get_raw_folder(exercise_number))
        preprocessed_folder = Path(self._storage.get_preprocessed_folder(exercise_number))

        for file, data in names.items():
            problems = data["problems"]
            zip_path = raw_folder / file
            target_path = preprocessed_folder / normalized_name(self._storage.get_student_by_muesli_id(muesli_id) for muesli_id in data["muesli_student_ids"])

            if not zip_path.is_file():
                self.printer.error(f"File {file} does not exist!")
                break

            if target_path.exists():
                self.printer.warning(f"Target path {target_path.name} exists!")
                if skip_existing:
                    self.printer.ask("Skipping. Hit enter to continue.")
                    continue
                else:
                    self.printer.error("Please remove or retry with '--skip'")
                    break
            else:
                target_path.mkdir(parents=True)

            if is_zip_file(file):
                self.printer.inform(f"Unpacking {file} ... ", end="")
                extension = zip_path.suffix
                try:
                    if not file.endswith("zip"):
                        problems.append(
                            f"Minor: Wrong archive format, please use '.zip' instead of '{extension}'.")
                    try:
                        shutil.unpack_archive(zip_path, target_path)
                        self.printer.confirm("[OK]")
                    except (BadZipFile, NotImplementedError) as e:
                        self.printer.warning("")
                        self.printer.warning(f"Detected bad zip file: {e}")
                        self.printer.warning(
                            f"Trying different archive types ...")
                        with self.printer:
                            problem = None
                            for type in ("7z", "tar", "gztar", "bztar", "xztar"):
                                try:
                                    shutil.unpack_archive(zip_path, target_path,
                                                          format=type)
                                    problem = f"Wrong file extension provided - this file was actually a {type}!"
                                    break
                                except:
                                    self.printer.warning(f"... {type} failed!")

                        if problem is None:
                            problems.append(
                                "Could not unzip zip file. Copying zip file to target.")
                            self.printer.error(
                                f"Fatal error: {file} could not be unpacked!")
                            self.printer.error("[ERR]")
                            shutil.copy(zip_path, target_path)
                            self.printer.inform("Copied zip file to target.")
                        else:
                            problems.append(problem)
                except shutil.ReadError:
                    self.printer.error(
                        f"Not supported archive-format: '{extension}'")
                    problems.append(
                        f"Not supported archive-format: '{extension}'")
            elif file != "meta.json":
                self.printer.warning(
                    f"File name is {file} -- no known compressed file!")
                while True:
                    answer = self.printer.ask(
                        "Choose [s]kip, [l]eave uncompressed or [a]bort.").strip().lower()
                    if answer[0] in "sla":
                        break
                    else:
                        self.printer.warning("Did not understand your answer.")
                if answer[0] == "s":
                    continue
                elif answer[0] == "a":
                    raise ValueError(
                        "Found invalid file name, aborting due to user request.")
                elif answer[0] == "l":
                    shutil.copy(zip_path, target_path)

            with open(target_path / "submission_meta.json", 'w') as fp:
                json_save(data, fp)


def is_zip_file(file):
    return file.endswith((".zip", ".tar.gz", ".tar", ".7z"))


class WorkflowSendConfirmation(Command):
    def __init__(self, printer, storage: InteractiveDataStorage):
        super().__init__(printer, "workflow.confirm", ("w.confirm",), 1, 2)

        self._storage = storage

    def __call__(self, exercise_number, debug_flag=False):
        preprocessed_folder = Path(self._storage.get_preprocessed_folder(exercise_number))

        if debug_flag == "--debug":
            debug_flag = True
        elif debug_flag is not False:
            raise ValueError(f"Invalid argument {debug_flag!r}.")

        if not preprocessed_folder.is_dir():
            self.printer.error(f"The data for exercise {exercise_number} was not extracted. Run workflow.unzip first.")
            return

        with EMailSender(self._storage.email_account, self._storage.my_name) as sender:
            for src_directory in preprocessed_folder.iterdir():
                if src_directory.name.startswith("."):
                    continue
                with open(src_directory / "submission_meta.json", "rb") as file:
                    submission_info = j_load(file)
                new_line = '\n'

                problems = submission_info["problems"]
                if len(problems) > 0:
                    problem_string = "Assigning the names was not easy; these issues occurred when parsing:"
                    problem_string += '\n'.join("- " + problem for problem in problems)
                else:
                    problem_string = "There were no issues parsing the file name. You are awesome!"

                students = [self._storage.get_student_by_muesli_id(muesli_student_id) for muesli_student_id in submission_info["muesli_student_ids"]]
                for student in students:
                    message = f"""Dear {student.muesli_name},
    
you or a team mate uploaded {submission_info["original_name"]!r} to Moodle as a hand in to sheet {exercise_number}.
We associate this hand in to the following students:
{new_line.join('- ' + student.muesli_name for student in students)}

{problem_string}

Have an awesome day!
{self._storage.my_name}
"""

                    self.printer.inform(f"Sending confirmation email to {student.moodle_name} ... ", end='')

                    try:
                        sender.send_mail([student], message, f'[Fundamentals of Machine Learning] Your submission to {self._storage.muesli_data.exercise_prefix} {exercise_number} was received', debug=debug_flag)
                        self.printer.confirm("[Ok]")
                    except BaseException as e:
                        self.printer.error(f"[Err] - {e}")

                self.printer.inform("─" * 100)


class WorkflowPrepareCommand(Command):
    FILTER_CROSS_COMMENT = filter_or(filter_name_end("cross-commented"), filter_name_end("cross_commented"), filter_name_end("cross-feedback"), filter_name_end("cross_feedback"))
    FILTER_SELF_COMMENT = filter_and(filter_or(filter_name_end("commented"), filter_name_end("feedback")), filter_not(FILTER_CROSS_COMMENT))

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

        if not preprocessed_folder.exists():
            self.printer.error(f"The data for exercise {exercise_number} was not extracted. Run workflow.unzip first:")
            self.printer.indent()
            self.printer.warning(str(preprocessed_folder))
            self.printer.outdent()
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
        for solution_by_muesli_ids, was_assigned_to_muesli_ids in cross_assignments:
            any_prev = any(solution_by_muesli_id in submission_muesli_ids for solution_by_muesli_id in solution_by_muesli_ids)
            any_feedback = any(was_assigned_to_muesli_id in all_next_submissions for was_assigned_to_muesli_id in was_assigned_to_muesli_ids)
            if any_prev and any_feedback:
                for was_assigned_to_muesli_id in was_assigned_to_muesli_ids:
                    if was_assigned_to_muesli_id in all_next_submissions:
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
        if not assignment_file.is_file():
            if self.printer.yes_no("cross-assignments.json was not found. Do you want to continue anyway?", None):
                return assignments
            else:
                raise NotImplementedError("Don't worry about this error")

        with open(assignment_file, "r") as file:
            data = j_load(file)
            for assignment in data:
                assignments.append((
                    assignment["submission_by_muesli_student_ids"],
                    assignment["assigned_to_muesli_student_ids"]
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
                    f"Uploading credits to {tutorial.time} for {len(student_data.keys()):>3d} students ... "
                )
                exercise_id = self._muesli.get_exercise_id(
                    tutorial_id,
                    self._storage.muesli_data.exercise_prefix,
                    exercise_number
                )
                status, number_of_changes = self._muesli.upload_credits(tutorial_id, exercise_id, student_data, self.printer)

                if status:
                    self.printer.confirm("[Ok]", end="")
                    self.printer.inform(f" Changed {number_of_changes:>3d} entries.")
                else:
                    self.printer.error("[Err]")
                    self.printer.error("Please check your connection state.")


class WorkflowZipCommand(Command):
    def __init__(self, printer, storage: InteractiveDataStorage):
        super().__init__(printer, "workflow.zip", ("w.zip",), 1, 1)
        self._storage = storage

    def __call__(self, exercise_number):
        finished_folder = Path(self._storage.get_finished_folder(exercise_number))
        mampf_folder = finished_folder / 'Mampf_Corrections'
        mampf_folder.mkdir(parents=True, exist_ok=True)

        for submission_folder in finished_folder.iterdir():
            if submission_folder.is_dir():
                if submission_folder != mampf_folder:
                    with open(submission_folder / "meta.json", "r") as file:

                        meta_info = json.load(file)
                        with ZipFile(mampf_folder / meta_info['original_name'], 'w') as zipF:
                            for file in ['Original and Comments','Feedback.txt']:
                                if file == 'Feedback.txt':
                                    zipF.write(filename=submission_folder / file, arcname=file)
                                else:
                                    self._zipdir(submission_folder /file, zipF, file)

        print('Corrections ready to upload for Mampf: 05_Fertig/Mampf_Corrections')

    def _zipdir(self,path, ziph, arcname):
        for root, dirs, files in os.walk(path):
            for file in files:
                ziph.write(os.path.join(root, file), 
                    os.path.relpath(os.path.join(root, file), 
                        os.path.join(path, '..')))

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

        assignment_file = p_join(self._storage.get_exercise_folder(exercise_number), "cross-assignments.json")

        assert not os.path.isfile(assignment_file), "You already sent cross-feedback tasks to people"

        ex_folder = Path(self._storage.get_exercise_folder(exercise_number))
        name_file = ex_folder / "names.json"
        with open(name_file, "r") as file:
            names = j_load(file)

        raw_folder = Path(self._storage.get_raw_folder(exercise_number))
        cross_folder = Path(self._storage.get_cross_folder(exercise_number))
        if cross_folder.is_dir():
            if len(list(cross_folder.iterdir())) > 0:
                raise ValueError(f"{cross_folder} exists and is not empty.")
        else:
            cross_folder.mkdir()

        # Collect all submission files and corresponding uploader
        submissions = []
        for file_name, data in names.items():
            file_path = raw_folder / file_name
            submissions.append((file_path, data["muesli_student_ids"]))

        # Find a permutation without self-assignment
        while True:
            new_order = np.random.permutation(len(submissions))
            if np.all(new_order != np.arange(len(submissions))):
                break

        with open(assignment_file, "w") as file:
            data = []

            for src_idx, tgt_idx in enumerate(new_order):
                src_file, src_students = submissions[src_idx]
                tgt_file, tgt_students = submissions[tgt_idx]

                shutil.copyfile(src_file, cross_folder / tgt_file.name)

                data.append({
                    "submission": src_file.name,
                    "submission_by_muesli_student_ids": src_students,
                    "assigned_to_muesli_student_ids": tgt_students,
                })
            json_save(data, file)
