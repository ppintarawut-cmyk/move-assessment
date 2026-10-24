import json

from conftest import exam_record, legacy_exam_record, legacy_exam_record_with_email

def test_exam_page_opens_on_landing(open_exam):
    page = open_exam()
    assert page.locator("#p-landing").is_visible()


def test_seeded_records_reach_the_page(open_exam):
    page = open_exam(exam_records=[exam_record()])
    count = page.evaluate(
        "() => JSON.parse(localStorage.getItem('hma_exam_records') || '[]').length")
    assert count == 1


def test_cand_key_prefers_the_new_field(open_exam):
    page = open_exam()
    assert page.evaluate(
        "() => candKey({candidate_key:'a@b.com', email:'zzz@b.com'})") == "a@b.com"


def test_cand_key_lowercases_the_email_fallback(open_exam):
    page = open_exam()
    assert page.evaluate("() => candKey({email:'Somchai@Example.COM'})") == "somchai@example.com"


def test_cand_key_falls_back_to_legacy_exam_record_field(open_exam):
    page = open_exam()
    assert page.evaluate("() => candKey({national_id:'1234567890123'})") == "1234567890123"


def test_cand_key_falls_back_to_legacy_snapshot_field(open_exam):
    page = open_exam()
    assert page.evaluate("() => candKey({nid:'1234567890123'})") == "1234567890123"


def test_cand_key_returns_empty_string_when_nothing_identifies_the_row(open_exam):
    page = open_exam()
    assert page.evaluate("() => candKey({})") == ""


def test_legacy_records_still_group_into_candidates(open_exam):
    page = open_exam(exam_records=[legacy_exam_record()])
    keys = page.evaluate("() => getCandidateProfiles().map(p => p.candidate_key)")
    assert keys == ["1234567890123"]


def test_deleting_a_legacy_candidate_removes_both_the_exam_record_and_the_snapshot(open_exam):
    """F1 regression (PDPA): a real pre-migration candidate is keyed by *email* in
    hma_exam_records (which carries both national_id and email) but keyed by
    *national_id* in hma_result_snapshots (which never carried email at all).
    Deleting by the exam-record key alone must not leave the snapshot — which holds
    the candidate's name, position, experience and per-section scores — behind.
    """
    legacy_rec = legacy_exam_record_with_email()
    legacy_snap = {
        # No candidate_key, no email — the real shape of a pre-migration snapshot.
        "nid": legacy_rec["national_id"],
        "name": legacy_rec["name"],
        "pos": legacy_rec["position"],
        "exp": legacy_rec["experience"],
        "datetime": legacy_rec["datetime"],
        "sessions": [],
    }
    page = open_exam(exam_records=[legacy_rec], result_snapshots=[legacy_snap])
    page.on("dialog", lambda dialog: dialog.accept())

    # Grant delete rights the way the guard checks it (admin login itself is
    # cloud-only and out of reach in this headless test), then render the real
    # "Candidates" table so its actual 🗑 delete button exists in the DOM.
    page.evaluate("() => { currentAdmin = { role: 'superadmin' }; nav('p-candidates'); }")

    # F12: click the rendered 🗑 button itself instead of hand-building an
    # equivalent rowKey object in JS. renderCandidatesPage() (producer) encodes
    # the onclick's rowKey and deleteApplicantData() (consumer) decodes it — if
    # the two ever disagree on the field name, hand-building the object here
    # would still pass while the real button silently deletes nothing (exactly
    # the failure mode the brief called out). Clicking exercises both sides.
    page.locator('#cand-tbody button[title="ลบผู้สมัครนี้"]').click()

    remaining_recs = page.evaluate(
        "() => JSON.parse(localStorage.getItem('hma_exam_records') || '[]').length")
    remaining_snaps = page.evaluate(
        "() => JSON.parse(localStorage.getItem('hma_result_snapshots') || '[]').length")
    assert remaining_recs == 0
    assert remaining_snaps == 0


def _legacy_snapshot_for(legacy_rec, **over):
    """Real shape of a pre-migration result_snapshot: keyed by national ID only —
    no candidate_key, no email at all (see legacy_exam_record_with_email's docstring
    for why the two collections end up keyed differently for the same person)."""
    snap = {
        "nid": legacy_rec["national_id"],
        "name": legacy_rec["name"],
        "pos": legacy_rec["position"],
        "exp": legacy_rec["experience"],
        "datetime": legacy_rec["datetime"],
        "sessions": [],
    }
    snap.update(over)
    return snap


