"""ส่งคำตอบไปตรวจที่เซิร์ฟเวอร์ — เทสต์ฝั่งหน้าเว็บ

เรื่องที่คุมไว้:
  * ถ้ายังไม่ตั้ง SCORING_ENDPOINT ทุกอย่างทำงานเหมือนเดิมเป๊ะ (ตรวจคะแนนในเครื่อง)
  * answersInBankOrder() คลายการสับข้อกลับได้ถูกต้อง — นี่คือจุดที่เคยให้คะแนนผิด
  * payload ที่ส่งไม่มีคะแนน ไม่มีเกณฑ์ผ่าน และไม่มีเฉลย
  * เมื่อตรวจที่เซิร์ฟเวอร์ หน้าเว็บต้องไม่เขียนคะแนนลงที่ไหนเลย
  * ส่งไม่สำเร็จต้องเข้าคิวแล้วส่งใหม่ได้ (สอบแบบไม่มีเน็ตยังทำได้)
  * โหลดคลังข้อสอบไม่สำเร็จต้องไม่ให้เริ่มสอบ แทนที่จะแจกข้อสอบที่ฝังมากับหน้าเว็บเงียบ ๆ
"""
import json

# คลังเล็ก ๆ ที่ตัวเลือกแต่ละอันข้อความไม่ซ้ำกัน เพื่อให้ยืนยันได้ว่า
# คำตอบที่ส่งไป ตรงกับตัวเลือกที่ผู้สมัครเห็นจริง ๆ
BANK = [
    {"sec": "A", "q": "Q0", "opts": [{"t": "0a", "p": 0}, {"t": "0b", "p": 1}, {"t": "0c", "p": 0}]},
    {"sec": "A", "q": "Q1", "opts": [{"t": "1a", "p": 1}, {"t": "1b", "p": 0}]},
    {"sec": "B", "q": "Q2", "opts": [{"t": "2a", "p": 0}, {"t": "2b", "p": 0}, {"t": "2c", "p": 2}]},
    {"sec": "B", "q": "Q3", "opts": [{"t": "3a", "p": 1}, {"t": "3b", "p": 0}]},
]

SETUP = """
(bank) => {
  ALL_QUESTIONS.TESTSET = bank;
  if (!TESTS.find(t => t.code === 'TESTSET'))
    TESTS.push({ code:'TESTSET', name:'Test Set', nameTH:'ชุดทดสอบ',
                 mins:10, passing:60, graded:true, custom:true });
  applicant = { name:'ผู้สมัคร ทดสอบ', email:'cand@example.com',
                pos:'Engineer', exp:'', phone:'', age:'' };
  sessions = [{ test: TESTS.find(t => t.code === 'TESTSET'), status:'in_progress',
                answers:[], _answersRandom:null, remainSecs:300,
                startedAt: Date.now(), violations:[] }];
  curSess = 0;
  _cloudBankLoaded = true;   // pretend the shared bank loaded
  // Record every POST instead of making one, so the payload can be inspected.
  window.__posts = [];
  window.__nextResponse = { ok:true, status:200, body:{ ok:true, recorded:true } };
  // /health เป็น GET ไม่มี body และแยกคิวบันทึกไว้ต่างหาก เพื่อไม่ให้ไปปนกับ
  // การส่งคำตอบที่เทสต์อื่นตรวจตามลำดับอยู่
  window.__gets = [];
  window.__healthResponse = { ok:true, status:200, body:{ ok:true } };
  window.fetch = async (url, init) => {
    const u = String(url);
    if (u.endsWith('/health')) {
      window.__gets.push(u);
      const h = window.__healthResponse;
      if (h === 'throw') throw new Error('network down');
      return { ok: h.ok, status: h.status, json: async () => h.body };
    }
    window.__posts.push({ url: u, body: (init && init.body) ? JSON.parse(init.body) : null });
    const r = window.__nextResponse;
    return { ok: r.ok, status: r.status, json: async () => r.body };
  };
  // What the candidate is actually shown, with the provenance tags.
  return getRandomizedQs(sessions[0])
    .map(q => ({ q: q.q, bi: q._bi, oi: q._oi, opts: q.opts.map(o => o.t) }));
}
"""


def _setup(page, endpoint="https://scoring.example.com"):
    shown = page.evaluate(SETUP, BANK)
    page.evaluate(f"() => {{ window.SCORING_ENDPOINT = {json.dumps(endpoint)}; }}")
    return shown


def _answer(page, picks):
    """ตอบตามตำแหน่งที่เห็นบนจอ (ลำดับที่สับแล้ว) แล้วส่งข้อสอบ"""
    page.evaluate(f"(picks) => {{ sessions[0]._answersRandom = picks; }}", picks)
    page.evaluate("() => window.doSubmit()")


def test_no_endpoint_means_nothing_changes(open_exam):
    """ยังไม่ตั้ง endpoint → ตรวจคะแนนในเครื่องเหมือนเดิม และไม่ส่งอะไรออกไป"""
    page = open_exam()
    shown = _setup(page, endpoint="")
    # ตอบถูกทุกข้อ โดยหาตำแหน่งตัวเลือกที่ถูกจากข้อความ
    best = {"Q0": "0b", "Q1": "1a", "Q2": "2c", "Q3": "3a"}
    picks = [q["opts"].index(best[q["q"]]) for q in shown]
    _answer(page, picks)

    assert page.evaluate("() => sessions[0].score") == 100
    assert page.evaluate("() => sessions[0].outcome") == "P"
    assert page.evaluate("() => sessions[0].raw") == 5
    assert page.evaluate("() => sessions[0].maxP") == 5
    assert page.evaluate("() => window.__posts.length") == 0


def test_the_submitted_answers_are_the_options_the_candidate_saw(open_exam):
    """คำตอบที่ส่งไปต้องชี้กลับไปที่ตัวเลือกที่ผู้สมัครเห็นจริง ไม่ใช่ตำแหน่งที่สับแล้ว

    นี่คือกับดักที่เคยทำให้ให้คะแนนผิดมาก่อน: ตำแหน่งบนจอกับตำแหน่งในคลังไม่ใช่อันเดียวกัน
    """
    page = open_exam()
    shown = _setup(page)
    # เลือกตัวเลือกที่สองของแต่ละข้อตามที่เห็นบนจอ (ข้อที่มีตัวเลือกเดียวจะเลือกตัวแรก)
    picks = [min(1, len(q["opts"]) - 1) for q in shown]
    _answer(page, picks)
    page.wait_for_function("() => window.__posts.length > 0")

    body = page.evaluate("() => window.__posts[0].body")
    answers = body["answers"]
    assert len(answers) == len(BANK)

    # สิ่งที่ผู้สมัครเห็นว่าเลือก เทียบกับสิ่งที่ส่งไปจริง
    for shown_q, pick in zip(shown, picks):
        chosen_text = shown_q["opts"][pick]
        base_index = shown_q["bi"]
        submitted_option = answers[base_index]
        assert BANK[base_index]["opts"][submitted_option]["t"] == chosen_text, (
            f"{shown_q['q']}: ผู้สมัครเลือก {chosen_text} "
            f"แต่ส่งไปเป็นตัวเลือกที่ {submitted_option} ของข้อ {base_index}"
        )


