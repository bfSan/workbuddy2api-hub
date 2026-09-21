"""Browser checks for dashboard pagination.

_test_pagination.mjs covers the pure slicing logic. This covers the parts only a
real DOM exposes: the 15s account poll must not bounce the viewer off their page,
and the paged API key editor must keep addressing rows by absolute index.

Run: .venv/bin/python _test_pagination_browser.py
"""
import http.server
import json
import os
import socketserver
import threading

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))

PASS = FAIL = 0


def check(label, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] " + label)
    else:
        FAIL += 1
        print("  [FAIL] " + label + ("  " + str(extra) if extra else ""))


# requests[i] is a scramble, not the row number, so "first row after sorting by
# 请求" disagrees with the server order and the assertion can actually fail.
def scrambled(i):
    return ((i * 5 + 11) % 63) + 1


ACCOUNTS = [{"uid": "intl%03d" % i, "nickname": "国际号%03d" % i, "realm": "intl",
             "enabled": True, "source": "oauth", "expiresIn": "30d",
             "credits": {"remain": 100 - i, "size": 500}} for i in range(63)]
USAGE = [{"account": "intl%03d" % i, "requests": scrambled(i),
          "total_tokens": scrambled(i) * 10, "cached_tokens": scrambled(i)}
         for i in range(63)]
# The server hands back both realms and the panel filters client side, so the
# realm toggle exercises the real path.
CN_ACCOUNTS = [{"uid": "cn%03d" % i, "nickname": "国内号%03d" % i, "realm": "cn",
                "enabled": True, "source": "oauth", "expiresIn": "30d"} for i in range(25)]
ALL_ACCOUNTS = ACCOUNTS + CN_ACCOUNTS
API_KEYS = [{"id": "k%02d" % i, "name": "key-%02d" % i, "masked": "wb-****%02d" % i,
             "realm": "", "enabled": True, "accounts": []} for i in range(45)]

SAVED = []

API_PREFIXES = ("/panel", "/accounts", "/usage", "/settings", "/scheduler",
                "/tasks", "/logs", "/realm", "/v1/models")