def test_admin_score_dashboard_reaches_a_legacy_candidates_snapshot(open_exam):
    """F9 regression: adminOpenScoreDash's real caller (the "📊 แดชบอร์ดคะแนน" button)
    passes candKey(indivExportData.rows[0]) — an exam-record-derived key, which for a
    pre-migration candidate is their *email*. The snapshot itself is keyed by
    *national ID*. Comparing the two directly finds nothing, so HR sees "ยังไม่มี
    ข้อมูลแดชบอร์ดคะแนน" for every legacy candidate — a regression from before this
    migration, when both sides were national IDs.
    """
    legacy_rec = legacy_exam_record_with_email()
    legacy_snap = _legacy_snapshot_for(legacy_rec)
    page = open_exam(exam_records=[legacy_rec], result_snapshots=[legacy_snap])

    # The exact key the real caller passes: an exam-record-derived candKey.
    exam_key = page.evaluate(
        "() => candKey(JSON.parse(localStorage.getItem('hma_exam_records'))[0])")
    assert exam_key == legacy_rec["email"]

    # เดิมเช็คผ่าน adminHasScoreDash() ด้วย แต่แอปไม่เคยเรียกฟังก์ชันนั้นเลย
    # (ถูกลบทิ้งแล้ว) — adminOpenScoreDash คือเส้นทางจริงและกวาด alias แบบเดียวกัน
    page.evaluate(f"() => adminOpenScoreDash({json.dumps(exam_key)})")
    reached_name = page.evaluate("() => applicant && applicant.name")
    assert reached_name == legacy_rec["name"]


def test_completing_an_attempt_updates_a_legacy_unsealed_snapshot_instead_of_duplicating_it(open_exam):
    """F10 regression: saveResultSnapshot() matches an existing unsealed snapshot by
    candKey(x) === candKey(snap) — but candKey(snap) is always the email
    (applicantKey), while a pre-migration candidate's still-unsealed snapshot is
    keyed by national ID. Finishing that in-flight attempt now appends a second
    snapshot row instead of updating the first one.
    """
    legacy_rec = legacy_exam_record_with_email()
    legacy_snap = _legacy_snapshot_for(legacy_rec)   # unsealed: no `_sealed` field
    page = open_exam(exam_records=[legacy_rec], result_snapshots=[legacy_snap])

    # Candidate resumes and completes their attempt: applicant carries the same
    # email/national ID as the legacy records, one session finishes, and
    # saveResultSnapshot() runs — the same call doSubmit() makes after a completed
    # session (index.html's setTimeout(saveResultSnapshot, 220)).
    page.evaluate(f"""
        () => {{
            applicant = {{
                name: {json.dumps(legacy_rec["name"])},
                pos: {json.dumps(legacy_rec["position"])},
                nid: {json.dumps(legacy_rec["national_id"])},
                email: {json.dumps(legacy_rec["email"])},
                exp: {legacy_rec["experience"]},
            }};
            sessions = [{{
                test: {{ code:'IQ', name:'IQ', nameTH:'ไอคิว', passing:60, mins:20 }},
                status:'completed', score:80, outcome:'P', raw:8, maxP:10,
                sections:{{}}, percentile:null, remainSecs:100, violations:[],
            }}];
            saveResultSnapshot();
        }}
    """)

    snaps = page.evaluate(
        "() => JSON.parse(localStorage.getItem('hma_result_snapshots') || '[]')")
    assert len(snaps) == 1


def test_candidate_email_cannot_break_out_of_the_rendered_row_controls(open_exam):
    """Security regression: the registration email validator
    (/^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$/, index.html) rejects only whitespace and `@` —
    `'`, `(`, `)` and `-` all pass. That value becomes candidate_key/email and flows
    into candKey(p), which the Candidates table interpolates into its row controls.

    Before the fix, renderCandidatesPage() built those controls as
    onclick="toggleCandSelect('${esc(nid)}')" / onclick="deleteApplicantData('${...}')".
    esc() HTML-entity-escapes `'` to `&#39;` — correct for HTML *text*, but an
    attribute's value is entity-decoded by the HTML parser *before* the browser
    compiles it as JavaScript, so `&#39;` becomes a real `'` that closes the JS
    string literal early. encodeURIComponent (used for the delete/pdf button's
    rowKey) doesn't escape `'`, `(` or `)` either, so it has the same hole.

    This payload (`'`, `(`, `)`, `-`) turns that hole into arbitrary script
    execution in the HR admin's own session — the session with delete rights and
    the Firestore connection — the moment the row is rendered and its control is
    used, no candidate cooperation required beyond registering with this email.
    """
    payload = "a')-(window.__xss_fired=1)-('b@x.co"
    rec = exam_record(candidate_key=payload, email=payload, name="เพย์โหลด ทดสอบ")
    page = open_exam(exam_records=[rec])
    page.on("dialog", lambda dialog: dialog.accept())
    page.evaluate("() => { currentAdmin = { role: 'superadmin' }; nav('p-candidates'); }")

    # Rendering the row alone must not run attacker script.
    assert page.evaluate("() => window.__xss_fired") is None

    # The checkbox control must still work — and select the FULL payload as the
    # candidate key, not a truncated fragment (a sign the string was reinterpreted
    # as JS rather than passed through as one opaque value).
    page.locator('#cand-tbody .cand-check').click()
    assert page.evaluate("() => [...candSelected]") == [payload]
    assert page.evaluate("() => window.__xss_fired") is None

    # The delete control must still work and remove exactly this candidate.
    page.locator('#cand-tbody button[title="ลบผู้สมัครนี้"]').click()
    remaining = page.evaluate(
        "() => JSON.parse(localStorage.getItem('hma_exam_records') || '[]').length")
    assert remaining == 0
    assert page.evaluate("() => window.__xss_fired") is None


