import { runChecks as runAdminChecks } from './homework-admin.mjs';
import { runChecks as runStudentChecks } from './homework-student.mjs';

export async function runChecks() {
  const [admin, student] = await Promise.all([runAdminChecks(), runStudentChecks()]);
  return Object.freeze({
    suite: 'student-mobile-app-homework',
    checks: Number(admin.checks) + Number(student.checks),
    checksPassed: Object.freeze([
      ...admin.checksPassed.map(name => `admin: ${name}`),
      ...student.checksPassed.map(name => `student: ${name}`),
    ]),
  });
}

export default runChecks;