def test_unanswered_questions_stay_unanswered(open_exam):
    page = open_exam()
    shown = _setup(page)
    picks = [0 if i % 2 == 0 else None for i in range(len(shown))]
    _answer(page, picks)
    page.wait_for_function("() => window.__posts.length > 0")

    answers = page.evaluate("() => window.__posts[0].body.answers")
    for shown_q, pick in zip(shown, picks):
        if pick is None:
            assert answers[shown_q["bi"]] is None
        else:
            assert answers[shown_q["bi"]] is not None


def test_a_stale_out_of_range_pick_counts_as_unanswered(open_exam):
    """index ค้างจากคลังรุ่นก่อนต้องนับเป็นไม่ตอบ ไม่ใช่ส่งค่าเพี้ยนไป"""
    page = open_exam()
    shown = _setup(page)
    _answer(page, [99] * len(shown))
    page.wait_for_function("() => window.__posts.length > 0")

    answers = page.evaluate("() => window.__posts[0].body.answers")
    assert answers == [None] * len(BANK)


def test_the_payload_carries_no_score_and_no_pass_mark(open_exam):
    """หน้าเว็บต้องไม่ส่งคะแนนหรือเกณฑ์ผ่านไป — เซิร์ฟเวอร์เป็นคนตัดสิน"""
    page = open_exam()
    shown = _setup(page)
    _answer(page, [0] * len(shown))
    page.wait_for_function("() => window.__posts.length > 0")

    post = page.evaluate("() => window.__posts[0]")
    assert post["url"] == "https://scoring.example.com/score"
    body = post["body"]
    assert set(body) == {"testCode", "sitting", "attempt", "candidate",
                         "answers", "fingerprint", "meta"}
    assert "passing" not in body["meta"]
    # เทียบเป็น "ชื่อฟิลด์" ไม่ใช่ substring — ไม่งั้น "p" จะไปแมตช์กับ phone/pos/exp
    # ซึ่งเป็นข้อมูลผู้สมัครที่ต้องส่งอยู่แล้ว
    sent = json.dumps(body)
    for leaked in ("score", "outcome", "raw", "maxP", "sections", "percentile",
                   "p", "why", "passing"):
        assert f'"{leaked}":' not in sent, f"payload ส่งฟิลด์ {leaked} ไปด้วย"
    # ฟิลด์ที่ต้องมี คือข้อมูลผู้สมัครกับคำตอบ เท่านั้น
    assert set(body["candidate"]) == {"key", "name", "email", "phone", "age", "exp", "pos"}
    assert body["candidate"]["key"] == "cand@example.com"
    assert body["meta"]["mins"] == 10
    assert body["meta"]["remainSecs"] == 300


def test_the_page_keeps_no_score_of_its_own(open_exam):
    """เมื่อเซิร์ฟเวอร์ตรวจ หน้าเว็บต้องไม่มีคะแนนค้างอยู่ และไม่เขียนผลลง localStorage"""
    page = open_exam()
    shown = _setup(page)
    _answer(page, [0] * len(shown))
    page.wait_for_function("() => window.__posts.length > 0")

    assert page.evaluate("() => sessions[0].status") == "completed"
    for field in ("score", "outcome", "raw", "maxP", "sections", "percentile"):
        assert page.evaluate(f"() => sessions[0].{field}") is None, f"{field} ยังมีค่าค้างอยู่"
    # ไม่มีผลสอบถูกเขียนลงเครื่อง — ฝั่งเซิร์ฟเวอร์เป็นคนเขียน
    assert page.evaluate("() => JSON.parse(localStorage.getItem('hma_exam_records') || '[]').length") == 0
    assert page.evaluate("() => JSON.parse(localStorage.getItem('hma_result_snapshots') || '[]').length") == 0


def test_every_test_in_one_sitting_shares_a_sitting_id(open_exam):
    page = open_exam()
    shown = _setup(page)
    _answer(page, [0] * len(shown))
    page.wait_for_function("() => window.__posts.length > 0")
    first = page.evaluate("() => window.__posts[0].body.sitting")

    # ชุดที่สองของการสอบครั้งเดียวกัน
    page.evaluate("""() => {
      sessions[0].status = 'in_progress';
      sessions[0]._randomizedQs = undefined;
      window.doSubmit();
    }""")
    page.wait_for_function("() => window.__posts.length > 1")
    assert page.evaluate("() => window.__posts[1].body.sitting") == first
    assert first.startswith("s")
    # ต้องใช้ได้เป็น document id — ตัวอักษร ตัวเลข ขีด ขีดล่าง เท่านั้น
    assert all(c.isalnum() or c in "-_" for c in first), first


def test_a_failed_send_is_queued_and_retried(open_exam):
    """ส่งไม่ได้ต้องเข้าคิว แล้วส่งใหม่สำเร็จเมื่อเชื่อมต่อได้ — สอบแบบไม่มีเน็ตยังทำได้"""
    page = open_exam()
    shown = _setup(page)
    page.evaluate("() => { window.__nextResponse = { ok:false, status:503, body:{ code:'down' } }; }")
    _answer(page, [0] * len(shown))
    page.wait_for_function(
        "() => JSON.parse(localStorage.getItem('hma_answer_queue') || '[]').length > 0")

    queued = page.evaluate("() => JSON.parse(localStorage.getItem('hma_answer_queue'))")
    assert len(queued) == 1
    assert queued[0]["submission"]["testCode"] == "TESTSET"

    # กลับมาออนไลน์แล้วส่งใหม่
    page.evaluate("() => { window.__nextResponse = { ok:true, status:200, body:{ ok:true } }; }")
    page.evaluate("() => flushAnswerQueue()")
    page.wait_for_function(
        "() => JSON.parse(localStorage.getItem('hma_answer_queue') || '[]').length === 0")


def test_a_refusal_that_will_not_improve_is_not_queued(open_exam):
    """4xx คือคำตอบชุดนี้ส่งใหม่ก็ไม่ผ่าน — ไม่ต้องวนเข้าคิว"""
    page = open_exam()
    shown = _setup(page)
    page.evaluate(
        "() => { window.__nextResponse = { ok:false, status:400, body:{ code:'bad_answers' } }; }")
    _answer(page, [0] * len(shown))
    page.wait_for_function("() => window.__posts.length > 0")
    assert page.evaluate(
        "() => JSON.parse(localStorage.getItem('hma_answer_queue') || '[]').length") == 0


