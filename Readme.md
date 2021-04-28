# TutorialSmartAssistant

Version used for Fundamentals of Machine Learning in summer 2021.

## Workflow

### Corrections

`XX` is the name of the exercise, e.g. 01a, 01b, ….

1. `w.setup XX` creates an empty directory for the raw student uploads. 
2. Bulk download submissions from MaMpf. Unzip the one file you got into the raw folder created in step 1.
3. `w.parse XX` parses the student names from the file.
4. `w.cross XX` creates a folder '06_Cross' which contains cross feedback assignments for your students.
   Bulk upload these files as "corrections" on MaMpf ASAP.
   
----- Not updated for summer 2021

4. `w.unzip XX` matches the zip filenames to moodle and muesli ids and unzips the solutions downloaded from moodle.
    1. When the names can't be matched, you need to help the system.
    2. Any problems in the naming will be reported and added as "problems" to the unzipped hand in. This is later included in the feedback file so that students know.
4. Make sure to get the `cross-assignments.json` file for the sheet from the responsible tutor.
5. `w.prep XX [YY]` filters the submissions to students assigned to you and prepares the unzipped files for correction.
    1. When `YY` is passed, for each group the submission(s) for the sheet `YY` are identified and copied. This is the basis for correction. This also identifies possible cross feedbacks and copies them to the directory.
    2. When the exercise has been enabled in Muesli, a feedback template is generated that lists the exercises and the maximum number of points
6. Now go through the hand ins and correct them
    1. Whatever changes you make in each solution will be visible to the students.
    2. Write your feedback into `Feedback.txt` -- this is parsed for getting the points in moodle.
        1. Write `[@-X]` when you deduct points, `X` can be a decimal like `1.5`.
        2. Write `[@+X]` for bonus points when the solution is especially nice.
    3. If you want to make detailed comments, copy the `whatever-commented.ipynb` to `whatever-corrected.ipynb` and add changes there, i.e. using `<span style="color:red;font-weight:bold">Comment</span>` in Markdown. Make sure to export this file to `whatever-corrected.html`.
    4. Look at the cross feedback. When it meets the requirements, open up the cross feedback point page in Müsli and enter the information directly. Make sure to keep the page open for short time, otherwise you might overwrite other tutor's input.
7. `w.cons XX` parses the information in the corrected directories and copies them.
8. `w.up XX` sends the corrected directories as zip files uploads the achieved points to Müsli.
9. `w.send XX [--debug]` sends the Feedback and all files in the corrected submissions to all students via mail. The debug flag sends all emails only to your own address.


### Cross Assignments

1. Make sure you ran `w.down XX` as before `w.uz XX`
3. `w.cross XX [--debug]` assigns each submission from this exercise to another group who handed in.
    1. Results are stored `cross-assignments.json`
    2. Assignments are sent via email by attaching the corresponding `.zip` file. The debug flag sends all emails only to your own address.
3. Send the other tutors the `cross-assignments.json` file.
4. When additional students get cross feedback assignments, add them to the file manually by searching the muesli ids and send the corrected version to the other tutors.


## TODOs

- When a student changes their submission group and changes the tutorial, the system probably assigns the submission to several students
- Implement some safety checks whether all cross feedbacks where copied.