def _fill_registration(page, email="Somchai@Example.com"):
    page.evaluate("() => nav('p-register')")
    page.fill("#r-fn", "สมชาย")
    page.fill("#r-ln", "ทดสอบ")
    page.fill("#r-age", "28")
    page.select_option("#reg-pos", index=1)
    page.fill("#r-email", email)
    page.check("#pdpa-consent")


def test_submitting_registration_starts_the_session_without_a_second_click(open_exam):
    """ขั้นยืนยันอีเมลถูกเอาออกแล้ว (ข้อความเดิมบอกว่าจะส่งผลไปทางอีเมล ซึ่งระบบไม่เคยทำ)
    ลงทะเบียนเสร็จต้องเข้าหน้าชุดสอบทันที ไม่มีให้กดซ้ำ
    """
    page = open_exam()
    _fill_registration(page)
    page.click("#reg-btn")
    page.wait_for_selector("#p-dash.active")
    assert page.evaluate("() => applicant.email") == "Somchai@Example.com"
    assert page.evaluate("() => pendingReg") is None
    assert page.evaluate("() => sessions.length") > 0


def test_confirming_the_email_starts_the_exam(open_exam):
    page = open_exam()
    _fill_registration(page)
    page.click("#reg-btn")
    page.wait_for_selector("#p-dash.active")
    assert page.evaluate("() => candKey({email: applicant.email})") == "somchai@example.com"


def test_the_email_actually_typed_is_the_one_used(open_exam):
    """อีเมลเป็นตัวระบุตัวตนของผู้สมัคร (กุญแจของผลสอบ, seed ของการสับข้อ,
    และสิ่งที่ HR ใช้จับคู่ผลสอบ) — ต้องใช้ค่าที่พิมพ์ล่าสุดเสมอ
    """
    page = open_exam()
    _fill_registration(page)
    page.fill("#r-email", "other@example.com")
    page.click("#reg-btn")
    page.wait_for_selector("#p-dash.active")
    assert page.evaluate("() => applicant.email") == "other@example.com"
    # และเป็นตัวที่กำหนดลำดับการสับข้อด้วย
    seed_key = page.evaluate("() => candKey(applicant)")
    assert seed_key == "other@example.com"


def test_reg_btn_keeps_its_english_label_while_the_confirm_box_is_open(open_exam):
    """F1 regression: submitReg() used to reset #reg-btn's label with the hardcoded
    Thai literal 'ยืนยันและเริ่มทดสอบ →' rather than the current-language I18N string.
    Under the old (pre-confirm-box) flow this was invisible — nav('p-dash') fired
    synchronously right after, so the reset never painted. Now the confirm box sits
    on top of the still-visible #p-register for as long as the candidate takes to
    decide, so an English-mode candidate durably sees #reg-btn revert to Thai while
    every other label on the page, including the new confirm box, reads English.
    """
    page = open_exam()
    page.click("#lang-fab")   # drive the language switch the way the app itself does
    _fill_registration(page)
    page.click("#reg-btn")
    page.wait_for_selector("#p-dash.active")
    # ขั้นยืนยันอีเมลถูกเอาออกแล้ว ป้ายปุ่มจึงไม่ถูกเห็นระหว่างรอ — แต่ค่าที่ตั้งกลับ
    # ต้องยังเป็นภาษาปัจจุบัน ไม่ใช่ข้อความไทยที่ฝังไว้ตายตัว มิฉะนั้นผู้สมัคร
    # ภาษาอังกฤษที่ย้อนกลับมาหน้านี้จะเห็นปุ่มเป็นภาษาไทย
    expected = page.evaluate("() => I18N.reg_btn.en")
    assert page.inner_text("#reg-btn") == expected


def test_leaving_registration_clears_pending_form_data(open_exam):
    """F2 regression: กด '← กลับ' แล้วข้อมูลฟอร์มที่ค้างอยู่ต้องถูกล้าง
    ไม่งั้นการกลับมาลงทะเบียนครั้งถัดไปจะหยิบของเก่าที่ถูกทิ้งไปแล้วมาใช้
    """
    page = open_exam()
    _fill_registration(page)
    page.evaluate("() => { pendingReg = { name:'ทิ้งไว้', email:'stale@example.com' }; }")

    page.click("#p-register .topbar button")   # '← กลับ' → nav('p-landing')
    page.wait_for_selector("#p-landing.active")
    assert page.evaluate("() => pendingReg") is None

    page.evaluate("() => nav('p-register')")
    assert page.evaluate("() => pendingReg") is None


# ── Task 4: stop collecting the national ID; fix consent to match reality ──

COLLECTED_TH = ["ชื่อ-นามสกุล", "อีเมล", "เบอร์โทรศัพท์", "อายุ",
                "ประสบการณ์", "ตำแหน่งที่สมัคร", "ผลการทดสอบ"]


