from course_recommender.data.transcripts import (
    Transcript,
    parse_grade,
    parse_text,
    semester_number,
)

# Синтетический транскрипт: настоящие в репозиторий не попадают.
SAMPLE = """NAZARBAYEV UNIVERSITY
Student Unofficial Transcript
Date: 25 September 2026
Student Name: Test Student
Student ID: 202100000
School: School of Computing and Artificial Intelligence
Primary major: Computer Science
Admission semester: Fall 2023
Fall 2023
Credits Grade
Course Code Course Title Grade
ECTS Points
MATH 161 Calculus I A 8 4
PHYS 161 Physics I for Scientists and Engineers with B+ 8 3.33
Laboratory
CSCI 151 Programming for Scientists and Engineers C 8 2
Semester GPA: 3.09 Credits Enrolled: 24 Credits Earned: 24
Spring 2024
Credits Grade
Course Code Course Title Grade
ECTS Points
CSCI 152 Performance and Data Structures B 8 3
Semester GPA: 3.00 Credits Enrolled: 8 Credits Earned: 8
Summer 2024
Credits Grade
Course Code Course Title Grade
ECTS Points
CSCI 299 Internship I I* 6 n/a
Semester GPA: 0.0 Credits Enrolled: 6 Credits Earned: 0
Overall
GPA: 3.06 Credits Enrolled: 38 Credits Earned: 32
* - not included in calculation of the GPA or in earned credits.
------------------------END OF TRANSCRIPT------------------------
"""


def test_header_fields():
    transcript = parse_text(SAMPLE)
    assert transcript.name == "Test Student"
    assert transcript.student_id == "202100000"
    assert transcript.major == "Computer Science"
    assert transcript.admission_term == "Fall 2023"
    assert transcript.admission_year == 2023


def test_school_name_becomes_a_code():
    # В транскрипте школа названа полностью, в документах регистрации — кодом
    assert parse_text(SAMPLE).school_code == "SCAI"
    assert Transcript(school="Не такая школа").school_code == "Не такая школа"


def test_courses_with_grades_and_credits():
    courses = {c.code: c for c in parse_text(SAMPLE).courses}
    assert courses["MATH 161"].grade == 4.0
    assert courses["MATH 161"].credits == 8
    assert courses["PHYS 161"].grade == 3.33
    assert courses["CSCI 151"].title == "Programming for Scientists and Engineers"


def test_incomplete_course_has_no_grade_and_earns_nothing():
    courses = {c.code: c for c in parse_text(SAMPLE).courses}
    internship = courses["CSCI 299"]
    assert internship.grade is None
    assert not internship.is_earned


def test_earned_credits_match_the_transcript():
    transcript = parse_text(SAMPLE)
    assert transcript.earned == 32
    assert transcript.credits_earned == 32
    assert not transcript.is_partial


def test_partial_transcript_is_detected():
    # В файл попала одна страница из двух: курсов меньше, чем в итоговой строке
    partial = parse_text(SAMPLE.replace("Credits Earned: 32", "Credits Earned: 198"))
    assert partial.is_partial


def test_semester_numbering_follows_the_plan():
    assert semester_number("Fall 2023", "Fall 2023") == 1
    assert semester_number("Spring 2024", "Fall 2023") == 2
    assert semester_number("Fall 2024", "Fall 2023") == 3
    assert semester_number("Spring 2026", "Fall 2023") == 6
    # Лето своего номера не получает
    assert semester_number("Summer 2024", "Fall 2023") == 2


def test_semester_numbering_for_spring_admission():
    assert semester_number("Spring 2024", "Spring 2024") == 1
    assert semester_number("Fall 2024", "Spring 2024") == 2


def test_parse_grade():
    assert parse_grade("A") == 4.0
    assert parse_grade("C-") == 1.67
    assert parse_grade("I*") is None  # незачёт — результата нет
    assert parse_grade("W") is None


def test_student_is_built_from_the_transcript():
    student = parse_text(SAMPLE).student()
    assert student.major == "Computer Science"
    assert student.gpa == 3.06
    assert student.earned_credits == 32
    # закрыт второй семестр, впереди третий — значит второй курс
    assert parse_text(SAMPLE).next_semester == 3
    assert student.year == 2
    assert student.grade_of("MATH 161") == 4.0
    assert student.grade_of("CSCI 299") is None


def test_terms_are_ordered_by_calendar():
    assert parse_text(SAMPLE).terms == ("Fall 2023", "Spring 2024", "Summer 2024")


def test_empty_text_gives_empty_transcript():
    transcript = parse_text("")
    assert not transcript.courses
    assert transcript.admission_year is None
    assert not transcript.is_partial
