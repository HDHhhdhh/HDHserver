import { searchKeyForText, studentSearchKey } from '../../shared/search.js';

function fieldValues(student, field) {
  const school = [
    student?.school,
    student?.schoolName,
    student?.highSchool,
    student?.middleSchool,
    student?.high,
    student?.middle,
    student?.schoolHigh,
    student?.schoolMiddle,
  ];
  const curriculum = [
    student?.curriculum,
    student?.subCurriculum,
    student?.subject,
    student?.course,
  ];

  if (field === 'school') return school;
  if (field === 'curriculum') return curriculum;
  return [...school, ...curriculum];
}

export function todayStudentSearchKey(student, field = 'all') {
  if (!student || typeof student !== 'object') return '';
  if (field === 'name') return studentSearchKey({ name: student.name, id: student.id });

  // Keep each field boundary visible to substring search: initials must not
  // combine the end of a name with the start of a school or curriculum.
  const fieldKeys = fieldValues(student, field)
    .filter(Boolean)
    .map(searchKeyForText);
  if (field === 'all') return [studentSearchKey(student), ...fieldKeys].filter(Boolean).join('|');
  return fieldKeys.join('|');
}