def test_registration_form_has_no_national_id_field(open_exam):
    page = open_exam()
    page.evaluate("() => nav('p-register')")
    assert page.locator("#r-nid").count() == 0


def test_consent_text_no_longer_mentions_the_national_id(open_exam):
    page = open_exam()
    for lang in ("th", "en"):
        text = page.evaluate(f"() => I18N.pdpa_consent.{lang}")
        assert "เลขประจำตัวประชาชน" not in text
        assert "national ID" not in text


COLLECTED_EN = ["full name", "email", "phone number", "age",
                "work experience", "position", "test results"]


def test_consent_text_lists_every_field_the_form_collects(open_exam):
    page = open_exam()
    text = page.evaluate("() => I18N.pdpa_consent.th")
    for field in COLLECTED_TH:
        assert field in text, f"consent ไม่ได้ประกาศว่าเก็บ {field}"


def test_english_consent_text_lists_the_same_fields(open_exam):
    page = open_exam()
    text = page.evaluate("() => I18N.pdpa_consent.en").lower()
    for field in COLLECTED_EN:
        assert field in text, f"English consent is missing {field}"


def test_pdpa_notice_links_to_the_privacy_page(open_exam):
    page = open_exam()
    page.evaluate("() => nav('p-register')")
    href = page.get_attribute("#p-register a[href='privacy.html']", "href")
    assert href == "privacy.html"


def test_privacy_page_loads_and_lists_the_collected_fields(open_exam, server):
    page = open_exam()
    page.goto(f"{server}/privacy.html")
    body = page.inner_text("body")
    for field in COLLECTED_TH:
        assert field in body


# ── F3 (task-4-report review): the consent text and privacy.html must also
# disclose that the system logs when a candidate switches away from the exam
# window/tab or attempts to copy text — a timestamped per-session log that is
# stored, exported and shown to HR (index.html: triggerCheat/examLeaveCount/
# buildExamRecord's *_leaves columns) but wasn't mentioned in either notice.


def test_consent_text_discloses_exam_window_leave_and_copy_paste_tracking(open_exam):
    page = open_exam()
    th = page.evaluate("() => I18N.pdpa_consent.th")
    en = page.evaluate("() => I18N.pdpa_consent.en").lower()
    assert "ออกจากหน้าต่างแบบทดสอบ" in th
    assert "คัดลอก" in th
    assert "switch away from the exam window" in en
    assert "copy" in en


def test_privacy_page_lists_exam_window_leave_and_copy_paste_tracking(open_exam, server):
    page = open_exam()
    page.goto(f"{server}/privacy.html")
    body = page.inner_text("body")
    assert "ออกจากหน้าต่างแบบทดสอบ" in body
    assert "คัดลอก" in body


# ── F6 (task-4-report review): privacy.html must be bilingual, following the
# same th/en toggle + 'hma_lang' localStorage mechanism index.html uses, so
# an English-using candidate who accepts the English consent (which links
# here) doesn't land on a Thai-only page, and the two pages stay in sync.


def test_privacy_page_has_an_english_toggle(open_exam, server):
    page = open_exam()
    page.goto(f"{server}/privacy.html")
    page.click("#lang-btn")
    body = page.inner_text("body")
    assert "Privacy Notice" in body
    assert "Data We Collect" in body
    assert "นโยบายความเป็นส่วนตัว" not in body


def test_privacy_page_follows_the_language_the_candidate_already_chose(open_exam, server):
    page = open_exam()
    page.click("#lang-fab")   # switch to English the way the app itself does
    page.goto(f"{server}/privacy.html")
    body = page.inner_text("body")
    assert "Privacy Notice" in body


def test_candidate_table_shows_the_email_not_a_national_id(open_exam):
    # F5 (task-4-report review): exam_record() has no national_id key at all, so
    # "1234567890123" could never appear here regardless of what the code does —
    # use legacy_exam_record_with_email() instead, which actually carries that
    # digit string under national_id (alongside the email candKey() prefers),
    # so this assertion has real teeth.
    page = open_exam(exam_records=[legacy_exam_record_with_email()])
    page.evaluate("() => { renderCandidates(); }")
    assert "somchai@example.com" in page.inner_text("#a-cand-tbody")
    assert "1234567890123" not in page.inner_text("#a-cand-tbody")


# ── Item A: the randomization seed must not collapse once nid is gone ──
#
# getRandomizedQs() used to seed its shuffle from applicant.nid. Once the
# national-ID field is removed, applicant.nid is undefined for every
# candidate, so every seed collapses to the same 'x' fallback and every
# candidate would see the questions in the identical order. The seed must
# key off applicantKey(applicant) (email, always lowercased) instead.


def test_two_candidates_with_different_emails_get_different_question_orders(open_exam):
    page = open_exam()
    order_a = page.evaluate("""
        () => {
            applicant = { name: 'A', email: 'alice@example.com' };
            return getRandomizedQs({ test: { code: 'IQ' } }).map(q => q.q);
        }
    """)
    order_b = page.evaluate("""
        () => {
            applicant = { name: 'B', email: 'bob@example.com' };
            return getRandomizedQs({ test: { code: 'IQ' } }).map(q => q.q);
        }
    """)
    assert len(order_a) > 1
    assert order_a != order_b