def test_a_sitting_the_endpoint_already_holds_clears_the_queue(open_exam):
    """409 already_graded คือ 'ถึงแล้ว' ไม่ใช่ล้มเหลว — ไม่ควรค้างคิวตลอดไป"""
    page = open_exam()
    _setup(page)
    page.evaluate("""() => {
      localStorage.setItem('hma_answer_queue', JSON.stringify([
        { submission: { testCode:'TESTSET', sitting:'s-old', answers:[0,0,0,0] }, at: 1 }]));
      window.__nextResponse = { ok:false, status:409, body:{ code:'already_graded' } };
    }""")
    page.evaluate("() => flushAnswerQueue()")
    page.wait_for_function(
        "() => JSON.parse(localStorage.getItem('hma_answer_queue') || '[]').length === 0")


def test_a_test_cannot_be_started_when_the_shared_bank_did_not_load(open_exam):
    """โหลดคลังไม่สำเร็จแล้วยังให้สอบ = ผู้สมัครได้ข้อสอบที่ฝังมากับหน้าเว็บแบบเงียบ ๆ

    วัดจากผลจริงที่ openTest() ทำ (เปิดหน้า p-test และเขียนชื่อชุดสอบ)
    ไม่ใช่จากตัวแปรที่เทสต์ตั้งเอง
    """
    page = open_exam()
    _setup(page)

    blocked = page.evaluate("""() => {
      _cloudBankLoaded = false;
      nav('p-dash');
      document.getElementById('t-testname').textContent = '';
      window.openTest();
      return {
        active:   document.querySelector('.page.active') ? document.querySelector('.page.active').id : null,
        testname: document.getElementById('t-testname').textContent,
      };
    }""")
    assert blocked["active"] == "p-dash", "เริ่มสอบไปแล้วทั้งที่ยังโหลดคลังไม่ได้"
    assert blocked["testname"] == ""

    # และเมื่อโหลดคลังได้แล้วก็เริ่มสอบได้ตามปกติ
    allowed = page.evaluate("""() => {
      _cloudBankLoaded = true;
      window.openTest();
      return {
        active:   document.querySelector('.page.active') ? document.querySelector('.page.active').id : null,
        testname: document.getElementById('t-testname').textContent,
      };
    }""")
    assert allowed["active"] == "p-test"
    assert allowed["testname"] == "ชุดทดสอบ"


def test_a_test_starts_normally_when_scoring_is_still_local(open_exam):
    """ยังไม่ตั้ง endpoint → การ์ดตัวนี้ต้องไม่ขัดขวางอะไรเลย แม้ยังไม่ได้โหลดคลัง"""
    page = open_exam()
    _setup(page, endpoint="")
    active = page.evaluate("""() => {
      _cloudBankLoaded = false;
      nav('p-dash');
      window.openTest();
      return document.querySelector('.page.active') ? document.querySelector('.page.active').id : null;
    }""")
    assert active == "p-test"


def test_the_question_set_fingerprint_tracks_the_questions(open_exam):
    """ลายนิ้วมือต้องนิ่งเมื่อข้อสอบไม่เปลี่ยน และเปลี่ยนเมื่อข้อสอบเปลี่ยน"""
    page = open_exam()
    _setup(page)
    first = page.evaluate("() => questionSetFingerprint('TESTSET')")
    again = page.evaluate("() => questionSetFingerprint('TESTSET')")
    assert first == again
    assert len(first) == 32

    changed = page.evaluate("""async () => {
      ALL_QUESTIONS.TESTSET[0].q = 'Q0 edited';
      return await questionSetFingerprint('TESTSET');
    }""")
    assert changed != first

    # ลำดับ key ใน object ไม่ควรทำให้ลายนิ้วมือเปลี่ยน
    reordered = page.evaluate("""async () => {
      ALL_QUESTIONS.TESTSET[0] = { opts: ALL_QUESTIONS.TESTSET[0].opts,
                                   q: 'Q0 edited', sec: ALL_QUESTIONS.TESTSET[0].sec };
      return await questionSetFingerprint('TESTSET');
    }""")
    assert reordered == changed


def test_the_attempt_number_counts_sittings_when_the_server_scores(open_exam):
    """ตรวจที่เซิร์ฟเวอร์แล้วหน้าเว็บไม่เขียน record ลงเครื่อง — เลข "ครั้งที่" ต้องยังเดินถูก

    ไม่งั้นการสอบซ้ำจะขึ้นว่า "ครั้งที่ 1" ตลอด
    """
    page = open_exam()
    shown = _setup(page)
    _answer(page, [0] * len(shown))
    page.wait_for_function("() => window.__posts.length > 0")
    assert page.evaluate("() => window.__posts[0].body.attempt") == 1
    first_sitting = page.evaluate("() => window.__posts[0].body.sitting")

    # กลับมาสอบใหม่เป็นครั้งที่สอง (เครื่องเดิม คนเดิม)
    page.evaluate("""() => {
      applicant._sitting = undefined;
      sessions[0].status = 'in_progress';
      sessions[0]._randomizedQs = undefined;
      window.doSubmit();
    }""")
    page.wait_for_function("() => window.__posts.length > 1")
    second = page.evaluate("() => window.__posts[1].body")
    assert second["attempt"] == 2, "การสอบครั้งที่สองยังขึ้นว่าครั้งที่ 1"
    assert second["sitting"] != first_sitting

    # บันทึกที่เก็บไว้ต้องมีแต่ id ไม่มีคะแนนหรือคำตอบติดไปด้วย
    log = page.evaluate("() => localStorage.getItem('hma_sitting_log')")
    for leaked in ('"score"', '"answers"', '"p"', '"outcome"'):
        assert leaked not in log, f"sitting log เก็บ {leaked} ไปด้วย"


def test_two_sittings_stay_separate_rows_in_the_hr_table(open_exam):
    """สองการสอบที่เลข "ครั้งที่" ชนกัน (คนละเครื่อง) ต้องไม่ถูกรวมเป็นแถวเดียว"""
    page = open_exam()
    rows = page.evaluate("""() => {
      const base = {
        candidate_key:'somchai@example.com', email:'somchai@example.com',
        name:'สมชาย ทดสอบ', position:'ช่างเทคนิค', datetime:'3/8/2569 10:00:00',
        IQ_score:70, IQ_outcome:'P', IQ_total:25, IQ_passing:60, _complete:true,
      };
      localStorage.setItem('hma_exam_records', JSON.stringify([
        { ...base, sitting:'s-first',  attempt:1 },
        { ...base, sitting:'s-second', attempt:1, IQ_score:85 },
      ]));
      return getStoredRows().filter(r => r.test === 'IQ').map(r => ({ id:r.id, score:r.score }));
    }""")
    assert len(rows) == 2, "สองการสอบรวมเป็นแถวเดียว"
    assert len({r["id"] for r in rows}) == 2
    assert sorted(r["score"] for r in rows) == [70, 85]


