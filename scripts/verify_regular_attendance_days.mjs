import assert from 'node:assert/strict';

import { regularAttendanceDaysForStudent } from '../static/js/shared/selfStudy.js';

function testShowsFourRegularDaysWhenOneScheduleIsSelfStudy() {
  // Given
  const student = {
    day1: '월 1',
    day2: '화 2',
    day3: '수 1',
    day4: '목 2',
    day5: '금 3',
    selfStudyDays: { day2: true },
  };

  // When
  const days = regularAttendanceDaysForStudent(student);

  // Then
  assert.deepEqual(days, ['월 1', '수 1', '목 2', '금 3']);
}

function testLegacySelfStudyFlagDoesNotConsumeRegularDayLimit() {
  // Given
  const student = {
    day1: '월 1',
    day2: '화 2',
    day3: '수 1',
    day4: '목 2',
    day5: '금 3',
    day2SelfStudy: true,
  };

  // When
  const days = regularAttendanceDaysForStudent(student);

  // Then
  assert.deepEqual(days, ['월 1', '수 1', '목 2', '금 3']);
}

testShowsFourRegularDaysWhenOneScheduleIsSelfStudy();
testLegacySelfStudyFlagDoesNotConsumeRegularDayLimit();
console.log('regular attendance day regression checks passed');