def test_same_candidate_gets_the_same_question_order_across_a_resume(open_exam):
    page = open_exam()
    _fill_registration(page, email="Somchai@Example.com")
    page.click("#reg-btn")
    page.wait_for_selector("#p-dash.active")

    # Start the IQ test directly (skip the intro screen) so a randomized order
    # is generated and persisted via the real window.openTest() wrapper.
    #
    # เฉลยไม่อยู่ในหน้าเว็บแล้ว หน้าเว็บจึงตรวจคะแนนเองไม่ได้ และ openTest() จะไม่ยอม
    # เริ่มสอบถ้าไม่มีทางให้คะแนนเลย — ตั้งให้อยู่ในสภาพใช้งานจริง (มีระบบตรวจคะแนน
    # และโหลดคลังมาแล้ว) เทสต์นี้ตรวจเรื่องลำดับการสับข้อ ไม่ใช่เรื่องการ์ดตัวนั้น
    page.evaluate("""
        () => {
            window.SCORING_ENDPOINT = 'https://scoring.example.com';
            _cloudBankLoaded = true;
            curSess = sessions.findIndex(s => s.test.code === 'IQ');
            sessions[curSess].status = 'in_progress';
            window.openTest();
        }
    """)
    order_before = page.evaluate("() => sessions[curSess]._randomizedQs.map(q => q.q)")
    assert len(order_before) > 1

    # Simulate a refresh: reload the page (in-memory state is gone, but the
    # session was persisted to localStorage by window.openTest()'s wrapper)
    # and resume through the real resumeSession() path.
    page.reload()
    page.wait_for_function("typeof submitReg !== 'undefined'")
    page.evaluate("""() => {
        window.SCORING_ENDPOINT = 'https://scoring.example.com';
        _cloudBankLoaded = true;
    }""")
    page.evaluate("() => resumeSession()")
    order_after = page.evaluate("() => sessions[curSess]._randomizedQs.map(q => q.q)")

    assert order_after == order_before


# ── F1 (task-4-report review): a session persisted by the OLD (pre-Task-4)
# build carries an applicant with BOTH .nid (what the old build seeded the
# shuffle from) and .email (what the current build seeds from instead). If
# such a session survives a deploy and the candidate resumes it within the
# 24h window, getRandomizedQs() must still reconstruct the SAME question
# order the candidate was actually looking at — not a different one keyed
# by email — or their positional answers get silently graded against the
# wrong questions.


def test_resuming_a_pre_task4_session_reconstructs_the_shuffle_it_was_sat_under(open_exam):
    page = open_exam()

    # What the OLD build's seed formula ("${applicant.nid || 'x'}|${code}")
    # produced for this candidate — computed directly via the same
    # randomizeQuestions() helper the app itself uses, independent of
    # whatever the current seed formula under test does.
    expected_order = page.evaluate("""
        () => randomizeQuestions(
            ALL_QUESTIONS['IQ'] || [],
            '1234567890123|IQ',
            (TESTS.find(t => t.code === 'IQ') || {}).shuffleOpts !== false
        ).map(q => q.q)
    """)
    assert len(expected_order) > 1

    # Simulate a session persisted by the OLD build: applicant carries both
    # .nid and .email, exactly the shape described in the F1 finding.
    page.evaluate("""
        () => {
            localStorage.setItem('hma_active_session', JSON.stringify({
                applicant: {
                    name: 'สมชาย ทดสอบ', pos: 'ช่างเทคนิค', exp: 3,
                    nid: '1234567890123', email: 'somchai@example.com',
                },
                sessions: [{
                    test: { code:'IQ', name:'IQ', nameTH:'ไอคิว', mins:20, passing:60 },
                    status: 'in_progress', score:null, outcome:null, raw:null, maxP:null,
                    answers: [], answersRandom: [0, 1, null],
                    remainSecs: 1000, startedAt: Date.now(),
                }],
                curSess: 0, curQ: 0, savedAt: Date.now(),
            }));
        }
    """)

    # เหตุผลเดียวกับเทสต์ด้านบน — resumeSession() ลงไปถึง openTest()
    page.evaluate("""() => {
        window.SCORING_ENDPOINT = 'https://scoring.example.com';
        _cloudBankLoaded = true;
    }""")
    page.evaluate("() => resumeSession()")
    actual_order = page.evaluate("() => sessions[curSess]._randomizedQs.map(q => q.q)")

    assert actual_order == expected_order