def test_records_without_a_sitting_still_group_by_attempt(open_exam):
    """record รุ่นก่อนที่ยังไม่มี sitting ต้องแสดงได้เหมือนเดิม"""
    page = open_exam()
    rows = page.evaluate("""() => {
      const base = {
        candidate_key:'somchai@example.com', email:'somchai@example.com',
        name:'สมชาย ทดสอบ', position:'ช่างเทคนิค', datetime:'3/8/2569 10:00:00',
        IQ_score:70, IQ_outcome:'P', IQ_total:25, IQ_passing:60, _complete:true,
      };
      localStorage.setItem('hma_exam_records', JSON.stringify([
        { ...base, attempt:1 },
        { ...base, attempt:2, IQ_score:85 },
      ]));
      return getStoredRows().filter(r => r.test === 'IQ').map(r => r.id);
    }""")
    assert len(set(rows)) == 2


# ── เฉลยฝั่งผู้ดูแล: โหลดจากระบบ และกันการเผลอทับเฉลยหาย ──────────────

ADMIN_SETUP = """
() => {
  window.SCORING_ENDPOINT = 'https://scoring.example.com';
  _cloudSettingsLoaded = true;
  _fullBankLoaded = false;
  // ยืนหมัน Firebase ให้พอใช้: ล็อกอินแล้ว และเขียน config/settings ได้
  window.__settingsWrites = [];
  window.db = { collection: () => ({ doc: () => ({
    set: async (data) => { window.__settingsWrites.push(data); },
  }) }) };
  window.fbAuth = { currentUser: { getIdToken: async () => 'admin-id-token' } };
  // Firebase ตัวจริงโหลดจาก CDN ซึ่งถูกบล็อกในเครื่องที่รันเทสต์ — ใส่เท่าที่ใช้
  window.firebase = { firestore: { FieldValue: { serverTimestamp: () => 'ts' } } };
  window.__requests = [];
  window.__bankResponse = { ok:true, status:200, body:{ ok:true, bank:{
    IQ: [
      { sec:'A', q:'Q0', opts:[{t:'0a',p:0},{t:'0b',p:1}], why:'because' },
      { sec:'A', q:'Q1', opts:[{t:'1a',p:1},{t:'1b',p:0}] },
    ],
  } } };
  window.__publishResponse = { ok:true, status:200, body:{ ok:true } };
  window.fetch = async (url, init = {}) => {
    const method = init.method || 'GET';
    window.__requests.push({
      url: String(url), method,
      auth: (init.headers || {}).authorization || null,
      body: init.body ? JSON.parse(init.body) : null,
    });
    const r = method === 'GET' ? window.__bankResponse : window.__publishResponse;
    return { ok: r.ok, status: r.status, json: async () => r.body };
  };
  return true;
}
"""


def test_an_admin_loads_the_answer_key_from_the_endpoint(open_exam):
    page = open_exam()
    page.evaluate(ADMIN_SETUP)
    ok = page.evaluate("() => adminLoadFullBank()")
    assert ok is True

    req = page.evaluate("() => window.__requests[0]")
    assert req["url"] == "https://scoring.example.com/admin/bank"
    assert req["method"] == "GET"
    assert req["auth"] == "Bearer admin-id-token"

    # ข้อสอบในหน้าเว็บต้องมีเฉลยแล้ว เพื่อให้หน้าแก้ข้อสอบกับหน้าทบทวนของ HR ใช้ได้
    assert page.evaluate("() => ALL_QUESTIONS.IQ[0].opts[1].p") == 1
    assert page.evaluate("() => ALL_QUESTIONS.IQ[0].why") == "because"
    assert page.evaluate("() => _fullBankLoaded") is True


def test_an_account_without_the_right_role_is_refused_quietly(open_exam):
    """บัญชี HR/viewer ไม่มีสิทธิ์เห็นเฉลย — ไม่ใช่ error ที่ต้องตะโกน"""
    page = open_exam()
    page.evaluate(ADMIN_SETUP)
    page.evaluate("() => { window.__bankResponse = { ok:false, status:403, body:{ code:'forbidden' } }; }")
    ok = page.evaluate("() => adminLoadFullBank()")
    assert ok is False
    assert page.evaluate("() => _fullBankLoaded") is False


def test_saving_publishes_the_whole_bank_to_the_endpoint(open_exam):
    """ต้องไม่เขียน config/bank จากเบราว์เซอร์ — ส่งทั้งคลังให้ระบบไปแยกเอง"""
    page = open_exam()
    page.evaluate(ADMIN_SETUP)
    page.evaluate("() => adminLoadFullBank()")
    page.wait_for_function("() => _fullBankLoaded")

    res = page.evaluate("() => cloudSaveQuestionBank()")
    assert res["bankOk"] is True

    posts = page.evaluate("() => window.__requests.filter(r => r.method === 'POST')")
    assert len(posts) == 1
    assert posts[0]["url"] == "https://scoring.example.com/admin/bank"
    assert posts[0]["auth"] == "Bearer admin-id-token"
    # คลังที่ส่งไปต้องมีเฉลยครบ
    assert posts[0]["body"]["bank"]["IQ"][0]["opts"][1]["p"] == 1
    # config/settings ยังเขียนเหมือนเดิม (ไม่ใช่ความลับ) แต่ต้องไม่มี customQuestions
    writes = page.evaluate("() => window.__settingsWrites")
    assert writes, "config/settings ไม่ได้ถูกเขียน"
    assert not any("customQuestions" in w for w in writes), "ยังเขียนคลังข้อสอบลง Firestore จากเบราว์เซอร์"


def test_saving_a_bank_that_lost_its_answer_key_is_refused(open_exam):
    """กับดักที่อันตรายที่สุด: ผู้ดูแลที่หน้าเว็บมีแต่โจทย์ (ไม่มีเฉลย) กดบันทึก
    = ทับเฉลยจริงหายทั้งระบบ ต้องไม่ยอมบันทึก
    """
    page = open_exam()
    page.evaluate(ADMIN_SETUP)
    page.evaluate("""() => {
      // หน้าเว็บโหลดมาได้แต่ครึ่งที่เปิดสาธารณะ — ตัวเลือกไม่มี p
      _fullBankLoaded = true;   // แม้ธงจะบอกว่าโหลดแล้ว ก็ยังต้องตรวจรูปร่างจริง
      localStorage.setItem('hma_custom_questions', JSON.stringify({
        IQ: [{ sec:'A', q:'Q0', opts:[{t:'0a'},{t:'0b'}] }],
      }));
    }""")
    res = page.evaluate("() => cloudSaveQuestionBank()")
    assert res["bankOk"] is False
    assert page.evaluate("() => window.__requests.filter(r => r.method === 'POST').length") == 0, \
        "ส่งคลังที่ไม่มีเฉลยขึ้นระบบไปแล้ว"


def test_saving_before_the_answer_key_arrives_is_refused(open_exam):
    page = open_exam()
    page.evaluate(ADMIN_SETUP)
    page.evaluate("""() => {
      _fullBankLoaded = false;
      localStorage.setItem('hma_custom_questions', JSON.stringify({
        IQ: [{ sec:'A', q:'Q0', opts:[{t:'0a',p:0},{t:'0b',p:1}] }],
      }));
    }""")
    res = page.evaluate("() => cloudSaveQuestionBank()")
    assert res["bankOk"] is False
    assert page.evaluate("() => window.__requests.filter(r => r.method === 'POST').length") == 0