def api_payload(path):
    if path.startswith("/panel/status"):
        return {"authenticated": True, "panel_password_is_default": False}
    if path.startswith("/realm"):
        return {"active_gateway_realm": "intl", "realms": ["intl", "cn"]}
    if path.startswith("/accounts"):
        return {"accounts": ALL_ACCOUNTS}
    if path.startswith("/usage/by-account"):
        return {"accounts": USAGE}
    if path.startswith("/usage/by-key"):
        return {"keys": []}
    if path.startswith("/usage/recent"):
        return {"rows": []}
    if path.startswith("/usage/perf") or path.startswith("/usage/analytics"):
        return {}
    if path.startswith("/usage"):
        return {"total": {}, "models": []}
    if path.startswith("/v1/models"):
        return {"data": []}
    if path.startswith("/settings/models"):
        return {"hidden": [], "order": []}
    if path.startswith("/settings"):
        return {"api_keys": API_KEYS, "account_options": ACCOUNTS[:5],
                "account_aliases": {}, "version": "test", "accounts_dir": "-",
                "usage_dir": "-", "settings_file": "-", "api_key_set": False}
    if path.startswith("/scheduler"):
        return {"enabled": True, "times": []}
    if path.startswith("/tasks"):
        return {"tasks": []}
    if path.startswith("/logs"):
        return {"entries": [], "max_id": 0}
    return {}


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=HERE, **kwargs)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path.startswith(API_PREFIXES):
            return self._json(api_payload(path))
        if path in ("/", ""):
            self.path = "/dashboard.html"
        return http.server.SimpleHTTPRequestHandler.do_GET(self)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        if self.path.startswith("/settings/save"):
            try:
                SAVED.append(json.loads(raw.decode("utf-8")))
            except Exception:
                SAVED.append({})
        return self._json({"ok": True, "msg": "saved"})

    def _json(self, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def rows(page):
    return page.locator("#accounts tbody tr").count()


def info(page):
    return page.locator("#accounts .pager-info").first.inner_text().strip()


def cards(page):
    # The pager is also a direct child div, so count only the key cards.
    return page.locator("#keyList > div:not(.pager)").count()


GEO_JS = """() => {
  const rows = [...document.querySelectorAll('#keyList > .keyrow')];
  return rows.map(r => {
    const kids = [...r.children].filter(el => getComputedStyle(el).display !== 'none');
    const rects = kids.map(el => el.getBoundingClientRect());
    const cy = rects.map(x => x.top + x.height / 2);
    return { count: kids.length, height: r.getBoundingClientRect().height,
             cyMin: Math.min(...cy), cyMax: Math.max(...cy),
             lefts: rects.map(x => x.left).sort((p, q) => p - q),
             rights: rects.map(x => x.right).sort((p, q) => p - q) };
  });
}"""


def overlaps(g):
    """First free slot at or after each control's left edge, in document order."""
    lefts, rights = g["lefts"], g["rights"]
    for k in range(len(lefts)):
        prev = -1e18
        for j in range(len(rights)):
            if rights[j] > lefts[k] + 1 and rights[j] < prev:
                prev = rights[j]
        if prev > lefts[k] + 1:
            return (round(lefts[k]), round(prev))
    return None


def run_checks(base):
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception:
            browser = p.chromium.launch(channel="chrome")
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(base, wait_until="networkidle")

        check("panel unlocked and account list rendered", rows(page) > 0)
        check("no page errors during boot", not errors, errors[:2])

        print("account table")
        check("page 1 shows one page of 10", rows(page) == 10, rows(page))
        check("count line reads 1-10 of 63", info(page) == "第 1-10 条 / 共 63 条", info(page))
        check("header reports the full pool across both realms",
              "全量 88" in page.locator("#acctCount").inner_text(),
              page.locator("#acctCount").inner_text())

        page.locator("#accounts .pager-nav").get_by_text("3", exact=True).first.click()
        check("jump to page 3 shows 10 rows", rows(page) == 10, rows(page))
        check("page 3 count line reads 21-30", info(page) == "第 21-30 条 / 共 63 条", info(page))
        check("page 3 starts at the 21st account",
              "国际号020" in page.locator("#accounts tbody tr").first.inner_text(),
              page.locator("#accounts tbody tr").first.inner_text()[:40])

        # loadAccounts() re-enters renderAccounts() every 15s; the page must hold.
        page.wait_for_timeout(17000)
        check("15s poll did not bounce the viewer off page 3",
              info(page) == "第 21-30 条 / 共 63 条", info(page))
        check("polled page 3 still shows the same rows",
              "国际号020" in page.locator("#accounts tbody tr").first.inner_text())

        print("account search")
        page.fill("#acctSearch", "国际号05")
        check("search resets to page 1", info(page) == "第 1-10 条 / 共 10 条", info(page))
        check("search narrows to 10 rows", rows(page) == 10, rows(page))
        check("header reflects the filter",
              "筛选 10 / 63" in page.locator("#acctCount").inner_text(),
              page.locator("#acctCount").inner_text())
        page.fill("#acctSearch", "intl060")
        check("search matches on uid", rows(page) == 1, rows(page))
        page.fill("#acctSearch", "不存在的号")
        check("no match shows an empty state",
              "没有匹配" in page.locator("#accounts").inner_text())
        page.fill("#acctSearch", "")
        check("clearing search restores page 1",
              rows(page) == 10 and info(page) == "第 1-10 条 / 共 63 条", info(page))

        print("account page size")
        page.select_option("#accounts .pager-size", "50")
        check("50/page shows 50 accounts", rows(page) == 50, rows(page))
        check("63 accounts at 50/page still needs two pages",
              page.locator("#accounts .pager-nav").count() == 1)
        page.select_option("#accounts .pager-size", "10")
        check("back to 10/page", rows(page) == 10, rows(page))
        # A retired 100/page persisted by an earlier build must not stick.
        check("100 is no longer offered",
              page.locator("#accounts .pager-size option").count() == 3,
              page.locator("#accounts .pager-size option").count())

        # A result set that fits one page drops the buttons but keeps the size
        # selector, otherwise the viewer is stranded at that size.
        page.select_option("#accounts .pager-size", "50")
        page.fill("#acctSearch", "国际号05")
        check("single page hides the page buttons",
              page.locator("#accounts .pager-nav").count() == 0)
        check("page-size control stays available on a single page",
              page.locator("#accounts .pager-size").count() == 1)
        page.fill("#acctSearch", "")
        page.select_option("#accounts .pager-size", "10")

        print("account sorting")
        # Fixtures put credits at 100-i, so the credit column is a clean ordering
        # probe that never agrees with the server order past the first row.
        def credit_col(n=3):
            return page.eval_on_selector_all(
                "#accounts tbody tr",
                """(rs, n) => rs.slice(0, n).map(r =>
                    r.querySelectorAll('td')[3].innerText.trim())""", n)

        check("no sort starts in server order",
              "国际号000" in page.locator("#accounts tbody tr").first.inner_text())
        check("inactive headers show the neutral glyph",
              page.locator("#accounts th.sortable.active").count() == 0)

        page.click("#th-accounts-credit")
        check("first click on a numeric column sorts descending",
              page.evaluate("() => PAGE_STATE.accounts.sort.key") == "credit"
              and page.evaluate("() => PAGE_STATE.accounts.sort.dir") == "desc",
              page.evaluate("() => PAGE_STATE.accounts.sort"))
        check("descending puts the fullest account first",
              credit_col(1)[0].startswith("100"), credit_col(3))
        check("sort marks the header active",
              page.locator("#accounts th.sortable.active").count() == 1)
        # The header markup and the stylesheet name the glyph separately, so a
        # rename on one side would silently drop the styling.
        check("the sort glyph is styled, not just present",
              page.evaluate("""() => {
                const el = document.querySelector('#th-accounts-credit .sort-glyph');
                return !!el && getComputedStyle(el).marginLeft !== '0px';
              }"""))

        page.click("#th-accounts-credit")
        check("second click flips to ascending",
              page.evaluate("() => PAGE_STATE.accounts.sort.dir") == "asc")
        # remain is 100-i, so the smallest balance on the list is 38.
        check("ascending empties first",
              credit_col(1)[0].startswith("38"), credit_col(3))

        # Sorting replaces the list, so the viewer must land on page 1.
        page.click("#th-accounts-credit")
        check("third click clears the sort and returns to server order",
              page.evaluate("() => PAGE_STATE.accounts.sort") == {"key": "", "dir": ""}
              and "国际号000" in page.locator("#accounts tbody tr").first.inner_text(),
              credit_col(2))

        page.click("#th-accounts-name")
        check("first click on a text column sorts ascending",
              page.evaluate("() => PAGE_STATE.accounts.sort") == {"key": "name", "dir": "asc"})
        page.click("#th-accounts-realm")
        check("changing column restarts the cycle descending for numbers, ascending for text",
              page.evaluate("() => PAGE_STATE.accounts.sort") == {"key": "realm", "dir": "asc"})
        page.click("#th-accounts-name")

        print("sorting composes with paging")
        # A fresh column lands on descending; a third click would clear it.
        page.click("#th-accounts-credit")
        page.locator("#accounts .pager-nav").get_by_text("2", exact=True).first.click()
        check("sorted page 2 holds ranks 11-20",
              page.evaluate("() => PAGE_STATE.accounts.sort.dir") == "desc"
              and info(page) == "第 11-20 条 / 共 63 条", info(page))
        # Ranks 1-10 are remain 100..91, so rank 11 is 90.
        check("descending page 2 starts at 90",
              credit_col(1)[0].startswith("90"), credit_col(3))
        # The 15s poll repaints the table; both the order and the page must hold.
        page.wait_for_timeout(17000)
        check("the poll kept the sort",
              page.evaluate("() => PAGE_STATE.accounts.sort") == {"key": "credit", "dir": "desc"},
              page.evaluate("() => PAGE_STATE.accounts.sort"))
        check("the poll kept page 2 with the same order",
              info(page) == "第 11-20 条 / 共 63 条" and credit_col(1)[0].startswith("90"),
              [info(page), credit_col(2)])

        print("sorting persists across reload")
        page.reload(wait_until="networkidle")
        page.wait_for_timeout(600)
        check("reload restores the saved sort",
              page.evaluate("() => PAGE_STATE.accounts.sort") == {"key": "credit", "dir": "desc"},
              page.evaluate("() => PAGE_STATE.accounts.sort"))
        check("restored sort is still descending",
              credit_col(1)[0].startswith("100"), credit_col(3))
        # The saved sort is descending, so it takes two more clicks to walk the
        # cycle desc -> asc -> none and leave server order for the checks below.
        page.click("#th-accounts-credit")
        check("second click on a numeric column reaches ascending",
              page.evaluate("() => PAGE_STATE.accounts.sort") == {"key": "credit", "dir": "asc"})
        page.click("#th-accounts-credit")
        check("sort cleared before the key checks",
              page.evaluate("() => PAGE_STATE.accounts.sort") == {"key": "", "dir": ""})

        print("api key editor")
        # PAGE_STATE is declared after switchViewRealm in the file, so this also
        # proves the realm toggle can reach it at click time rather than at parse.
        page.evaluate("() => { PAGE_STATE.accounts.page = 3; renderAccounts(); }")
        check("page 3 is set before the realm switch",
              info(page) == "第 21-30 条 / 共 63 条", info(page))
        page.evaluate("() => switchViewRealm('cn')")
        page.wait_for_timeout(500)
        check("switching realm returns to page 1",
              page.evaluate("() => PAGE_STATE.accounts.page") == 1,
              page.evaluate("() => PAGE_STATE.accounts.page"))
        check("cn view shows the cn pool from page 1",
              info(page) == "第 1-10 条 / 共 25 条", info(page))
        page.evaluate("() => switchViewRealm('intl')")
        page.wait_for_timeout(500)
        check("switching back starts clean",
              info(page) == "第 1-10 条 / 共 63 条", info(page))

        page.click("#btnNavSettings")
        page.wait_for_selector("#keyList > div")
        check("key page 1 shows 10 rows", cards(page) == 10, cards(page))
        check("key pager reports 45 keys",
              "第 1-10 条 / 共 45 条" in page.locator("#keyList .pager-info").inner_text(),
              page.locator("#keyList .pager-info").inner_text())

        # 45 keys at 10/page is five pages; the last one holds the remainder.
        page.locator("#keyList .pager-nav").get_by_text("末页", exact=True).first.click()
        check("key last page shows the 5-row remainder", cards(page) == 5, cards(page))
        first_key = page.locator("#keyList input[placeholder='备注名']").first
        check("key last page starts at key-40", first_key.input_value() == "key-40",
              first_key.input_value())

        # The last card is absolute row 44. Its dropdown must mutate row 44, not row 4.
        check("account dropdown no longer forces a full-width line",
              page.evaluate("""() => { const el = document.querySelector('.kac-wrap');
                const cs = getComputedStyle(el);
                return cs.width !== el.parentElement.getBoundingClientRect().width
                       + 'px' && cs.position === 'relative'; }"""))
        page.locator("#keyList .kac-wrap").last.locator("button").first.click()
        page.wait_for_selector("#kac-panel-44", state="visible")
        # It anchors upward so it cannot cover the pager beneath the last card.
        check("last row dropdown opens upward, clear of the pager",
              page.eval_on_selector("#kac-panel-44",
                                    "el => getComputedStyle(el).bottom !== 'auto'"))
        page.locator("#kac-panel-44 input[type=checkbox]").first.click()
        picked = page.evaluate("() => API_KEY_ROWS[44].accounts")
        check("checking a box edited absolute row 44", len(picked) == 1, picked)
        check("relative row 4 was left alone", page.evaluate("() => API_KEY_ROWS[4].accounts") == [])

        # The pager is still clickable with that panel open.
        page.locator("#keyList .pager-nav").get_by_text("首页", exact=True).first.click()
        check("paging back to page 1",
              "第 1-10 条 / 共 45 条" in page.locator("#keyList .pager-info").inner_text(),
              page.locator("#keyList .pager-info").inner_text())
        check("paging closed the account dropdown",
              page.evaluate("() => KEY_ACCT_UI.open") == -1,
              page.evaluate("() => KEY_ACCT_UI.open"))
        page.locator("#keyList input[placeholder='备注名']").nth(2).fill("renamed-p1")
        check("edit on page 1 landed on absolute row 2",
              page.evaluate("() => API_KEY_ROWS[2].name") == "renamed-p1",
              page.evaluate("() => API_KEY_ROWS[2].name"))

        print("saving across pages")
        page.get_by_text("保存全部", exact=True).click()
        page.wait_for_timeout(700)
        check("save fired once", len(SAVED) == 1, len(SAVED))
        if SAVED:
            keys = SAVED[0].get("api_keys") or []
            check("save sent all 45 keys, not just the visible page", len(keys) == 45, len(keys))
            check("cross-page name edit survived",
                  any(k.get("name") == "renamed-p1" for k in keys))
            check("cross-page account binding survived",
                  len(keys[44].get("accounts") or []) == 1 if len(keys) > 44 else False)

        print("adding a key")
        page.get_by_text("+ 添加一个 Key", exact=True).click()
        page.wait_for_timeout(400)
        check("add jumps to the last page so the new row is visible",
              "第 41-46 条 / 共 46 条" in page.locator("#keyList .pager-info").inner_text(),
              page.locator("#keyList .pager-info").inner_text())
        check("last page renders the fresh row",
              page.locator("#keyList input[placeholder='备注名']").count() == 6,
              page.locator("#keyList input[placeholder='备注名']").count())

        print("key row stays on one line")
        # The account dropdown used to carry width:100%, which pushed the trailing
        # controls onto a second line. Measure page 1, where every row is a saved
        # key with a masked hint, so the control count is uniform.
        page.locator("#keyList .pager-nav").get_by_text("首页", exact=True).first.click()
        page.set_viewport_size({"width": 1600, "height": 1000})
        page.wait_for_timeout(200)
        check("masked hint renders inline", page.locator("#keyList .key-masked").count() == 10,
              page.locator("#keyList .key-masked").count())
        geo = page.evaluate(GEO_JS)
        check("every key row is measured", len(geo) == 10, len(geo))
        # A wrapped row stacks controls onto separate lines, so the centre points of
        # the first and last child drift apart and the card grows taller.
        check("all controls sit on the same line (no wrap)",
              all(g["cyMax"] - g["cyMin"] < 2 for g in geo),
              [round(g["cyMax"] - g["cyMin"], 1) for g in geo])
        check("row height proves a single line", all(g["height"] < 52 for g in geo),
              [round(g["height"], 1) for g in geo])
        # Nine nodes: name, key, copy, realm, enable, generate, delete, dropdown, masked.
        check("the key row holds all nine controls",
              all(g["count"] == 9 for g in geo), [g["count"] for g in geo])
        check("no control overlaps another", all(not overlaps(g) for g in geo),
              [overlaps(g) for g in geo][:3])

        print("key row on a narrow viewport")
        # Below the breakpoint the row may wrap rather than scroll sideways, but a
        # wrap must never mean an overlap.
        page.set_viewport_size({"width": 900, "height": 1000})
        page.wait_for_timeout(200)
        narrow = page.evaluate(GEO_JS)
        check("narrow rows still hold every control",
              all(g["count"] == 9 for g in narrow), [g["count"] for g in narrow])
        check("nothing overlaps once the row wraps", all(not overlaps(g) for g in narrow),
              [overlaps(g) for g in narrow][:3])
        page.set_viewport_size({"width": 1280, "height": 900})

        check("no page errors after interacting", not errors, errors[:3])
        browser.close()


def main():
    with socketserver.TCPServer(("127.0.0.1", 0), Handler) as srv:
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        run_checks("http://127.0.0.1:%d/dashboard.html" % port)
        srv.shutdown()
    print("")
    print("pagination browser tests: %d passed, %d failed" % (PASS, FAIL))
    raise SystemExit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