# ── F2 (task-4-report review): adminOpenScoreDash() must not regress the HR
# candidates table. The applicant object it reconstructs must have no live
# .email (applicantKey(applicant) must stay '') so renderCandidates()'s live
# profile never masquerades as the real candidate and MERGES OVER their
# stored row (blank phone/age, a spurious "กำลังทำอยู่" live dot, attempts
# reset to 1) when HR opens the score dashboard and clicks back.
#
# Note: reconstructing `applicant` without `.email` also means
# renderCandidates()'s liveProfile (candidate_key: applicantKey(applicant),
# i.e. '') never matches the real stored row by candKey() either — so a
# SEPARATE, distinct row for the same candidate still gets appended (with a
# live dot on *that* row). That row-level duplication predates Task 4
# entirely (adminOpenScoreDash's applicant object never carried .email even
# before Task 4 — this candidate_key computation in renderCandidates() has
# always been unable to identify it), so it is out of scope for F1-F6 and is
# only noted, not asserted on, below. F2's specific regression was the real
# row silently losing its own data, which this test does assert on.


def test_admin_score_dashboard_does_not_corrupt_the_hr_candidates_table(open_exam):
    rec = exam_record()   # phone "0812345678", age 28, candidate_key/email "somchai@example.com"
    snap = {
        "candidate_key": rec["candidate_key"],
        "name": rec["name"], "pos": rec["position"], "exp": rec["experience"],
        "datetime": rec["datetime"],
        # At least one completed session — an empty list makes adminOpenScoreDash()
        # reconstruct `sessions = []`, and renderCandidates()'s liveProfile requires
        # `sessions.length` to be non-zero, so an empty fixture here would never be
        # able to exercise (or catch a regression in) the live-profile merge at all.
        "sessions": [{
            "code": "IQ", "name": "Cognitive Ability", "nameTH": "ความสามารถทางสติปัญญา",
            "passing": 70, "mins": 25, "score": 80, "outcome": "P", "raw": 8, "maxP": 10,
            "sections": {}, "percentile": None, "remainSecs": 100, "leaves": 0,
        }],
    }
    page = open_exam(exam_records=[rec], result_snapshots=[snap])
    page.evaluate("() => { currentAdmin = { role: 'superadmin' }; nav('p-admin'); }")

    key = page.evaluate(
        "() => candKey(JSON.parse(localStorage.getItem('hma_exam_records'))[0])")
    assert key == rec["candidate_key"]

    # HR opens the score dashboard for this candidate, then clicks "back" —
    # the exact real flow (adminOpenScoreDash → backFromResults → nav('p-admin')
    # → renderAdmin → renderCandidates).
    page.evaluate(f"() => adminOpenScoreDash({json.dumps(key)})")
    page.evaluate("() => backFromResults()")

    # Find the real candidate's own row by its email (present only on the real
    # stored row — the reconstructed applicant, and any phantom row derived
    # from it, never carries .email at all).
    real_row = page.locator("#a-cand-tbody tr", has_text="somchai@example.com")
    assert real_row.count() == 1, "the real stored candidate row must not itself be duplicated"

    row_text = real_row.inner_text()
    assert "0812345678" in row_text, "phone must still show — not blanked by the live-profile merge"
    assert "28" in row_text, "age must still show — not blanked by the live-profile merge"
    assert real_row.locator('[title="กำลังทำอยู่"]').count() == 0, \
        "the real candidate's row must not be marked as a live in-progress session"


# ── Item C: export column headers must not lie about what they contain ──
#
# buildExportData() (feeding both the CSV and the XLSX exports) used to label
# its identity column "เลขประชาชน" (national ID) even though the value is
# candKey(r) — the candidate's email for every post-migration record. A PII
# column whose header lies is exactly what this task exists to fix.


def test_export_data_does_not_label_the_identity_column_a_national_id(open_exam):
    page = open_exam(exam_records=[exam_record()])
    row = page.evaluate("() => buildExportData()[0]")
    assert "เลขประชาชน" not in row


def test_export_data_identity_column_holds_the_candidate_key(open_exam):
    # F5 (task-4-report review): exam_record() carries no national_id key, so
    # "1234567890123" could never show up in the exported row regardless of
    # implementation — legacy_exam_record_with_email() actually carries that
    # digit string (under national_id, alongside the email candKey() prefers),
    # giving the "not in values" half of this assertion something real to catch.
    page = open_exam(exam_records=[legacy_exam_record_with_email()])
    row = page.evaluate("() => buildExportData()[0]")
    # Whatever the column is called now, it must actually hold the candidate's
    # identity key (the email, for a post-migration record) rather than a
    # 13-digit national ID.
    values = list(row.values())
    assert "somchai@example.com" in values
    assert "1234567890123" not in values


# ── Task 5: แผงยืนยันตัวตนบนหน้าแรก ──
#
# ผู้สมัครไม่กล้ากดลิงก์เพราะระบบพิสูจน์ตัวเองไม่ได้ แผงนี้ต้องอยู่บนหน้าแรก
# ก่อนกรอกข้อมูลใด ๆ และต้องพาไปหา "คนจริง" ที่โทรถามได้


def test_trust_panel_is_visible_before_any_form(open_exam):
    page = open_exam()
    assert page.locator("#trust-panel").is_visible()
    panel = page.inner_text("#trust-panel")
    assert "Hino Motors Asia" in panel
    assert "privacy.html" in page.inner_html("#trust-panel")