def test_an_empty_test_set_does_not_count_as_a_lost_answer_key(open_exam):
    """ชุดสอบที่ยังไม่มีข้อ ไม่ใช่ชุดที่เฉลยหาย — ต้องไม่บล็อกการบันทึก"""
    page = open_exam()
    page.evaluate(ADMIN_SETUP)
    missing = page.evaluate("""() => banksMissingAnswers({
      EMPTY: [],
      GOOD:  [{ opts:[{t:'a',p:0},{t:'b',p:1}] }],
      BAD:   [{ opts:[{t:'a'},{t:'b'}] }],
      NOOPTS:[{ q:'no options at all' }],
    })""")
    assert missing == ["BAD", "NOOPTS"]


def test_a_failed_publish_is_reported_rather_than_claimed_as_saved(open_exam):
    page = open_exam()
    page.evaluate(ADMIN_SETUP)
    page.evaluate("() => adminLoadFullBank()")
    page.wait_for_function("() => _fullBankLoaded")
    page.evaluate("() => { window.__publishResponse = { ok:false, status:503, body:{ code:'down' } }; }")
    res = page.evaluate("() => cloudSaveQuestionBank()")
    assert res["bankOk"] is False


def test_without_an_endpoint_the_bank_still_goes_to_firestore(open_exam):
    """ยังไม่เปิดสวิตช์ → ทุกอย่างเหมือนเดิม"""
    page = open_exam()
    page.evaluate(ADMIN_SETUP)
    page.evaluate("""() => {
      window.SCORING_ENDPOINT = '';
      localStorage.setItem('hma_custom_questions', JSON.stringify({
        IQ: [{ sec:'A', q:'Q0', opts:[{t:'0a',p:0},{t:'0b',p:1}] }],
      }));
    }""")
    res = page.evaluate("() => cloudSaveQuestionBank()")
    assert res["bankOk"] is True
    assert page.evaluate("() => window.__requests.length") == 0, "ยังยิงไปที่ endpoint ทั้งที่ยังไม่เปิดสวิตช์"
    writes = page.evaluate("() => window.__settingsWrites")
    assert any("customQuestions" in w for w in writes), "ไม่ได้เขียนคลังลง Firestore ตามพฤติกรรมเดิม"


# ── เฉลยไม่อยู่ในหน้าเว็บแล้ว ────────────────────────────────────────────

def test_the_page_ships_no_answer_key(open_exam):
    """ข้อสอบที่ฝังมากับหน้าเว็บต้องไม่มีเฉลยและไม่มีคำอธิบายเลย"""
    page = open_exam()
    leaks = page.evaluate("""() => {
      const out = { scored: [], explained: [], counts: {} };
      const scan = (label, qs) => {
        out.counts[label] = qs.length;
        qs.forEach((q, i) => {
          if ((q.opts || []).some(o => o && typeof o.p === 'number')) out.scored.push(label + '[' + i + ']');
          if (q.why != null || q.exp != null) out.explained.push(label + '[' + i + ']');
        });
      };
      Object.keys(ALL_QUESTIONS).forEach(c => scan(c, ALL_QUESTIONS[c]));
      scan('PERS_DEFAULTS', DEFAULT_PERS_QUESTIONS);
      return out;
    }""")
    assert leaks["scored"] == [], f"ยังมีเฉลยในหน้าเว็บ: {leaks['scored'][:5]}"
    assert leaks["explained"] == [], f"ยังมีคำอธิบายในหน้าเว็บ: {leaks['explained'][:5]}"
    # และโจทย์ยังอยู่ครบ ไม่ใช่ว่าตัดทิ้งไปทั้งก้อน
    assert leaks["counts"]["PERS_DEFAULTS"] == 60
    assert sum(v for k, v in leaks["counts"].items() if k != "PERS_DEFAULTS") == 116


def test_a_test_cannot_start_when_nothing_can_score_it(open_exam):
    """ไม่มีเฉลยในเครื่อง และไม่มีระบบตรวจคะแนน → ต้องไม่ให้เริ่มสอบ

    ถ้าปล่อยให้เริ่ม ทุกคนจะได้คะแนนศูนย์ ซึ่งดูเหมือนผลสอบจริง
    """
    page = open_exam()
    _setup(page, endpoint="")
    blocked = page.evaluate("""() => {
      // คลังแบบที่เผยแพร่จริง: มีโจทย์ ไม่มีเฉลย
      ALL_QUESTIONS.TESTSET = ALL_QUESTIONS.TESTSET.map(q => ({ ...q, opts: q.opts.map(o => ({ t: o.t })) }));
      sessions[0]._randomizedQs = undefined;
      nav('p-dash');
      document.getElementById('t-testname').textContent = '';
      window.openTest();
      return document.querySelector('.page.active').id;
    }""")
    assert blocked == "p-dash", "เริ่มสอบไปแล้วทั้งที่ไม่มีอะไรให้คะแนนได้"
    assert page.evaluate("() => canGradeLocally('TESTSET')") is False


def test_a_test_starts_once_there_is_an_endpoint(open_exam):
    """มีระบบตรวจคะแนนแล้ว ก็เริ่มสอบได้ ทั้งที่หน้าเว็บไม่มีเฉลย"""
    page = open_exam()
    _setup(page)   # ตั้ง endpoint + _cloudBankLoaded ให้แล้ว
    page.evaluate("""() => {
      // คลังไม่มีเฉลย เหมือนครึ่งที่เผยแพร่จริง
      ALL_QUESTIONS.TESTSET = ALL_QUESTIONS.TESTSET.map(q => ({ ...q, opts: q.opts.map(o => ({ t: o.t })) }));
      sessions[0]._randomizedQs = undefined;
    }""")
    assert page.evaluate("() => canGradeLocally('TESTSET')") is False
    active = page.evaluate("""() => {
      nav('p-dash');
      window.openTest();
      return document.querySelector('.page.active').id;
    }""")
    assert active == "p-test"


def test_an_admin_holding_the_key_can_still_grade_locally(open_exam):
    """ผู้ดูแลที่ดึงเฉลยมาแล้ว canGradeLocally ต้องเป็นจริง (หน้าทบทวนของ HR ใช้)"""
    page = open_exam()
    _setup(page)
    assert page.evaluate("() => canGradeLocally('TESTSET')") is True


