import json
import pathlib
import socket
import subprocess
import sys
import time

import pytest
from patchright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent   # โฟลเดอร์ files/
PORT = 8791
BASE = f"http://127.0.0.1:{PORT}"


def _port_open(port):
    with socket.socket() as s:
        s.settimeout(0.2)
        return s.connect_ex(("127.0.0.1", port)) == 0


@pytest.fixture(scope="session")
def server():
    """เสิร์ฟโฟลเดอร์ files/ ถ้ามีเซิร์ฟเวอร์รันอยู่แล้วก็ใช้ตัวนั้น"""
    if _port_open(PORT):
        yield BASE
        return
    proc = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(PORT)],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(50):
        if _port_open(PORT):
            break
        time.sleep(0.1)
    else:
        proc.terminate()
        raise RuntimeError(f"http.server ไม่ขึ้นที่พอร์ต {PORT}")
    yield BASE
    proc.terminate()
    proc.wait(timeout=5)


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


# หน้าแดชบอร์ดคะแนนเรียก Chart.js จาก CDN ถ้าเครื่องที่รันเทสต์ออกเน็ตไม่ได้
# renderResults() จะพังที่ "Chart is not defined" แล้วเทสต์ที่ไม่เกี่ยวกับกราฟเลย
# ก็พังตามไปด้วย จึงจ่ายตัวแทนขนาดเล็กให้แทน เทสต์ในไฟล์นี้ตรวจ "โครงหน้า"
# ไม่ได้ตรวจว่ากราฟวาดออกมาหน้าตาถูกไหม — ส่วนนั้นต้องดูด้วยตาบนของจริง
_CHART_STUB = """window.Chart = function (ctx) {
  const c = ctx.canvas;
  const fit = function () {
    const e = c.parentElement;
    if (!e) return;
    const cs = getComputedStyle(e);
    const w = e.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
    c.style.width = w + 'px'; c.style.height = w + 'px'; c.width = w; c.height = w;
  };
  fit();
  window.addEventListener('resize', fit);
  this.destroy = function () { window.removeEventListener('resize', fit); };
};"""


def _stub_cdn(route):
    """Chart.js ได้ตัวแทน ส่วนไลบรารีอื่นได้ไฟล์ว่าง — หน้าเว็บรับมือกับการที่
    ไลบรารี PDF/Excel ไม่มาอยู่แล้ว (ขึ้น toast บอก) จึงไม่ต้องปลอมให้"""
    body = _CHART_STUB if "chart.umd.js" in route.request.url else ""
    route.fulfill(content_type="application/javascript", body=body)


@pytest.fixture
def open_exam(browser, server):
    """เปิด index.html (ระบบสอบ) โดย seed localStorage ก่อนสคริปต์ของหน้าจะรัน"""
    contexts = []

    def _open(exam_records=None, result_snapshots=None):
        ctx = browser.new_context()
        ctx.route("**/cdnjs.cloudflare.com/**", _stub_cdn)
        contexts.append(ctx)
        for key, value in (("hma_exam_records", exam_records),
                           ("hma_result_snapshots", result_snapshots)):
            if value is None:
                continue
            payload = json.dumps(json.dumps(value))
            # ใส่ค่าเฉพาะตอนยังว่าง — add_init_script ยิงซ้ำทุก navigation
            # ถ้า setItem ตรง ๆ การ reload จะล้างสิ่งที่หน้าเว็บเพิ่งเขียนไป
            ctx.add_init_script(
                f"if (!localStorage.getItem('{key}')) localStorage.setItem('{key}', {payload})")
        page = ctx.new_page()
        # patchright ใช้ isolated world เป็นค่าเริ่มต้น
        # ซึ่งมองไม่เห็น function ที่ประกาศไว้ใน <script> ของหน้า
        _orig_evaluate = page.evaluate
        page.evaluate = lambda expr, arg=None: _orig_evaluate(expr, arg, isolated_context=False)
        page.goto(f"{server}/index.html")
        page.wait_for_function("typeof submitReg !== 'undefined'")
        return page

    yield _open
    for ctx in contexts:
        ctx.close()


def exam_record(**over):
    """record ผลสอบขั้นต่ำที่ผ่าน guard ของ renderer ทุกตัว (รูปแบบใหม่)"""
    base = {
        "datetime": "3/8/2569 10:00:00", "_ts": 1785000000000,
        "candidate_key": "somchai@example.com",
        "name": "สมชาย ทดสอบ", "email": "somchai@example.com",
        "phone": "0812345678", "age": 28, "experience": 3,
        "position": "ช่างเทคนิค", "attempt": 1, "attempt_label": "ครั้งที่ 1",
        "_complete": True,
    }
    base.update(over)
    return base


def legacy_exam_record(**over):
    """record รูปแบบเก่าที่ยังใช้เลขบัตรเป็น key — ใช้ทดสอบ read-compat

    ไม่มี email เพราะ candKey() ให้ email ชนะ national_id เสมอเมื่อมีทั้งคู่
    (ตั้งใจ — record เก่าที่รู้ email แล้วควรรวมกับ identity ใหม่ทันที) ฟิกซ์เจอร์นี้
    จำลอง record ที่ยังไม่รู้ email เลย ซึ่งเป็นเคสเดียวที่ fallback ไป national_id จริง ๆ
    """
    base = exam_record()
    base.pop("candidate_key")
    base.pop("email")
    base["national_id"] = "1234567890123"
    base.update(over)
    return base


def legacy_exam_record_with_email(**over):
    """รูปทรงจริงของ record ก่อน migration (ต่างจาก legacy_exam_record() ด้านบน ซึ่งตัด
    email ออกโดยตั้งใจเพื่อทดสอบ fallback ไป national_id แยกเป็นกรณีเดียว) —
    record เก่าจริง ๆ มีทั้ง national_id (ยังไม่ได้ลบตอน migrate) และ email
    (เก็บไว้ตั้งแต่แรกสำหรับติดต่อผู้สมัคร) แต่ไม่มี candidate_key เลย

    ภายใต้ลำดับ fallback ปัจจุบันของ candKey() (candidate_key || email || national_id
    || nid) record แบบนี้จะถูก key ด้วยอีเมลเสมอ — ตรงข้ามกับ result_snapshot รุ่นเก่าที่
    ไม่เคยเก็บ email เลย (มีแค่ nid) จึงถูก key ด้วยเลขบัตรแทน คนเดียวกันจึงมี key ต่างกัน
    คนละคอลเลกชัน นี่คือช่องโหว่ที่การลบ (deleteApplicantData/bulkDeleteCandidates)
    ต้องกวาดให้ครบทั้งสอง key ไม่งั้น snapshot จะรอดจากการลบ
    """
    base = exam_record()
    base.pop("candidate_key")
    base["national_id"] = "1234567890123"
    base.update(over)
    return base
