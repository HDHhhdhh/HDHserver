// 한 줄 신규 학생 바(가로 스크롤 + 통일 스타일)
export function mountNewStudentBar() {
  // 마운트 지점 없으면 헤더 아래 자동 생성
  let host = document.getElementById('newStuMount');
  if (!host) {
    host = document.createElement('div');
    host.id = 'newStuMount';
    const hdr = document.querySelector('header.topbar') || document.body;
    hdr.insertAdjacentElement('afterend', host);
  }

  host.innerHTML = `
  <div class="ns-wrap">
    <input class="ns-input" id="ns_name" placeholder="이름">

    <select class="ns-input" id="ns_cur">
      <option value="공수1">공수1</option>
      <option value="공수2">공수2</option>
      <option value="미적분1">미적분1</option>
      <option value="미적분2">미적분2</option>
      <option value="대수">대수</option>
      <option value="기하">기하</option>
      <option value="확통">확통</option>
    </select>

    <select class="ns-input" id="ns_sub">
      <option value="">세부과정 선택</option>
      <option value="A:Ble">A:Ble</option>
      <option value="APEX">APEX</option>
    </select>

    <input class="ns-input" id="ns_day1" placeholder="요일1">
    <input class="ns-input" id="ns_day2" placeholder="요일2">
    <input class="ns-input" id="ns_day3" placeholder="요일3">
    <input class="ns-input" id="ns_day4" placeholder="요일4">
    <input class="ns-input" id="ns_day5" placeholder="요일5">

    <!-- ✅ 학년 추가 -->
    <select class="ns-input" id="ns_grade">
      <option value="">학년 선택</option>
      <option value="중1">중1</option>
      <option value="중2">중2</option>
      <option value="중3">중3</option>
      <option value="고1">고1</option>
      <option value="고2">고2</option>
      <option value="고3">고3</option>
      <option value="N수">N수</option>
    </select>

    <select class="ns-input" id="ns_level">
      <option value="">레벨 선택</option>
      <option value="상">상</option>
      <option value="중상">중상</option>
      <option value="중">중</option>
      <option value="하">하</option>
    </select>

    <input class="ns-input" id="ns_school" placeholder="학교">
    <input class="ns-input" id="ns_doc" placeholder="학생 개별 문서 URL(옵션)">

    <button class="ns-btn" id="ns_add">추가</button>
  </div>`;

  document.getElementById('ns_add')?.addEventListener('click', async () => {
    const body = {
      name: val('ns_name'),
      curriculum: val('ns_cur'),
      subCurriculum: val('ns_sub'),
      day1: val('ns_day1'), day2: val('ns_day2'), day3: val('ns_day3'),
      day4: val('ns_day4'), day5: val('ns_day5'),

      // ✅ 학년
      grade: val('ns_grade'),

      level: val('ns_level'),
      school: val('ns_school'),
      docUrl: val('ns_doc')
    };

    try {
      const r = await fetch('/api/add-student', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
      if (!r.ok) throw new Error(r.status);
      location.reload();
    } catch (e) {
      alert('추가 실패: ' + e.message);
    }
  });

  function val(id) { return (document.getElementById(id)?.value || '').trim(); }
}