def test_the_fingerprint_ignores_whether_this_browser_holds_the_answers(open_exam):
    """ผู้ดูแลที่ล็อกอินอยู่จะมีคลังฉบับมีเฉลย ผู้สมัครมีฉบับไม่มีเฉลย
    ทั้งสองต้องได้ลายนิ้วมือเดียวกัน ไม่งั้นผู้ดูแลจะส่งข้อสอบไม่ได้เลย (stale_bank)
    """
    page = open_exam()
    _setup(page)   # BANK มีเฉลย (p) อยู่
    with_answers = page.evaluate("() => questionSetFingerprint('TESTSET')")

    without_answers = page.evaluate("""async () => {
      // คลังแบบที่เผยแพร่จริง: ตัด p และคำอธิบายออก
      ALL_QUESTIONS.TESTSET = ALL_QUESTIONS.TESTSET.map(q => {
        const { why, exp, ...rest } = q;
        return { ...rest, opts: q.opts.map(o => ({ t: o.t })) };
      });
      return await questionSetFingerprint('TESTSET');
    }""")
    assert with_answers == without_answers, "ลายนิ้วมือเปลี่ยนตามว่ามีเฉลยอยู่ในเครื่องหรือไม่"


def test_the_fingerprint_still_changes_when_the_questions_change(open_exam):
    """แต่ต้องยังจับได้เมื่อตัวข้อสอบเปลี่ยนจริง ไม่งั้นด่านนี้ไร้ความหมาย"""
    page = open_exam()
    _setup(page)
    before = page.evaluate("() => questionSetFingerprint('TESTSET')")

    edited = page.evaluate("""async () => {
      ALL_QUESTIONS.TESTSET[0].q = 'คำถามที่ถูกแก้';
      return await questionSetFingerprint('TESTSET');
    }""")
    assert edited != before

    reordered = page.evaluate("""async () => {
      ALL_QUESTIONS.TESTSET[0].opts = [ALL_QUESTIONS.TESTSET[0].opts[1], ALL_QUESTIONS.TESTSET[0].opts[0]];
      return await questionSetFingerprint('TESTSET');
    }""")
    assert reordered != edited, "สลับลำดับตัวเลือกแล้วลายนิ้วมือไม่เปลี่ยน"


def test_the_old_result_queue_is_not_replayed_once_the_server_scores(open_exam):
    """คิวเก่าเก็บคะแนนที่เบราว์เซอร์คิดเอง และกฎใหม่ห้ามเบราว์เซอร์เขียนผลสอบแล้ว
    ถ้ายัง replay จะล้มเหลวทุกครั้งที่เปิดหน้าเว็บไปตลอด และเป็นการพยายามเขียน
    สิ่งที่ระบบตั้งใจไม่ให้เชื่อ
    """
    page = open_exam()
    page.evaluate(ADMIN_SETUP)
    page.evaluate("""() => {
      window.__writes = [];
      window.db = { collection: (c) => ({
        add: async (d) => { window.__writes.push([c, d]); },
        doc: () => ({ set: async () => {} }),
      }) };
      localStorage.setItem('hma_cloud_pending', JSON.stringify([
        { rec: { candidate_key:'old@example.com', IQ_score: 99 }, at: 1 },
      ]));
    }""")
    page.evaluate("() => cloudFlushPending()")
    assert page.evaluate("() => window.__writes.length") == 0, "ยัง replay คิวเก่าอยู่"
    # ไม่ลบข้อมูลของผู้สมัครทิ้งเอง แค่ไม่ส่ง
    assert page.evaluate(
        "() => JSON.parse(localStorage.getItem('hma_cloud_pending')).length") == 1


def test_the_old_result_queue_still_works_while_scoring_is_local(open_exam):
    """ยังไม่เปิดสวิตช์ → พฤติกรรมเดิมต้องไม่เปลี่ยน"""
    page = open_exam()
    page.evaluate(ADMIN_SETUP)
    page.evaluate("""() => {
      window.SCORING_ENDPOINT = '';
      window.__writes = [];
      window.db = { collection: (c) => ({
        add: async (d) => { window.__writes.push([c, d]); },
        doc: () => ({ set: async () => {} }),
      }) };
      localStorage.setItem('hma_cloud_pending', JSON.stringify([
        { rec: { candidate_key:'old@example.com', IQ_score: 99 }, at: 1 },
      ]));
    }""")
    page.evaluate("() => cloudFlushPending()")
    page.wait_for_function("() => window.__writes.length > 0")
    assert page.evaluate("() => window.__writes[0][0]") == "exam_records"


# ── ไม่ให้ผู้สมัครหายไปเงียบ ๆ ──────────────────────────────────
#
# เมื่อตรวจคะแนนที่เซิร์ฟเวอร์ หน้าเว็บไม่เขียนอะไรลงเครื่องเลย การสอบจึง "มีอยู่"
# ก็ต่อเมื่อเซิร์ฟเวอร์ตรวจไปแล้วอย่างน้อยหนึ่งชุด ผู้สมัครที่ส่งคำตอบไม่สำเร็จจึง
# ไม่เหลือร่องรอยใด ๆ และ HR แยกไม่ออกจากคนที่ไม่เคยมา


def _reg_posts(page):
    return page.evaluate(
        "() => window.__posts.filter(p => p.url.endsWith('/register')).map(p => p.body)")


def test_starting_a_sitting_tells_the_endpoint_who_is_sitting_it(open_exam):
    page = open_exam()
    _setup(page)
    page.evaluate("""() => {
        applicant = { name:'สมชาย ทดสอบ', email:'somchai@example.com', pos:'ช่างเทคนิค',
                      phone:'0812345678', age:28, exp:3 };
        pendingReg = { ...applicant, postype:'', preset:null };
        startRegisteredSession();
    }""")
    page.wait_for_function("() => window.__posts.some(p => p.url.endsWith('/register'))")
    body = _reg_posts(page)[0]
    assert body["candidate"]["key"] == "somchai@example.com"
    assert body["candidate"]["name"] == "สมชาย ทดสอบ"
    assert body["candidate"]["phone"] == "0812345678"
    assert body["candidate"]["pos"] == "ช่างเทคนิค"
    assert body["sitting"], "ไม่ได้บอกว่าเป็นการสอบครั้งไหน"
    # ไม่มีคะแนนและไม่มีคำตอบติดไปด้วย — นี่คือการแจ้งตัวตน ไม่ใช่การส่งข้อสอบ
    assert "answers" not in body and "score" not in body


def test_a_registration_that_cannot_be_sent_is_queued_and_retried(open_exam):
    page = open_exam()
    _setup(page)
    page.evaluate("""() => {
        window.__nextResponse = { ok:false, status:503, body:{ code:'down' } };
        applicant = { name:'สมชาย ทดสอบ', email:'somchai@example.com', pos:'ช่างเทคนิค',
                      phone:'', age:'', exp:'' };
        pendingReg = { ...applicant, postype:'', preset:null };
        startRegisteredSession();
    }""")
    page.wait_for_function(
        "() => JSON.parse(localStorage.getItem('hma_registration_queue') || '[]').length > 0")

    page.evaluate("() => { window.__nextResponse = { ok:true, status:200, body:{ ok:true } }; }")
    page.evaluate("() => flushRegistrationQueue()")
    page.wait_for_function(
        "() => JSON.parse(localStorage.getItem('hma_registration_queue') || '[]').length === 0")