def test_trust_panel_warns_while_the_hr_contact_is_a_placeholder(open_exam):
    page = open_exam()
    # ตั้งค่า placeholder เองแทนที่จะพึ่งค่าที่ ship มา — ไม่งั้นเทสต์ตัวนี้จะแดง
    # ทันทีที่ Task 8 Step 1 ใส่ข้อมูล HR จริง
    page.evaluate("() => { HR_CONTACT.name = 'ยังไม่ระบุ'; renderTrustPanel(); }")
    assert page.locator("#hr-contact-warning").is_visible()


def test_warning_disappears_once_real_contact_details_are_set(open_exam):
    page = open_exam()
    page.evaluate("""() => {
        HR_CONTACT.name  = 'ภัทราวุธ ย.';
        HR_CONTACT.email = 'pattarawut_y@hinomotorsasia.com';
        renderTrustPanel();
    }""")
    assert page.locator("#hr-contact-warning").count() == 0
    assert "pattarawut_y@hinomotorsasia.com" in page.inner_text("#trust-panel")


def test_trust_panel_escapes_contact_values(open_exam):
    # HR_CONTACT ถูกกรอกโดยคน ไม่ใช่ผู้สมัคร แต่ renderTrustPanel สร้าง HTML ด้วย
    # string template — ถ้าไม่ escape ชื่อที่มี < > จะพัง markup
    page = open_exam()
    page.evaluate("""() => {
        HR_CONTACT.name  = '<img src=x onerror="window.__trust_xss=1">';
        HR_CONTACT.email = 'hr@hinomotorsasia.com';
        renderTrustPanel();
    }""")
    assert page.evaluate("() => window.__trust_xss") is None
    assert "<img" in page.inner_text("#trust-panel")


def test_privacy_page_shares_the_same_contact_details(open_exam, server):
    # แผงบนหน้าแรกกับหน้านโยบายต้องบอกผู้รับผิดชอบคนเดียวกัน ไม่งั้นผู้สมัคร
    # ที่โทรตามเบอร์ในนโยบายจะไปไม่ถึงคนเดียวกับที่หน้าแรกอ้าง
    index_contact = open_exam().evaluate(
        "() => [HR_CONTACT.name, HR_CONTACT.email]")
    page = open_exam()
    page.goto(f"{server}/privacy.html")
    privacy_contact = page.evaluate(
        "() => [HR_CONTACT.name, HR_CONTACT.email]")
    assert index_contact == privacy_contact


def test_trust_panel_follows_the_language_toggle(open_exam):
    # แผงนี้สร้างด้วย JS ไม่ใช่ data-i18n — applyLang() จึงไม่แตะให้เอง
    # ถ้าไม่ hook ไว้ ผู้สมัครที่กด EN จะเห็นแผงยืนยันตัวตนค้างเป็นภาษาไทย
    page = open_exam()
    assert "แบบทดสอบนี้เป็นของ" in page.inner_text("#trust-panel")
    page.click("#lang-fab")
    assert "This assessment belongs to" in page.inner_text("#trust-panel")
    page.click("#lang-fab")
    assert "แบบทดสอบนี้เป็นของ" in page.inner_text("#trust-panel")


# ── code-review fixes 1-3: the "don't ship with placeholder contacts" gate ──


def test_blank_contact_values_count_as_placeholders(open_exam):
    # เดิมเช็คแค่คำขึ้นต้น 'ยังไม่ระบุ' — ลบค่าทิ้งเป็นค่าว่างแล้ว guard เงียบ
    # แล้วหน้าแรกขึ้นให้ผู้สมัครโดยไม่มีชื่อผู้รับผิดชอบเลย
    page = open_exam()
    page.evaluate("""() => {
        HR_CONTACT.name = ''; HR_CONTACT.email = '   ';
        renderTrustPanel();
    }""")
    assert page.locator("#hr-contact-warning").is_visible()


def test_privacy_page_warns_while_the_hr_contact_is_a_placeholder(open_exam, server):
    # หน้านโยบายระบุ "ผู้ควบคุมข้อมูล" ตามกฎหมาย — ปล่อยให้ขึ้น placeholder
    # เป็นชื่อผู้รับผิดชอบไม่ได้
    # ตั้งค่า placeholder เองแทนที่จะพึ่งค่าที่ ship มา (เหมือนฝั่ง index.html)
    page = open_exam()
    page.goto(f"{server}/privacy.html")
    page.evaluate("() => { HR_CONTACT.name = 'ยังไม่ระบุ'; applyLang(); }")
    assert page.locator("#hr-contact-warning").is_visible()


def test_privacy_page_warns_when_a_contact_value_is_blank(open_exam, server):
    page = open_exam()
    page.goto(f"{server}/privacy.html")
    page.evaluate("() => { HR_CONTACT.email = '  '; applyLang(); }")
    assert page.locator("#hr-contact-warning").is_visible()


