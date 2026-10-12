"use strict";
// Key-free versioned lab review contract. No network, grading or submission code.
(function (root) {
  const SCHEMA = "ocr.review.run.v1";
  const statuses = new Set(["safe_auto_grade", "review_required", "retake_required", "retake_uploaded",
    "data_check_required", "confirmed", "student_selected_candidate", "student_direct_input",
    "safe_auto_grade_after_retake", "student_selected_candidate_after_retake", "student_direct_input_after_retake"]);
  const finalStatuses = new Set(["safe_auto_grade", "confirmed", "student_selected_candidate", "student_direct_input",
    "safe_auto_grade_after_retake", "student_selected_candidate_after_retake", "student_direct_input_after_retake"]);
  const forbidden = new Set(["expected", "expected_answer", "canonical", "canonical_answer", "canonical_answers",
    "accepted_answers", "answer_key", "answer_keys", "answerkeys", "grading", "correct_answer", "is_correct",
    "correct", "incorrect", "score", "wrong", "pct"]);
  const topFields = new Set(["schema", "identity", "test_id", "round", "problem_count", "items", "photo_preview", "source", "demo"]);
  const itemFields = new Set(["question_no", "status", "recognized", "candidates", "warnings", "final_answer",
    "source", "review_history", "identity_sha256", "crop_preview", "crop_sha256", "uncertainty", "needs_review", "retake_image_attached"]);
  const identityFields = new Set(["schema", "photo_sha256", "test_id", "round", "form_id", "model",
    "prompt_version", "preprocessing_version", "question_numbers", "identity_sha256"]);
  function fail(message) { throw new Error(message); }
  function inspect(value) {
    if (Array.isArray(value)) return value.forEach(inspect);
    if (!value || typeof value !== "object") return;
    for (const [key, child] of Object.entries(value)) {
      if (forbidden.has(key.toLowerCase())) fail("정답 정보가 포함된 입력은 허용하지 않습니다.");
      inspect(child);
    }
  }
  function fields(value, allowed) {
    if (!value || Array.isArray(value) || typeof value !== "object") fail("객체 형식이 필요합니다.");
    if (Object.keys(value).some(key => !allowed.has(key))) fail("지원하지 않는 입력 필드입니다.");
  }
  function canonical(value) {
    if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
    if (value && typeof value === "object") return "{" + Object.keys(value).sort().map(k => JSON.stringify(k)+":"+canonical(value[k])).join(",") + "}";
    return JSON.stringify(value);
  }
  async function sha(bytes) {
    const digest = await crypto.subtle.digest("SHA-256", bytes);
    return Array.from(new Uint8Array(digest), n=>n.toString(16).padStart(2,"0")).join("");
  }
  async function identity(value) {
    fields(value, identityFields);
    if (Object.keys(value).length !== identityFields.size || value.schema !== "ocr.run.identity.v1") fail("실행 identity가 필요합니다.");
    for (const key of ["test_id","form_id","model","prompt_version","preprocessing_version"]) {
      if (typeof value[key] !== "string" || !/^[A-Za-z0-9_.-]{1,160}$/.test(value[key])) fail("실행 식별자가 잘못되었습니다.");
    }
    if (typeof value.round !== "string" || !/^[1-9][0-9]*$/.test(value.round)) fail("회차가 잘못되었습니다.");
    if (!/^[a-f0-9]{64}$/.test(value.photo_sha256)) fail("사진 hash가 필요합니다.");
    if (!Array.isArray(value.question_numbers) || value.question_numbers.length!==20 ||
        value.question_numbers.some((n,i)=>n!==i+1)) fail("identity 문항 집합이 잘못되었습니다.");
    const unsigned = {...value}; delete unsigned.identity_sha256;
    if (await sha(new TextEncoder().encode(canonical(unsigned))) !== value.identity_sha256) fail("실행 identity checksum 불일치");
    return structuredClone(value);
  }
  async function image(data, hash) {
    if (typeof data !== "string" || !/^data:image\/(png|jpeg);base64,[A-Za-z0-9+/=]+$/.test(data)) fail("이 실행의 비식별 이미지가 필요합니다.");
    const decoded = Uint8Array.from(atob(data.split(",")[1]), c=>c.charCodeAt(0));
    if (await sha(decoded) !== hash) fail("이미지 hash 불일치");
  }
  function answer(value) {
    if (typeof value !== "string" || !value.trim() || /[?\r\n]/.test(value)) fail("미확정 또는 여러 줄 답안은 최종화할 수 없습니다.");
    return value.trim();
  }
  async function parse(payload) {
    inspect(payload); fields(payload, topFields);
    if (payload.schema !== SCHEMA || payload.problem_count !== 20) fail("20문항 versioned review가 필요합니다.");
    const run = await identity(payload.identity);
    if (payload.test_id!==run.test_id || payload.round!==run.round) fail("시험 identity 불일치");
    if (!Array.isArray(payload.items) || payload.items.length!==20) fail("정확한 20문항이 필요합니다.");
    if (payload.photo_preview) await image(payload.photo_preview,run.photo_sha256);
    const seen = new Set(), items=[];
    for (const raw of payload.items) {
      fields(raw,itemFields);
      const n=raw.question_no;
      if (!Number.isInteger(n)||n<1||n>20||seen.has(n)) fail("문항 번호 중복·누락·범위 오류");
      seen.add(n);
      if(raw.identity_sha256!==run.identity_sha256) fail("다른 실행의 문항입니다.");
      if(!statuses.has(raw.status)) fail("알 수 없는 상태는 완료할 수 없습니다.");
      if(typeof raw.recognized!=="string") fail("원문 인식값이 필요합니다.");
      if(!Array.isArray(raw.candidates)||raw.candidates.some(v=>typeof v!=="string")) fail("후보 형식 오류");
      const candidates=[...new Set(raw.candidates.map(v=>v.trim()).filter(v=>v&&!/[?\r\n]/.test(v)))].slice(0,5);
      if(!Array.isArray(raw.warnings)||raw.warnings.some(v=>typeof v!=="string")) fail("경고 형식 오류");
      const history=Array.isArray(raw.review_history)?raw.review_history:[];
      if(history.length>200) fail("검토 이력이 너무 큽니다.");
      history.forEach(h=>{
        fields(h,new Set(["action","value","source"]));
        if(typeof h.action!=="string"||typeof h.value!=="string"||typeof h.source!=="string") fail("검토 이력 형식 오류");
      });
      if(raw.crop_preview) await image(raw.crop_preview,raw.crop_sha256);
      let status=raw.status;
      if(status==="safe_auto_grade" && (raw.needs_review!==false || !["none","clear"].includes(raw.uncertainty) || raw.warnings.length)) status="review_required";
      const final=status===raw.status?raw.final_answer:null;
      const source=status===raw.status?raw.source:null;
      if(finalStatuses.has(status)) {
        answer(final);
        if(!source || source==="retake_uploaded") fail("최종 답안 출처가 필요합니다.");
      } else if(final!=null||source!=null) fail("미확정 문항의 최종 답안은 비워야 합니다.");
      items.push({question_no:n,status,recognized:raw.recognized,candidates,warnings:[...new Set(raw.warnings)],
        final_answer:final??null,source:source??null,review_history:structuredClone(history),
        identity_sha256:run.identity_sha256,crop_preview:raw.crop_preview||"",crop_sha256:raw.crop_sha256||"",
        uncertainty:typeof raw.uncertainty==="string"?raw.uncertainty:"unverified",needs_review:raw.needs_review!==false,
        retake_image_attached:raw.retake_image_attached===true});
    }
    items.sort((a,b)=>a.question_no-b.question_no);
    return {schema:SCHEMA,identity:run,test_id:run.test_id,round:run.round,problem_count:20,items,
      photo_preview:payload.photo_preview||"",source:typeof payload.source==="string"?payload.source:"local_review",demo:payload.demo===true};
  }
  function finalize(payload, decisions) {
    if(!payload || payload.demo || payload.schema!==SCHEMA || !payload.identity ||
       !Array.isArray(payload.items) || payload.items.length!==20 ||
       new Set(payload.items.map(i=>i.question_no)).size!==20 ||
       payload.items.some(i=>!Number.isInteger(i.question_no)||i.question_no<1||i.question_no>20||
         i.identity_sha256!==payload.identity.identity_sha256))
      fail("demo·입력 없음·문항 불일치는 완료 검증에 사용할 수 없습니다.");
    const items=payload.items.map(item=>{
      const d=decisions.get(item.question_no);
      let final=item.final_answer, source=item.source, status=item.status;
      if(!finalStatuses.has(status)) {
        if(status!=="review_required" || !d?.confirmed) fail("미확정·재촬영·자료 불일치 문항이 있습니다.");
        final=d.final_answer;source=d.source;status=source;
      }
      answer(final);
      if(!finalStatuses.has(status) || !["safe_auto_grade","student_selected_candidate","student_direct_input",
        "safe_auto_grade_after_retake","student_selected_candidate_after_retake","student_direct_input_after_retake"].includes(source)) fail("최종 출처·상태 오류");
      return {question_no:item.question_no,status,recognized:item.recognized,candidates:[...item.candidates],
        warnings:[...item.warnings],final_answer:final.trim(),source,
        review_history:structuredClone(d?.history||item.review_history),identity_sha256:payload.identity.identity_sha256,
        uncertainty:item.uncertainty,needs_review:item.needs_review,
        ...(item.retake_image_attached?{retake_image_attached:true}:{})};
    });
    return {schema:SCHEMA,identity:structuredClone(payload.identity),test_id:payload.test_id,round:payload.round,problem_count:20,items};
  }
  root.OCRReviewContract={parse,finalize,answer,inspect,schema:SCHEMA};
})(globalThis);