def test_a_registration_the_endpoint_refuses_outright_is_not_queued(open_exam):
    # 4xx คือรูปแบบผิด ส่งใหม่กี่ครั้งก็ผิดเหมือนเดิม ไม่ต้องวนค้างคิว
    page = open_exam()
    _setup(page)
    page.evaluate("""async () => {
        window.__nextResponse = { ok:false, status:400, body:{ code:'bad_request' } };
        applicant = { name:'สมชาย', email:'somchai@example.com', pos:'x', phone:'', age:'', exp:'' };
        await registerSitting();
    }""")
    assert page.evaluate(
        "() => window.__posts.filter(p => p.url.endsWith('/register')).length") == 1
    assert page.evaluate(
        "() => JSON.parse(localStorage.getItem('hma_registration_queue') || '[]').length") == 0


def test_registering_never_blocks_the_candidate_from_starting(open_exam):
    # งานเอกสารล้มเหลวไม่ใช่เหตุให้ห้ามคนเข้าสอบ
    page = open_exam()
    _setup(page)
    page.evaluate("""() => {
        window.__nextResponse = { ok:false, status:503, body:{} };
        applicant = { name:'สมชาย', email:'somchai@example.com', pos:'x', phone:'', age:'', exp:'' };
        pendingReg = { ...applicant, postype:'', preset:null };
        startRegisteredSession();
    }""")
    assert page.locator("#p-dash").is_visible()


# ── ไม่ให้เริ่มสอบถ้าระบบตรวจคะแนนไม่ตอบ ────────────────────────


def test_a_test_does_not_start_while_the_endpoint_is_unreachable(open_exam):
    page = open_exam()
    _setup(page)
    page.evaluate("""() => {
        window.__healthResponse = { ok:false, status:503, body:{} };
        sessions[0].status = 'not_started';
    }""")
    page.evaluate("() => startTest(0)")
    page.wait_for_function("() => (window.__gets || []).length > 0")
    page.wait_for_timeout(150)
    assert page.evaluate("() => (document.querySelector('.page.active')||{}).id") != "p-test"
    assert "ติดต่อไม่ได้" in page.inner_text("#toast")


def test_a_test_starts_once_the_endpoint_answers(open_exam):
    page = open_exam()
    _setup(page)
    page.evaluate("() => { sessions[0].status = 'not_started'; }")
    page.evaluate("() => startTest(0)")
    page.wait_for_function("() => (document.querySelector('.page.active')||{}).id === 'p-test'")
    assert page.evaluate("() => (window.__gets || []).length") == 1


def test_the_endpoint_is_only_asked_once_while_it_keeps_answering(open_exam):
    # เช็กทุกครั้งที่กดเริ่มคือการถ่วงเวลาผู้สมัครโดยไม่ได้อะไรเพิ่ม
    page = open_exam()
    _setup(page)
    page.evaluate("() => { sessions[0].status = 'not_started'; }")
    page.evaluate("() => startTest(0)")
    page.wait_for_function("() => (document.querySelector('.page.active')||{}).id === 'p-test'")
    page.evaluate("() => startTest(0)")
    page.wait_for_timeout(150)
    assert page.evaluate("() => (window.__gets || []).length") == 1


def test_a_candidate_who_was_turned_away_can_try_again(open_exam):
    # ความล้มเหลวครั้งแรกต้องไม่ถูกจำไปตลอดทั้งเซสชัน
    page = open_exam()
    _setup(page)
    page.evaluate("""() => {
        window.__healthResponse = { ok:false, status:503, body:{} };
        sessions[0].status = 'not_started';
    }""")
    page.evaluate("() => startTest(0)")
    page.wait_for_function("() => (window.__gets || []).length > 0")
    page.evaluate("() => { window.__healthResponse = { ok:true, status:200, body:{ ok:true } }; }")
    page.evaluate("() => startTest(0)")
    page.wait_for_function("() => (document.querySelector('.page.active')||{}).id === 'p-test'")


def test_resuming_a_test_already_under_way_is_not_blocked(open_exam):
    # นาฬิกาเดินไปแล้ว กั้นไว้ก็เสียเวลาเท่ากัน และคำตอบที่ทำไปแล้วปลอดภัยกว่า
    # ถ้าได้ทำจนจบแล้วเข้าคิว มากกว่าถูกทิ้งค้างไว้
    page = open_exam()
    _setup(page)
    page.evaluate("""() => {
        window.__healthResponse = 'throw';
        sessions[0].status = 'in_progress';
    }""")
    page.evaluate("() => continueTest(0)")
    assert page.evaluate("() => (document.querySelector('.page.active')||{}).id") == "p-test"


# ── หน้าขอบคุณต้องไม่โกหก ───────────────────────────────────────


def test_the_thank_you_page_says_the_results_went_out_only_when_they_did(open_exam):
    page = open_exam()
    _setup(page)
    page.evaluate("() => { localStorage.removeItem('hma_answer_queue'); nav('p-thankyou'); }")
    assert "ส่งให้ทีม HR" in page.inner_text("#ty-note")
    assert page.inner_text("#ty-badge") == "✓"


def test_the_thank_you_page_admits_when_answers_are_still_stuck(open_exam):
    page = open_exam()
    _setup(page)
    page.evaluate("""() => {
        localStorage.setItem('hma_answer_queue', JSON.stringify([
            { submission: { testCode:'TESTSET', sitting:'s1', answers:[0] }, at: 1 }]));
        nav('p-thankyou');
    }""")
    note = page.inner_text("#ty-note")
    assert "ส่งให้ทีม HR" not in note, "ยังบอกว่าส่งแล้วทั้งที่ยังไม่ได้ส่ง"
    assert "อย่าเพิ่งปิดหน้านี้" in note
    assert "ยังไม่หายไปไหน" in note, "ต้องบอกด้วยว่าคำตอบยังอยู่ ไม่ได้หาย"
    assert page.inner_text("#ty-title") == "ยังส่งคำตอบไม่สำเร็จ"


def test_the_thank_you_page_updates_itself_once_the_queue_clears(open_exam):
    page = open_exam()
    _setup(page)
    page.evaluate("""() => {
        localStorage.setItem('hma_answer_queue', JSON.stringify([
            { submission: { testCode:'TESTSET', sitting:'s1', answers:[0] }, at: 1 }]));
        nav('p-thankyou');
    }""")
    assert page.inner_text("#ty-title") == "ยังส่งคำตอบไม่สำเร็จ"
    page.evaluate("() => flushAnswerQueue()")
    page.wait_for_function("() => document.getElementById('ty-title').textContent.includes('ขอบคุณ')")
    assert "ส่งให้ทีม HR" in page.inner_text("#ty-note")