def test_shipped_contact_details_are_real(open_exam, server):
    # ค่าที่ ship จริงต้องผ่าน guard ทั้งสองหน้า — เทสต์นี้คือสิ่งที่กันไม่ให้
    # deploy ทั้งที่ยังไม่ได้ใส่ข้อมูล
    page = open_exam()
    assert page.evaluate("() => hrContactIsPlaceholder()") is False
    assert page.locator("#hr-contact-warning").count() == 0
    page.goto(f"{server}/privacy.html")
    assert page.evaluate("() => hrContactIsPlaceholder()") is False
    assert page.locator("#hr-contact-warning").count() == 0


def test_privacy_page_warning_clears_once_real_contact_details_are_set(open_exam, server):
    page = open_exam()
    page.goto(f"{server}/privacy.html")
    page.evaluate("""() => {
        HR_CONTACT.name  = 'ภัทราวุธ ย.';
        HR_CONTACT.email = 'pattarawut_y@hinomotorsasia.com';
        applyLang();
    }""")
    assert page.locator("#hr-contact-warning").count() == 0
    assert "pattarawut_y@hinomotorsasia.com" in page.inner_text("#hr-contact")


def test_privacy_page_escapes_contact_values(open_exam, server):
    page = open_exam()
    page.goto(f"{server}/privacy.html")
    page.evaluate("""() => {
        HR_CONTACT.name  = '<img src=x onerror="window.__priv_xss=1">';
        HR_CONTACT.email = 'hr@hinomotorsasia.com';
        applyLang();
    }""")
    assert page.evaluate("() => window.__priv_xss") is None
    assert "<img" in page.inner_text("#hr-contact")


def test_privacy_page_mailto_href_cannot_break_out_of_the_attribute(open_exam, server):
    # href="mailto:${...}" เป็น attribute ที่คั่นด้วย " — อีเมลที่มี " จะปิด attribute
    # แล้วส่วนที่เหลือถูก parse เป็น markup
    page = open_exam()
    page.goto(f"{server}/privacy.html")
    page.evaluate("""() => {
        HR_CONTACT.name  = 'HR';
        HR_CONTACT.email = 'a" onmouseover="window.__priv_href=1" x="';
        applyLang();
    }""")
    link = page.locator("#hr-contact a")
    assert link.get_attribute("onmouseover") is None
    assert link.get_attribute("href").startswith("mailto:")


# ── code-review follow-ups: correctness ──


def test_cand_key_normalizes_a_numeric_legacy_id(open_exam):
    # legacy record ที่ national_id มาเป็นตัวเลข (re-import / แก้มือใน Firestore)
    # ต้องได้ string ไม่งั้น Set ของ string จะ has() ไม่เจอ แล้วเลือก/ลบไม่ได้
    page = open_exam()
    assert page.evaluate("() => candKey({national_id: 1234567890123})") == "1234567890123"
    assert page.evaluate("() => typeof candKey({nid: 1234567890123})") == "string"


def test_cand_key_aliases_normalize_a_numeric_legacy_id(open_exam):
    aliases = open_exam().evaluate(
        "() => [...candKeyAliases({national_id: 1234567890123})]")
    assert aliases == ["1234567890123"]


def test_deleting_a_candidate_with_a_numeric_legacy_id_removes_the_record(open_exam):
    # ผลลัพธ์จริงของ candKey() ที่ไม่ normalize: resolveCandidateAliases เทียบ
    # candKey(record) (number) กับ key ที่มาจาก JSON (string) → ไม่ตรง → alias ว่าง
    # → filter ไม่ตัดอะไรเลย → กด "ลบข้อมูลทั้งหมด" แล้ว record ยังอยู่ ทั้งที่ UI บอกว่าลบแล้ว
    page = open_exam(exam_records=[legacy_exam_record(national_id=1234567890123, email="")])
    aliases = page.evaluate("() => [...resolveCandidateAliases('1234567890123')]")
    assert aliases == ["1234567890123"], \
        "record ที่ national_id เป็นตัวเลขต้อง resolve alias เจอ ไม่งั้นลบไม่โดน"


def test_candidate_row_avatar_survives_a_blank_name(open_exam):
    # charCodeAt(0) ของ string ว่างคือ NaN → colors[NaN] undefined
    # → style="background:undefined" (avatar ไม่มีสี)
    page = open_exam(exam_records=[exam_record(name="")])
    page.evaluate("() => { renderCandidates(); }")
    avatar = page.locator("#a-cand-tbody .avatar").first
    assert "undefined" not in (avatar.get_attribute("style") or "")


def test_pending_reg_is_declared_before_its_users(open_exam):
    # nav() (บรรทัด ~1712) และ submitReg() แตะ pendingReg แต่ let ประกาศทีหลัง
    # ยังไม่ระเบิดเพราะไม่มี top-level call ก่อนถึงบรรทัดนั้น — แต่เป็นกับดัก
    page = open_exam()
    src = page.evaluate("() => document.documentElement.outerHTML")
    decl = src.index("let pendingReg")
    assert decl < src.index("function nav(id)"), \
        "let pendingReg ต้องประกาศก่อน nav() ไม่งั้น init ที่เพิ่มเข้ามาทีหลังจะเจอ TDZ"