# ── ผลที่ยังไม่ได้ตรวจ ไม่ใช่ผลสอบ ──────────────────────────────
#
# เมื่อตรวจคะแนนที่เซิร์ฟเวอร์ หน้าเว็บไม่รู้คะแนน เซสชันที่ทำเสร็จแล้วแต่ผลยังไม่กลับมา
# เคยถูกแสดงเป็นแถวผลสอบ ทำให้ HR เห็น "null/100" — ผลที่ไม่เคยมี กลับอ่านเหมือนมี


def _finish_without_a_score(page):
    """ทำข้อสอบจนจบโดยที่เซิร์ฟเวอร์ยังไม่ได้ส่งคะแนนกลับมา"""
    shown = _setup(page)
    page.evaluate("() => { window.__nextResponse = { ok:false, status:503, body:{} }; }")
    _answer(page, [0] * len(shown))
    page.wait_for_function("() => sessions[0].status === 'completed'")


def test_a_finished_test_with_no_score_yet_is_not_shown_as_a_result(open_exam):
    page = open_exam()
    _finish_without_a_score(page)
    rows = page.evaluate("() => getAllRows().map(r => ({ test: r.test, score: r.score }))")
    assert all(r["score"] is not None for r in rows), f"มีแถวที่คะแนนว่างหลุดมา: {rows}"


def test_the_candidate_still_appears_in_the_hr_list_without_a_score(open_exam):
    # ไม่แสดงเป็นผลสอบ ไม่ได้แปลว่าให้หายไปทั้งคน — นั่นคือปัญหาที่เรากำลังแก้
    page = open_exam()
    _finish_without_a_score(page)
    profile = page.evaluate("""() => {
        const key = applicantKey(applicant);
        const live = { candidate_key: key };
        // เรียกผ่านทางเดียวกับที่หน้าผู้ดูแลใช้
        renderCandidates();
        const rows = [...document.querySelectorAll('#a-cand-tbody tr')].map(r => r.textContent);
        return rows.filter(t => t.includes('cand@example.com')).length;
    }""")
    assert profile >= 1, "ผู้สมัครหายไปจากรายชื่อฝั่ง HR"


def test_a_scored_test_still_shows_as_a_result(open_exam):
    # กันไม่ให้ตัวกรองข้างบนกวาดผลจริงทิ้งไปด้วย
    page = open_exam()
    shown = _setup(page)
    page.evaluate("() => { window.SCORING_ENDPOINT = ''; }")   # ตรวจคะแนนในเครื่องเหมือนเดิม
    _answer(page, [0] * len(shown))
    page.wait_for_function("() => sessions[0].status === 'completed'")
    rows = page.evaluate("() => getAllRows().filter(r => r.test === 'TESTSET')")
    assert len(rows) == 1 and rows[0]["score"] is not None


# ── หน้าต่างต้องอยู่เหนือแถบเมนูของผู้ดูแล ───────────────────────


def test_a_modal_sits_above_the_admin_sidebar(open_exam):
    # แถบเมนูเป็น z-index 71 ส่วนหน้าต่างเคยเป็น 50 เปิดผลสอบขณะเมนูเปิดอยู่
    # แล้วเมนูจะทับหน้าต่างไว้
    page = open_exam()
    page.set_viewport_size({"width": 1440, "height": 900})
    on_top = page.evaluate("""() => {
        // แถบเมนูอยู่ในหน้าผู้ดูแล ถ้าไม่เปิดหน้านั้นก่อน มันจะกว้างเป็นศูนย์
        // แล้วเทสต์จะผ่านโดยไม่ได้วัดอะไรเลย
        nav('p-admin');
        toggleAdminSidebar(true);
        openModal('mod-indiv-pdf');
        const sb = document.getElementById('adm-sidebar').getBoundingClientRect();
        if (sb.width < 100) return 'แถบเมนูไม่ได้เปิดจริง';
        const el = document.elementFromPoint(sb.x + sb.width / 2, sb.y + sb.height / 2);
        return el && el.closest('#adm-sidebar') ? 'เมนู' : 'หน้าต่าง';
    }""")
    assert on_top == "หน้าต่าง", f"แถบเมนูยังทับหน้าต่างอยู่ ({on_top})"


def test_the_score_dashboard_says_why_it_cannot_open_yet(open_exam):
    # "ไม่มีข้อมูล" เฉย ๆ ทำให้ดูเหมือนปุ่มเสีย
    page = open_exam()
    _setup(page)
    page.evaluate("() => adminOpenScoreDash('nobody@example.com')")
    msg = page.inner_text("#toast")
    assert "ยังมาไม่ถึง" in msg and "รอสักครู่" in msg



def test_the_hr_row_shows_no_score_badge_while_the_result_is_still_coming(open_exam):
    # โปรไฟล์ผู้สมัครเคยหยิบ s.score มาใส่ทั้งที่ยังเป็นค่าว่าง ทำให้แถวขึ้น "null"
    page = open_exam()
    _finish_without_a_score(page)
    row = page.evaluate("""() => {
        nav('p-admin');
        renderCandidates();
        const tr = [...document.querySelectorAll('#a-cand-tbody tr')]
            .find(r => r.textContent.includes('cand@example.com'));
        return tr ? tr.textContent : null;
    }""")
    assert row is not None, "ผู้สมัครหายไปจากรายชื่อ"
    assert "null" not in row and "undefined" not in row, f"แถวโชว์คะแนนที่ยังไม่มี: {row}"


def test_a_result_already_recorded_is_not_wiped_by_the_sitting_in_flight(open_exam):
    """ผลที่ตรวจแล้วต้องไม่ถูกเซสชันที่ยังไม่ได้คะแนนทับหายไป

    renderCandidates() รวมโปรไฟล์ที่เก็บไว้กับเซสชันปัจจุบันด้วยการ spread ทับกัน
    ถ้าเซสชันปัจจุบันใส่คะแนนเป็นค่าว่างลงไป คะแนนจริงที่เคยตรวจแล้วจะถูกทับหาย
    — HR จะเห็นผู้สมัครที่เคยมีผล กลายเป็นไม่มีผล
    """
    page = open_exam(exam_records=[{
        "datetime": "3/8/2569 10:00:00", "_ts": 1785000000000,
        "candidate_key": "cand@example.com", "name": "ผู้สมัคร ทดสอบ",
        "email": "cand@example.com", "phone": "", "age": "", "experience": "",
        "position": "Engineer", "attempt": 1, "attempt_label": "ครั้งที่ 1",
        "_complete": True, "TESTSET_score": 88, "TESTSET_outcome": "P",
    }])
    _finish_without_a_score(page)
    row = page.evaluate("""() => {
        nav('p-admin');
        renderCandidates();
        const tr = [...document.querySelectorAll('#a-cand-tbody tr')]
            .find(r => r.textContent.includes('cand@example.com'));
        return tr ? tr.textContent.replace(/\s+/g, ' ') : null;
    }""")
    assert row is not None, "ผู้สมัครหายไปจากรายชื่อ"
    assert "TESTSET 88" in row, f"คะแนนที่ตรวจแล้วถูกทับหายไป: {row}"
